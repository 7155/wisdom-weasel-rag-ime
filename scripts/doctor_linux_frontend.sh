#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3 || true)}"
SIDECAR_HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
SIDECAR_PORT="${RAG_IME_SIDECAR_PORT:-8766}"
SIDECAR_BASE_URL="${RAG_IME_SIDECAR_URL:-http://$SIDECAR_HOST:$SIDECAR_PORT}"
SERVICE_NAME="${RAG_IME_SYSTEMD_SERVICE_NAME:-rag-ime-sidecar.service}"
REQUIRE_SIDECAR="${RAG_IME_DOCTOR_REQUIRE_SIDECAR:-0}"
REQUIRE_FCITX5="${RAG_IME_DOCTOR_REQUIRE_FCITX5:-0}"
REQUIRE_RIME="${RAG_IME_DOCTOR_REQUIRE_RIME:-0}"
REQUIRE_SYSTEMD="${RAG_IME_DOCTOR_REQUIRE_SYSTEMD:-0}"
REQUIRE_TRYOUT="${RAG_IME_DOCTOR_REQUIRE_TRYOUT:-0}"

failures=0
warnings=0

ok() { printf '[OK] %s\n' "$1"; }
warn() { warnings=$((warnings + 1)); printf '[WARN] %s\n' "$1"; }
fail() { failures=$((failures + 1)); printf '[FAIL] %s\n' "$1"; }

is_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

require_or_warn() {
  local required="$1"
  local message="$2"
  if is_true "$required"; then
    fail "$message"
  else
    warn "$message"
  fi
}

if [[ -n "$PYTHON_EXECUTABLE" && -x "$PYTHON_EXECUTABLE" ]]; then
  if "$PYTHON_EXECUTABLE" -c 'import rag_ime.cli' >/dev/null 2>&1; then
    ok "rag_ime.cli imports with $PYTHON_EXECUTABLE"
  else
    fail "rag_ime.cli import failed with $PYTHON_EXECUTABLE"
  fi
else
  fail "python3 executable not found"
fi

if command -v fcitx5 >/dev/null 2>&1; then
  ok "fcitx5 executable found: $(command -v fcitx5)"
else
  require_or_warn "$REQUIRE_FCITX5" "fcitx5 executable not found"
fi

if command -v fcitx5-remote >/dev/null 2>&1; then
  if fcitx5-remote >/dev/null 2>&1; then
    ok "fcitx5-remote can contact a running Fcitx5 instance"
  else
    require_or_warn "$REQUIRE_FCITX5" "fcitx5-remote exists but cannot contact a running Fcitx5 instance"
  fi
else
  warn "fcitx5-remote not found; cannot check active Fcitx5 runtime"
fi

if command -v rime_deployer >/dev/null 2>&1; then
  ok "rime_deployer found: $(command -v rime_deployer)"
else
  require_or_warn "$REQUIRE_RIME" "rime_deployer not found; install fcitx5-rime/librime tools before frontend validation"
fi

if command -v systemctl >/dev/null 2>&1; then
  if systemctl --user show "$SERVICE_NAME" --property=LoadState --property=ActiveState >/tmp/rag-ime-linux-doctor-systemd.$$ 2>/dev/null; then
    state="$(tr '\n' ' ' </tmp/rag-ime-linux-doctor-systemd.$$)"
    ok "systemd user service visible: $SERVICE_NAME $state"
  else
    require_or_warn "$REQUIRE_SYSTEMD" "systemd user service not visible: $SERVICE_NAME"
  fi
  rm -f /tmp/rag-ime-linux-doctor-systemd.$$
else
  require_or_warn "$REQUIRE_SYSTEMD" "systemctl not found; cannot verify systemd user service"
fi

if [[ -n "$PYTHON_EXECUTABLE" && -x "$PYTHON_EXECUTABLE" ]]; then
  health_output="$(mktemp /tmp/rag-ime-linux-doctor-health.out.XXXXXX)"
  health_error="$(mktemp /tmp/rag-ime-linux-doctor-health.err.XXXXXX)"
  set +e
  "$PYTHON_EXECUTABLE" - <<PY >"$health_output" 2>"$health_error"
import json
import sys
import urllib.request
url = "$SIDECAR_BASE_URL/health"
try:
    with urllib.request.urlopen(url, timeout=1.5) as response:
        payload = json.load(response)
    print(f"server={payload.get('serverName', 'sidecar')} project={payload.get('project', '')}")
except Exception as exc:  # noqa: BLE001 - shell health probe
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
  health_status=$?
  set -e
  if [[ "$health_status" == "0" ]]; then
    health_summary="$(cat "$health_output")"
    ok "sidecar health passed: $SIDECAR_BASE_URL/health $health_summary"
  else
    health_error_text="$(cat "$health_error" 2>/dev/null || true)"
    require_or_warn "$REQUIRE_SIDECAR" "sidecar health failed: $SIDECAR_BASE_URL/health ${health_error_text}"
  fi
  rm -f "$health_output" "$health_error"
fi

if is_true "$REQUIRE_TRYOUT"; then
  "$PYTHON_EXECUTABLE" - <<PY
import json
import sys
import urllib.request
payload = {
    "sessionId": "linux-doctor",
    "requestSeq": 1,
    "rawInput": "ragshurufa",
    "preedit": "ragshurufa",
    "committedContext": "正在验证 Linux Fcitx5 Rime 适配",
    "maxVisibleCandidates": 6,
    "maxSideCandidates": 2,
    "latencyBudgetMs": 500,
    "rimeContext": {
        "candidates": [
            {"label": "1", "text": "RAG 输入法", "comment": "rime"},
            {"label": "2", "text": "RAG 是", "comment": "rime"},
        ],
        "highlightedIndex": 0,
        "page": 0,
        "isLastPage": False,
    },
}
request = urllib.request.Request(
    "$SIDECAR_BASE_URL/rime-suggest",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=3.0) as response:
    result = json.load(response)
items = result.get("displayCandidates") or []
if not items:
    raise SystemExit("no displayCandidates returned")
first = items[0]
if first.get("selectionAction") != "select_rime_candidate":
    raise SystemExit(f"first candidate is not Rime selection: {first}")
print(f"displayCandidates={len(items)} queryBasis={result.get('queryBasis')} firstAction={first.get('selectionAction')}")
PY
  ok "sidecar /rime-suggest contract probe passed"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "doctor failed: failures=$failures warnings=$warnings" >&2
  exit 1
fi

echo "doctor passed: warnings=$warnings"
