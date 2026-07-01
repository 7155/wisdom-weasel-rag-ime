#!/usr/bin/env bash
set -euo pipefail

INPUT_SOURCE_ID="${1:-${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}}"
MODULE_CACHE="${RAG_IME_SWIFT_MODULE_CACHE:-${TMPDIR:-/tmp}/rag-ime-swift-module-cache}"

if ! command -v swift >/dev/null 2>&1; then
  echo "swift is not available; cannot query macOS input sources" >&2
  exit 3
fi

script="$(mktemp /tmp/rag-ime-tis-input-source.XXXXXX.swift)"
trap 'rm -f "$script"' EXIT
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

let target = CommandLine.arguments[1]
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
  let selected = cfBoolProperty(source, kTISPropertyInputSourceIsSelected)
  print("id=\(id) name=\(name) enabled=\(enabled) selectable=\(selectable) selected=\(selected)")
}
if !matched {
  print("missing \(target)")
  exit(2)
}
SWIFT

out="$(mktemp /tmp/rag-ime-tis-input-source.out.XXXXXX)"
err="$(mktemp /tmp/rag-ime-tis-input-source.err.XXXXXX)"
trap 'rm -f "$script" "$out" "$err"' EXIT

set +e
swift -module-cache-path "$MODULE_CACHE" "$script" "$INPUT_SOURCE_ID" >"$out" 2>"$err"
status=$?
set -e

if [[ "$status" != "0" ]]; then
  cat "$out"
  cat "$err" >&2
  exit "$status"
fi

cat "$out"
if grep -Fq "enabled=true" "$out" && grep -Fq "selectable=true" "$out"; then
  exit 0
fi
exit 2
