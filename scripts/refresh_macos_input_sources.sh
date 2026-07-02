#!/usr/bin/env bash
set -euo pipefail

APP="${RAG_IME_MACOS_SYSTEM_APP:-/Library/Input Methods/RagImeMac.app}"
BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-refresh-input-sources.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

if [[ ! -x "$LSREGISTER" ]]; then
  echo "lsregister is not available: $LSREGISTER" >&2
  exit 3
fi

if [[ ! -d "$APP" ]]; then
  echo "system app is missing: $APP" >&2
  exit 2
fi

"$LSREGISTER" -dump >"$tmpdir/lsregister-before.txt" 2>/dev/null || true
/usr/bin/python3 - "$tmpdir/lsregister-before.txt" "$APP" >"$tmpdir/stale-paths.txt" <<'PY'
import sys

dump_path, canonical_app = sys.argv[1:3]
current_path = None

def flush() -> None:
    if not current_path:
        return
    if current_path.endswith("/RagImeMac.app") and current_path != canonical_app:
        print(current_path)

with open(dump_path, "r", encoding="utf-8", errors="replace") as handle:
    for raw in handle:
        line = raw.rstrip("\n")
        if line.startswith("---------------------------------------------------------------------------------"):
            flush()
            current_path = None
            continue
        if line.startswith("path:"):
            current_path = line.split(":", 1)[1].strip().split(" (0x", 1)[0]
flush()
PY

while IFS= read -r stale_path; do
  [[ -n "$stale_path" ]] || continue
  "$LSREGISTER" -u "$stale_path" >/dev/null 2>&1 || true
  echo "unregistered stale LS path: $stale_path"
done <"$tmpdir/stale-paths.txt"

"$LSREGISTER" -f -R "$APP" >/dev/null 2>&1 || true
"$LSREGISTER" -gc >/dev/null 2>&1 || true

killall cfprefsd >/dev/null 2>&1 || true
killall TextInputMenuAgent >/dev/null 2>&1 || true
killall SystemUIServer >/dev/null 2>&1 || true
osascript -e 'tell application "System Settings" to quit' >/dev/null 2>&1 || true
sleep 1

echo "registered system app: $APP"
"$(dirname "${BASH_SOURCE[0]}")/check_macos_input_source.sh" "${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}" || true
