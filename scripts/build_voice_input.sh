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
CODESIGN_IDENTITY="${RAG_IME_CODESIGN_IDENTITY:--}"

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

if [[ "$CODESIGN_IDENTITY" == "-" ]]; then
  # The default ad-hoc requirement is a changing cdhash, which makes macOS
  # forget Accessibility and Microphone grants after every local rebuild.
  codesign --force --deep --sign - \
    --requirements '=designated => identifier "com.rag-ime.voice"' \
    "$APP" >/dev/null
else
  codesign --force --deep --sign "$CODESIGN_IDENTITY" "$APP" >/dev/null
fi

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
