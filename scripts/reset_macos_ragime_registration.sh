#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
INPUT_SOURCE_ID="${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}"
PREF_DOMAIN="${RAG_IME_HITOOLBOX_DOMAIN:-com.apple.HIToolbox}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-reset-registration.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

before="$tmpdir/before.plist"
after="$tmpdir/after.plist"
backup="$HOME/Desktop/com.apple.HIToolbox.rag-ime-reset-backup.$(date +%Y%m%d-%H%M%S).plist"

if ! defaults export "$PREF_DOMAIN" "$before" >/dev/null 2>&1; then
  echo "cannot export $PREF_DOMAIN" >&2
  exit 2
fi
cp "$before" "$backup"

/usr/bin/python3 - "$before" "$after" "$BUNDLE_ID" "$INPUT_SOURCE_ID" <<'PY'
import plistlib
import sys

before_path, after_path, bundle_id, input_mode = sys.argv[1:5]
with open(before_path, "rb") as handle:
    payload = plistlib.load(handle)

def keep(entry):
    if not isinstance(entry, dict):
        return True
    return entry.get("Bundle ID") != bundle_id and entry.get("Input Mode") != input_mode

for key in ("AppleEnabledInputSources", "AppleSelectedInputSources", "AppleInputSourceHistory"):
    value = payload.get(key)
    if isinstance(value, list):
        payload[key] = [entry for entry in value if keep(entry)]

with open(after_path, "wb") as handle:
    plistlib.dump(payload, handle)
PY

killall cfprefsd >/dev/null 2>&1 || true
defaults import "$PREF_DOMAIN" "$after"
killall cfprefsd >/dev/null 2>&1 || true
killall TextInputMenuAgent >/dev/null 2>&1 || true
killall SystemUIServer >/dev/null 2>&1 || true
sleep 0.5

echo "backup: $backup"
"$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" "$INPUT_SOURCE_ID" || true
