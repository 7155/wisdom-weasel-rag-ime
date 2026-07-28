#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.macos_uninstall import (
    MacOSUninstallOptions,
    apply_macos_uninstall_plan,
    build_macos_uninstall_plan,
    write_uninstall_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or apply a user-scoped RAG-IME uninstall without touching unrelated Rime data"
    )
    parser.add_argument("--apply", action="store_true", help="Apply the printed plan; default is dry-run")
    parser.add_argument("--home", default=str(Path.home()), help="User home containing the installed components")
    parser.add_argument(
        "--component",
        choices=("all", "sidecar", "voice"),
        default="all",
        help="Limit base removal to one component; destructive purge flags remain explicit",
    )
    parser.add_argument("--remove-patched-squirrel", action="store_true")
    parser.add_argument("--remove-rime-managed-config", action="store_true")
    parser.add_argument(
        "--purge-runtime-cache",
        action="store_true",
        help="Remove only generated application code and allowlisted caches; preserve user data",
    )
    parser.add_argument("--purge-local-data", action="store_true")
    parser.add_argument("--purge-credentials", action="store_true")
    parser.add_argument("--purge-voice-config", action="store_true")
    parser.add_argument("--report", default="", help="Optional mode-600 JSON report path")
    args = parser.parse_args()

    plan = build_macos_uninstall_plan(
        args.home,
        options=MacOSUninstallOptions(
            component_scope=str(args.component),
            remove_patched_squirrel=bool(args.remove_patched_squirrel),
            remove_rime_managed_config=bool(args.remove_rime_managed_config),
            purge_runtime_cache=bool(args.purge_runtime_cache),
            purge_local_data=bool(args.purge_local_data),
            purge_credentials=bool(args.purge_credentials),
            purge_voice_config=bool(args.purge_voice_config),
        ),
    )
    report = apply_macos_uninstall_plan(plan) if args.apply else plan
    if args.report:
        write_uninstall_report(report, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
