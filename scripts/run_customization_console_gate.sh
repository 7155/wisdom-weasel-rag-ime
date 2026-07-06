#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m unittest \
  tests.test_settings_schema \
  tests.test_settings_store \
  tests.test_debug_management_api

node --check debug/app.js

python3 -m py_compile \
  rag_ime/settings_models.py \
  rag_ime/settings_schema.py \
  rag_ime/settings_store.py \
  rag_ime/debug_server.py
