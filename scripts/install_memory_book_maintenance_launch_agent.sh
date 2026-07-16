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
INSTALLED_SCRIPT_DIR="$APP_CODE_DIR/scripts"
INSTALLED_SCRIPT="$INSTALLED_SCRIPT_DIR/run_memory_book_maintenance_once.sh"
INSTALL_MARKER="$APP_CODE_DIR/rag-ime-install-marker.json"
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
mkdir -p "$PLIST_DIR" "$LOG_DIR" "$APP_CODE_DIR" "$INSTALLED_SCRIPT_DIR"
rm -rf "$APP_CODE_DIR/rag_ime"
cp -R "$ROOT/rag_ime" "$APP_CODE_DIR/rag_ime"
cp "$ROOT/scripts/memory_book_maintenance_launch.py" "$LAUNCH_WRAPPER"
cp "$ROOT/scripts/run_memory_book_maintenance_once.sh" "$INSTALLED_SCRIPT"
chmod 755 "$LAUNCH_WRAPPER" "$INSTALLED_SCRIPT"
MODEL_ENV_SOURCE="${RAG_IME_DEEPSEEK_ENV:-${RAG_IME_MODEL_ENV:-}}"
if [[ -z "$MODEL_ENV_SOURCE" ]]; then
  for candidate in "$APP_SUPPORT_DIR/deepseek.env" "$ROOT/.rag-ime-data/deepseek.env"; do
    if [[ -f "$candidate" ]]; then
      MODEL_ENV_SOURCE="$candidate"
      break
    fi
  done
fi
if [[ -n "$MODEL_ENV_SOURCE" && -f "$MODEL_ENV_SOURCE" ]]; then
  INSTALLED_MODEL_ENV="$APP_SUPPORT_DIR/deepseek.env"
  if [[ "$MODEL_ENV_SOURCE" != "$INSTALLED_MODEL_ENV" ]]; then
    cp "$MODEL_ENV_SOURCE" "$INSTALLED_MODEL_ENV"
  fi
  chmod 600 "$INSTALLED_MODEL_ENV"
  export RAG_IME_DEEPSEEK_ENV="$INSTALLED_MODEL_ENV"
fi

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

install_marker.write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.component-install-marker.v1",
            "component": "memory-book-maintenance",
            "sourceRoot": root,
            "sourceCommit": source_commit,
            "sourceDirty": source_dirty,
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "pythonExecutable": python_executable,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

env_keys = [
    "RAG_IME_APP_SUPPORT_DIR",
    "RAG_IME_DB_PATH",
    "RAG_IME_PROJECT",
    "RAG_IME_DEEPSEEK_ENV",
    "RAG_IME_MODEL_ENV",
    "RAG_IME_DEEPSEEK_THINKING",
    "RAG_IME_DEEPSEEK_REASONING_EFFORT",
    "RAG_IME_DEEPSEEK_MAX_TOKENS",
    "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_DIR",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_STALE_LOCK_SECONDS",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_SINCE_DAYS",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_RECENT_LIMIT",
    "RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE",
    "RAG_IME_PYTHON",
    "SSL_CERT_FILE",
]
environment = {
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "RAG_IME_ROOT": app_code_dir,
    "RAG_IME_SOURCE_ROOT": root,
    "RAG_IME_INSTALL_MARKER": str(install_marker),
    "RAG_IME_DEEPSEEK_THINKING": os.environ.get("RAG_IME_DEEPSEEK_THINKING", "disabled"),
    "RAG_IME_DEEPSEEK_REASONING_EFFORT": os.environ.get("RAG_IME_DEEPSEEK_REASONING_EFFORT", "low"),
    "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS": os.environ.get("RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS", "2048"),
    # The scheduled job may prepare a review draft, but it never applies
    # memory changes. Apply/rollback stays behind the native approval path.
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY": "0",
    # The owner-scoped evidence curator supersedes the old global organizer.
    "RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE": "0",
}
environment["RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER"] = "scheduled"
for key in env_keys:
    value = os.environ.get(key)
    if value:
        environment[key] = value

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
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"
echo "$PLIST_PATH"
echo "Logs: $LOG_DIR/memory-book-maintenance.out.log and $LOG_DIR/memory-book-maintenance.err.log"
