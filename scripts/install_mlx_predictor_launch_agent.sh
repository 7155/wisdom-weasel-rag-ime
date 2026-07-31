#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RAG_IME_MLX_LAUNCH_AGENT_LABEL:-com.rag-ime.mlx-predictor}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/RagIme"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
APP_CODE_DIR="$APP_SUPPORT_DIR/components/mlx-predictor"
MLX_RUNTIME_ROOT="${RAG_IME_MLX_RUNTIME_ROOT:-$APP_CODE_DIR}"
MANAGED_MLX_PYTHON="${RAG_IME_MLX_VENV:-$MLX_RUNTIME_ROOT/.venv}/bin/python"
INSTALL_MARKER="$APP_CODE_DIR/rag-ime-install-marker.json"
MODEL_REGISTRY_EXPLICIT="${RAG_IME_MODEL_REGISTRY+x}"
MODEL_REGISTRY_ORIGIN="${RAG_IME_MODEL_REGISTRY_ORIGIN:-$([[ -n "$MODEL_REGISTRY_EXPLICIT" ]] && printf explicit || printf default)}"
MODEL_REGISTRY_PATH="${RAG_IME_MODEL_REGISTRY:-$APP_SUPPORT_DIR/models.json}"
PORTABLE_MODEL_DIR="${RAG_IME_MODELS_DIR:-$APP_SUPPORT_DIR/Models}/minimind-ime-v2"
LAUNCH_WRAPPER="$APP_CODE_DIR/sidecar_launch.py"
HOST="${RAG_IME_MLX_HOST:-127.0.0.1}"
PORT="${RAG_IME_MLX_PORT:-8767}"
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
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
SOURCE_DIRTY="false"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
  SOURCE_DIRTY="true"
fi

if [[ "$MODEL_REGISTRY_ORIGIN" == "explicit" && ! -f "$MODEL_REGISTRY_PATH" ]]; then
  echo "Explicit model registry does not exist: $MODEL_REGISTRY_PATH" >&2
  exit 1
fi

python_has_required_stdlib() {
  [[ -n "$1" && -x "$1" ]] && "$1" - <<'PY' >/dev/null 2>&1
import hashlib
import sqlite3
import ssl
import sys

hashlib.md5(b"rag-ime").hexdigest()
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
}

detect_model_profile() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*|*minimind-ime-v2*) printf '%s\n' "minimind_ime_v2" ;;
    *Qwen3*|*qwen3*) printf '%s\n' "qwen3_06b_ime_hot" ;;
    *) printf '%s\n' "qwen3_06b_ime_hot" ;;
  esac
}

PYTHON_EXECUTABLE="${RAG_IME_MLX_PYTHON:-}"
PYTHON_ORIGIN="explicit"
if [[ -z "$PYTHON_EXECUTABLE" ]]; then
  PYTHON_EXECUTABLE="$MANAGED_MLX_PYTHON"
  PYTHON_ORIGIN="managed"
fi

if [[ "$PYTHON_ORIGIN" == "managed" ]] && ! python_has_required_stdlib "$PYTHON_EXECUTABLE"; then
  if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
    echo "managed MLX runtime is not ready for dry-run: $PYTHON_EXECUTABLE" >&2
    echo "Run scripts/setup_mlx_predictor_env.sh first or set RAG_IME_MLX_PYTHON explicitly." >&2
    exit 1
  fi
  PYTHON_EXECUTABLE="$(
    RAG_IME_APP_SUPPORT_DIR="$APP_SUPPORT_DIR" \
    RAG_IME_MLX_RUNTIME_ROOT="$MLX_RUNTIME_ROOT" \
      "$ROOT/scripts/setup_mlx_predictor_env.sh"
  )"
fi
if [[ "$PYTHON_ORIGIN" == "managed" ]] \
  && [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "true" && "$DRY_RUN" != "TRUE" ]] \
  && ! "$PYTHON_EXECUTABLE" -c 'import mlx_lm' >/dev/null 2>&1; then
  PYTHON_EXECUTABLE="$(
    RAG_IME_APP_SUPPORT_DIR="$APP_SUPPORT_DIR" \
    RAG_IME_MLX_RUNTIME_ROOT="$MLX_RUNTIME_ROOT" \
      "$ROOT/scripts/setup_mlx_predictor_env.sh"
  )"
fi

if ! python_has_required_stdlib "$PYTHON_EXECUTABLE"; then
  echo "python executable cannot import required stdlib modules (sqlite3/hashlib/ssl): $PYTHON_EXECUTABLE" >&2
  echo "Set RAG_IME_MLX_PYTHON to a healthy Python 3.12+." >&2
  exit 1
fi

