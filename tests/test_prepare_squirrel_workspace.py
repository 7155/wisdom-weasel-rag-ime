from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class PrepareSquirrelWorkspaceScriptTests(unittest.TestCase):
    def test_prepare_squirrel_workspace_dry_run_reports_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-prepare-") as tmp:
            workdir = Path(tmp) / "squirrel"
            env = {
                **os.environ,
                "RAG_IME_SQUIRREL_DRY_RUN": "1",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SIDECAR_PORT": "18766",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn(f"workdir={workdir}", result.stdout)
        self.assertIn("base_ref=2158538", result.stdout)
        self.assertIn("sidecar_url=http://127.0.0.1:18766/api", result.stdout)
        self.assertIn(f"repo_root={root}", result.stdout)


if __name__ == "__main__":
    unittest.main()
