#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/build/RagImeMac.app"
TARGET_DIR="$HOME/Library/Input Methods"
TARGET_APP="$TARGET_DIR/RagImeMac.app"

if [[ ! -d "$APP_DIR" ]]; then
  "$ROOT/scripts/build_macos_frontend.sh" >/dev/null
fi

mkdir -p "$TARGET_DIR"
rm -rf "$TARGET_APP"
cp -R "$APP_DIR" "$TARGET_APP"

echo "$TARGET_APP"
echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME."
