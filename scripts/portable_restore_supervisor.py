#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


APP_CODE_ROOT = Path(__file__).resolve().parent
if str(APP_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_CODE_ROOT))

from rag_ime.external_actions import execute_portable_restore_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one approved RAG-IME portable restore plan")
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    result = execute_portable_restore_plan(args.plan)
    if result.get("ok") is True:
        return 0
    error = str(result.get("error") or "portable restore did not complete")
    print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
