#!/usr/bin/env bash
set -euo pipefail

INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"
PREF_DOMAIN="${RAG_IME_HITOOLBOX_DOMAIN:-com.apple.HIToolbox}"
INPUTSOURCES_DOMAIN="${RAG_IME_INPUTSOURCES_DOMAIN:-com.apple.inputsources}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh}"
REPORT_PATH="${RAG_IME_ENABLE_SQUIRREL_REPAIR_REPORT:-}"
DRY_RUN=0
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --report-path)
      REPORT_PATH="${2:?--report-path requires a value}"
      shift 2
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 64
      ;;
  esac
done
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-hitoolbox.XXXXXX")"

if [[ ! -x /usr/bin/python3 ]]; then
  echo "/usr/bin/python3 is required to update the HIToolbox plist safely" >&2
  exit 3
fi

before="$tmpdir/before.plist"
after="$tmpdir/after.plist"
inputs_before="$tmpdir/inputs-before.plist"
inputs_after="$tmpdir/inputs-after.plist"
backup="$HOME/Desktop/com.apple.HIToolbox.rag-ime-backup.$(date +%Y%m%d-%H%M%S).plist"
inputs_backup="$HOME/Desktop/com.apple.inputsources.rag-ime-backup.$(date +%Y%m%d-%H%M%S).plist"
hitoolbox_changed=""
third_party_changed=""
hitoolbox_backup=""
inputsources_backup=""
hitoolbox_direct_write_denied=0
inputsources_import_failed=0
inputsources_direct_write_denied=0

