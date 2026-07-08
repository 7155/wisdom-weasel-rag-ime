#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY_PROFILE="${RAG_IME_MEMORY_PROFILE:-low}"
RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-safe-dev}"

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
      "/Volumes/undo 4t/models/minimind-3-ime-v2-final-mlx-q8"
      "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit"
      "/Volumes/undo 4t/models/mlx-community-Qwen3-0.6B-4bit-local"
      "$ROOT/../models/mlx/Qwen3-0.6B-4bit"
      "/Volumes/undo 4t/models/minimind-3-ime-v2-final-mlx-fp16"
      "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local"
    )
  else
    candidates=(
      "/Volumes/undo 4t/models/minimind-3-ime-v2-final-mlx-fp16"
      "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local"
      "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit"
      "/Volumes/undo 4t/models/mlx-community-Qwen3-0.6B-4bit-local"
      "/Volumes/undo 4t/models/minimind-3-ime-v2-final-mlx-q8"
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

detect_mlx_prompt_mode() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*) printf '%s\n' "base-completion" ;;
    *) printf '%s\n' "" ;;
  esac
}

detect_predictor_stream_first() {
  local model_dir="$1"
  case "$model_dir" in
    *minimind-3-ime-v2-final*) printf '%s\n' "0" ;;
    *) printf '%s\n' "1" ;;
  esac
}

MODEL_DIR="${RAG_IME_MLX_MODEL:-$(detect_mlx_model || true)}"
if [[ -n "${RAG_IME_MLX_PYTHON:-}" ]]; then
  MLX_PYTHON="$RAG_IME_MLX_PYTHON"
elif [[ -x "$ROOT/.venv-mlx313/bin/python" ]]; then
  MLX_PYTHON="$ROOT/.venv-mlx313/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  MLX_PYTHON="$ROOT/.venv/bin/python"
else
  MLX_PYTHON="$ROOT/.venv-mlx314sys/bin/python"
fi

if [[ ! -d "$MODEL_DIR" ]]; then
  echo "MLX model directory not found: $MODEL_DIR" >&2
  echo "Set RAG_IME_MLX_MODEL to a local MLX model directory." >&2
  exit 1
fi

if [[ ! -x "$MLX_PYTHON" ]]; then
  echo "MLX python is not executable: $MLX_PYTHON" >&2
  echo "Set RAG_IME_MLX_PYTHON to a Python that can import mlx_lm." >&2
  exit 1
fi

if [[ -n "${RAG_IME_PYTHON:-}" ]]; then
  SIDECAR_PYTHON="$RAG_IME_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  SIDECAR_PYTHON="$ROOT/.venv/bin/python"
else
  SIDECAR_PYTHON="$MLX_PYTHON"
fi

export RAG_IME_MLX_MODEL="$MODEL_DIR"
export RAG_IME_MLX_PYTHON="$MLX_PYTHON"
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
export RAG_IME_MLX_PROFILE="${RAG_IME_MLX_PROFILE:-qwen3_06b_ime_hot}"
export RAG_IME_MLX_PROMPT_MODE="${RAG_IME_MLX_PROMPT_MODE:-$(detect_mlx_prompt_mode "$MODEL_DIR")}"
export RAG_IME_LAUNCH_KEEP_ALIVE="${RAG_IME_LAUNCH_KEEP_ALIVE:-0}"

