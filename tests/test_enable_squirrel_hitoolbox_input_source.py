from __future__ import annotations

import os
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


class EnableSquirrelHitoolboxInputSourceScriptTests(unittest.TestCase):
    def test_dry_run_reports_changes_without_importing_preferences(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-enable-squirrel-dry-run-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            home.mkdir()
            fake_bin = _write_fake_tools(tmp_path)
            check_script = _write_fake_check_script(tmp_path)
            calls_log = tmp_path / "calls.log"
            report_path = tmp_path / "repair-report.json"

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "enable_squirrel_hitoolbox_input_source.sh"),
                    "--dry-run",
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_TEST_CALLS_LOG": str(calls_log),
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            calls = calls_log.read_text(encoding="utf-8")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("defaults export com.apple.HIToolbox", calls)
            self.assertIn("defaults export com.apple.inputsources", calls)
            self.assertNotIn("defaults import", calls)
            self.assertIn("changed=true", result.stdout)
            self.assertIn("third_party_changed=true", result.stdout)
            self.assertIn("dry-run: no preference files imported", result.stdout)
            self.assertIn("Current strict readiness:", result.stdout)
            self.assertIn("fake readiness still failing", result.stdout)
            self.assertFalse((home / "Desktop").exists())
            self.assertEqual(report["schemaVersion"], "rag-ime.squirrel-hitoolbox-repair.v1")
            self.assertTrue(report["dryRun"])
            self.assertTrue(report["hitoolboxChanged"])
            self.assertTrue(report["thirdPartyChanged"])
            self.assertEqual(report["backups"], [])

    def test_apply_uses_direct_write_when_defaults_import_does_not_persist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-enable-squirrel-apply-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            preferences = home / "Library" / "Preferences"
            preferences.mkdir(parents=True)
            _write_initial_preferences(preferences)
            fake_bin = _write_fake_tools(tmp_path)
            check_script = _write_successful_check_script(tmp_path)
            calls_log = tmp_path / "calls.log"
            report_path = tmp_path / "repair-report.json"

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "enable_squirrel_hitoolbox_input_source.sh"),
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_TEST_CALLS_LOG": str(calls_log),
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_SQUIRREL_APP": str(tmp_path / "missing-squirrel.app"),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            inputsources = plistlib.loads((preferences / "com.apple.inputsources.plist").read_bytes())
            third_party = inputsources["AppleEnabledThirdPartyInputSources"]
            backups = sorted(desktop.glob("com.apple.inputsources.rag-ime-backup.*.plist"))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertIn("warning: defaults import did not persist com.apple.inputsources", result.stderr)
        self.assertTrue(backups)
        self.assertTrue(report["ok"])
        self.assertFalse(report["dryRun"])
        self.assertTrue(report["thirdPartyChanged"])
        self.assertTrue(report["backups"])
        self.assertEqual(report["deniedPreferenceDomains"], [])
        self.assertTrue(any(item.get("Input Mode") == "im.rime.inputmethod.Squirrel.Hans" for item in third_party))
        self.assertTrue(
            any(
                item.get("Bundle ID") == "im.rime.inputmethod.Squirrel" and "Input Mode" not in item
                for item in third_party
            )
        )


def _write_fake_tools(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    defaults = fake_bin / "defaults"
    defaults.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'echo "defaults $*" >> "$RAG_IME_TEST_CALLS_LOG"',
                'if [[ "$1" == "export" ]]; then',
                '  domain="$2"',
                '  out="$3"',
                '  /usr/bin/python3 - "$domain" "$out" <<\'PY\'',
                "import plistlib",
                "import sys",
                "domain, out = sys.argv[1:3]",
                "if domain == 'com.apple.HIToolbox':",
                "    payload = {'AppleEnabledInputSources': []}",
                "elif domain == 'com.apple.inputsources':",
                "    payload = {'AppleEnabledThirdPartyInputSources': []}",
                "else:",
                "    raise SystemExit(1)",
                "with open(out, 'wb') as handle:",
                "    plistlib.dump(payload, handle)",
                "PY",
                "  exit 0",
                "fi",
                'if [[ "$1" == "import" ]]; then',
                "  exit 0",
                "fi",
                "exit 64",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    defaults.chmod(0o755)
    return fake_bin


def _write_fake_check_script(tmp_path: Path) -> Path:
    check_script = tmp_path / "check-input-source.sh"
    check_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'echo "check $*" >> "$RAG_IME_TEST_CALLS_LOG"',
                'echo "fake readiness still failing for ${@: -1}"',
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    check_script.chmod(0o755)
    return check_script


def _write_successful_check_script(tmp_path: Path) -> Path:
    check_script = tmp_path / "check-input-source-success.sh"
    check_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'echo "check $*" >> "$RAG_IME_TEST_CALLS_LOG"',
                'echo "id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true thirdPartyEnabled=true"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    check_script.chmod(0o755)
    return check_script


def _write_initial_preferences(preferences: Path) -> None:
    with (preferences / "com.apple.HIToolbox.plist").open("wb") as handle:
        plistlib.dump({"AppleEnabledInputSources": []}, handle)
    with (preferences / "com.apple.inputsources.plist").open("wb") as handle:
        plistlib.dump({"AppleEnabledThirdPartyInputSources": []}, handle)


if __name__ == "__main__":
    unittest.main()
