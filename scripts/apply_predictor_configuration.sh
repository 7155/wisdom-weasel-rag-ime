#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
SIDECAR_PLIST="$HOME/Library/LaunchAgents/com.rag-ime.sidecar.plist"
MODEL_REGISTRY="${RAG_IME_MODEL_REGISTRY:-}"
DB_PATH="${RAG_IME_DB_PATH:-}"

plist_environment_value() {
  local plist_path="$1"
  local key="$2"
  if [[ -f "$plist_path" ]]; then
    /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:$key" "$plist_path" 2>/dev/null || true
  fi
}

if [[ -z "$MODEL_REGISTRY" ]]; then
  MODEL_REGISTRY="$(plist_environment_value "$SIDECAR_PLIST" RAG_IME_MODEL_REGISTRY)"
fi
if [[ -z "$MODEL_REGISTRY" ]]; then
  MODEL_REGISTRY="$APP_SUPPORT_DIR/models.json"
fi
if [[ -z "$DB_PATH" ]]; then
  DB_PATH="$(plist_environment_value "$SIDECAR_PLIST" RAG_IME_DB_PATH)"
fi
if [[ -z "$DB_PATH" ]]; then
  DB_PATH="$APP_SUPPORT_DIR/rag-ime.sqlite"
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "Control Center settings database was not found: $DB_PATH" >&2
  exit 1
fi
if [[ ! -f "$MODEL_REGISTRY" ]]; then
  echo "Model registry was not found: $MODEL_REGISTRY" >&2
  exit 1
fi

PYTHON=""
for candidate in \
  "$APP_SUPPORT_DIR/KnowledgeRuntime/.venv/bin/python" \
  "$ROOT/.venv/bin/python" \
  "$ROOT/.venv-mlx313/bin/python" \
  "$ROOT/.venv-mlx314sys/bin/python" \
  /opt/homebrew/bin/python3 \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]] \
    && PYTHONPATH="$ROOT" "$candidate" -c 'import rag_ime.predictor_configuration' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "No compatible Python runtime can load rag_ime.predictor_configuration" >&2
  exit 1
fi

backup="$(mktemp "${TMPDIR:-/tmp}/rag-ime-models.XXXXXX.json")"
cp "$MODEL_REGISTRY" "$backup"
registry_changed=0
rollback() {
  local exit_code=$?
  trap - ERR INT TERM
  if [[ "$registry_changed" == "1" && -f "$backup" ]]; then
    cp "$backup" "$MODEL_REGISTRY"
    echo "Predictor apply failed; restored the previous model registry." >&2
  fi
  rm -f "$backup"
  exit "$exit_code"
}
trap rollback ERR INT TERM

# Desired values come only from the validated settings database and the model
# registry. Do not let stale Control Center process variables shadow them.
unset RAG_IME_MODEL_ID \
  RAG_IME_PREDICTOR_MODEL RAG_IME_PREDICTOR_PROFILE \
  RAG_IME_PREDICTOR_PROMPT_MODE RAG_IME_PREDICTOR_MAX_TOKENS \
  RAG_IME_PREDICTOR_TEMPERATURE RAG_IME_PREDICTOR_TOP_P \
  RAG_IME_MLX_MODEL RAG_IME_MLX_PROFILE RAG_IME_MLX_PROMPT_MODE \
  RAG_IME_MLX_MAX_TOKENS RAG_IME_MLX_TEMPERATURE RAG_IME_MLX_TOP_P
export RAG_IME_MODEL_REGISTRY="$MODEL_REGISTRY"
export RAG_IME_DB_PATH="$DB_PATH"

PYTHONPATH="$ROOT" "$PYTHON" -m rag_ime.predictor_configuration \
  preview --db "$DB_PATH" --registry "$MODEL_REGISTRY" >/dev/null
PYTHONPATH="$ROOT" "$PYTHON" -m rag_ime.predictor_configuration \
  apply --db "$DB_PATH" --registry "$MODEL_REGISTRY"
registry_changed=1

RAG_IME_MODEL_REGISTRY="$MODEL_REGISTRY" \
  "$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
RAG_IME_MODEL_REGISTRY="$MODEL_REGISTRY" \
RAG_IME_DB_PATH="$DB_PATH" \
RAG_IME_INSTALL_AGENT_GATEWAY=0 \
  "$ROOT/scripts/install_sidecar_launch_agent.sh"

PYTHONPATH="$ROOT" "$PYTHON" -m rag_ime.predictor_configuration \
  status --db "$DB_PATH" --registry "$MODEL_REGISTRY"

trap - ERR INT TERM
rm -f "$backup"
