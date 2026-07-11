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
SIDECAR_LAUNCH_AGENT_PLIST="${RAG_IME_SIDECAR_LAUNCH_AGENT_PLIST:-$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist}"
MLX_LAUNCH_AGENT_LABEL="${RAG_IME_MLX_LAUNCH_AGENT_LABEL:-com.rag-ime.mlx-predictor}"
MLX_LAUNCH_AGENT_PLIST="${RAG_IME_MLX_LAUNCH_AGENT_PLIST:-$HOME/Library/LaunchAgents/$MLX_LAUNCH_AGENT_LABEL.plist}"
REQUIRE_SIDECAR="${RAG_IME_DOCTOR_REQUIRE_SIDECAR:-0}"
REQUIRE_XCODE="${RAG_IME_DOCTOR_REQUIRE_XCODE:-0}"
REQUIRE_PREDICTOR="${RAG_IME_DOCTOR_REQUIRE_PREDICTOR:-0}"
REQUIRE_TRYOUT="${RAG_IME_DOCTOR_REQUIRE_TRYOUT:-0}"
REQUIRE_LAUNCH_AGENT_PLIST_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_LAUNCH_AGENT_PLIST:-}"
REQUIRE_LAUNCH_AGENT_PLIST="${REQUIRE_LAUNCH_AGENT_PLIST_CONFIGURED:-0}"
REQUIRE_HITOOLBOX_ENABLED="${RAG_IME_DOCTOR_REQUIRE_HITOOLBOX_ENABLED:-${RAG_IME_REQUIRE_HITOOLBOX_ENABLED:-0}}"
REQUIRE_MIXED_LAYOUT_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_MIXED_LAYOUT:-}"
REQUIRE_MIXED_LAYOUT="${REQUIRE_MIXED_LAYOUT_CONFIGURED:-0}"
CHECK_LAUNCHD="${RAG_IME_DOCTOR_CHECK_LAUNCHD:-1}"
REQUIRE_INPUT_SOURCE_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE:-}"
REQUIRE_INPUT_SOURCE="${REQUIRE_INPUT_SOURCE_CONFIGURED:-0}"
REQUIRE_SELECTED_INPUT_SOURCE="${RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE:-0}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
SQUIRREL_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
REFRESH_INPUT_SOURCE="${RAG_IME_DOCTOR_REFRESH_INPUT_SOURCE:-1}"
REFRESH_INPUT_SOURCE_SCRIPT="${RAG_IME_REFRESH_SQUIRREL_INPUT_SOURCE_REGISTRATION_SCRIPT:-$ROOT/scripts/refresh_squirrel_input_source_registration.sh}"
REQUIRE_PATCHED_APP_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_PATCHED_APP:-}"
REQUIRE_PATCHED_APP="${REQUIRE_PATCHED_APP_CONFIGURED:-0}"
SQUIRREL_APP_BASENAME="$(basename "$SQUIRREL_APP")"
DEFAULT_DUPLICATE_APP_CANDIDATES="$HOME/Library/Input Methods/$SQUIRREL_APP_BASENAME:/Library/Input Methods/$SQUIRREL_APP_BASENAME"
SQUIRREL_DUPLICATE_APP_CANDIDATES="${RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES:-$DEFAULT_DUPLICATE_APP_CANDIDATES}"
REQUIRE_FRONTEND_TRACE="${RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE:-0}"
FRONTEND_TRACE_WAIT="${RAG_IME_DOCTOR_FRONTEND_TRACE_WAIT:-0}"
FRONTEND_TRACE_LOG="${RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG:-$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl}"
REQUIRE_LOGITS_MODEL_CONFIGURED="${RAG_IME_DOCTOR_REQUIRE_LOGITS_MODEL:-}"
REQUIRE_LOGITS_MODEL="${REQUIRE_LOGITS_MODEL_CONFIGURED:-0}"
EXPECT_PREDICTOR_PROVIDER="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_PROVIDER:-${RAG_IME_PREDICTOR_PROVIDER:-}}"
EXPECT_PREDICTOR_MODEL="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_MODEL:-${RAG_IME_PREDICTOR_MODEL:-}}"
EXPECT_PREDICTOR_BASE_URL="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_BASE_URL:-${RAG_IME_PREDICTOR_BASE_URL:-}}"
EXPECT_PREDICTOR_PROFILE="${RAG_IME_DOCTOR_EXPECT_PREDICTOR_PROFILE:-${RAG_IME_PREDICTOR_PROFILE:-}}"
EXPECT_STREAM_FIRST="${RAG_IME_DOCTOR_EXPECT_STREAM_FIRST:-${RAG_IME_PREDICTOR_STREAM_FIRST:-}}"
DOCTOR_LATENCY_BUDGET_MS="${RAG_IME_DOCTOR_LATENCY_BUDGET_MS:-2000}"

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

app_binary_hash() {
  local app="$1"
  local executable="$app/Contents/MacOS/Squirrel"
  [[ -x "$executable" ]] || return 0
  shasum -a 256 "$executable" 2>/dev/null | awk '{print $1}'
}

same_path() {
  local left="$1"
  local right="$2"
  [[ "$(cd "$(dirname "$left")" 2>/dev/null && pwd -P)/$(basename "$left")" == "$(cd "$(dirname "$right")" 2>/dev/null && pwd -P)/$(basename "$right")" ]]
}

squirrel_app_has_mixed_frontend_trace() {
  local app="$1"
  local executable="$app/Contents/MacOS/Squirrel"
  local marker
  local marker_text
  [[ -x "$executable" ]] || return 1
  marker_text="$(strings "$executable" 2>/dev/null || true)"
  for marker in \
    "rag-ime.squirrel-frontend-trace.v1" \
    "rag-ime.foreground-trace.v2" \
    "composition_ai_suppressed" \
    "foreground_context_capture_resolved" \
    "assistant_overlay_candidate_visible" \
    "side_candidate_feedback_recorded"; do
    grep -Fq -- "$marker" <<< "$marker_text" || return 1
  done
}

