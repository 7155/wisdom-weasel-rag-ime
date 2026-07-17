#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HOME/Applications/RagImeDesktopBridge.app"
EXECUTABLE="$APP/Contents/MacOS/RagImeDesktopBridge"
LABEL="com.rag-ime.desktop-bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

"$ROOT/scripts/build_desktop_bridge.sh" install >/dev/null
mkdir -p "$HOME/Library/LaunchAgents"

/usr/libexec/PlistBuddy -c "Clear dict" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :Label string $LABEL" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string $EXECUTABLE" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string --headless" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :RunAtLoad bool true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :KeepAlive dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :KeepAlive:SuccessfulExit bool false" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProcessType string Interactive" "$PLIST"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
if ! "$EXECUTABLE" --request-accessibility-only >/dev/null 2>&1; then
  echo "Accessibility approval was requested for RagImeDesktopBridge; semantic reads stay fail-closed until it is granted." >&2
fi
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  sleep 0.4
  launchctl bootstrap "$DOMAIN" "$PLIST"
fi
launchctl kickstart -k "$DOMAIN/$LABEL"
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
