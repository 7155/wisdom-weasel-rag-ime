#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${RAG_IME_SYSTEMD_SERVICE_NAME:-rag-ime-sidecar.service}"
SIDECAR_HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
SIDECAR_PORT="${RAG_IME_SIDECAR_PORT:-8766}"
SIDECAR_BASE_URL="${RAG_IME_SIDECAR_URL:-http://$SIDECAR_HOST:$SIDECAR_PORT}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3 || true)}"

export RAG_IME_ENABLE_LOCAL_VECTOR="${RAG_IME_ENABLE_LOCAL_VECTOR:-1}"
export RAG_IME_EMBEDDING_PROVIDER="${RAG_IME_EMBEDDING_PROVIDER:-local-hash}"
export RAG_IME_EMBEDDING_DIMENSIONS="${RAG_IME_EMBEDDING_DIMENSIONS:-96}"
export RAG_IME_VECTOR_CANDIDATES="${RAG_IME_VECTOR_CANDIDATES:-80}"
export RAG_IME_VECTOR_WEIGHT="${RAG_IME_VECTOR_WEIGHT:-1.4}"
export RAG_IME_VECTOR_AUTO_REBUILD_LIMIT="${RAG_IME_VECTOR_AUTO_REBUILD_LIMIT:-5000}"

"$ROOT/scripts/install_sidecar_systemd_user.sh"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user restart "$SERVICE_NAME"
fi

if [[ -n "$PYTHON_EXECUTABLE" && -x "$PYTHON_EXECUTABLE" ]]; then
  "$PYTHON_EXECUTABLE" - <<PY
import json
import sys
import time
import urllib.request

url = "$SIDECAR_BASE_URL/health"
last = None
for _ in range(20):
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            payload = json.load(response)
        print(f"health: OK server={payload.get('serverName', 'sidecar')} url={url}")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - shell health probe
        last = exc
        time.sleep(0.25)
print(f"health: FAIL url={url} error={last}", file=sys.stderr)
sys.exit(1)
PY
fi
