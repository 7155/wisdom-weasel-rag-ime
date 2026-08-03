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
AUTO_COMMIT_KEY="${RAG_IME_FOREGROUND_SOAK_AUTO_COMMIT_KEY:-6}"
AUTO_KEY="${RAG_IME_FOREGROUND_SOAK_AUTO_KEY:-option-1}"
AUTO_TYPE_DELAY="${RAG_IME_FOREGROUND_SOAK_AUTO_DELAY_SECONDS:-2.5}"
AUTO_CHAR_DELAY="${RAG_IME_FOREGROUND_SOAK_AUTO_CHAR_DELAY_SECONDS:-0.04}"
CHAIN_REPEATS="${RAG_IME_FOREGROUND_SOAK_CHAIN_REPEATS:-10}"
AUTO_APP_SWITCH="${RAG_IME_FOREGROUND_SOAK_APP_SWITCH:-1}"
MIN_SIDECAR_REQUESTS="${RAG_IME_FOREGROUND_SOAK_MIN_SIDECAR_REQUESTS:-1}"
MIN_SIDECAR_APPLIED="${RAG_IME_FOREGROUND_SOAK_MIN_SIDECAR_APPLIED:-1}"
MIN_PANEL_DISPLAYS="${RAG_IME_FOREGROUND_SOAK_MIN_PANEL_DISPLAYS:-1}"
MIN_SIDE_COMMITS="${RAG_IME_FOREGROUND_SOAK_MIN_SIDE_COMMITS:-1}"
MIN_POST_COMMIT_FOLLOWUPS="${RAG_IME_FOREGROUND_SOAK_MIN_POST_COMMIT_FOLLOWUPS:-1}"
MIN_DURATION_SEC="${RAG_IME_FOREGROUND_SOAK_MIN_DURATION_SEC:-0}"
MIN_BACKSPACES="${RAG_IME_FOREGROUND_SOAK_MIN_BACKSPACES:-1}"
MIN_APP_SWITCHES="${RAG_IME_FOREGROUND_SOAK_MIN_APP_SWITCHES:-}"
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
  --auto-query TEXT     Pinyin text used for the first automated case
  --auto-commit-key KEY Native Rime candidate key sent after each Pinyin query (default: 6)
  --auto-key KEY        Assistant action repeated after native commit (default: option-1)
                       Supported actions: Tab or Option+number.
  --chain-repeats N     Repeat assistant selection N times for chaining evidence (default: 10)
  --no-app-switch       Do not include an automated app switch between soak cases
  --min-duration-sec N  Required foreground trace duration in seconds
  --min-backspaces N    Required delete/backspace invalidations
  --min-app-switches N  Required app/focus/input-source switches
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
    --auto-commit-key)
      AUTO_COMMIT_KEY="$2"
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
    --no-app-switch)
      AUTO_APP_SWITCH=0
      ;;
    --min-duration-sec)
      MIN_DURATION_SEC="$2"
      shift
      ;;
    --min-backspaces)
      MIN_BACKSPACES="$2"
      shift
      ;;
    --min-app-switches)
      MIN_APP_SWITCHES="$2"
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

if [[ "$AUTO_KEY" != "tab" && ! "$AUTO_KEY" =~ ^option-[0-9]$ ]]; then
  echo "--auto-key must be tab or option-0 through option-9" >&2
  exit 2
fi

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
if [[ -z "$MIN_APP_SWITCHES" ]]; then
  if [[ "$AUTO_APP_SWITCH" == "1" ]]; then
    MIN_APP_SWITCHES=1
  else
    MIN_APP_SWITCHES=0
  fi
fi
SELECT_REPORT_PATH="${RAG_IME_SELECT_INPUT_SOURCE_REPORT_PATH:-${REPORT_PATH%.json}.input-source-selection.json}"
if [[ -n "${RAG_IME_FOREGROUND_SOAK_CASES:-}" ]]; then
  AUTO_CASES_TEXT="$RAG_IME_FOREGROUND_SOAK_CASES"
else
  AUTO_CASES_TEXT="$(cat <<EOF
$AUTO_QUERY	$AUTO_COMMIT_KEY	$AUTO_KEY	$CHAIN_REPEATS	continuous_pinyin
zhe ge fang an	$AUTO_COMMIT_KEY	$AUTO_KEY	2	ordinary_pinyin_with_app_switch
lian xu yu ce	$AUTO_COMMIT_KEY	$AUTO_KEY	2	ordinary_pinyin
open /			0	raw_english_path
cd ~/Downloads			0	shell_path
https://example.com			0	url_passthrough
EOF
)"
fi
AUTO_CASE_COUNT="$(RAG_IME_FOREGROUND_SOAK_CASES_RESOLVED="$AUTO_CASES_TEXT" "$PYTHON_EXECUTABLE" - <<'PY'
import os

