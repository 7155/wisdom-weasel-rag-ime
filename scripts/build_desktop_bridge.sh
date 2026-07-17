#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/macos/RagImeDesktopBridge"
APP="$ROOT/build/RagImeDesktopBridge.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ACTION="${1:-build}"
CODESIGN_IDENTITY="${RAG_IME_CODESIGN_IDENTITY:--}"
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_DIRTY="false"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  SOURCE_DIRTY="true"
fi

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$SRC/Info.plist" "$CONTENTS/Info.plist"

sources=()
while IFS= read -r file; do sources+=("$file"); done < <(find "$SRC" -type f -name '*.swift' | sort)

xcrun swiftc \
  -O \
  -swift-version 5 \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework ApplicationServices \
  -framework Carbon \
  -framework CoreGraphics \
  -framework CryptoKit \
  "${sources[@]}" \
  -o "$MACOS/RagImeDesktopBridge"

python3 - "$RESOURCES/rag-ime-desktop-bridge-build-marker.json" "$SOURCE_COMMIT" "$SOURCE_DIRTY" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
target.write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.desktop-bridge-build-marker.v1",
            "gitCommit": sys.argv[2],
            "gitDirty": sys.argv[3] == "true",
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "capabilities": {
                "accessibilitySemantics": True,
                "treeDiff": True,
                "semanticActions": True,
                "liveStateRevalidation": True,
                "modelSuppliedCoordinates": False,
                "screenCapture": False,
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

"$ROOT/scripts/support/build_app_icon.sh" "$RESOURCES/RagImeIcon.icns"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string RagImeIcon' "$CONTENTS/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile RagImeIcon' "$CONTENTS/Info.plist"

if [[ "$CODESIGN_IDENTITY" == "-" ]]; then
  # Keep one stable designated requirement so local rebuilds retain the user's
  # Accessibility grant instead of becoming a new TCC identity each time.
  codesign --force --deep --sign - \
    --requirements '=designated => identifier "com.rag-ime.desktop-bridge"' \
    "$APP" >/dev/null
else
  codesign --force --deep --sign "$CODESIGN_IDENTITY" "$APP" >/dev/null
fi

if [[ "$ACTION" == "install" ]]; then
  DEST="$HOME/Applications/RagImeDesktopBridge.app"
  mkdir -p "$HOME/Applications"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  codesign --verify --deep --strict "$DEST"
  echo "$DEST"
else
  echo "$APP"
fi
