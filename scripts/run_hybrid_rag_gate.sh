#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RAG_IME_HYBRID_RAG_CORE=1 \
python3 -m rag_ime.cli eval-hybrid-rag-core \
  --cases-file eval/hybrid_rag_core_cases.jsonl \
  --project wisdom-weasel-rag-ime \
  --repeat "${RAG_IME_HYBRID_RAG_EVAL_REPEAT:-3}"

if [[ -f eval/v1_post_commit_memory_cases.jsonl ]]; then
  RAG_IME_AI_AFTER_COMMIT_ONLY=1 \
  RAG_IME_ENABLE_COMPOSING_MODEL=0 \
  RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL=0 \
  python3 -m rag_ime.cli eval-memory-optimizer \
    eval/v1_post_commit_memory_cases.jsonl \
    --project wisdom-weasel-rag-ime \
    --repeat "${RAG_IME_V1_POST_COMMIT_MEMORY_EVAL_REPEAT:-1}"
fi
