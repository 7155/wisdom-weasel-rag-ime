#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LSREGISTER="${RAG_IME_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}"
RAG_IME_APP="${RAG_IME_FRONTEND_APP:-$HOME/Library/Input Methods/RAG-IME.app}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-clean-input-source-ls.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

if [[ ! -x "$LSREGISTER" ]]; then
  echo "lsregister is not available: $LSREGISTER" >&2
  exit 3
fi

canonical_rag_ime=""
canonical_squirrel=""
if [[ -d "$RAG_IME_APP" ]]; then
  canonical_rag_ime="$(cd "$(dirname "$RAG_IME_APP")" && pwd -P)/$(basename "$RAG_IME_APP")"
fi
if [[ -d "$SQUIRREL_APP" ]]; then
  canonical_squirrel="$(cd "$(dirname "$SQUIRREL_APP")" && pwd -P)/$(basename "$SQUIRREL_APP")"
fi

"$LSREGISTER" -dump >"$tmpdir/lsregister-before.txt" 2>/dev/null || true
/usr/bin/python3 - "$tmpdir/lsregister-before.txt" "$canonical_rag_ime" "$canonical_squirrel" >"$tmpdir/stale-paths.txt" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

dump_path = Path(sys.argv[1])
canonical_paths = {item for item in sys.argv[2:4] if item}
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

if [[ -n "$canonical_rag_ime" ]]; then
  "$LSREGISTER" -f -R "$canonical_rag_ime" >/dev/null 2>&1 || true
  echo "registered current RAG-IME app: $canonical_rag_ime"
fi
if [[ -n "$canonical_squirrel" ]]; then
  "$LSREGISTER" -f -R -trusted "$canonical_squirrel" >/dev/null 2>&1 || true
  echo "registered current Squirrel app: $canonical_squirrel"
fi
"$LSREGISTER" -gc >/dev/null 2>&1 || true
killall cfprefsd >/dev/null 2>&1 || true
killall TextInputMenuAgent >/dev/null 2>&1 || true
killall SystemUIServer >/dev/null 2>&1 || true

echo "stale_registration_count=$count"
"$ROOT/scripts/check_macos_input_source.sh" im.rag-ime.inputmethod.RagIme.Hans || true
"$ROOT/scripts/check_macos_input_source.sh" im.rime.inputmethod.Squirrel.Hans || true
