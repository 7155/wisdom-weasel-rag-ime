#!/usr/bin/env bash
set -euo pipefail

REPORT_PATH="${RAG_IME_SELECT_INPUT_SOURCE_REPORT_PATH:-}"
INPUT_SOURCE_ID=""
while (($#)); do
  case "$1" in
    --report-path)
      REPORT_PATH="${2:?--report-path requires a value}"
      shift 2
      ;;
    --report-path=*)
      REPORT_PATH="${1#--report-path=}"
      shift
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/select_macos_input_source.sh [--report-path PATH] [INPUT_SOURCE_ID]

Selects a macOS Text Input Source with Carbon TIS and verifies that it became
the current input source.

Options:
  --report-path PATH  Write a machine-readable JSON selection attempt report.
  -h, --help          Show this help.
USAGE
      exit 0
      ;;
    --*)
      echo "unknown option: $1" >&2
      exit 64
      ;;
    *)
      if [[ -n "$INPUT_SOURCE_ID" ]]; then
        echo "unexpected extra argument: $1" >&2
        exit 64
      fi
      INPUT_SOURCE_ID="$1"
      shift
      ;;
  esac
done
INPUT_SOURCE_ID="${INPUT_SOURCE_ID:-${RAG_IME_MACOS_INPUT_SOURCE_ID:-${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODULE_CACHE="${RAG_IME_SWIFT_MODULE_CACHE:-${TMPDIR:-/tmp}/rag-ime-swift-module-cache}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-tis-select-input-source.XXXXXX")"
script="$tmpdir/select.swift"
select_out="$tmpdir/select.out"
select_err="$tmpdir/select.err"
check_out="$tmpdir/check.out"
check_err="$tmpdir/check.err"
trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$MODULE_CACHE"

