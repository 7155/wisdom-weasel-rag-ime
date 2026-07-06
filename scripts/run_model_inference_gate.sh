#!/usr/bin/env bash
set -euo pipefail

scripts/run_predictor_latency_gate.sh
python3 -m unittest tests.test_mlx_predictor_server tests.test_rime_sidecar

TRACE_LOG="${RAG_IME_SQUIRREL_TRACE_LOG:-${RAG_IME_FRONTEND_TRACE_LOG:-}}"
if [[ -n "$TRACE_LOG" && -f "$TRACE_LOG" ]]; then
  python3 scripts/check_squirrel_frontend_trace.py \
    --log-path "$TRACE_LOG" \
    --require-modern-prediction-session \
    --require-prediction-status-visible \
    --require-source-badges \
    --require-balanced-quota \
    --max-renumber-rate 0
fi
