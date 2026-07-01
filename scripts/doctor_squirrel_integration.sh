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
REQUIRE_PREDICTOR="${RAG_IME_DOCTOR_REQUIRE_PREDICTOR:-0}"
REQUIRE_TRYOUT="${RAG_IME_DOCTOR_REQUIRE_TRYOUT:-0}"
CHECK_LAUNCHD="${RAG_IME_DOCTOR_CHECK_LAUNCHD:-1}"
REQUIRE_INPUT_SOURCE_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE:-}"
REQUIRE_INPUT_SOURCE="${REQUIRE_INPUT_SOURCE_CONFIGURED:-0}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
EXPECT_PREDICTOR_PROVIDER="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_PROVIDER:-${RAG_IME_PREDICTOR_PROVIDER:-}}"
EXPECT_PREDICTOR_MODEL="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_MODEL:-${RAG_IME_PREDICTOR_MODEL:-}}"
EXPECT_STREAM_FIRST="${RAG_IME_DOCTOR_EXPECT_STREAM_FIRST:-${RAG_IME_PREDICTOR_STREAM_FIRST:-}}"

failures=0
warnings=0
launchd_loaded=0
sidecar_healthy=0

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

if bool_true "$REQUIRE_TRYOUT"; then
  REQUIRE_SIDECAR=1
  REQUIRE_XCODE=1
  if [[ -z "$REQUIRE_INPUT_SOURCE_CONFIGURED" ]]; then
    REQUIRE_INPUT_SOURCE=1
  fi
fi

printf 'RAG-IME Squirrel integration doctor\n'
printf 'repo: %s\n' "$ROOT"
printf 'squirrel_workdir: %s\n' "$SQUIRREL_WORKDIR"
printf 'sidecar: %s\n' "$SIDECAR_BASE_URL"
printf 'squirrel_app: %s\n' "$SQUIRREL_APP"
printf 'squirrel_input_source: %s\n' "$SQUIRREL_INPUT_SOURCE_ID"
printf 'tryout_readiness: %s\n' "$REQUIRE_TRYOUT"
printf 'active_developer_dir: %s\n' "$(xcode-select -p 2>/dev/null || printf '<none>')"
printf 'DEVELOPER_DIR: %s\n\n' "${DEVELOPER_DIR:-<unset>}"

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
    require_or_warn "$REQUIRE_TRYOUT" "Squirrel workdir is missing RAG-IME Swift files; run scripts/prepare_squirrel_workspace.sh"
  fi
  if [[ -f "$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml" ]]; then
    ok "generated Squirrel config snippet exists"
  else
    require_or_warn "$REQUIRE_TRYOUT" "generated config snippet missing: $SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml"
  fi
  if git -C "$SQUIRREL_WORKDIR" diff --check >/dev/null 2>&1; then
    ok "Squirrel workdir diff passes whitespace check"
  else
    require_or_warn "$REQUIRE_TRYOUT" "Squirrel workdir diff has whitespace issues"
  fi
else
  require_or_warn "$REQUIRE_TRYOUT" "Squirrel workdir not prepared; run scripts/prepare_squirrel_workspace.sh"
fi

if command -v xcodebuild >/dev/null 2>&1 && xcodebuild_version="$(xcodebuild -version 2>/dev/null)"; then
  ok "xcodebuild is available: $(printf '%s' "$xcodebuild_version" | tr '\n' ' ')"
  if bool_true "$REQUIRE_TRYOUT"; then
    if [[ -d "$SQUIRREL_WORKDIR/Squirrel.xcodeproj" || -f "$SQUIRREL_WORKDIR/Squirrel.xcodeproj/project.pbxproj" ]]; then
      if xcodebuild -project "$SQUIRREL_WORKDIR/Squirrel.xcodeproj" -list >/dev/null 2>&1; then
        ok "xcodebuild can inspect patched Squirrel project"
      else
        fail "xcodebuild cannot inspect patched Squirrel project: $SQUIRREL_WORKDIR/Squirrel.xcodeproj"
      fi
    else
      fail "patched Squirrel project missing: $SQUIRREL_WORKDIR/Squirrel.xcodeproj"
    fi
  fi
