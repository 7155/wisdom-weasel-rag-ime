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
EOF
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
  "$PI_PYTHON" "$ROOT/scripts/install_managed_pi_runtime.py" \
    --payload "$PI_BUILD_DIR" \
    --app-support "$APP_SUPPORT_DIR"
  required+=(--require piRuntime --require piSkills)
fi

if [[ "$INCLUDE_DESKTOP" == "1" ]]; then
  "$ROOT/scripts/install_desktop_bridge_launch_agent.sh"
  required+=(--require desktopBridge)
fi

# The stack owns launch order. Prevent the standalone Sidecar installer from
# also refreshing the gateway, otherwise launchd sees two back-to-back
# bootout/bootstrap cycles for the same label and can reject the second one.
RAG_IME_INSTALL_AGENT_GATEWAY=0 "$ROOT/scripts/install_sidecar_launch_agent.sh"

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

if [[ "$INCLUDE_MLX" == "auto" ]]; then
  if [[ -f "$APP_SUPPORT_DIR/models.json" || -f "$HOME/Library/LaunchAgents/com.rag-ime.mlx-predictor.plist" ]]; then
    INCLUDE_MLX=1
  else
    INCLUDE_MLX=0
  fi
fi
if [[ "$INCLUDE_MLX" == "1" ]]; then
  "$ROOT/scripts/install_mlx_predictor_launch_agent.sh"
  required+=(--require mlxPredictor)
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
  "$ROOT/scripts/build_patched_squirrel.sh" install
fi

# Install the user-visible app last so its marker becomes the canonical product
# generation only after the supporting runtimes have been refreshed.
"$ROOT/scripts/build_control_center_web_host.sh" install-release

"$ROOT/scripts/check_installed_product_components.py" \
  --repo-root "$ROOT" \
  --expected-commit "$SOURCE_COMMIT" \
  "${required[@]}" \
  --require-current
