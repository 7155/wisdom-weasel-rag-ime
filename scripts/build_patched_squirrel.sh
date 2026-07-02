#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
PROJECT_PATH="${RAG_IME_SQUIRREL_PROJECT:-$SQUIRREL_WORKDIR/Squirrel.xcodeproj}"
SCHEME="${RAG_IME_SQUIRREL_SCHEME:-Squirrel}"
CONFIGURATION="${RAG_IME_SQUIRREL_CONFIGURATION:-Release}"
DERIVED_DATA="${RAG_IME_SQUIRREL_DERIVED_DATA:-/tmp/rag-ime-squirrel-derived-data}"
INSTALL_DIR="${RAG_IME_SQUIRREL_INSTALL_DIR:-$HOME/Library/Input Methods}"
INSTALL_APP_NAME="${RAG_IME_SQUIRREL_INSTALL_APP_NAME:-Squirrel}"
ACTION="${1:-${RAG_IME_SQUIRREL_BUILD_ACTION:-build}}"
DRY_RUN="${RAG_IME_SQUIRREL_BUILD_DRY_RUN:-0}"
XCODEBUILD="${RAG_IME_XCODEBUILD:-$(command -v xcodebuild || true)}"
PREINSTALL="${RAG_IME_SQUIRREL_PREINSTALL:-auto}"
NO_DOWNLOAD="${RAG_IME_SQUIRREL_NO_DOWNLOAD:-0}"
SKIP_POSTINSTALL="${RAG_IME_SQUIRREL_SKIP_POSTINSTALL:-0}"
SKIP_CODESIGN="${RAG_IME_SQUIRREL_SKIP_CODESIGN:-0}"
CODESIGN_IDENTITY="${RAG_IME_SQUIRREL_CODESIGN_IDENTITY:--}"
DEFAULT_BUNDLE_ID="im.rime.inputmethod.Squirrel"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-$DEFAULT_BUNDLE_ID}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"
HANT_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_HANT_INPUT_SOURCE_ID:-$BUNDLE_ID.Hant}"
if [[ "$BUNDLE_ID" == "$DEFAULT_BUNDLE_ID" && "$INSTALL_APP_NAME" == "Squirrel" ]]; then
  DEFAULT_DISPLAY_NAME="Squirrel"
  DEFAULT_CONNECTION_NAME="Squirrel_Connection"
else
  DEFAULT_DISPLAY_NAME="$INSTALL_APP_NAME"
  DEFAULT_CONNECTION_NAME="RagIme_Connection"
fi
DISPLAY_NAME="${RAG_IME_SQUIRREL_DISPLAY_NAME:-$DEFAULT_DISPLAY_NAME}"
HANS_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANS_DISPLAY_NAME:-$DISPLAY_NAME - Simplified}"
HANT_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANT_DISPLAY_NAME:-$DISPLAY_NAME - Traditional}"
CONNECTION_NAME="${RAG_IME_SQUIRREL_CONNECTION_NAME:-$DEFAULT_CONNECTION_NAME}"
BUILD_SETTINGS_EXTRA="${RAG_IME_SQUIRREL_BUILD_SETTINGS:-CODE_SIGNING_ALLOWED=NO}"

extra_build_settings=()
if [[ -n "$BUILD_SETTINGS_EXTRA" ]]; then
  read -r -a extra_build_settings <<< "$BUILD_SETTINGS_EXTRA"
fi

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

