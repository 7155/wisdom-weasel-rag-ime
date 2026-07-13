#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY_PROFILE="${RAG_IME_MEMORY_PROFILE:-low}"
RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-foreground-rag-proof}"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
MODEL_REGISTRY_EXPLICIT="${RAG_IME_MODEL_REGISTRY+x}"
MODEL_REGISTRY_PATH="${RAG_IME_MODEL_REGISTRY:-$APP_SUPPORT_DIR/models.json}"
MODEL_REGISTRY_ORIGIN="${RAG_IME_MODEL_REGISTRY_ORIGIN:-$([[ -n "$MODEL_REGISTRY_EXPLICIT" ]] && printf explicit || printf default)}"
PORTABLE_MODELS_DIR="${RAG_IME_MODELS_DIR:-$APP_SUPPORT_DIR/Models}"
EMBEDDING_PROVIDER_WAS_EXPLICIT="${RAG_IME_EMBEDDING_PROVIDER+x}"
PREFERRED_MLX_BGE_Q8_MODEL="${RAG_IME_MLX_BGE_Q8_MODEL:-$PORTABLE_MODELS_DIR/bge-base-zh-v1.5-mlx-q8}"

if [[ -n "$MODEL_REGISTRY_EXPLICIT" && ! -f "$MODEL_REGISTRY_PATH" ]]; then
  echo "Explicit model registry does not exist: $MODEL_REGISTRY_PATH" >&2
  exit 1
fi

is_low_memory_profile() {
  local normalized
  normalized="$(printf '%s' "$MEMORY_PROFILE" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    low|safe|memory|memory-safe|minimal) return 0 ;;
    *) return 1 ;;
  esac
}

detect_mlx_model() {
  local candidate
  local candidates=()
  if is_low_memory_profile; then
    candidates=(
      "$PORTABLE_MODELS_DIR/minimind-ime-v2"
      "$PORTABLE_MODELS_DIR/minimind-ime-v2-q8"
      "$ROOT/../models/mlx/Qwen3-0.6B-4bit"
    )
  else
    candidates=(
      "$PORTABLE_MODELS_DIR/minimind-ime-v2"
      "$PORTABLE_MODELS_DIR/minimind-ime-v2-fp16"
      "$ROOT/../models/mlx/Qwen3-0.6B-4bit"
    )
  fi
  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

detect_sidecar_python() {
  local candidate
  local candidates=()
  candidates+=("${RAG_IME_PYTHON:-}")
  candidates+=("$ROOT/.venv/bin/python")
  candidates+=("$ROOT/.venv-mlx313/bin/python")
  candidates+=("$ROOT/.venv-mlx314sys/bin/python")
  candidates+=("/opt/homebrew/bin/python3")
  candidates+=("$(command -v python3 2>/dev/null || true)")
  candidates+=("/usr/local/bin/python3")
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_registered_model() {
  local python_exec
  if [[ -n "${RAG_IME_PYTHON:-}" && -x "$RAG_IME_PYTHON" ]]; then
    python_exec="$RAG_IME_PYTHON"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    python_exec="$ROOT/.venv/bin/python"
  else
    python_exec="$(command -v python3 2>/dev/null || true)"
  fi
  [[ -n "$python_exec" && -x "$python_exec" && -f "$MODEL_REGISTRY_PATH" ]] || return 1
  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$python_exec" -m rag_ime.model_runtime \
    --registry "$MODEL_REGISTRY_PATH" --lane hot --format shell
}

detect_mlx_prompt_mode() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*|*minimind-ime-v2*) printf '%s\n' "base-completion" ;;
    *) printf '%s\n' "" ;;
  esac
}

detect_mlx_profile() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*|*minimind-ime-v2*) printf '%s\n' "minimind_ime_v2" ;;
    *Qwen3*|*qwen3*) printf '%s\n' "qwen3_06b_ime_hot" ;;
    *) printf '%s\n' "qwen3_06b_ime_hot" ;;
  esac
}

detect_predictor_stream_first() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*|*minimind-ime-v2*) printf '%s\n' "0" ;;
    *) printf '%s\n' "1" ;;
  esac
}

