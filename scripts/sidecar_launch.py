from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(os.environ.get("RAG_IME_ROOT") or Path(__file__).resolve().parents[1])
    sys.path.insert(0, str(root))
    from rag_ime.cli import main as cli_main

    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
