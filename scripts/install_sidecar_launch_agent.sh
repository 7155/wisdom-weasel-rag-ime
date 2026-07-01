#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
APP_CODE_DIR="$APP_SUPPORT_DIR/app"
LAUNCH_WRAPPER="$APP_CODE_DIR/sidecar_launch.py"
DB_PATH="${RAG_IME_DB_PATH:-$APP_SUPPORT_DIR/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
PORT="${RAG_IME_SIDECAR_PORT:-8766}"
CORE_MODE="${RAG_IME_CORE_MODE:-local}"
CORE_COMMAND="${RAG_MEMORY_CORE_COMMAND:-}"
NO_SEED="${RAG_IME_SIDECAR_NO_SEED:-0}"
DRY_RUN="${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}"

detect_python() {
  local candidate
  local candidates=()
  candidates+=("/usr/local/bin/python3")
  candidates+=("$(command -v python3 2>/dev/null || true)")
  candidates+=("/opt/homebrew/bin/python3")

  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(detect_python || true)}"

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

if [[ ! -f "$ROOT/scripts/sidecar_launch.py" ]]; then
  echo "sidecar launch wrapper not found: $ROOT/scripts/sidecar_launch.py" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR" "$(dirname "$DB_PATH")" "$APP_CODE_DIR"
rm -rf "$APP_CODE_DIR/rag_ime"
cp -R "$ROOT/rag_ime" "$APP_CODE_DIR/rag_ime"
cp "$ROOT/scripts/sidecar_launch.py" "$LAUNCH_WRAPPER"

ROOT="$ROOT" \
LABEL="$LABEL" \
PLIST_PATH="$PLIST_PATH" \
LOG_DIR="$LOG_DIR" \
APP_SUPPORT_DIR="$APP_SUPPORT_DIR" \
APP_CODE_DIR="$APP_CODE_DIR" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
LAUNCH_WRAPPER="$LAUNCH_WRAPPER" \
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
app_support_dir = os.environ["APP_SUPPORT_DIR"]
app_code_dir = os.environ["APP_CODE_DIR"]
label = os.environ["LABEL"]
args = [
    os.environ["PYTHON_EXECUTABLE"],
    os.environ["LAUNCH_WRAPPER"],
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

env_vars = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "RAG_IME_ROOT": app_code_dir,
    "RAG_IME_SOURCE_ROOT": root,
    "RAG_IME_DB_PATH": os.environ["DB_PATH"],
    "RAG_IME_CORE_MODE": os.environ["CORE_MODE"],
}
for key in (
    "RAG_IME_RIME_CACHE_TTL_MS",
    "RAG_IME_SUGGESTION_CACHE_SIZE",
    "RAG_IME_HISTORY_CONTEXT_EVENTS",
    "RAG_IME_HISTORY_CONTEXT_CHARS",
    "RAG_IME_PREDICTOR_PROVIDER",
    "RAG_IME_PREDICTOR_BASE_URL",
    "RAG_IME_PREDICTOR_MODEL",
    "RAG_IME_PREDICTOR_PROFILE",
    "RAG_IME_PREDICTOR_TIMEOUT_MS",
    "RAG_IME_PREDICTOR_MAX_TOKENS",
    "RAG_IME_PREDICTOR_TEMPERATURE",
    "RAG_IME_PREDICTOR_TOP_P",
    "RAG_IME_PREDICTOR_DISABLE_THINKING",
    "RAG_IME_PREDICTOR_STREAM_FIRST",
    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS",
    "RAG_IME_PREDICTOR_FAILURE_LATENCY_MS",
    "RAG_IME_PREDICTOR_EXTRA_BODY_JSON",
    "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON",
    "RAG_IME_PREDICTOR_API_KEY",
    "RAG_IME_MLX_MODEL",
):
    value = os.environ.get(key)
    if value:
        env_vars[key] = value
if core_command:
    env_vars["RAG_MEMORY_CORE_COMMAND"] = core_command

payload = {
    "Label": label,
    "ProgramArguments": args,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "StandardOutPath": str(Path(os.environ["LOG_DIR"]) / "sidecar.out.log"),
    "StandardErrorPath": str(Path(os.environ["LOG_DIR"]) / "sidecar.err.log"),
    "WorkingDirectory": app_support_dir,
    "EnvironmentVariables": env_vars,
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
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "$PLIST_PATH"
echo "http://$HOST:$PORT/"
echo "Logs: $LOG_DIR/sidecar.out.log and $LOG_DIR/sidecar.err.log"

for _attempt in {1..20}; do
  if "$PYTHON_EXECUTABLE" - "$HOST" "$PORT" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request

host = sys.argv[1]
port = sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.0) as response:
    payload = json.loads(response.read().decode("utf-8"))
if not payload.get("ok"):
    raise SystemExit(1)
PY
  then
    echo "health: OK"
    exit 0
  fi
  sleep 0.5
done

echo "health: not ready; inspect $LOG_DIR/sidecar.err.log" >&2
exit 1
