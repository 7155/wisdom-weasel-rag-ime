#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RAG_IME_SKIP_WEB_INSTALL="${RAG_IME_SKIP_WEB_INSTALL:-1}" \
  "$ROOT/scripts/build_control_center_web.sh" >/dev/null

python3 -m unittest \
  tests.test_control_api \
  tests.test_control_center_web_host

RAG_IME_SKIP_WEB_BUILD=1 "$ROOT/scripts/build_control_center_web_host.sh" build >/dev/null
RAG_IME_CONTROL_UI=web RAG_IME_CONTROL_SKIP_LIVE=1 \
  "$ROOT/scripts/check_control_center_footprint.sh"

echo "control center web gate: PASS"
