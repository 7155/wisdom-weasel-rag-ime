#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
APP_CODE_DIR="$APP_SUPPORT_DIR/app"
SIDE_LABEL="${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}"
LABEL="${RAG_IME_AGENT_GATEWAY_LABEL:-com.rag-ime.agent-gateway}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
SIDE_PLIST="$PLIST_DIR/$SIDE_LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
WRAPPER="$APP_CODE_DIR/sidecar_launch.py"
INSTALL_MARKER="$APP_CODE_DIR/rag-ime-install-marker.json"
DB_PATH="${RAG_IME_DB_PATH:-$APP_SUPPORT_DIR/rag-ime.sqlite}"
HOST="${RAG_IME_AGENT_GATEWAY_HOST:-127.0.0.1}"
PORT="${RAG_IME_AGENT_GATEWAY_PORT:-8768}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
DRY_RUN="${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}"
MANAGED_RUNTIME_POINTER="$APP_SUPPORT_DIR/PiRuntime/current.json"

if [[ ! -f "$WRAPPER" || ! -d "$APP_CODE_DIR/rag_ime" ]]; then
  echo "installed app code is missing; run scripts/install_sidecar_launch_agent.sh first" >&2
  exit 1
fi
if ! python3 - "$INSTALL_MARKER" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        marker = json.load(source)
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
raise SystemExit(0 if marker.get("component") == "sidecar-runtime" and marker.get("sourceCommit") else 1)
PY
then
  echo "installed sidecar provenance is missing or was overwritten; reinstall the sidecar first" >&2
  exit 1
fi
if [[ ! -f "$MANAGED_RUNTIME_POINTER" && "${RAG_IME_ALLOW_UNMANAGED_PI:-0}" != "1" ]]; then
  echo "managed Pi Runtime is missing; install a verified protocol-v2 payload first" >&2
  exit 1
fi

PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-}"
if [[ -z "$PYTHON_EXECUTABLE" && -f "$SIDE_PLIST" ]]; then
  PYTHON_EXECUTABLE="$(python3 - "$SIDE_PLIST" <<'PY'
import plistlib
import sys
with open(sys.argv[1], "rb") as source:
    payload = plistlib.load(source)
args = payload.get("ProgramArguments") or []
print(args[0] if args else "")
PY
)"
fi
if [[ -z "$PYTHON_EXECUTABLE" ]]; then
  for candidate in "$ROOT/.venv/bin/python" /opt/homebrew/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then PYTHON_EXECUTABLE="$candidate"; break; fi
  done
fi
if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "Python executable is unavailable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"
SIDE_PLIST="$SIDE_PLIST" PLIST_PATH="$PLIST_PATH" LABEL="$LABEL" LOG_DIR="$LOG_DIR" \
APP_SUPPORT_DIR="$APP_SUPPORT_DIR" APP_CODE_DIR="$APP_CODE_DIR" WRAPPER="$WRAPPER" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" DB_PATH="$DB_PATH" HOST="$HOST" PORT="$PORT" \
PROJECT="$PROJECT" "$PYTHON_EXECUTABLE" - <<'PY'
import os
import plistlib
from pathlib import Path

environment = {}
side_plist = Path(os.environ["SIDE_PLIST"])
if side_plist.is_file():
    with side_plist.open("rb") as source:
        payload = plistlib.load(source)
    raw = payload.get("EnvironmentVariables")
    if isinstance(raw, dict):
        environment = {str(key): str(value) for key, value in raw.items() if value is not None}

for key in (
    "RAG_IME_PI_EXECUTABLE",
    "RAG_IME_PI_NODE",
    "RAG_IME_PI_EXTENSION",
    "RAG_IME_PI_PROTOCOL_VERSION",
    "RAG_IME_PI_TOOLS",
):
    environment.pop(key, None)

environment.update({
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "RAG_IME_ROOT": os.environ["APP_CODE_DIR"],
    "RAG_IME_APP_SUPPORT_DIR": os.environ["APP_SUPPORT_DIR"],
    "RAG_IME_DB_PATH": os.environ["DB_PATH"],
    "RAG_IME_PI_ENABLED": "1",
    "RAG_IME_PI_VERSION": "0.80.7",
    "RAG_IME_AGENT_GATEWAY_ENABLED": "1",
    "RAG_IME_AGENT_TOOL_URL": f"http://127.0.0.1:{os.environ['PORT']}/api/agent/tool/execute",
})

arguments = [
    os.environ["PYTHON_EXECUTABLE"],
    os.environ["WRAPPER"],
    "--core-mode", environment.get("RAG_IME_CORE_MODE", "local"),
    "--db-path", os.environ["DB_PATH"],
    "agent-gateway",
    "--host", os.environ["HOST"],
    "--port", os.environ["PORT"],
    "--project", os.environ["PROJECT"],
    "--no-seed",
]
payload = {
    "Label": os.environ["LABEL"],
    "ProgramArguments": arguments,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Background",
    "ThrottleInterval": 3,
    "WorkingDirectory": os.environ["APP_SUPPORT_DIR"],
    "StandardOutPath": str(Path(os.environ["LOG_DIR"]) / "agent-gateway.out.log"),
    "StandardErrorPath": str(Path(os.environ["LOG_DIR"]) / "agent-gateway.err.log"),
    "EnvironmentVariables": environment,
}
with open(os.environ["PLIST_PATH"], "wb") as target:
    plistlib.dump(payload, target)
PY

if command -v plutil >/dev/null 2>&1; then plutil -lint "$PLIST_PATH" >/dev/null; fi
echo "$PLIST_PATH"
if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  echo "dry-run: not loading Agent Gateway"
  exit 0
fi

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
pkill -f 'sidecar_launch.py.*agent-gateway' >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"

deadline=$((SECONDS + 45))
while (( SECONDS < deadline )); do
  if "$PYTHON_EXECUTABLE" - "$HOST" "$PORT" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request
host, port = sys.argv[1:]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(f"http://{host}:{port}/api/health", timeout=1.0) as response:
    payload = json.loads(response.read())
if not payload.get("ok"):
    raise SystemExit(1)
PY
  then
    echo "Agent Gateway health: OK (http://$HOST:$PORT/)"
    exit 0
  fi
  sleep 0.5
done

echo "Agent Gateway health did not become ready; inspect $LOG_DIR/agent-gateway.err.log" >&2
exit 1
