#!/usr/bin/env bash
set -euo pipefail

LABEL="com.rag-ime.desktop-bridge"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP="$HOME/Applications/RagImeDesktopBridge.app"
SOCKET="${RAG_IME_DESKTOP_BRIDGE_SOCKET:-${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}/desktop-bridge.sock}"

launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST" "$SOCKET"
rm -rf "$APP"
echo "Removed RagImeDesktopBridge."
