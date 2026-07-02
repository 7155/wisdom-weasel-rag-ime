#!/usr/bin/env bash
set -euo pipefail

INPUT_SOURCE_ID="${1:-${RAG_IME_MACOS_INPUT_SOURCE_ID:-${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}}}"
MODULE_CACHE="${RAG_IME_SWIFT_MODULE_CACHE:-${TMPDIR:-/tmp}/rag-ime-swift-module-cache}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-tis-select-input-source.XXXXXX")"
script="$tmpdir/select.swift"
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

swift -module-cache-path "$MODULE_CACHE" "$script" "$INPUT_SOURCE_ID"
"$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" --require-selected "$INPUT_SOURCE_ID"
