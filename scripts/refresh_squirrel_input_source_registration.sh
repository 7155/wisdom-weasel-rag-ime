#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/RAG-IME.app}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rag-ime.inputmethod.RagIme}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"
CHECK_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
SELECT_AFTER_REFRESH="${RAG_IME_SQUIRREL_AUTO_SELECT:-0}"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-squirrel-input-source-refresh.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ! -d "$APP/Contents" ]]; then
  echo "input method app missing: $APP" >&2
  exit 2
fi

if [[ ! -x "$APP/Contents/MacOS/Squirrel" ]]; then
  echo "Squirrel executable missing: $APP/Contents/MacOS/Squirrel" >&2
  exit 3
fi

if [[ ! -x "$LSREGISTER" ]]; then
  echo "lsregister is not available: $LSREGISTER" >&2
  exit 4
fi

canonical_app="$(cd "$(dirname "$APP")" && pwd -P)/$(basename "$APP")"

"$LSREGISTER" -dump >"$tmpdir/lsregister-before.txt" 2>/dev/null || true
/usr/bin/python3 - "$tmpdir/lsregister-before.txt" "$canonical_app" "$BUNDLE_ID" >"$tmpdir/stale-paths.txt" <<'PY'
from __future__ import annotations

import sys

dump_path, canonical_app, bundle_id = sys.argv[1:4]
records: list[dict[str, str]] = []
current: dict[str, str] = {}


def flush() -> None:
    if current:
        records.append(dict(current))
        current.clear()


with open(dump_path, "r", encoding="utf-8", errors="replace") as handle:
    for raw in handle:
        line = raw.rstrip("\n")
        if line.startswith("-" * 20):
            flush()
            continue
        stripped = line.strip()
        if stripped.startswith("path:"):
            path = stripped.split(":", 1)[1].strip().split(" (0x", 1)[0]
            current["path"] = path
        elif stripped.startswith("identifier:"):
            current["identifier"] = stripped.split(":", 1)[1].strip().strip('"')
flush()

for record in records:
    path = record.get("path", "")
    identifier = record.get("identifier", "")
    if not path or identifier != bundle_id or path == canonical_app:
        continue
    print(path)
PY

while IFS= read -r stale_path; do
  [[ -n "$stale_path" ]] || continue
  "$LSREGISTER" -u "$stale_path" >/dev/null 2>&1 || true
  echo "unregistered stale input method bundle path: $stale_path"
done <"$tmpdir/stale-paths.txt"

"$LSREGISTER" -f -R -trusted "$APP" >/dev/null 2>&1 || true
"$LSREGISTER" -gc >/dev/null 2>&1 || true

"$APP/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
sleep 0.5
"$APP/Contents/MacOS/Squirrel" --enable-input-source "$INPUT_SOURCE_ID" >/dev/null 2>&1 ||
  "$APP/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 ||
  true

killall cfprefsd >/dev/null 2>&1 || true
sleep 0.5

if bool_true "$SELECT_AFTER_REFRESH"; then
  "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID" >/dev/null 2>&1 || true
fi

RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$CHECK_SCRIPT" "$INPUT_SOURCE_ID"
