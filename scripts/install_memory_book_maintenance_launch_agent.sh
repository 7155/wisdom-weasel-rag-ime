#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_MEMORY_BOOK_MAINTENANCE_LABEL:-com.rag-ime.memory-book-maintenance}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
INTERVAL_SECONDS="${RAG_IME_MEMORY_BOOK_MAINTENANCE_INTERVAL_SECONDS:-3600}"
DRY_RUN="${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

python3 - "$PLIST_PATH" "$LABEL" "$ROOT" "$LOG_DIR" "$INTERVAL_SECONDS" <<'PY'
import os
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
label = sys.argv[2]
root = sys.argv[3]
log_dir = Path(sys.argv[4])
interval = max(300, int(sys.argv[5]))
script = str(Path(root) / "scripts" / "run_memory_book_maintenance_once.sh")

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
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_DIR",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_SINCE_DAYS",
    "RAG_IME_MEMORY_BOOK_MAINTENANCE_RECENT_LIMIT",
    "RAG_IME_PYTHON",
    "SSL_CERT_FILE",
]
environment = {
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "RAG_IME_DEEPSEEK_THINKING": os.environ.get("RAG_IME_DEEPSEEK_THINKING", "disabled"),
    "RAG_IME_DEEPSEEK_REASONING_EFFORT": os.environ.get("RAG_IME_DEEPSEEK_REASONING_EFFORT", "low"),
    "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS": os.environ.get("RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS", "2048"),
}
for key in env_keys:
    value = os.environ.get(key)
    if value:
        environment[key] = value

payload = {
    "Label": label,
    "ProgramArguments": ["/bin/bash", script],
    "WorkingDirectory": root,
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
