#!/usr/bin/env bash
set -euo pipefail

DOMAIN="gui/$(id -u)"

for label in com.rag-ime.sidecar com.rag-ime.mlx-predictor; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  launchctl bootout "$DOMAIN" "$plist" >/dev/null 2>&1 || true
  launchctl disable "$DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl remove "$label" >/dev/null 2>&1 || true
done

pkill -f 'sidecar_launch.py.*mlx-predictor-server' >/dev/null 2>&1 || true
pkill -f 'sidecar_launch.py.*sidecar-server' >/dev/null 2>&1 || true
pkill -f 'rag_ime.cli mlx-predictor-server' >/dev/null 2>&1 || true
pkill -f '/Library/Input Methods/RAG-IME.app|RAG-IME.app|im.rag-ime.inputmethod.RagIme' >/dev/null 2>&1 || true

echo "RAG-IME runtime stopped and LaunchAgents disabled."
