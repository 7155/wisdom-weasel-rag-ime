#!/usr/bin/env python3
"""Check configured compaction against the pinned SDK with an offline model seam."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_managed_pi_runtime_v2 import _prepare_sdk_prompt_overlay
from rag_ime.agent_prompt_settings import default_prompt_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-worktree", type=Path, required=True)
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    if not args.node:
        parser.error("Node is required")
    with tempfile.TemporaryDirectory(prefix="paw-native-prompt-smoke-") as temporary:
        sdk = _prepare_sdk_prompt_overlay(args.pi_worktree.resolve(), Path(temporary) / "sdk")
        settings = Path(temporary) / "prompt-settings.json"
        settings.write_text(json.dumps(default_prompt_settings(), ensure_ascii=False), encoding="utf-8")
        subprocess.run([
            args.node,
            str(ROOT / "tests/fixtures/pi_prompt_settings_probe.mjs"),
            str(sdk),
            str(settings),
        ], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
