#!/usr/bin/env bash
set -euo pipefail

XCODE_VERSION="${RAG_IME_XCODE_VERSION:-27.0 Beta 2}"
INSTALL_DIR="${RAG_IME_XCODE_INSTALL_DIR:-/Volumes/undo 4t/Applications}"
DOWNLOAD_DIR="${RAG_IME_XCODE_DOWNLOAD_DIR:-/Volumes/undo 4t/XcodeDownloads}"
USE_SUDO="${RAG_IME_USE_SUDO:-0}"
INSTALL_MODE="${RAG_IME_INSTALL_XCODE:-0}"
PREFERRED_XCODE_APP="${RAG_IME_XCODE_APP:-}"

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

section() {
  printf '\n== %s ==\n' "$1"
}

print_command() {
  printf '  %s\n' "$1"
}

find_xcode_app() {
  if [[ -n "$PREFERRED_XCODE_APP" && -d "$PREFERRED_XCODE_APP/Contents/Developer" ]]; then
    printf '%s\n' "$PREFERRED_XCODE_APP"
    return 0
  fi

  local candidates=()
  candidates+=("/Applications/Xcode.app")
  candidates+=("$INSTALL_DIR/Xcode.app")

  local found
  while IFS= read -r found; do
    candidates+=("$found")
  done < <(find "$INSTALL_DIR" -maxdepth 1 -type d -name 'Xcode*.app' 2>/dev/null | sort -r)

  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate/Contents/Developer" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

run_xcodebuild_version() {
  local developer_dir="$1"
  DEVELOPER_DIR="$developer_dir" xcodebuild -version 2>/dev/null
}

configure_xcode() {
  local xcode_app="$1"
  local developer_dir="$xcode_app/Contents/Developer"

  section "Detected Xcode"
  printf 'xcode_app: %s\n' "$xcode_app"
  printf 'developer_dir: %s\n' "$developer_dir"

  if run_xcodebuild_version "$developer_dir"; then
    printf 'project-local xcodebuild check: OK\n'
  else
    printf 'project-local xcodebuild check: FAIL\n'
    return 1
  fi

  section "System Configuration"
  if bool_true "$USE_SUDO"; then
    sudo xcode-select -s "$developer_dir"
    sudo xcodebuild -license accept
    sudo xcodebuild -runFirstLaunch
    printf 'selected developer directory: %s\n' "$(xcode-select -p)"
  else
    printf 'Not changing global xcode-select because RAG_IME_USE_SUDO is not set.\n'
    printf 'For this shell, use:\n'
    print_command "export DEVELOPER_DIR=\"$developer_dir\""
    printf 'To configure globally, run:\n'
    print_command "RAG_IME_USE_SUDO=1 $0"
  fi
}

print_install_help() {
  section "Install Help"
  printf 'No full Xcode.app was found.\n'
  printf 'Current recommended prerelease for this macOS 27 beta host: %s\n' "$XCODE_VERSION"
  printf 'Preferred external install directory: %s\n' "$INSTALL_DIR"
  printf 'Preferred external download directory: %s\n' "$DOWNLOAD_DIR"

  printf '\nIf Apple Developer authentication is available to xcodes:\n'
  print_command "brew install xcodes aria2"
  print_command "mkdir -p \"$INSTALL_DIR\" \"$DOWNLOAD_DIR\""
  print_command "xcodes download \"$XCODE_VERSION\" --directory \"$DOWNLOAD_DIR\""
  print_command "xcodes install \"$XCODE_VERSION\" --directory \"$INSTALL_DIR\""

  printf '\nIf you prefer App Store stable Xcode:\n'
  print_command "brew install mas"
  print_command "mas open 497799835"
  printf 'Then install Xcode in the App Store UI and rerun this script.\n'

  printf '\nAfter Xcode is installed, rerun:\n'
  print_command "$0"

  printf '\nOptional automation switches:\n'
  print_command "RAG_IME_INSTALL_XCODE=xcodes $0"
  print_command "RAG_IME_INSTALL_XCODE=mas $0"
}

try_install() {
  case "$INSTALL_MODE" in
    0|false|FALSE|no|NO)
      return 0
      ;;
    xcodes)
      mkdir -p "$INSTALL_DIR" "$DOWNLOAD_DIR"
      if ! command -v xcodes >/dev/null 2>&1; then
        printf 'xcodes is not installed. Install it with: brew install xcodes\n' >&2
        return 1
      fi
      xcodes download "$XCODE_VERSION" --directory "$DOWNLOAD_DIR"
      xip_path="$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name 'Xcode*.xip' -print | sort -r | head -1)"
      if [[ -z "$xip_path" ]]; then
        printf 'Downloaded Xcode .xip was not found in %s\n' "$DOWNLOAD_DIR" >&2
        return 1
      fi
      xcodes install --path "$xip_path" --directory "$INSTALL_DIR"
      ;;
    mas)
      if ! command -v mas >/dev/null 2>&1; then
        printf 'mas is not installed. Install it with: brew install mas\n' >&2
        return 1
      fi
      mas get 497799835
      ;;
    *)
      printf 'Unknown RAG_IME_INSTALL_XCODE=%s. Use 0, xcodes, or mas.\n' "$INSTALL_MODE" >&2
      return 1
      ;;
  esac
}

section "Host State"
sw_vers || true
printf 'active_developer_dir: %s\n' "$(xcode-select -p 2>/dev/null || printf '<none>')"
printf 'DEVELOPER_DIR: %s\n' "${DEVELOPER_DIR:-<unset>}"
printf 'install_dir: %s\n' "$INSTALL_DIR"
printf 'download_dir: %s\n' "$DOWNLOAD_DIR"

if command -v xcodes >/dev/null 2>&1; then
  printf 'xcodes: %s\n' "$(xcodes version 2>/dev/null || printf '<error>')"
else
  printf 'xcodes: <missing>\n'
fi

if command -v mas >/dev/null 2>&1; then
  printf 'mas: %s\n' "$(mas version 2>/dev/null || printf '<error>')"
else
  printf 'mas: <missing>\n'
fi

try_install

if xcode_app="$(find_xcode_app)"; then
  configure_xcode "$xcode_app"
else
  print_install_help
fi
