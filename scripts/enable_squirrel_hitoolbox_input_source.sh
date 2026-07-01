#!/usr/bin/env bash
set -euo pipefail

INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"
PREF_DOMAIN="${RAG_IME_HITOOLBOX_DOMAIN:-com.apple.HIToolbox}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-/Library/Input Methods/Squirrel.app}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-hitoolbox.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

if [[ ! -x /usr/bin/python3 ]]; then
  echo "/usr/bin/python3 is required to update the HIToolbox plist safely" >&2
  exit 3
fi

before="$tmpdir/before.plist"
after="$tmpdir/after.plist"
backup="$HOME/Desktop/com.apple.HIToolbox.rag-ime-backup.$(date +%Y%m%d-%H%M%S).plist"

if ! defaults export "$PREF_DOMAIN" "$before" >/dev/null 2>&1; then
  echo "cannot export $PREF_DOMAIN" >&2
  exit 2
fi
cp "$before" "$backup"
echo "backup: $backup"

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

defaults import "$PREF_DOMAIN" "$after"
killall cfprefsd >/dev/null 2>&1 || true
sleep 0.5

if [[ -x "$SQUIRREL_APP/Contents/MacOS/Squirrel" ]]; then
  "$SQUIRREL_APP/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
  sleep 0.5
fi

"$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" --require-hitoolbox-enabled "$INPUT_SOURCE_ID"
