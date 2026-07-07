#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

detect_mlx_model() {
  local candidate
  for candidate in \
    "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
    "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit" \
    "/Volumes/undo 4t/models/mlx-community-Qwen3-0.6B-4bit-local" \
    "$ROOT/../models/mlx/Qwen3-0.6B-4bit"
  do
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
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

export RAG_IME_MLX_MODEL="$MODEL_DIR"
export RAG_IME_MLX_PYTHON="$MLX_PYTHON"
export RAG_IME_MLX_MAX_TOKENS="${RAG_IME_MLX_MAX_TOKENS:-32}"
export RAG_IME_MLX_TEMPERATURE="${RAG_IME_MLX_TEMPERATURE:-0.15}"
export RAG_IME_MLX_TOP_P="${RAG_IME_MLX_TOP_P:-0.85}"
export RAG_IME_MLX_PROMPT_CACHE="${RAG_IME_MLX_PROMPT_CACHE:-1}"
export RAG_IME_MLX_PROFILE="${RAG_IME_MLX_PROFILE:-qwen3_06b_ime_hot}"

export RAG_IME_PREDICTOR_PROVIDER="${RAG_IME_PREDICTOR_PROVIDER:-mlx}"
export RAG_IME_PREDICTOR_BASE_URL="${RAG_IME_PREDICTOR_BASE_URL:-http://127.0.0.1:8767}"
export RAG_IME_PREDICTOR_MODEL="${RAG_IME_PREDICTOR_MODEL:-$MODEL_DIR}"
export RAG_IME_PREDICTOR_PROFILE="${RAG_IME_PREDICTOR_PROFILE:-qwen3_06b_ime_hot}"
export RAG_IME_PREDICTOR_STREAM_FIRST="${RAG_IME_PREDICTOR_STREAM_FIRST:-1}"
export RAG_IME_PREDICTOR_TIMEOUT_MS="${RAG_IME_PREDICTOR_TIMEOUT_MS:-12000}"
export RAG_IME_PREDICTOR_MAX_TOKENS="${RAG_IME_PREDICTOR_MAX_TOKENS:-16}"
export RAG_IME_PREDICTOR_TEMPERATURE="${RAG_IME_PREDICTOR_TEMPERATURE:-0.15}"
export RAG_IME_PREDICTOR_TOP_P="${RAG_IME_PREDICTOR_TOP_P:-0.85}"
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS="${RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS:-0}"
export RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION="${RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION:-1}"
export RAG_IME_ENABLE_COMPOSING_MODEL="${RAG_IME_ENABLE_COMPOSING_MODEL:-0}"
export RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL="${RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL:-0}"
export RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS="${RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS:-150}"
export RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS="${RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS:-250}"
export RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-12000}"
export RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-12000}"
export RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-900}"

export RAG_IME_ENABLE_LOCAL_VECTOR="${RAG_IME_ENABLE_LOCAL_VECTOR:-1}"
export RAG_IME_EMBEDDING_PROVIDER="${RAG_IME_EMBEDDING_PROVIDER:-local-hash}"
export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-96}"
export RAG_IME_VECTOR_CANDIDATES="${RAG_IME_VECTOR_CANDIDATES:-80}"
export RAG_IME_VECTOR_WEIGHT="${RAG_IME_VECTOR_WEIGHT:-1.4}"
export RAG_IME_VECTOR_AUTO_REBUILD_LIMIT="${RAG_IME_VECTOR_AUTO_REBUILD_LIMIT:-5000}"

export RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-900}"
export RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-1200}"
export RAG_IME_SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rag-ime.inputmethod.RagIme.Hans}"
export RAG_IME_INPUT_SOURCE_BUNDLE_ID="${RAG_IME_INPUT_SOURCE_BUNDLE_ID:-im.rag-ime.inputmethod.RagIme}"

"$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
"$ROOT/scripts/install_sidecar_launch_agent.sh"
"$ROOT/scripts/wait_squirrel_typing_ready.sh"