else
  active_developer_dir="$(xcode-select -p 2>/dev/null || true)"
  if [[ "$active_developer_dir" == *CommandLineTools* ]]; then
    require_or_warn "$REQUIRE_XCODE" "active developer directory is CommandLineTools; install/select full Xcode with scripts/setup_xcode_for_squirrel.sh"
  else
    require_or_warn "$REQUIRE_XCODE" "full Xcode/xcodebuild is not available; run scripts/setup_xcode_for_squirrel.sh"
  fi
fi

if command -v swiftc >/dev/null 2>&1; then
  ok "swiftc is available"
else
  warn "swiftc is not available; sidecar Swift typecheck cannot run"
fi

check_macos_input_source() {
  local app="$1"
  local input_source_id="$2"
  local out
  local status

  if [[ -x "$app/Contents/MacOS/Squirrel" ]]; then
    ok "installed Squirrel.app executable exists: $app"
  else
    require_or_warn "$REQUIRE_INPUT_SOURCE" "installed Squirrel.app executable missing: $app"
    return
  fi

  out="$(mktemp /tmp/rag-ime-tis-input-source.out.XXXXXX)"
  set +e
  "$ROOT/scripts/check_macos_input_source.sh" "$input_source_id" >"$out" 2>&1
  status=$?
  set -e

  if [[ "$status" == "0" ]]; then
    ok "macOS input source enabled: $(cat "$out")"
  elif grep -Fq "id=$input_source_id" "$out"; then
    require_or_warn "$REQUIRE_INPUT_SOURCE" "macOS input source is registered but not enabled/selectable: $(cat "$out")"
  else
    require_or_warn "$REQUIRE_INPUT_SOURCE" "macOS input source is not registered: $(cat "$out")"
  fi
  rm -f "$out"
}

if bool_true "$REQUIRE_INPUT_SOURCE" || [[ -d "$SQUIRREL_APP" ]]; then
  check_macos_input_source "$SQUIRREL_APP" "$SQUIRREL_INPUT_SOURCE_ID"
fi

if bool_true "$CHECK_LAUNCHD"; then
  if launchctl print "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    launchd_loaded=1
    ok "LaunchAgent loaded: $LAUNCH_AGENT_LABEL"
  else
    warn "LaunchAgent not loaded: run scripts/install_sidecar_launch_agent.sh"
  fi
fi

sidecar_out="$(mktemp /tmp/rag-ime-doctor-sidecar.out.XXXXXX)"
sidecar_err="$(mktemp /tmp/rag-ime-doctor-sidecar.err.XXXXXX)"
set +e
"$PYTHON_EXECUTABLE" - "$SIDECAR_BASE_URL" "$EXPECT_PREDICTOR_PROVIDER" "$EXPECT_PREDICTOR_MODEL" "$EXPECT_STREAM_FIRST" >"$sidecar_out" 2>"$sidecar_err" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
expected_provider = sys.argv[2].strip()
expected_model = sys.argv[3].strip()
expected_stream_first = sys.argv[4].strip()

def provider_matches(expected, actual):
    aliases = {
        "ollama": "local-ollama",
        "mlx": "local-mlx",
        "mlx-lm": "local-mlx",
        "mlx-service": "local-mlx",
        "openai": "local-openai-compatible",
        "openai-compatible": "local-openai-compatible",
    }
    normalized = aliases.get(expected.strip().lower(), expected.strip())
    return not normalized or normalized == actual

