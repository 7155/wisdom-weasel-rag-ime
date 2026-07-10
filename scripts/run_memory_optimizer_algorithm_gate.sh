#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RAG_IME_AI_AFTER_COMMIT_ONLY=0 \
RAG_IME_ENABLE_COMPOSING_MODEL=1 \
RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL=1 \
python3 -m rag_ime.cli eval-memory-optimizer \
  docs/eval/memory_optimizer_cases.jsonl \
  --project wisdom-weasel-rag-ime \
  --repeat "${RAG_IME_MEMORY_OPTIMIZER_EVAL_REPEAT:-1}"
