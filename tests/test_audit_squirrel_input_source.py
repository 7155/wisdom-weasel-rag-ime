from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.cli import _tryout_input_source_audit


class AuditSquirrelInputSourceScriptTests(unittest.TestCase):
    def test_reports_third_party_missing_without_mutating_preferences(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-input-source-audit-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            _write_preferences(home)
            check_script = _write_fake_check_script(tmp_path)
            lsregister = _write_fake_lsregister(tmp_path)
            before_hitoolbox = (home / "Library" / "Preferences" / "com.apple.HIToolbox.plist").read_bytes()
            before_inputsources = (home / "Library" / "Preferences" / "com.apple.inputsources.plist").read_bytes()

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "audit_squirrel_input_source.py"),
                    "--check-script",
                    str(check_script),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_LSREGISTER": str(lsregister),
                },
                text=True,
                capture_output=True,
            )

            after_hitoolbox = (home / "Library" / "Preferences" / "com.apple.HIToolbox.plist").read_bytes()
            after_inputsources = (home / "Library" / "Preferences" / "com.apple.inputsources.plist").read_bytes()

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["schemaVersion"], "rag-ime.macos-input-source-audit.v1")
        self.assertFalse(report["mutatesSystem"])
        self.assertEqual(report["readiness"]["state"], "third-party-missing")
        self.assertFalse(report["preferences"]["wouldChangeHitoolbox"])
        self.assertTrue(report["preferences"]["wouldChangeThirdParty"])
        self.assertEqual(report["launchServices"]["duplicatePathCount"], 1)
        self.assertEqual(before_hitoolbox, after_hitoolbox)
        self.assertEqual(before_inputsources, after_inputsources)

    def test_tryout_audit_helper_attaches_readiness_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-tryout-audit-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            _write_preferences(home)
            check_script = _write_fake_check_script(tmp_path)
            lsregister = _write_fake_lsregister(tmp_path)

            with patch.dict(os.environ, {"HOME": str(home), "RAG_IME_LSREGISTER": str(lsregister)}):
                report = _tryout_input_source_audit(
                    input_source_id="im.rime.inputmethod.Squirrel.Hans",
                    input_source_check_script=check_script,
                )

        self.assertEqual(report["schemaVersion"], "rag-ime.macos-input-source-audit.v1")
        self.assertEqual(report["readiness"]["state"], "third-party-missing")
        self.assertTrue(report["preferences"]["wouldChangeThirdParty"])
        self.assertEqual(report["launchServices"]["duplicatePathCount"], 1)


def _write_preferences(home: Path) -> None:
    preferences = home / "Library" / "Preferences"
    preferences.mkdir(parents=True)
    hitoolbox = {
        "AppleEnabledInputSources": [
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
    }
    third_party = {"AppleEnabledThirdPartyInputSources": []}
    with (preferences / "com.apple.HIToolbox.plist").open("wb") as handle:
        plistlib.dump(hitoolbox, handle)
    with (preferences / "com.apple.inputsources.plist").open("wb") as handle:
        plistlib.dump(third_party, handle)


def _write_fake_check_script(tmp_path: Path) -> Path:
    script = tmp_path / "check-input-source.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false tisSelected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true thirdPartyEnabled=false'",
                "exit 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_fake_lsregister(tmp_path: Path) -> Path:
    script = tmp_path / "lsregister"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "cat <<'EOF'",
                "---------------------------------------------------------------------------------",
                "path: /Users/undo/Library/Input Methods/Squirrel.app (0x1)",
                'identifier: "im.rime.inputmethod.Squirrel"',
                'name: "Squirrel"',
                "---------------------------------------------------------------------------------",
                "path: /tmp/old/Squirrel.app (0x2)",
                'identifier: "im.rime.inputmethod.Squirrel"',
                'name: "Squirrel"',
                "EOF",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


if __name__ == "__main__":
    unittest.main()
