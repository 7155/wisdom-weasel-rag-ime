#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HOME/Applications/RagImeVoice.app"
VOICE_EXECUTABLE="$APP/Contents/MacOS/RagImeVoice"
LABEL="com.rag-ime.voice"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

"$ROOT/scripts/build_voice_input.sh" install >/dev/null
mkdir -p "$HOME/Library/LaunchAgents"

/usr/libexec/PlistBuddy -c "Clear dict" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :Label string $LABEL" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string $VOICE_EXECUTABLE" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :RunAtLoad bool true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :KeepAlive dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :KeepAlive:SuccessfulExit bool false" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :ProcessType string Interactive" "$PLIST"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
while IFS= read -r pid; do
  [[ -n "$pid" ]] || continue
  kill "$pid" >/dev/null 2>&1 || true
done < <(pgrep -f "^${VOICE_EXECUTABLE}$" 2>/dev/null || true)
for _ in 1 2 3 4 5; do
  pgrep -f "^${VOICE_EXECUTABLE}$" >/dev/null 2>&1 || break
  sleep 0.2
done
if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
  sleep 0.4
  launchctl bootstrap "$DOMAIN" "$PLIST"
fi
launchctl kickstart -k "$DOMAIN/$LABEL"
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
