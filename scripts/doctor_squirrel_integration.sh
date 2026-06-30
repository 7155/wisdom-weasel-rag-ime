#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
PATCH_FILE="${RAG_IME_SQUIRREL_PATCH:-$ROOT/squirrel-patches/0001-add-rag-ime-sidecar.patch}"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
SIDECAR_HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
SIDECAR_PORT="${RAG_IME_SIDECAR_PORT:-8766}"
SIDECAR_BASE_URL="${RAG_IME_SIDECAR_URL:-http://$SIDECAR_HOST:$SIDECAR_PORT}"
LAUNCH_AGENT_LABEL="${RAG_IME_LAUNCH_AGENT_LABEL:-com.rag-ime.sidecar}"
REQUIRE_SIDECAR="${RAG_IME_DOCTOR_REQUIRE_SIDECAR:-0}"
REQUIRE_XCODE="${RAG_IME_DOCTOR_REQUIRE_XCODE:-0}"
CHECK_LAUNCHD="${RAG_IME_DOCTOR_CHECK_LAUNCHD:-1}"

failures=0
warnings=0

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf '[FAIL] %s\n' "$1"
}

require_or_warn() {
  local required="$1"
  local message="$2"
  if [[ "$required" == "1" || "$required" == "true" || "$required" == "TRUE" ]]; then
    fail "$message"
  else
    warn "$message"
  fi
}

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

printf 'RAG-IME Squirrel integration doctor\n'
printf 'repo: %s\n' "$ROOT"
printf 'squirrel_workdir: %s\n' "$SQUIRREL_WORKDIR"
printf 'sidecar: %s\n\n' "$SIDECAR_BASE_URL"

if [[ -x "$PYTHON_EXECUTABLE" ]]; then
  ok "python executable: $PYTHON_EXECUTABLE"
else
  fail "python executable not found or not executable: $PYTHON_EXECUTABLE"
fi

if [[ -f "$PATCH_FILE" ]]; then
  ok "Squirrel patch exists: $PATCH_FILE"
else
  fail "Squirrel patch missing: $PATCH_FILE"
fi

if PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_EXECUTABLE" -m rag_ime.cli --help >/dev/null 2>&1; then
  ok "rag_ime.cli imports from this checkout"
else
  fail "cannot run python -m rag_ime.cli; check PYTHONPATH/current checkout"
fi

if [[ -d "$SQUIRREL_WORKDIR/.git" ]]; then
  ok "Squirrel workdir is a git checkout"
  if [[ -f "$SQUIRREL_WORKDIR/sources/RagImeSidecarClient.swift" && -f "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift" ]]; then
    ok "Squirrel workdir contains RAG-IME sidecar Swift files"
  else
    warn "Squirrel workdir is missing RAG-IME Swift files; run scripts/prepare_squirrel_workspace.sh"
  fi
  if [[ -f "$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml" ]]; then
    ok "generated Squirrel config snippet exists"
  else
    warn "generated config snippet missing: $SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml"
  fi
  if git -C "$SQUIRREL_WORKDIR" diff --check >/dev/null 2>&1; then
    ok "Squirrel workdir diff passes whitespace check"
  else
    warn "Squirrel workdir diff has whitespace issues"
  fi
else
  warn "Squirrel workdir not prepared; run scripts/prepare_squirrel_workspace.sh"
fi

if command -v xcodebuild >/dev/null 2>&1 && xcodebuild -version >/dev/null 2>&1; then
  ok "xcodebuild is available"
else
  require_or_warn "$REQUIRE_XCODE" "full Xcode/xcodebuild is not available; Squirrel build cannot be verified here"
fi

if command -v swiftc >/dev/null 2>&1; then
  ok "swiftc is available"
else
  warn "swiftc is not available; sidecar Swift typecheck cannot run"
fi

if bool_true "$CHECK_LAUNCHD"; then
  if launchctl print "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    ok "LaunchAgent loaded: $LAUNCH_AGENT_LABEL"
  else
    warn "LaunchAgent not loaded: run scripts/install_sidecar_launch_agent.sh"
  fi
fi

sidecar_out="$(mktemp /tmp/rag-ime-doctor-sidecar.out.XXXXXX)"
sidecar_err="$(mktemp /tmp/rag-ime-doctor-sidecar.err.XXXXXX)"
set +e
"$PYTHON_EXECUTABLE" - "$SIDECAR_BASE_URL" >"$sidecar_out" 2>"$sidecar_err" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
try:
    with urllib.request.urlopen(f"{base}/health", timeout=1.5) as response:
        health = json.loads(response.read().decode("utf-8"))
    payload = {
        "sessionId": "doctor",
        "requestSeq": 1,
        "maxVisibleCandidates": 3,
        "maxSideCandidates": 1,
        "rimeContext": {"candidates": [{"label": "1", "text": "本地记忆", "comment": "rime"}]},
    }
    request = urllib.request.Request(
        f"{base}/rime-suggest",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2.5) as response:
        result = json.loads(response.read().decode("utf-8"))
    if health.get("ok") and result.get("schemaVersion") == "rag-ime.rime-sidecar.v1":
        print(json.dumps({"ok": True, "eventCount": health.get("eventCount"), "displayCandidates": len(result.get("displayCandidates", []))}, ensure_ascii=False))
    else:
        raise RuntimeError("sidecar returned unexpected payload")
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PY
sidecar_status=$?
set -e
if [[ "$sidecar_status" == "0" ]]; then
  ok "HTTP sidecar health and rime-suggest passed: $(cat "$sidecar_out")"
else
  require_or_warn "$REQUIRE_SIDECAR" "HTTP sidecar is not healthy at $SIDECAR_BASE_URL; run scripts/install_sidecar_launch_agent.sh"
fi
rm -f "$sidecar_out" "$sidecar_err"

printf '\nsummary: failures=%s warnings=%s\n' "$failures" "$warnings"

if [[ "$failures" -gt 0 ]]; then
  exit 1
fi
