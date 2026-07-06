#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DB_PATH="${RAG_IME_GATE_DB_PATH:-.rag-ime-data/product-readiness-gate.sqlite}"
FRONTEND_DB_PATH="${RAG_IME_FRONTEND_DB_PATH:-$HOME/Library/Application Support/RagIme/rag-ime.sqlite}"
CASES_FILE="${RAG_IME_GATE_CASES_FILE:-docs/eval/codex-history-cases.example.jsonl}"
SOAK_REPORT="${RAG_IME_SQUIRREL_SOAK_REPORT:-/tmp/rag-ime-squirrel-soak-report.json}"
FOREGROUND_READINESS_REPORT="${RAG_IME_FOREGROUND_READINESS_REPORT:-/tmp/rag-ime-foreground-readiness.json}"
SIDECAR_LAUNCH_AGENT_PLIST="${RAG_IME_SIDECAR_LAUNCH_AGENT_PLIST:-$HOME/Library/LaunchAgents/com.rag-ime.sidecar.plist}"
REQUIRE_MACOS_FRONTEND="${RAG_IME_REQUIRE_MACOS_FRONTEND:-0}"
REQUIRE_SICHUAN_FUZZY="${RAG_IME_REQUIRE_SICHUAN_FUZZY:-$REQUIRE_MACOS_FRONTEND}"
SICHUAN_FUZZY_CHECK_SCRIPT="${RAG_IME_SICHUAN_FUZZY_CHECK_SCRIPT:-$ROOT/scripts/check_sichuan_fuzzy_profile.sh}"
PREPARE_FOREGROUND_SCRIPT="${RAG_IME_PREPARE_SQUIRREL_FOREGROUND_CHECK_SCRIPT:-$ROOT/scripts/prepare_squirrel_foreground_check.sh}"
DRY_RUN=0
RUN_UNIT_TESTS="${RAG_IME_GATE_RUN_UNIT_TESTS:-1}"
RUN_ACCEPTANCE="${RAG_IME_GATE_RUN_ACCEPTANCE:-1}"
RUN_QUALITY_GATE="${RAG_IME_GATE_RUN_QUALITY_GATE:-1}"
SEED_DEMO="${RAG_IME_GATE_SEED_DEMO:-1}"
RESET_GATE_DB="${RAG_IME_GATE_RESET_DB:-1}"
REQUIRE_PREDICTOR_CAPABILITY="${RAG_IME_REQUIRE_PREDICTOR_CAPABILITY:-}"
SIDECAR_LATENCY_BUDGET_MS="${RAG_IME_GATE_SIDECAR_LATENCY_BUDGET_MS:-}"

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
  --no-reset-gate-db      Do not reset the gate DB before seeding demo memories.
  --db-path PATH          SQLite DB path for quality-gate.
  --frontend-db-path PATH SQLite DB path expected by the installed Squirrel/Rime config.
  --cases-file PATH       Eval cases file for quality-gate.
  --soak-report PATH      Squirrel foreground soak report path.
  --foreground-readiness-report PATH
                           Foreground readiness summary report path.
  --sidecar-plist PATH    Installed sidecar LaunchAgent plist for predictor env fallback.
  --sidecar-latency-budget-ms MS
                           Latency budget used by sidecar eval requests.
  -h, --help              Show this help.

Environment:
  RAG_IME_REQUIRE_MACOS_FRONTEND=1  Require Squirrel tryout + soak report checks.
  RAG_IME_REQUIRE_SICHUAN_FUZZY=1   Require installed Sichuan mild fuzzy profile.
  RAG_IME_FRONTEND_DB_PATH=PATH      Installed frontend runtime DB path.
  RAG_IME_FOREGROUND_READINESS_REPORT=PATH
  RAG_IME_PREPARE_SQUIRREL_FOREGROUND_CHECK_SCRIPT=PATH
  RAG_IME_SIDECAR_LAUNCH_AGENT_PLIST=PATH
                                    Sidecar plist used to recover local predictor env.
  RAG_IME_REQUIRE_PREDICTOR_CAPABILITY=name
                                    Add a local predictor capability requirement,
                                    for example seededPromptReplay.
  RAG_IME_GATE_SIDECAR_LATENCY_BUDGET_MS=MS
                                    Override sidecar eval latency budget.
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
    --no-reset-gate-db)
      RESET_GATE_DB=0
      shift
      ;;
    --db-path)
      DB_PATH="${2:?--db-path requires a value}"
      shift 2
      ;;
    --frontend-db-path)
      FRONTEND_DB_PATH="${2:?--frontend-db-path requires a value}"
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
    --foreground-readiness-report)
      FOREGROUND_READINESS_REPORT="${2:?--foreground-readiness-report requires a value}"
      shift 2
      ;;
    --sidecar-plist)
      SIDECAR_LAUNCH_AGENT_PLIST="${2:?--sidecar-plist requires a value}"
      shift 2
      ;;
    --sidecar-latency-budget-ms)
      SIDECAR_LATENCY_BUDGET_MS="${2:?--sidecar-latency-budget-ms requires a value}"
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

plist_env_value() {
  local key="$1"
  [[ -f "$SIDECAR_LAUNCH_AGENT_PLIST" ]] || return 1
  "$PYTHON_BIN" - "$SIDECAR_LAUNCH_AGENT_PLIST" "$key" <<'PY'
import plistlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
try:
    payload = plistlib.loads(path.read_bytes())
except Exception:
    raise SystemExit(1)
env = payload.get("EnvironmentVariables")
if not isinstance(env, dict):
    raise SystemExit(1)
value = str(env.get(key) or "")
if value:
    print(value)
PY
}

