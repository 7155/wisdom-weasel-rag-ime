#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_MLX_LAUNCH_AGENT_LABEL:-com.rag-ime.mlx-predictor}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
APP_CODE_DIR="$APP_SUPPORT_DIR/app"
LAUNCH_WRAPPER="$APP_CODE_DIR/sidecar_launch.py"
HOST="${RAG_IME_MLX_HOST:-127.0.0.1}"
PORT="${RAG_IME_MLX_PORT:-8767}"
MODEL="${RAG_IME_MLX_MODEL:-/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local}"
PROFILE="${RAG_IME_MLX_PROFILE:-${RAG_IME_PREDICTOR_PROFILE:-qwen3_06b_ime_hot}}"
MAX_TOKENS="${RAG_IME_MLX_MAX_TOKENS:-8}"
TEMPERATURE="${RAG_IME_MLX_TEMPERATURE:-0.15}"
TOP_P="${RAG_IME_MLX_TOP_P:-0.85}"
PROMPT_CACHE="${RAG_IME_MLX_PROMPT_CACHE:-0}"
PROMPT_CACHE_MAX_KV_SIZE="${RAG_IME_MLX_PROMPT_CACHE_MAX_KV_SIZE:-0}"
PREFIX_CACHE="${RAG_IME_MLX_PREFIX_CACHE:-0}"
PREFIX_CACHE_MAX_ENTRIES="${RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES:-8}"
PREFIX_CACHE_MAX_MB="${RAG_IME_MLX_PREFIX_CACHE_MAX_MB:-32}"
PROMPT_MODE="${RAG_IME_MLX_PROMPT_MODE:-}"
MEMORY_PROFILE="${RAG_IME_MEMORY_PROFILE:-low}"
HF_HOME_VALUE="${RAG_IME_HF_HOME:-}"
DRY_RUN="${RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN:-0}"

detect_python() {
  local candidate
  local candidates=()
  candidates+=("$ROOT/.venv-mlx313/bin/python")
  candidates+=("$ROOT/.venv-mlx314sys/bin/python")
  candidates+=("$ROOT/.venv-mlx/bin/python")
  candidates+=("$ROOT/.venv/bin/python")
  candidates+=("/opt/homebrew/bin/python3.13")
  candidates+=("/opt/homebrew/bin/python3")
  candidates+=("$(command -v python3 2>/dev/null || true)")

  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" - <<'PY' >/dev/null 2>&1; then
import hashlib
import sqlite3
import ssl
import sys

hashlib.md5(b"rag-ime").hexdigest()
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_EXECUTABLE="${RAG_IME_MLX_PYTHON:-${RAG_IME_PYTHON:-$(detect_python || true)}}"

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

if ! "$PYTHON_EXECUTABLE" - <<'PY' >/dev/null 2>&1; then
import hashlib
import sqlite3
import ssl
import sys

hashlib.md5(b"rag-ime").hexdigest()
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  echo "python executable cannot import required stdlib modules (sqlite3/hashlib/ssl): $PYTHON_EXECUTABLE" >&2
  echo "Set RAG_IME_MLX_PYTHON or RAG_IME_PYTHON to a healthy Python." >&2
  exit 1
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "true" && "$DRY_RUN" != "TRUE" ]]; then
  if ! "$PYTHON_EXECUTABLE" -c 'import mlx_lm' >/dev/null 2>&1; then
    echo "mlx-lm is not importable from $PYTHON_EXECUTABLE" >&2
    echo "Install it first, for example: python -m pip install mlx-lm" >&2
    exit 1
  fi
fi

