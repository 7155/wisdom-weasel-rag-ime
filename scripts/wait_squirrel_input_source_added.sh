#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
TIMEOUT_SECONDS="${RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS:-180}"
POLL_SECONDS="${RAG_IME_INPUT_SOURCE_ADDED_POLL_SECONDS:-1}"

deadline=$((SECONDS + TIMEOUT_SECONDS))

echo "Waiting for Squirrel to be added to the current user's macOS input-source lists: $INPUT_SOURCE_ID"
echo "Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel."

last_output=""
while [[ "$SECONDS" -le "$deadline" ]]; do
  if last_output="$("$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
    echo "input-source-added: $last_output"
    echo "Next: switch the macOS input menu to Squirrel - Simplified, then run scripts/wait_squirrel_typing_ready.sh"
    exit 0
  fi
  sleep "$POLL_SECONDS"
done

echo "Squirrel was not fully added before timeout: $INPUT_SOURCE_ID" >&2
if [[ -n "$last_output" ]]; then
  echo "$last_output" >&2
fi
echo "If thirdPartyEnabled=false, use the System Settings Add flow; command-line writes may be ignored by macOS 27." >&2
echo "Recommended helper: scripts/open_squirrel_input_source_settings.sh --wait" >&2
exit 1
