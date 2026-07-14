#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/rag-ime-agent-activity.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
OUTPUT="${1:-/tmp/rag-ime-agent-activity.png}"

sources=()
while IFS= read -r file; do
  sources+=("$file")
done < <(
  find "$ROOT/macos/Shared" "$ROOT/macos/RagImeControl" \
    -type f -name '*.swift' ! -name 'RagImeControlApp.swift' | sort
)

xcrun swiftc \
  -O \
  -parse-as-library \
  -module-cache-path "$TMP_ROOT/module-cache" \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework AVFoundation \
  -framework ImageIO \
  -framework QuickLookUI \
  -framework Security \
  -framework SwiftUI \
  "${sources[@]}" \
  "$ROOT/tests/swift/AgentActivityPanelSnapshot.swift" \
  -o "$TMP_ROOT/agent-activity-snapshot"

"$TMP_ROOT/agent-activity-snapshot" "$OUTPUT"
echo "$OUTPUT"
