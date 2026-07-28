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
    install_managed_pi_runtime,
    read_managed_pi_runtime_acceptance_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify and atomically activate a prepared offline Pi runtime"
    )
    parser.add_argument("--payload", required=True)
    parser.add_argument(
        "--app-support",
        default=os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or str(Path.home() / "Library" / "Application Support" / "RagIme"),
    )
    parser.add_argument("--no-activate", action="store_true")
    parser.add_argument(
        "--acceptance-report",
        default="",
        help=(
            "Mode-600 deterministic installed-payload smoke receipt required to "
            "create accepted lifecycle and retired lineage"
        ),
    )
    args = parser.parse_args(argv)
    if args.no_activate and args.acceptance_report:
        parser.error("--acceptance-report cannot be combined with --no-activate")
    try:
        acceptance = (
            read_managed_pi_runtime_acceptance_report(args.acceptance_report)
            if args.acceptance_report
            else None
        )
        installation = install_managed_pi_runtime(
            args.payload,
            args.app_support,
            activate=not args.no_activate,
            acceptance=acceptance,
        )
    except (OSError, ManagedPiRuntimeError) as exc:
        print(f"managed Pi runtime installation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "runtimeVersion": installation.runtime_version,
                "piVersion": installation.pi_version,
                "runtimeDir": str(installation.runtime_dir),
                "manifestSha256": installation.manifest_sha256,
                "activated": not args.no_activate,
                "accepted": bool(args.acceptance_report),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
