from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


class MemoryBookMaintenanceScriptTests(unittest.TestCase):
    def test_install_memory_book_maintenance_launch_agent_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-book-agent-") as tmp:
            home = Path(tmp) / "home"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_memory_book_maintenance_launch_agent.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_DEEPSEEK_ENV": str(root / ".rag-ime-data" / "deepseek.env"),
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_INTERVAL_SECONDS": "900",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.memory-book-maintenance.plist"
            payload = plistlib.loads(plist_path.read_bytes())

        self.assertIn(str(plist_path), result.stdout)
        self.assertEqual(payload["Label"], "com.rag-ime.memory-book-maintenance")
        self.assertEqual(payload["StartInterval"], 900)
        self.assertFalse(payload["RunAtLoad"])
        self.assertFalse(payload["KeepAlive"])
        self.assertIn("run_memory_book_maintenance_once.sh", payload["ProgramArguments"][-1])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_REASONING_EFFORT"], "low")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS"], "2048")
        self.assertNotIn("RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY", env_vars)

    def test_memory_book_runner_uses_non_overlapping_lock_and_apply_is_opt_in(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "run_memory_book_maintenance_once.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_MEMORY_BOOK_MAINTENANCE_LOCK_DIR", source)
        self.assertIn("maintenance_lock_held", source)
        self.assertIn("trap cleanup_lock EXIT INT TERM", source)
        self.assertIn('APPLY="${RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY:-0}"', source)
        self.assertIn('RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS="${RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS:-2048}"', source)
        self.assertIn('if [[ "$APPLY" == "1"', source)


if __name__ == "__main__":
    unittest.main()
