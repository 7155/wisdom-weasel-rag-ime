#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Toggle the Squirrel RAG-IME frontend patch.")
    parser.add_argument("enabled", choices=("true", "false"))
    parser.add_argument(
        "--config",
        default=str(Path.home() / "Library" / "Rime" / "squirrel.custom.yaml"),
        help="Path to squirrel.custom.yaml.",
    )
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--deploy", action="store_true", help="Run Squirrel --reload after changing the file.")
    parser.add_argument(
        "--squirrel-app",
        default=str(Path.home() / "Library" / "Input Methods" / "Squirrel.app"),
        help="Squirrel app used for --deploy.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    desired = args.enabled == "true"
    if not config_path.exists():
        if desired:
            raise SystemExit(f"config file not found: {config_path}")
        print(f"config file not found, frontend already disabled: {config_path}")
        return 0

    original = config_path.read_text(encoding="utf-8")
    pattern = re.compile(r'("rag_ime/enabled"\s*:\s*)(true|false)')
    match = pattern.search(original)
    if not match:
        if desired:
            raise SystemExit(f"rag_ime/enabled key not found: {config_path}")
        print(f"rag_ime/enabled key not found, frontend treated as disabled: {config_path}")
        return 0

    current = match.group(2) == "true"
    if current == desired:
        print(f"rag_ime frontend already {'enabled' if desired else 'disabled'}: {config_path}")
        return 0

    updated = pattern.sub(rf"\1{str(desired).lower()}", original, count=1)
    if not args.no_backup:
        backup_path = config_path.with_suffix(
            config_path.suffix + ".rag-ime-toggle-" + datetime.now().strftime("%Y%m%d%H%M%S") + ".bak"
        )
        backup_path.write_text(original, encoding="utf-8")
        print(f"backup={backup_path}")
    config_path.write_text(updated, encoding="utf-8")
    print(f"rag_ime frontend {'enabled' if desired else 'disabled'}: {config_path}")

    if args.deploy:
        squirrel_executable = Path(args.squirrel_app).expanduser() / "Contents" / "MacOS" / "Squirrel"
        if not squirrel_executable.exists():
            raise SystemExit(f"Squirrel executable not found: {squirrel_executable}")
        subprocess.run([str(squirrel_executable), "--reload"], check=True)
        print(f"reloaded Squirrel: {squirrel_executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
