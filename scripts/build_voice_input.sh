#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/macos/RagImeVoice"
SHARED="$ROOT/macos/Shared"
APP="$ROOT/build/RagImeVoice.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ACTION="${1:-build}"

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"
cp "$SRC/Info.plist" "$CONTENTS/Info.plist"
cp "$SHARED/Assets/CompanionStates/"*.png "$RESOURCES/"

sources=()
while IFS= read -r file; do sources+=("$file"); done < <(find "$SHARED" "$SRC" -type f -name '*.swift' | sort)

xcrun swiftc \
  -O \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework ApplicationServices \
  -framework AVFoundation \
  -framework Carbon \
  -framework Security \
  -framework SwiftUI \
  "${sources[@]}" \
  -o "$MACOS/RagImeVoice"

"$ROOT/scripts/support/build_app_icon.sh" "$RESOURCES/RagImeIcon.icns"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string RagImeIcon' "$CONTENTS/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile RagImeIcon' "$CONTENTS/Info.plist"

codesign --force --deep --sign - "$APP" >/dev/null

if [[ "$ACTION" == "install" ]]; then
  DEST="$HOME/Applications/RagImeVoice.app"
  mkdir -p "$HOME/Applications"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  codesign --verify --deep --strict "$DEST"
  echo "$DEST"
else
  echo "$APP"
fi
