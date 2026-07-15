#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANONICAL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
DUPLICATE_APP="${RAG_IME_SQUIRREL_SYSTEM_APP:-/Library/Input Methods/Squirrel.app}"
STAMP="$(date '+%Y%m%d-%H%M%S')"
QUARANTINE_APP="${RAG_IME_SQUIRREL_QUARANTINE_APP:-$DUPLICATE_APP.rag-ime-quarantine-$STAMP}"
LSREGISTER="${RAG_IME_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
PREFLIGHT=0

if [[ "${1:-}" == "--preflight" || "${1:-}" == "--dry-run" ]]; then
  PREFLIGHT=1
elif [[ -n "${1:-}" ]]; then
  echo "usage: scripts/quarantine_duplicate_squirrel_app.sh [--preflight]" >&2
  exit 2
fi

bundle_id() {
  plutil -extract CFBundleIdentifier raw -o - "$1/Contents/Info.plist" 2>/dev/null || true
}

has_current_patch() {
  local executable="$1/Contents/MacOS/Squirrel"
  local marker
  local marker_text
  [[ -x "$executable" ]] || return 1
  marker_text="$(strings "$executable" 2>/dev/null || true)"
  for marker in \
    "rag-ime.foreground-trace.v2" \
    "composition_ai_suppressed" \
    "foreground_context_capture_resolved"; do
    grep -Fq -- "$marker" <<< "$marker_text" || return 1
  done
}

if [[ ! -d "$CANONICAL_APP" ]]; then
  echo "canonical Squirrel.app missing: $CANONICAL_APP" >&2
  exit 1
fi
if ! has_current_patch "$CANONICAL_APP"; then
  echo "canonical Squirrel.app is not the current patched build: $CANONICAL_APP" >&2
  exit 1
fi

duplicate_exists=false
same_bundle_id=false
if [[ -d "$DUPLICATE_APP" ]]; then
  duplicate_exists=true
  if [[ "$(bundle_id "$DUPLICATE_APP")" == "$(bundle_id "$CANONICAL_APP")" ]]; then
    same_bundle_id=true
  fi
fi

if [[ "$PREFLIGHT" == "1" ]]; then
  echo "mode=preflight"
  echo "canonical_app=$CANONICAL_APP"
  echo "canonical_patch=true"
  echo "duplicate_app=$DUPLICATE_APP"
  echo "duplicate_exists=$duplicate_exists"
  echo "same_bundle_id=$same_bundle_id"
  echo "quarantine_app=$QUARANTINE_APP"
  if sudo -n true >/dev/null 2>&1; then
    echo "sudo_cached=true"
  else
    echo "sudo_cached=false"
  fi
  exit 0
fi

if [[ "$duplicate_exists" != "true" ]]; then
  echo "no system duplicate found: $DUPLICATE_APP"
  exec python3 "$ROOT/scripts/audit_canonical_squirrel_bundles.py"
fi
if [[ "$same_bundle_id" != "true" ]]; then
  echo "refusing to quarantine app with a different bundle id: $DUPLICATE_APP" >&2
  exit 1
fi

"$LSREGISTER" -u "$DUPLICATE_APP" >/dev/null 2>&1 || true
sudo mv "$DUPLICATE_APP" "$QUARANTINE_APP"
"$LSREGISTER" -f "$CANONICAL_APP" >/dev/null 2>&1 || true
killall TextInputMenuAgent TextInputSwitcher imklaunchagent >/dev/null 2>&1 || true
RAG_IME_SQUIRREL_APP="$CANONICAL_APP" \
  RAG_IME_SQUIRREL_BUNDLE_ID="${INPUT_SOURCE_ID%.*}" \
  RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$INPUT_SOURCE_ID" \
  "$ROOT/scripts/refresh_squirrel_input_source_registration.sh" || true
"$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID" || true
python3 "$ROOT/scripts/audit_canonical_squirrel_bundles.py"
echo "quarantined duplicate Squirrel.app at: $QUARANTINE_APP"