REGISTERED_MODEL_PATH=""
REGISTERED_MODEL_PROFILE=""
REGISTERED_MODEL_PROMPT_MODE=""
REGISTERED_MODEL_ID=""
REGISTERED_MODEL_FINGERPRINT=""
REGISTERED_MODEL_RUNTIME=""
if [[ -f "$MODEL_REGISTRY_PATH" ]]; then
  if ! REGISTERED_RUNTIME_ENV="$(PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_EXECUTABLE" -m rag_ime.model_runtime --registry "$MODEL_REGISTRY_PATH" --lane hot --format shell)"; then
    echo "Active hot model registry entry is invalid or its artifact is missing: $MODEL_REGISTRY_PATH" >&2
    exit 1
  fi
  eval "$REGISTERED_RUNTIME_ENV"
  REGISTERED_MODEL_PATH="${RAG_IME_REGISTERED_MODEL_PATH:-}"
  REGISTERED_MODEL_PROFILE="${RAG_IME_REGISTERED_MODEL_PROFILE:-}"
  REGISTERED_MODEL_PROMPT_MODE="${RAG_IME_REGISTERED_MODEL_PROMPT_MODE:-}"
  REGISTERED_MODEL_ID="${RAG_IME_REGISTERED_MODEL_ID:-}"
  REGISTERED_MODEL_FINGERPRINT="${RAG_IME_REGISTERED_MODEL_FINGERPRINT:-}"
  REGISTERED_MODEL_RUNTIME="${RAG_IME_REGISTERED_MODEL_RUNTIME:-}"
  HOST="${RAG_IME_MLX_HOST:-$HOST}"
  PORT="${RAG_IME_MLX_PORT:-$PORT}"
fi

if [[ -n "$REGISTERED_MODEL_RUNTIME" && "$REGISTERED_MODEL_RUNTIME" != "mlx" && -z "${RAG_IME_MLX_MODEL:-}" ]]; then
  echo "Active hot model runtime is $REGISTERED_MODEL_RUNTIME, not mlx; refusing to launch the MLX service." >&2
  exit 1
fi

MODEL="${RAG_IME_MLX_MODEL:-${REGISTERED_MODEL_PATH:-$PORTABLE_MODEL_DIR}}"
INFERRED_PROFILE="$(detect_model_profile "$MODEL")"
INFERRED_MODEL_ID="$(basename "${MODEL:-local-model}")"
PROFILE="${RAG_IME_MLX_PROFILE:-${RAG_IME_PREDICTOR_PROFILE:-${REGISTERED_MODEL_PROFILE:-$INFERRED_PROFILE}}}"
PROMPT_MODE="${RAG_IME_MLX_PROMPT_MODE:-$REGISTERED_MODEL_PROMPT_MODE}"
MAX_TOKENS="${RAG_IME_MLX_MAX_TOKENS:-$MAX_TOKENS}"
TEMPERATURE="${RAG_IME_MLX_TEMPERATURE:-$TEMPERATURE}"
TOP_P="${RAG_IME_MLX_TOP_P:-$TOP_P}"
MODEL_ID="${RAG_IME_MODEL_ID:-${REGISTERED_MODEL_ID:-$INFERRED_MODEL_ID}}"
MODEL_FINGERPRINT="${RAG_IME_MODEL_FINGERPRINT:-$REGISTERED_MODEL_FINGERPRINT}"

if [[ ! -d "$MODEL" && "$DRY_RUN" != "1" && "$DRY_RUN" != "true" && "$DRY_RUN" != "TRUE" ]]; then
  echo "MLX model directory not found: $MODEL" >&2
  echo "Register a model with: python3 -m rag_ime.model_registry register --model-id ID --path PATH --profile minimind_ime_v2 --prompt-mode base-completion" >&2
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

"$PYTHON_EXECUTABLE" - "$INSTALL_MARKER" "$ROOT" "$SOURCE_COMMIT" "$SOURCE_DIRTY" "$PYTHON_EXECUTABLE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.component-install-marker.v1",
            "component": "mlx-predictor",
            "sourceRoot": sys.argv[2],
            "sourceCommit": sys.argv[3],
            "sourceDirty": sys.argv[4] == "true",
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "pythonExecutable": sys.argv[5],
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

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
MODEL_ID="$MODEL_ID" \
MODEL_FINGERPRINT="$MODEL_FINGERPRINT" \
MODEL_REGISTRY_PATH="$MODEL_REGISTRY_PATH" \
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
    "RAG_IME_INSTALL_MARKER": str(Path(app_code_dir) / "rag-ime-install-marker.json"),
    "RAG_IME_MLX_MODEL": os.environ["MODEL"],
    "RAG_IME_MODEL_ID": os.environ["MODEL_ID"],
    "RAG_IME_MODEL_FINGERPRINT": os.environ["MODEL_FINGERPRINT"],
    "RAG_IME_MODEL_REGISTRY": os.environ["MODEL_REGISTRY_PATH"],
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

