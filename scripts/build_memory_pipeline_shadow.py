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
from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.memory_shadow_recovery import (
    build_memory_pipeline_shadow,
    shadow_recovery_summary,
)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Build a private, reversible Memory Pipeline shadow from the live "
            "database plus an exact historical backup. Source databases are "
            "opened read-only and are never activated or replaced."
        )
    )
    parser.add_argument("--current-db", type=Path, required=True)
    parser.add_argument("--historical-backup-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--rollback-db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
    )
    parser.add_argument(
        "--allow-applied-checksum-mismatch",
        action="append",
        type=int,
        default=[],
        metavar="VERSION",
        help=(
            "Acknowledge one already-applied checksum collision in this shadow "
            "only. The recorded database migration is retained and the source "
            "migration is excluded from the temporary migration view."
        ),
    )
    args = parser.parse_args(argv)

    provider = embedding_provider_from_env()
    try:
        report = build_memory_pipeline_shadow(
            args.current_db,
            args.historical_backup_db,
            output_db=args.output_db,
            rollback_db=args.rollback_db,
            report_path=args.report,
            embedding_provider=provider,
            project=str(args.project),
            timezone_name=str(args.timezone),
            migrations_dir=args.migrations_dir,
            allowed_applied_checksum_mismatch_versions=(
                args.allow_applied_checksum_mismatch
            ),
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            shadow_recovery_summary(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
