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

from rag_ime.managed_pi_runtime import ManagedPiRuntimeError, install_managed_pi_runtime


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
    args = parser.parse_args(argv)
    try:
        installation = install_managed_pi_runtime(
            args.payload,
            args.app_support,
            activate=not args.no_activate,
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
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
