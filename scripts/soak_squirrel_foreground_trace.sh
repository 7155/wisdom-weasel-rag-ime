#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
TRACE_LOG="${RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG:-$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl}"
REPORT_PATH="${RAG_IME_SQUIRREL_SOAK_REPORT_PATH:-/tmp/rag-ime-squirrel-soak-report.json}"
WAIT_SECONDS="${RAG_IME_FOREGROUND_SOAK_WAIT_SECONDS:-60}"
TEST_FILE="${RAG_IME_FOREGROUND_SOAK_TEST_FILE:-$HOME/Desktop/rag-ime-foreground-soak.txt}"
OPEN_APP="${RAG_IME_FOREGROUND_SOAK_APP:-TextEdit}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
SELECT_INPUT_SOURCE_SCRIPT="${RAG_IME_SELECT_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/select_macos_input_source.sh}"
TRACE_CLEAR_SCRIPT="${RAG_IME_TRACE_CLEAR_SCRIPT:-$ROOT/scripts/check_squirrel_frontend_trace.py}"
SOAK_CHECK_SCRIPT="${RAG_IME_SOAK_CHECK_SCRIPT:-$ROOT/scripts/check_squirrel_soak_report.py}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
OPEN_COMMAND="${RAG_IME_OPEN_COMMAND:-open}"

CLEAR_TRACE=1
OPEN_TEST_FILE=1
SELECT_INPUT_SOURCE=1
REQUIRE_MIXED_PANEL=1
REQUIRE_SIDE_PANEL=0
REQUIRE_SIDE_COMMIT=1
REQUIRE_COMMIT_OBSERVED=1
REQUIRE_POST_COMMIT_FOLLOWUP=1
REQUIRE_DELETE_RESYNC="${RAG_IME_FOREGROUND_SOAK_REQUIRE_DELETE_RESYNC:-1}"
REQUIRE_MODERN_PREDICTION_SESSION=1
REQUIRE_BALANCED_QUOTA=1
REQUIRE_SNAPSHOT_SELECTION_TRACE=1
AUTO_TYPE=1
AUTO_QUERY="${RAG_IME_FOREGROUND_SOAK_AUTO_QUERY:-er qi}"
AUTO_KEY="${RAG_IME_FOREGROUND_SOAK_AUTO_KEY:-6}"
AUTO_TYPE_DELAY="${RAG_IME_FOREGROUND_SOAK_AUTO_DELAY_SECONDS:-2.5}"
AUTO_CHAR_DELAY="${RAG_IME_FOREGROUND_SOAK_AUTO_CHAR_DELAY_SECONDS:-0.04}"
CHAIN_REPEATS="${RAG_IME_FOREGROUND_SOAK_CHAIN_REPEATS:-10}"
MIN_SIDECAR_REQUESTS="${RAG_IME_FOREGROUND_SOAK_MIN_SIDECAR_REQUESTS:-1}"
MIN_SIDECAR_APPLIED="${RAG_IME_FOREGROUND_SOAK_MIN_SIDECAR_APPLIED:-1}"
MIN_PANEL_DISPLAYS="${RAG_IME_FOREGROUND_SOAK_MIN_PANEL_DISPLAYS:-1}"
MIN_SIDE_COMMITS="${RAG_IME_FOREGROUND_SOAK_MIN_SIDE_COMMITS:-1}"
MIN_POST_COMMIT_FOLLOWUPS="${RAG_IME_FOREGROUND_SOAK_MIN_POST_COMMIT_FOLLOWUPS:-1}"
MIN_CHAIN_DEPTH="${RAG_IME_FOREGROUND_SOAK_MIN_CHAIN_DEPTH:-}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: scripts/soak_squirrel_foreground_trace.sh [options]

Collect a machine-readable real-foreground Squirrel soak report. The script
tries to automate typing when macOS Accessibility is available, otherwise it
still writes a JSON report with manualRequired instructions.

