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
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
OPEN_COMMAND="${RAG_IME_OPEN_COMMAND:-open}"

CLEAR_TRACE=1
OPEN_TEST_FILE=1
SELECT_INPUT_SOURCE=1
REQUIRE_SIDE_COMMIT=1
REQUIRE_MIXED_PANEL=1
REQUIRE_SIDE_PANEL=0
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_FOREGROUND_TRACE_REQUIRE_HITOOLBOX_ENABLED:-0}"
REQUIRE_MODERN_PREDICTION_SESSION=1
DRY_RUN=0
AUTO_TYPE=0
AUTO_QUERY="${RAG_IME_FOREGROUND_TRACE_AUTO_QUERY:-er qi}"
AUTO_KEY="${RAG_IME_FOREGROUND_TRACE_AUTO_KEY:-6}"
AUTO_TYPE_DELAY="${RAG_IME_FOREGROUND_TRACE_AUTO_DELAY_SECONDS:-2.5}"
AUTO_CHAR_DELAY="${RAG_IME_FOREGROUND_TRACE_AUTO_CHAR_DELAY_SECONDS:-0.04}"

usage() {
  cat <<'USAGE'
Usage: scripts/verify_squirrel_foreground_trace.sh [options]

Clears the patched Squirrel frontend trace, selects Squirrel, opens a small
typing test file, then waits for real foreground AppKit evidence:
  - mixed panel: horizontal MLX/LLM row plus vertical RAG/memory rows
  - side commit: number key accepted one model/RAG side candidate

Options:
  --wait SECONDS        Seconds to wait for trace evidence (default: 60)
  --mixed-only          Require mixed panel layout but not number-key side commit
  --side-panel-only     Require any model/RAG/memory side panel instead of mixed model+RAG layout
  --no-clear            Do not clear the existing frontend trace first
  --no-open             Do not open the TextEdit test file
  --no-select           Do not try to select the Squirrel input source
  --require-hitoolbox-enabled
                       Also require the HIToolbox preference gate before typing
  --no-modern-session   Do not require a non-legacy predictionSession trace
  --auto-type           Try to type the test query and side-candidate key with AppleScript
  --auto-query TEXT     Text used by --auto-type (default: er qi)
  --auto-key KEY        Number key used by --auto-type (default: 6)
  --auto-char-delay SEC Delay between simulated characters (default: 0.04)
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
      ;;
    --side-panel-only)
      REQUIRE_MIXED_PANEL=0
      REQUIRE_SIDE_PANEL=1
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
if [[ "$REQUIRE_MODERN_PREDICTION_SESSION" == "1" ]]; then
  trace_args+=(--require-modern-prediction-session)
fi

if [[ "$DRY_RUN" == "1" ]]; then
  cat <<EOF
repo_root=$ROOT
input_source_id=$INPUT_SOURCE_ID
trace_log=$TRACE_LOG
wait_seconds=$WAIT_SECONDS
test_file=$TEST_FILE
open_app=$OPEN_APP
clear_trace=$CLEAR_TRACE
open_test_file=$OPEN_TEST_FILE
select_input_source=$SELECT_INPUT_SOURCE
require_side_commit=$REQUIRE_SIDE_COMMIT
require_mixed_panel=$REQUIRE_MIXED_PANEL
require_side_panel=$REQUIRE_SIDE_PANEL
require_hitoolbox_enabled=$REQUIRE_HITOOLBOX_ENABLED
require_modern_prediction_session=$REQUIRE_MODERN_PREDICTION_SESSION
auto_type=$AUTO_TYPE
auto_query=$AUTO_QUERY
auto_key=$AUTO_KEY
auto_type_delay=$AUTO_TYPE_DELAY
auto_char_delay=$AUTO_CHAR_DELAY
check_input_source_script=$CHECK_INPUT_SOURCE_SCRIPT
select_input_source_script=$SELECT_INPUT_SOURCE_SCRIPT
trace_check_command=$PYTHON_EXECUTABLE ${trace_args[*]}
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
    "4. Press a visible candidate number to accept a side candidate.\n\n",
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
  set sideKey to item 3 of argv
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
    keystroke sideKey
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

Trace log:
  $TRACE_LOG
EOF

"$PYTHON_EXECUTABLE" "${trace_args[@]}"
