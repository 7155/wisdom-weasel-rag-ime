#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
REPORT_PATH="${RAG_IME_INPUT_SOURCE_AUDIT_REPORT:-/tmp/rag-ime-input-source-audit.json}"
SUMMARY_PATH="${RAG_IME_FOREGROUND_READINESS_REPORT:-/tmp/rag-ime-foreground-readiness.json}"
AUDIT_SCRIPT="${RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/audit_squirrel_input_source.py}"
OPEN_SETTINGS_SCRIPT="${RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT:-$ROOT/scripts/open_squirrel_input_source_settings.sh}"
REFRESH_REGISTRATION_SCRIPT="${RAG_IME_REFRESH_SQUIRREL_INPUT_SOURCE_REGISTRATION_SCRIPT:-$ROOT/scripts/refresh_squirrel_input_source_registration.sh}"
WAIT_ADDED_SCRIPT="${RAG_IME_WAIT_SQUIRREL_INPUT_SOURCE_ADDED_SCRIPT:-$ROOT/scripts/wait_squirrel_input_source_added.sh}"
WAIT_TYPING_SCRIPT="${RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT:-$ROOT/scripts/wait_squirrel_typing_ready.sh}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

OPEN_SETTINGS=1
WAIT_ADDED=1
WAIT_TYPING=1
REFRESH_REGISTRATION=0
FOREGROUND_READY=0
refresh_status=""
audit_status=""
state=""
next_action=""
duplicate_count=""

usage() {
  cat <<'USAGE'
Usage: scripts/prepare_squirrel_foreground_check.sh [options]

Runs the real-foreground readiness flow for the product Squirrel input source:
read-only audit -> optional System Settings Add flow -> wait for input-source
selection -> sidecar health check.

Options:
  --report-path PATH  Write the input-source audit JSON to PATH.
  --summary-path PATH Write foreground readiness summary JSON to PATH.
  --no-open           Do not open System Settings if the source is not added.
  --refresh-registration
                      Refresh LaunchServices/Squirrel registration before audit.
  --no-wait-added     Do not wait for the System Settings Add flow to complete.
  --no-wait-typing    Do not wait for the source to be selected/current.
  -h, --help          Show this help.

Environment:
  RAG_IME_SQUIRREL_INPUT_SOURCE_ID=id  Defaults to im.rime.inputmethod.Squirrel.Hans.
  RAG_IME_INPUT_SOURCE_AUDIT_REPORT=PATH
  RAG_IME_FOREGROUND_READINESS_REPORT=PATH
  RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT=PATH
  RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT=PATH
  RAG_IME_REFRESH_SQUIRREL_INPUT_SOURCE_REGISTRATION_SCRIPT=PATH
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
    --summary-path)
      SUMMARY_PATH="${2:?--summary-path requires a value}"
      shift 2
      ;;
    --no-open)
      OPEN_SETTINGS=0
      shift
      ;;
    --refresh-registration)
      REFRESH_REGISTRATION=1
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

write_summary() {
  local exit_code="${1:-0}"
  "$PYTHON_BIN" - "$SUMMARY_PATH" "$REPORT_PATH" "$INPUT_SOURCE_ID" "$exit_code" \
    "${state:-}" "${next_action:-}" "${duplicate_count:-}" "${refresh_status:-}" "${audit_status:-}" \
    "$FOREGROUND_READY" "$OPEN_SETTINGS" "$WAIT_ADDED" "$WAIT_TYPING" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1]).expanduser()
audit_path = Path(sys.argv[2]).expanduser()
input_source_id = sys.argv[3]
exit_code = int(sys.argv[4] or 0)
state = sys.argv[5]
next_action = sys.argv[6]
duplicate_count_arg = sys.argv[7]
refresh_status = sys.argv[8]
audit_status = sys.argv[9]
foreground_ready = sys.argv[10] == "1"
open_settings = sys.argv[11] == "1"
wait_added = sys.argv[12] == "1"
wait_typing = sys.argv[13] == "1"

audit_payload = {}
if audit_path.exists():
    try:
        audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive helper path
        audit_payload = {"readError": exc.__class__.__name__}

readiness = audit_payload.get("readiness") if isinstance(audit_payload.get("readiness"), dict) else {}
launch_services = audit_payload.get("launchServices") if isinstance(audit_payload.get("launchServices"), dict) else {}
state = state or str(readiness.get("state") or "unknown")
next_action = next_action or str(readiness.get("nextAction") or "")
try:
    duplicate_count = int(duplicate_count_arg or launch_services.get("duplicatePathCount") or 0)
