from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin", "requires macOS input-source tools")
class CheckMacosInputSourceScriptTests(unittest.TestCase):
    def test_third_party_preferences_are_sufficient_without_legacy_hitoolbox_entries(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-check-input-source-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            _write_preferences(home, include_squirrel_hitoolbox=False, include_squirrel_third_party=True)
            fake_bin = _write_fake_swift(tmp_path)
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            env.pop("RAG_IME_SQUIRREL_INPUT_SOURCE_ID", None)
            env.pop("RAG_IME_MACOS_INPUT_SOURCE_ID", None)
            env.pop("RAG_IME_INPUT_SOURCE_BUNDLE_ID", None)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "check_macos_input_source.sh"),
                    "--require-hitoolbox-enabled",
                ],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("id=im.rime.inputmethod.Squirrel.Hans", result.stdout)
        self.assertIn("hitoolboxEnabled=false", result.stdout)
        self.assertIn("thirdPartyEnabled=true", result.stdout)
        self.assertIn("preferenceEnabled=true", result.stdout)

    def test_requires_third_party_inputsources_for_real_enabled_status(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-check-input-source-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            _write_preferences(home, include_squirrel_hitoolbox=True, include_squirrel_third_party=False)
            fake_bin = _write_fake_swift(tmp_path)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "check_macos_input_source.sh"),
                    "--require-hitoolbox-enabled",
                    "im.rime.inputmethod.Squirrel.Hans",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enabled=true selectable=true", result.stdout)
        self.assertIn("hitoolboxEnabled=true", result.stdout)
        self.assertIn("thirdPartyEnabled=false", result.stdout)

    def test_reports_ready_from_the_canonical_third_party_preference_domain(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-check-input-source-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            report_path = tmp_path / "check-report.json"
            _write_preferences(home, include_squirrel_hitoolbox=False, include_squirrel_third_party=True)
            fake_bin = _write_fake_swift(tmp_path)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "check_macos_input_source.sh"),
                    "--require-hitoolbox-enabled",
                    "--report-path",
                    str(report_path),
                    "im.rime.inputmethod.Squirrel.Hans",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertIn("hitoolboxEnabled=false", result.stdout)
        self.assertIn("thirdPartyEnabled=true", result.stdout)
        self.assertEqual(payload["schemaVersion"], "rag-ime.macos-input-source-check.v1")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["inputSourceId"], "im.rime.inputmethod.Squirrel.Hans")
        self.assertTrue(payload["requirements"]["hitoolboxEnabled"])
        self.assertFalse(payload["source"]["hitoolboxEnabled"])
        self.assertTrue(payload["source"]["thirdPartyEnabled"])
        self.assertTrue(payload["source"]["preferenceEnabled"])
        self.assertIsNone(payload["failureKind"])

    def test_duplicate_tis_records_fail_with_a_repairable_report(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-check-input-source-duplicate-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            report_path = tmp_path / "check-report.json"
            _write_preferences(home, include_squirrel_hitoolbox=False, include_squirrel_third_party=True)
            fake_bin = _write_fake_swift(tmp_path)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "check_macos_input_source.sh"),
                    "--report-path",
                    str(report_path),
                    "im.rime.inputmethod.Squirrel.Hans",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_TEST_MATCH_COUNT": "2",
                },
                text=True,
                capture_output=True,
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["failureKind"], "duplicate-input-source")
        self.assertEqual(payload["source"]["matchCount"], 2)
        self.assertIn("refresh_squirrel_input_source_registration.sh", " ".join(payload["commands"]))

    def test_report_path_explains_third_party_missing_failure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-check-input-source-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            report_path = tmp_path / "check-report.json"
            _write_preferences(home, include_squirrel_hitoolbox=True, include_squirrel_third_party=False)
            fake_bin = _write_fake_swift(tmp_path)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "check_macos_input_source.sh"),
                    "--require-hitoolbox-enabled",
                    "--report-path",
                    str(report_path),
                    "im.rime.inputmethod.Squirrel.Hans",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                text=True,
                capture_output=True,
            )
            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failureKind"], "third-party-missing")
        self.assertTrue(payload["source"]["hitoolboxEnabled"])
        self.assertFalse(payload["source"]["thirdPartyEnabled"])
        self.assertIn("System Settings", " ".join(payload["manualRequired"]))


def _write_fake_swift(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    swift = fake_bin / "swift"
    swift.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                'target="${@: -1}"',
                'count="${RAG_IME_TEST_MATCH_COUNT:-1}"',
                'echo "id=$target name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC matchCount=$count"',
                'if [[ "$count" -gt 1 ]]; then exit 5; fi',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    swift.chmod(0o755)
    return fake_bin


def _write_preferences(
    home: Path,
    *,
    include_squirrel_hitoolbox: bool,
    include_squirrel_third_party: bool,
) -> None:
    preferences = home / "Library" / "Preferences"
    preferences.mkdir(parents=True)
    hitoolbox_sources: list[dict[str, object]] = [
        {
            "InputSourceKind": "Keyboard Layout",
            "KeyboardLayout ID": 252,
            "KeyboardLayout Name": "ABC",
        }
    ]
    if include_squirrel_hitoolbox:
        hitoolbox_sources.extend(_squirrel_entries())
    with (preferences / "com.apple.HIToolbox.plist").open("wb") as handle:
        plistlib.dump({"AppleEnabledInputSources": hitoolbox_sources}, handle)

    third_party_sources: list[dict[str, object]] = []
    if include_squirrel_third_party:
        third_party_sources.extend(_squirrel_entries())
    with (preferences / "com.apple.inputsources.plist").open("wb") as handle:
        plistlib.dump({"AppleEnabledThirdPartyInputSources": third_party_sources}, handle)


def _squirrel_entries() -> list[dict[str, object]]:
    return [
        {
            "Bundle ID": "im.rime.inputmethod.Squirrel",
            "Input Mode": "im.rime.inputmethod.Squirrel.Hans",
            "InputSourceKind": "Input Mode",
        },
        {
            "Bundle ID": "im.rime.inputmethod.Squirrel",
            "InputSourceKind": "Keyboard Input Method",
        },
    ]


if __name__ == "__main__":
    unittest.main()