RAG_IME_REGISTERED_MODEL_PATH=""
RAG_IME_REGISTERED_MODEL_PROFILE=""
RAG_IME_REGISTERED_MODEL_PROMPT_MODE=""
RAG_IME_REGISTERED_MODEL_ID=""
RAG_IME_REGISTERED_MODEL_FINGERPRINT=""
RAG_IME_MODEL_RUNTIME=""
RAG_IME_MODEL_RUNTIME_LIFECYCLE=""
RAG_IME_MODEL_RUNTIME_READY="0"
if [[ -f "$MODEL_REGISTRY_PATH" ]]; then
  if ! REGISTERED_RUNTIME_ENV="$(resolve_registered_model)"; then
    echo "Active hot model registry entry is invalid or its artifact is missing: $MODEL_REGISTRY_PATH" >&2
    exit 1
  fi
  eval "$REGISTERED_RUNTIME_ENV"
fi

MODEL_RUNTIME="${RAG_IME_MODEL_RUNTIME:-mlx}"

if [[ "$MODEL_RUNTIME" == "mlx" ]]; then
  MODEL_DIR="${RAG_IME_MLX_MODEL:-${RAG_IME_REGISTERED_MODEL_PATH:-$(detect_mlx_model || true)}}"
else
  MODEL_DIR="${RAG_IME_PREDICTOR_MODEL:-${RAG_IME_REGISTERED_MODEL_NAME:-${RAG_IME_REGISTERED_MODEL_PATH:-}}}"
fi
LEGACY_MODEL_PROFILE="$(detect_mlx_profile "$MODEL_DIR")"
LEGACY_MODEL_ID="$(basename "${MODEL_DIR:-local-model}")"
MLX_PYTHON=""
if [[ "$MODEL_RUNTIME" == "mlx" ]]; then
  if [[ -n "${RAG_IME_MLX_PYTHON:-}" ]]; then
    MLX_PYTHON="$RAG_IME_MLX_PYTHON"
  elif [[ -x "$ROOT/.venv-mlx313/bin/python" ]]; then
    MLX_PYTHON="$ROOT/.venv-mlx313/bin/python"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    MLX_PYTHON="$ROOT/.venv/bin/python"
  elif [[ -x "$ROOT/.venv-mlx314sys/bin/python" ]]; then
    MLX_PYTHON="$ROOT/.venv-mlx314sys/bin/python"
  fi
fi

if [[ "$MODEL_RUNTIME" == "mlx" && ! -d "$MODEL_DIR" ]]; then
  echo "MLX model directory not found: $MODEL_DIR" >&2
  echo "Set RAG_IME_MLX_MODEL to a local MLX model directory." >&2
  exit 1
fi

if [[ "$MODEL_RUNTIME" == "mlx" && ! -x "$MLX_PYTHON" ]]; then
  echo "MLX python is not executable: $MLX_PYTHON" >&2
  echo "Set RAG_IME_MLX_PYTHON to a Python that can import mlx_lm." >&2
  exit 1
fi

SIDECAR_PYTHON="$(detect_sidecar_python || true)"
if [[ -z "$SIDECAR_PYTHON" || ! -x "$SIDECAR_PYTHON" ]]; then
  echo "Sidecar Python is not available; set RAG_IME_PYTHON to an executable Python 3.11+." >&2
  exit 1
fi
eval "$(PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$SIDECAR_PYTHON" -m rag_ime.runtime_profile --profile "$RUNTIME_PROFILE" --format shell)"

export RAG_IME_MODEL_REGISTRY="$MODEL_REGISTRY_PATH"
export RAG_IME_MODEL_REGISTRY_ORIGIN="$MODEL_REGISTRY_ORIGIN"
export RAG_IME_MODEL_RUNTIME="$MODEL_RUNTIME"
export RAG_IME_MODEL_ID="${RAG_IME_MODEL_ID:-${RAG_IME_REGISTERED_MODEL_ID:-$LEGACY_MODEL_ID}}"
export RAG_IME_MODEL_FINGERPRINT="${RAG_IME_MODEL_FINGERPRINT:-$RAG_IME_REGISTERED_MODEL_FINGERPRINT}"
if [[ "$MODEL_RUNTIME" == "mlx" ]]; then
  export RAG_IME_MLX_MODEL="$MODEL_DIR"
  export RAG_IME_MLX_PYTHON="$MLX_PYTHON"
  export RAG_IME_MLX_HOST="${RAG_IME_MLX_HOST:-127.0.0.1}"
  export RAG_IME_MLX_PORT="${RAG_IME_MLX_PORT:-8767}"
