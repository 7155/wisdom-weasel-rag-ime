#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
PROJECT_PATH="${RAG_IME_SQUIRREL_PROJECT:-$SQUIRREL_WORKDIR/Squirrel.xcodeproj}"
SCHEME="${RAG_IME_SQUIRREL_SCHEME:-Squirrel}"
CONFIGURATION="${RAG_IME_SQUIRREL_CONFIGURATION:-Release}"
DERIVED_DATA="${RAG_IME_SQUIRREL_DERIVED_DATA:-/tmp/rag-ime-squirrel-derived-data}"
ACTION="${1:-${RAG_IME_SQUIRREL_BUILD_ACTION:-build}}"
DRY_RUN="${RAG_IME_SQUIRREL_BUILD_DRY_RUN:-0}"
XCODEBUILD="${RAG_IME_XCODEBUILD:-$(command -v xcodebuild || true)}"

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

usage() {
  cat <<EOF
Usage: scripts/build_patched_squirrel.sh [list|build]

Environment:
  RAG_IME_SQUIRREL_WORKDIR       patched Squirrel checkout (default: /tmp/rag-ime-squirrel)
  RAG_IME_SQUIRREL_PROJECT       Xcode project path (default: <workdir>/Squirrel.xcodeproj)
  RAG_IME_SQUIRREL_SCHEME        Xcode scheme (default: Squirrel)
  RAG_IME_SQUIRREL_CONFIGURATION Xcode configuration (default: Release)
  RAG_IME_SQUIRREL_DERIVED_DATA  derived data path (default: /tmp/rag-ime-squirrel-derived-data)
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
  CODE_SIGNING_ALLOWED=NO
  build
)

if [[ "$ACTION" != "list" && "$ACTION" != "build" ]]; then
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
action=$ACTION
xcodebuild=${XCODEBUILD:-<not-found>}
list_command=${XCODEBUILD:-xcodebuild} ${xcodebuild_base_args[*]} -list
build_command=${XCODEBUILD:-xcodebuild} ${xcodebuild_build_args[*]}
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
require_file "$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml" "patched Squirrel workdir is missing generated config snippet"

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
printf 'xcodebuild: %s\n' "$XCODEBUILD"
printf 'xcodebuild_version: %s\n\n' "$(printf '%s' "$xcodebuild_version" | tr '\n' ' ')"

"$XCODEBUILD" "${xcodebuild_base_args[@]}" -list >/dev/null
printf '[OK] xcodebuild can inspect patched Squirrel project\n'

if [[ "$ACTION" == "list" ]]; then
  exit 0
fi

"$XCODEBUILD" "${xcodebuild_build_args[@]}"
printf '[OK] xcodebuild build succeeded\n'
