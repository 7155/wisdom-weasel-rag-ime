# Xcode Setup For Patched Squirrel

This project builds the production macOS input method by patching Squirrel/Rime. The InputMethodKit app in this repository is only a prototype and contract harness; the real frontend needs a full Xcode installation.

## Current Local Finding

On this host, `xcode-select` pointed at:

```text
/Library/Developer/CommandLineTools
```

That is not enough for the full Squirrel build. `xcodebuild -version` fails when the active developer directory is only Command Line Tools.

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

## One Command Check

Run:

```bash
scripts/setup_xcode_for_squirrel.sh
```

The script prints:

- current macOS version;
- active `xcode-select` developer directory;
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

## Squirrel Validation

After Xcode is available:

```bash
scripts/prepare_squirrel_workspace.sh
RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh
```

Then open the prepared Squirrel checkout in Xcode or build it with `xcodebuild`.