Options:
  --wait SECONDS        Seconds to wait for foreground evidence (default: 60)
  --report-path PATH    Output JSON report (default: /tmp/rag-ime-squirrel-soak-report.json)
  --mixed-only          Require mixed model-inline plus RAG block layout only
  --side-panel-only     Require any side panel instead of mixed layout
  --no-followup         Do not require post-commit follow-up
  --no-commit-observed  Do not require a commit_observed trace before follow-up
  --require-delete-resync
                       Require delete/backspace invalidation followed by committed-context resync
  --no-delete-resync   Do not require delete/backspace committed-context resync
  --no-clear            Do not clear the existing frontend trace first
  --no-open             Do not open the test editor file
  --no-select           Do not auto-select the Squirrel input source
  --no-auto-type        Skip Accessibility typing and record manualRequired
  --no-modern-session   Do not require a non-legacy predictionSession event
  --no-balanced-quota   Do not require product model/RAG/Rime quota trace
  --no-snapshot-selection-trace
                       Do not require accepted snapshot-selection trace before side commits
  --auto-query TEXT     Text used for auto typing / manual instructions
  --auto-key KEY        Number key used for auto typing / manual instructions
  --chain-repeats N     Repeat side-candidate selection N times for chaining evidence (default: 10)
  --min-chain-depth N   Required successful chain depth (default: chain repeats)
  --dry-run             Print resolved commands without changing local state
  -h, --help            Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait)
      WAIT_SECONDS="$2"
      shift
      ;;
    --report-path)
      REPORT_PATH="$2"
      shift
      ;;
    --mixed-only)
      REQUIRE_SIDE_COMMIT=0
      REQUIRE_POST_COMMIT_FOLLOWUP=0
      ;;
    --side-panel-only)
      REQUIRE_MIXED_PANEL=0
      REQUIRE_SIDE_PANEL=1
      ;;
    --no-followup)
      REQUIRE_POST_COMMIT_FOLLOWUP=0
      ;;
    --no-commit-observed)
      REQUIRE_COMMIT_OBSERVED=0
      ;;
    --require-delete-resync)
      REQUIRE_DELETE_RESYNC=1
      ;;
    --no-delete-resync)
      REQUIRE_DELETE_RESYNC=0
      ;;
    --no-clear)
      CLEAR_TRACE=0
      ;;
    --no-open)
      OPEN_TEST_FILE=0
      ;;
    --no-select)
      SELECT_INPUT_SOURCE=0
      ;;
    --no-auto-type)
      AUTO_TYPE=0
      ;;
    --no-modern-session)
      REQUIRE_MODERN_PREDICTION_SESSION=0
      ;;
    --no-balanced-quota)
      REQUIRE_BALANCED_QUOTA=0
      ;;
    --no-snapshot-selection-trace)
      REQUIRE_SNAPSHOT_SELECTION_TRACE=0
      ;;
    --auto-query)
      AUTO_QUERY="$2"
      shift
      ;;
    --auto-key)
      AUTO_KEY="$2"
      shift
      ;;
    --chain-repeats)
      CHAIN_REPEATS="$2"
      shift
      ;;
    --min-chain-depth)
      MIN_CHAIN_DEPTH="$2"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$REQUIRE_SIDE_COMMIT" != "1" ]]; then
  MIN_SIDE_COMMITS=0
fi
if [[ "$REQUIRE_POST_COMMIT_FOLLOWUP" != "1" ]]; then
  MIN_POST_COMMIT_FOLLOWUPS=0
fi
if [[ -z "$MIN_CHAIN_DEPTH" ]]; then
  MIN_CHAIN_DEPTH="$CHAIN_REPEATS"
fi
if [[ "$REQUIRE_SIDE_COMMIT" != "1" || "$REQUIRE_POST_COMMIT_FOLLOWUP" != "1" ]]; then
  MIN_CHAIN_DEPTH=0
fi
SELECT_REPORT_PATH="${RAG_IME_SELECT_INPUT_SOURCE_REPORT_PATH:-${REPORT_PATH%.json}.input-source-selection.json}"