export RAG_IME_PREDICTOR_PROVIDER="${RAG_IME_PREDICTOR_PROVIDER:-mlx}"
export RAG_IME_PREDICTOR_BASE_URL="${RAG_IME_PREDICTOR_BASE_URL:-http://127.0.0.1:8767}"
export RAG_IME_PREDICTOR_MODEL="${RAG_IME_PREDICTOR_MODEL:-$MODEL_DIR}"
export RAG_IME_PREDICTOR_PROFILE="${RAG_IME_PREDICTOR_PROFILE:-qwen3_06b_ime_hot}"
export RAG_IME_PREDICTOR_STREAM_FIRST="${RAG_IME_PREDICTOR_STREAM_FIRST:-$(detect_predictor_stream_first "$MODEL_DIR")}"
export RAG_IME_PREDICTOR_TIMEOUT_MS="${RAG_IME_PREDICTOR_TIMEOUT_MS:-3000}"
export RAG_IME_PREDICTOR_MAX_TOKENS="${RAG_IME_PREDICTOR_MAX_TOKENS:-8}"
export RAG_IME_PREDICTOR_TEMPERATURE="${RAG_IME_PREDICTOR_TEMPERATURE:-0.15}"
export RAG_IME_PREDICTOR_TOP_P="${RAG_IME_PREDICTOR_TOP_P:-0.85}"
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS="${RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS:-0}"
export RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION="${RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION:-1}"
export RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL="${RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL:-1}"
export RAG_IME_ENABLE_COMPOSING_MODEL="${RAG_IME_ENABLE_COMPOSING_MODEL:-0}"
export RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL="${RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL:-0}"
export RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS="${RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS:-150}"
export RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS="${RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS:-250}"
export RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS="${RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS:-8}"
export RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT="${RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT:-1}"
export RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES="${RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES:-32}"
export RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES="${RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES:-16}"
export RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES="${RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES:-128}"
export RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES="${RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES:-32}"
export RAG_IME_SUGGESTION_CACHE_SIZE="${RAG_IME_SUGGESTION_CACHE_SIZE:-32}"
export RAG_IME_RAG_DIRECT_DISPLAY="${RAG_IME_RAG_DIRECT_DISPLAY:-0}"
export RAG_IME_DEEPSEEK_THINKING="${RAG_IME_DEEPSEEK_THINKING:-disabled}"
export RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS="${RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS:-1024}"

export RAG_IME_ENABLE_LOCAL_VECTOR="${RAG_IME_ENABLE_LOCAL_VECTOR:-1}"
export RAG_IME_EMBEDDING_PROVIDER="${RAG_IME_EMBEDDING_PROVIDER:-local-hash}"
export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-96}"
export RAG_IME_EMBEDDING_CACHE_SIZE="${RAG_IME_EMBEDDING_CACHE_SIZE:-32}"
export RAG_IME_VECTOR_CANDIDATES="${RAG_IME_VECTOR_CANDIDATES:-32}"
export RAG_IME_VECTOR_WEIGHT="${RAG_IME_VECTOR_WEIGHT:-1.4}"
export RAG_IME_VECTOR_AUTO_REBUILD_LIMIT="${RAG_IME_VECTOR_AUTO_REBUILD_LIMIT:-1500}"

case "$RUNTIME_PROFILE" in
  v1-proof)
    export RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-12000}"
    export RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-12000}"
    export RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-900}"
    export RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-900}"
    export RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-1200}"
    ;;
  safe-dev)
    export RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-6000}"
    export RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-3000}"
    export RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-450}"
    export RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-450}"
    export RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-600}"
    ;;
  *)
    echo "unknown RAG_IME_RUNTIME_PROFILE: $RUNTIME_PROFILE" >&2
    echo "expected one of: safe-dev, v1-proof" >&2
    exit 1
    ;;
esac
export RAG_IME_SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
export RAG_IME_INPUT_SOURCE_BUNDLE_ID="${RAG_IME_INPUT_SOURCE_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"

"$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
"$ROOT/scripts/install_sidecar_launch_agent.sh"
if [[ "${RAG_IME_LAUNCH_AGENT_DRY_RUN:-0}" == "1" || "${RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN:-0}" == "1" ]]; then
  echo "dry-run: skipping input-source readiness wait"
  exit 0
fi

if [[ "${RAG_IME_ENABLE_FRONTEND_ON_RESTART:-0}" != "1" ]]; then
  "$ROOT/scripts/set_rag_ime_frontend_enabled.py" false >/dev/null 2>&1 || true
  echo "RAG-IME backend restarted; frontend remains disabled."
  echo "Set RAG_IME_ENABLE_FRONTEND_ON_RESTART=1 only for a controlled foreground proof run."
  exit 0
fi

"$ROOT/scripts/set_rag_ime_frontend_enabled.py" true
"$ROOT/scripts/wait_squirrel_typing_ready.sh"