write_report() {
  local exit_code="${1:-0}"
  [[ -n "$REPORT_PATH" ]] || return 0
  /usr/bin/python3 - "$REPORT_PATH" "$exit_code" "$DRY_RUN" "$INPUT_SOURCE_ID" "$BUNDLE_ID" \
    "$PREF_DOMAIN" "$INPUTSOURCES_DOMAIN" "$hitoolbox_changed" "$third_party_changed" \
    "$hitoolbox_backup" "$inputsources_backup" "$hitoolbox_direct_write_denied" \
    "$inputsources_import_failed" "$inputsources_direct_write_denied" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

(
    report_path,
    exit_code,
    dry_run,
    input_source_id,
    bundle_id,
    hitoolbox_domain,
    inputsources_domain,
    hitoolbox_changed,
    third_party_changed,
    hitoolbox_backup,
    inputsources_backup,
    hitoolbox_direct_write_denied,
    inputsources_import_failed,
    inputsources_direct_write_denied,
) = sys.argv[1:15]

denied = []
if hitoolbox_direct_write_denied == "1":
    denied.append(hitoolbox_domain)
if inputsources_import_failed == "1" or inputsources_direct_write_denied == "1":
    denied.append(inputsources_domain)

needs_manual_add = inputsources_import_failed == "1" or inputsources_direct_write_denied == "1"
payload = {
    "schemaVersion": "rag-ime.squirrel-hitoolbox-repair.v1",
    "exitCode": int(exit_code or 0),
    "ok": int(exit_code or 0) == 0,
    "dryRun": dry_run == "1",
    "inputSourceId": input_source_id,
    "bundleId": bundle_id,
    "hitoolboxChanged": hitoolbox_changed == "true",
    "thirdPartyChanged": third_party_changed == "true",
    "backups": [item for item in [hitoolbox_backup, inputsources_backup] if item],
    "deniedPreferenceDomains": list(dict.fromkeys(denied)),
    "inputsourcesImportFailed": inputsources_import_failed == "1",
    "inputsourcesDirectWriteDenied": inputsources_direct_write_denied == "1",
    "hitoolboxDirectWriteDenied": hitoolbox_direct_write_denied == "1",
    "manualRequired": [
        "Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel - Simplified."
    ] if needs_manual_add else [],
    "commands": [
        "scripts/open_squirrel_input_source_settings.sh --wait",
        "scripts/prepare_squirrel_foreground_check.sh --refresh-registration",
    ] if needs_manual_add else [],
}
path = Path(report_path).expanduser()
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

trap 'status=$?; write_report "$status" >/dev/null 2>&1 || true; rm -rf "$tmpdir"; exit "$status"' EXIT

write_plist_directly() {
  local source_path="$1"
  local target_path="$2"
  /usr/bin/python3 - "$source_path" "$target_path" <<'PY'
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
tmp = target.with_name(f".{target.name}.rag-ime-tmp")
shutil.copyfile(source, tmp)
os.chmod(tmp, mode)
try:
    os.replace(tmp, target)
except PermissionError:
    tmp.unlink(missing_ok=True)
    with source.open("rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    os.chmod(target, mode)
PY
}

if ! defaults export "$PREF_DOMAIN" "$before" >/dev/null 2>&1; then
  echo "cannot export $PREF_DOMAIN" >&2
  exit 2
fi

if defaults export "$INPUTSOURCES_DOMAIN" "$inputs_before" >/dev/null 2>&1; then
  inputsources_existed=1
else
  /usr/bin/python3 - "$inputs_before" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "wb") as handle:
    plistlib.dump({}, handle)
PY
  inputsources_existed=0
fi

hitoolbox_change_output="$(/usr/bin/python3 - "$before" "$after" "$BUNDLE_ID" "$INPUT_SOURCE_ID" <<'PY'
import plistlib
import sys

before_path, after_path, bundle_id, input_mode = sys.argv[1:5]
with open(before_path, "rb") as handle:
    payload = plistlib.load(handle)

enabled = payload.setdefault("AppleEnabledInputSources", [])
if not isinstance(enabled, list):
    raise SystemExit("AppleEnabledInputSources is not an array")

# Third-party input methods belong in com.apple.inputsources only. Keeping the
# same mode in HIToolbox makes recent macOS releases enumerate duplicate TIS
# records with identical names.
normalized = [
    entry
    for entry in enabled
    if not (
        isinstance(entry, dict)
        and (entry.get("Bundle ID") == bundle_id or entry.get("Input Mode") == input_mode)
    )
]
changed = normalized != enabled
payload["AppleEnabledInputSources"] = normalized

with open(after_path, "wb") as handle:
    plistlib.dump(payload, handle)

print("changed=true" if changed else "changed=false")
PY
)"
echo "$hitoolbox_change_output"
if [[ "$hitoolbox_change_output" == *"changed=true"* ]]; then
  hitoolbox_changed=true
else
  hitoolbox_changed=false
fi

third_party_change_output="$(/usr/bin/python3 - "$inputs_before" "$inputs_after" "$BUNDLE_ID" "$INPUT_SOURCE_ID" <<'PY'
import plistlib
import sys

before_path, after_path, bundle_id, input_mode = sys.argv[1:5]
with open(before_path, "rb") as handle:
    payload = plistlib.load(handle)

enabled = payload.setdefault("AppleEnabledThirdPartyInputSources", [])
if not isinstance(enabled, list):
    raise SystemExit("AppleEnabledThirdPartyInputSources is not an array")

canonical_entries = [
    {
        "Bundle ID": bundle_id,
        "Input Mode": input_mode,
        "InputSourceKind": "Input Mode",
    },
    {
        "Bundle ID": bundle_id,
        "InputSourceKind": "Keyboard Input Method",
    },
]
unrelated = [
    entry
    for entry in enabled
    if not (
        isinstance(entry, dict)
        and (entry.get("Bundle ID") == bundle_id or entry.get("Input Mode") == input_mode)
    )
]
normalized = unrelated + canonical_entries
changed = normalized != enabled
payload["AppleEnabledThirdPartyInputSources"] = normalized

with open(after_path, "wb") as handle:
    plistlib.dump(payload, handle)

print("third_party_changed=true" if changed else "third_party_changed=false")
PY
)"
echo "$third_party_change_output"
if [[ "$third_party_change_output" == *"third_party_changed=true"* ]]; then
  third_party_changed=true