usage() {
  cat <<EOF
Usage: scripts/build_patched_squirrel.sh [list|build|install]

Environment:
  RAG_IME_SQUIRREL_WORKDIR       patched Squirrel checkout (default: /tmp/rag-ime-squirrel)
  RAG_IME_SQUIRREL_PROJECT       Xcode project path (default: <workdir>/Squirrel.xcodeproj)
  RAG_IME_SQUIRREL_SCHEME        Xcode scheme (default: Squirrel)
  RAG_IME_SQUIRREL_CONFIGURATION Xcode configuration (default: Release)
  RAG_IME_SQUIRREL_DERIVED_DATA  derived data path (default: /tmp/rag-ime-squirrel-derived-data)
  RAG_IME_SQUIRREL_INSTALL_DIR   install target (default: ~/Library/Input Methods)
  RAG_IME_SQUIRREL_INSTALL_APP_NAME installed app bundle name (default: Squirrel)
  RAG_IME_SQUIRREL_BUNDLE_ID     app/input-source bundle prefix (default: im.rime.inputmethod.Squirrel)
  RAG_IME_SQUIRREL_DISPLAY_NAME  app/input-source display name (default: Squirrel or install app name)
  RAG_IME_SQUIRREL_CONNECTION_NAME input method connection name (default: Squirrel_Connection or RagIme_Connection)
  RAG_IME_SQUIRREL_PREINSTALL    auto|1|0, run Squirrel action-install when dependencies are missing
  RAG_IME_SQUIRREL_NO_DOWNLOAD   set no_download=1 for action-install
  RAG_IME_SQUIRREL_BUILD_SETTINGS extra xcodebuild settings (default: CODE_SIGNING_ALLOWED=NO)
  RAG_IME_SQUIRREL_CODESIGN_IDENTITY codesign identity after copy (default: - for ad-hoc)
  RAG_IME_SQUIRREL_SKIP_CODESIGN skip post-copy codesign
  RAG_IME_SQUIRREL_SKIP_POSTINSTALL skip Squirrel scripts/postinstall after install
  RAG_IME_SQUIRREL_INPUT_SOURCE_ID input source checked after install
  RAG_IME_XCODEBUILD             xcodebuild executable override
  RAG_IME_SQUIRREL_BUILD_DRY_RUN print resolved commands without requiring Xcode/workdir
EOF
}

xcodebuild_base_args=(
  -project "$PROJECT_PATH"
)

xcodebuild_build_args=(
  -project "$PROJECT_PATH"
  -scheme "$SCHEME"
  -configuration "$CONFIGURATION"
  -derivedDataPath "$DERIVED_DATA"
  "${extra_build_settings[@]}"
  build
)

PRODUCT_APP="$DERIVED_DATA/Build/Products/$CONFIGURATION/Squirrel.app"
TARGET_APP="$INSTALL_DIR/$INSTALL_APP_NAME.app"

if [[ "$ACTION" != "list" && "$ACTION" != "build" && "$ACTION" != "install" ]]; then
  usage >&2
  echo "unknown action: $ACTION" >&2
  exit 1
fi

if bool_true "$DRY_RUN"; then
  cat <<EOF
repo_root=$ROOT
workdir=$SQUIRREL_WORKDIR
project=$PROJECT_PATH
scheme=$SCHEME
configuration=$CONFIGURATION
derived_data=$DERIVED_DATA
product_app=$PRODUCT_APP
install_dir=$INSTALL_DIR
install_app_name=$INSTALL_APP_NAME
target_app=$TARGET_APP
action=$ACTION
xcodebuild=${XCODEBUILD:-<not-found>}
preinstall=$PREINSTALL
no_download=$NO_DOWNLOAD
build_settings=$BUILD_SETTINGS_EXTRA
codesign_identity=$CODESIGN_IDENTITY
skip_codesign=$SKIP_CODESIGN
bundle_id=$BUNDLE_ID
input_source_id=$INPUT_SOURCE_ID
hant_input_source_id=$HANT_INPUT_SOURCE_ID
display_name=$DISPLAY_NAME
connection_name=$CONNECTION_NAME
list_command=${XCODEBUILD:-xcodebuild} ${xcodebuild_base_args[*]} -list
build_command=${XCODEBUILD:-xcodebuild} ${xcodebuild_build_args[*]}
install_command=$0 install
EOF
  exit 0
fi

require_file() {
  local path="$1"
  local message="$2"
  if [[ ! -f "$path" ]]; then
    echo "$message: $path" >&2
    exit 1
  fi
}

require_text() {
  local path="$1"
  local text="$2"
  local description="$3"
  if ! grep -Fq "$text" "$path"; then
    echo "patched Squirrel workdir is missing $description in $path" >&2
    exit 1
  fi
}

if [[ ! -d "$SQUIRREL_WORKDIR/.git" ]]; then
  echo "Squirrel workdir not prepared: $SQUIRREL_WORKDIR" >&2
  echo "Run scripts/prepare_squirrel_workspace.sh first." >&2
  exit 1
fi

