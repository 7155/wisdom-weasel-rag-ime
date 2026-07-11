#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LSREGISTER="${RAG_IME_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"
LEGACY_APP_NAMES="${RAG_IME_LEGACY_INPUT_METHOD_APP_NAMES:-RAG-IME.app:RagIme.app}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-clean-input-source-ls.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

if [[ ! -x "$LSREGISTER" ]]; then
  echo "lsregister is not available: $LSREGISTER" >&2
  exit 3
fi

canonical_squirrel=""
if [[ -d "$SQUIRREL_APP" ]]; then
  canonical_squirrel="$(cd "$(dirname "$SQUIRREL_APP")" && pwd -P)/$(basename "$SQUIRREL_APP")"
fi

"$LSREGISTER" -dump >"$tmpdir/lsregister-before.txt" 2>/dev/null || true
/usr/bin/python3 - "$tmpdir/lsregister-before.txt" "$canonical_squirrel" "$LEGACY_APP_NAMES" >"$tmpdir/stale-paths.txt" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

dump_path = Path(sys.argv[1])
canonical_paths = {sys.argv[2]} if sys.argv[2] else set()
legacy_app_names = {item for item in sys.argv[3].split(":") if item}
records: list[dict[str, str]] = []
current: dict[str, str] = {}


def flush() -> None:
    if current:
        records.append(dict(current))
        current.clear()


for raw in dump_path.read_text(encoding="utf-8", errors="replace").splitlines():
    if raw.startswith("-" * 20):
        flush()
        continue
    stripped = raw.strip()
    if stripped.startswith("path:"):
        current["path"] = stripped.split(":", 1)[1].strip().split(" (0x", 1)[0]
    elif stripped.startswith("identifier:"):
        current["identifier"] = stripped.split(":", 1)[1].strip().strip('"')
    elif stripped.startswith("name:"):
        current["name"] = stripped.split(":", 1)[1].strip().strip('"')
flush()

def is_relevant(record: dict[str, str]) -> bool:
    haystack = " ".join(str(value) for value in record.values())
    return any(
        needle in haystack
        for needle in (
            "RAG-IME",
            "RagIme",
            "RagImeMac",
            "Squirrel",
            "im.rag-ime.inputmethod",
            "dev.local.inputmethod.RagImeMac",
            "im.rime.inputmethod.Squirrel",
        )
    )


def is_stale_path(path: str) -> bool:
    if not path or path in canonical_paths:
        return False
    if any(path.endswith("/" + legacy_name) or f"/{legacy_name}/" in path for legacy_name in legacy_app_names):
        return True
    if path.endswith("/Contents/Frameworks/Sparkle.framework/Versions/B/Updater.app"):
        return True
    stale_markers = (
        "/private/var/folders/",
        "/private/tmp/",
        "/tmp/",
        "/Desktop/rag-ime-input-method-",
        "/Desktop/rag-ime-input-method-backups/",
        "/Library/Application Support/RagIme/uninstall-backups/",
        "/Library/Application Support/RAG-IME/Quarantine/",
        ".disabled",
        ".rag-ime-backup-",
        ".rag-ime-removed-",
        ".disabled-rag-ime-",
        ".rag-ime-misinstall-",
    )
    return any(marker in path for marker in stale_markers)


seen: set[str] = set()
for record in records:
    path = record.get("path", "")
    if not is_relevant(record) or not is_stale_path(path) or path in seen:
        continue
    seen.add(path)
    print(path)
PY

count=0
while IFS= read -r stale_path; do
  [[ -n "$stale_path" ]] || continue
  "$LSREGISTER" -u "$stale_path" >/dev/null 2>&1 || true
  count=$((count + 1))
  echo "unregistered stale input-source LS path: $stale_path"
done <"$tmpdir/stale-paths.txt"

"$LSREGISTER" -gc >/dev/null 2>&1 || true
killall cfprefsd >/dev/null 2>&1 || true
killall TextInputMenuAgent >/dev/null 2>&1 || true
killall SystemUIServer >/dev/null 2>&1 || true

echo "stale_registration_count=$count"
if [[ -n "$canonical_squirrel" ]]; then
  RAG_IME_SQUIRREL_APP="$canonical_squirrel" \
    RAG_IME_SQUIRREL_BUNDLE_ID="$BUNDLE_ID" \
    RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$INPUT_SOURCE_ID" \
    "$ROOT/scripts/refresh_squirrel_input_source_registration.sh" || true
else
  "$ROOT/scripts/check_macos_input_source.sh" "$INPUT_SOURCE_ID" || true
fi
