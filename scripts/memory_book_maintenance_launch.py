from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_root = Path(os.environ.get("RAG_IME_ROOT") or Path(__file__).resolve().parent)
    script = app_root / "scripts" / "run_memory_book_maintenance_once.sh"
    if not script.is_file():
        print(f"memory book maintenance script missing: {script}", file=sys.stderr)
        return 66
    env = dict(os.environ)
    env["RAG_IME_ROOT"] = str(app_root)
    completed = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=app_root,
        env=env,
        check=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
