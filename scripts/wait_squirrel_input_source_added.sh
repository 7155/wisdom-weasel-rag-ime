#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
INPUT_SOURCE_NAME="${RAG_IME_SQUIRREL_INPUT_SOURCE_NAME:-}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
TIMEOUT_SECONDS="${RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS:-180}"
POLL_SECONDS="${RAG_IME_INPUT_SOURCE_ADDED_POLL_SECONDS:-1}"

deadline=$((SECONDS + TIMEOUT_SECONDS))

infer_input_source_name() {
  if [[ -n "$INPUT_SOURCE_NAME" ]]; then
    printf '%s\n' "$INPUT_SOURCE_NAME"
    return
  fi
  case "$INPUT_SOURCE_ID" in
    *RagIme.Hans) printf 'RAG-IME - Simplified\n' ;;
    *RagIme.Hant) printf 'RAG-IME - Traditional\n' ;;
    *Squirrel.Hant) printf 'Squirrel - Traditional\n' ;;
    *) printf 'Squirrel - Simplified\n' ;;
  esac
}

display_name="$(infer_input_source_name)"
product_name="${display_name% - Simplified}"
product_name="${product_name% - Traditional}"

echo "Waiting for $product_name to be added to the current user's macOS input-source lists: $INPUT_SOURCE_ID"
echo "Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> $display_name."

last_output=""
while [[ "$SECONDS" -le "$deadline" ]]; do
  if last_output="$("$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
    echo "input-source-added: $last_output"
    echo "Next: switch the macOS input menu to $display_name, then run scripts/wait_squirrel_typing_ready.sh"
    exit 0
  fi
  sleep "$POLL_SECONDS"
done

echo "$product_name was not fully added before timeout: $INPUT_SOURCE_ID" >&2
if [[ -n "$last_output" ]]; then
  echo "$last_output" >&2
fi
echo "If thirdPartyEnabled=false, use the System Settings Add flow; command-line writes may be ignored by macOS 27." >&2
echo "Recommended helper: scripts/open_squirrel_input_source_settings.sh --wait" >&2
exit 1
