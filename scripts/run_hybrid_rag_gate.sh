#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RAG_IME_HYBRID_RAG_CORE=1 \
python3 -m rag_ime.cli eval-hybrid-rag-core \
  --cases-file docs/eval/hybrid_rag_core_cases.jsonl \
  --project wisdom-weasel-rag-ime \
  --repeat "${RAG_IME_HYBRID_RAG_EVAL_REPEAT:-3}"

if [[ -f docs/eval/memory_optimizer_cases.jsonl ]]; then
  python3 -m rag_ime.cli eval-memory-optimizer \
    docs/eval/memory_optimizer_cases.jsonl \
    --project wisdom-weasel-rag-ime \
    --repeat "${RAG_IME_MEMORY_OPTIMIZER_EVAL_REPEAT:-1}"
fi