if [[ ! -f "$ROOT/scripts/sidecar_launch.py" ]]; then
  echo "sidecar launch wrapper not found: $ROOT/scripts/sidecar_launch.py" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR" "$APP_CODE_DIR"
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
HOST="$HOST" \
PORT="$PORT" \
MODEL="$MODEL" \
PROFILE="$PROFILE" \
MAX_TOKENS="$MAX_TOKENS" \
TEMPERATURE="$TEMPERATURE" \
TOP_P="$TOP_P" \
PROMPT_CACHE="$PROMPT_CACHE" \
PROMPT_CACHE_MAX_KV_SIZE="$PROMPT_CACHE_MAX_KV_SIZE" \
PREFIX_CACHE="$PREFIX_CACHE" \
PREFIX_CACHE_MAX_ENTRIES="$PREFIX_CACHE_MAX_ENTRIES" \
PREFIX_CACHE_MAX_MB="$PREFIX_CACHE_MAX_MB" \
PROMPT_MODE="$PROMPT_MODE" \
MEMORY_PROFILE="$MEMORY_PROFILE" \
HF_HOME_VALUE="$HF_HOME_VALUE" \
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
    "mlx-predictor-server",
    "--host",
    os.environ["HOST"],
    "--port",
    os.environ["PORT"],
    "--model",
    os.environ["MODEL"],
    "--profile",
    os.environ["PROFILE"],
    "--max-tokens",
    os.environ["MAX_TOKENS"],
    "--temperature",
    os.environ["TEMPERATURE"],
    "--top-p",
    os.environ["TOP_P"],
]
if os.environ.get("PROMPT_CACHE", "").strip().lower() in {"1", "true", "yes", "on"}:
    args.append("--prompt-cache")
max_kv_size = os.environ.get("PROMPT_CACHE_MAX_KV_SIZE", "").strip()
if max_kv_size and max_kv_size != "0":
    args.extend(["--prompt-cache-max-kv-size", max_kv_size])

env_vars = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "RAG_IME_ROOT": app_code_dir,
    "RAG_IME_SOURCE_ROOT": root,
    "RAG_IME_MLX_MODEL": os.environ["MODEL"],
    "RAG_IME_MLX_PROFILE": os.environ["PROFILE"],
    "RAG_IME_MLX_HOST": os.environ["HOST"],
    "RAG_IME_MLX_PORT": os.environ["PORT"],
    "RAG_IME_MLX_MAX_TOKENS": os.environ["MAX_TOKENS"],
    "RAG_IME_MLX_TEMPERATURE": os.environ["TEMPERATURE"],
    "RAG_IME_MLX_TOP_P": os.environ["TOP_P"],
    "RAG_IME_MLX_PROMPT_CACHE": os.environ["PROMPT_CACHE"],
    "RAG_IME_MLX_PROMPT_CACHE_MAX_KV_SIZE": os.environ["PROMPT_CACHE_MAX_KV_SIZE"],
    "RAG_IME_MLX_PREFIX_CACHE": os.environ["PREFIX_CACHE"],
    "RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES": os.environ["PREFIX_CACHE_MAX_ENTRIES"],
    "RAG_IME_MLX_PREFIX_CACHE_MAX_MB": os.environ["PREFIX_CACHE_MAX_MB"],
    "RAG_IME_MEMORY_PROFILE": os.environ["MEMORY_PROFILE"],
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "ALL_PROXY": "",
    "http_proxy": "",
    "https_proxy": "",
    "all_proxy": "",
}
prompt_mode = os.environ.get("PROMPT_MODE", "").strip()
if prompt_mode:
    env_vars["RAG_IME_MLX_PROMPT_MODE"] = prompt_mode
hf_home = os.environ.get("HF_HOME_VALUE", "").strip()
if hf_home:
    env_vars["HF_HOME"] = hf_home
    env_vars["HUGGINGFACE_HUB_CACHE"] = str(Path(hf_home) / "hub")

payload = {
    "Label": label,
    "ProgramArguments": args,
    "RunAtLoad": True,
    "KeepAlive": os.environ.get("RAG_IME_LAUNCH_KEEP_ALIVE", "0").strip().lower()
    not in {"0", "false", "no", "off"},
    "ThrottleInterval": 10,
    "StandardOutPath": str(Path(os.environ["LOG_DIR"]) / "mlx-predictor.out.log"),
    "StandardErrorPath": str(Path(os.environ["LOG_DIR"]) / "mlx-predictor.err.log"),
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
sleep 0.2
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "$PLIST_PATH"
echo "http://$HOST:$PORT/"
echo "Logs: $LOG_DIR/mlx-predictor.out.log and $LOG_DIR/mlx-predictor.err.log"

for _attempt in {1..120}; do
  if "$PYTHON_EXECUTABLE" - "$HOST" "$PORT" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request

host = sys.argv[1]
port = sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.0) as response:
    payload = json.loads(response.read().decode("utf-8"))
if not payload.get("ok") or not payload.get("modelLoaded"):
    raise SystemExit(1)
PY
  then
    echo "health: OK"
    exit 0
  fi
  sleep 1
done

echo "health: not ready; inspect $LOG_DIR/mlx-predictor.err.log" >&2
exit 1
