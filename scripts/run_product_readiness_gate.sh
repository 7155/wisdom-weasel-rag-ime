#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DB_PATH="${RAG_IME_GATE_DB_PATH:-.rag-ime-data/product-readiness-gate.sqlite}"
CASES_FILE="${RAG_IME_GATE_CASES_FILE:-docs/eval/codex-history-cases.example.jsonl}"
SOAK_REPORT="${RAG_IME_SQUIRREL_SOAK_REPORT:-/tmp/rag-ime-squirrel-soak-report.json}"
REQUIRE_MACOS_FRONTEND="${RAG_IME_REQUIRE_MACOS_FRONTEND:-0}"
DRY_RUN=0
RUN_UNIT_TESTS="${RAG_IME_GATE_RUN_UNIT_TESTS:-1}"
RUN_ACCEPTANCE="${RAG_IME_GATE_RUN_ACCEPTANCE:-1}"
RUN_QUALITY_GATE="${RAG_IME_GATE_RUN_QUALITY_GATE:-1}"
SEED_DEMO="${RAG_IME_GATE_SEED_DEMO:-1}"
REQUIRE_PREDICTOR_CAPABILITY="${RAG_IME_REQUIRE_PREDICTOR_CAPABILITY:-}"

usage() {
  cat <<'USAGE'
Usage: scripts/run_product_readiness_gate.sh [options]

Runs the product readiness gate for Wisdom-Weasel RAG-IME.

Options:
  --dry-run               Print the commands without executing them.
  --skip-unit-tests       Skip python3 -m unittest discover -s tests.
  --skip-acceptance       Skip scripts/acceptance.py.
  --skip-quality-gate     Skip rag_ime.cli quality-gate.
  --skip-seed-demo        Do not seed demo memories into the gate DB.
  --db-path PATH          SQLite DB path for quality-gate.
  --cases-file PATH       Eval cases file for quality-gate.
  --soak-report PATH      Squirrel foreground soak report path.
  -h, --help              Show this help.

Environment:
  RAG_IME_REQUIRE_MACOS_FRONTEND=1  Require Squirrel tryout + soak report checks.
  RAG_IME_REQUIRE_PREDICTOR_CAPABILITY=name
                                    Add a local predictor capability requirement,
                                    for example seededPromptReplay.
USAGE
}

while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-unit-tests)
      RUN_UNIT_TESTS=0
      shift
      ;;
    --skip-acceptance)
      RUN_ACCEPTANCE=0
      shift
      ;;
    --skip-quality-gate)
      RUN_QUALITY_GATE=0
      shift
      ;;
    --skip-seed-demo)
      SEED_DEMO=0
      shift
      ;;
    --db-path)
      DB_PATH="${2:?--db-path requires a value}"
      shift 2
      ;;
    --cases-file)
      CASES_FILE="${2:?--cases-file requires a value}"
      shift 2
      ;;
    --soak-report)
      SOAK_REPORT="${2:?--soak-report requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[product-gate] %s\n' "$*"
}

run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" != "1" ]]; then
    "$@"
  fi
}

log "root=$ROOT"
log "db_path=$DB_PATH"
log "cases_file=$CASES_FILE"
log "require_macos_frontend=$REQUIRE_MACOS_FRONTEND"
log "require_predictor_capability=${REQUIRE_PREDICTOR_CAPABILITY:-none}"

if [[ "$RUN_UNIT_TESTS" == "1" ]]; then
  log "unit tests"
  run_cmd "$PYTHON_BIN" -W error::ResourceWarning -m unittest discover -s tests
else
  log "unit tests skipped"
fi

if [[ "$RUN_ACCEPTANCE" == "1" ]]; then
  log "deterministic acceptance"
  run_cmd "$PYTHON_BIN" scripts/acceptance.py
else
  log "acceptance skipped"
fi

if [[ "$RUN_QUALITY_GATE" == "1" ]]; then
  if [[ "$SEED_DEMO" == "1" ]]; then
    log "seed demo memories into gate DB"
    run_cmd "$PYTHON_BIN" -m rag_ime.cli --db-path "$DB_PATH" seed-demo
    log "seed eval-case memories into gate DB"
    run_cmd "$PYTHON_BIN" -m rag_ime.cli --db-path "$DB_PATH" seed-eval-cases --cases-file "$CASES_FILE"
  else
    log "seed demo skipped"
  fi
  log "backend quality gate"
  QUALITY_CMD=(
    "$PYTHON_BIN" -m rag_ime.cli
    --db-path "$DB_PATH"
    quality-gate
    --cases-file "$CASES_FILE"
    --force-side-candidates
    --require-suggestion-cache
    --max-visible-candidates 8
    --max-side-candidates 5
    --min-rag-pass-rate 0.9
    --min-sidecar-pass-rate 0.9
    --max-sidecar-noise-rate 0.05
    --max-sidecar-rag-timeout-rate 0
    --max-sidecar-model-timeout-rate 0
    --max-old-input-echo-rate 0.01
  )
  if [[ -n "$REQUIRE_PREDICTOR_CAPABILITY" ]]; then
    QUALITY_CMD+=(--require-predictor-capability "$REQUIRE_PREDICTOR_CAPABILITY")
  fi
  run_cmd "${QUALITY_CMD[@]}"
else
  log "quality gate skipped"
fi

if [[ "$REQUIRE_MACOS_FRONTEND" == "1" ]]; then
  log "macOS Squirrel tryout gate"
  TRYOUT_CMD=(
    "$PYTHON_BIN" -m rag_ime.cli
    --db-path "$DB_PATH"
    squirrel-tryout-gate
    --cases-file "$CASES_FILE"
    --min-rag-pass-rate 0.9
    --min-sidecar-pass-rate 0.9
    --max-visible-candidates 8
    --max-side-candidates 5
    --max-sidecar-noise-rate 0.05
    --max-sidecar-rag-timeout-rate 0
    --max-sidecar-model-timeout-rate 0
    --report-path /tmp/rag-ime-squirrel-tryout-gate.json
  )
  if [[ -n "$REQUIRE_PREDICTOR_CAPABILITY" ]]; then
    TRYOUT_CMD+=(--require-predictor-capability "$REQUIRE_PREDICTOR_CAPABILITY")
  fi
  run_cmd "${TRYOUT_CMD[@]}"

  log "foreground soak report check"
  run_cmd "$PYTHON_BIN" scripts/check_squirrel_soak_report.py \
    --report-path "$SOAK_REPORT" \
    --max-stale-applied 0 \
    --min-side-commits 50 \
    --min-post-commit-followups 30 \
    --require-side-commit \
    --require-commit-observed \
    --require-post-commit-followup \
    --require-modern-prediction-session
else
  log "macOS Squirrel foreground checks skipped; set RAG_IME_REQUIRE_MACOS_FRONTEND=1 to require them"
fi

log "passed"