cases = [line for line in os.environ.get("RAG_IME_FOREGROUND_SOAK_CASES_RESOLVED", "").splitlines() if line.strip()]
print(len(cases))
PY
)"

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
  --min-duration-sec "$MIN_DURATION_SEC"
  --min-backspaces "$MIN_BACKSPACES"
  --min-app-switches "$MIN_APP_SWITCHES"
  --min-chain-depth "$MIN_CHAIN_DEPTH"
)
if [[ "$SELECT_INPUT_SOURCE" == "1" ]]; then
  soak_args+=(--input-source-selection-report "$SELECT_REPORT_PATH")
fi
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
auto_commit_key=$AUTO_COMMIT_KEY
auto_key=$AUTO_KEY
chain_repeats=$CHAIN_REPEATS
auto_case_count=$AUTO_CASE_COUNT
auto_app_switch=$AUTO_APP_SWITCH
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
min_duration_sec=$MIN_DURATION_SEC
min_backspaces=$MIN_BACKSPACES
min_app_switches=$MIN_APP_SWITCHES
min_chain_depth=$MIN_CHAIN_DEPTH
soak_check_command=$PYTHON_EXECUTABLE ${soak_args[*]}
auto_cases:
$AUTO_CASES_TEXT
EOF
  exit 0
fi

manual_required=()
input_source_ready=1
if ! input_source_status="$("$CHECK_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID" 2>&1)"; then
  input_source_ready=0
  printf '%s\n' "$input_source_status" >&2
  manual_required+=("Squirrel input source is not ready; add/select $INPUT_SOURCE_ID before foreground typing.")
else
  printf '%s\n' "$input_source_status"
fi
if [[ "$SELECT_INPUT_SOURCE" == "1" ]]; then
  set +e
  "$SELECT_INPUT_SOURCE_SCRIPT" --report-path "$SELECT_REPORT_PATH" "$INPUT_SOURCE_ID"
  select_status=$?
  set -e
  if [[ "$select_status" != "0" ]]; then
    input_source_ready=0
    AUTO_TYPE=0
    manual_required+=("Programmatic input-source selection failed; see $SELECT_REPORT_PATH.")
    manual_required+=("Open System Settings -> Keyboard -> Input Sources, add/select Squirrel - Simplified, then rerun the soak gate.")
  fi
else
  set +e
  "$CHECK_INPUT_SOURCE_SCRIPT" --require-selected "$INPUT_SOURCE_ID"
  selected_status=$?
  set -e
  if [[ "$selected_status" != "0" ]]; then
    input_source_ready=0
    AUTO_TYPE=0
    manual_required+=("The active input source is not $INPUT_SOURCE_ID; select it before foreground typing.")
  fi
fi

if [[ "$CLEAR_TRACE" == "1" ]]; then
  "$PYTHON_EXECUTABLE" "$TRACE_CLEAR_SCRIPT" --log-path "$TRACE_LOG" --clear >/dev/null
fi

if [[ "$OPEN_TEST_FILE" == "1" ]]; then
  mkdir -p "$(dirname "$TEST_FILE")"
  RAG_IME_FOREGROUND_SOAK_CASES_RESOLVED="$AUTO_CASES_TEXT" "$PYTHON_EXECUTABLE" - "$TEST_FILE" "$INPUT_SOURCE_ID" "$AUTO_APP_SWITCH" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1]).expanduser()
input_source = sys.argv[2]
app_switch = sys.argv[3] == "1"
cases: list[tuple[str, str, str, int, str]] = []
for line in os.environ.get("RAG_IME_FOREGROUND_SOAK_CASES_RESOLVED", "").splitlines():
    if not line.strip():
        continue
    parts = line.split("\t")
    query = parts[0].strip()
    commit_key = parts[1].strip() if len(parts) > 1 else ""
    action_key = parts[2].strip() if len(parts) > 2 else ""
    repeats_text = parts[3].strip() if len(parts) > 3 else "0"
    label = parts[4].strip() if len(parts) > 4 else "case"
    try:
        repeats = int(repeats_text or "0")
    except ValueError:
        repeats = 0
    cases.append((query, commit_key, action_key, max(0, repeats), label))

steps = [
    "RAG-IME foreground soak test",
    "",
    f"1. Make sure the active input source is {input_source}.",
    "2. For Pinyin cases, commit one native Rime candidate with the ordinary number key.",
    "3. Wait for visible model, RAG, and memory side candidates.",
    "4. Select assistant candidates only with Tab or Option+number.",
    "5. For raw English/path/URL cases, verify side candidates do not hijack normal typing.",
    "6. After assistant selection, wait for the next prediction before selecting again.",
    "7. Press Backspace/Delete near the end and verify the next request uses updated foreground context.",
]
if app_switch:
    steps.append("8. Switch away from this editor once during the second case, then return; stale candidates must not commit.")
