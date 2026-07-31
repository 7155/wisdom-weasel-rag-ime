#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
SIDECAR_PLIST="$HOME/Library/LaunchAgents/com.rag-ime.sidecar.plist"
DB_PATH="${RAG_IME_DB_PATH:-}"

if [[ -z "$DB_PATH" && -f "$SIDECAR_PLIST" ]]; then
  DB_PATH="$(
    /usr/libexec/PlistBuddy \
      -c "Print :EnvironmentVariables:RAG_IME_DB_PATH" \
      "$SIDECAR_PLIST" 2>/dev/null || true
  )"
fi
if [[ -z "$DB_PATH" ]]; then
  DB_PATH="$APP_SUPPORT_DIR/rag-ime.sqlite"
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "Control Center settings database was not found: $DB_PATH" >&2
  exit 1
fi
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
if [[ ! -x "$SQUIRREL_APP/Contents/MacOS/Squirrel" ]]; then
  echo "Squirrel app executable was not found: $SQUIRREL_APP" >&2
  exit 1
fi

# install_squirrel_rag_config.sh owns the managed YAML block and preserves all
# user-owned Rime content. The explicit deploy flag makes this approved host
# action build and reload Squirrel after projecting validated DB settings.
RAG_IME_DB_PATH="$DB_PATH" \
RAG_IME_SQUIRREL_DEPLOY=1 \
  exec "$ROOT/scripts/install_squirrel_rag_config.sh"
