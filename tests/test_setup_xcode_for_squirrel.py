from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


class SetupXcodeForSquirrelScriptTests(unittest.TestCase):
    def test_setup_script_is_syntax_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        subprocess.run(
            ["bash", "-n", str(root / "scripts" / "setup_xcode_for_squirrel.sh")],
            cwd=root,
            check=True,
        )

    def test_setup_script_reports_host_state_without_installing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "RAG_IME_INSTALL_XCODE": "0",
            "RAG_IME_XCODE_INSTALL_DIR": str(root / "build" / "missing-xcode-test"),
        }
        result = subprocess.run(
            ["bash", str(root / "scripts" / "setup_xcode_for_squirrel.sh")],
            cwd=root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("== Host State ==", result.stdout)
        self.assertIn("fastlane_session:", result.stdout)
        self.assertIn("== Disk Space ==", result.stdout)
        self.assertIn("minimum_free_gib:", result.stdout)
        self.assertIn("== Installed Xcodes ==", result.stdout)
        if "== Install Help ==" in result.stdout:
            self.assertIn("RAG_IME_INSTALL_XCODE", result.stdout)
        else:
            self.assertIn("== Detected Xcode ==", result.stdout)
            self.assertIn("project-local xcodebuild check:", result.stdout)
            self.assertIn("== System Configuration ==", result.stdout)


if __name__ == "__main__":
    unittest.main()