kill_stale_mlx_predictor_processes() {
  if [[ "${RAG_IME_KILL_STALE_MLX_ON_INSTALL:-1}" == "0" ]]; then
    return 0
  fi
  pkill -f 'sidecar_launch.py.*mlx-predictor-server' >/dev/null 2>&1 || true
  pkill -f 'rag_ime.cli.*mlx-predictor-server' >/dev/null 2>&1 || true
  if command -v lsof >/dev/null 2>&1; then
    local pid
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      ps -p "$pid" -o command= | grep -E 'sidecar_launch.py|rag_ime.cli' >/dev/null 2>&1 || continue
      kill "$pid" >/dev/null 2>&1 || true
    done < <(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
  fi
}

wait_for_mlx_port_release() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local attempt
  for attempt in {1..25}; do
    if ! lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "MLX predictor port $PORT is still occupied after stale-process cleanup" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  return 1
}

bootstrap_launch_agent() {
  local attempt
  local delay
  local error_log

  error_log="$(mktemp "${TMPDIR:-/tmp}/rag-ime-mlx-launchctl-bootstrap.XXXXXX")"
  trap 'rm -f "$error_log"' RETURN

  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "$DOMAIN" "$PLIST_PATH" 2>"$error_log"; then
      return 0
    fi
    if [[ "$attempt" == "5" ]]; then
      break
    fi
    delay="$(awk "BEGIN { printf \"%.1f\", $attempt * 0.4 }")"
    sleep "$delay"
  done

  echo "launchctl bootstrap failed for $DOMAIN/$LABEL" >&2
  cat "$error_log" >&2
  return 1
}

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
kill_stale_mlx_predictor_processes
wait_for_mlx_port_release
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
sleep 0.2
bootstrap_launch_agent

echo "$PLIST_PATH"
DISPLAY_HOST="$HOST"
if [[ "$DISPLAY_HOST" == *:* && "$DISPLAY_HOST" != \[*\] ]]; then
  DISPLAY_HOST="[$DISPLAY_HOST]"
fi
echo "http://$DISPLAY_HOST:$PORT/"
echo "Logs: $LOG_DIR/mlx-predictor.out.log and $LOG_DIR/mlx-predictor.err.log"

for _attempt in {1..120}; do
  if "$PYTHON_EXECUTABLE" - \
    "$HOST" \
    "$PORT" \
    "$MODEL" \
    "$MODEL_FINGERPRINT" \
    "$PROFILE" \
    "$PROMPT_MODE" \
    "$MAX_TOKENS" \
    "$TEMPERATURE" \
    "$TOP_P" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

host = sys.argv[1]
port = sys.argv[2]
expected_model = Path(sys.argv[3]).expanduser().resolve()
expected_fingerprint = sys.argv[4].strip().lower()
expected_profile = sys.argv[5]
expected_prompt_mode = sys.argv[6]
expected_max_tokens = sys.argv[7]
expected_temperature = sys.argv[8]
expected_top_p = sys.argv[9]
url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(f"http://{url_host}:{port}/health", timeout=1.0) as response:
    payload = json.loads(response.read().decode("utf-8"))
if not payload.get("ok") or not payload.get("modelLoaded"):
    raise SystemExit(1)
model_profile = payload.get("modelProfile")
if not isinstance(model_profile, dict):
    raise SystemExit(1)
if str(model_profile.get("id") or "") != expected_profile:
    raise SystemExit(1)
if str(payload.get("promptMode") or "") != expected_prompt_mode:
    raise SystemExit(1)
try:
    runtime_max_tokens = int(model_profile.get("maxTokens"))
    configured_max_tokens = int(expected_max_tokens)
except (TypeError, ValueError):
    raise SystemExit(1)
if runtime_max_tokens != configured_max_tokens:
    raise SystemExit(1)
runtime_config = payload.get("runtimeConfig")
if not isinstance(runtime_config, dict):
    raise SystemExit(1)
try:
    runtime_temperature = float(runtime_config.get("temperature"))
    runtime_top_p = float(runtime_config.get("topP"))
    configured_temperature = float(expected_temperature)
    configured_top_p = float(expected_top_p)
except (TypeError, ValueError):
    raise SystemExit(1)
if abs(runtime_temperature - configured_temperature) > 1e-9:
    raise SystemExit(1)
if abs(runtime_top_p - configured_top_p) > 1e-9:
    raise SystemExit(1)
runtime_model = Path(str(payload.get("model") or "")).expanduser().resolve()
runtime_fingerprint = str(payload.get("modelFingerprint") or "").strip().lower()

def matching_sha256(first: str, second: str) -> bool:
    if not first.startswith("sha256:") or not second.startswith("sha256:"):
        return False
    first_digest = first.removeprefix("sha256:")
    second_digest = second.removeprefix("sha256:")
    if len(first_digest) not in {16, 64} or len(second_digest) not in {16, 64}:
        return False
    return first_digest == second_digest or first_digest.startswith(second_digest) or second_digest.startswith(first_digest)

if runtime_model != expected_model and not matching_sha256(expected_fingerprint, runtime_fingerprint):
    raise SystemExit(1)
expected_digest = expected_fingerprint.removeprefix("sha256:") if expected_fingerprint.startswith("sha256:") else ""
if len(expected_digest) == 64 and not matching_sha256(expected_fingerprint, runtime_fingerprint):
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