if [[ ! -d "$PROJECT_PATH" || ! -f "$PROJECT_PATH/project.pbxproj" ]]; then
  echo "patched Squirrel Xcode project missing: $PROJECT_PATH" >&2
  echo "Run scripts/prepare_squirrel_workspace.sh first and verify the Squirrel checkout." >&2
  exit 1
fi

require_file "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift" "patched Squirrel workdir is missing RAG-IME model file"
require_file "$SQUIRREL_WORKDIR/sources/RagImeSidecarClient.swift" "patched Squirrel workdir is missing RAG-IME client file"
require_file "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "patched Squirrel workdir is missing patched SquirrelInputController"
require_file "$SQUIRREL_WORKDIR/sources/SquirrelPanel.swift" "patched Squirrel workdir is missing patched SquirrelPanel"
require_file "$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml" "patched Squirrel workdir is missing generated config snippet"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "ragImePanelForcesHorizontalLayout" "mixed LLM horizontal-lane guard"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "traceRagImeFrontendEvent" "foreground frontend trace hook"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "panel_text_layout" "actual frontend mixed-layout trace event"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "sidecar_request_scheduled" "real foreground sidecar request trace event"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "sidecar_empty_response_ignored" "empty sidecar response guard"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "rag-ime.foreground-trace.v2" "foreground trace v2 marker"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "forceSideCandidates: true" "foreground forced LLM/RAG candidate request"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift" "candidate.sourceType" "compact model inline candidate comments"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelPanel.swift" "candidateSeparator" "mixed inline/block candidate separator"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelPanel.swift" "ragImePanelLinear" "forced horizontal layout for inline LLM candidates"
require_text "$SQUIRREL_WORKDIR/sources/SquirrelPanel.swift" "traceRagImePanelTextLayout" "actual frontend mixed-layout trace"
if [[ -f "$SQUIRREL_WORKDIR/sources/InputSource.swift" ]]; then
  require_text "$SQUIRREL_WORKDIR/sources/InputSource.swift" "static var inputSourceIDPrefix: String" "brandable input-source prefix"
fi

deps_ready() {
  [[ -f "$SQUIRREL_WORKDIR/lib/librime.1.dylib" ]] &&
    [[ -d "$SQUIRREL_WORKDIR/Frameworks/Sparkle.framework" ]] &&
    [[ -f "$SQUIRREL_WORKDIR/bin/rime-install" ]]
}

prepare_squirrel_dependencies() {
  if [[ "$ACTION" == "list" ]]; then
    return 0
  fi

  local should_preinstall=0
  if bool_true "$PREINSTALL"; then
    should_preinstall=1
  elif [[ "$PREINSTALL" == "auto" && ! deps_ready ]]; then
    should_preinstall=1
  fi

  if [[ "$should_preinstall" == "1" ]]; then
    if [[ ! -x "$SQUIRREL_WORKDIR/action-install.sh" ]]; then
      echo "[WARN] Squirrel action-install.sh not found; skipping dependency preinstall" >&2
    else
      printf '[INFO] preparing Squirrel binary dependencies with action-install.sh\n'
      if bool_true "$NO_DOWNLOAD"; then
        (cd "$SQUIRREL_WORKDIR" && no_download=1 ./action-install.sh)
      else
        (cd "$SQUIRREL_WORKDIR" && ./action-install.sh)
      fi
    fi
  fi

  if [[ -f "$SQUIRREL_WORKDIR/package/add_data_files" ]]; then
    printf '[INFO] refreshing Squirrel bundled data files\n'
    (cd "$SQUIRREL_WORKDIR" && bash package/add_data_files)
  fi
}

ensure_squirrel_input_source_enabled() {
  local app="$1"
  local attempt
  local output

  if [[ ! -x "$app/Contents/MacOS/Squirrel" ]]; then
    printf '[WARN] Squirrel executable missing; cannot verify input source: %s\n' "$app" >&2
    return 0
  fi
  for attempt in 1 2 3 4 5; do
    "$app/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
    sleep 0.5
    "$app/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 || true
    if output="$("$ROOT/scripts/check_macos_input_source.sh" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
      printf '[OK] macOS input source enabled for real use: %s\n' "$output"
      return 0
    fi
    sleep 0.5
  done
  printf '[WARN] macOS input source not confirmed for real use after install: %s\n' "$output" >&2
  printf '[WARN] If thirdPartyEnabled=false, add %s from System Settings -> Keyboard -> Input Sources.\n' "$DISPLAY_NAME" >&2
}

