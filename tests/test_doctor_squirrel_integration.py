from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DoctorSquirrelIntegrationScriptTests(unittest.TestCase):
    def test_doctor_default_mode_warns_without_sidecar_but_exits_zero(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-squirrel-") as tmp:
            env = {
                **os.environ,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("RAG-IME Squirrel integration doctor", result.stdout)
        self.assertIn("[OK] Squirrel patch exists", result.stdout)
        self.assertIn("[WARN] Squirrel workdir not prepared", result.stdout)
        self.assertIn("[WARN] HTTP sidecar is not healthy", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
