#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
INCLUDE_SQUIRREL=0
INCLUDE_DESKTOP=1
INCLUDE_VOICE=1
INCLUDE_MAINTENANCE=1
INCLUDE_MLX="auto"
INCLUDE_PI="auto"
PI_WORKTREE="${RAG_IME_PI_WORKTREE:-}"
SQUIRREL_WORKDIR_OVERRIDE_SET=0
SQUIRREL_WORKDIR_OVERRIDE=""
SQUIRREL_DERIVED_DATA_OVERRIDE_SET=0
SQUIRREL_DERIVED_DATA_OVERRIDE=""
SQUIRREL_STACK_TEMP_ROOT=""
SQUIRREL_STACK_WORKDIR=""
SQUIRREL_STACK_DERIVED_DATA=""
if [[ "${RAG_IME_SQUIRREL_WORKDIR+x}" == "x" ]]; then
  SQUIRREL_WORKDIR_OVERRIDE_SET=1
  SQUIRREL_WORKDIR_OVERRIDE="$RAG_IME_SQUIRREL_WORKDIR"
fi
if [[ "${RAG_IME_SQUIRREL_DERIVED_DATA+x}" == "x" ]]; then
  SQUIRREL_DERIVED_DATA_OVERRIDE_SET=1
  SQUIRREL_DERIVED_DATA_OVERRIDE="$RAG_IME_SQUIRREL_DERIVED_DATA"
fi

usage() {
  cat <<'EOF'
Usage: scripts/install_product_stack.sh [options]

Options:
  --include-squirrel    Rebuild and install the patched Squirrel input method.
  --skip-desktop        Do not install the Accessibility-only desktop bridge.
  --skip-voice          Do not install the optional voice agent.
  --skip-maintenance    Do not install the Memory Book maintenance job.
  --skip-pi             Do not rebuild Pi; reuse an existing verified Runtime if present.
  --include-pi          Require rebuilding and installing the managed Pi Runtime.
  --pi-worktree PATH    Build Pi from this verified worktree instead of auto-discovery.
  --skip-mlx            Do not reinstall the MLX predictor.
  --include-mlx         Require and reinstall the MLX predictor.
  -h, --help            Show this help.

The stack installer refuses dirty tracked source by default. Set
RAG_IME_ALLOW_DIRTY_INSTALL=1 only for an explicitly marked development build.

With --include-squirrel, an explicit RAG_IME_SQUIRREL_WORKDIR or
RAG_IME_SQUIRREL_DERIVED_DATA must be an absolute path that does not exist yet.
The release installer never resets or silently reuses an existing checkout.
EOF
}

cleanup_stack_squirrel_workspace() {
  local exit_code=$?
  trap - EXIT
  if [[ -n "$SQUIRREL_STACK_TEMP_ROOT" && -d "$SQUIRREL_STACK_TEMP_ROOT" ]]; then
    rm -rf -- "$SQUIRREL_STACK_TEMP_ROOT"
  fi
  exit "$exit_code"
}

