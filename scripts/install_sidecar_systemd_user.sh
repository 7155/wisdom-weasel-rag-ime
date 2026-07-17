#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${RAG_IME_SYSTEMD_SERVICE_NAME:-rag-ime-sidecar.service}"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/rag-ime}"
APP_CODE_DIR="$APP_SUPPORT_DIR/app"
DB_PATH="${RAG_IME_DB_PATH:-$APP_SUPPORT_DIR/rag-ime.sqlite}"
LOG_DIR="${RAG_IME_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/rag-ime}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
PORT="${RAG_IME_SIDECAR_PORT:-8766}"
CORE_MODE="${RAG_IME_CORE_MODE:-local}"
CORE_COMMAND="${RAG_MEMORY_CORE_COMMAND:-}"
NO_SEED="${RAG_IME_SIDECAR_NO_SEED:-0}"
DRY_RUN="${RAG_IME_SYSTEMD_DRY_RUN:-0}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3 || true)}"

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

if ! "$PYTHON_EXECUTABLE" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  echo "python executable must be Python 3.10 or newer: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

mkdir -p "$SYSTEMD_USER_DIR" "$APP_CODE_DIR" "$(dirname "$DB_PATH")" "$LOG_DIR"
rm -rf "$APP_CODE_DIR/rag_ime"
cp -R "$ROOT/rag_ime" "$APP_CODE_DIR/rag_ime"

SERVICE_ARGS=(
  "$PYTHON_EXECUTABLE"
  -m rag_ime.cli
  --core-mode "$CORE_MODE"
  --db-path "$DB_PATH"
)
if [[ -n "$CORE_COMMAND" ]]; then
  SERVICE_ARGS+=(--core-command "$CORE_COMMAND")
fi
SERVICE_ARGS+=(
  sidecar-server
  --host "$HOST"
  --port "$PORT"
  --project "$PROJECT"
)
if [[ "$NO_SEED" == "1" || "$NO_SEED" == "true" || "$NO_SEED" == "TRUE" ]]; then
  SERVICE_ARGS+=(--no-seed)
fi

systemd_escape_arg() {
  printf '%q' "$1"
}

EXEC_START=""
for arg in "${SERVICE_ARGS[@]}"; do
  if [[ -z "$EXEC_START" ]]; then
    EXEC_START="$(systemd_escape_arg "$arg")"
  else
    EXEC_START+=" $(systemd_escape_arg "$arg")"
  fi
done

{
  echo "[Unit]"
  echo "Description=Wisdom-Weasel RAG IME sidecar"
  echo "Documentation=file://$ROOT/docs/linux-fcitx5-adapter.md"
  echo "After=default.target"
  echo
  echo "[Service]"
  echo "Type=simple"
  echo "WorkingDirectory=$APP_CODE_DIR"
  echo "Environment=PYTHONDONTWRITEBYTECODE=1"
  echo "Environment=PYTHONUNBUFFERED=1"
  echo "Environment=RAG_IME_ROOT=$APP_CODE_DIR"
  echo "Environment=RAG_IME_SOURCE_ROOT=$ROOT"
  echo "Environment=RAG_IME_DB_PATH=$DB_PATH"
  echo "Environment=RAG_IME_CORE_MODE=$CORE_MODE"
  for key in \
    RAG_IME_RIME_CACHE_TTL_MS \
    RAG_IME_SUGGESTION_CACHE_SIZE \
    RAG_IME_HISTORY_CONTEXT_EVENTS \
    RAG_IME_HISTORY_CONTEXT_CHARS \
    RAG_IME_MODEL_CONTEXT_EVENTS \
    RAG_IME_MODEL_CONTEXT_CHARS \
    RAG_IME_PREDICTOR_PROVIDER \
    RAG_IME_PREDICTOR_BASE_URL \
    RAG_IME_PREDICTOR_MODEL \
    RAG_IME_PREDICTOR_PROFILE \
    RAG_IME_PREDICTOR_TIMEOUT_MS \
    RAG_IME_PREDICTOR_MAX_TOKENS \
    RAG_IME_PREDICTOR_TEMPERATURE \
    RAG_IME_PREDICTOR_TOP_P \
    RAG_IME_PREDICTOR_DISABLE_THINKING \
    RAG_IME_PREDICTOR_STREAM_FIRST \
    RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS \
    RAG_IME_PREDICTOR_FAILURE_LATENCY_MS \
    RAG_IME_PREDICTOR_EXTRA_BODY_JSON \
    RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON \
    RAG_IME_PREDICTOR_API_KEY \
    RAG_IME_EMBEDDING_PROVIDER \
    RAG_IME_EMBEDDING_BASE_URL \
    RAG_IME_EMBEDDING_MODEL \
    RAG_IME_EMBEDDING_API_KEY \
    RAG_IME_EMBEDDING_TIMEOUT_MS \
    RAG_IME_EMBEDDING_DIMENSIONS \
    RAG_IME_EMBEDDING_CACHE_SIZE \
    RAG_IME_EMBEDDING_EXTRA_BODY_JSON \
    RAG_IME_EMBEDDING_EXTRA_HEADERS_JSON \
    RAG_IME_VECTOR_CANDIDATES \
    RAG_IME_VECTOR_WEIGHT \
    RAG_IME_VECTOR_AUTO_REBUILD_LIMIT \
    RAG_IME_ENABLE_LOCAL_VECTOR; do
    value="${!key:-}"
    if [[ -n "$value" ]]; then
      printf 'Environment=%s=%q\n' "$key" "$value"
    fi
  done
  if [[ -n "$CORE_COMMAND" ]]; then
    printf 'Environment=RAG_MEMORY_CORE_COMMAND=%q\n' "$CORE_COMMAND"
  fi
  echo "ExecStart=$EXEC_START"
  echo "Restart=on-failure"
  echo "RestartSec=2"
  echo "StandardOutput=append:$LOG_DIR/sidecar.out.log"
  echo "StandardError=append:$LOG_DIR/sidecar.err.log"
  echo
  echo "[Install]"
  echo "WantedBy=default.target"
} > "$SERVICE_PATH"

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  echo "$SERVICE_PATH"
  echo "dry-run: not enabling or starting systemd user service"
  exit 0
fi

systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

echo "$SERVICE_PATH"
echo "http://$HOST:$PORT/"
echo "Logs: $LOG_DIR/sidecar.out.log and $LOG_DIR/sidecar.err.log"
