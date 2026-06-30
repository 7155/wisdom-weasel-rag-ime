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
RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh
```

Then open the prepared Squirrel checkout in Xcode or build it with `xcodebuild`.