require_fresh_squirrel_path() {
  local label="$1"
  local path="$2"
  if [[ -z "$path" || "$path" != /* || "$path" == "/" ]]; then
    echo "$label must be a non-root absolute path: ${path:-<empty>}" >&2
    exit 73
  fi
  if [[ -e "$path" || -L "$path" ]]; then
    echo "refusing to reuse existing explicit $label: $path" >&2
    echo "choose a new path; the product installer never resets a caller-owned Squirrel workspace" >&2
    exit 73
  fi
}

run_with_stack_squirrel_workspace() {
  env \
    RAG_IME_SQUIRREL_WORKDIR="$SQUIRREL_STACK_WORKDIR" \
    RAG_IME_SQUIRREL_PROJECT="$SQUIRREL_STACK_WORKDIR/Squirrel.xcodeproj" \
    RAG_IME_SQUIRREL_DERIVED_DATA="$SQUIRREL_STACK_DERIVED_DATA" \
    RAG_IME_SQUIRREL_PATCH="$ROOT/squirrel-patches/0001-add-rag-ime-sidecar.patch" \
    RAG_IME_SQUIRREL_RESET=0 \
    RAG_IME_SQUIRREL_DRY_RUN=0 \
    RAG_IME_SQUIRREL_BUILD_DRY_RUN=0 \
    RAG_IME_SQUIRREL_SKIP_POSTINSTALL=0 \
    RAG_IME_SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE=0 \
    "$@"
}

prepare_stack_squirrel_workspace() {
  if [[ "$SQUIRREL_WORKDIR_OVERRIDE_SET" == "1" ]]; then
    require_fresh_squirrel_path "RAG_IME_SQUIRREL_WORKDIR" "$SQUIRREL_WORKDIR_OVERRIDE"
    SQUIRREL_STACK_WORKDIR="$SQUIRREL_WORKDIR_OVERRIDE"
  fi
  if [[ "$SQUIRREL_DERIVED_DATA_OVERRIDE_SET" == "1" ]]; then
    require_fresh_squirrel_path \
      "RAG_IME_SQUIRREL_DERIVED_DATA" \
      "$SQUIRREL_DERIVED_DATA_OVERRIDE"
    SQUIRREL_STACK_DERIVED_DATA="$SQUIRREL_DERIVED_DATA_OVERRIDE"
  fi
  if [[ "$SQUIRREL_WORKDIR_OVERRIDE_SET" != "1" ||
    "$SQUIRREL_DERIVED_DATA_OVERRIDE_SET" != "1" ]]; then
    SQUIRREL_STACK_TEMP_ROOT="$(
      mktemp -d "${TMPDIR:-/tmp}/rag-ime-squirrel-install-stack.XXXXXX"
    )"
    trap cleanup_stack_squirrel_workspace EXIT
  fi
  if [[ "$SQUIRREL_WORKDIR_OVERRIDE_SET" != "1" ]]; then
    SQUIRREL_STACK_WORKDIR="$SQUIRREL_STACK_TEMP_ROOT/worktree"
  fi
  if [[ "$SQUIRREL_DERIVED_DATA_OVERRIDE_SET" != "1" ]]; then
    SQUIRREL_STACK_DERIVED_DATA="$SQUIRREL_STACK_TEMP_ROOT/derived-data"
  fi
  if [[ "$SQUIRREL_STACK_WORKDIR" == "$SQUIRREL_STACK_DERIVED_DATA" ]]; then
    echo "Squirrel workdir and derived-data paths must be different" >&2
    exit 73
  fi

  run_with_stack_squirrel_workspace "$ROOT/scripts/prepare_squirrel_workspace.sh"
  echo "Prepared current-source Squirrel workspace: $SQUIRREL_STACK_WORKDIR"
}

while (($#)); do
  case "$1" in
    --include-squirrel) INCLUDE_SQUIRREL=1 ;;
    --skip-desktop) INCLUDE_DESKTOP=0 ;;
    --skip-voice) INCLUDE_VOICE=0 ;;
    --skip-maintenance) INCLUDE_MAINTENANCE=0 ;;
    --skip-pi) INCLUDE_PI=0 ;;
    --include-pi) INCLUDE_PI=1 ;;
    --pi-worktree)
      shift
      [[ $# -gt 0 ]] || { echo "--pi-worktree requires a path" >&2; exit 2; }
      PI_WORKTREE="$1"
      INCLUDE_PI=1
      ;;
    --skip-mlx) INCLUDE_MLX=0 ;;
    --include-mlx) INCLUDE_MLX=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] \
  && [[ "${RAG_IME_ALLOW_DIRTY_INSTALL:-0}" != "1" ]]; then
  echo "refusing to install a mixed product stack from dirty tracked source" >&2
  echo "commit or stash tracked changes, or set RAG_IME_ALLOW_DIRTY_INSTALL=1 for a development build" >&2
  exit 1
fi

if [[ "$INCLUDE_SQUIRREL" == "1" ]]; then
  prepare_stack_squirrel_workspace
fi

echo "Installing product runtime generation $SOURCE_COMMIT"
EXTENSION_SOURCE="$ROOT/integrations/browser-copilot/extension"
EXTENSION_DEST="$APP_SUPPORT_DIR/BrowserCopilot/extension"
if [[ ! -f "$EXTENSION_SOURCE/manifest.json" ]]; then
  echo "missing Browser Co-pilot extension manifest" >&2
  exit 1
fi
mkdir -p "$(dirname "$EXTENSION_DEST")"
rm -rf "$EXTENSION_DEST"
ditto "$EXTENSION_SOURCE" "$EXTENSION_DEST"
echo "Browser Co-pilot extension installed at $EXTENSION_DEST"

required=(--require control --require sidecar --require squirrel)

if [[ "$INCLUDE_PI" == "auto" ]]; then
  if [[ -n "$PI_WORKTREE" ]] \
    || [[ -f "$APP_SUPPORT_DIR/PiRuntime/current.json" ]] \
    || [[ -d "$ROOT/../pi/packages/rag-ime-runtime-host" ]] \
    || [[ -d "$ROOT/../pi-rag-ime-runtime/packages/rag-ime-runtime-host" ]]; then
    INCLUDE_PI=1
  else
    INCLUDE_PI=0
  fi
fi
if [[ "$INCLUDE_PI" == "1" ]]; then
  PI_BUILD_DIR="$ROOT/build/managed-pi-runtime/install-stack-current"
  PI_PYTHON="${RAG_IME_PYTHON:-$(command -v python3)}"
  if [[ -z "$PI_PYTHON" || ! -x "$PI_PYTHON" ]]; then
    echo "python executable not found for managed Pi Runtime packaging" >&2
    exit 1
  fi
  pi_build_args=(--output "$PI_BUILD_DIR" --force)
  if [[ -n "$PI_WORKTREE" ]]; then
    pi_build_args+=(--pi-worktree "$PI_WORKTREE")
  fi
  "$PI_PYTHON" "$ROOT/scripts/build_managed_pi_runtime_v2.py" "${pi_build_args[@]}"
  PI_STAGE_REPORT="$PI_BUILD_DIR.install-stage.json"
  PI_ACCEPTANCE_REPORT="$PI_BUILD_DIR.acceptance.json"
  : > "$PI_STAGE_REPORT"
  chmod 600 "$PI_STAGE_REPORT"
  "$PI_PYTHON" "$ROOT/scripts/install_managed_pi_runtime.py" \
    --payload "$PI_BUILD_DIR" \
    --app-support "$APP_SUPPORT_DIR" \
    --no-activate > "$PI_STAGE_REPORT"
  PI_RUNTIME_VERSION="$("$PI_PYTHON" - "$PI_STAGE_REPORT" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = str(report.get("runtimeVersion") or "")
if not report.get("ok") or not version:
    raise SystemExit("managed Pi staging did not return a runtime version")
print(version)
PY
  )"
  PI_INSTALLED_PAYLOAD="$APP_SUPPORT_DIR/PiRuntime/$PI_RUNTIME_VERSION"
  : > "$PI_ACCEPTANCE_REPORT"
  chmod 600 "$PI_ACCEPTANCE_REPORT"
  "$PI_PYTHON" "$ROOT/scripts/smoke_pi_session_staged_runtime.py" \
    --payload "$PI_INSTALLED_PAYLOAD" \
    --workspace-root "$ROOT" \
    --deterministic-test-gate > "$PI_ACCEPTANCE_REPORT"
  "$PI_PYTHON" "$ROOT/scripts/install_managed_pi_runtime.py" \
    --payload "$PI_BUILD_DIR" \
    --app-support "$APP_SUPPORT_DIR" \
    --acceptance-report "$PI_ACCEPTANCE_REPORT"
  required+=(--require piRuntime --require piSkills)
fi

if [[ "$INCLUDE_DESKTOP" == "1" ]]; then
  "$ROOT/scripts/install_desktop_bridge_launch_agent.sh"
  required+=(--require desktopBridge)
fi

if [[ "$INCLUDE_MLX" == "auto" ]]; then
  if [[ -f "$APP_SUPPORT_DIR/models.json" || -f "$HOME/Library/LaunchAgents/com.rag-ime.mlx-predictor.plist" ]]; then
    INCLUDE_MLX=1
  else
    INCLUDE_MLX=0
  fi
fi
if [[ "$INCLUDE_MLX" == "1" ]]; then
  # Start the registry-selected resident model before Sidecar. Sidecar resolves
  # the same registry into its predictor contract and its health gate must
  # never publish a usable service backed by NullPredictionProvider.
  "$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
  required+=(--require mlxPredictor)
fi

# The stack owns launch order. Prevent the standalone Sidecar installer from
# also refreshing the gateway, otherwise launchd sees two back-to-back
# bootout/bootstrap cycles for the same label and can reject the second one.
RAG_IME_INSTALL_AGENT_GATEWAY=0 \
  "$ROOT/scripts/install_sidecar_launch_agent.sh"

if [[ -f "$APP_SUPPORT_DIR/PiRuntime/current.json" ]]; then
  "$ROOT/scripts/install_agent_gateway_launch_agent.sh"
  required+=(--require piRuntime)
else
  if [[ "$INCLUDE_PI" == "1" ]]; then
    echo "Managed Pi Runtime packaging completed without an active pointer" >&2
    exit 1
  fi
  echo "Managed Pi Runtime is not installed; Agent gateway installation was skipped."
fi

if [[ "$INCLUDE_MAINTENANCE" == "1" ]]; then
  "$ROOT/scripts/install_memory_book_maintenance_launch_agent.sh"
  required+=(--require memoryBookMaintenance)
fi

if [[ "$INCLUDE_VOICE" == "1" ]]; then
  "$ROOT/scripts/install_voice_input_launch_agent.sh"
  required+=(--require voice)
fi

if [[ "$INCLUDE_SQUIRREL" == "1" ]]; then
  run_with_stack_squirrel_workspace "$ROOT/scripts/build_patched_squirrel.sh" install
fi

# Install the user-visible app last so its marker becomes the canonical product
# generation only after the supporting runtimes have been refreshed.
"$ROOT/scripts/build_control_center_web_host.sh" install-release

"$ROOT/scripts/check_installed_product_components.py" \
  --repo-root "$ROOT" \
  --expected-commit "$SOURCE_COMMIT" \
  "${required[@]}" \
  --require-current

# Runtime retention is deliberately after deterministic session.open,
# room.dispatch, Provider-context inspection and room.cancel exercised the
# installed payload before activation. The component audit above is additional
# provenance/live-process evidence; HTTP 200 alone never authorizes retirement.
if [[ "$INCLUDE_PI" == "1" ]]; then
  PI_RETENTION_PLAN="$PI_BUILD_DIR.retention-plan.json"
  PI_RETENTION_REPORT="$PI_BUILD_DIR.retention-result.json"
  "$PI_PYTHON" "$ROOT/scripts/prune_managed_pi_runtime.py" \
    --app-support "$APP_SUPPORT_DIR" \
    --retain-generations 2 \
    --report "$PI_RETENTION_PLAN"
  "$PI_PYTHON" "$ROOT/scripts/prune_managed_pi_runtime.py" \
    --app-support "$APP_SUPPORT_DIR" \
    --retain-generations 2 \
    --apply \
    --plan "$PI_RETENTION_PLAN" \
    --report "$PI_RETENTION_REPORT"
fi