should_brand_app() {
  [[ "$INSTALL_APP_NAME" != "Squirrel" ||
    "$BUNDLE_ID" != "$DEFAULT_BUNDLE_ID" ||
    "$INPUT_SOURCE_ID" != "$DEFAULT_BUNDLE_ID.Hans" ||
    "$HANT_INPUT_SOURCE_ID" != "$DEFAULT_BUNDLE_ID.Hant" ||
    "$DISPLAY_NAME" != "Squirrel" ||
    "$CONNECTION_NAME" != "Squirrel_Connection" ]]
}

run_branded_postinstall() {
  local app="$1"
  local output

  "$app/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
  sleep 0.5
  "$app/Contents/MacOS/Squirrel" --enable-input-source "$INPUT_SOURCE_ID" >/dev/null 2>&1 || true
  sleep 0.5
  if output="$("$ROOT/scripts/check_macos_input_source.sh" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
    printf '[OK] branded macOS input source enabled for real use: %s\n' "$output"
  else
    printf '[WARN] branded macOS input source not confirmed after install: %s\n' "$output" >&2
    RAG_IME_SQUIRREL_APP="$app" \
      RAG_IME_SQUIRREL_BUNDLE_ID="$BUNDLE_ID" \
      RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$INPUT_SOURCE_ID" \
      "$ROOT/scripts/enable_squirrel_hitoolbox_input_source.sh" >/dev/null 2>&1 || true
    if output="$("$ROOT/scripts/check_macos_input_source.sh" --require-hitoolbox-enabled "$INPUT_SOURCE_ID" 2>&1)"; then
      printf '[OK] branded macOS input source enabled after HIToolbox repair: %s\n' "$output"
    else
      printf '[WARN] branded macOS input source still needs manual System Settings add: %s\n' "$output" >&2
    fi
  fi
  if output="$("$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID" 2>&1)"; then
    printf '[OK] selected branded input source: %s\n' "$output"
  else
    printf '[WARN] branded input source was not selected automatically: %s\n' "$output" >&2
  fi
}

install_squirrel_app() {
  if [[ ! -d "$PRODUCT_APP" ]]; then
    echo "built Squirrel.app not found: $PRODUCT_APP" >&2
    exit 1
  fi
  mkdir -p "$INSTALL_DIR"
  rm -rf "$TARGET_APP"
  cp -R "$PRODUCT_APP" "$TARGET_APP"
  printf '[OK] installed patched Squirrel.app: %s\n' "$TARGET_APP"

  if should_brand_app; then
    RAG_IME_SQUIRREL_APP="$TARGET_APP" \
      RAG_IME_SQUIRREL_BUNDLE_ID="$BUNDLE_ID" \
      RAG_IME_SQUIRREL_INPUT_SOURCE_ID="$INPUT_SOURCE_ID" \
      RAG_IME_SQUIRREL_HANT_INPUT_SOURCE_ID="$HANT_INPUT_SOURCE_ID" \
      RAG_IME_SQUIRREL_DISPLAY_NAME="$DISPLAY_NAME" \
      RAG_IME_SQUIRREL_HANS_DISPLAY_NAME="$HANS_DISPLAY_NAME" \
      RAG_IME_SQUIRREL_HANT_DISPLAY_NAME="$HANT_DISPLAY_NAME" \
      RAG_IME_SQUIRREL_CONNECTION_NAME="$CONNECTION_NAME" \
      "$ROOT/scripts/brand_squirrel_app.sh" "$TARGET_APP"
    printf '[OK] branded patched Squirrel.app as %s (%s)\n' "$DISPLAY_NAME" "$BUNDLE_ID"
  fi

  if bool_true "$SKIP_CODESIGN"; then
    printf '[WARN] skipped Squirrel codesign; input source registration may fail\n' >&2
  elif command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign "$CODESIGN_IDENTITY" "$TARGET_APP"
    printf '[OK] signed patched Squirrel.app with identity: %s\n' "$CODESIGN_IDENTITY"
  else
    printf '[WARN] codesign not found; input source registration may fail\n' >&2
  fi

  RAG_IME_SQUIRREL_WORKDIR="$SQUIRREL_WORKDIR" \
    RAG_IME_SQUIRREL_CONFIG_SNIPPET="$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml" \
    RAG_IME_SQUIRREL_APP="$TARGET_APP" \
    RAG_IME_SQUIRREL_DEPLOY=0 \
    "$ROOT/scripts/install_squirrel_rag_config.sh"
  printf '[OK] installed RAG-IME Squirrel config\n'

  RAG_IME_SQUIRREL_WORKDIR="$SQUIRREL_WORKDIR" \
    RAG_IME_SQUIRREL_APP="$TARGET_APP" \
    "$ROOT/scripts/bootstrap_squirrel_user_data.sh"

  if bool_true "$SKIP_POSTINSTALL"; then
    printf '[WARN] skipped Squirrel postinstall; input source may need manual registration\n' >&2
    return 0
  fi
  if should_brand_app; then
    run_branded_postinstall "$TARGET_APP"
  elif [[ -f "$SQUIRREL_WORKDIR/scripts/postinstall" ]]; then
    (cd "$SQUIRREL_WORKDIR" && DSTROOT="$INSTALL_DIR" bash scripts/postinstall)
    printf '[OK] Squirrel postinstall completed\n'
    ensure_squirrel_input_source_enabled "$TARGET_APP"
  else
    printf '[WARN] Squirrel postinstall script not found; input source may need manual registration\n' >&2
  fi
}

