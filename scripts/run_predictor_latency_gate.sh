#!/usr/bin/env bash
set -euo pipefail

REPORT="${REPORT:-/tmp/rag-ime-predictor-bench.json}"

python3 -m unittest \
  tests.test_predictor_latency \
  tests.test_model_lane_scheduler \
  tests.test_mlx_prefix_cache \
  tests.test_sequence_fork \
  tests.test_predictor_benchmark

python3 -m rag_ime.cli benchmark-predictor \
  --profile "${RAG_IME_PREDICTOR_PROFILE:-qwen3_06b_ime_hot}" \
  --cases eval/predictor_latency_cases.jsonl \
  --repeat "${RAG_IME_PREDICTOR_BENCH_REPEAT:-20}" \
  --report "$REPORT"

python3 scripts/check_predictor_latency_report.py \
  --report "$REPORT" \
  --max-hot-first-candidate-p95-ms 500 \
  --max-hot-three-candidates-p95-ms 900 \
  --min-format-valid-rate 0.99 \
  --max-generic-filler-rate 0.02 \
  --max-duplicate-rate 0.05