fi
export RAG_IME_PYTHON="$SIDECAR_PYTHON"
export RAG_IME_MEMORY_PROFILE="$MEMORY_PROFILE"
export RAG_IME_MLX_MAX_TOKENS="${RAG_IME_MLX_MAX_TOKENS:-8}"
export RAG_IME_MLX_TEMPERATURE="${RAG_IME_MLX_TEMPERATURE:-0.15}"
export RAG_IME_MLX_TOP_P="${RAG_IME_MLX_TOP_P:-0.85}"
if is_low_memory_profile; then
  export RAG_IME_MLX_PROMPT_CACHE="${RAG_IME_MLX_PROMPT_CACHE:-0}"
else
  export RAG_IME_MLX_PROMPT_CACHE="${RAG_IME_MLX_PROMPT_CACHE:-1}"
fi
export RAG_IME_MLX_PREFIX_CACHE="${RAG_IME_MLX_PREFIX_CACHE:-0}"
export RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES="${RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES:-8}"
export RAG_IME_MLX_PREFIX_CACHE_MAX_MB="${RAG_IME_MLX_PREFIX_CACHE_MAX_MB:-32}"
export RAG_IME_MLX_PROFILE="${RAG_IME_MLX_PROFILE:-${RAG_IME_REGISTERED_MODEL_PROFILE:-$LEGACY_MODEL_PROFILE}}"
export RAG_IME_MLX_PROMPT_MODE="${RAG_IME_MLX_PROMPT_MODE:-${RAG_IME_REGISTERED_MODEL_PROMPT_MODE:-$(detect_mlx_prompt_mode "$MODEL_DIR")}}"
export RAG_IME_LAUNCH_KEEP_ALIVE="${RAG_IME_LAUNCH_KEEP_ALIVE:-0}"

MLX_BASE_HOST="${RAG_IME_MLX_HOST:-127.0.0.1}"
if [[ "$MLX_BASE_HOST" == *:* && "$MLX_BASE_HOST" != \[*\] ]]; then
  MLX_BASE_HOST="[$MLX_BASE_HOST]"
fi
DEFAULT_PREDICTOR_BASE_URL="http://$MLX_BASE_HOST:${RAG_IME_MLX_PORT:-8767}"
export RAG_IME_PREDICTOR_PROVIDER="${RAG_IME_PREDICTOR_PROVIDER:-$MODEL_RUNTIME}"
export RAG_IME_PREDICTOR_BASE_URL="${RAG_IME_PREDICTOR_BASE_URL:-${RAG_IME_REGISTERED_MODEL_ENDPOINT:-$DEFAULT_PREDICTOR_BASE_URL}}"
export RAG_IME_PREDICTOR_MODEL="${RAG_IME_PREDICTOR_MODEL:-$MODEL_DIR}"
export RAG_IME_PREDICTOR_PROFILE="${RAG_IME_PREDICTOR_PROFILE:-${RAG_IME_REGISTERED_MODEL_PROFILE:-$LEGACY_MODEL_PROFILE}}"
export RAG_IME_PREDICTOR_PROMPT_MODE="${RAG_IME_PREDICTOR_PROMPT_MODE:-${RAG_IME_REGISTERED_MODEL_PROMPT_MODE:-}}"
export RAG_IME_PREDICTOR_STREAM_FIRST="${RAG_IME_PREDICTOR_STREAM_FIRST:-$(detect_predictor_stream_first "$MODEL_DIR")}"
export RAG_IME_PREDICTOR_TIMEOUT_MS="${RAG_IME_PREDICTOR_TIMEOUT_MS:-3000}"
export RAG_IME_PREDICTOR_MAX_TOKENS="${RAG_IME_PREDICTOR_MAX_TOKENS:-8}"
export RAG_IME_PREDICTOR_TEMPERATURE="${RAG_IME_PREDICTOR_TEMPERATURE:-0.15}"
export RAG_IME_PREDICTOR_TOP_P="${RAG_IME_PREDICTOR_TOP_P:-0.85}"
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS="${RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS:-0}"
export RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION="${RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION:-1}"
export RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL="${RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL:-1}"
if [[ -z "${RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE:-}" ]]; then
  if [[ "$RUNTIME_PROFILE" == "foreground-rag-proof" ]]; then
    RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE="observe"
  else
    RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE="strict"
  fi
