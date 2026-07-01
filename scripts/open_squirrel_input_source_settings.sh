#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
INPUT_SOURCE_NAME="${RAG_IME_SQUIRREL_INPUT_SOURCE_NAME:-}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
WAIT_SCRIPT="${RAG_IME_WAIT_SQUIRREL_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/wait_squirrel_input_source_added.sh}"
OPEN_COMMAND="${RAG_IME_OPEN_COMMAND:-open}"
SETTINGS_URL="${RAG_IME_KEYBOARD_SETTINGS_URL:-x-apple.systempreferences:com.apple.Keyboard-Settings.extension}"

OPEN_SETTINGS=1
WAIT_AFTER_OPEN=0

usage() {
  cat <<'USAGE'
Usage: scripts/open_squirrel_input_source_settings.sh [--wait] [--no-open]

Opens macOS Keyboard settings and prints the exact manual Add flow for Squirrel.
This helper does not click System Settings or modify input-source preferences.

Options:
  --wait     After opening settings, run scripts/wait_squirrel_input_source_added.sh.
  --no-open  Print the manual flow without launching System Settings.
  -h, --help Show this help.
USAGE
}

infer_input_source_name() {
  if [[ -n "$INPUT_SOURCE_NAME" ]]; then
    printf '%s\n' "$INPUT_SOURCE_NAME"
    return
  fi
  case "$INPUT_SOURCE_ID" in
    *RagIme.Hans)
      printf 'RAG-IME - Simplified\n'
      ;;
    *RagIme.Hant)
      printf 'RAG-IME - Traditional\n'
      ;;
    *Squirrel.Hant)
      printf 'Squirrel - Traditional\n'
      ;;
    *)
      printf 'Squirrel - Simplified\n'
      ;;
  esac
}

display_name="$(infer_input_source_name)"
product_name="${display_name% - Simplified}"
product_name="${product_name% - Traditional}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait)
      WAIT_AFTER_OPEN=1
      ;;
    --no-open)
      OPEN_SETTINGS=0
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

if added_output="$("$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
  echo "$product_name is already fully added to the current user's macOS input-source lists."
  echo "$added_output"
  echo "Next: switch the macOS input menu to $display_name, then run scripts/wait_squirrel_typing_ready.sh"
  exit 0
fi

echo "$product_name is not fully added to the current user's macOS input-source lists: $INPUT_SOURCE_ID"
echo "$added_output"
echo
echo "Manual Add flow:"
echo "  System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> $display_name"
echo

if [[ "$OPEN_SETTINGS" -eq 1 ]]; then
  if command -v "$OPEN_COMMAND" >/dev/null 2>&1; then
    if "$OPEN_COMMAND" "$SETTINGS_URL" >/dev/null 2>&1; then
      echo "Opened Keyboard settings: $SETTINGS_URL"
    else
      echo "warning: failed to open Keyboard settings URL: $SETTINGS_URL" >&2
      echo "Open System Settings manually and use the Add flow above." >&2
    fi
  else
    echo "warning: open command is unavailable: $OPEN_COMMAND" >&2
    echo "Open System Settings manually and use the Add flow above." >&2
  fi
else
  echo "Skipped opening System Settings because --no-open was supplied."
fi

echo
echo "After adding $display_name, verify with:"
echo "  scripts/wait_squirrel_input_source_added.sh"
echo

if [[ "$WAIT_AFTER_OPEN" -eq 1 ]]; then
  exec "$WAIT_SCRIPT"
fi