write_report() {
  [[ -n "$REPORT_PATH" ]] || return 0
  local phase="$1"
  local exit_code="$2"
  local select_status="$3"
  local check_status="$4"
  mkdir -p "$(dirname "$REPORT_PATH")"
  "$PYTHON_BIN" - "$REPORT_PATH" "$INPUT_SOURCE_ID" "$phase" "$exit_code" "$select_status" "$check_status" "$select_out" "$select_err" "$check_out" "$check_err" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

report_path = Path(sys.argv[1]).expanduser()
target = sys.argv[2]
phase = sys.argv[3]
exit_code = int(sys.argv[4])
select_status = int(sys.argv[5])
check_status = int(sys.argv[6])
select_out = Path(sys.argv[7])
select_err = Path(sys.argv[8])
check_out = Path(sys.argv[9])
check_err = Path(sys.argv[10])

def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return ""

stdout_text = read(check_out) or read(select_out)
stderr_text = "\n".join(part for part in [read(select_err), read(check_err)] if part)
combined = "\n".join(part for part in [stdout_text, stderr_text] if part)

fields = {}
for key in [
    "id",
    "name",
    "enabled",
    "selectable",
    "selected",
    "tisSelected",
    "current",
    "hitoolboxEnabled",
    "thirdPartyEnabled",
]:
    match = re.search(rf"(?:^|\s){re.escape(key)}=([^\n]+?)(?=\s+[A-Za-z][A-Za-z0-9]*=|$)", stdout_text)
    if not match:
        continue
    value = match.group(1).strip()
    if value == "true":
        fields[key] = True
    elif value == "false":
        fields[key] = False
    else:
        fields[key] = value

tis_select_status = None
match = re.search(r"TISSelectInputSource (?:failed|returned):?\s*(-?\d+)", combined)
if match:
    tis_select_status = int(match.group(1))

failure_kind = None
manual_required = []
commands = []
if exit_code == 0:
    failure_kind = None
elif "missing " in combined and select_status == 2:
    failure_kind = "input-source-missing"
    manual_required.append("Install/register the patched Squirrel input source before selecting it.")
elif "TISEnableInputSource failed" in combined:
    failure_kind = "enable-failed"
elif tis_select_status is not None:
    failure_kind = "tis-select-failed"
elif check_status != 0:
    failure_kind = "selected-check-failed"
else:
    failure_kind = "select-failed"

if tis_select_status == -50:
    manual_required.append("macOS rejected programmatic selection with TISSelectInputSource=-50; add/select Squirrel in System Settings or the input menu.")
if fields.get("thirdPartyEnabled") is False:
    manual_required.append("AppleEnabledThirdPartyInputSources does not include this input source; use System Settings -> Keyboard -> Input Sources -> Add.")
if fields.get("selected") is False:
    manual_required.append("The current input source is still not the requested Squirrel input source.")
if manual_required:
    commands.extend([
        "scripts/open_squirrel_input_source_settings.sh --wait",
        f"scripts/check_macos_input_source.sh --require-selected {target}",
    ])

payload = {
    "schemaVersion": "rag-ime.macos-input-source-selection.v1",
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "ok": exit_code == 0,
    "exitCode": exit_code,
    "phase": phase,
    "inputSourceId": target,
    "selectPhaseExitCode": select_status,
    "checkPhaseExitCode": check_status,
    "tisSelectStatus": tis_select_status,
    "failureKind": failure_kind,
    "source": fields,
    "manualRequired": list(dict.fromkeys(manual_required)),
    "commands": commands,
    "stdoutTail": stdout_text[-2000:],
    "stderrTail": stderr_text[-2000:],
}
report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

cat >"$script" <<'SWIFT'
import Foundation
import Carbon

func cfStringProperty(_ source: TISInputSource, _ key: CFString) -> String? {
  guard let raw = TISGetInputSourceProperty(source, key) else { return nil }
  return Unmanaged<CFString>.fromOpaque(raw).takeUnretainedValue() as String
}

func cfBoolProperty(_ source: TISInputSource, _ key: CFString) -> Bool {
  guard let raw = TISGetInputSourceProperty(source, key) else { return false }
  return CFBooleanGetValue(Unmanaged<CFBoolean>.fromOpaque(raw).takeUnretainedValue())
}

func currentInputSourceID() -> String? {
  guard let raw = TISCopyCurrentKeyboardInputSource() else { return nil }
  let source = raw.takeRetainedValue()
  return cfStringProperty(source, kTISPropertyInputSourceID)
}

func findSource(_ target: String) -> TISInputSource? {
  let list = TISCreateInputSourceList(nil, true).takeRetainedValue() as NSArray
  for item in list {
    let source = item as! TISInputSource
    guard cfStringProperty(source, kTISPropertyInputSourceID) == target else { continue }
    return source
  }
  return nil
}

func printStatus(_ source: TISInputSource) {
  let id = cfStringProperty(source, kTISPropertyInputSourceID) ?? "<missing-id>"
  let name = cfStringProperty(source, kTISPropertyLocalizedName) ?? "<unnamed>"
  let enabled = cfBoolProperty(source, kTISPropertyInputSourceIsEnabled)
  let selectable = cfBoolProperty(source, kTISPropertyInputSourceIsSelectCapable)
  let currentID = currentInputSourceID()
  let tisSelected = cfBoolProperty(source, kTISPropertyInputSourceIsSelected)
  let currentSelected = currentID == id
  print("id=\(id) name=\(name) enabled=\(enabled) selectable=\(selectable) selected=\(currentSelected) tisSelected=\(tisSelected) current=\(currentID ?? "<none>")")
}

let target = CommandLine.arguments[1]
guard let source = findSource(target) else {
  fputs("missing \(target)\n", stderr)
  exit(2)
}

if !cfBoolProperty(source, kTISPropertyInputSourceIsEnabled) {
  let enableStatus = TISEnableInputSource(source)
  guard enableStatus == noErr else {
    fputs("TISEnableInputSource failed: \(enableStatus)\n", stderr)
    exit(3)
  }
}

let selectStatus = TISSelectInputSource(source)
if selectStatus != noErr {
  Thread.sleep(forTimeInterval: 0.25)
  if currentInputSourceID() != target {
    fputs("TISSelectInputSource failed: \(selectStatus)\n", stderr)
    exit(4)
  }
  fputs("TISSelectInputSource returned \(selectStatus), but current source is already \(target)\n", stderr)
}

Thread.sleep(forTimeInterval: 0.25)
if let refreshed = findSource(target) {
  printStatus(refreshed)
} else {
  fputs("selected source disappeared: \(target)\n", stderr)
  exit(5)
}
SWIFT

set +e
swift -module-cache-path "$MODULE_CACHE" "$script" "$INPUT_SOURCE_ID" >"$select_out" 2>"$select_err"
select_status=$?
set -e
cat "$select_out"
cat "$select_err" >&2
if [[ "$select_status" != "0" ]]; then
  set +e
  "$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" "$INPUT_SOURCE_ID" >"$check_out" 2>"$check_err"
  check_status=$?
  set -e
  write_report "select" "$select_status" "$select_status" "$check_status"
  exit "$select_status"
fi

set +e
"$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" --require-selected "$INPUT_SOURCE_ID" >"$check_out" 2>"$check_err"
check_status=$?
set -e
cat "$check_out"
cat "$check_err" >&2
if [[ "$check_status" != "0" ]]; then
  write_report "final-check" "$check_status" "$select_status" "$check_status"
  exit "$check_status"
fi
write_report "final-check" 0 "$select_status" "$check_status"
