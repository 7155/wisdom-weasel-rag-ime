#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.db.migration_runner import DEFAULT_MIGRATIONS_DIR
from rag_ime.memory_pipeline_diagnostics import (
    build_memory_pipeline_recovery_preview,
    recovery_report_summary,
    write_private_recovery_report,
)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Create a raw-text-free, read-only Memory Pipeline recovery preview. "
            "Neither SQLite database is migrated or modified."
        )
    )
    parser.add_argument("--current-db", type=Path, required=True)
    parser.add_argument("--backup-db", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSON file outside Git; it is created exclusively with mode 0600",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="Source migration directory used only for checksum comparison",
    )
    args = parser.parse_args(argv)

    try:
        report = build_memory_pipeline_recovery_preview(
            args.current_db,
            args.backup_db,
            migrations_dir=args.migrations_dir,
        )
        output = write_private_recovery_report(args.output, report)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            recovery_report_summary(report, report_path=output),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if not bool(report["readiness"]["zeroMutationProof"]):
        return 2
    if not bool(report["readiness"]["exactRecoveryCompatible"]):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
