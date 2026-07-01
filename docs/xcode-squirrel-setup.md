# Xcode Setup For Patched Squirrel

This project builds the production macOS input method by patching Squirrel/Rime. The InputMethodKit app in this repository is only a prototype and contract harness; the real frontend needs a full Xcode installation.

## Current Local Finding

On this host, `xcode-select` pointed at:

```text
/Library/Developer/CommandLineTools
```

That is not enough for the full Squirrel build. `xcodebuild -version` fails when the active developer directory is only Command Line Tools.

As of 2026-07-01, this host also has:

```text
xcodes 2.0.2
mas 7.0.0
```

but no full Xcode installation under either:

```text
/Applications
/Volumes/undo 4t/Applications
```

An automated `xcodes` install attempt failed because Apple Developer credentials are not available in this non-interactive Codex session:

```text
Apple ID: Missing username or a password. Please try again.
```

The host is macOS 27.0 beta, so the best matching Xcode candidate from `xcodes list` is:

```text
27.0 Beta 2
```

The App Store stable fallback visible through `mas info 497799835` is:

```text
Xcode 26.6
Minimum OS 26.2
```

For Squirrel validation, 26.6 may be enough; for matching the beta SDK exactly, use the 27.0 beta from Apple Developer.

The system disk currently has too little free space for a full Xcode download plus expansion, so prefer the external disk paths in this document.

## One Command Check

Run:

```bash
scripts/setup_xcode_for_squirrel.sh
```

The script prints:

- current macOS version;
- active `xcode-select` developer directory;
- external-disk and system-disk free space;
- installed Xcode versions under `/Applications` and the external install directory;
- whether `FASTLANE_SESSION` is available;
- whether `xcodes` and `mas` are installed;
- detected `Xcode.app` candidates;
- the exact `DEVELOPER_DIR` export or sudo command to finish configuration.

It does not change global `xcode-select` by default.

## Recommended Install Route

Because the system disk may not have enough free space for Xcode download plus expansion, prefer the external disk:

```bash
mkdir -p "/Volumes/undo 4t/XcodeDownloads" "/Volumes/undo 4t/Applications"
```

If Apple Developer authentication is available to `xcodes`:

```bash
brew install xcodes aria2
xcodes download "27.0 Beta 2" --directory "/Volumes/undo 4t/XcodeDownloads"
xcodes install "27.0 Beta 2" --directory "/Volumes/undo 4t/Applications"
```

For the current non-interactive Codex process, use one of these instead:

```bash
# Run this in a normal terminal so xcodes can prompt for Apple ID credentials.
xcodes download "27.0 Beta 2" --directory "/Volumes/undo 4t/XcodeDownloads"

# Or provide a Fastlane session to the setup script.
export FASTLANE_SESSION="<apple developer session>"
RAG_IME_XCODES_USE_FASTLANE_AUTH=1 RAG_IME_INSTALL_XCODE=xcodes scripts/setup_xcode_for_squirrel.sh
```

If using App Store stable Xcode:

```bash
brew install mas
mas open 497799835
```

Install Xcode from the App Store UI, then rerun:

```bash
scripts/setup_xcode_for_squirrel.sh
```

## Configure After Install

For project-local validation without changing the global developer directory:

```bash
export DEVELOPER_DIR="/path/to/Xcode.app/Contents/Developer"
scripts/doctor_squirrel_integration.sh
```

To configure the whole machine, run:

```bash
RAG_IME_USE_SUDO=1 scripts/setup_xcode_for_squirrel.sh
```

That runs:

```bash
sudo xcode-select -s "/path/to/Xcode.app/Contents/Developer"
sudo xcodebuild -license accept
sudo xcodebuild -runFirstLaunch
```

If Xcode is installed on the external disk, `xcode-select` accepts the external app developer directory:

```bash
sudo xcode-select -s "/Volumes/undo 4t/Applications/Xcode.app/Contents/Developer"
```

## Squirrel Validation

After Xcode is available:

```bash
scripts/prepare_squirrel_workspace.sh
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh
scripts/build_patched_squirrel.sh install
```

`scripts/build_patched_squirrel.sh list` is the non-destructive project
inspection gate. The default `build` action checks the patched files, prepares
Squirrel binary dependencies with `action-install.sh` when needed, refreshes
bundled data files, then runs:

