#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-install}"

export RAG_IME_SQUIRREL_DISPLAY_NAME="${RAG_IME_SQUIRREL_DISPLAY_NAME:-智鼬输入法}"
export RAG_IME_SQUIRREL_HANS_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANS_DISPLAY_NAME:-智鼬输入法}"
export RAG_IME_SQUIRREL_HANT_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANT_DISPLAY_NAME:-智鼬输入法（繁体）}"

exec "$ROOT/scripts/build_patched_squirrel.sh" "$ACTION"
