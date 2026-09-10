#!/usr/bin/env python3
"""Refresh existing PAW Dock tiles after installation, preserving other pins."""
from __future__ import annotations

import copy
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any


def refresh_tiles(tiles: list[dict[str, Any]], app: Path) -> list[dict[str, Any]]:
    result = copy.deepcopy(tiles)
    for item in result:
        tile = item.get("tile-data", {})
        if tile.get("bundle-identifier") != "com.rag-ime.control":
            continue
        tile["file-label"] = "Personal Agent Workbench"
        tile["file-data"] = {"_CFURLString": app.as_uri() + "/", "_CFURLStringType": 15}
        # Finder aliases can retain the old bundle path even after file-data changes.
        tile.pop("book", None)
    return result


def main() -> None:
    app, backup = map(Path, sys.argv[1:])
    raw = subprocess.check_output(["defaults", "export", "com.apple.dock", "-"])
    original = plistlib.loads(raw).get("persistent-apps", [])
    updated = refresh_tiles(original, app)
    if updated == original:
        return
    (backup / "dock-before.plist").write_bytes(raw)
    subprocess.run([
        "defaults", "write", "com.apple.dock", "persistent-apps", "-array",
        *(plistlib.dumps(item).decode() for item in updated),
    ], check=True)
    subprocess.run(["killall", "Dock"], check=False)


if __name__ == "__main__":
    main()
