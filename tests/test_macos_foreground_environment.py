from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_macos_foreground_environment import parse_session_state, read_ioreg


class MacosForegroundEnvironmentTests(unittest.TestCase):
    def test_locked_session_and_secure_input_are_blockers(self) -> None:
        state = parse_session_state(
            '"CGSSessionScreenIsLocked"=Yes,"kCGSSessionSecureInputPID"=465'
        )

        self.assertFalse(state["ready"])
        self.assertEqual(state["screenLocked"], True)
        self.assertEqual(state["secureInputPid"], 465)
        self.assertEqual(state["blockers"], ["screen_locked", "secure_input_active"])

    def test_unlocked_session_without_secure_input_is_ready(self) -> None:
        state = parse_session_state('"CGSSessionScreenIsLocked"=No')

        self.assertTrue(state["ready"])
        self.assertEqual(state["screenLocked"], False)
        self.assertEqual(state["secureInputPid"], 0)

    def test_missing_lock_key_is_warning_not_false_blocker(self) -> None:
        state = parse_session_state('"IOConsoleUsers"=({"kCGSessionLoginDoneKey"=Yes})')

        self.assertTrue(state["ready"])
        self.assertEqual(state["screenLocked"], None)
        self.assertEqual(state["blockers"], [])
        self.assertEqual(state["warnings"], ["screen_lock_state_unavailable"])

    def test_ioreg_invalid_utf8_does_not_abort_foreground_check(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["ioreg"],
            returncode=0,
            stdout=b'"CGSSessionScreenIsLocked"=No\xff',
            stderr=b"",
        )

        with patch("scripts.check_macos_foreground_environment.subprocess.run", return_value=completed):
            raw, source = read_ioreg("")

        self.assertEqual(source, "ioreg")
        self.assertIn('"CGSSessionScreenIsLocked"=No', raw)
        self.assertIn("\ufffd", raw)

    def test_cli_fails_closed_and_writes_report(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-foreground-env-") as tmp:
            fixture = Path(tmp) / "ioreg.txt"
            report = Path(tmp) / "report.json"
            fixture.write_text('"CGSSessionScreenIsLocked"=Yes', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "check_macos_foreground_environment.py"),
                    "--require-ready",
                    "--ioreg-file",
                    str(fixture),
                    "--report-path",
                    str(report),
                ],
                cwd=root,
                check=False,
                text=True,
                capture_output=True,
            )

            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["blockers"], ["screen_locked"])
        self.assertFalse(payload["ready"])


if __name__ == "__main__":
    unittest.main()
