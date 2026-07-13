#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# A repair must preserve the product input path. The generic restart helper is
# deliberately fail-closed by default, so opt the supervised repair back in.
export RAG_IME_ENABLE_FRONTEND_ON_RESTART=1
export RAG_IME_SKIP_INPUT_SOURCE_READINESS=1
export RAG_IME_RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-foreground-rag-proof}"

exec "$ROOT/scripts/restart_rag_ime_runtime.sh"
