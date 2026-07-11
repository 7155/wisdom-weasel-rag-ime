#!/usr/bin/env bash
set -euo pipefail

LABEL="com.rag-ime.voice"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP="$HOME/Applications/RagImeVoice.app"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
rm -rf "$APP"

if [[ "${1:-}" == "--purge-credentials" ]]; then
  SERVICE="com.rag-ime.voice.volcengine"
  for account in app-id access-token resource-id; do
    security delete-generic-password -s "$SERVICE" -a "$account" >/dev/null 2>&1 || true
  done
  rm -f "$HOME/Library/Application Support/RagIme/voice-hotwords.json"
fi

echo "RAG-IME voice agent removed. macOS privacy-list entries can be removed manually in System Settings."
