#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ALLOWED_FEATURE_STATUSES = {
    "foreground_verified",
    "backend_only",
    "debug_preview",
    "offline_tool",
    "blocked_by_bug",
}
ALLOWED_PRODUCT_STATUSES = {"foreground_verified", "backend_only", "blocked_by_bug"}


def validate_product_status(payload: dict[str, object], *, repo_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if payload.get("schemaVersion") != "rag-ime.product-status.v1":
        errors.append("schemaVersion must be rag-ime.product-status.v1")
    product_status = str(payload.get("productStatus") or "")
    if product_status not in ALLOWED_PRODUCT_STATUSES:
        errors.append(f"unsupported productStatus: {product_status}")
    release_status = str(payload.get("releaseStatus") or "")
    if release_status not in {"ready", "blocked"}:
        errors.append(f"unsupported releaseStatus: {release_status}")
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        errors.append("blockers must be a list")
        blockers = []
    if release_status == "blocked" and not blockers:
        errors.append("blocked releaseStatus requires at least one blocker")
    features = payload.get("features")
    if not isinstance(features, dict) or not features:
        errors.append("features must be a non-empty object")
    else:
        for feature_id, status in features.items():
            if str(status) not in ALLOWED_FEATURE_STATUSES:
                errors.append(f"unsupported feature status for {feature_id}: {status}")
    evidence = payload.get("foregroundEvidence")
    if not isinstance(evidence, dict):
        errors.append("foregroundEvidence must be an object")
        evidence = {}
    strict_soak = evidence.get("strictSoakPassed") is True
    if product_status == "foreground_verified" and not strict_soak:
        errors.append("foreground_verified requires strictSoakPassed=true")
    if release_status == "ready" and (not strict_soak or blockers):
        errors.append("ready release requires a green strict soak and no blockers")
    if repo_root is not None:
        source_commit = str(payload.get("sourceCommit") or "")
        if not source_commit:
            errors.append("sourceCommit is required")
        elif subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        ).returncode != 0:
            errors.append(f"sourceCommit is not an ancestor of HEAD: {source_commit}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the machine-readable RAG-IME product status.")
    parser.add_argument("--status", default="docs/product-status.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status_path = Path(args.status).resolve()
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("product status must contain a JSON object")
    repo_root = status_path.parents[1]
    errors = validate_product_status(payload, repo_root=repo_root)
    report = {
        "schemaVersion": "rag-ime.product-status-check.v1",
        "ok": not errors,
        "statusPath": str(status_path),
        "productStatus": payload.get("productStatus"),
        "releaseStatus": payload.get("releaseStatus"),
        "blockerCount": len(payload.get("blockers") or []),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("OK" if report["ok"] else "FAILED")
        for error in errors:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