```text
xcodebuild -project <patched>/Squirrel.xcodeproj -scheme Squirrel -configuration Release -derivedDataPath /tmp/rag-ime-squirrel-derived-data CODE_SIGNING_ALLOWED=NO build
```

The `install` action then:

- copies the built `Squirrel.app` to `~/Library/Input Methods` by default;
- ad-hoc signs the copied app with `codesign --force --deep --sign -` unless `RAG_IME_SQUIRREL_SKIP_CODESIGN=1` is set;
- writes a managed `rag_ime/*` patch block into `~/Library/Rime/squirrel.custom.yaml`;
- runs Squirrel `scripts/postinstall` so the input source is registered, built, and enabled.

Useful switches:

```bash
# Install machine-wide instead of user-local.
RAG_IME_SQUIRREL_INSTALL_DIR="/Library/Input Methods" scripts/build_patched_squirrel.sh install

# Reuse already downloaded Squirrel dependency archives.
RAG_IME_SQUIRREL_NO_DOWNLOAD=1 scripts/build_patched_squirrel.sh

# Copy/install without running Squirrel postinstall.
RAG_IME_SQUIRREL_SKIP_POSTINSTALL=1 scripts/build_patched_squirrel.sh install

# Copy/install without local ad-hoc signing. This is mainly for tests.
RAG_IME_SQUIRREL_SKIP_CODESIGN=1 scripts/build_patched_squirrel.sh install
```

After install, keep the sidecar running and run the strict gate again:

```bash
scripts/install_sidecar_launch_agent.sh
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
```

In strict mode the doctor also checks macOS Text Input Services and should report
`im.rime.inputmethod.Squirrel.Hans enabled=true selectable=true`. This is not
enough to prove the input method is visible in System Settings. Add the
HIToolbox gate when verifying installation on the user's machine:

```bash
RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 \
RAG_IME_DOCTOR_REQUIRE_HITOOLBOX_ENABLED=1 \
RAG_IME_SQUIRREL_APP="/Library/Input Methods/Squirrel.app" \
  scripts/doctor_squirrel_integration.sh
```

If the output says `hitoolboxEnabled=false`, Squirrel is registered but not
present in the current user's enabled input-source list. The normal route is:
System Settings -> Keyboard -> Input Sources -> "+" -> Chinese, Simplified ->
Squirrel - Simplified. For local debug only, the repo includes a helper:

```bash
scripts/enable_squirrel_hitoolbox_input_source.sh
```

It backs up `com.apple.HIToolbox` to the Desktop, appends Squirrel's bundle/mode
entries, restarts `cfprefsd`, and re-runs the strict source check. After that,
run `Squirrel --register-input-source` again if TIS temporarily drops the source.

Terminal-based selection can still fail if macOS refuses to switch the active
foreground input source from a background command; use the input menu for the
continuous typing test. After switching from the input menu, use:

```bash
scripts/wait_squirrel_typing_ready.sh
```

It waits until `im.rime.inputmethod.Squirrel.Hans selected=true`, then confirms
the sidecar health and configured local model lane.

After that, run the combined machine gate:

```bash
python3 -m rag_ime.cli \
  --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" \
  squirrel-tryout-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --report-path /tmp/rag-ime-squirrel-tryout-report.json
```

This gate is intentionally read-only. It verifies the selected input source,
the installed `Squirrel.app`, the actual Rime managed config, the user
LaunchAgent, sidecar health, the `/rime-suggest` sidecar payload, and the
backend/Rime-sidecar quality gate.
It does not install, enable, switch, select a side candidate, or drive the GUI.

Manual continuous-use verification:

1. Open System Settings -> Keyboard -> Input Sources and confirm Squirrel is present.
2. Select Squirrel from the macOS input menu and wait for `scripts/wait_squirrel_typing_ready.sh` to pass.
3. Run `squirrel-tryout-gate` and keep `/tmp/rag-ime-squirrel-tryout-report.json`.
4. Open a normal editor and type at least 20 mixed Chinese/English prompts.
5. Confirm normal Rime candidates still occupy the primary candidate slots.
6. Confirm RAG/model side candidates appear only after stable Rime candidates or idle semantic input.
7. Select at least one side candidate by number key and confirm `/rime-select` records the commit in the sidecar logs.

If the project opens in Xcode but the script fails, inspect the exact
`xcodebuild` output first; the wrapper checks the patched files and config before
entering Xcode build proper.