fi
export RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE
export RAG_IME_ENABLE_COMPOSING_MODEL="${RAG_IME_ENABLE_COMPOSING_MODEL:-$RAG_IME_PROFILE_COMPOSITION_AI}"
export RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL="${RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL:-$RAG_IME_PROFILE_PINYIN_CONSTRAINED_MODEL}"
export RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS="${RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS:-180}"
export RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS="${RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS:-180}"
export RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS="${RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS:-8}"
export RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT="${RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT:-$RAG_IME_PROFILE_REQUIRE_FOREGROUND_CONTEXT}"
export RAG_IME_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS="${RAG_IME_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS:-$RAG_IME_PROFILE_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS}"
export RAG_IME_POST_COMMIT_PENDING_PREVIEW="${RAG_IME_POST_COMMIT_PENDING_PREVIEW:-$RAG_IME_PROFILE_ASSISTANT_PENDING_PREVIEW}"
export RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES="${RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES:-32}"
export RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES="${RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES:-16}"
export RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES="${RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES:-128}"
export RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES="${RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES:-32}"
export RAG_IME_SUGGESTION_CACHE_SIZE="${RAG_IME_SUGGESTION_CACHE_SIZE:-32}"
export RAG_IME_HYBRID_RAG_CORE="${RAG_IME_HYBRID_RAG_CORE:-$RAG_IME_PROFILE_HYBRID_RAG_CORE}"
export RAG_IME_RAG_DIRECT_DISPLAY="${RAG_IME_RAG_DIRECT_DISPLAY:-$RAG_IME_PROFILE_RAG_DIRECT_DISPLAY}"
export RAG_IME_AUTO_PREDICT_IDLE_MS="${RAG_IME_AUTO_PREDICT_IDLE_MS:-420}"
export RAG_IME_AUTO_PREDICT_MIN_DELTA_CHARS="${RAG_IME_AUTO_PREDICT_MIN_DELTA_CHARS:-8}"
export RAG_IME_AUTO_PREDICT_MAX_CALLS_PER_10S="${RAG_IME_AUTO_PREDICT_MAX_CALLS_PER_10S:-2}"
export RAG_IME_AUTO_PREDICT_IGNORE_COOLDOWN_MS="${RAG_IME_AUTO_PREDICT_IGNORE_COOLDOWN_MS:-2500}"
export RAG_IME_POST_COMMIT_ACTIVE_RAG_BUTTON="${RAG_IME_POST_COMMIT_ACTIVE_RAG_BUTTON:-1}"
export RAG_IME_T0_DIRECT_MEMORY_THRESHOLD="${RAG_IME_T0_DIRECT_MEMORY_THRESHOLD:-0.86}"
export RAG_IME_DEEPSEEK_THINKING="${RAG_IME_DEEPSEEK_THINKING:-disabled}"
export RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS="${RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS:-0}"

existing_sidecar_environment() {
  local key="$1"
  local plist="$HOME/Library/LaunchAgents/${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}.plist"
  [[ -f "$plist" ]] || return 0
  /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:$key" "$plist" 2>/dev/null || true
}

export RAG_IME_ENABLE_LOCAL_VECTOR="${RAG_IME_ENABLE_LOCAL_VECTOR:-1}"
EXISTING_EMBEDDING_PROVIDER="$(existing_sidecar_environment RAG_IME_EMBEDDING_PROVIDER)"
EXISTING_EMBEDDING_MODEL="$(existing_sidecar_environment RAG_IME_EMBEDDING_MODEL)"
EXISTING_EMBEDDING_DIMENSIONS="$(existing_sidecar_environment RAG_IME_EMBEDDING_DIMENSIONS)"
MLX_BGE_MODE="${RAG_IME_ENABLE_MLX_BGE:-auto}"
if [[ "$MLX_BGE_MODE" == "auto" ]]; then
  if [[ -n "$EMBEDDING_PROVIDER_WAS_EXPLICIT" ]]; then
    MLX_BGE_MODE=0
  elif [[ "$EXISTING_EMBEDDING_PROVIDER" == "local-bge-mlx" ]]; then
    MLX_BGE_MODE=1
  elif [[ -z "$EXISTING_EMBEDDING_PROVIDER" || "$EXISTING_EMBEDDING_PROVIDER" == "local-hash" ]]; then
    [[ -d "$PREFERRED_MLX_BGE_Q8_MODEL" ]] && MLX_BGE_MODE=1 || MLX_BGE_MODE=0
  else
    MLX_BGE_MODE=0
  fi
