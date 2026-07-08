#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
TRACE_LOG="${RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG:-$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl}"
WAIT_SECONDS="${RAG_IME_FOREGROUND_TRACE_WAIT_SECONDS:-60}"
TEST_FILE="${RAG_IME_FOREGROUND_TRACE_TEST_FILE:-$HOME/Desktop/rag-ime-foreground-trace-test.txt}"
OPEN_APP="${RAG_IME_FOREGROUND_TRACE_APP:-TextEdit}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
SELECT_INPUT_SOURCE_SCRIPT="${RAG_IME_SELECT_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/select_macos_input_source.sh}"
TRACE_CHECK_SCRIPT="${RAG_IME_TRACE_CHECK_SCRIPT:-$ROOT/scripts/check_squirrel_frontend_trace.py}"
SOAK_CHECK_SCRIPT="${RAG_IME_SOAK_CHECK_SCRIPT:-$ROOT/scripts/check_squirrel_soak_report.py}"
SOAK_REPORT_PATH="${RAG_IME_SQUIRREL_SOAK_REPORT_PATH:-/tmp/rag-ime-v1-soak-report.json}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
OPEN_COMMAND="${RAG_IME_OPEN_COMMAND:-open}"

CLEAR_TRACE=1
OPEN_TEST_FILE=1
SELECT_INPUT_SOURCE=1
REQUIRE_SIDE_COMMIT=1
REQUIRE_COMMIT_OBSERVED=1
REQUIRE_POST_COMMIT_FOLLOWUP=1
REQUIRE_DELETE_RESYNC="${RAG_IME_FOREGROUND_TRACE_REQUIRE_DELETE_RESYNC:-0}"
REQUIRE_MIXED_PANEL=1
REQUIRE_SIDE_PANEL=0
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_FOREGROUND_TRACE_REQUIRE_HITOOLBOX_ENABLED:-0}"
REQUIRE_MODERN_PREDICTION_SESSION=1
REQUIRE_BALANCED_QUOTA=1
REQUIRE_RIME_COMPOSITION_OK=0
REQUIRE_POST_COMMIT_VISIBLE=0
REQUIRE_POST_COMMIT_PENDING_STATUS=0
REQUIRE_PREDICTION_STATUS_VISIBLE=0
REQUIRE_SOURCE_BADGES=0
REQUIRE_ACTIVE_RAG_ACTION_BUTTON=0
REQUIRE_ACTIVE_RAG_THINKING=0
REQUIRE_ACTIVE_RAG_READY=0
REQUIRE_ACTIVE_RAG_COMMIT=0
REQUIRE_ACTIVE_RAG_STALE_DROP=0
REQUIRE_POST_COMMIT_KEY_POLICY=0
REQUIRE_APP_SWITCH_STALE_DROP=0
REQUIRE_FOLLOWUP_AFTER_SELECT=0
MAX_FIRST_VISIBLE_MS=""
MAX_STALE_APPLY_COUNT=""
MAX_CONTEXT_ECHO_COUNT=""
USE_V1_SOAK_GATE=0
DRY_RUN=0
AUTO_TYPE=0
AUTO_QUERY="${RAG_IME_FOREGROUND_TRACE_AUTO_QUERY:-er qi}"
AUTO_KEY="${RAG_IME_FOREGROUND_TRACE_AUTO_KEY:-6}"
AUTO_KEY_WAS_SET=0
AUTO_TYPE_DELAY="${RAG_IME_FOREGROUND_TRACE_AUTO_DELAY_SECONDS:-2.5}"
AUTO_CHAR_DELAY="${RAG_IME_FOREGROUND_TRACE_AUTO_CHAR_DELAY_SECONDS:-0.04}"

