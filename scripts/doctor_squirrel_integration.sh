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
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_DOCTOR_REQUIRE_HITOOLBOX_ENABLED:-${RAG_IME_REQUIRE_HITOOLBOX_ENABLED:-0}}"
REQUIRE_MIXED_LAYOUT_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_MIXED_LAYOUT:-}"
REQUIRE_MIXED_LAYOUT="${REQUIRE_MIXED_LAYOUT_CONFIGURED:-0}"
CHECK_LAUNCHD="${RAG_IME_DOCTOR_CHECK_LAUNCHD:-1}"
REQUIRE_INPUT_SOURCE_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE:-}"
REQUIRE_INPUT_SOURCE="${REQUIRE_INPUT_SOURCE_CONFIGURED:-0}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
REFRESH_INPUT_SOURCE="${RAG_IME_DOCTOR_REFRESH_INPUT_SOURCE:-1}"
REQUIRE_PATCHED_APP_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_PATCHED_APP:-}"
REQUIRE_PATCHED_APP="${REQUIRE_PATCHED_APP_CONFIGURED:-0}"
SQUIRREL_DUPLICATE_APP_CANDIDATES="${RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES:-$HOME/Library/Input Methods/Squirrel.app:/Library/Input Methods/Squirrel.app}"
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

info() {
  printf '[INFO] %s\n' "$1"
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

app_bundle_id() {
  local app="$1"
  plutil -extract CFBundleIdentifier raw -o - "$app/Contents/Info.plist" 2>/dev/null || true
}

same_path() {
  local left="$1"
  local right="$2"
  [[ "$(cd "$(dirname "$left")" 2>/dev/null && pwd -P)/$(basename "$left")" == "$(cd "$(dirname "$right")" 2>/dev/null && pwd -P)/$(basename "$right")" ]]
}

squirrel_app_has_mixed_frontend_trace() {
  local app="$1"
  local executable="$app/Contents/MacOS/Squirrel"
  [[ -x "$executable" ]] || return 1
  strings "$executable" 2>/dev/null | grep -Fq "rag-ime.squirrel-frontend-trace.v1" &&
    strings "$executable" 2>/dev/null | grep -Fq "panel_text_layout"
}

check_patched_squirrel_app() {
  local app="$1"
  local required="$2"

  if squirrel_app_has_mixed_frontend_trace "$app"; then
    ok "installed Squirrel.app contains RAG-IME mixed-layout frontend trace"
  else
    require_or_warn "$required" "installed Squirrel.app lacks RAG-IME mixed-layout frontend trace; rebuild/install patched Squirrel: $app"
  fi
}

check_duplicate_squirrel_apps() {
  local configured_app="$1"
  local candidate
  local bundle_id
  local found_stale=0

  IFS=':' read -r -a duplicate_candidates <<< "$SQUIRREL_DUPLICATE_APP_CANDIDATES"
  for candidate in "${duplicate_candidates[@]}"; do
    [[ -n "$candidate" && -d "$candidate" ]] || continue
    if same_path "$candidate" "$configured_app"; then
      continue
    fi
    bundle_id="$(app_bundle_id "$candidate")"
    [[ "$bundle_id" == "im.rime.inputmethod.Squirrel" ]] || continue
    if ! squirrel_app_has_mixed_frontend_trace "$candidate"; then
      found_stale=1
      info "stale Squirrel.app with same bundle id exists outside target app: $candidate"
    fi
  done

  if [[ "$found_stale" == "0" ]]; then
    ok "no stale same-bundle Squirrel.app detected in duplicate app candidates"
  fi
}

if bool_true "$REQUIRE_TRYOUT"; then
  REQUIRE_SIDECAR=1
  REQUIRE_XCODE=1
  if [[ -z "$REQUIRE_MIXED_LAYOUT_CONFIGURED" ]]; then
    REQUIRE_MIXED_LAYOUT=1
  fi
  if [[ -z "$REQUIRE_INPUT_SOURCE_CONFIGURED" ]]; then
    REQUIRE_INPUT_SOURCE=1
  fi
  if [[ -z "$REQUIRE_PATCHED_APP_CONFIGURED" ]]; then
    REQUIRE_PATCHED_APP=1
  fi
fi

printf 'RAG-IME Squirrel integration doctor\n'
printf 'repo: %s\n' "$ROOT"
printf 'squirrel_workdir: %s\n' "$SQUIRREL_WORKDIR"
printf 'sidecar: %s\n' "$SIDECAR_BASE_URL"
printf 'squirrel_app: %s\n' "$SQUIRREL_APP"
printf 'squirrel_input_source: %s\n' "$SQUIRREL_INPUT_SOURCE_ID"
printf 'tryout_readiness: %s\n' "$REQUIRE_TRYOUT"
printf 'require_hitoolbox_enabled: %s\n' "$REQUIRE_HITOOLBOX_ENABLED"
printf 'require_mixed_layout: %s\n' "$REQUIRE_MIXED_LAYOUT"
printf 'refresh_input_source: %s\n' "$REFRESH_INPUT_SOURCE"
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
  local tmpdir
  local out
  local status

  if [[ -x "$app/Contents/MacOS/Squirrel" ]]; then
    ok "installed Squirrel.app executable exists: $app"
  else
    require_or_warn "$REQUIRE_INPUT_SOURCE" "installed Squirrel.app executable missing: $app"
    return
  fi

  check_patched_squirrel_app "$app" "$REQUIRE_PATCHED_APP"
  check_duplicate_squirrel_apps "$app"

  if bool_true "$REFRESH_INPUT_SOURCE"; then
    "$app/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
    sleep 0.3
    "$app/Contents/MacOS/Squirrel" --enable-input-source "$input_source_id" >/dev/null 2>&1 ||
      "$app/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 ||
      true
    sleep 0.3
  fi

  tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/rag-ime-tis-input-source.out.XXXXXX")"
  out="$tmpdir/out"
  set +e
  if bool_true "$REQUIRE_HITOOLBOX_ENABLED"; then
    "$ROOT/scripts/check_macos_input_source.sh" --require-hitoolbox-enabled "$input_source_id" >"$out" 2>&1
  else
    "$ROOT/scripts/check_macos_input_source.sh" "$input_source_id" >"$out" 2>&1
  fi
  status=$?
  set -e

  if [[ "$status" == "0" ]]; then
    ok "macOS input source enabled: $(cat "$out")"
  elif grep -Fq "id=$input_source_id" "$out"; then
    require_or_warn "$REQUIRE_INPUT_SOURCE" "macOS input source is registered but not enabled/selectable: $(cat "$out")"
  else
    require_or_warn "$REQUIRE_INPUT_SOURCE" "macOS input source is not registered: $(cat "$out"); run RAG_IME_SQUIRREL_APP=\"$app\" scripts/enable_squirrel_hitoolbox_input_source.sh"
  fi
  rm -rf "$tmpdir"
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
"$PYTHON_EXECUTABLE" - "$SIDECAR_BASE_URL" "$EXPECT_PREDICTOR_PROVIDER" "$EXPECT_PREDICTOR_MODEL" "$EXPECT_STREAM_FIRST" "$REQUIRE_MIXED_LAYOUT" >"$sidecar_out" 2>"$sidecar_err" <<'PY'
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

require_mixed_layout = truthy(sys.argv[5].strip())

def expected_rank_for_label(label):
    if label == "0":
        return 10
    if str(label).isdigit():
        return int(label)
    return None

def validate_candidate_contract(result, *, require):
    display = result.get("displayCandidates")
    if not isinstance(display, list):
        return {
            "ok": False,
            "checked": require,
            "message": "candidate contract: displayCandidates is not an array",
        }
    if not require:
        return {
            "ok": True,
            "checked": False,
            "message": "candidate contract: not required",
            "displayCount": len(display),
        }

    errors = []
    model_indices = []
    rag_indices = []
    rime_indices = []
    for index, item in enumerate(display):
        if not isinstance(item, dict):
            errors.append(f"candidate {index + 1} is not an object")
            continue
        label = str(item.get("label") or "")
        selection_key = str(item.get("selectionKey") or "")
        selection_rank = item.get("selectionRank")
        expected_label = "0" if index == 9 else str(index + 1)
        if label != expected_label:
            errors.append(f"candidate {index + 1} label={label!r}, expected {expected_label!r}")
        if selection_key != label:
            errors.append(f"candidate {index + 1} selectionKey={selection_key!r}, expected label")
        if selection_rank != expected_rank_for_label(label):
            errors.append(f"candidate {index + 1} selectionRank={selection_rank!r}, expected rank for {label!r}")

        source_type = str(item.get("sourceType") or "")
        display_layout = str(item.get("displayLayout") or "")
        display_lane = str(item.get("displayLane") or "")
        selection_action = str(item.get("selectionAction") or "")
        if source_type in {"model", "rag"} and selection_action != "commit_side_candidate":
            errors.append(f"{source_type} candidate {label} does not commit side candidate")
        if source_type == "model":
            model_indices.append(index)
            if display_layout != "inline" or display_lane != "model":
                errors.append(f"model candidate {label} is not inline/model")
        elif source_type == "rag":
            rag_indices.append(index)
            if display_layout != "block" or display_lane != "memory":
                errors.append(f"rag candidate {label} is not block/memory")
        elif source_type == "rime":
            rime_indices.append(index)
            if selection_action != "select_rime_candidate":
                errors.append(f"rime candidate {label} does not route to Rime selection")

    policy = result.get("mergePolicy") if isinstance(result.get("mergePolicy"), dict) else {}
    if policy.get("sideFirst") is not True or policy.get("rimeFirst") is not False:
        errors.append("mergePolicy is not side-first")
    if policy.get("fallbackOrder") != ["model", "rag", "rime"]:
        errors.append("mergePolicy fallbackOrder is not model/rag/rime")
    if not model_indices:
        errors.append("no model inline candidates")
    if not rag_indices:
        errors.append("no rag block candidates")
    if model_indices and rag_indices and max(model_indices) > min(rag_indices):
        errors.append("model inline candidates do not precede rag block candidates")
    if rime_indices and (model_indices or rag_indices) and min(rime_indices) < max(model_indices + rag_indices):
        errors.append("Rime fallback appears before side candidates")

    ok = not errors
    return {
        "ok": ok,
        "checked": True,
        "message": (
            "candidate contract: model inline + rag block + shared selection keys passed"
            if ok
            else "candidate contract failed: " + "; ".join(errors[:5])
        ),
        "displayCount": len(display),
        "modelCount": len(model_indices),
        "ragCount": len(rag_indices),
        "rimeCount": len(rime_indices),
    }

try:
    with urllib.request.urlopen(f"{base}/health", timeout=1.5) as response:
        health = json.loads(response.read().decode("utf-8"))
    payload = {
        "sessionId": "doctor",
        "requestSeq": 1,
        "rawInput": "ragshurufa",
        "preedit": "ragshurufa",
        "committedContext": "用户正在验证 RAG 输入法候选布局和数字键选择",
        "maxVisibleCandidates": 8 if require_mixed_layout else 3,
        "maxSideCandidates": 8 if require_mixed_layout else 1,
        "forceSideCandidates": require_mixed_layout,
        "rimeContext": {
            "candidates": [
                {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                {"label": "2", "text": "RAG 记忆", "comment": "rime"},
            ]
        },
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
        "dryRun": True,
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
        candidate_contract = validate_candidate_contract(result, require=require_mixed_layout)
        predictor = health.get("predictor") if isinstance(health.get("predictor"), dict) else {}
        provider_name = str(predictor.get("providerName") or "")
        model = str(predictor.get("model") or "")
        stream_first = bool(predictor.get("streamFirstCandidate"))
        model_info = predictor.get("modelInfo") if isinstance(predictor.get("modelInfo"), dict) else {}
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
        if model_info and model_info.get("textOnly") is False and model_info.get("hasVisionConfig") is True:
            predictor_ok = False
            messages.append("active MLX model includes vision_config; prefer a text-only model for IME latency/memory")
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
            "candidateContract": candidate_contract,
            "predictorCheck": {
                "ok": predictor_ok,
                "message": "; ".join(messages),
                "providerName": provider_name,
                "model": model,
                "streamFirstCandidate": stream_first,
                "modelInfo": model_info,
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
  candidate_contract_line="$("$PYTHON_EXECUTABLE" - "$sidecar_out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
contract = payload.get("candidateContract") if isinstance(payload.get("candidateContract"), dict) else {}
if not contract.get("checked"):
    print("SKIP\tcandidate contract: not required")
else:
    level = "OK" if contract.get("ok", False) else "WARN"
    message = str(contract.get("message") or "candidate contract: status unavailable")
    counts = (
        f" display={contract.get('displayCount')} "
        f"model={contract.get('modelCount')} "
        f"rag={contract.get('ragCount')} "
        f"rime={contract.get('rimeCount')}"
    )
    print(f"{level}\t{message};{counts}")
PY
)"
  candidate_contract_level="${candidate_contract_line%%	*}"
  candidate_contract_message="${candidate_contract_line#*	}"
  if [[ "$candidate_contract_level" == "OK" ]]; then
    ok "$candidate_contract_message"
  elif [[ "$candidate_contract_level" != "SKIP" ]]; then
    require_or_warn "$REQUIRE_MIXED_LAYOUT" "$candidate_contract_message"
  fi
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
