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
DRY_RUN=0
AUTO_TYPE=0
AUTO_QUERY="${RAG_IME_FOREGROUND_TRACE_AUTO_QUERY:-er qi}"
AUTO_KEY="${RAG_IME_FOREGROUND_TRACE_AUTO_KEY:-6}"
AUTO_TYPE_DELAY="${RAG_IME_FOREGROUND_TRACE_AUTO_DELAY_SECONDS:-2.5}"

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
  --no-clear            Do not clear the existing frontend trace first
  --no-open             Do not open the TextEdit test file
  --no-select           Do not try to select the Squirrel input source
  --auto-type           Try to type the test query and side-candidate key with AppleScript
  --auto-query TEXT     Text used by --auto-type (default: er qi)
  --auto-key KEY        Number key used by --auto-type (default: 6)
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
    --no-clear)
      CLEAR_TRACE=0
      ;;
    --no-open)
      OPEN_TEST_FILE=0
      ;;
    --no-select)
      SELECT_INPUT_SOURCE=0
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
  --require-mixed-panel
  --print-last 8
)
if [[ "$REQUIRE_SIDE_COMMIT" == "1" ]]; then
  trace_args+=(--require-side-commit)
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
auto_type=$AUTO_TYPE
auto_query=$AUTO_QUERY
auto_key=$AUTO_KEY
auto_type_delay=$AUTO_TYPE_DELAY
check_input_source_script=$CHECK_INPUT_SOURCE_SCRIPT
select_input_source_script=$SELECT_INPUT_SOURCE_SCRIPT
trace_check_command=$PYTHON_EXECUTABLE ${trace_args[*]}
EOF
  exit 0
fi

"$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"

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
  "$PYTHON_EXECUTABLE" - "$TEST_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser()
path.write_text(
    "RAG-IME foreground trace test\n\n"
    "1. Make sure the active input source is Squirrel - Simplified.\n"
    "2. Type a semantic pinyin prefix such as: er qi, xian zai, rag shu ru fa.\n"
    "3. Wait for the mixed panel: 1-5 horizontal MLX/LLM, 6-8 vertical RAG/memory.\n"
    "4. Press 6, 7, or 8 to accept a side sentence candidate.\n\n",
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
  osascript - "$OPEN_APP" "$AUTO_QUERY" "$AUTO_KEY" "$AUTO_TYPE_DELAY" <<'APPLESCRIPT'
on run argv
  set appName to item 1 of argv
  set queryText to item 2 of argv
  set sideKey to item 3 of argv
  set waitSeconds to (item 4 of argv) as number
  tell application appName to activate
  delay 0.8
  tell application "System Events"
    keystroke return
    delay 0.2
    keystroke queryText
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
  click the opened editor, type "er qi", then press 6, 7, or 8.
EOF
  fi
fi

cat <<EOF
Foreground trace gate is waiting for real Squirrel AppKit events.

Manual action now:
  1. Click the opened editor or any normal text field.
  2. Type: er qi
  3. Wait for 1-5 horizontal MLX/LLM candidates and 6-8 vertical RAG/memory rows.
  4. Press 6, 7, or 8 to commit a side candidate.

Trace log:
  $TRACE_LOG
EOF

"$PYTHON_EXECUTABLE" "${trace_args[@]}"