check_patched_squirrel_app() {
  local app="$1"
  local required="$2"

  if squirrel_app_has_mixed_frontend_trace "$app"; then
    ok "installed Squirrel.app contains current RAG-IME frontend patch"
  else
    require_or_warn "$required" "installed Squirrel.app lacks current RAG-IME frontend patch; rebuild/install patched Squirrel: $app"
  fi
}

check_duplicate_squirrel_apps() {
  local configured_app="$1"
  local candidate
  local configured_bundle_id
  local bundle_id
  local configured_hash
  local candidate_hash
  local found_stale=0

  configured_bundle_id="$(app_bundle_id "$configured_app")"
  configured_hash="$(app_binary_hash "$configured_app")"
  if [[ -z "$configured_bundle_id" ]]; then
    configured_bundle_id="im.rime.inputmethod.Squirrel"
  fi
  IFS=':' read -r -a duplicate_candidates <<< "$SQUIRREL_DUPLICATE_APP_CANDIDATES"
  for candidate in "${duplicate_candidates[@]}"; do
    [[ -n "$candidate" && -d "$candidate" ]] || continue
    if same_path "$candidate" "$configured_app"; then
      continue
    fi
    bundle_id="$(app_bundle_id "$candidate")"
    [[ "$bundle_id" == "$configured_bundle_id" ]] || continue
    if ! squirrel_app_has_mixed_frontend_trace "$candidate"; then
      found_stale=1
      require_or_warn "$REQUIRE_PATCHED_APP" "stale input method app with same bundle id lacks current RAG-IME frontend patch: $candidate; replace or remove it before foreground typing validation"
      continue
    fi
    candidate_hash="$(app_binary_hash "$candidate")"
    if [[ -n "$configured_hash" && -n "$candidate_hash" && "$candidate_hash" != "$configured_hash" ]]; then
      found_stale=1
      require_or_warn "$REQUIRE_PATCHED_APP" "duplicate input method app with same bundle id differs from configured patched app: $candidate; replace/remove it to avoid macOS loading an older input method binary"
    fi
  done

  if [[ "$found_stale" == "0" ]]; then
    ok "no stale same-bundle input method app detected in duplicate app candidates"
  fi
}

check_frontend_trace() {
  local out
  local status
  local wait_seconds

  if ! bool_true "$REQUIRE_FRONTEND_TRACE"; then
    return 0
  fi
  if [[ ! -f "$ROOT/scripts/check_squirrel_frontend_trace.py" ]]; then
    fail "frontend trace checker missing: $ROOT/scripts/check_squirrel_frontend_trace.py"
    return 0
  fi

  out="$(mktemp /tmp/rag-ime-frontend-trace.out.XXXXXX)"
  wait_seconds="$FRONTEND_TRACE_WAIT"
  set +e
  "$PYTHON_EXECUTABLE" "$ROOT/scripts/check_squirrel_frontend_trace.py" \
    --log-path "$FRONTEND_TRACE_LOG" \
    --require-mixed-panel \
    --require-side-commit \
    --require-modern-prediction-session \
    --wait "$wait_seconds" \
    --print-last 4 >"$out" 2>&1
  status=$?
  set -e

  if [[ "$status" == "0" ]]; then
    trace_line="$("$PYTHON_EXECUTABLE" - "$out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
panel = payload.get("latestMixedPanel") if isinstance(payload.get("latestMixedPanel"), dict) else {}
layout = payload.get("latestMixedTextLayout") if isinstance(payload.get("latestMixedTextLayout"), dict) else {}
number_key_commit = payload.get("latestNumberKeySideCommit") if isinstance(payload.get("latestNumberKeySideCommit"), dict) else {}
modern_session_event = payload.get("latestModernPredictionSession") if isinstance(payload.get("latestModernPredictionSession"), dict) else {}
commit = number_key_commit.get("commit") if isinstance(number_key_commit.get("commit"), dict) else {}
counts = layout.get("candidateCounts") if isinstance(layout.get("candidateCounts"), dict) else panel.get("candidateCounts", {})
candidate = commit.get("candidate") if isinstance(commit.get("candidate"), dict) else {}
prediction_session = modern_session_event.get("predictionSession") if isinstance(modern_session_event.get("predictionSession"), dict) else {}
print(
    "frontend trace passed: "
    f"events={payload.get('eventCount')} "
    f"modelInline={counts.get('modelInline')} "
    f"ragBlock={counts.get('ragBlock')} "
    f"phase={prediction_session.get('phase')} "
    f"expiresAfterMs={prediction_session.get('expiresAfterMs')} "
    f"numberKey={number_key_commit.get('key')} "
    f"sideCommitLabel={candidate.get('label')}"
)
PY
)"
    ok "$trace_line"
  else
    trace_summary="$("$PYTHON_EXECUTABLE" - "$out" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        payload = json.load(fh)
except Exception:
    print("frontend trace checker did not return JSON")
    raise SystemExit(0)
print(
    "frontend trace missing mixed panel or number-key side commit: "
    f"events={payload.get('eventCount')} "
    f"latestMixedPanel={bool(payload.get('latestMixedPanel'))} "
    f"latestMixedTextLayout={bool(payload.get('latestMixedTextLayout'))} "
    f"latestModernPredictionSession={bool(payload.get('latestModernPredictionSession'))} "
    f"latestSideCommit={bool(payload.get('latestSideCommit'))} "
    f"latestNumberKeySideCommit={bool(payload.get('latestNumberKeySideCommit'))} "
    f"log={payload.get('logPath')}"
)
PY
)"
    require_or_warn "$REQUIRE_FRONTEND_TRACE" "$trace_summary"
  fi
  rm -f "$out"
}

