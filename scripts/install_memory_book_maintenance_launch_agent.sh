#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_MEMORY_BOOK_MAINTENANCE_LABEL:-com.rag-ime.memory-book-maintenance}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
APP_CODE_DIR="$APP_SUPPORT_DIR/components/memory-book-maintenance"
LAUNCH_WRAPPER="$APP_CODE_DIR/memory_book_maintenance_launch.py"
INSTALL_MARKER="$APP_CODE_DIR/rag-ime-install-marker.json"
# Poll hourly; the Gateway reads the current managed cadence and returns a
# no-op when no owner scope is due.
INTERVAL_SECONDS="${RAG_IME_MEMORY_BOOK_MAINTENANCE_INTERVAL_SECONDS:-3600}"
DRY_RUN="${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
SOURCE_DIRTY="false"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
  SOURCE_DIRTY="true"
fi

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi
if [[ "$APP_CODE_DIR" != "$APP_SUPPORT_DIR/components/memory-book-maintenance" ]]; then
  echo "unsafe memory maintenance component path: $APP_CODE_DIR" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR" "$APP_CODE_DIR"
# Remove only obsolete payloads previously owned by this component. The
# scheduler must not ship a second rag_ime package or a database-reading runner.
rm -rf "$APP_CODE_DIR/rag_ime" "$APP_CODE_DIR/scripts"
cp "$ROOT/scripts/memory_book_maintenance_launch.py" "$LAUNCH_WRAPPER"
chmod 755 "$LAUNCH_WRAPPER"

"$PYTHON_EXECUTABLE" - "$PLIST_PATH" "$LABEL" "$ROOT" "$APP_CODE_DIR" "$LAUNCH_WRAPPER" "$LOG_DIR" "$INTERVAL_SECONDS" "$PYTHON_EXECUTABLE" "$SOURCE_COMMIT" "$SOURCE_DIRTY" "$INSTALL_MARKER" <<'PY'
import json
import os
import plistlib
import sys
from datetime import datetime, timezone
from pathlib import Path

plist_path = Path(sys.argv[1])
label = sys.argv[2]
root = sys.argv[3]
app_code_dir = sys.argv[4]
launch_wrapper = sys.argv[5]
log_dir = Path(sys.argv[6])
interval = max(300, int(sys.argv[7]))
python_executable = sys.argv[8]
source_commit = sys.argv[9]
source_dirty = sys.argv[10] == "true"
install_marker = Path(sys.argv[11])

gateway_url = os.environ.get(
    "RAG_IME_AGENT_GATEWAY_URL",
    "http://127.0.0.1:8768",
).strip()
install_marker.write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.component-install-marker.v1",
            "component": "memory-maintenance-trigger",
            "transport": "gateway-loopback-http",
            "sourceRoot": root,
            "sourceCommit": source_commit,
            "sourceDirty": source_dirty,
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "pythonExecutable": python_executable,
            "gatewayUrl": gateway_url,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

environment = {
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "RAG_IME_AGENT_GATEWAY_URL": gateway_url,
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER": "scheduled",
    "RAG_IME_MEMORY_MAINTENANCE_TIMEOUT_SECONDS": os.environ.get(
        "RAG_IME_MEMORY_MAINTENANCE_TIMEOUT_SECONDS", "3600"
    ),
    "RAG_IME_MEMORY_MAINTENANCE_POLL_SECONDS": os.environ.get(
        "RAG_IME_MEMORY_MAINTENANCE_POLL_SECONDS", "0.5"
    ),
}
project = os.environ.get("RAG_IME_PROJECT", "").strip()
if project:
    environment["RAG_IME_PROJECT"] = project

payload = {
    "Label": label,
    "ProgramArguments": [python_executable, launch_wrapper],
    "WorkingDirectory": app_code_dir,
    "StartInterval": interval,
    "RunAtLoad": False,
    "KeepAlive": False,
    "StandardOutPath": str(log_dir / "memory-book-maintenance.out.log"),
    "StandardErrorPath": str(log_dir / "memory-book-maintenance.err.log"),
    "EnvironmentVariables": environment,
}
plist_path.parent.mkdir(parents=True, exist_ok=True)
plist_path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False))
PY

if [[ "$DRY_RUN" == "1" ]]; then
  echo "$PLIST_PATH"
  plutil -p "$PLIST_PATH"
  exit 0
fi

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl enable "gui/$(id -u)/$LABEL"
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "$PLIST_PATH"
echo "Logs: $LOG_DIR/memory-book-maintenance.out.log and $LOG_DIR/memory-book-maintenance.err.log"
