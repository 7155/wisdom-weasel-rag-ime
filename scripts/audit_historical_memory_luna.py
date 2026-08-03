#!/usr/bin/env python3
"""Run one final independent Luna/max audit over a completed private catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.activity_timeline_evaluation import (
    load_luna_structured_run,
    run_luna_structured,
)
from rag_ime.historical_memory_catalog_audit import (
    build_historical_catalog_audit_packet,
    historical_catalog_audit_prompt,
    historical_catalog_audit_schema,
    validate_historical_catalog_audit,
)


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit every current Atom and active Book in a completed private candidate."
    )
    parser.add_argument("--candidate-db", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument("--timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--production-db", type=Path, default=DEFAULT_PRODUCTION_DB)
    parser.add_argument("--public-report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    candidate = args.candidate_db.expanduser().resolve(strict=True)
    production = args.production_db.expanduser().resolve(strict=False)
    if candidate == production:
        raise SystemExit("production SQLite cannot be a catalog audit candidate")
    private_root = args.private_dir.expanduser().resolve(strict=False)
    if private_root.is_relative_to(ROOT):
        raise SystemExit("--private-dir must be outside the Git worktree")
    if private_root.exists():
        if not private_root.is_dir() or stat.S_IMODE(private_root.stat().st_mode) & 0o077:
            raise SystemExit("existing --private-dir must be a mode-0700 directory")
    else:
        private_root.mkdir(parents=True, mode=0o700)
        private_root.chmod(0o700)

    preflight = _preflight(candidate)
    if int(preflight["pendingCandidateEvidenceCount"]) != 0:
        raise SystemExit("historical curation is incomplete; candidate Evidence remains")
    packet = build_historical_catalog_audit_packet(
        candidate,
        project=str(args.project),
    )
    prompt = historical_catalog_audit_prompt(packet)
    schema = historical_catalog_audit_schema()
    digest = str(packet["catalogDigest"])
    run = _run_or_resume_audit(
        prompt=prompt,
        schema=schema,
        artifact_base=private_root / f"catalog-audit-{digest[:16]}",
        timeout_seconds=float(args.timeout_seconds),
        codex_bin=str(args.codex_bin),
    )
    validated = validate_historical_catalog_audit(run.output, packet=packet)
    passed = (
        bool(validated["passed"])
        and preflight["quickCheck"] == "ok"
        and int(preflight["foreignKeyViolationCount"]) == 0
    )
    summary = {
        "schemaVersion": "rag-ime.historical-memory-catalog-audit-summary.v1",
        "passed": passed,
        "candidateOnly": True,
        "productionDatabaseOpened": False,
        "productionMutationPerformed": False,
        "model": run.model,
        "thinking": run.thinking,
        "elapsedSeconds": round(run.elapsed_seconds, 3),
        "promptSha256": run.prompt_sha256,
        "outputSha256": run.output_sha256,
        "preflight": preflight,
        "audit": validated,
    }
    _write_private_json(
        private_root / f"catalog-audit-{digest[:16]}-summary.json",
        summary,
    )
    if args.public_report is not None:
        _write_public_report(args.public_report.expanduser(), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if bool(summary["passed"]) else 1


def _preflight(path: Path) -> dict[str, object]:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30.0) as conn:
        integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        pending = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agent_memory_evidence
                WHERE status = 'active'
                  AND evidence_domain = 'personal_memory'
                  AND admission_state = 'candidate'
                """
            ).fetchone()[0]
        )
    return {
        "quickCheck": integrity,
        "foreignKeyViolationCount": foreign_keys,
        "pendingCandidateEvidenceCount": pending,
        "databaseSha256": _sha256_file(path),
    }


def _run_or_resume_audit(
    *,
    prompt: str,
    schema: dict[str, object],
    artifact_base: Path,
    timeout_seconds: float,
    codex_bin: str,
):
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    schema_sha256 = hashlib.sha256(
        json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    for attempt in range(1, 100):
        artifact_dir = (
            artifact_base
            if attempt == 1
            else artifact_base.with_name(f"{artifact_base.name}-attempt-{attempt:02d}")
        )
        if artifact_dir.exists():
            try:
                resumed = load_luna_structured_run(
                    artifact_dir,
                    phase="historical-catalog-audit",
                )
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if (
                resumed.prompt_sha256 == prompt_sha256
                and resumed.schema_sha256 == schema_sha256
            ):
                return resumed
            continue
        return run_luna_structured(
            prompt=prompt,
            schema=schema,
            artifact_dir=artifact_dir,
            phase="historical-catalog-audit",
            timeout_seconds=timeout_seconds,
            codex_bin=codex_bin,
        )
    raise RuntimeError("no available private catalog audit attempt directory")


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == encoded:
            return
        raise FileExistsError(path)
    path.write_text(encoded, encoding="utf-8")
    path.chmod(0o600)


def _write_public_report(path: Path, summary: dict[str, object]) -> None:
    audit = dict(summary.get("audit") or {})
    preflight = dict(summary.get("preflight") or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "# Historical Memory Final Catalog Audit",
                "",
                "- Scope: completed disposable candidate; production SQLite was not opened or modified.",
                f"- Luna/max elapsed seconds: `{summary.get('elapsedSeconds')}`.",
                f"- Atoms checked: `{audit.get('atomCount')}`; Books checked: `{audit.get('bookCount')}`.",
                f"- Evidence excerpts checked: `{audit.get('evidenceExcerptCount')}`.",
                f"- Findings: `{audit.get('findingCount')}`; by code: `{json.dumps(audit.get('findingCounts') or {}, sort_keys=True)}`.",
                f"- Protocol errors: `{audit.get('errorCount')}`.",
                f"- SQLite quick check: `{preflight.get('quickCheck')}`; foreign-key violations: `{preflight.get('foreignKeyViolationCount')}`.",
                f"- Result: `{'pass' if summary.get('passed') else 'needs repair'}`.",
                "",
                "Private source text, model output, database paths, and stable identifiers are excluded.",
                "",
            )
        ),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
