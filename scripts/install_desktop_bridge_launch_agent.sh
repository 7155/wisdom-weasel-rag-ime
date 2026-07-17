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

wait_for_previous_job_release() {
  local attempt
  for attempt in {1..60}; do
    if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "previous launchd job did not release in time: $DOMAIN/$LABEL" >&2
  return 1
}

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
wait_for_previous_job_release
launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
if ! "$EXECUTABLE" --request-accessibility-only >/dev/null 2>&1; then
  echo "Accessibility approval was requested for RagImeDesktopBridge; semantic reads stay fail-closed until it is granted." >&2
fi

bootstrap_launch_agent() {
  local attempt
  local error_log
  error_log="$(mktemp "${TMPDIR:-/tmp}/rag-ime-desktop-bridge-bootstrap.XXXXXX")"
  trap 'rm -f "$error_log"' RETURN

  # launchd can retain the old app job briefly after bootout while TCC checks
  # the rebuilt bundle. Retry long enough for that job teardown to complete.
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if launchctl bootstrap "$DOMAIN" "$PLIST" 2>"$error_log"; then
      return 0
    fi
    [[ "$attempt" == "10" ]] || sleep "$(awk "BEGIN { printf \"%.1f\", $attempt * 0.4 }")"
  done

  echo "launchctl bootstrap failed for $DOMAIN/$LABEL" >&2
  cat "$error_log" >&2
  return 1
}

bootstrap_launch_agent
if ! launchctl kickstart "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  # RunAtLoad may already be transitioning through xpcproxy. A loaded job is
  # sufficient here; the stack audit verifies that it reaches running state.
  launchctl print "$DOMAIN/$LABEL" >/dev/null
fi
launchctl print "$DOMAIN/$LABEL" | grep -E 'state =|pid =|last exit code' || true