maybe_export_plist_env() {
  local key="$1"
  local current="${!key:-}"
  local value
  if [[ -n "$current" ]]; then
    return 0
  fi
  value="$(plist_env_value "$key" 2>/dev/null || true)"
  if [[ -n "$value" ]]; then
    export "$key=$value"
  fi
}

PREDICTOR_ENV_SOURCE="shell"
if [[ -n "$REQUIRE_PREDICTOR_CAPABILITY" && -z "${RAG_IME_PREDICTOR_PROVIDER:-}" ]]; then
  maybe_export_plist_env RAG_IME_PREDICTOR_PROVIDER
  maybe_export_plist_env RAG_IME_PREDICTOR_BASE_URL
  maybe_export_plist_env RAG_IME_PREDICTOR_MODEL
  maybe_export_plist_env RAG_IME_PREDICTOR_PROFILE
  maybe_export_plist_env RAG_IME_PREDICTOR_TIMEOUT_MS
  maybe_export_plist_env RAG_IME_PREDICTOR_MAX_TOKENS
  maybe_export_plist_env RAG_IME_PREDICTOR_TEMPERATURE
  maybe_export_plist_env RAG_IME_PREDICTOR_TOP_P
  maybe_export_plist_env RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS
  if [[ -n "${RAG_IME_PREDICTOR_PROVIDER:-}" ]]; then
    PREDICTOR_ENV_SOURCE="launch-agent-plist"
  fi
fi

if [[ -z "$SIDECAR_LATENCY_BUDGET_MS" ]]; then
  if [[ -n "$REQUIRE_PREDICTOR_CAPABILITY" ]]; then
    SIDECAR_LATENCY_BUDGET_MS="${RAG_IME_PREDICTOR_TIMEOUT_MS:-6500}"
  else
    SIDECAR_LATENCY_BUDGET_MS=300
  fi
fi

log "root=$ROOT"
log "db_path=$DB_PATH"
log "frontend_db_path=$FRONTEND_DB_PATH"
log "sidecar_plist=$SIDECAR_LAUNCH_AGENT_PLIST"
log "cases_file=$CASES_FILE"
log "foreground_readiness_report=$FOREGROUND_READINESS_REPORT"
log "require_macos_frontend=$REQUIRE_MACOS_FRONTEND"
log "require_sichuan_fuzzy=$REQUIRE_SICHUAN_FUZZY"
log "require_predictor_capability=${REQUIRE_PREDICTOR_CAPABILITY:-none}"
log "sidecar_latency_budget_ms=$SIDECAR_LATENCY_BUDGET_MS"
log "reset_gate_db=$RESET_GATE_DB"
log "predictor_env_source=$PREDICTOR_ENV_SOURCE"
log "predictor_provider=${RAG_IME_PREDICTOR_PROVIDER:-none}"
log "predictor_base_url=${RAG_IME_PREDICTOR_BASE_URL:-none}"

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
    SEED_DEMO_CMD=("$PYTHON_BIN" -m rag_ime.cli --db-path "$DB_PATH" seed-demo)
    if [[ "$RESET_GATE_DB" == "1" ]]; then
      SEED_DEMO_CMD+=(--reset)
    fi
    run_cmd "${SEED_DEMO_CMD[@]}"
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
    --skip-acceptance-check
    --max-visible-candidates 8
    --max-side-candidates 5
    --sidecar-latency-budget-ms "$SIDECAR_LATENCY_BUDGET_MS"
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

if [[ "$REQUIRE_SICHUAN_FUZZY" == "1" ]]; then
  log "Sichuan fuzzy profile check"
  run_cmd "$SICHUAN_FUZZY_CHECK_SCRIPT"
else
  log "Sichuan fuzzy profile check skipped; set RAG_IME_REQUIRE_SICHUAN_FUZZY=1 to require it"
fi

if [[ "$REQUIRE_MACOS_FRONTEND" == "1" ]]; then
  log "foreground readiness preflight"
  run_cmd "$PREPARE_FOREGROUND_SCRIPT" \
    --refresh-registration \
    --no-open \
    --no-wait-typing \
    --summary-path "$FOREGROUND_READINESS_REPORT"

  log "macOS Squirrel tryout gate"
  TRYOUT_CMD=(
    "$PYTHON_BIN" -m rag_ime.cli
    --db-path "$FRONTEND_DB_PATH"
    squirrel-tryout-gate
    --cases-file "$CASES_FILE"
    --min-rag-pass-rate 0.9
    --min-sidecar-pass-rate 0.9
    --skip-acceptance-check
    --max-visible-candidates 8
    --max-side-candidates 5
    --sidecar-latency-budget-ms "$SIDECAR_LATENCY_BUDGET_MS"
    --max-sidecar-noise-rate 0.05
    --max-sidecar-rag-timeout-rate 0
    --max-sidecar-model-timeout-rate 0
    --include-input-source-audit
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
    --max-flicker-count 0 \
    --max-min-visible-violations 0 \
    --max-rag-empty-cleared-panel 0 \
    --min-side-commits 50 \
    --min-post-commit-followups 30 \
    --min-backspaces 1 \
    --min-app-switches 1 \
    --min-chain-depth 10 \
    --require-side-commit \
    --require-commit-observed \
    --require-post-commit-followup \
    --require-delete-resync \
    --require-modern-prediction-session \
    --require-balanced-quota \
    --require-snapshot-selection-trace
else
  log "macOS Squirrel foreground checks skipped; set RAG_IME_REQUIRE_MACOS_FRONTEND=1 to require them"
fi

log "passed"