soak_args=(
  "$SOAK_CHECK_SCRIPT"
  --log-path "$TRACE_LOG"
  --report-path "$REPORT_PATH"
  --wait "$WAIT_SECONDS"
  --print-last 8
  --min-sidecar-requests "$MIN_SIDECAR_REQUESTS"
  --min-sidecar-applied "$MIN_SIDECAR_APPLIED"
  --min-panel-displays "$MIN_PANEL_DISPLAYS"
  --min-side-commits "$MIN_SIDE_COMMITS"
  --min-post-commit-followups "$MIN_POST_COMMIT_FOLLOWUPS"
  --min-chain-depth "$MIN_CHAIN_DEPTH"
)
if [[ "$REQUIRE_MIXED_PANEL" == "1" ]]; then
  soak_args+=(--require-mixed-panel)
fi
if [[ "$REQUIRE_SIDE_PANEL" == "1" ]]; then
  soak_args+=(--require-side-panel)
fi
if [[ "$REQUIRE_SIDE_COMMIT" == "1" ]]; then
  soak_args+=(--require-side-commit)
fi
if [[ "$REQUIRE_COMMIT_OBSERVED" == "1" ]]; then
  soak_args+=(--require-commit-observed)
fi
if [[ "$REQUIRE_POST_COMMIT_FOLLOWUP" == "1" ]]; then
  soak_args+=(--require-post-commit-followup)
fi
if [[ "$REQUIRE_DELETE_RESYNC" == "1" ]]; then
  soak_args+=(--require-delete-resync)
fi
if [[ "$REQUIRE_MODERN_PREDICTION_SESSION" == "1" ]]; then
  soak_args+=(--require-modern-prediction-session)
fi
if [[ "$REQUIRE_BALANCED_QUOTA" == "1" ]]; then
  soak_args+=(--require-balanced-quota)
fi
if [[ "$REQUIRE_SNAPSHOT_SELECTION_TRACE" == "1" ]]; then
  soak_args+=(--require-snapshot-selection-trace)
fi

if [[ "$DRY_RUN" == "1" ]]; then
  cat <<EOF
repo_root=$ROOT
input_source_id=$INPUT_SOURCE_ID
trace_log=$TRACE_LOG
report_path=$REPORT_PATH
select_report_path=$SELECT_REPORT_PATH
wait_seconds=$WAIT_SECONDS
test_file=$TEST_FILE
open_app=$OPEN_APP
clear_trace=$CLEAR_TRACE
open_test_file=$OPEN_TEST_FILE
select_input_source=$SELECT_INPUT_SOURCE
auto_type=$AUTO_TYPE
auto_query=$AUTO_QUERY
auto_key=$AUTO_KEY
chain_repeats=$CHAIN_REPEATS
auto_type_delay=$AUTO_TYPE_DELAY
auto_char_delay=$AUTO_CHAR_DELAY
require_mixed_panel=$REQUIRE_MIXED_PANEL
require_side_panel=$REQUIRE_SIDE_PANEL
require_side_commit=$REQUIRE_SIDE_COMMIT
require_commit_observed=$REQUIRE_COMMIT_OBSERVED
require_post_commit_followup=$REQUIRE_POST_COMMIT_FOLLOWUP
require_delete_resync=$REQUIRE_DELETE_RESYNC
require_modern_prediction_session=$REQUIRE_MODERN_PREDICTION_SESSION
require_balanced_quota=$REQUIRE_BALANCED_QUOTA
require_snapshot_selection_trace=$REQUIRE_SNAPSHOT_SELECTION_TRACE
min_sidecar_requests=$MIN_SIDECAR_REQUESTS
min_sidecar_applied=$MIN_SIDECAR_APPLIED
min_panel_displays=$MIN_PANEL_DISPLAYS
min_side_commits=$MIN_SIDE_COMMITS
min_post_commit_followups=$MIN_POST_COMMIT_FOLLOWUPS
min_chain_depth=$MIN_CHAIN_DEPTH
soak_check_command=$PYTHON_EXECUTABLE ${soak_args[*]}
EOF
  exit 0
fi

