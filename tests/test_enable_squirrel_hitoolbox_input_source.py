from __future__ import annotations

import os
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

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "enable_squirrel_hitoolbox_input_source.sh"),
                    "--dry-run",
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
            self.assertIn("defaults export com.apple.HIToolbox", calls)
            self.assertIn("defaults export com.apple.inputsources", calls)
            self.assertNotIn("defaults import", calls)
            self.assertIn("changed=true", result.stdout)
            self.assertIn("third_party_changed=true", result.stdout)
            self.assertIn("dry-run: no preference files imported", result.stdout)
            self.assertIn("Current strict readiness:", result.stdout)
            self.assertIn("fake readiness still failing", result.stdout)
            self.assertFalse((home / "Desktop").exists())


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


if __name__ == "__main__":
    unittest.main()
