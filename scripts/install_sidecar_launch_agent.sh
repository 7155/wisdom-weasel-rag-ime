#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
DB_PATH="${RAG_IME_DB_PATH:-$ROOT/.rag-ime-data/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
PORT="${RAG_IME_SIDECAR_PORT:-8766}"
CORE_MODE="${RAG_IME_CORE_MODE:-local}"
CORE_COMMAND="${RAG_MEMORY_CORE_COMMAND:-}"
NO_SEED="${RAG_IME_SIDECAR_NO_SEED:-0}"
DRY_RUN="${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}"

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR" "$(dirname "$DB_PATH")"

ROOT="$ROOT" \
LABEL="$LABEL" \
PLIST_PATH="$PLIST_PATH" \
LOG_DIR="$LOG_DIR" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
DB_PATH="$DB_PATH" \
PROJECT="$PROJECT" \
HOST="$HOST" \
PORT="$PORT" \
CORE_MODE="$CORE_MODE" \
CORE_COMMAND="$CORE_COMMAND" \
NO_SEED="$NO_SEED" \
"$PYTHON_EXECUTABLE" - <<'PY'
import os
import plistlib
from pathlib import Path

root = os.environ["ROOT"]
label = os.environ["LABEL"]
args = [
    os.environ["PYTHON_EXECUTABLE"],
    "-m",
    "rag_ime.cli",
    "--core-mode",
    os.environ["CORE_MODE"],
    "--db-path",
    os.environ["DB_PATH"],
]
core_command = os.environ.get("CORE_COMMAND", "")
if core_command:
    args.extend(["--core-command", core_command])
args.extend(
    [
        "sidecar-server",
        "--host",
        os.environ["HOST"],
        "--port",
        os.environ["PORT"],
        "--project",
        os.environ["PROJECT"],
    ]
)
if os.environ.get("NO_SEED") in {"1", "true", "TRUE", "yes", "YES"}:
    args.append("--no-seed")

payload = {
    "Label": label,
    "ProgramArguments": args,
    "WorkingDirectory": root,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "StandardOutPath": str(Path(os.environ["LOG_DIR"]) / "sidecar.out.log"),
    "StandardErrorPath": str(Path(os.environ["LOG_DIR"]) / "sidecar.err.log"),
    "EnvironmentVariables": {
        "PYTHONPATH": root,
        "RAG_IME_DB_PATH": os.environ["DB_PATH"],
        "RAG_IME_CORE_MODE": os.environ["CORE_MODE"],
    },
}
if core_command:
    payload["EnvironmentVariables"]["RAG_MEMORY_CORE_COMMAND"] = core_command

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
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "$PLIST_PATH"
echo "http://$HOST:$PORT/"
echo "Logs: $LOG_DIR/sidecar.out.log and $LOG_DIR/sidecar.err.log"