usage() {
  cat <<'USAGE'
Usage: scripts/verify_squirrel_foreground_trace.sh [options]

Clears the patched Squirrel frontend trace, selects Squirrel, opens a small
typing test file, then waits for real foreground AppKit evidence:
  - mixed panel: horizontal MLX/LLM row plus vertical RAG/memory rows
  - side commit: number key accepted one model/RAG side candidate
  - follow-up: accepting a side candidate schedules the next post-commit prediction

Options:
  --wait SECONDS        Seconds to wait for trace evidence (default: 60)
  --mixed-only          Require mixed panel layout but not number-key side commit
  --side-panel-only     Require any model/RAG/memory side panel instead of mixed model+RAG layout
  --no-followup         Do not require post-commit follow-up after side commit
  --no-commit-observed  Do not require a commit_observed trace before follow-up
  --require-delete-resync
                       Require delete/backspace invalidation followed by committed-context resync
  --no-clear            Do not clear the existing frontend trace first
  --no-open             Do not open the TextEdit test file
  --no-select           Do not try to select the Squirrel input source
  --require-hitoolbox-enabled
                       Also require the HIToolbox preference gate before typing
  --no-modern-session   Do not require a non-legacy predictionSession trace
  --no-balanced-quota   Do not require product model/RAG/Rime quota trace
  --report-path PATH    Output JSON report when v1 soak gates are requested
  --require-rime-composition-ok
                       Require composition-time Rime ownership evidence
  --require-post-commit-visible
                       Require a real non-status post-commit prediction panel
  --require-post-commit-pending-status
                       Require the post-commit status/action row before model output
  --require-prediction-status-visible
                       Require a non-selectable status/thinking row in a visible panel
  --require-source-badges
                       Require source badge/color coverage
  --require-active-rag-action-button
                       Require the explicit DeepSeek/Active RAG action button in a post-commit panel
  --require-active-rag-thinking
                       Require Active RAG thinking/status animation evidence
  --require-active-rag-ready
                       Require Active RAG ready candidate evidence
  --require-active-rag-commit
                       Require Active RAG candidate commit evidence
  --require-active-rag-stale-drop-check
                       Require stale/rejected Active RAG transaction evidence
  --require-post-commit-key-policy
                       Require post-commit number-key pass-through policy evidence
  --require-app-switch-stale-drop
                       Require app/focus/input-source stale-drop evidence
  --require-followup-after-select
                       Require side-candidate selection followed by post-commit request
  --max-first-visible-ms N
                       Maximum first useful post-commit visible latency
  --max-stale-apply-count N
                       Maximum stale responses allowed to apply
  --max-context-echo-count N
                       Maximum context-echo candidates allowed
  --auto-type           Try to type the test query and side-candidate key with AppleScript
  --auto-query TEXT     Text used by --auto-type (default: er qi)
  --auto-key KEY        Number key used by --auto-type (default: 6)
                       For Active RAG proof, use ctrl-period by default.
  --auto-char-delay SEC Delay between simulated characters (default: 0.04)
  --active-rag-proof   Require the final DeepSeek action button -> thinking -> ready lifecycle
  --dry-run             Print resolved commands without changing local state
  -h, --help            Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait)
      if [[ $# -lt 2 ]]; then
        echo "--wait requires a value" >&2
        exit 2
      fi
      WAIT_SECONDS="$2"
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
    --no-clear)
      CLEAR_TRACE=0
      ;;
    --no-open)
      OPEN_TEST_FILE=0
      ;;
    --no-select)
      SELECT_INPUT_SOURCE=0
      ;;
    --require-hitoolbox-enabled)
      REQUIRE_HITOOLBOX_ENABLED=1
      ;;
    --no-modern-session)
      REQUIRE_MODERN_PREDICTION_SESSION=0
      ;;
    --no-balanced-quota)
      REQUIRE_BALANCED_QUOTA=0
      ;;
    --report-path)
      if [[ $# -lt 2 ]]; then
        echo "--report-path requires a value" >&2
        exit 2
      fi
      SOAK_REPORT_PATH="$2"
      USE_V1_SOAK_GATE=1
      shift
      ;;
    --require-rime-composition-ok)
      REQUIRE_RIME_COMPOSITION_OK=1
      USE_V1_SOAK_GATE=1
      ;;
    --require-post-commit-visible)
      REQUIRE_POST_COMMIT_VISIBLE=1
      USE_V1_SOAK_GATE=1
      ;;
    --require-post-commit-pending-status)
      REQUIRE_POST_COMMIT_PENDING_STATUS=1
      ;;
    --require-prediction-status-visible)
      REQUIRE_PREDICTION_STATUS_VISIBLE=1
      ;;
    --require-source-badges)
      REQUIRE_SOURCE_BADGES=1
      USE_V1_SOAK_GATE=1
      ;;
    --require-active-rag-action-button)
      REQUIRE_ACTIVE_RAG_ACTION_BUTTON=1
      ;;
    --require-active-rag-thinking)
      REQUIRE_ACTIVE_RAG_THINKING=1
      ;;
    --require-active-rag-ready)
      REQUIRE_ACTIVE_RAG_READY=1
      ;;
    --require-active-rag-commit)
      REQUIRE_ACTIVE_RAG_COMMIT=1
      ;;
    --require-active-rag-stale-drop-check)
      REQUIRE_ACTIVE_RAG_STALE_DROP=1
      ;;
    --require-post-commit-key-policy)
      REQUIRE_POST_COMMIT_KEY_POLICY=1
      USE_V1_SOAK_GATE=1
      ;;
    --require-app-switch-stale-drop)
      REQUIRE_APP_SWITCH_STALE_DROP=1
      USE_V1_SOAK_GATE=1
      ;;
    --require-followup-after-select)
      REQUIRE_FOLLOWUP_AFTER_SELECT=1
      USE_V1_SOAK_GATE=1
      ;;
    --max-first-visible-ms)
      if [[ $# -lt 2 ]]; then
        echo "--max-first-visible-ms requires a value" >&2
        exit 2
      fi
      MAX_FIRST_VISIBLE_MS="$2"
      USE_V1_SOAK_GATE=1
      shift
      ;;
    --max-stale-apply-count)
      if [[ $# -lt 2 ]]; then
        echo "--max-stale-apply-count requires a value" >&2
        exit 2
      fi
      MAX_STALE_APPLY_COUNT="$2"
      USE_V1_SOAK_GATE=1
      shift
      ;;
    --max-context-echo-count)
      if [[ $# -lt 2 ]]; then
        echo "--max-context-echo-count requires a value" >&2
        exit 2
      fi
      MAX_CONTEXT_ECHO_COUNT="$2"
      USE_V1_SOAK_GATE=1
      shift
      ;;
    --auto-type)
      AUTO_TYPE=1
      ;;
    --auto-query)
      if [[ $# -lt 2 ]]; then
        echo "--auto-query requires a value" >&2
        exit 2
      fi
      AUTO_QUERY="$2"
      shift
      ;;
    --auto-key)
      if [[ $# -lt 2 ]]; then
        echo "--auto-key requires a value" >&2
        exit 2
      fi
      AUTO_KEY="$2"
      AUTO_KEY_WAS_SET=1
      shift
      ;;
    --auto-char-delay)
      if [[ $# -lt 2 ]]; then
        echo "--auto-char-delay requires a value" >&2
        exit 2
      fi
      AUTO_CHAR_DELAY="$2"
      shift
      ;;
    --active-rag-proof)
      REQUIRE_MIXED_PANEL=0
      REQUIRE_SIDE_PANEL=0
      REQUIRE_SIDE_COMMIT=0
      REQUIRE_COMMIT_OBSERVED=0
      REQUIRE_POST_COMMIT_FOLLOWUP=0
      REQUIRE_BALANCED_QUOTA=0
      REQUIRE_MODERN_PREDICTION_SESSION=0
      REQUIRE_POST_COMMIT_PENDING_STATUS=1
      REQUIRE_PREDICTION_STATUS_VISIBLE=1
      REQUIRE_ACTIVE_RAG_ACTION_BUTTON=1
      REQUIRE_ACTIVE_RAG_THINKING=1
      REQUIRE_ACTIVE_RAG_READY=1
      if [[ "$AUTO_KEY_WAS_SET" == "0" ]]; then
        AUTO_KEY="${RAG_IME_FOREGROUND_TRACE_ACTIVE_RAG_AUTO_KEY:-ctrl-period}"
      fi
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

trace_args=(
  "$TRACE_CHECK_SCRIPT"
  --log-path "$TRACE_LOG"
  --wait "$WAIT_SECONDS"
  --print-last 8
)
if [[ "$REQUIRE_MIXED_PANEL" == "1" ]]; then
  trace_args+=(--require-mixed-panel)
fi
if [[ "$REQUIRE_SIDE_PANEL" == "1" ]]; then
  trace_args+=(--require-side-panel)
fi
if [[ "$REQUIRE_SIDE_COMMIT" == "1" ]]; then
  trace_args+=(--require-side-commit)
fi
if [[ "$REQUIRE_COMMIT_OBSERVED" == "1" ]]; then
  trace_args+=(--require-commit-observed)
fi
if [[ "$REQUIRE_POST_COMMIT_FOLLOWUP" == "1" ]]; then
  trace_args+=(--require-post-commit-followup)
fi
if [[ "$REQUIRE_DELETE_RESYNC" == "1" ]]; then
  trace_args+=(--require-delete-resync)
fi
if [[ "$REQUIRE_MODERN_PREDICTION_SESSION" == "1" ]]; then
  trace_args+=(--require-modern-prediction-session)
fi
if [[ "$REQUIRE_BALANCED_QUOTA" == "1" ]]; then
  trace_args+=(--require-balanced-quota)
fi
if [[ "$REQUIRE_POST_COMMIT_PENDING_STATUS" == "1" ]]; then
  trace_args+=(--require-post-commit-pending-status)
fi
if [[ "$REQUIRE_PREDICTION_STATUS_VISIBLE" == "1" ]]; then
  trace_args+=(--require-prediction-status-visible)
fi
if [[ "$REQUIRE_ACTIVE_RAG_ACTION_BUTTON" == "1" ]]; then
  trace_args+=(--require-active-rag-action-button)
fi
if [[ "$REQUIRE_ACTIVE_RAG_THINKING" == "1" ]]; then
  trace_args+=(--require-active-rag-thinking)
fi
if [[ "$REQUIRE_ACTIVE_RAG_READY" == "1" ]]; then
  trace_args+=(--require-active-rag-ready)
fi
if [[ "$REQUIRE_ACTIVE_RAG_COMMIT" == "1" ]]; then
  trace_args+=(--require-active-rag-commit)
fi
if [[ "$REQUIRE_ACTIVE_RAG_STALE_DROP" == "1" ]]; then
  trace_args+=(--require-active-rag-stale-drop-check)
fi

soak_args=(
  "$SOAK_CHECK_SCRIPT"
  --log-path "$TRACE_LOG"
  --report-path "$SOAK_REPORT_PATH"
  --wait "$WAIT_SECONDS"
  --print-last 8
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
if [[ "$REQUIRE_RIME_COMPOSITION_OK" == "1" ]]; then
  soak_args+=(--require-rime-composition-ok)
fi
if [[ "$REQUIRE_POST_COMMIT_VISIBLE" == "1" ]]; then
  soak_args+=(--require-post-commit-visible)
fi
if [[ "$REQUIRE_SOURCE_BADGES" == "1" ]]; then
  soak_args+=(--require-source-badges)
fi
if [[ "$REQUIRE_POST_COMMIT_KEY_POLICY" == "1" ]]; then
  soak_args+=(--require-post-commit-key-policy)
fi
if [[ "$REQUIRE_APP_SWITCH_STALE_DROP" == "1" ]]; then
  soak_args+=(--require-app-switch-stale-drop)
fi
if [[ "$REQUIRE_FOLLOWUP_AFTER_SELECT" == "1" ]]; then
  soak_args+=(--require-followup-after-select)
fi
if [[ -n "$MAX_FIRST_VISIBLE_MS" ]]; then
  soak_args+=(--max-first-visible-ms "$MAX_FIRST_VISIBLE_MS")
fi
if [[ -n "$MAX_STALE_APPLY_COUNT" ]]; then
  soak_args+=(--max-stale-apply-count "$MAX_STALE_APPLY_COUNT")
fi
if [[ -n "$MAX_CONTEXT_ECHO_COUNT" ]]; then
  soak_args+=(--max-context-echo-count "$MAX_CONTEXT_ECHO_COUNT")
fi

gate_mode="trace"
gate_args=("${trace_args[@]}")
if [[ "$USE_V1_SOAK_GATE" == "1" ]]; then
  gate_mode="v1-soak"
  gate_args=("${soak_args[@]}")
fi

if [[ "$DRY_RUN" == "1" ]]; then
  cat <<EOF
repo_root=$ROOT
input_source_id=$INPUT_SOURCE_ID
trace_log=$TRACE_LOG
soak_report_path=$SOAK_REPORT_PATH
wait_seconds=$WAIT_SECONDS
test_file=$TEST_FILE
open_app=$OPEN_APP
clear_trace=$CLEAR_TRACE
open_test_file=$OPEN_TEST_FILE
select_input_source=$SELECT_INPUT_SOURCE
require_side_commit=$REQUIRE_SIDE_COMMIT
require_commit_observed=$REQUIRE_COMMIT_OBSERVED
require_post_commit_followup=$REQUIRE_POST_COMMIT_FOLLOWUP
require_delete_resync=$REQUIRE_DELETE_RESYNC
require_mixed_panel=$REQUIRE_MIXED_PANEL
require_side_panel=$REQUIRE_SIDE_PANEL
require_hitoolbox_enabled=$REQUIRE_HITOOLBOX_ENABLED
require_modern_prediction_session=$REQUIRE_MODERN_PREDICTION_SESSION
require_balanced_quota=$REQUIRE_BALANCED_QUOTA
require_rime_composition_ok=$REQUIRE_RIME_COMPOSITION_OK
require_post_commit_visible=$REQUIRE_POST_COMMIT_VISIBLE
require_post_commit_pending_status=$REQUIRE_POST_COMMIT_PENDING_STATUS
require_prediction_status_visible=$REQUIRE_PREDICTION_STATUS_VISIBLE
require_source_badges=$REQUIRE_SOURCE_BADGES
require_active_rag_action_button=$REQUIRE_ACTIVE_RAG_ACTION_BUTTON
require_active_rag_thinking=$REQUIRE_ACTIVE_RAG_THINKING
require_active_rag_ready=$REQUIRE_ACTIVE_RAG_READY
require_active_rag_commit=$REQUIRE_ACTIVE_RAG_COMMIT
require_active_rag_stale_drop=$REQUIRE_ACTIVE_RAG_STALE_DROP
require_post_commit_key_policy=$REQUIRE_POST_COMMIT_KEY_POLICY
require_app_switch_stale_drop=$REQUIRE_APP_SWITCH_STALE_DROP
require_followup_after_select=$REQUIRE_FOLLOWUP_AFTER_SELECT
max_first_visible_ms=$MAX_FIRST_VISIBLE_MS
max_stale_apply_count=$MAX_STALE_APPLY_COUNT
max_context_echo_count=$MAX_CONTEXT_ECHO_COUNT
gate_mode=$gate_mode
auto_type=$AUTO_TYPE
auto_query=$AUTO_QUERY
auto_key=$AUTO_KEY
auto_type_delay=$AUTO_TYPE_DELAY
auto_char_delay=$AUTO_CHAR_DELAY
check_input_source_script=$CHECK_INPUT_SOURCE_SCRIPT
select_input_source_script=$SELECT_INPUT_SOURCE_SCRIPT
trace_check_command=$PYTHON_EXECUTABLE ${trace_args[*]}
soak_check_command=$PYTHON_EXECUTABLE ${soak_args[*]}
gate_command=$PYTHON_EXECUTABLE ${gate_args[*]}
EOF
  exit 0
fi

if [[ "$REQUIRE_HITOOLBOX_ENABLED" == "1" ]]; then
  "$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"
else
  "$CHECK_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID"
fi

if [[ "$SELECT_INPUT_SOURCE" == "1" ]]; then
  "$SELECT_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID"
else
  "$CHECK_INPUT_SOURCE_SCRIPT" --require-selected "$INPUT_SOURCE_ID"
fi

if [[ "$CLEAR_TRACE" == "1" ]]; then
  "$PYTHON_EXECUTABLE" "$TRACE_CHECK_SCRIPT" --log-path "$TRACE_LOG" --clear >/dev/null
fi

if [[ "$OPEN_TEST_FILE" == "1" ]]; then
  mkdir -p "$(dirname "$TEST_FILE")"
  "$PYTHON_EXECUTABLE" - "$TEST_FILE" "$AUTO_QUERY" "$INPUT_SOURCE_ID" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
query = sys.argv[2]
input_source = sys.argv[3]
path.write_text(
    "RAG-IME foreground trace test\n\n"
    f"1. Make sure the active input source is {input_source}.\n"
    f"2. Type: {query}.\n"
    "3. Wait for LLM/model, RAG, and memory candidates in the panel.\n"
    "4. Press a visible candidate number to accept a side candidate and wait for the next prediction.\n\n"
    "5. Press Ctrl+. and wait for the animated thinking row, then one ready candidate.\n\n",
    encoding="utf-8",
)
PY
  "$OPEN_COMMAND" -a "$OPEN_APP" "$TEST_FILE" >/dev/null 2>&1 || {
    echo "warning: failed to open $OPEN_APP with $TEST_FILE" >&2
    echo "Open any normal editor manually and type with Squirrel selected." >&2
  }
fi

if [[ "$AUTO_TYPE" == "1" ]]; then
  set +e
  osascript - "$OPEN_APP" "$AUTO_QUERY" "$AUTO_KEY" "$AUTO_TYPE_DELAY" "$AUTO_CHAR_DELAY" <<'APPLESCRIPT'
on run argv
  set appName to item 1 of argv
  set queryText to item 2 of argv
  set actionKey to item 3 of argv
  set waitSeconds to (item 4 of argv) as number
  set charDelaySeconds to (item 5 of argv) as number
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
    if actionKey is "tab" then
      key code 48
    else if actionKey is "ctrl-period" or actionKey is "control-period" or actionKey is "ctrl-." or actionKey is "control-." then
      keystroke "." using control down
    else if actionKey is "ctrl-enter" or actionKey is "control-enter" then
      key code 36 using control down
    else if actionKey is "ctrl-return" or actionKey is "control-return" then
      key code 36 using control down
    else if actionKey is "return" then
      key code 36
    else if actionKey is "enter" then
      key code 76
    else if actionKey begins with "option-" then
      set digitText to text 8 thru -1 of actionKey
      set digitKeyCodes to {{"1", 18}, {"2", 19}, {"3", 20}, {"4", 21}, {"5", 23}, {"6", 22}, {"7", 26}, {"8", 28}, {"9", 25}, {"0", 29}}
      repeat with digitKeyPair in digitKeyCodes
        if item 1 of digitKeyPair is digitText then
          key code (item 2 of digitKeyPair) using option down
          return
        end if
      end repeat
      keystroke actionKey
    else
      keystroke actionKey
    end if
  end tell
end run
APPLESCRIPT
  auto_type_status=$?
  set -e
  if [[ "$auto_type_status" != "0" ]]; then
    cat >&2 <<'EOF'
warning: automatic foreground typing failed.
This is usually a macOS Accessibility permission issue, not an IME failure.

To allow auto typing, grant Accessibility permission to the app running this
command, usually Codex and/or your terminal:
  System Settings -> Privacy & Security -> Accessibility

Manual fallback:
  click the opened editor, type "$AUTO_QUERY", then press a visible side-candidate number.
EOF
  fi
fi

cat <<EOF
Foreground trace gate is waiting for real Squirrel AppKit events.

Manual action now:
  1. Click the opened editor or any normal text field.
  2. Type: $AUTO_QUERY
  3. Wait for LLM/model, RAG, and memory candidates in the panel.
  4. Press a visible candidate number to commit a side candidate.
  5. Press Ctrl+. and wait for thinking animation plus one ready candidate.

Trace log:
  $TRACE_LOG
EOF

"$PYTHON_EXECUTABLE" "${gate_args[@]}"
