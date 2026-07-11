#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m unittest \
  tests.test_settings_schema \
  tests.test_settings_store \
  tests.test_debug_management_api \
  tests.test_native_control_center \
  tests.test_runtime_lifecycle_control_plane

for obsolete in debug/index.html debug/app.js debug/styles.css; do
  if [[ -e "$obsolete" ]]; then
    echo "legacy browser control surface must stay removed: $obsolete" >&2
    exit 1
  fi
done

python3 -m py_compile \
  rag_ime/settings_models.py \
  rag_ime/settings_schema.py \
  rag_ime/settings_store.py \
  rag_ime/debug_server.py

bash scripts/build_control_center.sh
