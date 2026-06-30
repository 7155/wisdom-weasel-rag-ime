#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/build/RagImeMac.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
SRC_DIR="$ROOT/macos/RagImeMac/Sources"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
RAG_IME_DB_PATH_VALUE="${RAG_IME_DB_PATH:-$ROOT/.rag-ime-data/rag-ime.sqlite}"
RAG_IME_PROJECT_VALUE="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
RAG_IME_TOP_K_VALUE="${RAG_IME_TOP_K:-5}"

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$ROOT/macos/RagImeMac/Info.plist" "$CONTENTS_DIR/Info.plist"

ICON_PPM="$RESOURCES_DIR/RagImeIcon.ppm"
python3 - "$ICON_PPM" <<'PY'
import math
import sys

path = sys.argv[1]
size = 64
pixels = []
for y in range(size):
    for x in range(size):
        dx = x - size / 2
        dy = y - size / 2
        radius = math.sqrt(dx * dx + dy * dy)
        if radius > 30:
            pixels.append((0, 0, 0))
            continue
        teal = int(128 + 72 * (1 - y / size))
        blue = int(160 + 72 * (x / size))
        bg = (18, teal, blue)
        in_r = (
            (15 <= x <= 22 and 17 <= y <= 47)
            or (22 <= x <= 40 and 17 <= y <= 23)
            or (22 <= x <= 40 and 30 <= y <= 36)
            or (38 <= x <= 45 and 24 <= y <= 30)
            or (32 <= x <= 45 and 36 <= y <= 47 and abs((y - 36) - (x - 32)) <= 5)
        )
        pixels.append((245, 250, 252) if in_r else bg)

with open(path, "wb") as fh:
    fh.write(f"P6\n{size} {size}\n255\n".encode("ascii"))
    for pixel in pixels:
        fh.write(bytes(pixel))
PY
sips -s format tiff "$ICON_PPM" --out "$RESOURCES_DIR/RagImeIcon.tiff" >/dev/null
rm -f "$ICON_PPM"

swiftc \
  -O \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework InputMethodKit \
  "$SRC_DIR/RagModels.swift" \
  "$SRC_DIR/RagBridgeClient.swift" \
  "$SRC_DIR/RagCandidatePanel.swift" \
  "$SRC_DIR/RagInputController.swift" \
  "$SRC_DIR/RagImeMacApp.swift" \
  -o "$MACOS_DIR/RagImeMac"

ROOT="$ROOT" \
RAG_IME_DB_PATH_VALUE="$RAG_IME_DB_PATH_VALUE" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
RAG_IME_PROJECT_VALUE="$RAG_IME_PROJECT_VALUE" \
RAG_IME_TOP_K_VALUE="$RAG_IME_TOP_K_VALUE" \
python3 - "$RESOURCES_DIR/bridge-config.json" "$RESOURCES_DIR/bridge-config.example.json" <<'PY'
import json
import os
import sys

payload = {
    "repoRoot": os.environ["ROOT"],
    "dbPath": os.environ["RAG_IME_DB_PATH_VALUE"],
    "pythonExecutable": os.environ["PYTHON_EXECUTABLE"],
    "project": os.environ["RAG_IME_PROJECT_VALUE"],
    "topK": int(os.environ["RAG_IME_TOP_K_VALUE"]),
}
for path in sys.argv[1:]:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
PY

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
fi

echo "$APP_DIR"
