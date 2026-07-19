from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin", "requires macOS LaunchAgent tools")
class MemoryBookMaintenanceScriptTests(unittest.TestCase):
    def test_install_memory_book_maintenance_launch_agent_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = (
            root / "scripts" / "install_memory_book_maintenance_launch_agent.sh"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-book-agent-") as tmp:
            home = Path(tmp) / "home"
            model_env = Path(tmp) / "source-deepseek.env"
            model_env.write_text("DEEPSEEK_API_KEY=fake\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_memory_book_maintenance_launch_agent.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_DEEPSEEK_ENV": str(model_env),
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_INTERVAL_SECONDS": "900",
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.memory-book-maintenance.plist"
            payload = plistlib.loads(plist_path.read_bytes())
            app_dir = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "components"
                / "memory-book-maintenance"
            )
            installed_files = {
                "wrapper": (app_dir / "memory_book_maintenance_launch.py").is_file(),
                "runner": (app_dir / "scripts" / "run_memory_book_maintenance_once.sh").is_file(),
                "package": (app_dir / "rag_ime" / "cli.py").is_file(),
                "marker": (app_dir / "rag-ime-install-marker.json").is_file(),
            }

        self.assertIn(str(plist_path), result.stdout)
        self.assertEqual(payload["Label"], "com.rag-ime.memory-book-maintenance")
        self.assertEqual(payload["StartInterval"], 900)
        self.assertFalse(payload["RunAtLoad"])
        self.assertFalse(payload["KeepAlive"])
        self.assertTrue(payload["ProgramArguments"][-1].endswith("memory_book_maintenance_launch.py"))
        self.assertEqual(payload["WorkingDirectory"], str(app_dir))
        self.assertTrue(installed_files["wrapper"])
        self.assertTrue(installed_files["runner"])
        self.assertTrue(installed_files["package"])
        self.assertTrue(installed_files["marker"])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_ROOT"], str(app_dir))
        self.assertEqual(env_vars["RAG_IME_INSTALL_MARKER"], str(app_dir / "rag-ime-install-marker.json"))
        self.assertEqual(env_vars["RAG_IME_SOURCE_ROOT"], str(root))
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_REASONING_EFFORT"], "low")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS"], "2048")
        self.assertTrue(env_vars["RAG_IME_DEEPSEEK_ENV"].endswith("Application Support/RagIme/deepseek.env"))
        self.assertEqual(env_vars["RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY"], "0")
        self.assertEqual(env_vars["RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE"], "0")
        self.assertEqual(env_vars["RAG_IME_PERSONAL_CONTEXT_BATCH_LIMIT"], "500")
        self.assertNotIn("RAG_IME_OWNER_MEMORY_INTERVAL_SECONDS", env_vars)
        self.assertNotIn("RAG_IME_PERSONAL_CONTEXT_INTERVAL_SECONDS", env_vars)
        self.assertLess(
            installer.rindex("launchctl enable"),
            installer.rindex("launchctl bootstrap"),
        )

    def test_install_discovers_existing_app_support_model_env(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-book-env-") as tmp:
            home = Path(tmp) / "home"
            app_support = home / "Library" / "Application Support" / "RagIme"
            app_support.mkdir(parents=True)
            (app_support / "deepseek.env").write_text("DEEPSEEK_API_KEY=fake\n", encoding="utf-8")
            subprocess.run(
                ["bash", str(root / "scripts" / "install_memory_book_maintenance_launch_agent.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_DEEPSEEK_ENV": "",
                    "RAG_IME_MODEL_ENV": "",
                },
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.memory-book-maintenance.plist"
            payload = plistlib.loads(plist_path.read_bytes())

        self.assertEqual(
            payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_ENV"],
            str(app_support / "deepseek.env"),
        )

    def test_memory_book_runner_uses_non_overlapping_lock_and_standalone_apply_is_explicit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "run_memory_book_maintenance_once.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_MEMORY_BOOK_MAINTENANCE_LOCK_DIR", source)
        self.assertIn("RAG_IME_MEMORY_BOOK_MAINTENANCE_STALE_LOCK_SECONDS", source)
        self.assertIn("owner.pid", source)
        self.assertIn('mv "$LOCK_DIR" "$stale_lock_dir"', source)
        self.assertIn("maintenance_lock_held", source)
        self.assertIn("trap cleanup_lock EXIT INT TERM", source)
        self.assertIn('APPLY="${RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY:-0}"', source)
        self.assertIn(
            'LEGACY_MAINTENANCE="${RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE:-0}"',
            source,
        )
        self.assertIn('RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS="${RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS:-2048}"', source)
        self.assertIn("--save-draft", source)
        self.assertIn('"mode": "owner_scoped"', source)
        self.assertIn("--managed-memory-settings", source)
        self.assertNotIn("owner_cmd+=(--no-auto-apply)", source)
        self.assertNotIn("--interval-seconds \"$OWNER_INTERVAL_SECONDS\"", source)
        self.assertIn(
            '"reviewRequired": any(bool(item.get("reviewRequired")) for item in results)',
            source,
        )
        self.assertIn('payload["storedDraft"] = bool(preview.get("storedDraft"))', source)
        self.assertIn('payload["reviewRequired"] = payload["storedDraft"] and applied != "true"', source)
        self.assertIn('if [[ "$APPLY" == "1"', source)
        self.assertIn("personal-context-maintenance-run", source)
        self.assertIn('PERSONAL_CONTEXT_LOG="$OUT_DIR/personal-context-$STAMP.json"', source)
        self.assertNotIn("-m rag_ime.codex_memory_source", source)
        self.assertNotIn("codexMemoryImport", source)


if __name__ == "__main__":
    unittest.main()
