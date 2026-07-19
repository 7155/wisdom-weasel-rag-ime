#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"
CHECK_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
PREFERENCE_REPAIR_SCRIPT="${RAG_IME_ENABLE_SQUIRREL_SCRIPT:-$ROOT/scripts/enable_squirrel_hitoolbox_input_source.sh}"
SELECT_AFTER_REFRESH="${RAG_IME_SQUIRREL_AUTO_SELECT:-0}"
QUARANTINE_STALE_APPS="${RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS:-0}"
QUARANTINE_ROOT="${RAG_IME_STALE_SQUIRREL_QUARANTINE_DIR:-$HOME/Library/Application Support/RagIme/disabled-input-method-backups}"
FORCE_DAEMON_REFRESH="${RAG_IME_SQUIRREL_FORCE_DAEMON_REFRESH:-0}"
BUNDLE_REPLACED="${RAG_IME_SQUIRREL_BUNDLE_REPLACED:-0}"
LSREGISTER="${RAG_IME_LSREGISTER:-/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister}"
KILLALL="${RAG_IME_KILLALL:-/usr/bin/killall}"
REFRESH_SLEEP_SECONDS="${RAG_IME_INPUT_SOURCE_REFRESH_SLEEP_SECONDS:-1}"
services_restarted=0
imklaunchagent_restarted=0
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-squirrel-input-source-refresh.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

run_check() {
  set +e
  check_output="$(RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$CHECK_SCRIPT" "$INPUT_SOURCE_ID" 2>&1)"
  check_status=$?
  set -e
}

restart_input_services() {
  local include_preferences="${1:-0}"
  local services=(TextInputMenuAgent TextInputSwitcher imklaunchagent)
  if [[ "$services_restarted" == "1" ]]; then
    echo "macOS input services were already restarted once; refusing a second disruptive restart" >&2
    return 0
  fi
  if bool_true "$include_preferences"; then
    services=(cfprefsd "${services[@]}")
  fi
  "$KILLALL" "${services[@]}" >/dev/null 2>&1 || true
  services_restarted=1
  sleep "$REFRESH_SLEEP_SECONDS"
}

restart_imklaunchagent_after_bundle_replacement() {
  if [[ "$imklaunchagent_restarted" == "1" ]]; then
    echo "imklaunchagent was already restarted once for this bundle replacement" >&2
    return 0
  fi
  "$KILLALL" imklaunchagent >/dev/null 2>&1 || true
  imklaunchagent_restarted=1
  sleep "$REFRESH_SLEEP_SECONDS"
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
timestamp="$(date +%Y%m%d-%H%M%S)"
stale_path_count=0

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
  stale_path_count=$((stale_path_count + 1))
  quarantine_path=""
  archive_stale=false
  if bool_true "$QUARANTINE_STALE_APPS" || [[ "$stale_path" == "$QUARANTINE_ROOT/"* ]]; then
    archive_stale=true
  fi
  "$LSREGISTER" -u "$stale_path" >/dev/null 2>&1 || true
  if [[ "$archive_stale" == true && -d "$stale_path" ]]; then
    mkdir -p "$QUARANTINE_ROOT"
    quarantine_path="$QUARANTINE_ROOT/$(basename "$stale_path").disabled-bundle-$timestamp.zip"
    if /usr/bin/ditto -c -k --keepParent "$stale_path" "$quarantine_path" 2>/dev/null; then
      rm -rf "$stale_path"
      echo "archived stale input method bundle path: $stale_path -> $quarantine_path"
    else
      echo "warning: could not archive stale input method bundle path: $stale_path" >&2
      quarantine_path=""
    fi
  fi
  if [[ -n "$quarantine_path" ]]; then
    "$LSREGISTER" -u "$quarantine_path" >/dev/null 2>&1 || true
  fi
  echo "unregistered stale input method bundle path: $stale_path"
done <"$tmpdir/stale-paths.txt"

if bool_true "$BUNDLE_REPLACED"; then
  # The canonical path is unchanged, but LaunchServices must see the newly
  # signed bundle before IMK rebuilds its bundle-to-connection-name cache.
  "$LSREGISTER" -f -R -trusted "$APP" >/dev/null 2>&1 || true
  echo "refreshed canonical bundle metadata before rebuilding the IMK connection cache"
fi

run_check

if [[ "$check_status" == "0" ]] && bool_true "$BUNDLE_REPLACED"; then
  # The installer has already handed the active source to ABC and stopped the
  # old Squirrel process. Restart only the endpoint broker once: leaving this
  # process alive makes newly focused apps fail with an unrecognized
  # InputMethodConnectionName, while restarting menu/preference agents is
  # unnecessarily disruptive.
  echo "restarting imklaunchagent once after the signed bundle replacement"
  restart_imklaunchagent_after_bundle_replacement
  run_check
fi

if [[ "$check_status" == "0" ]] && ! bool_true "$FORCE_DAEMON_REFRESH"; then
  if [[ "$imklaunchagent_restarted" == "1" ]]; then
    echo "input-source registration healthy with a fresh IMK endpoint broker"
  else
    echo "input-source registration already healthy; left macOS input services running"
  fi
  if bool_true "$SELECT_AFTER_REFRESH"; then
    "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID" >/dev/null 2>&1 || true
  fi
  RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$CHECK_SCRIPT" "$INPUT_SOURCE_ID"
  exit 0
fi

if [[ "$check_status" == "0" ]] && bool_true "$FORCE_DAEMON_REFRESH"; then
  echo "forcing one explicit macOS input-service refresh"
  restart_input_services 0
  run_check
fi

if [[ "$check_status" == "5" ]]; then
  echo "normalizing duplicate third-party input-source preference records"
  "$LSREGISTER" -gc >/dev/null 2>&1 || true
  RAG_IME_SQUIRREL_BUNDLE_ID="$BUNDLE_ID" \
    RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$INPUT_SOURCE_ID" \
    "$PREFERENCE_REPAIR_SCRIPT" >/dev/null
  restart_input_services 1
  run_check
fi

if [[ "$check_status" == "2" ]]; then
  echo "registering missing canonical Squirrel bundle once through LaunchServices"
  "$LSREGISTER" -f -R -trusted "$APP" >/dev/null 2>&1 || true
  restart_input_services 0
  run_check
fi

if [[ "$check_status" != "0" && "$check_status" != "5" ]]; then
  "$APP/Contents/MacOS/Squirrel" --enable-input-source "$INPUT_SOURCE_ID" >/dev/null 2>&1 ||
    "$APP/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 ||
    true
  restart_input_services 1
  run_check
fi

if [[ "$check_status" != "0" ]]; then
  printf '%s\n' "$check_output" >&2
  echo "input-source registration is not unique and ready; no repeated TISRegisterInputSource call was made" >&2
  exit "$check_status"
fi
echo "input-source registration is unique; no repeated TIS registration or daemon restart was used"

if bool_true "$SELECT_AFTER_REFRESH"; then
  "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID" >/dev/null 2>&1 || true
fi

RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$CHECK_SCRIPT" "$INPUT_SOURCE_ID"
