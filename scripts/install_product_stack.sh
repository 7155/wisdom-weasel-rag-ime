#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
INCLUDE_SQUIRREL=0
INCLUDE_VOICE=1
INCLUDE_MAINTENANCE=1
INCLUDE_MLX="auto"

usage() {
  cat <<'EOF'
Usage: scripts/install_product_stack.sh [options]

Options:
  --include-squirrel    Rebuild and install the patched Squirrel input method.
  --skip-voice          Do not install the optional voice agent.
  --skip-maintenance    Do not install the Memory Book maintenance job.
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
    --skip-voice) INCLUDE_VOICE=0 ;;
    --skip-maintenance) INCLUDE_MAINTENANCE=0 ;;
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

# The stack owns launch order. Prevent the standalone Sidecar installer from
# also refreshing the gateway, otherwise launchd sees two back-to-back
# bootout/bootstrap cycles for the same label and can reject the second one.
RAG_IME_INSTALL_AGENT_GATEWAY=0 "$ROOT/scripts/install_sidecar_launch_agent.sh"

required=(--require control --require sidecar --require squirrel)
if [[ -f "$APP_SUPPORT_DIR/PiRuntime/current.json" ]]; then
  "$ROOT/scripts/install_agent_gateway_launch_agent.sh"
  required+=(--require piRuntime)
else
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
