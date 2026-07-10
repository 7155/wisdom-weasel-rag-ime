#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


SOURCE_NAMES = (
    "RagImeAssistantSurfaceState.swift",
    "RagImeSuggestionCardView.swift",
    "RagImeSuggestionRowView.swift",
    "RagImeNonActivatingPanel.swift",
    "RagImeAssistantPanelController.swift",
)


def new_file_diff(name: str, source: str) -> str:
    lines = source.splitlines()
    body = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/sources/{name} b/sources/{name}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/sources/{name}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}\n"
    )


def replace_diff(text: str, name: str, replacement: str) -> str:
    marker = f"diff --git a/sources/{name} b/sources/{name}\n"
    start = text.find(marker)
    if start < 0:
        return text.rstrip() + "\n" + replacement
    next_diff = text.find("diff --git ", start + len(marker))
    if next_diff < 0:
        next_diff = len(text)
    return text[:start] + replacement + text[next_diff:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync canonical Assistant Overlay v2 Swift sources into the Squirrel patch.")
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    text = args.patch.read_text(encoding="utf-8")
    for name in SOURCE_NAMES:
        source = (args.source_dir / name).read_text(encoding="utf-8")
        text = replace_diff(text, name, new_file_diff(name, source))
    args.patch.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