fi

if [[ "$MLX_BGE_MODE" == "1" ]]; then
  if [[ -n "$EMBEDDING_PROVIDER_WAS_EXPLICIT" ]]; then
    NORMALIZED_EXPLICIT_EMBEDDING_PROVIDER="$(printf '%s' "$RAG_IME_EMBEDDING_PROVIDER" | tr '[:upper:]' '[:lower:]')"
    case "$NORMALIZED_EXPLICIT_EMBEDDING_PROVIDER" in
      local-bge-mlx|mlx-bert|mlx-bge) ;;
      *)
        echo "RAG_IME_ENABLE_MLX_BGE=1 conflicts with explicit RAG_IME_EMBEDDING_PROVIDER=$RAG_IME_EMBEDDING_PROVIDER" >&2
        exit 1
        ;;
    esac
  fi
  DEFAULT_MLX_BGE_MODEL="$PREFERRED_MLX_BGE_Q8_MODEL"
  if [[ "$EXISTING_EMBEDDING_PROVIDER" == "local-bge-mlx" && -n "$EXISTING_EMBEDDING_MODEL" ]]; then
    DEFAULT_MLX_BGE_MODEL="$EXISTING_EMBEDDING_MODEL"
  fi
  RAG_IME_EMBEDDING_MODEL="${RAG_IME_EMBEDDING_MODEL:-$DEFAULT_MLX_BGE_MODEL}"
  if [[ ! -d "$RAG_IME_EMBEDDING_MODEL" ]]; then
    echo "MLX BGE model directory does not exist: $RAG_IME_EMBEDDING_MODEL" >&2
    exit 1
  fi
  export RAG_IME_EMBEDDING_PROVIDER="local-bge-mlx"
  export RAG_IME_EMBEDDING_MODEL
  export RAG_IME_EMBEDDING_BITS="${RAG_IME_EMBEDDING_BITS:-8}"
  export RAG_IME_EMBEDDING_GROUP_SIZE="${RAG_IME_EMBEDDING_GROUP_SIZE:-32}"
  export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-768}"
elif [[ "${RAG_IME_ENABLE_LOCAL_BGE:-0}" == "1" ]]; then
  export RAG_IME_EMBEDDING_PROVIDER="local-bge"
  export RAG_IME_EMBEDDING_MODEL="${RAG_IME_EMBEDDING_MODEL:-BAAI/bge-base-zh-v1.5}"
  export RAG_IME_EMBEDDING_CACHE_DIR="${RAG_IME_EMBEDDING_CACHE_DIR:-$ROOT/.rag-ime-data/hf-cache/hub}"
  export RAG_IME_EMBEDDING_LOCAL_FILES_ONLY="${RAG_IME_EMBEDDING_LOCAL_FILES_ONLY:-1}"
  export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-768}"
else
  if [[ "$MLX_BGE_MODE" != "0" ]]; then
    echo "RAG_IME_ENABLE_MLX_BGE must be auto, 0, or 1: $MLX_BGE_MODE" >&2
    exit 1
  fi
  if [[ -z "${RAG_IME_EMBEDDING_PROVIDER:-}" ]]; then
    if [[ "${RAG_IME_ENABLE_MLX_BGE:-auto}" == "0" && "$EXISTING_EMBEDDING_PROVIDER" == "local-bge-mlx" ]]; then
      export RAG_IME_EMBEDDING_PROVIDER="local-hash"
    else
      export RAG_IME_EMBEDDING_PROVIDER="${EXISTING_EMBEDDING_PROVIDER:-local-hash}"
    fi
  fi
  if [[ "$RAG_IME_EMBEDDING_PROVIDER" == "local-hash" ]]; then
    export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-96}"
  else
    export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-${EXISTING_EMBEDDING_DIMENSIONS:-1024}}"
  fi
