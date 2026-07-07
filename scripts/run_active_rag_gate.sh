#!/usr/bin/env bash
set -euo pipefail

python3 -m rag_ime.cli \
  --core-mode local \
  eval-active-rag \
  --cases-file docs/eval/active_rag_cases.jsonl \
  --repeat "${RAG_IME_ACTIVE_RAG_EVAL_REPEAT:-1}" \
  --ready-budget-ms "${RAG_IME_ACTIVE_RAG_READY_BUDGET_MS:-3000}"
