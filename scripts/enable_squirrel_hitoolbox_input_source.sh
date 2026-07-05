#!/usr/bin/env bash
set -euo pipefail

INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"
PREF_DOMAIN="${RAG_IME_HITOOLBOX_DOMAIN:-com.apple.HIToolbox}"
INPUTSOURCES_DOMAIN="${RAG_IME_INPUTSOURCES_DOMAIN:-com.apple.inputsources}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-hitoolbox.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

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

if ! defaults export "$PREF_DOMAIN" "$before" >/dev/null 2>&1; then
  echo "cannot export $PREF_DOMAIN" >&2
  exit 2
fi
cp "$before" "$backup"
echo "backup: $backup"

if defaults export "$INPUTSOURCES_DOMAIN" "$inputs_before" >/dev/null 2>&1; then
  cp "$inputs_before" "$inputs_backup"
  echo "backup: $inputs_backup"
else
  /usr/bin/python3 - "$inputs_before" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "wb") as handle:
    plistlib.dump({}, handle)
PY
  echo "backup: <none; $INPUTSOURCES_DOMAIN did not exist>"
fi

/usr/bin/python3 - "$before" "$after" "$BUNDLE_ID" "$INPUT_SOURCE_ID" <<'PY'
import plistlib
import sys

before_path, after_path, bundle_id, input_mode = sys.argv[1:5]
with open(before_path, "rb") as handle:
    payload = plistlib.load(handle)

enabled = payload.setdefault("AppleEnabledInputSources", [])
if not isinstance(enabled, list):
    raise SystemExit("AppleEnabledInputSources is not an array")

def has_mode(entry):
    return isinstance(entry, dict) and entry.get("Input Mode") == input_mode

def has_bundle(entry):
    return (
        isinstance(entry, dict)
        and entry.get("Bundle ID") == bundle_id
        and "Input Mode" not in entry
    )

changed = False
if not any(has_mode(entry) for entry in enabled):
    enabled.append(
        {
            "Bundle ID": bundle_id,
            "Input Mode": input_mode,
            "InputSourceKind": "Input Mode",
        }
    )
    changed = True

if not any(has_bundle(entry) for entry in enabled):
    enabled.append(
        {
            "Bundle ID": bundle_id,
            "InputSourceKind": "Keyboard Input Method",
        }
    )
    changed = True

with open(after_path, "wb") as handle:
    plistlib.dump(payload, handle)

print("changed=true" if changed else "changed=false")
PY

/usr/bin/python3 - "$inputs_before" "$inputs_after" "$BUNDLE_ID" "$INPUT_SOURCE_ID" <<'PY'
import plistlib
import sys

before_path, after_path, bundle_id, input_mode = sys.argv[1:5]
with open(before_path, "rb") as handle:
    payload = plistlib.load(handle)

enabled = payload.setdefault("AppleEnabledThirdPartyInputSources", [])
if not isinstance(enabled, list):
    raise SystemExit("AppleEnabledThirdPartyInputSources is not an array")

def has_mode(entry):
    return isinstance(entry, dict) and entry.get("Input Mode") == input_mode

def has_bundle(entry):
    return (
        isinstance(entry, dict)
        and entry.get("Bundle ID") == bundle_id
        and "Input Mode" not in entry
    )

changed = False
if not any(has_mode(entry) for entry in enabled):
    enabled.append(
        {
            "Bundle ID": bundle_id,
            "Input Mode": input_mode,
            "InputSourceKind": "Input Mode",
        }
    )
    changed = True

if not any(has_bundle(entry) for entry in enabled):
    enabled.append(
        {
            "Bundle ID": bundle_id,
            "InputSourceKind": "Keyboard Input Method",
        }
    )
    changed = True

with open(after_path, "wb") as handle:
    plistlib.dump(payload, handle)

print("third_party_changed=true" if changed else "third_party_changed=false")
PY

killall cfprefsd >/dev/null 2>&1 || true
defaults import "$PREF_DOMAIN" "$after"
defaults import "$INPUTSOURCES_DOMAIN" "$inputs_after" || {
  echo "warning: cannot import $INPUTSOURCES_DOMAIN; add Squirrel from System Settings -> Keyboard -> Input Sources" >&2
}
killall cfprefsd >/dev/null 2>&1 || true
sleep 0.5

if ! plutil -extract AppleEnabledInputSources xml1 -o "$tmpdir/hitoolbox-after-import.plist" "$HOME/Library/Preferences/$PREF_DOMAIN.plist" >/dev/null 2>&1 ||
  ! grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/hitoolbox-after-import.plist" ||
  ! grep -Fq "<string>$BUNDLE_ID</string>" "$tmpdir/hitoolbox-after-import.plist"; then
  echo "warning: defaults import did not persist $PREF_DOMAIN; writing user plist directly" >&2
  if cp "$after" "$HOME/Library/Preferences/$PREF_DOMAIN.plist" 2>/dev/null; then
    killall cfprefsd >/dev/null 2>&1 || true
    sleep 0.5
  else
    echo "warning: macOS denied direct write to $HOME/Library/Preferences/$PREF_DOMAIN.plist" >&2
    echo "warning: add $INPUT_SOURCE_ID from System Settings -> Keyboard -> Input Sources -> Add." >&2
  fi
fi

if ! plutil -extract AppleEnabledThirdPartyInputSources xml1 -o "$tmpdir/third-party-after-import.plist" "$HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" >/dev/null 2>&1 ||
  ! grep -Fq "<string>$INPUT_SOURCE_ID</string>" "$tmpdir/third-party-after-import.plist" ||
  ! grep -Fq "<string>$BUNDLE_ID</string>" "$tmpdir/third-party-after-import.plist"; then
  echo "warning: defaults import did not persist $INPUTSOURCES_DOMAIN; writing user plist directly" >&2
  if cp "$inputs_after" "$HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" 2>/dev/null; then
    killall cfprefsd >/dev/null 2>&1 || true
    sleep 0.5
  else
    echo "warning: macOS denied direct write to $HOME/Library/Preferences/$INPUTSOURCES_DOMAIN.plist" >&2
    echo "warning: add $INPUT_SOURCE_ID from System Settings -> Keyboard -> Input Sources -> Add." >&2
  fi
fi

if [[ -x "$SQUIRREL_APP/Contents/MacOS/Squirrel" ]]; then
  "$SQUIRREL_APP/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
  sleep 0.5
fi

echo "If thirdPartyEnabled=false below, use System Settings -> Keyboard -> Input Sources -> Add and choose this input source: $INPUT_SOURCE_ID."
"$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"
