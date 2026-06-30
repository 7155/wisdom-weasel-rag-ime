from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LaunchAgentScriptTests(unittest.TestCase):
    def test_install_sidecar_launch_agent_dry_run_writes_plist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_SIDECAR_PORT": "18766",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            self.assertIn(str(plist_path), result.stdout)
            self.assertIn("dry-run", result.stdout)
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(payload["Label"], "com.rag-ime.sidecar")
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["EnvironmentVariables"]["PYTHONPATH"], str(root))
        self.assertIn("sidecar-server", payload["ProgramArguments"])
        self.assertIn("18766", payload["ProgramArguments"])


if __name__ == "__main__":
    unittest.main()
