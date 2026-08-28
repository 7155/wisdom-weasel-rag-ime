#!/usr/bin/env python3
"""Run PAW's public vertical-Agent examples in isolated local sandboxes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.vertical_agent_suite import run_vertical_agent_self_test_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic SGG / 掌柜问数 Trace-Eval sandbox self-tests.",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="New or empty directory that will contain isolated run artifacts.",
    )
    parser.add_argument(
        "--app",
        action="append",
        dest="app_ids",
        help="Run one built-in app id; repeat to select several. Defaults to all.",
    )
    args = parser.parse_args()
    try:
        report = run_vertical_agent_self_test_suite(
            args.output_root,
            app_ids=args.app_ids,
        )
    except Exception as exc:
        print(f"vertical self-test setup failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
