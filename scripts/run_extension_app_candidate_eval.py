#!/usr/bin/env python3
"""Validate and sandbox-test one source-isolated PAWOS Extension App candidate.

This command never installs an App.  It binds the App's exact manifest and Pi
Skill to the registered vertical suite, runs that suite in a fresh local
sandbox, and writes one privacy-safe success or failure receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.vertical_agent_harness import resolve_builtin_vertical_suite
from rag_ime.vertical_agent_sandbox import run_vertical_agent_self_test
from scripts.validate_extension_app import (
    ExtensionAppValidationError,
    validate_extension_app,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_sha256(root: Path) -> str:
    resolved_root = root.resolve(strict=True)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Extension App candidate tree may not contain symlinks")
        if not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("Extension App candidate file escapes its source root") from exc
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.name == ".DS_Store":
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _failure_class(error: BaseException) -> str:
    message = str(error).lower()
    if "bindingsha256" in message or "binding" in message:
        return "binding_digest_mismatch"
    if "skillsha256" in message or "skill" in message:
        return "skill_contract_invalid"
    if "suite" in message:
        return "suite_binding_invalid"
    return "source_contract_invalid"


def run_extension_app_candidate_eval(
    app_directory: str | Path,
    workspace_root: str | Path,
    *,
    quick_validate: str | None = None,
) -> dict[str, object]:
    requested = Path(app_directory).expanduser()
    source_tree_sha256 = ""
    try:
        if requested.is_symlink():
            raise ValueError("Extension App candidate root may not be a symlink")
        app_root = requested.resolve(strict=True)
        source_tree_sha256 = _tree_sha256(app_root)
        validation = validate_extension_app(
            app_root,
            quick_validate=quick_validate,
        )
    except (ExtensionAppValidationError, OSError, ValueError) as error:
        fingerprint = _sha256_bytes(
            f"{type(error).__name__}:{error}".encode("utf-8")
        )
        return {
            "schemaVersion": "pawos.extension-app-candidate-eval.v1",
            "status": "source_validation_failed",
            "candidate": {
                "slug": requested.name,
                "sourceTreeSha256": source_tree_sha256,
                "sourceTreeHashAvailable": bool(source_tree_sha256),
                "installActionPerformed": False,
            },
            "failure": {
                "errorType": type(error).__name__,
                "failureClass": _failure_class(error),
                "errorFingerprint": f"sha256:{fingerprint}",
            },
            "boundary": {
                "sandboxExecuted": False,
                "providerCalls": 0,
                "installActionPerformed": False,
                "foregroundAccepted": False,
            },
        }

    suite_info = validation["suite"]
    assert isinstance(suite_info, Mapping)
    suite_id = str(suite_info["suiteId"])
    suite_revision = str(suite_info["suiteRevision"])
    manifest = resolve_builtin_vertical_suite(suite_id, suite_revision)
    result = run_vertical_agent_self_test(manifest, workspace_root)
    eval_run = result["evalRun"]
    trace = result["trace"]
    sandbox_run = result["sandboxRun"]
    assert isinstance(eval_run, Mapping)
    assert isinstance(trace, Mapping)
    assert isinstance(sandbox_run, Mapping)
    app_manifest_path = app_root / "pawos-app.json"
    package_manifest_path = app_root / "pi-package" / "package.json"
    skill_path = (
        app_root
        / "pi-package"
        / "skills"
        / str(validation["skill"]["name"])
        / "SKILL.md"
    )
    suite_manifest_sha256 = _sha256_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {
        "schemaVersion": "pawos.extension-app-candidate-eval.v1",
        "status": "sandbox_verified",
        "candidate": {
            "appId": validation["appId"],
            "version": validation["version"],
            "packageId": validation["packageId"],
            "bindingSha256": validation["binding"]["bindingSha256"],
            "skillSha256": validation["binding"]["skillSha256"],
            "sourceTreeSha256": source_tree_sha256,
            "appManifestSha256": _sha256_bytes(app_manifest_path.read_bytes()),
            "packageManifestSha256": _sha256_bytes(package_manifest_path.read_bytes()),
            "skillFileSha256": _sha256_bytes(skill_path.read_bytes()),
            "installActionPerformed": False,
        },
        "suite": {
            "suiteId": suite_id,
            "suiteRevision": suite_revision,
            "suiteManifestSha256": suite_manifest_sha256,
            "fixtureCount": len(manifest["fixtures"]),
            "truthVisibleToProvider": False,
        },
        "result": {
            "importedDocumentCount": result["importedCount"],
            "retrievalHitCount": result["retrieval"]["hitCount"],
            "metrics": dict(eval_run["metrics"]),
            "providerCalls": result["providerCalls"],
            "productionWriteBlocked": result["productionWriteBlocked"],
            "traceStatus": trace["status"],
            "traceVerified": result["traceVerification"]["verified"],
        },
        "receipts": {
            "traceId": trace["traceId"],
            "evalRunId": eval_run["evalRunId"],
            "sandboxRunId": sandbox_run["sandboxRunId"],
            "workspaceFingerprint": result["workspaceFingerprint"],
        },
        "boundary": {
            "fixtureOnly": True,
            "realBusinessData": False,
            "providerCalls": 0,
            "installActionPerformed": False,
            "foregroundAccepted": False,
            "claimAllowed": "Source-isolated App/Package/Skill binding and one deterministic offline sandbox contract were verified.",
            "claimForbidden": "Production Text-to-SQL accuracy, installed App acceptance, foreground behavior, or real business-data correctness.",
        },
    }


def _write_json_atomic(path: str | Path, value: Mapping[str, object]) -> None:
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-directory", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quick-validate")
    args = parser.parse_args(argv)
    report = run_extension_app_candidate_eval(
        args.app_directory,
        args.workspace_root,
        quick_validate=args.quick_validate,
    )
    _write_json_atomic(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "sandbox_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
