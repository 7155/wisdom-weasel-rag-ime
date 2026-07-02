#!/usr/bin/env bash
set -euo pipefail

REQUIRE_SELECTED="${RAG_IME_REQUIRE_SELECTED:-0}"
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_REQUIRE_HITOOLBOX_ENABLED:-0}"
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
    *)
      echo "unknown option: $1" >&2
      exit 64
      ;;
  esac
done
INPUT_SOURCE_ID="${1:-${RAG_IME_MACOS_INPUT_SOURCE_ID:-${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}}}"
if [[ -n "${RAG_IME_INPUT_SOURCE_BUNDLE_ID:-}" ]]; then
  INPUT_SOURCE_BUNDLE_ID="$RAG_IME_INPUT_SOURCE_BUNDLE_ID"
elif [[ "$INPUT_SOURCE_ID" == "${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}" ]]; then
  INPUT_SOURCE_BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
else
  INPUT_SOURCE_BUNDLE_ID="${INPUT_SOURCE_ID%.*}"
fi
MODULE_CACHE="${RAG_IME_SWIFT_MODULE_CACHE:-${TMPDIR:-/tmp}/rag-ime-swift-module-cache}"

if ! command -v swift >/dev/null 2>&1; then
  echo "swift is not available; cannot query macOS input sources" >&2
  exit 3
fi

TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-tis-input-source.XXXXXX")"
script="$tmpdir/query.swift"
out="$tmpdir/out"
err="$tmpdir/err"
trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$MODULE_CACHE"

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
var matched = false
for item in list {
  let source = item as! TISInputSource
  guard let id = cfStringProperty(source, kTISPropertyInputSourceID) else { continue }
  guard id == target else { continue }
  matched = true
  let name = cfStringProperty(source, kTISPropertyLocalizedName) ?? "<unnamed>"
  let enabled = cfBoolProperty(source, kTISPropertyInputSourceIsEnabled)
  let selectable = cfBoolProperty(source, kTISPropertyInputSourceIsSelectCapable)
  let tisSelected = cfBoolProperty(source, kTISPropertyInputSourceIsSelected)
  let currentSelected = currentID == id
  print("id=\(id) name=\(name) enabled=\(enabled) selectable=\(selectable) selected=\(currentSelected) tisSelected=\(tisSelected) current=\(currentID ?? "<none>")")
}
if !matched {
  print("missing \(target)")
  exit(2)
}
SWIFT

set +e
swift -module-cache-path "$MODULE_CACHE" "$script" "$INPUT_SOURCE_ID" >"$out" 2>"$err"
status=$?
set -e

if [[ "$status" != "0" ]]; then
  cat "$out"
  cat "$err" >&2
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
sed "s/$/ hitoolboxEnabled=$hitoolbox_value thirdPartyEnabled=$third_party_value/" "$out"
if [[ "$tis_ok" == "1" ]]; then
  if [[ "$REQUIRE_SELECTED" == "1" || "$REQUIRE_SELECTED" == "true" || "$REQUIRE_SELECTED" == "TRUE" ]]; then
    set +e
    grep -Fq "selected=true" "$out"
    selected_status=$?
    set -e
    if [[ "$selected_status" != "0" ]]; then
      exit "$selected_status"
    fi
  fi
  if [[ "$REQUIRE_HITOOLBOX_ENABLED" == "1" || "$REQUIRE_HITOOLBOX_ENABLED" == "true" || "$REQUIRE_HITOOLBOX_ENABLED" == "TRUE" ]]; then
    [[ "$hitoolbox_ok" == "1" && "$third_party_ok" == "1" ]]
    exit $?
  fi
  exit 0
fi
exit 2
