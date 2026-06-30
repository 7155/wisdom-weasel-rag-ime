#!/usr/bin/env bash
set -euo pipefail

LABEL="${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Removed $PLIST_PATH"
