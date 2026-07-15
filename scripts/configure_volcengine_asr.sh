#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --app-id ID --access-token-file PATH [--resource-id ID]" >&2
  exit 2
}

APP_ID=""
TOKEN_FILE=""
RESOURCE_ID="volc.seedasr.sauc.duration"
while (($#)); do
  case "$1" in
    --app-id) APP_ID="${2:-}"; shift 2 ;;
    --access-token-file) TOKEN_FILE="${2:-}"; shift 2 ;;
    --resource-id) RESOURCE_ID="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$APP_ID" && -f "$TOKEN_FILE" && -n "$RESOURCE_ID" ]] || usage

TOKEN="$(tr -d '\r\n[:space:]' < "$TOKEN_FILE")"
[[ -n "$TOKEN" ]] || { echo "Access Token file is empty" >&2; exit 1; }
SERVICE="com.rag-ime.voice.volcengine"
VOICE_BIN="$HOME/Applications/RagImeVoice.app/Contents/MacOS/RagImeVoice"
CONTROL_BIN="$HOME/Applications/RagImeControl.app/Contents/MacOS/RagImeControl"
[[ -x "$VOICE_BIN" && -x "$CONTROL_BIN" ]] || {
  echo "Install RagImeVoice.app and RagImeControl.app before importing credentials." >&2
  exit 1
}

store_item() {
  local account="$1"
  local value="$2"
  security delete-generic-password -s "$SERVICE" -a "$account" >/dev/null 2>&1 || true
  security add-generic-password \
    -s "$SERVICE" \
    -a "$account" \
    -w "$value" \
    -T "$VOICE_BIN" \
    -T "$CONTROL_BIN" \
    >/dev/null
}

store_item app-id "$APP_ID"
store_item access-token "$TOKEN"
store_item resource-id "$RESOURCE_ID"
unset TOKEN
echo "Volcengine ASR credentials stored in macOS Keychain."
