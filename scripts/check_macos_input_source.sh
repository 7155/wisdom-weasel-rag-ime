#!/usr/bin/env bash
set -euo pipefail

REQUIRE_SELECTED="${RAG_IME_REQUIRE_SELECTED:-0}"
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_REQUIRE_HITOOLBOX_ENABLED:-0}"
REPORT_PATH="${RAG_IME_CHECK_INPUT_SOURCE_REPORT_PATH:-}"
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --require-selected)
      REQUIRE_SELECTED=1
      shift
      ;;
    --require-hitoolbox-enabled)
      REQUIRE_HITOOLBOX_ENABLED=1
      shift
      ;;
    --report-path)
      REPORT_PATH="${2:?--report-path requires a value}"
      shift 2
      ;;
    --report-path=*)
      REPORT_PATH="${1#--report-path=}"
      shift
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 64
      ;;
  esac
done
INPUT_SOURCE_ID="${1:-${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}}"
INPUT_SOURCE_BUNDLE_ID="${RAG_IME_INPUT_SOURCE_BUNDLE_ID:-${INPUT_SOURCE_ID%.*}}"
MODULE_CACHE="${RAG_IME_SWIFT_MODULE_CACHE:-${TMPDIR:-/tmp}/rag-ime-swift-module-cache}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v swift >/dev/null 2>&1; then
  echo "swift is not available; cannot query macOS input sources" >&2
  exit 3
fi

TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-tis-input-source.XXXXXX")"
script="$tmpdir/query.swift"
out="$tmpdir/out"
err="$tmpdir/err"
annotated_out="$tmpdir/annotated.out"
trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$MODULE_CACHE"

write_report() {
  [[ -n "$REPORT_PATH" ]] || return 0
  local exit_code="$1"
  mkdir -p "$(dirname "$REPORT_PATH")"
  "$PYTHON_BIN" - "$REPORT_PATH" "$INPUT_SOURCE_ID" "$INPUT_SOURCE_BUNDLE_ID" "$exit_code" \
    "$REQUIRE_SELECTED" "$REQUIRE_HITOOLBOX_ENABLED" "$annotated_out" "$out" "$err" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

report_path = Path(sys.argv[1]).expanduser()
target = sys.argv[2]
bundle_id = sys.argv[3]
exit_code = int(sys.argv[4])
require_selected = sys.argv[5] in {"1", "true", "TRUE"}
require_hitoolbox = sys.argv[6] in {"1", "true", "TRUE"}
annotated_path = Path(sys.argv[7])
stdout_path = Path(sys.argv[8])
stderr_path = Path(sys.argv[9])

def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return ""

stdout_text = read(annotated_path) or read(stdout_path)
stderr_text = read(stderr_path)
fields = {}
if stdout_text.startswith("missing "):
    fields["missing"] = stdout_text.removeprefix("missing ").splitlines()[0].strip()
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
    "preferenceEnabled",
    "matchCount",
]:
    match = re.search(rf"(?:^|\s){re.escape(key)}=([^\n]+?)(?=\s+[A-Za-z][A-Za-z0-9]*=|$)", stdout_text)
    if not match:
        continue
    value = match.group(1).strip()
    if key == "matchCount":
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    elif value == "true":
        fields[key] = True
    elif value == "false":
        fields[key] = False
    else:
        fields[key] = value

failure_kind = None
manual_required = []
commands = []
if exit_code == 0:
    failure_kind = None
elif fields.get("missing") == target:
    failure_kind = "input-source-missing"
    manual_required.append("Install/register the patched Squirrel.app before foreground verification.")
    commands.append("scripts/build_patched_squirrel.sh install")
elif exit_code == 5 or (isinstance(fields.get("matchCount"), int) and fields["matchCount"] > 1):
    failure_kind = "duplicate-input-source"
    manual_required.append("Normalize Squirrel preferences and remove stale LaunchServices registrations before selecting it again.")
    commands.append("scripts/enable_squirrel_hitoolbox_input_source.sh")
    commands.append("RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1 scripts/refresh_squirrel_input_source_registration.sh")
elif require_selected and fields.get("selected") is False:
    failure_kind = "not-selected"
    manual_required.append("Select Squirrel - Simplified from the macOS input menu.")
    commands.append("scripts/wait_squirrel_typing_ready.sh")
elif require_hitoolbox and not bundle_id.startswith("com.apple.") and fields.get("thirdPartyEnabled") is False:
    failure_kind = "third-party-missing"
    manual_required.append("Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel - Simplified.")
    commands.append("scripts/open_squirrel_input_source_settings.sh --wait")
    commands.append("scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json")
elif require_hitoolbox and bundle_id.startswith("com.apple.") and fields.get("hitoolboxEnabled") is False:
    failure_kind = "hitoolbox-missing"
    manual_required.append("Repair HIToolbox input-source preferences or add Squirrel in System Settings.")
    commands.append("scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json")
elif fields.get("enabled") is not True or fields.get("selectable") is not True:
    failure_kind = "not-enabled-or-selectable"
else:
    failure_kind = "check-failed"