check_launch_agent_plist_drift() {
  local sidecar_json="$1"
  local sidecar_status="$2"
  local out
  local line
  local required
  local level
  local message

  if ! bool_true "$REQUIRE_LAUNCH_AGENT_PLIST" &&
    [[ ! -f "$SIDECAR_LAUNCH_AGENT_PLIST" && ! -f "$MLX_LAUNCH_AGENT_PLIST" ]]; then
    return 0
  fi

  out="$(mktemp /tmp/rag-ime-launch-agent-plist.out.XXXXXX)"
  set +e
  "$PYTHON_EXECUTABLE" - \
    "$ROOT" \
    "$SIDECAR_LAUNCH_AGENT_PLIST" \
    "$LAUNCH_AGENT_LABEL" \
    "$MLX_LAUNCH_AGENT_PLIST" \
    "$MLX_LAUNCH_AGENT_LABEL" \
    "$sidecar_json" \
    "$sidecar_status" \
    "$EXPECT_PREDICTOR_PROVIDER" \
    "$EXPECT_PREDICTOR_MODEL" \
    "$EXPECT_PREDICTOR_BASE_URL" \
    "$EXPECT_PREDICTOR_PROFILE" \
    "$EXPECT_STREAM_FIRST" \
    "$REQUIRE_LOGITS_MODEL" \
    "$REQUIRE_LAUNCH_AGENT_PLIST" >"$out" <<'PY'
import json
import plistlib
import sys
from pathlib import Path
from urllib.parse import urlparse

root = sys.argv[1]
sidecar_plist_path = Path(sys.argv[2])
sidecar_label = sys.argv[3]
mlx_plist_path = Path(sys.argv[4])
mlx_label = sys.argv[5]
sidecar_json_path = Path(sys.argv[6])
sidecar_status = sys.argv[7]
expected_provider = sys.argv[8].strip()
expected_model = sys.argv[9].strip()
expected_base_url = sys.argv[10].strip()
expected_profile = sys.argv[11].strip()
expected_stream_first = sys.argv[12].strip()
require_logits_model = sys.argv[13].strip().lower() in {"1", "true", "yes", "on"}
require_plist = sys.argv[14].strip().lower() in {"1", "true", "yes", "on"}

provider_aliases = {
    "ollama": "local-ollama",
    "local-ollama": "local-ollama",
    "mlx": "local-mlx",
    "mlx-lm": "local-mlx",
    "mlx-service": "local-mlx",
    "local-mlx": "local-mlx",
    "openai": "local-openai-compatible",
    "openai-compatible": "local-openai-compatible",
    "local-openai-compatible": "local-openai-compatible",
}


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_provider(value: str) -> str:
    return provider_aliases.get(value.strip().lower(), value.strip())


def provider_matches(expected: str, actual: str) -> bool:
    if not expected:
        return True
    return normalize_provider(expected) == normalize_provider(actual)


def load_plist(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    return payload if isinstance(payload, dict) else None


def arg_value(args: list[object], flag: str) -> str:
    for index, item in enumerate(args):
        if str(item) == flag and index + 1 < len(args):
            return str(args[index + 1])
    return ""


def parsed_port(url: str) -> str:
    if not url:
        return ""
    try:
        port = urlparse(url).port
    except ValueError:
        return ""
    return str(port or "")


def emit(name: str, ok: bool, required: bool, message: str) -> None:
    level = "OK" if ok else "FAIL" if required else "WARN"
    print(f"{level}\t{1 if required else 0}\t{name}: {message}")


health: dict[str, object] = {}
if sidecar_status == "0" and sidecar_json_path.exists():
    with sidecar_json_path.open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    health = parsed if isinstance(parsed, dict) else {}

predictor = health.get("predictorCheck") if isinstance(health.get("predictorCheck"), dict) else {}
health_provider = str(predictor.get("providerName") or "")
health_model = str(predictor.get("model") or "")
health_stream_first = predictor.get("streamFirstCandidate")
expected_provider = expected_provider or health_provider
expected_model = expected_model or health_model
is_mlx_provider = provider_matches("mlx", expected_provider) or require_logits_model
sidecar_predictor_base_url = ""

sidecar_plist = load_plist(sidecar_plist_path)
if sidecar_plist is None:
    emit(
        "sidecar LaunchAgent plist",
        False,
        require_plist,
        f"missing: {sidecar_plist_path}",
    )
else:
    errors: list[str] = []
    args = sidecar_plist.get("ProgramArguments") if isinstance(sidecar_plist.get("ProgramArguments"), list) else []
    env = sidecar_plist.get("EnvironmentVariables") if isinstance(sidecar_plist.get("EnvironmentVariables"), dict) else {}
    if sidecar_plist.get("Label") != sidecar_label:
        errors.append(f"Label={sidecar_plist.get('Label')!r}, expected {sidecar_label!r}")
    if "sidecar-server" not in [str(item) for item in args]:
        errors.append("ProgramArguments missing sidecar-server")
    source_root = str(env.get("RAG_IME_SOURCE_ROOT") or "")
    if source_root != root:
        errors.append(f"RAG_IME_SOURCE_ROOT={source_root!r}, expected {root!r}")
    plist_provider = str(env.get("RAG_IME_PREDICTOR_PROVIDER") or "")
    if expected_provider and not provider_matches(plist_provider, expected_provider):
        errors.append(f"RAG_IME_PREDICTOR_PROVIDER={plist_provider!r}, expected {expected_provider!r}")
    plist_model = str(env.get("RAG_IME_PREDICTOR_MODEL") or "")
    if expected_model and plist_model != expected_model:
        errors.append(f"RAG_IME_PREDICTOR_MODEL={plist_model!r}, expected {expected_model!r}")
    plist_base_url = str(env.get("RAG_IME_PREDICTOR_BASE_URL") or "")
    sidecar_predictor_base_url = plist_base_url
    if expected_base_url and plist_base_url != expected_base_url:
        errors.append(f"RAG_IME_PREDICTOR_BASE_URL={plist_base_url!r}, expected {expected_base_url!r}")
    if is_mlx_provider and not plist_base_url:
        errors.append("RAG_IME_PREDICTOR_BASE_URL missing for MLX provider")
    plist_profile = str(env.get("RAG_IME_PREDICTOR_PROFILE") or "")
    if expected_profile and plist_profile != expected_profile:
        errors.append(f"RAG_IME_PREDICTOR_PROFILE={plist_profile!r}, expected {expected_profile!r}")
    stream_env = str(env.get("RAG_IME_PREDICTOR_STREAM_FIRST") or "")
    if expected_stream_first and truthy(stream_env) != truthy(expected_stream_first):
        errors.append(
            f"RAG_IME_PREDICTOR_STREAM_FIRST={stream_env!r}, expected {expected_stream_first!r}"
        )
    elif stream_env and isinstance(health_stream_first, bool) and truthy(stream_env) != health_stream_first:
        errors.append(
            f"RAG_IME_PREDICTOR_STREAM_FIRST={stream_env!r}, health has {health_stream_first!r}"
        )
    emit(
        "sidecar LaunchAgent plist",
        not errors,
        require_plist,
        "matches current sidecar provider/model env"
        if not errors
        else "drift: " + "; ".join(errors[:6]),
    )
    v1_defaults = {
        "RAG_IME_RUNTIME_PROFILE": "v1-proof",
        "RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION": "1",
        "RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL": "1",
        "RAG_IME_ENABLE_COMPOSING_MODEL": "0",
        "RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL": "0",
        "RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS": "180",
        "RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS": "250",
        "RAG_IME_POST_COMMIT_COMPLETION_TTL_MS": "12000",
        "RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS": "12000",
        "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "900",
        "RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT": "1",
        "RAG_IME_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS": "700",
        "RAG_IME_HYBRID_RAG_CORE": "1",
        "RAG_IME_RAG_DIRECT_DISPLAY": "0",
        "RAG_IME_POST_COMMIT_ACTIVE_RAG_BUTTON": "1",
        "RAG_IME_POST_COMMIT_PENDING_PREVIEW": "0",
        "RAG_IME_ENABLE_DEMO_SAFE_FALLBACK": "0",
    }
    v1_errors = [
        f"{key}={str(env.get(key) or '')!r}, expected {expected!r}"
        for key, expected in v1_defaults.items()
        if str(env.get(key) or "") != expected
    ]
    emit(
        "sidecar LaunchAgent v1 foreground defaults",
        not v1_errors,
        require_plist,
        "match post-commit 180/250ms and model UX budget 900ms"
        if not v1_errors
        else "drift: " + "; ".join(v1_errors[:6]),
    )
    deepseek_post_commit = str(env.get("RAG_IME_DEEPSEEK_POST_COMMIT") or "").strip().lower()
    deepseek_post_commit_ok = deepseek_post_commit not in ("1", "true", "yes", "on")
    emit(
        "sidecar LaunchAgent v1 DeepSeek passive gate",
        deepseek_post_commit_ok,
        require_plist,
        "DeepSeek post-commit is not enabled for ordinary v1 candidates"
        if deepseek_post_commit_ok
        else "RAG_IME_DEEPSEEK_POST_COMMIT must not be enabled for ordinary v1 candidate lane",
    )

mlx_required = require_plist and is_mlx_provider
mlx_plist = load_plist(mlx_plist_path)
if mlx_plist is None:
    if mlx_required:
        emit("MLX predictor LaunchAgent plist", False, True, f"missing: {mlx_plist_path}")
elif mlx_plist is not None:
    errors = []
    args = mlx_plist.get("ProgramArguments") if isinstance(mlx_plist.get("ProgramArguments"), list) else []
    env = mlx_plist.get("EnvironmentVariables") if isinstance(mlx_plist.get("EnvironmentVariables"), dict) else {}
    if mlx_plist.get("Label") != mlx_label:
        errors.append(f"Label={mlx_plist.get('Label')!r}, expected {mlx_label!r}")
    if "mlx-predictor-server" not in [str(item) for item in args]:
        errors.append("ProgramArguments missing mlx-predictor-server")
    mlx_model = str(env.get("RAG_IME_MLX_MODEL") or arg_value(args, "--model"))
    if expected_model and mlx_model != expected_model:
        errors.append(f"RAG_IME_MLX_MODEL={mlx_model!r}, expected {expected_model!r}")
    sidecar_port = parsed_port(expected_base_url or sidecar_predictor_base_url)
    mlx_port = str(env.get("RAG_IME_MLX_PORT") or arg_value(args, "--port"))
    if sidecar_port and mlx_port != sidecar_port:
        errors.append(f"RAG_IME_MLX_PORT={mlx_port!r}, expected sidecar base URL port {sidecar_port!r}")
    prompt_cache = str(env.get("RAG_IME_MLX_PROMPT_CACHE") or "")
    memory_profile = str(env.get("RAG_IME_MEMORY_PROFILE") or "").strip().lower()
    prompt_cache_required = memory_profile not in {"low", "safe", "memory", "memory-safe", "minimal"}
    if prompt_cache_required and (not truthy(prompt_cache) or "--prompt-cache" not in [str(item) for item in args]):
        errors.append("MLX prompt cache is not enabled in LaunchAgent")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        if str(env.get(key) or ""):
            errors.append(f"{key} should be empty for local MLX LaunchAgent")
            break
    emit(
        "MLX predictor LaunchAgent plist",
        not errors,
        mlx_required,
        "matches text-only MLX model and memory-profile cache policy"
        if not errors
        else "drift: " + "; ".join(errors[:6]),
    )
PY
  status=$?
  set -e

  if [[ "$status" != "0" ]]; then
    require_or_warn "$REQUIRE_LAUNCH_AGENT_PLIST" "LaunchAgent plist drift check failed to run"
    rm -f "$out"
    return 0
  fi

  while IFS=$'\t' read -r level required message; do
    [[ -n "$level" ]] || continue
    if [[ "$level" == "OK" ]]; then
      ok "$message"
    elif [[ "$required" == "1" ]]; then
      fail "$message"
    else
      warn "$message"
    fi
  done <"$out"
  rm -f "$out"
}

if bool_true "$REQUIRE_TRYOUT"; then
  REQUIRE_SIDECAR=1
  REQUIRE_XCODE=1
  if [[ -z "$REQUIRE_LAUNCH_AGENT_PLIST_CONFIGURED" ]]; then
    REQUIRE_LAUNCH_AGENT_PLIST=1
  fi
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
printf 'require_selected_input_source: %s\n' "$REQUIRE_SELECTED_INPUT_SOURCE"
printf 'require_mixed_layout: %s\n' "$REQUIRE_MIXED_LAYOUT"
printf 'refresh_input_source: %s\n' "$REFRESH_INPUT_SOURCE"
printf 'require_frontend_trace: %s\n' "$REQUIRE_FRONTEND_TRACE"
printf 'require_logits_model: %s\n' "$REQUIRE_LOGITS_MODEL"
printf 'require_launch_agent_plist: %s\n' "$REQUIRE_LAUNCH_AGENT_PLIST"
printf 'doctor_latency_budget_ms: %s\n' "$DOCTOR_LATENCY_BUDGET_MS"
printf 'sidecar_launch_agent_plist: %s\n' "$SIDECAR_LAUNCH_AGENT_PLIST"
printf 'mlx_launch_agent_plist: %s\n' "$MLX_LAUNCH_AGENT_PLIST"
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
    RAG_IME_SQUIRREL_APP="$app" \
      RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$input_source_id" \
      "$REFRESH_INPUT_SOURCE_SCRIPT" >/dev/null 2>&1 || true
  fi

  tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/rag-ime-tis-input-source.out.XXXXXX")"
  out="$tmpdir/out"
  set +e
  if bool_true "$REQUIRE_SELECTED_INPUT_SOURCE" && bool_true "$REQUIRE_HITOOLBOX_ENABLED"; then
    "$ROOT/scripts/check_macos_input_source.sh" --require-selected --require-hitoolbox-enabled "$input_source_id" >"$out" 2>&1
  elif bool_true "$REQUIRE_SELECTED_INPUT_SOURCE"; then
    "$ROOT/scripts/check_macos_input_source.sh" --require-selected "$input_source_id" >"$out" 2>&1
  elif bool_true "$REQUIRE_HITOOLBOX_ENABLED"; then
    "$ROOT/scripts/check_macos_input_source.sh" --require-hitoolbox-enabled "$input_source_id" >"$out" 2>&1
  else
    "$ROOT/scripts/check_macos_input_source.sh" "$input_source_id" >"$out" 2>&1
  fi
  status=$?
  set -e

  if [[ "$status" == "0" ]]; then
    ok "macOS input source enabled: $(cat "$out")"
  elif bool_true "$REQUIRE_SELECTED_INPUT_SOURCE" && grep -Fq "id=$input_source_id" "$out" && grep -Fq "selected=false" "$out"; then
    require_or_warn "$REQUIRE_INPUT_SOURCE" "macOS input source is enabled but not selected/current: $(cat "$out")"
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
"$PYTHON_EXECUTABLE" - "$SIDECAR_BASE_URL" "$EXPECT_PREDICTOR_PROVIDER" "$EXPECT_PREDICTOR_MODEL" "$EXPECT_STREAM_FIRST" "$REQUIRE_MIXED_LAYOUT" "$REQUIRE_LOGITS_MODEL" "$DOCTOR_LATENCY_BUDGET_MS" >"$sidecar_out" 2>"$sidecar_err" <<'PY'
import json
import sys
import time
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
require_logits_model = truthy(sys.argv[6].strip())
latency_budget_ms = int(sys.argv[7].strip() or "300")

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
    side_indices = []
    rime_indices = []
    action_indices = []
    selectable_index = 0
    for index, item in enumerate(display):
        if not isinstance(item, dict):
            errors.append(f"candidate {index + 1} is not an object")
            continue
        source_type = str(item.get("sourceType") or "")
        label = str(item.get("label") or "")
        selection_key = str(item.get("selectionKey") or "")
        selection_rank = item.get("selectionRank")
        display_layout = str(item.get("displayLayout") or "")
        display_lane = str(item.get("displayLane") or "")
        selection_action = str(item.get("selectionAction") or "")
        if source_type in {"action", "status"}:
            if label or selection_key or selection_rank not in {None, 0}:
                errors.append(f"{source_type} row {index + 1} must remain unnumbered")
            if source_type == "action":
                action_indices.append(index)
                if selection_action != "start_active_rag_from_context" or display_lane != "active_rag":
                    errors.append("DeepSeek action row has the wrong routing contract")
            continue

        selectable_index += 1
        expected_label = "0" if selectable_index == 10 else str(selectable_index)
        if label != expected_label:
            errors.append(f"candidate {index + 1} label={label!r}, expected {expected_label!r}")
        if selection_key != label:
            errors.append(f"candidate {index + 1} selectionKey={selection_key!r}, expected label")
        if selection_rank != expected_rank_for_label(label):
            errors.append(f"candidate {index + 1} selectionRank={selection_rank!r}, expected rank for {label!r}")

        if source_type in {"model", "rag"} and selection_action != "commit_side_candidate":
            errors.append(f"{source_type} candidate {label} does not commit side candidate")
        if source_type == "model":
            model_indices.append(index)
            side_indices.append(index)
            if display_layout != "block" or display_lane != "model":
                errors.append(f"model candidate {label} is not block/model")
        elif source_type == "rag":
            rag_indices.append(index)
            side_indices.append(index)
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
    if not side_indices:
        errors.append("no model/RAG side candidates")
    if model_indices and rag_indices and max(model_indices) > min(rag_indices):
        errors.append("model candidates do not precede rag block candidates")
    if rime_indices and side_indices and min(rime_indices) < max(side_indices):
        errors.append("Rime fallback appears before side candidates")

    ok = not errors
    return {
        "ok": ok,
        "checked": True,
        "message": (
            "candidate contract: side candidates have shared selection keys and routing"
            if ok
            else "candidate contract failed: " + "; ".join(errors[:5])
        ),
        "displayCount": len(display),
        "modelCount": len(model_indices),
        "ragCount": len(rag_indices),
        "sideCount": len(side_indices),
        "rimeCount": len(rime_indices),
        "actionCount": len(action_indices),
    }

def post_rime_suggest(payload):
    request = urllib.request.Request(
        f"{base}/rime-suggest",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3.5) as response:
        return json.loads(response.read().decode("utf-8"))

def doctor_prediction_payload(*, session_id="doctor", request_seq=1, latency_ms=None):
    effective_latency_ms = latency_budget_ms if latency_ms is None else latency_ms
    if require_mixed_layout:
        # Mixed-layout readiness checks the end-to-end candidate contract, not
        # the strict first-token latency target. Keep latency optimization as a
        # separate benchmark so a slow local MLX model does not look like a
        # broken LLM/RAG wiring path.
        effective_latency_ms = max(effective_latency_ms, 2000)
    context = "我想设计一个候选展示方式"
    payload = {
        "sessionId": session_id,
        "requestSeq": request_seq,
        "privacyDisposition": "allowed",
        "frontendBuild": "rag-ime.foreground-trace.v2",
        "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
        "rawInput": "",
        "preedit": "",
        "commitTextPreview": "展示方式",
        "idleMs": 80,
        "committedContext": context,
        "maxVisibleCandidates": 8,
        "maxSideCandidates": 8,
        "latencyBudgetMs": effective_latency_ms,
        "forceSideCandidates": require_mixed_layout,
        "frontendRevision": request_seq,
        "selectionEpoch": request_seq,
        "inputGeneration": request_seq,
        "frontAppBundleId": "com.apple.TextEdit",
        "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
        "commitBurstReady": True,
        "commitBurstDeltaChars": len(context),
        "commitBurstTexts": ["展示方式"],
        "foregroundText": reliable_foreground_text(
            context=context,
            request_seq=request_seq,
            group_id="app:doctor-prediction",
        ),
        "rimeContext": {"candidates": []},
    }
    return payload

def doctor_model_validation_payload(*, session_id="doctor-model-validation", request_seq=20, latency_ms=None):
    effective_latency_ms = max(latency_budget_ms, 2000) if latency_ms is None else max(latency_ms, 2000)
    context = "我已经看完 Felix 的候选生命周期，下一步"
    return {
        "sessionId": session_id,
        "requestSeq": request_seq,
        "frontendBuild": "rag-ime.foreground-trace.v2",
        "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
        "rawInput": "",
        "preedit": "",
        "commitTextPreview": "下一步",
        "idleMs": 200,
        "committedContext": context,
        "maxVisibleCandidates": 8,
        "maxSideCandidates": 8,
        "latencyBudgetMs": effective_latency_ms,
        "forceSideCandidates": True,
        "frontendRevision": request_seq,
        "selectionEpoch": request_seq,
        "inputGeneration": request_seq,
        "frontAppBundleId": "com.apple.TextEdit",
        "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
        "commitBurstReady": True,
        "commitBurstDeltaChars": len(context),
        "commitBurstTexts": ["下一步"],
        "foregroundText": reliable_foreground_text(
            context=context,
            request_seq=request_seq,
            group_id="app:doctor-model-validation",
        ),
        "rimeContext": {"candidates": []},
    }

def reliable_foreground_text(*, context, request_seq, group_id):
    return {
        "available": True,
        "source": "text_input_client",
        "confidence": 0.92,
        "freshnessMs": 0,
        "selectedTextHash": "",
        "selectedTextChars": 0,
        "selectedTextPreview": "",
        "surroundingBefore": context,
        "surroundingAfter": "",
        "wholeValueHash": "",
        "wholeValueChars": len(context),
        "canReplaceSelection": False,
        "captureEpoch": request_seq,
        "commitTextMatched": True,
        "contextGroupId": group_id,
        "contextGroupLevel": "app",
        "contextGroupConfidence": 0.5,
        "warnings": ["doctor_text_input_client_context"],
    }

def extract_model_predictions(result, provider_name):
    predictions = result.get("modelPredictions")
    if not isinstance(predictions, list):
        predictions = []
    model_predictions = [
        item for item in predictions
        if isinstance(item, dict) and str(item.get("providerName") or "") == provider_name
    ]
    if model_predictions:
        return model_predictions
    display = result.get("displayCandidates")
    if isinstance(display, list):
        return [
            item for item in display
            if isinstance(item, dict) and item.get("sourceType") == "model"
        ]
    return []

def retry_model_probe_if_needed(result, provider_name, *, force_validation_probe=False):
    model_predictions = extract_model_predictions(result, provider_name)
    if model_predictions:
        return result, model_predictions, ""
    model_lane = result.get("modelLane") if isinstance(result.get("modelLane"), dict) else {}
    skipped_reason = str(model_lane.get("skippedReason") or "")
    retry_reasons = {"model lane already running", "model lane exceeded latency budget"}
    if skipped_reason not in retry_reasons and not force_validation_probe:
        return result, model_predictions, skipped_reason
    last_result = result
    attempts = 4 if (skipped_reason in retry_reasons or force_validation_probe) else 1
    probe_payload = doctor_model_validation_payload(
        session_id=f"doctor-model-validation-{int(time.time() * 1000)}",
        request_seq=20,
        latency_ms=max(latency_budget_ms, 2000),
    )
    for attempt in range(attempts):
        if attempt > 0:
            time.sleep(0.18 * attempt)
            probe_payload["progressiveFollowUp"] = True
        probe = post_rime_suggest(probe_payload)
        model_predictions = extract_model_predictions(probe, provider_name)
        last_result = probe
        if model_predictions:
            return probe, model_predictions, skipped_reason
    return last_result, model_predictions, skipped_reason

def validate_raw_pinyin_guard():
    guard_latency_ms = max(latency_budget_ms, 2000) if require_mixed_layout else latency_budget_ms
    dirty = post_rime_suggest({
        "sessionId": "doctor-raw-pinyin",
        "requestSeq": 2,
        "rawInput": "jiubiruwopinshishur",
        "preedit": "jiubiruwopinshishur",
        "maxVisibleCandidates": 6,
        "maxSideCandidates": 3,
        "latencyBudgetMs": guard_latency_ms,
        "rimeContext": {"candidates": []},
    })
    fallback = post_rime_suggest({
        "sessionId": "doctor-raw-context",
        "requestSeq": 3,
        "rawInput": "asdioj",
        "preedit": "asdioj",
        "committedContext": "我想设计一个候选展示方式",
        "maxVisibleCandidates": 6,
        "maxSideCandidates": 3,
        "latencyBudgetMs": guard_latency_ms,
        "rimeContext": {"candidates": []},
    })

    errors = []
    dirty_trigger = dirty.get("triggerDecision") if isinstance(dirty.get("triggerDecision"), dict) else {}
    dirty_policy = dirty.get("mergePolicy") if isinstance(dirty.get("mergePolicy"), dict) else {}
    if dirty.get("queryBasis") != "rawInputFallback":
        errors.append(f"dirty raw queryBasis={dirty.get('queryBasis')!r}, expected rawInputFallback")
    if dirty_trigger.get("shouldRefresh") is not False:
        errors.append("dirty raw input refreshed side lanes")
    if dirty_policy.get("sideCandidatesEnabled") is not False:
        errors.append("dirty raw input left side candidates enabled")
    if dirty.get("displayCandidates") not in ([], None):
        errors.append("dirty raw input returned display candidates")

    fallback_trigger = fallback.get("triggerDecision") if isinstance(fallback.get("triggerDecision"), dict) else {}
    fallback_display = fallback.get("displayCandidates")
    fallback_side_count = sum(
        1
        for item in fallback_display
        if isinstance(item, dict) and item.get("sourceType") in {"model", "rag"}
    ) if isinstance(fallback_display, list) else 0
    if fallback.get("queryBasis") != "committedContext":
        errors.append(f"context fallback queryBasis={fallback.get('queryBasis')!r}, expected committedContext")
    if fallback_trigger.get("shouldRefresh") is not False:
        errors.append("composition with committed context refreshed side lanes")
    if fallback_side_count != 0:
        errors.append("composition with committed context returned AI side candidates")

    ok = not errors
    return {
        "ok": ok,
        "message": (
            "raw pinyin guard: dirty raw input skips side lanes, including committedContext fallback during composition"
            if ok
            else "raw pinyin guard failed: " + "; ".join(errors[:5])
        ),
        "dirty": {
            "queryBasis": dirty.get("queryBasis"),
            "shouldRefresh": dirty_trigger.get("shouldRefresh"),
            "displayCount": len(dirty.get("displayCandidates") or []),
            "reason": dirty_trigger.get("reason"),
        },
        "fallback": {
            "queryBasis": fallback.get("queryBasis"),
            "shouldRefresh": fallback_trigger.get("shouldRefresh"),
            "sideCount": fallback_side_count,
            "reason": fallback_trigger.get("reason"),
        },
    }

def validate_model_generation_path(result, health):
    predictor = health.get("predictor") if isinstance(health.get("predictor"), dict) else {}
    provider_name = str(predictor.get("providerName") or "")
    is_mlx = provider_matches("mlx", provider_name)
    if not require_logits_model and not is_mlx:
        return (
            {
                "ok": True,
                "checked": False,
                "message": "model generation path: not required",
            },
            result,
        )

    result, model_predictions, retry_reason = retry_model_probe_if_needed(
        result,
        provider_name,
        force_validation_probe=is_mlx,
    )

    capability_probe = predictor.get("capabilityProbe") if isinstance(predictor.get("capabilityProbe"), dict) else {}
    capabilities = predictor.get("capabilities") if isinstance(predictor.get("capabilities"), dict) else {}
    if not capabilities and isinstance(capability_probe.get("capabilities"), dict):
        capabilities = capability_probe.get("capabilities")
    prompt_cache = predictor.get("promptCache") if isinstance(predictor.get("promptCache"), dict) else {}
    if not prompt_cache and isinstance(capability_probe.get("promptCache"), dict):
        prompt_cache = capability_probe.get("promptCache")

    errors = []
    if require_logits_model and not is_mlx:
        errors.append(f"expected MLX logits provider, got {provider_name or '<none>'}")
    if require_logits_model and is_mlx and capabilities.get("logitsTopK") is not True:
        errors.append("MLX health does not advertise logitsTopK")
    if is_mlx and not model_predictions:
        if retry_reason:
            errors.append(f"no MLX model predictions to validate after retry; initial skip={retry_reason}")
        else:
            errors.append("no MLX model predictions to validate")

    modes = []
    fallback_json_values = []
    score_counts = []
    prompt_cache_prepared = bool(prompt_cache.get("enabled")) and bool(prompt_cache.get("prepared"))
    for item in model_predictions:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        mode = str(metadata.get("candidate_mode") or metadata.get("candidateMode") or "")
        server_timing = metadata.get("server_timing") if isinstance(metadata.get("server_timing"), dict) else {}
        if not mode and isinstance(server_timing, dict):
            mode = str(server_timing.get("candidateMode") or "")
        candidate_scores = metadata.get("candidate_scores")
        if candidate_scores is None:
            candidate_scores = metadata.get("candidateScores")
        if isinstance(candidate_scores, list):
            score_counts.append(len(candidate_scores))
        else:
            score_counts.append(0)
        modes.append(mode)
        fallback_json_values.append(server_timing.get("fallbackJson"))
        item_prompt_cache = metadata.get("prompt_cache") if isinstance(metadata.get("prompt_cache"), dict) else {}
        if bool(item_prompt_cache.get("enabled")) and bool(item_prompt_cache.get("prepared")):
            prompt_cache_prepared = True

    verified_mlx_modes = {"next-token-logits", "continuation-branches"}
    if require_logits_model and is_mlx and (
        not modes or any(mode not in verified_mlx_modes for mode in modes)
    ):
        errors.append(f"MLX model candidate modes are not verified logits/branch modes: {modes}")
    if require_logits_model and is_mlx and any(value is not False for value in fallback_json_values):
        errors.append(f"MLX model fell back to JSON generation: {fallback_json_values}")
    if require_logits_model and is_mlx and any(count <= 0 for count in score_counts):
        errors.append("MLX candidates are missing candidate_scores")
    if require_logits_model and is_mlx and not prompt_cache_prepared:
        errors.append("MLX prompt cache is not enabled/prepared")

    ok = not errors
    if ok and require_logits_model:
        mode_summary = ", ".join(sorted({mode or "unknown" for mode in modes})) or "unknown"
        message = f"model generation path: MLX candidates use verified {mode_summary} with prepared prompt cache"
    elif ok and is_mlx:
        mode_summary = ", ".join(sorted({mode or "unknown" for mode in modes})) or "unknown"
        message = f"model generation path: MLX model candidates available ({mode_summary}; logits gate not required)"
    elif ok:
        message = "model generation path: model candidates available"
    else:
        message = "model generation path failed: " + "; ".join(errors[:5])
    return (
        {
            "ok": ok,
            "checked": True,
            "message": message,
            "providerName": provider_name,
            "candidateModes": modes,
            "fallbackJson": fallback_json_values,
            "candidateScoreCounts": score_counts,
            "promptCachePrepared": prompt_cache_prepared,
            "logitsTopK": capabilities.get("logitsTopK"),
        },
        result,
    )

try:
    with urllib.request.urlopen(f"{base}/health", timeout=1.5) as response:
        health = json.loads(response.read().decode("utf-8"))
    result = post_rime_suggest(doctor_prediction_payload())
    raw_pinyin_guard = validate_raw_pinyin_guard()
    model_generation_path, contract_result = validate_model_generation_path(result, health)
    select_payload = {
        "dryRun": True,
        "privacyDisposition": "allowed",
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
        candidate_contract = validate_candidate_contract(contract_result, require=require_mixed_layout)
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
            "displayCandidates": len(contract_result.get("displayCandidates", [])),
            "rimeSelectOk": True,
            "candidateContract": candidate_contract,
            "rawPinyinGuard": raw_pinyin_guard,
            "modelGenerationPath": model_generation_path,
            "rankingDiagnostics": contract_result.get("rankingDiagnostics"),
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
  ranking_line="$("$PYTHON_EXECUTABLE" - "$sidecar_out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
diag = payload.get("rankingDiagnostics") if isinstance(payload.get("rankingDiagnostics"), dict) else {}
if not diag:
    print("INFO\tRAG ranking diagnostics: unavailable from sidecar")
else:
    source_counts = diag.get("sourceCounts") if isinstance(diag.get("sourceCounts"), dict) else {}
    top = diag.get("topCandidate") if isinstance(diag.get("topCandidate"), dict) else {}
    top_text = str(top.get("text") or "")
    top_source = str(top.get("sourceType") or "")
    top_total = top.get("scoreBreakdownTotal")
    source_text = ",".join(f"{key}={value}" for key, value in sorted(source_counts.items())) or "none"
    if diag.get("hasRagScoreBreakdown"):
        print(
            "OK\t"
            + f"RAG ranking diagnostics available; sources={source_text}; "
            + f"top={top_source}:{top_text[:30]} total={top_total}"
        )
    else:
        print(
            "INFO\t"
            + f"RAG ranking diagnostics present without score breakdown; sources={source_text}; "
            + f"top={top_source}:{top_text[:30]}"
        )
PY
)"
  ranking_level="${ranking_line%%	*}"
  ranking_message="${ranking_line#*	}"
  if [[ "$ranking_level" == "OK" ]]; then
    ok "$ranking_message"
  else
    info "$ranking_message"
  fi
  raw_pinyin_guard_line="$("$PYTHON_EXECUTABLE" - "$sidecar_out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
guard = payload.get("rawPinyinGuard") if isinstance(payload.get("rawPinyinGuard"), dict) else {}
level = "OK" if guard.get("ok", False) else "WARN"
message = str(guard.get("message") or "raw pinyin guard: status unavailable")
print(f"{level}\t{message}")
PY
)"
  raw_pinyin_guard_level="${raw_pinyin_guard_line%%	*}"
  raw_pinyin_guard_message="${raw_pinyin_guard_line#*	}"
  if [[ "$raw_pinyin_guard_level" == "OK" ]]; then
    ok "$raw_pinyin_guard_message"
  else
    require_or_warn "$REQUIRE_SIDECAR" "$raw_pinyin_guard_message"
  fi
  model_generation_line="$("$PYTHON_EXECUTABLE" - "$sidecar_out" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
path = payload.get("modelGenerationPath") if isinstance(payload.get("modelGenerationPath"), dict) else {}
if not path.get("checked"):
    print("SKIP\tmodel generation path: not required")
else:
    level = "OK" if path.get("ok", False) else "WARN"
    message = str(path.get("message") or "model generation path: status unavailable")
    detail = (
        f" modes={path.get('candidateModes')} "
        f"fallbackJson={path.get('fallbackJson')} "
        f"promptCachePrepared={path.get('promptCachePrepared')}"
    )
    print(f"{level}\t{message};{detail}")
PY
)"
  model_generation_level="${model_generation_line%%	*}"
  model_generation_message="${model_generation_line#*	}"
  if [[ "$model_generation_level" == "OK" ]]; then
    ok "$model_generation_message"
  elif [[ "$model_generation_level" != "SKIP" ]]; then
    require_or_warn "$REQUIRE_LOGITS_MODEL" "$model_generation_message"
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
check_launch_agent_plist_drift "$sidecar_out" "$sidecar_status"
rm -f "$sidecar_out" "$sidecar_err"

check_frontend_trace

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
