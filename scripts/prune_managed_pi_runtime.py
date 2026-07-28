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

from rag_ime.managed_pi_runtime import (
    ManagedPiRuntimeError,
    apply_managed_pi_runtime_retention_plan,
    build_managed_pi_runtime_retention_plan,
    read_managed_pi_runtime_retention_plan,
    write_managed_pi_runtime_retention_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply manifest-aware managed Pi generation retention"
        )
    )
    parser.add_argument(
        "--app-support",
        default=os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or str(Path.home() / "Library" / "Application Support" / "RagIme"),
    )
    parser.add_argument(
        "--retain-generations",
        type=int,
        choices=(2,),
        default=2,
        help="Retain the active and verified immediate previous generations",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply an unchanged dry-run plan; default only prints the plan",
    )
    parser.add_argument(
        "--plan",
        default="",
        help="Mode-600 dry-run plan required by --apply",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional mode-600 JSON plan/result path",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.plan:
        parser.error("--apply requires --plan from a prior dry-run")
    if not args.apply and args.plan:
        parser.error("--plan is only valid with --apply")
    if args.apply and not args.report:
        parser.error("--apply requires --report for durable evidence")

    try:
        if args.apply:
            plan = read_managed_pi_runtime_retention_plan(args.plan)
            report = apply_managed_pi_runtime_retention_plan(
                plan,
                app_support=args.app_support,
            )
        else:
            report = build_managed_pi_runtime_retention_plan(
                args.app_support,
                retain_generations=args.retain_generations,
            )
        if args.report:
            write_managed_pi_runtime_retention_report(args.report, report)
    except (OSError, ManagedPiRuntimeError) as exc:
        print(f"managed Pi runtime retention failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("ok") is not True:
        print(
            "managed Pi runtime retention completed with a typed partial-failure receipt",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
