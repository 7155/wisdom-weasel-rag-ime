#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${RAG_IME_MACOS_APP:-$ROOT/build/RagImeMac.app}"
BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
INPUT_SOURCE_ID="${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac}"
SIDECAR_BASE_URL="http://${RAG_IME_SIDECAR_HOST:-127.0.0.1}:${RAG_IME_SIDECAR_PORT:-8766}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
REQUIRE_INSTALLED="${RAG_IME_DOCTOR_REQUIRE_INSTALLED:-0}"
REQUIRE_INPUT_SOURCE="${RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE:-0}"
REQUIRE_SELECTED_INPUT_SOURCE="${RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE:-0}"
REQUIRE_SIDECAR="${RAG_IME_DOCTOR_REQUIRE_SIDECAR:-0}"
LATENCY_BUDGET_MS="${RAG_IME_DOCTOR_LATENCY_BUDGET_MS:-650}"

failures=0
warnings=0

bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

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
  if bool_true "$required"; then
    fail "$message"
  else
    warn "$message"
  fi
}

plist_value() {
  local key="$1"
  local plist="$2"
  plutil -extract "$key" raw -o - "$plist" 2>/dev/null || true
}

printf 'RAG-IME native macOS frontend doctor\n'
printf 'repo: %s\n' "$ROOT"
printf 'app: %s\n' "$APP"
printf 'input_source: %s\n' "$INPUT_SOURCE_ID"
printf 'sidecar: %s\n' "$SIDECAR_BASE_URL"
printf 'doctor_latency_budget_ms: %s\n\n' "$LATENCY_BUDGET_MS"

if [[ ! -d "$APP" && "$APP" == "$ROOT/build/RagImeMac.app" ]]; then
  if "$ROOT/scripts/build_macos_frontend.sh" >/dev/null; then
    ok "built native RagImeMac.app"
  else
    fail "failed to build native RagImeMac.app"
  fi
fi

if [[ -d "$APP" ]]; then
  ok "native app bundle exists: $APP"
else
  require_or_warn "$REQUIRE_INSTALLED" "native app bundle missing: $APP"
fi

INFO_PLIST="$APP/Contents/Info.plist"
EXECUTABLE="$APP/Contents/MacOS/RagImeMac"
if [[ -f "$INFO_PLIST" ]]; then
  bundle_id="$(plist_value CFBundleIdentifier "$INFO_PLIST")"
  package_type="$(plist_value CFBundlePackageType "$INFO_PLIST")"
  controller="$(plist_value InputMethodServerControllerClass "$INFO_PLIST")"
  connection="$(plist_value InputMethodConnectionName "$INFO_PLIST")"
  if [[ "$bundle_id" == "$BUNDLE_ID" ]]; then
    ok "bundle id: $bundle_id"
  else
    fail "unexpected bundle id: ${bundle_id:-<missing>}"
  fi
  if [[ "$package_type" == "APPL" && "$controller" == "RagInputController" && -n "$connection" ]]; then
    ok "InputMethodKit plist keys present"
  else
    fail "InputMethodKit plist keys incomplete: packageType=${package_type:-<missing>} controller=${controller:-<missing>} connection=${connection:-<missing>}"
  fi
else
  require_or_warn "$REQUIRE_INSTALLED" "Info.plist missing: $INFO_PLIST"
fi

if [[ -x "$EXECUTABLE" ]]; then
  ok "native executable exists"
else
  require_or_warn "$REQUIRE_INSTALLED" "native executable missing: $EXECUTABLE"
fi

if [[ -x "$EXECUTABLE" ]]; then
  if "$EXECUTABLE" --print-config >/tmp/rag-ime-native-print-config.json 2>/tmp/rag-ime-native-print-config.err; then
    if "$PYTHON_EXECUTABLE" - /tmp/rag-ime-native-print-config.json <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
missing = [key for key in ("repoRoot", "dbPath", "pythonExecutable", "project") if not payload.get(key)]
if missing:
    print("missing " + ",".join(missing))
    raise SystemExit(1)
print(payload.get("project"))
PY
    then
      ok "bridge config is readable"
    else
      fail "bridge config is incomplete: $(cat /tmp/rag-ime-native-print-config.err 2>/dev/null || true)"
    fi
  else
    fail "RagImeMac --print-config failed: $(cat /tmp/rag-ime-native-print-config.err 2>/dev/null || true)"
  fi

  if "$EXECUTABLE" --preview-rime-sidecar-json >/tmp/rag-ime-native-sidecar-preview.json 2>/tmp/rag-ime-native-sidecar-preview.err; then
    if "$PYTHON_EXECUTABLE" - /tmp/rag-ime-native-sidecar-preview.json <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
display = payload.get("displayCandidates")
prediction = payload.get("predictionFirst") if isinstance(payload.get("predictionFirst"), dict) else {}
if payload.get("schemaVersion") != "rag-ime.rime-sidecar.v1":
    print("bad schema")
    raise SystemExit(1)
