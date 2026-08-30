#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RAG_IME_SKIP_WEB_INSTALL="${RAG_IME_SKIP_WEB_INSTALL:-1}" \
RAG_IME_CONTROL_TRANSPORT=http \
RAG_IME_CONTROL_BUILD_CHANNEL=production \
  "$ROOT/scripts/build_control_center_web.sh" >/dev/null

python3 -m unittest \
  tests.test_control_api

if [[ "${RAG_IME_SKIP_WEB_E2E:-0}" != "1" ]]; then
  "$ROOT/scripts/run_control_center_web_qa.sh"
fi

RAG_IME_USE_VERIFIED_WEB_DIST=1 \
  "$ROOT/scripts/build_paw_os_electron_host.sh" build-release >/dev/null
RAG_IME_CONTROL_SKIP_LIVE=1 \
  "$ROOT/scripts/check_control_center_footprint.sh"

echo "control center web gate: PASS"
