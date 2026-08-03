#!/usr/bin/env python3
"""Apply an independent catalog audit to a disposable memory candidate."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.historical_memory_catalog_audit import (
    quarantine_historical_catalog_audit_atoms,
)


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Conservatively quarantine every Atom rejected by an independent "
            "catalog audit. Source Evidence is never deleted."
        )
    )
    parser.add_argument("--candidate-db", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument("--production-db", type=Path, default=DEFAULT_PRODUCTION_DB)
    parser.add_argument("--preverified-schema", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    candidate = args.candidate_db.expanduser().resolve(strict=True)
    production = args.production_db.expanduser().resolve(strict=False)
    if candidate == production:
        raise SystemExit("production SQLite cannot be a catalog repair target")
    audit_path = args.audit_output.expanduser().resolve(strict=True)
    audit_output = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit_output, dict):
        raise SystemExit("audit output must be one JSON object")

    report_path = args.private_report.expanduser().resolve(strict=False)
    if report_path.is_relative_to(ROOT):
        raise SystemExit("--private-report must be outside the Git worktree")
    if report_path.exists():
        if stat.S_IMODE(report_path.stat().st_mode) & 0o077:
            raise SystemExit("existing --private-report must be mode 0600")
        raise SystemExit("private report already exists")
    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    result = quarantine_historical_catalog_audit_atoms(
        candidate,
        project=str(args.project),
        audit_output=audit_output,
        preverified_schema=bool(args.preverified_schema),
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