if not isinstance(display, list):
    print("displayCandidates missing")
    raise SystemExit(1)
print(f"display={len(display)} mode={prediction.get('mode', '')}")
PY
    then
      ok "native bridge decodes rime-sidecar preview"
    else
      fail "native bridge preview payload is invalid"
    fi
  else
    require_or_warn "$REQUIRE_SIDECAR" "native bridge rime-sidecar preview failed: $(cat /tmp/rag-ime-native-sidecar-preview.err 2>/dev/null || true)"
  fi
fi

set +e
"$PYTHON_EXECUTABLE" - "$SIDECAR_BASE_URL" "$LATENCY_BUDGET_MS" >/tmp/rag-ime-native-sidecar-http.json 2>/tmp/rag-ime-native-sidecar-http.err <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
latency_budget_ms = int(sys.argv[2])

def get_json(path):
    with urllib.request.urlopen(f"{base}{path}", timeout=2.5) as response:
        return json.loads(response.read().decode("utf-8"))

def post_json(path, payload):
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=4.0) as response:
        return json.loads(response.read().decode("utf-8"))

health = get_json("/health")
suggest = post_json(
    "/rime-suggest",
    {
        "sessionId": "native-doctor",
        "requestSeq": 1,
        "rawInput": "",
        "preedit": "",
        "commitTextPreview": "我想",
        "idleMs": 80,
        "committedContext": "用户正在验证 native RagImeMac Prediction-first RAG 输入法，需要 LLM RAG 记忆候选",
        "maxVisibleCandidates": 8,
        "maxSideCandidates": 8,
        "latencyBudgetMs": latency_budget_ms,
        "forceSideCandidates": True,
        "rimeContext": {"candidates": []},
    },
)
raw_guard = post_json(
    "/rime-suggest",
    {
        "sessionId": "native-doctor-raw",
        "requestSeq": 2,
        "rawInput": "git status",
        "preedit": "git status",
        "committedContext": "正在验证 native 输入法英文命令保护",
        "maxVisibleCandidates": 6,
        "maxSideCandidates": 6,
        "latencyBudgetMs": latency_budget_ms,
        "forceSideCandidates": True,
        "rimeContext": {"candidates": []},
    },
)
display = suggest.get("displayCandidates")
if not isinstance(display, list):
    display = []
sources = [str(item.get("sourceType") or "") for item in display if isinstance(item, dict)]
raw_display = raw_guard.get("displayCandidates")
raw_first = raw_display[0] if isinstance(raw_display, list) and raw_display and isinstance(raw_display[0], dict) else {}
errors = []
if health.get("ok") is not True:
    errors.append("health not ok")
if not any(source in {"model", "rag", "memory"} for source in sources):
    errors.append("no model/rag/memory side candidates")
if raw_first.get("sourceType") != "raw_english" or raw_first.get("insertText") != "git status":
    errors.append("raw command is not protected as first candidate")
print(json.dumps({
    "ok": not errors,
    "errors": errors,
    "eventCount": health.get("eventCount"),
    "sources": sources,
    "displayCount": len(display),
    "rawFirst": raw_first.get("sourceType"),
}, ensure_ascii=False))
raise SystemExit(0 if not errors else 1)
PY
sidecar_status=$?
set -e
if [[ "$sidecar_status" == "0" ]]; then
  ok "HTTP sidecar prediction and raw-input guard passed: $(cat /tmp/rag-ime-native-sidecar-http.json)"
else
  require_or_warn "$REQUIRE_SIDECAR" "HTTP sidecar prediction/raw guard failed: $(cat /tmp/rag-ime-native-sidecar-http.err 2>/dev/null || true) $(cat /tmp/rag-ime-native-sidecar-http.json 2>/dev/null || true)"
fi

if bool_true "$REQUIRE_INPUT_SOURCE" || bool_true "$REQUIRE_SELECTED_INPUT_SOURCE"; then
  args=("$INPUT_SOURCE_ID")
  if bool_true "$REQUIRE_SELECTED_INPUT_SOURCE"; then
    args=("--require-selected" "${args[@]}")
  fi
  if RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/check_macos_input_source.sh" "${args[@]}" >/tmp/rag-ime-native-input-source.out 2>/tmp/rag-ime-native-input-source.err; then
    ok "native macOS input source ready: $(cat /tmp/rag-ime-native-input-source.out)"
  else
    require_or_warn "$REQUIRE_INPUT_SOURCE" "native macOS input source not ready: $(cat /tmp/rag-ime-native-input-source.out 2>/dev/null || true) $(cat /tmp/rag-ime-native-input-source.err 2>/dev/null || true)"
  fi
else
  warn "native macOS input source check not required; set RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 for registration gate"
fi

printf '\nsummary: failures=%d warnings=%d\n' "$failures" "$warnings"
if [[ "$failures" -gt 0 ]]; then
  exit 1
fi
