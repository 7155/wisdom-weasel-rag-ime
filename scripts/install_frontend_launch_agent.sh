#!/usr/bin/env bash
set -euo pipefail

LABEL="${RAG_IME_FRONTEND_LAUNCH_AGENT_LABEL:-com.rag-ime.frontend}"
APP_PATH="${RAG_IME_FRONTEND_APP:-${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
DRY_RUN="${RAG_IME_FRONTEND_LAUNCH_AGENT_DRY_RUN:-0}"

EXECUTABLE="$APP_PATH/Contents/MacOS/Squirrel"
INFO_PLIST="$APP_PATH/Contents/Info.plist"

if [[ ! -x "$EXECUTABLE" ]]; then
  echo "RAG-IME frontend executable not found or not executable: $EXECUTABLE" >&2
  exit 1
fi

if [[ ! -f "$INFO_PLIST" ]]; then
  echo "RAG-IME frontend Info.plist not found: $INFO_PLIST" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

LABEL="$LABEL" \
APP_PATH="$APP_PATH" \
EXECUTABLE="$EXECUTABLE" \
PLIST_PATH="$PLIST_PATH" \
LOG_DIR="$LOG_DIR" \
/usr/bin/python3 - <<'PY'
import os
import plistlib
from pathlib import Path

label = os.environ["LABEL"]
app_path = os.environ["APP_PATH"]
executable = os.environ["EXECUTABLE"]
log_dir = Path(os.environ["LOG_DIR"])

payload = {
    "Label": label,
    "ProgramArguments": [executable],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "LimitLoadToSessionType": "Aqua",
    "WorkingDirectory": str(Path(app_path) / "Contents" / "MacOS"),
    "StandardOutPath": str(log_dir / "frontend.out.log"),
    "StandardErrorPath": str(log_dir / "frontend.err.log"),
}

with open(os.environ["PLIST_PATH"], "wb") as fh:
    plistlib.dump(payload, fh)
PY

if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$PLIST_PATH" >/dev/null
fi

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  echo "$PLIST_PATH"
  echo "dry-run: not loading launch agent"
  exit 0
fi

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
sleep 0.2
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "$PLIST_PATH"
echo "$APP_PATH"
echo "Logs: $LOG_DIR/frontend.out.log and $LOG_DIR/frontend.err.log"
