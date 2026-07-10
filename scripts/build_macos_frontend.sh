#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/build/RagImeMac.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
SRC_DIR="$ROOT/macos/RagImeMac/Sources"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
DEFAULT_RUNTIME_DB="$HOME/Library/Application Support/RagIme/rag-ime.sqlite"
RAG_IME_DB_PATH_VALUE="${RAG_IME_DB_PATH:-$DEFAULT_RUNTIME_DB}"
RAG_IME_PROJECT_VALUE="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
RAG_IME_TOP_K_VALUE="${RAG_IME_TOP_K:-5}"
RAG_IME_SIDECAR_URL_VALUE="${RAG_IME_SIDECAR_URL:-http://127.0.0.1:8766}"
RAG_IME_RIME_INDEX_PATH_VALUE="${RAG_IME_RIME_INDEX_PATH:-}"
if [[ -n "${RAG_IME_RIME_DICT_DIR:-}" ]]; then
  RAG_IME_RIME_DICT_DIR_VALUE="$RAG_IME_RIME_DICT_DIR"
elif [[ -f "$ROOT/../agent-source-projects/wisdom-weasel-felix/third_party/rime_wanxiang/wanxiang.dict.yaml" ]]; then
  RAG_IME_RIME_DICT_DIR_VALUE="$ROOT/../agent-source-projects/wisdom-weasel-felix/third_party/rime_wanxiang"
elif [[ -f "$ROOT/third_party/rime_wanxiang/wanxiang.dict.yaml" ]]; then
  RAG_IME_RIME_DICT_DIR_VALUE="$ROOT/third_party/rime_wanxiang"
elif [[ -f "$ROOT/rime-wanxiang/wanxiang.dict.yaml" ]]; then
  RAG_IME_RIME_DICT_DIR_VALUE="$ROOT/rime-wanxiang"
else
  RAG_IME_RIME_DICT_DIR_VALUE="$HOME/Library/Rime"
fi

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$ROOT/macos/RagImeMac/Info.plist" "$CONTENTS_DIR/Info.plist"
if [[ -d "$ROOT/macos/RagImeMac/Resources" ]]; then
  /usr/bin/ditto "$ROOT/macos/RagImeMac/Resources" "$RESOURCES_DIR"
fi

if [[ -f "$RAG_IME_RIME_DICT_DIR_VALUE/wanxiang.dict.yaml" || -f "$RAG_IME_RIME_DICT_DIR_VALUE/luna_pinyin.dict.yaml" ]]; then
  INDEX_ARGS=(
    --dict-dir "$RAG_IME_RIME_DICT_DIR_VALUE"
    --output "$RESOURCES_DIR/rime-candidate-index.tsv"
    --cap 12
    --max-prefix-len 8
    --max-text-len 8
    --max-entries 35000
  )
  if [[ -f "$HOME/Library/Rime/essay.txt" ]]; then
    INDEX_ARGS+=(--essay-path "$HOME/Library/Rime/essay.txt")
  fi
  if [[ -f "$RAG_IME_RIME_DICT_DIR_VALUE/wanxiang_english.dict.yaml" ]]; then
    INDEX_ARGS+=(
      --english-dict "$RAG_IME_RIME_DICT_DIR_VALUE/wanxiang_english.dict.yaml"
      --max-english-entries 0
      --max-english-prefix-len 16
    )
  fi
  python3 "$ROOT/scripts/build_rime_candidate_index.py" "${INDEX_ARGS[@]}" >/dev/null
fi

ICON_PPM="$RESOURCES_DIR/RagImeIcon.ppm"
python3 - "$ICON_PPM" <<'PY'
import math
import sys

path = sys.argv[1]
size = 1024
pixels = []
for y in range(size):
    for x in range(size):
        dx = x - size / 2
        dy = y - size / 2
        radius = math.sqrt(dx * dx + dy * dy)
        if radius > size * 0.47:
            pixels.append((0, 0, 0))
            continue
        teal = int(118 + 88 * (1 - y / size))
        blue = int(150 + 86 * (x / size))
        bg = (18, teal, blue)
        in_r = (
            (0.23 <= x / size <= 0.34 and 0.24 <= y / size <= 0.74)
            or (0.34 <= x / size <= 0.62 and 0.24 <= y / size <= 0.35)
            or (0.34 <= x / size <= 0.62 and 0.46 <= y / size <= 0.57)
            or (0.59 <= x / size <= 0.70 and 0.35 <= y / size <= 0.47)
            or (
                0.50 <= x / size <= 0.72
                and 0.57 <= y / size <= 0.74
                and abs(((y / size) - 0.57) - ((x / size) - 0.50)) <= 0.08
            )
        )
        pixels.append((245, 250, 252) if in_r else bg)

with open(path, "wb") as fh:
    fh.write(f"P6\n{size} {size}\n255\n".encode("ascii"))
    for pixel in pixels:
        fh.write(bytes(pixel))
PY
sips -s format tiff "$ICON_PPM" --out "$RESOURCES_DIR/RagImeIcon.tiff" >/dev/null
ICONSET="$RESOURCES_DIR/RagImeIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -s format png -z "$size" "$size" "$ICON_PPM" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  retina=$((size * 2))
  sips -s format png -z "$retina" "$retina" "$ICON_PPM" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns "$ICONSET" -o "$RESOURCES_DIR/RagImeIcon.icns" >/dev/null
fi
rm -rf "$ICONSET"
rm -f "$ICON_PPM"

swiftc \
  -O \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework InputMethodKit \
  -framework SwiftUI \
  "$SRC_DIR/RagModels.swift" \
  "$SRC_DIR/RimeSidecarModels.swift" \
  "$SRC_DIR/RimeDictionaryCandidateProvider.swift" \
  "$SRC_DIR/RagBridgeClient.swift" \
  "$SRC_DIR/RagCandidatePanel.swift" \
  "$SRC_DIR/RagImeAssistantOverlayView.swift" \
  "$SRC_DIR/RagImeAssistantOverlayPreviewFixtures.swift" \
  "$SRC_DIR/RagImeAssistantPanelController.swift" \
  "$SRC_DIR/RagInputController.swift" \
  "$SRC_DIR/RagImeMacApp.swift" \
  -o "$MACOS_DIR/RagImeMac"

ROOT="$ROOT" \
RAG_IME_DB_PATH_VALUE="$RAG_IME_DB_PATH_VALUE" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
RAG_IME_PROJECT_VALUE="$RAG_IME_PROJECT_VALUE" \
RAG_IME_TOP_K_VALUE="$RAG_IME_TOP_K_VALUE" \
RAG_IME_SIDECAR_URL_VALUE="$RAG_IME_SIDECAR_URL_VALUE" \
RAG_IME_RIME_DICT_DIR_VALUE="$RAG_IME_RIME_DICT_DIR_VALUE" \
RAG_IME_RIME_INDEX_PATH_VALUE="$RAG_IME_RIME_INDEX_PATH_VALUE" \
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
    "sidecarBaseUrl": os.environ["RAG_IME_SIDECAR_URL_VALUE"],
    "rimeDictDir": os.environ["RAG_IME_RIME_DICT_DIR_VALUE"],
    "rimeCandidateIndexPath": os.environ["RAG_IME_RIME_INDEX_PATH_VALUE"],
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