"$CHECK_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID"
if [[ "$SELECT_INPUT_SOURCE" == "1" ]]; then
  "$SELECT_INPUT_SOURCE_SCRIPT" --report-path "$SELECT_REPORT_PATH" "$INPUT_SOURCE_ID"
else
  "$CHECK_INPUT_SOURCE_SCRIPT" --require-selected "$INPUT_SOURCE_ID"
fi

if [[ "$CLEAR_TRACE" == "1" ]]; then
  "$PYTHON_EXECUTABLE" "$TRACE_CLEAR_SCRIPT" --log-path "$TRACE_LOG" --clear >/dev/null
fi

if [[ "$OPEN_TEST_FILE" == "1" ]]; then
  mkdir -p "$(dirname "$TEST_FILE")"
  "$PYTHON_EXECUTABLE" - "$TEST_FILE" "$AUTO_QUERY" "$AUTO_KEY" "$INPUT_SOURCE_ID" "$CHAIN_REPEATS" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
query = sys.argv[2]
key = sys.argv[3]
input_source = sys.argv[4]
chain_repeats = int(sys.argv[5])
path.write_text(
    "RAG-IME foreground soak test\n\n"
    f"1. Make sure the active input source is {input_source}.\n"
    f"2. Type: {query}.\n"
    "3. Wait for visible model, RAG, and memory side candidates.\n"
    f"4. Press candidate number {key} (or any visible side-candidate number), wait for the next prediction, then repeat {chain_repeats} total side-candidate selections.\n"
    "5. Press Backspace/Delete, then wait for the next request to use the updated foreground context.\n\n",
    encoding="utf-8",
)
PY
  "$OPEN_COMMAND" -a "$OPEN_APP" "$TEST_FILE" >/dev/null 2>&1 || true
fi

manual_required=()
if [[ "$AUTO_TYPE" == "1" ]]; then
  set +e
  osascript - "$OPEN_APP" "$AUTO_QUERY" "$AUTO_KEY" "$AUTO_TYPE_DELAY" "$AUTO_CHAR_DELAY" "$CHAIN_REPEATS" <<'APPLESCRIPT'
on run argv
  set appName to item 1 of argv
  set queryText to item 2 of argv
  set sideKey to item 3 of argv
  set waitSeconds to (item 4 of argv) as number
  set charDelaySeconds to (item 5 of argv) as number
  set chainRepeats to (item 6 of argv) as integer
  tell application appName to activate
  delay 0.8
  tell application "System Events"
    keystroke return
    delay 0.2
    repeat with charIndex from 1 to length of queryText
      keystroke (character charIndex of queryText)
      delay charDelaySeconds
    end repeat
    delay waitSeconds
    repeat with chainIndex from 1 to chainRepeats
      keystroke sideKey
      delay waitSeconds
    end repeat
    key code 51
  end tell
end run
APPLESCRIPT
  auto_type_status=$?
  set -e
  if [[ "$auto_type_status" != "0" ]]; then
    manual_required+=("Accessibility typing failed; grant Accessibility to Codex or Terminal, then retry or type manually.")
  fi
else
  manual_required+=("Automatic Accessibility typing disabled; manual foreground typing confirmation is still required.")
fi

manual_required+=("Foreground editor typing verification")
manual_required+=("Real Squirrel candidate panel visual check")
manual_required+=("Side candidate number-key commit verification, repeated ${CHAIN_REPEATS} times for continuous prediction chaining")
manual_required+=("Backspace/Delete committed-context resync verification")

echo "Foreground soak gate is collecting real Squirrel AppKit events."
echo "Trace log: $TRACE_LOG"
echo "Report path: $REPORT_PATH"
echo "Manual action if needed: type '$AUTO_QUERY', then press a visible side-candidate number such as '$AUTO_KEY' ${CHAIN_REPEATS} times, waiting for the next prediction after each commit."

for item in "${manual_required[@]}"; do
  soak_args+=(--manual-required "$item")
done

"$PYTHON_EXECUTABLE" "${soak_args[@]}"