steps.append("")
steps.append("Cases:")
for index, (query, commit_key, action_key, repeats, label) in enumerate(cases, start=1):
    if action_key and repeats:
        action = (
            f"commit native Rime with {commit_key}, then trigger assistant action "
            f"{action_key} {repeats} time(s)"
        )
    else:
        action = "type only; normal text must pass through"
    steps.append(f"- {index}. [{label}] type `{query}`; {action}.")
steps.append("")
path.write_text(
    "\n".join(steps),
    encoding="utf-8",
)
PY
  "$OPEN_COMMAND" -a "$OPEN_APP" "$TEST_FILE" >/dev/null 2>&1 || true
fi

if [[ "$AUTO_TYPE" == "1" ]]; then
  set +e
  osascript - "$OPEN_APP" "$AUTO_TYPE_DELAY" "$AUTO_CHAR_DELAY" "$AUTO_APP_SWITCH" "$AUTO_CASES_TEXT" <<'APPLESCRIPT'
on sendAssistantAction(actionKey)
  tell application "System Events"
    if actionKey is "" or actionKey is "none" then
      return false
    else if actionKey is "tab" then
      key code 48
    else if actionKey begins with "option-" then
      set digitText to text 8 thru -1 of actionKey
      set digitKeyCodes to {{"1", 18}, {"2", 19}, {"3", 20}, {"4", 21}, {"5", 23}, {"6", 22}, {"7", 26}, {"8", 28}, {"9", 25}, {"0", 29}}
      repeat with digitKeyPair in digitKeyCodes
        if item 1 of digitKeyPair is digitText then
          key code (item 2 of digitKeyPair) using option down
          return true
        end if
      end repeat
      return false
    end if
  end tell
  return true
end sendAssistantAction

on sendNativeCommit(commitKey)
  tell application "System Events"
    if commitKey is "" or commitKey is "none" then
      return false
    else if commitKey is "return" then
      key code 36
    else if commitKey is "enter" then
      key code 76
    else if commitKey is "space" then
      key code 49
    else
      keystroke commitKey
    end if
  end tell
  return true
end sendNativeCommit

on run argv
  set appName to item 1 of argv
  set waitSeconds to (item 2 of argv) as number
  set charDelaySeconds to (item 3 of argv) as number
  set shouldAppSwitch to ((item 4 of argv) as integer)
  set caseText to item 5 of argv
  tell application appName to activate
  delay 0.8
  tell application "System Events"
    keystroke return
    delay 0.2
    set caseLines to paragraphs of caseText
    set caseIndex to 0
    repeat with caseLine in caseLines
      set lineText to caseLine as text
      if lineText is not "" then
        set AppleScript's text item delimiters to tab
        set fields to text items of lineText
        set AppleScript's text item delimiters to ""
        set queryText to item 1 of fields
        set commitKey to ""
        set actionKey to ""
        set chainRepeats to 0
        if (count of fields) is greater than 1 then set commitKey to item 2 of fields
        if (count of fields) is greater than 2 then set actionKey to item 3 of fields
        if (count of fields) is greater than 3 then set chainRepeats to (item 4 of fields) as integer
        set caseIndex to caseIndex + 1
        keystroke return
        delay 0.2
        repeat with charIndex from 1 to length of queryText
          keystroke (character charIndex of queryText)
          delay charDelaySeconds
        end repeat
        my sendNativeCommit(commitKey)
        delay waitSeconds
        if shouldAppSwitch is 1 and caseIndex is 2 then
          key code 48 using {command down}
          delay 0.8
          tell application appName to activate
          delay 0.8
        end if
        repeat with chainIndex from 1 to chainRepeats
          my sendAssistantAction(actionKey)
          delay waitSeconds
        end repeat
      end if
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
manual_required+=("Native Rime ordinary-number commit plus Tab/Option-number assistant selection across ${AUTO_CASE_COUNT} foreground soak cases, including ${CHAIN_REPEATS} continuous prediction selections")
manual_required+=("Backspace/Delete committed-context resync verification")
if [[ "$AUTO_APP_SWITCH" == "1" ]]; then
  manual_required+=("App switch stale-candidate invalidation verification")
fi

echo "Foreground soak gate is collecting real Squirrel AppKit events."
echo "Trace log: $TRACE_LOG"
echo "Report path: $REPORT_PATH"
echo "Manual action if needed: follow the ${AUTO_CASE_COUNT} cases in $TEST_FILE, waiting for the next prediction after each side-candidate commit."

for item in "${manual_required[@]}"; do
  soak_args+=(--manual-required "$item")
done

"$PYTHON_EXECUTABLE" "${soak_args[@]}"