def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

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
    select_payload = {
        "candidate": {
            "label": "2",
            "text": "doctor side candidate",
            "insertText": "doctor side candidate",
            "sourceType": "model",
            "selectionAction": "commit_side_candidate",
            "sourceIndex": 0,
        },
        "query": "doctor",
        "recentContext": "Squirrel tryout readiness probe",
        "preedit": "doctor",
    }
    select_request = urllib.request.Request(
        f"{base}/rime-select",
        data=json.dumps(select_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(select_request, timeout=2.5) as response:
        selection = json.loads(response.read().decode("utf-8"))
    if (
        health.get("ok")
        and result.get("schemaVersion") == "rag-ime.rime-sidecar.v1"
        and selection.get("schemaVersion") == "rag-ime.rime-selection.v1"
        and selection.get("ok") is not False
    ):
        predictor = health.get("predictor") if isinstance(health.get("predictor"), dict) else {}
        provider_name = str(predictor.get("providerName") or "")
        model = str(predictor.get("model") or "")
        stream_first = bool(predictor.get("streamFirstCandidate"))
        predictor_ok = True
        messages = []
        if expected_provider and not provider_matches(expected_provider, provider_name):
            predictor_ok = False
            messages.append(f"expected provider {expected_provider}, got {provider_name or '<none>'}")
        if expected_model and expected_model != model:
            predictor_ok = False
            messages.append(f"expected model {expected_model}, got {model or '<none>'}")
        if expected_stream_first and truthy(expected_stream_first) != stream_first:
            predictor_ok = False
            messages.append(f"expected streamFirstCandidate={truthy(expected_stream_first)}, got {stream_first}")
        if not messages:
            if predictor.get("configured"):
                messages.append(f"sidecar predictor: {provider_name} {model} streamFirstCandidate={str(stream_first).lower()}")
            else:
                messages.append("sidecar predictor: not configured")
        print(json.dumps({
            "ok": True,
            "eventCount": health.get("eventCount"),
            "displayCandidates": len(result.get("displayCandidates", [])),
            "rimeSelectOk": True,
            "predictorCheck": {
                "ok": predictor_ok,
                "message": "; ".join(messages),
                "providerName": provider_name,
                "model": model,
                "streamFirstCandidate": stream_first,
            },
        }, ensure_ascii=False))
    else:
        raise RuntimeError("sidecar returned unexpected payload")
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PY
sidecar_status=$?
set -e
if [[ "$sidecar_status" == "0" ]]; then
  sidecar_healthy=1
  ok "HTTP sidecar health, rime-suggest, and rime-select passed: $(cat "$sidecar_out")"
  predictor_line="$("$PYTHON_EXECUTABLE" - "$sidecar_out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
check = payload.get("predictorCheck") if isinstance(payload.get("predictorCheck"), dict) else {}
level = "OK" if check.get("ok", True) else "WARN"
message = str(check.get("message") or "sidecar predictor: status unavailable")
print(f"{level}\t{message}")
PY
)"
  predictor_level="${predictor_line%%	*}"
  predictor_message="${predictor_line#*	}"
  if [[ "$predictor_level" == "OK" ]]; then
    ok "$predictor_message"
  else
    require_or_warn "$REQUIRE_PREDICTOR" "$predictor_message"
  fi
else
  require_or_warn "$REQUIRE_SIDECAR" "HTTP sidecar is not healthy at $SIDECAR_BASE_URL; run scripts/install_sidecar_launch_agent.sh"
fi
rm -f "$sidecar_out" "$sidecar_err"

if bool_true "$REQUIRE_TRYOUT"; then
  if [[ "$launchd_loaded" == "1" || "$sidecar_healthy" == "1" ]]; then
    ok "tryout runtime path has launchd or healthy HTTP sidecar"
  else
    fail "tryout runtime path has neither loaded LaunchAgent nor healthy HTTP sidecar"
  fi
fi

printf '\nsummary: failures=%s warnings=%s\n' "$failures" "$warnings"

if [[ "$failures" -gt 0 ]]; then
  exit 1
fi
