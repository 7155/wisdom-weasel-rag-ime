#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/build/RagImeMac.app"
TARGET_DIR="$HOME/Library/Input Methods"
TARGET_APP="$TARGET_DIR/RagImeMac.app"
CONFIG_DIR="$HOME/Library/Application Support/RagImeMac"
USER_CONFIG="$CONFIG_DIR/bridge-config.json"

if [[ ! -d "$APP_DIR" ]]; then
  "$ROOT/scripts/build_macos_frontend.sh" >/dev/null
fi

mkdir -p "$TARGET_DIR"
rm -rf "$TARGET_APP"
cp -R "$APP_DIR" "$TARGET_APP"

mkdir -p "$CONFIG_DIR"
if [[ -f "$USER_CONFIG" ]]; then
  cp "$USER_CONFIG" "$USER_CONFIG.bak"
fi
cp "$TARGET_APP/Contents/Resources/bridge-config.json" "$USER_CONFIG"

echo "$TARGET_APP"
echo "$USER_CONFIG"
echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME."
