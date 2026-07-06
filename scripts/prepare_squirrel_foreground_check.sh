#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
REPORT_PATH="${RAG_IME_INPUT_SOURCE_AUDIT_REPORT:-/tmp/rag-ime-input-source-audit.json}"
AUDIT_SCRIPT="${RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/audit_squirrel_input_source.py}"
OPEN_SETTINGS_SCRIPT="${RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT:-$ROOT/scripts/open_squirrel_input_source_settings.sh}"
WAIT_ADDED_SCRIPT="${RAG_IME_WAIT_SQUIRREL_INPUT_SOURCE_ADDED_SCRIPT:-$ROOT/scripts/wait_squirrel_input_source_added.sh}"
WAIT_TYPING_SCRIPT="${RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT:-$ROOT/scripts/wait_squirrel_typing_ready.sh}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

OPEN_SETTINGS=1
WAIT_ADDED=1
WAIT_TYPING=1
FOREGROUND_READY=0

usage() {
  cat <<'USAGE'
Usage: scripts/prepare_squirrel_foreground_check.sh [options]

Runs the real-foreground readiness flow for the product Squirrel input source:
read-only audit -> optional System Settings Add flow -> wait for input-source
selection -> sidecar health check.

Options:
  --report-path PATH  Write the input-source audit JSON to PATH.
  --no-open           Do not open System Settings if the source is not added.
  --no-wait-added     Do not wait for the System Settings Add flow to complete.
  --no-wait-typing    Do not wait for the source to be selected/current.
  -h, --help          Show this help.

Environment:
  RAG_IME_SQUIRREL_INPUT_SOURCE_ID=id  Defaults to im.rime.inputmethod.Squirrel.Hans.
  RAG_IME_INPUT_SOURCE_AUDIT_REPORT=PATH
  RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT=PATH
  RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT=PATH
  RAG_IME_WAIT_SQUIRREL_INPUT_SOURCE_ADDED_SCRIPT=PATH
  RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT=PATH
USAGE
}

while (($#)); do
  case "$1" in
    --report-path)
      REPORT_PATH="${2:?--report-path requires a value}"
      shift 2
      ;;
    --no-open)
      OPEN_SETTINGS=0
      shift
      ;;
    --no-wait-added)
      WAIT_ADDED=0
      shift
      ;;
    --no-wait-typing)
      WAIT_TYPING=0
      shift
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
done

log() {
  printf '[foreground-ready] %s\n' "$*"
}

json_value() {
  "$PYTHON_BIN" - "$REPORT_PATH" "$1" <<'PY'
import json
import sys

path = sys.argv[1]
selector = sys.argv[2].split(".")
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
value = payload
for part in selector:
    if not isinstance(value, dict):
        value = ""
        break
    value = value.get(part, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PY
}

log "input_source_id=$INPUT_SOURCE_ID"
log "audit_report=$REPORT_PATH"

set +e
"$AUDIT_SCRIPT" --input-source-id "$INPUT_SOURCE_ID" --report-path "$REPORT_PATH"
audit_status=$?
set -e

state="$(json_value readiness.state 2>/dev/null || true)"
next_action="$(json_value readiness.nextAction 2>/dev/null || true)"
duplicate_count="$(json_value launchServices.duplicatePathCount 2>/dev/null || true)"

log "audit_exit_code=$audit_status"
log "readiness_state=${state:-unknown}"
if [[ -n "$next_action" ]]; then
  log "next_action=$next_action"
fi
if [[ -n "$duplicate_count" && "$duplicate_count" != "0" ]]; then
  log "duplicate_squirrel_app_paths=$duplicate_count"
fi

case "$state" in
  ready)
    log "Squirrel is added and selected."
    ;;
  switch)
    log "Squirrel is added but not current; use the macOS input menu to select it."
    ;;
  third-party-missing|preferences-incomplete)
    if [[ "$OPEN_SETTINGS" == "1" ]]; then
      log "opening System Settings Add flow"
      if [[ "$WAIT_ADDED" == "1" ]]; then
        "$OPEN_SETTINGS_SCRIPT" --wait
      else
        "$OPEN_SETTINGS_SCRIPT"
      fi
    else
      log "System Settings open skipped; run scripts/open_squirrel_input_source_settings.sh --wait"
    fi
    ;;
  missing)
    log "Squirrel input source is missing; install/register patched Squirrel first."
    exit 2
    ;;
  *)
    log "unknown input-source readiness state; inspect $REPORT_PATH"
    exit 3
    ;;
esac

if [[ "$WAIT_TYPING" == "1" ]]; then
  log "waiting for selected input source and sidecar health"
  "$WAIT_TYPING_SCRIPT"
  FOREGROUND_READY=1
elif [[ "$state" == "ready" ]]; then
  FOREGROUND_READY=1
else
  log "typing-ready wait skipped"
fi

if [[ "$FOREGROUND_READY" == "1" ]]; then
  log "ready for foreground trace verification"
  log "next: scripts/verify_squirrel_foreground_trace.sh"
else
  log "foreground trace verification is still pending; complete the input-source Add/select flow first"
  exit 1
fi