payload = {
    "schemaVersion": "rag-ime.macos-input-source-check.v1",
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "ok": exit_code == 0,
    "exitCode": exit_code,
    "inputSourceId": target,
    "bundleId": bundle_id,
    "requirements": {
        "selected": require_selected,
        "hitoolboxEnabled": require_hitoolbox,
    },
    "source": fields,
    "failureKind": failure_kind,
    "manualRequired": list(dict.fromkeys(manual_required)),
    "commands": list(dict.fromkeys(commands)),
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

let target = CommandLine.arguments[1]
let currentID = currentInputSourceID()
let list = TISCreateInputSourceList(nil, true).takeRetainedValue() as NSArray
var matchCount = 0
var firstMatch = ""
for item in list {
  let source = item as! TISInputSource
  guard let id = cfStringProperty(source, kTISPropertyInputSourceID) else { continue }
  guard id == target else { continue }
  matchCount += 1
  let name = cfStringProperty(source, kTISPropertyLocalizedName) ?? "<unnamed>"
  let enabled = cfBoolProperty(source, kTISPropertyInputSourceIsEnabled)
  let selectable = cfBoolProperty(source, kTISPropertyInputSourceIsSelectCapable)
  let tisSelected = cfBoolProperty(source, kTISPropertyInputSourceIsSelected)
  let currentSelected = currentID == id
  if firstMatch.isEmpty {
    firstMatch = "id=\(id) name=\(name) enabled=\(enabled) selectable=\(selectable) selected=\(currentSelected) tisSelected=\(tisSelected) current=\(currentID ?? "<none>")"
  }
}
if matchCount == 0 {
  print("missing \(target)")
  exit(2)
}
print("\(firstMatch) matchCount=\(matchCount)")
if matchCount > 1 {
  exit(5)
}
SWIFT

set +e
swift -module-cache-path "$MODULE_CACHE" "$script" "$INPUT_SOURCE_ID" >"$out" 2>"$err"
status=$?
set -e

if [[ "$status" != "0" ]]; then
  cat "$out"
  cat "$err" >&2
  cp "$out" "$annotated_out"
  write_report "$status"
  exit "$status"
fi

tis_ok=0
hitoolbox_ok=0
third_party_ok=1
if grep -Fq "enabled=true" "$out" && grep -Fq "selectable=true" "$out"; then
  tis_ok=1
fi

if plutil -extract AppleEnabledInputSources xml1 -o "$tmpdir/hitoolbox-enabled.plist" "$HOME/Library/Preferences/com.apple.HIToolbox.plist" >/dev/null 2>&1; then
  if grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/hitoolbox-enabled.plist" ||
    grep -Fq "<string>$INPUT_SOURCE_BUNDLE_ID</string>" "$tmpdir/hitoolbox-enabled.plist"; then
    hitoolbox_ok=1
  fi
fi

if [[ "$INPUT_SOURCE_BUNDLE_ID" != com.apple.* ]]; then
  third_party_ok=0
  if plutil -extract AppleEnabledThirdPartyInputSources xml1 -o "$tmpdir/third-party-enabled.plist" "$HOME/Library/Preferences/com.apple.inputsources.plist" >/dev/null 2>&1; then
    if grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/third-party-enabled.plist" ||
      grep -Fq "<string>$INPUT_SOURCE_BUNDLE_ID</string>" "$tmpdir/third-party-enabled.plist"; then
      third_party_ok=1
    fi
  fi
fi

hitoolbox_value=false
if [[ "$hitoolbox_ok" == "1" ]]; then
  hitoolbox_value=true
fi
third_party_value=false
if [[ "$third_party_ok" == "1" ]]; then
  third_party_value=true
fi
preference_ok="$hitoolbox_ok"
if [[ "$INPUT_SOURCE_BUNDLE_ID" != com.apple.* ]]; then
  preference_ok="$third_party_ok"
fi
preference_value=false
if [[ "$preference_ok" == "1" ]]; then
  preference_value=true
fi
sed "s/$/ hitoolboxEnabled=$hitoolbox_value thirdPartyEnabled=$third_party_value preferenceEnabled=$preference_value/" "$out" >"$annotated_out"
cat "$annotated_out"
if [[ "$tis_ok" == "1" ]]; then
  if [[ "$REQUIRE_SELECTED" == "1" || "$REQUIRE_SELECTED" == "true" || "$REQUIRE_SELECTED" == "TRUE" ]]; then
    set +e
    grep -Fq "selected=true" "$out"
    selected_status=$?
    set -e
    if [[ "$selected_status" != "0" ]]; then
      write_report "$selected_status"
      exit "$selected_status"
    fi
  fi
  if [[ "$REQUIRE_HITOOLBOX_ENABLED" == "1" || "$REQUIRE_HITOOLBOX_ENABLED" == "true" || "$REQUIRE_HITOOLBOX_ENABLED" == "TRUE" ]]; then
    set +e
    [[ "$preference_ok" == "1" ]]
    enabled_status=$?
    set -e
    write_report "$enabled_status"
    exit "$enabled_status"
  fi
  write_report 0
  exit 0
fi
write_report 2
exit 2
