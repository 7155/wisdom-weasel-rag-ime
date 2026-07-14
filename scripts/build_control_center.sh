#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/macos/RagImeControl"
SHARED="$ROOT/macos/Shared"
APP="$ROOT/build/RagImeControl.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ACTION="${1:-build}"
CONTROL_UI="${RAG_IME_CONTROL_UI:-web}"

case "$CONTROL_UI" in
  native-legacy)
    ;;
  web)
    if [[ "$ACTION" == "install" ]]; then
      exec "$ROOT/scripts/build_control_center_web_host.sh" install-release
    fi
    exec "$ROOT/scripts/build_control_center_web_host.sh" build-release
    ;;
  *)
    echo "RAG_IME_CONTROL_UI must be web (default) or native-legacy (rollback only)" >&2
    exit 2
    ;;
esac

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$SRC/Info.plist" "$CONTENTS/Info.plist"
cp "$SHARED/Assets/CompanionStates/"*.png "$RESOURCES/"
cp "$SHARED/Assets/CompanionStatesFull/"*.png "$RESOURCES/"

mapfile=()
while IFS= read -r file; do mapfile+=("$file"); done < <(find "$SHARED" "$SRC" -type f -name '*.swift' | sort)

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/tmp/rag-ime-control-clang-cache}" \
SWIFT_MODULECACHE_PATH="${SWIFT_MODULECACHE_PATH:-/tmp/rag-ime-control-swift-cache}" \
xcrun swiftc \
  -O \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework AVFoundation \
  -framework ImageIO \
  -framework QuickLookUI \
  -framework Security \
  -framework SwiftUI \
  "${mapfile[@]}" \
  -o "$MACOS/RagImeControl"

python3 - "$RESOURCES/rag-ime-control-build-marker.json" "$ROOT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
root = Path(sys.argv[2])
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
).stdout.strip()
target.write_text(json.dumps({
    "bundleId": "com.rag-ime.control",
    "gitCommit": commit,
    "managementSchemaVersion": "rag-ime.management.v1",
    "settingsSchemaVersion": "rag-ime.settings-schema.v3",
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

"$ROOT/scripts/support/build_app_icon.sh" "$RESOURCES/RagImeIcon.icns"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string RagImeIcon' "$CONTENTS/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile RagImeIcon' "$CONTENTS/Info.plist"

codesign --force --deep --sign - "$APP" >/dev/null
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$CONTENTS/Info.plist")"
[[ "$bundle_id" == "com.rag-ime.control" ]] || { echo "unexpected bundle id: $bundle_id" >&2; exit 1; }

if otool -L "$MACOS/RagImeControl" | grep -Eq 'WebKit|JavaScriptCore'; then
  echo "control center must not link WebKit or JavaScriptCore" >&2
  exit 1
fi

if [[ "$ACTION" == "install" ]]; then
  DEST="$HOME/Applications/RagImeControl.app"
  mkdir -p "$HOME/Applications"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  codesign --verify --deep --strict "$DEST"
  echo "$DEST"
else
  echo "$APP"
fi