if [[ -z "$XCODEBUILD" || ! -x "$XCODEBUILD" ]]; then
  active_developer_dir="$(xcode-select -p 2>/dev/null || true)"
  if [[ "$active_developer_dir" == *CommandLineTools* ]]; then
    echo "xcodebuild is not available from full Xcode; active developer directory is CommandLineTools." >&2
  else
    echo "xcodebuild is not available." >&2
  fi
  echo "Install/select full Xcode with scripts/setup_xcode_for_squirrel.sh." >&2
  exit 1
fi

if ! xcodebuild_version="$("$XCODEBUILD" -version 2>&1)"; then
  active_developer_dir="$(xcode-select -p 2>/dev/null || true)"
  echo "xcodebuild -version failed." >&2
  if [[ "$active_developer_dir" == *CommandLineTools* ]]; then
    echo "active developer directory is CommandLineTools; full Xcode is required for Squirrel." >&2
  fi
  printf '%s\n' "$xcodebuild_version" >&2
  echo "Install/select full Xcode with scripts/setup_xcode_for_squirrel.sh." >&2
  exit 1
fi

printf 'RAG-IME patched Squirrel build\n'
printf 'repo: %s\n' "$ROOT"
printf 'workdir: %s\n' "$SQUIRREL_WORKDIR"
printf 'project: %s\n' "$PROJECT_PATH"
printf 'scheme: %s\n' "$SCHEME"
printf 'configuration: %s\n' "$CONFIGURATION"
printf 'derived_data: %s\n' "$DERIVED_DATA"
printf 'product_app: %s\n' "$PRODUCT_APP"
printf 'install_dir: %s\n' "$INSTALL_DIR"
printf 'target_app: %s\n' "$TARGET_APP"
printf 'bundle_id: %s\n' "$BUNDLE_ID"
printf 'input_source_id: %s\n' "$INPUT_SOURCE_ID"
printf 'xcodebuild: %s\n' "$XCODEBUILD"
printf 'xcodebuild_version: %s\n\n' "$(printf '%s' "$xcodebuild_version" | tr '\n' ' ')"

"$XCODEBUILD" "${xcodebuild_base_args[@]}" -list >/dev/null
printf '[OK] xcodebuild can inspect patched Squirrel project\n'

if [[ "$ACTION" == "list" ]]; then
  exit 0
fi

prepare_squirrel_dependencies
"$XCODEBUILD" "${xcodebuild_build_args[@]}"
printf '[OK] xcodebuild build succeeded\n'
printf '[OK] built patched Squirrel.app: %s\n' "$PRODUCT_APP"

if [[ "$ACTION" == "install" ]]; then
  install_squirrel_app
fi
