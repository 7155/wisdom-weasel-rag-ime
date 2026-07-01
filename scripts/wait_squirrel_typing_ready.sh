#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
SIDECAR_URL="${RAG_IME_SIDECAR_URL:-http://127.0.0.1:8766}"
TIMEOUT_SECONDS="${RAG_IME_TYPING_READY_TIMEOUT_SECONDS:-60}"
POLL_SECONDS="${RAG_IME_TYPING_READY_POLL_SECONDS:-1}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"

if ! added_output="$("$CHECK_INPUT_SOURCE_SCRIPT" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
  echo "Squirrel is not fully added to the current user's macOS input-source lists." >&2
  echo "$added_output" >&2
  echo "Use System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel." >&2
  echo "Then run scripts/wait_squirrel_input_source_added.sh before switching input sources." >&2
  exit 2
fi

deadline=$((SECONDS + TIMEOUT_SECONDS))

echo "Waiting for selected input source: $INPUT_SOURCE_ID"
echo "Use the macOS input menu to switch to Squirrel - Simplified."

last_output=""
while [[ "$SECONDS" -le "$deadline" ]]; do
  if last_output="$("$CHECK_INPUT_SOURCE_SCRIPT" --require-selected "$INPUT_SOURCE_ID" 2>&1)"; then
    echo "input-source: $last_output"
    break
  fi
  sleep "$POLL_SECONDS"
done

if [[ "$SECONDS" -gt "$deadline" ]]; then
  echo "input source was not selected before timeout: $INPUT_SOURCE_ID" >&2
  if [[ -n "$last_output" ]]; then
    echo "$last_output" >&2
  fi
  exit 1
fi

"$PYTHON_EXECUTABLE" - "$SIDECAR_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(f"{base}/health", timeout=2.0) as response:
    health = json.loads(response.read().decode("utf-8"))
if not health.get("ok"):
    raise SystemExit("sidecar health is not ok")
predictor = health.get("predictor") if isinstance(health.get("predictor"), dict) else {}
print(
    "sidecar: ok "
    f"events={health.get('eventCount')} "
    f"predictor={predictor.get('providerName') or '<none>'} "
    f"model={predictor.get('model') or '<none>'} "
    f"streamFirst={str(bool(predictor.get('streamFirstCandidate'))).lower()}"
)
PY

echo "Ready: type in a normal macOS text field and verify the Squirrel candidate panel."
