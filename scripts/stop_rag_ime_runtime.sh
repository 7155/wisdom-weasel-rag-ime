#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="gui/$(id -u)"
LABELS=(
  com.rag-ime.sidecar
  com.rag-ime.agent-gateway
  com.rag-ime.memory-book-maintenance
  com.rag-ime.mlx-predictor
  com.rag-ime.desktop-bridge
  com.rag-ime.voice
)

for label in "${LABELS[@]}"; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  launchctl bootout "$DOMAIN" "$plist" >/dev/null 2>&1 || true
  launchctl disable "$DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl remove "$label" >/dev/null 2>&1 || true
done

pkill -f 'sidecar_launch.py.*mlx-predictor-server' >/dev/null 2>&1 || true
pkill -f 'sidecar_launch.py.*sidecar-server' >/dev/null 2>&1 || true
pkill -f 'sidecar_launch.py.*agent-gateway' >/dev/null 2>&1 || true
pkill -f 'memory_book_maintenance_launch.py' >/dev/null 2>&1 || true
pkill -f 'run_memory_book_maintenance_once.sh' >/dev/null 2>&1 || true
pkill -f 'rag_ime.cli mlx-predictor-server' >/dev/null 2>&1 || true
pkill -f 'rag_ime.cli agent-gateway' >/dev/null 2>&1 || true
pkill -f '/Contents/MacOS/RagImeDesktopBridge([[:space:]]|$)' >/dev/null 2>&1 || true
pkill -f '/Contents/MacOS/RagImeVoice([[:space:]]|$)' >/dev/null 2>&1 || true
pkill -f '/Contents/MacOS/RagImeControl([[:space:]]|$)' >/dev/null 2>&1 || true
rm -f "${RAG_IME_DESKTOP_BRIDGE_SOCKET:-${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}/desktop-bridge.sock}"
pkill -f '/Library/Input Methods/RAG-IME.app|RAG-IME.app|im.rag-ime.inputmethod.RagIme' >/dev/null 2>&1 || true
pkill -f "$HOME/Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel" >/dev/null 2>&1 || true

if [[ "${RAG_IME_DISABLE_FRONTEND_ON_STOP:-1}" != "0" ]]; then
  "$ROOT/scripts/set_rag_ime_frontend_enabled.py" false >/dev/null 2>&1 || true
fi

runtime_stopped() {
  local label port
  for label in "${LABELS[@]}"; do
    if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
      return 1
    fi
  done
  if command -v lsof >/dev/null 2>&1; then
    for port in \
      "${RAG_IME_SIDECAR_PORT:-8766}" \
      "${RAG_IME_MLX_PORT:-8767}" \
      "${RAG_IME_AGENT_GATEWAY_PORT:-8768}"; do
      if lsof -nP -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        return 1
      fi
    done
  fi
  if pgrep -f '[s]idecar_launch.py.*(sidecar-server|agent-gateway|mlx-predictor-server)' >/dev/null 2>&1 \
    || pgrep -f '[m]emory_book_maintenance_launch.py' >/dev/null 2>&1 \
    || pgrep -f '[r]ag_ime\.cli .*(sidecar-server|agent-gateway|mlx-predictor-server)' >/dev/null 2>&1 \
    || pgrep -f '/Contents/MacOS/[R]agImeDesktopBridge([[:space:]]|$)' >/dev/null 2>&1 \
    || pgrep -f '/Contents/MacOS/[R]agImeVoice([[:space:]]|$)' >/dev/null 2>&1 \
    || pgrep -f '/Contents/MacOS/[R]agImeControl([[:space:]]|$)' >/dev/null 2>&1 \
    || pgrep -f '/Library/Input Methods/[S]quirrel\.app/Contents/MacOS/Squirrel' >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

for _ in {1..40}; do
  runtime_stopped && break
  sleep 0.25
done
if ! runtime_stopped; then
  echo "RAG-IME runtime did not stop cleanly; refusing database maintenance." >&2
  exit 1
fi

echo "RAG-IME runtime stopped and LaunchAgents disabled."