except (TypeError, ValueError):
    duplicate_count = 0

matching_paths = []
records = launch_services.get("matchingRecords")
for record in records if isinstance(records, list) else []:
    if not isinstance(record, dict):
        continue
    path = str(record.get("path") or "")
    if path and path not in matching_paths:
        matching_paths.append(path)
duplicate_paths = matching_paths if duplicate_count else []

manual_required = []
commands = []
if duplicate_count:
    manual_required.append("Remove or refresh stale Squirrel LaunchServices registrations.")
    commands.append("scripts/prepare_squirrel_foreground_check.sh --refresh-registration --no-open --no-wait-typing")
    commands.append("RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1 scripts/refresh_squirrel_input_source_registration.sh")
if state in {"third-party-missing", "preferences-incomplete"}:
    manual_required.append("Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel - Simplified.")
    commands.append("scripts/open_squirrel_input_source_settings.sh --wait")
    commands.append("scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json")
elif state == "switch":
    manual_required.append("Select Squirrel - Simplified from the macOS input menu.")
    commands.append("scripts/wait_squirrel_typing_ready.sh")
elif state == "missing":
    manual_required.append("Install/register the patched Squirrel.app before foreground verification.")
    commands.append("scripts/build_patched_squirrel.sh install")
if foreground_ready:
    commands.append("scripts/verify_squirrel_foreground_trace.sh")
elif wait_typing:
    commands.append("scripts/wait_squirrel_typing_ready.sh")

payload = {
    "schemaVersion": "rag-ime.foreground-readiness.v1",
    "ok": exit_code == 0 and foreground_ready,
    "exitCode": exit_code,
    "inputSourceId": input_source_id,
    "auditReportPath": str(audit_path),
    "readinessState": state,
    "nextAction": next_action,
    "foregroundReady": foreground_ready,
    "manualRequired": list(dict.fromkeys(item for item in manual_required if item)),
    "commands": list(dict.fromkeys(item for item in commands if item)),
    "duplicatePathCount": duplicate_count,
    "duplicatePaths": duplicate_paths,
    "matchingPaths": matching_paths,
    "refreshRegistrationExitCode": int(refresh_status) if str(refresh_status).strip().lstrip("-").isdigit() else None,
    "auditExitCode": int(audit_status) if str(audit_status).strip().lstrip("-").isdigit() else None,
    "flow": {
        "openSettings": open_settings,
        "waitAdded": wait_added,
        "waitTyping": wait_typing,
    },
}
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

trap 'status=$?; write_summary "$status" >/dev/null 2>&1 || true; exit "$status"' EXIT

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

print_duplicate_paths() {
  "$PYTHON_BIN" - "$REPORT_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
records = payload.get("launchServices", {}).get("matchingRecords", [])
paths = []
for record in records if isinstance(records, list) else []:
    if not isinstance(record, dict):
        continue
    path = str(record.get("path") or "")
    if path and path not in paths:
        paths.append(path)
for path in paths:
    print(path)
PY
}

log "input_source_id=$INPUT_SOURCE_ID"
log "audit_report=$REPORT_PATH"
log "readiness_summary=$SUMMARY_PATH"

if [[ "$REFRESH_REGISTRATION" == "1" ]]; then
  log "refreshing LaunchServices/Squirrel input-source registration"
  set +e
  "$REFRESH_REGISTRATION_SCRIPT"
  refresh_status=$?
  set -e
  log "refresh_registration_exit_code=$refresh_status"
fi

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
  while IFS= read -r duplicate_path; do
    [[ -n "$duplicate_path" ]] || continue
    log "matching_squirrel_app_path=$duplicate_path"
  done < <(print_duplicate_paths 2>/dev/null || true)
  log "duplicate_cleanup_hint=scripts/prepare_squirrel_foreground_check.sh --refresh-registration"
  log "duplicate_quarantine_hint=RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1 scripts/refresh_squirrel_input_source_registration.sh"
else
  log "duplicate_squirrel_app_paths=0"
fi

case "$state" in
  ready)
    log "Squirrel is added and selected."
    ;;
  switch)
    log "Squirrel is added but not current; use the macOS input menu to select it."
    ;;
  third-party-missing|preferences-incomplete)
    log "third_party_allow_list_missing=1"
    log "command_line_repair_hint=scripts/enable_squirrel_hitoolbox_input_source.sh"
    log "command_line_repair_report_hint=scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json"
    log "manual_add_hint=scripts/open_squirrel_input_source_settings.sh --wait"
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
