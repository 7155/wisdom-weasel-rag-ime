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
- bootstraps `~/Library/Rime` with bundled Squirrel data and Plum output, then runs `Squirrel --build` and `--reload` from the user Rime directory;
- runs Squirrel `scripts/postinstall` so the input source is registered and enabled.

The user-data bootstrap is required even when macOS already lists Squirrel in
System Settings. A bundle can be registered while `~/Library/Rime` still lacks
compiled schemas, which makes the selected input method produce no normal
candidate output. The bootstrap command is:

```bash
scripts/bootstrap_squirrel_user_data.sh
```

It verifies build artifacts such as `~/Library/Rime/build/default.yaml` and
`~/Library/Rime/build/luna_pinyin.table.bin`, and it treats Squirrel log lines
like `missing input schema` or `failed to save config` as install failures even
when the executable exits with status 0.

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
enough to prove the input method is visible in System Settings. Before checking,
the doctor refreshes the configured app with `--register-input-source` and
`--enable-input-source`, which makes the gate less sensitive to macOS TIS cache
timing immediately after install. It also verifies that the configured
`Squirrel.app` contains the RAG-IME mixed-layout frontend trace. If another
same-bundle `Squirrel.app` exists outside the configured target and does not
contain that patch, normal doctor warns and strict tryout fails because macOS
may load the stale frontend. The fix is to replace the system copy with the
patched user-local app:

```bash
scripts/replace_system_squirrel_app.sh
```

The script backs up the old `/Library/Input Methods/Squirrel.app` before
copying the patched app, restarts `Squirrel`, then registers and selects the
input source. Add the HIToolbox gate when verifying installation on the user's
machine:

```bash
RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE=1 \
RAG_IME_DOCTOR_REQUIRE_HITOOLBOX_ENABLED=1 \
RAG_IME_SQUIRREL_APP="/Library/Input Methods/Squirrel.app" \
  scripts/doctor_squirrel_integration.sh
```

If the output says `hitoolboxEnabled=false`, Squirrel is registered but not
present in every current-user input-source list macOS uses. The normal route is:
System Settings -> Keyboard -> Input Sources -> "+" -> Chinese, Simplified ->
Squirrel - Simplified. For local debug only, the repo includes a helper:

```bash
scripts/enable_squirrel_hitoolbox_input_source.sh
```

It backs up `com.apple.HIToolbox` and `com.apple.inputsources` to the Desktop,
tries to append Squirrel's bundle/mode entries to both domains, restarts
`cfprefsd`, and re-runs the strict source check. On macOS 27 the third-party
`com.apple.inputsources` domain may reject command-line writes. If the check
prints `thirdPartyEnabled=false`, use the System Settings "+" flow; otherwise
the input menu can keep showing another third-party input method even while TIS
reports Squirrel as registered/selectable.

Terminal-based selection can still fail if macOS refuses to switch the active
foreground input source from a background command; use the input menu for the
continuous typing test. To open the Keyboard settings pane, use the System
Settings Add flow, and wait until macOS has accepted Squirrel into the current
user's third-party input-source list, use:

```bash
scripts/open_squirrel_input_source_settings.sh --wait
```

The helper only opens settings and waits; it does not click System Settings. If
settings is already open, run the strict wait gate directly:

```bash
scripts/wait_squirrel_input_source_added.sh
```

After switching from the input menu, use:

```bash
scripts/wait_squirrel_typing_ready.sh
```

The source-added gate waits until the current user's HIToolbox and third-party
input-source lists both include Squirrel. The typing-ready gate waits until
`im.rime.inputmethod.Squirrel.Hans selected=true`, then confirms the sidecar
health and configured local model lane.

After that, run the combined machine gate:

```bash
python3 -m rag_ime.cli \
  --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" \
  squirrel-tryout-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --report-path /tmp/rag-ime-squirrel-tryout-report.json
```

This gate is intentionally read-only. It verifies the selected input source,
the installed `Squirrel.app`, the actual Rime managed config, default simplified
schema/page-size settings in `default.custom.yaml` and compiled
`build/default.yaml`, required `~/Library/Rime/build` artifacts, the user
LaunchAgent, sidecar health, the `/rime-suggest` sidecar payload, and the
backend/Rime-sidecar quality gate.
It does not install, enable, switch, select a side candidate, or drive the GUI.

Strict Squirrel doctor mode also checks the mixed candidate contract. With
`RAG_IME_DOCTOR_REQUIRE_TRYOUT=1`, it requires the sidecar probe to return
shared selection keys/ranks and a side-first display list where LLM candidates
use `displayLayout=inline` and RAG/memory sentence candidates use
`displayLayout=block`. This proves the backend/native payload contract before
manual foreground typing; it still does not prove that the visible AppKit panel
looked correct in a real editor.

Manual continuous-use verification:

1. Run `scripts/open_squirrel_input_source_settings.sh --wait`.
2. In System Settings, add Squirrel from Chinese, Simplified if it is not present.
3. Select Squirrel from the macOS input menu and wait for `scripts/wait_squirrel_typing_ready.sh` to pass.
4. Run `squirrel-tryout-gate` and keep `/tmp/rag-ime-squirrel-tryout-report.json`.
5. Run the foreground AppKit trace gate:

```bash
scripts/verify_squirrel_foreground_trace.sh
```

6. In the opened editor, type at least one semantic pinyin prefix such as `er qi`
   and accept a side sentence candidate with `6`, `7`, or `8`.
7. For a longer manual pass, type at least 20 mixed Chinese/English prompts.
8. Confirm normal Rime candidates remain available as fallback when side candidates do not fill the panel.
9. Confirm side candidates are side-first when available: short LLM/model
   candidates fill the first horizontal row, RAG/memory sentence candidates start
   below as vertical rows, and native Rime candidates appear only after remaining
   side slots are exhausted.
10. If you need to inspect an existing trace without reopening the foreground
    test file, run the lower-level checker:

```bash
python3 scripts/check_squirrel_frontend_trace.py \
  --require-mixed-panel \
  --require-side-commit \
  --print-last 8
```

Or make the strict doctor require the same foreground evidence after manual
typing:

```bash
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 \
RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE=1 \
RAG_IME_DOCTOR_FRONTEND_TRACE_WAIT=30 \
RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify \
  scripts/doctor_squirrel_integration.sh
```

The trace file is local-only at `~/Library/Logs/RagIme/squirrel-frontend.jsonl`
and is enabled by `rag_ime/frontend_trace: true` in the managed Squirrel config.
It is the repeatable evidence that the installed AppKit frontend actually used
the sidecar display candidates: `panel_display_candidates` must show
`modelInline > 0`, `ragBlock > 0`, and `forcesHorizontalLayout=true`, while
`panel_text_layout` must show space separators between model candidates and a
newline before the first sentence candidate. After a number-key accept,
`side_candidate_commit` proves the visible key routed through RAG-IME rather
than native Rime selection.

If the project opens in Xcode but the script fails, inspect the exact
`xcodebuild` output first; the wrapper checks the patched files and config before
entering Xcode build proper.