else
  third_party_changed=false
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry-run: would import $PREF_DOMAIN from $after"
  if [[ "$inputsources_existed" == "1" ]]; then
    echo "dry-run: would import $INPUTSOURCES_DOMAIN from $inputs_after"
  else
    echo "dry-run: would create $INPUTSOURCES_DOMAIN with Squirrel third-party entries"
  fi
  echo "dry-run: no preference files imported, no backups written, no input source registered"
  echo "Current strict readiness:"
  RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" || true
  exit 0
fi

if [[ "$hitoolbox_changed" == "false" && "$third_party_changed" == "false" ]]; then
  echo "Squirrel preference records are already normalized; no backup or import needed."
  "$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"
  exit 0
fi

cp "$before" "$backup"
hitoolbox_backup="$backup"
echo "backup: $backup"
if [[ "$inputsources_existed" == "1" ]]; then
  cp "$inputs_before" "$inputs_backup"
  inputsources_backup="$inputs_backup"
  echo "backup: $inputs_backup"
else
  echo "backup: <none; $INPUTSOURCES_DOMAIN did not exist>"
fi

killall cfprefsd >/dev/null 2>&1 || true
defaults import "$PREF_DOMAIN" "$after"
defaults import "$INPUTSOURCES_DOMAIN" "$inputs_after" || {
  inputsources_import_failed=1
  echo "warning: cannot import $INPUTSOURCES_DOMAIN; add Squirrel from System Settings -> Keyboard -> Input Sources" >&2
}
killall cfprefsd >/dev/null 2>&1 || true
sleep 0.5

if ! plutil -extract AppleEnabledInputSources xml1 -o "$tmpdir/hitoolbox-after-import.plist" "$HOME/Library/Preferences/$PREF_DOMAIN.plist" >/dev/null 2>&1 ||
  grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/hitoolbox-after-import.plist" ||
  grep -Fq "<string>$BUNDLE_ID</string>" "$tmpdir/hitoolbox-after-import.plist"; then
  echo "warning: defaults import did not persist $PREF_DOMAIN; writing user plist directly" >&2
  direct_err="$tmpdir/hitoolbox-direct-write.err"
  if write_plist_directly "$after" "$HOME/Library/Preferences/$PREF_DOMAIN.plist" 2>"$direct_err"; then
    killall cfprefsd >/dev/null 2>&1 || true
    sleep 0.5
  else
    hitoolbox_direct_write_denied=1
    echo "warning: macOS denied direct write to $HOME/Library/Preferences/$PREF_DOMAIN.plist" >&2
    sed 's/^/warning: direct write detail: /' "$direct_err" >&2
    echo "warning: add $INPUT_SOURCE_ID from System Settings -> Keyboard -> Input Sources -> Add." >&2
  fi
fi

if ! plutil -extract AppleEnabledThirdPartyInputSources xml1 -o "$tmpdir/third-party-after-import.plist" "$HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" >/dev/null 2>&1 ||
  ! grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/third-party-after-import.plist" ||
  ! grep -Fq "<string>$BUNDLE_ID</string>" "$tmpdir/third-party-after-import.plist"; then
  echo "warning: defaults import did not persist $INPUTSOURCES_DOMAIN; writing user plist directly" >&2
  direct_err="$tmpdir/third-party-direct-write.err"
  if write_plist_directly "$inputs_after" "$HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" 2>"$direct_err"; then
    killall cfprefsd >/dev/null 2>&1 || true
    sleep 0.5
  else
    inputsources_direct_write_denied=1
    echo "warning: macOS denied direct write to $HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" >&2
    sed 's/^/warning: direct write detail: /' "$direct_err" >&2
    echo "warning: add $INPUT_SOURCE_ID from System Settings -> Keyboard -> Input Sources -> Add." >&2
  fi
fi

echo "If thirdPartyEnabled=false below, use System Settings -> Keyboard -> Input Sources -> Add and choose this input source: $INPUT_SOURCE_ID."
"$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"
