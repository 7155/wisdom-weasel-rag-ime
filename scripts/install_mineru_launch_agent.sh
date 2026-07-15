#!/usr/bin/env bash
set -euo pipefail

LABEL="${RAG_IME_MINERU_LAUNCH_AGENT_LABEL:-com.rag-ime.mineru}"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
RUNTIME_DIR="${RAG_IME_MINERU_RUNTIME_DIR:-$APP_SUPPORT_DIR/MinerU}"
VENV_DIR="${RAG_IME_MINERU_VENV_DIR:-$RUNTIME_DIR/.venv}"
MODEL_CACHE_DIR="${RAG_IME_MINERU_MODEL_CACHE_DIR:-$RUNTIME_DIR/models}"
OUTPUT_DIR="${RAG_IME_MINERU_OUTPUT_DIR:-$RUNTIME_DIR/output}"
SERVICE_CWD="${RAG_IME_MINERU_SERVICE_CWD:-$APP_SUPPORT_DIR/MinerU}"
LOG_DIR="${RAG_IME_MINERU_LOG_DIR:-$HOME/Library/Logs/RagIme/MinerU}"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
HOST="127.0.0.1"
PORT="${RAG_IME_MINERU_PORT:-30001}"
PACKAGE_SPEC="${RAG_IME_MINERU_PACKAGE_SPEC:-mineru[all]>=3.4,<3.5}"
MODEL_SOURCE="${RAG_IME_MINERU_MODEL_SOURCE:-modelscope}"
PYTHON="${RAG_IME_MINERU_PYTHON:-/opt/homebrew/bin/python3.13}"
INSTALL_PACKAGE="${RAG_IME_MINERU_INSTALL_PACKAGE:-1}"
HEALTH_TIMEOUT_SECONDS="${RAG_IME_MINERU_HEALTH_TIMEOUT_SECONDS:-60}"

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "RAG_IME_MINERU_PORT must be between 1024 and 65535" >&2
  exit 2
fi
if [[ ! "$HEALTH_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( HEALTH_TIMEOUT_SECONDS < 1 )); then
  echo "RAG_IME_MINERU_HEALTH_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ "$HOST" != "127.0.0.1" ]]; then
  echo "MinerU must remain bound to loopback" >&2
  exit 2
fi

mkdir -p "$RUNTIME_DIR" "$MODEL_CACHE_DIR" "$OUTPUT_DIR" "$SERVICE_CWD" "$LOG_DIR" "$(dirname "$PLIST_PATH")"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to create the isolated MinerU runtime" >&2
    exit 1
  fi
  uv venv --python "$PYTHON" "$VENV_DIR"
fi

if [[ "$INSTALL_PACKAGE" == "1" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to install MinerU" >&2
    exit 1
  fi
  uv pip install --python "$VENV_DIR/bin/python" "$PACKAGE_SPEC"
fi

MINERU_API="$VENV_DIR/bin/mineru-api"
if [[ ! -x "$MINERU_API" ]]; then
  echo "mineru-api is unavailable in $VENV_DIR" >&2
  exit 1
fi

VENV_DIR="$VENV_DIR" \
MINERU_API="$MINERU_API" \
RUNTIME_DIR="$RUNTIME_DIR" \
SERVICE_CWD="$SERVICE_CWD" \
MODEL_CACHE_DIR="$MODEL_CACHE_DIR" \
OUTPUT_DIR="$OUTPUT_DIR" \
LOG_DIR="$LOG_DIR" \
PLIST_PATH="$PLIST_PATH" \
LABEL="$LABEL" \
HOST="$HOST" \
PORT="$PORT" \
MODEL_SOURCE="$MODEL_SOURCE" \
"$VENV_DIR/bin/python" - <<'PY'
import os
import plistlib
from pathlib import Path

payload = {
    "Label": os.environ["LABEL"],
    # Launch the console entry point through Python rather than executing its
    # generated shell shim. launchd can otherwise reject a shim stored on an
    # external volume before Python ever starts.
    "ProgramArguments": [
        f"{os.environ['VENV_DIR']}/bin/python",
        "-m",
        "mineru.cli.fast_api",
        "--host",
        os.environ["HOST"],
        "--port",
        os.environ["PORT"],
    ],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "WorkingDirectory": os.environ["SERVICE_CWD"],
    "StandardOutPath": str(Path(os.environ["LOG_DIR"]) / "mineru.out.log"),
    "StandardErrorPath": str(Path(os.environ["LOG_DIR"]) / "mineru.err.log"),
    "EnvironmentVariables": {
        "PATH": f"{os.environ['VENV_DIR']}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
        "HF_HOME": str(Path(os.environ["MODEL_CACHE_DIR"]) / "huggingface"),
        "MODELSCOPE_CACHE": str(Path(os.environ["MODEL_CACHE_DIR"]) / "modelscope"),
        "MINERU_MODEL_SOURCE": os.environ["MODEL_SOURCE"],
        "MINERU_API_OUTPUT_ROOT": os.environ["OUTPUT_DIR"],
        "MINERU_API_ENABLE_FASTAPI_DOCS": "true",
        "MINERU_API_MAX_CONCURRENT_REQUESTS": "1",
        "MINERU_PROCESSING_WINDOW_SIZE": "4",
        "MINERU_PDF_RENDER_THREADS": "2",
        "MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS": "600",
        "TOKENIZERS_PARALLELISM": "false",
    },
}

with open(os.environ["PLIST_PATH"], "wb") as handle:
    plistlib.dump(payload, handle)
PY

plutil -lint "$PLIST_PATH" >/dev/null

DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
pkill -f "$MINERU_API.*--port $PORT" >/dev/null 2>&1 || true
pkill -f "mineru.cli.fast_api.*--port $PORT" >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
for _ in {1..30}; do
  if ! lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

bootstrap_ok=0
for attempt in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1; then
    bootstrap_ok=1
    break
  fi
  sleep "0.$((attempt * 2))"
done
if [[ "$bootstrap_ok" != "1" ]]; then
  echo "failed to bootstrap $LABEL" >&2
  exit 1
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if "$VENV_DIR/bin/python" - "$PORT" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1.0) as response:
    payload = json.loads(response.read().decode("utf-8"))
if int(getattr(response, "status", 0)) != 200 or not isinstance(payload, dict):
    raise SystemExit(1)
PY
  then
    echo "$PLIST_PATH"
    echo "http://127.0.0.1:$PORT/health"
    echo "MinerU health: OK"
    exit 0
  fi
  sleep 0.5
done

echo "MinerU health did not become ready after ${HEALTH_TIMEOUT_SECONDS}s" >&2
echo "Logs: $LOG_DIR/mineru.out.log and $LOG_DIR/mineru.err.log" >&2
exit 1