fi
export RAG_IME_EMBEDDING_CACHE_SIZE="${RAG_IME_EMBEDDING_CACHE_SIZE:-32}"
export RAG_IME_VECTOR_CANDIDATES="${RAG_IME_VECTOR_CANDIDATES:-32}"
export RAG_IME_VECTOR_WEIGHT="${RAG_IME_VECTOR_WEIGHT:-1.4}"
export RAG_IME_VECTOR_AUTO_REBUILD_LIMIT="${RAG_IME_VECTOR_AUTO_REBUILD_LIMIT:-1500}"

export RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-$RAG_IME_PROFILE_POST_COMMIT_COMPLETION_TTL_MS}"
export RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_HARD_TIMEOUT_MS}"
export RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_BUDGET_MS}"
export RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-$RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS}"
export RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-$RAG_IME_PROFILE_SQUIRREL_TIMEOUT_MS}"
export RAG_IME_SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
export RAG_IME_INPUT_SOURCE_BUNDLE_ID="${RAG_IME_INPUT_SOURCE_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"

STOP_OLD_MLX_AFTER_SIDECAR=0
SIDECAR_PLIST_PATH="$HOME/Library/LaunchAgents/${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}.plist"
SIDECAR_PLIST_BACKUP=""
if [[ "$MODEL_RUNTIME" == "mlx" ]]; then
  "$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
else
  if ! PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$SIDECAR_PYTHON" -m rag_ime.model_runtime \
    --registry "$MODEL_REGISTRY_PATH" --lane hot --probe >/dev/null; then
    echo "External predictor runtime is not reachable; refusing to start Sidecar with a dead model route." >&2
    exit 1
  fi
  STOP_OLD_MLX_AFTER_SIDECAR=1
  if [[ "${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}" != "1" && -f "$SIDECAR_PLIST_PATH" ]]; then
    SIDECAR_PLIST_BACKUP="$(mktemp "${TMPDIR:-/tmp}/rag-ime-sidecar-plist.XXXXXX")"
    cp "$SIDECAR_PLIST_PATH" "$SIDECAR_PLIST_BACKUP"
  fi
fi
if ! "$ROOT/scripts/install_sidecar_launch_agent.sh"; then
  if [[ -n "$SIDECAR_PLIST_BACKUP" && -f "$SIDECAR_PLIST_BACKUP" ]]; then
    cp "$SIDECAR_PLIST_BACKUP" "$SIDECAR_PLIST_PATH"
    launchctl bootout "gui/$(id -u)/${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}" >/dev/null 2>&1 || true
    launchctl enable "gui/$(id -u)/${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$SIDECAR_PLIST_PATH" >/dev/null 2>&1 || true
  fi
  rm -f "$SIDECAR_PLIST_BACKUP"
  echo "Sidecar switch failed; the previous MLX runtime was left running." >&2
  exit 1
fi
rm -f "$SIDECAR_PLIST_BACKUP"
if [[ "$STOP_OLD_MLX_AFTER_SIDECAR" == "1" && "${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}" != "1" ]]; then
  launchctl bootout "gui/$(id -u)/com.rag-ime.mlx-predictor" >/dev/null 2>&1 || true
fi
if [[ "${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}" == "1" || "${RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN:-0}" == "1" ]]; then
  echo "dry-run: skipping input-source readiness wait"
  exit 0
fi

FRONTEND_ON_RESTART_DEFAULT="0"
if [[ "$RUNTIME_PROFILE" == "foreground-rag-proof" ]]; then
  FRONTEND_ON_RESTART_DEFAULT="1"
fi
if [[ "${RAG_IME_ENABLE_FRONTEND_ON_RESTART:-$FRONTEND_ON_RESTART_DEFAULT}" != "1" ]]; then
  "$ROOT/scripts/set_rag_ime_frontend_enabled.py" false >/dev/null 2>&1 || true
  echo "RAG-IME backend restarted; frontend remains disabled."
  echo "Set RAG_IME_ENABLE_FRONTEND_ON_RESTART=1 to enable the Squirrel frontend."
  exit 0
fi

"$ROOT/scripts/set_rag_ime_frontend_enabled.py" true
if [[ "${RAG_IME_SKIP_INPUT_SOURCE_READINESS:-0}" == "1" ]]; then
  echo "RAG-IME runtime repaired; Squirrel remains enabled and may be selected when needed."
  exit 0
fi
"$ROOT/scripts/wait_squirrel_typing_ready.sh"
