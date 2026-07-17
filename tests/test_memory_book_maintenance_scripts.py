from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_role_book import AgentRoleBookStore
from rag_ime.personal_context import AgentMemoryEvidenceStore


@unittest.skipUnless(sys.platform == "darwin", "requires macOS LaunchAgent tools")
class MemoryBookMaintenanceScriptTests(unittest.TestCase):
    def test_install_memory_book_maintenance_launch_agent_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
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
                    "RAG_IME_PERSONAL_CONTEXT_APPLY_SAFE_RECENT_WORK": "1",
                    "RAG_IME_PERSONAL_CONTEXT_INTERVAL_SECONDS": "900",
                    "RAG_IME_PERSONAL_CONTEXT_BATCH_LIMIT": "25",
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
        self.assertEqual(env_vars["RAG_IME_PERSONAL_CONTEXT_MAINTENANCE_ENABLED"], "1")
        self.assertEqual(
            env_vars["RAG_IME_PERSONAL_CONTEXT_APPLY_SAFE_RECENT_WORK"],
            "1",
        )
        self.assertEqual(env_vars["RAG_IME_PERSONAL_CONTEXT_INTERVAL_SECONDS"], "900")
        self.assertEqual(env_vars["RAG_IME_PERSONAL_CONTEXT_BATCH_LIMIT"], "25")

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
        self.assertEqual(
            payload["EnvironmentVariables"][
                "RAG_IME_PERSONAL_CONTEXT_APPLY_SAFE_RECENT_WORK"
            ],
            "0",
        )

    def test_memory_book_runner_uses_non_overlapping_lock_and_standalone_apply_is_explicit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "run_memory_book_maintenance_once.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_MEMORY_BOOK_MAINTENANCE_LOCK_DIR", source)
        self.assertIn("maintenance_lock_held", source)
        self.assertIn("trap cleanup_lock EXIT INT TERM", source)
        self.assertIn('APPLY="${RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY:-0}"', source)
        self.assertIn('RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS="${RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS:-2048}"', source)
        self.assertIn("--save-draft", source)
        self.assertIn('"reviewRequired": applied != "true"', source)
        self.assertIn('if [[ "$APPLY" == "1"', source)
        self.assertIn("personal-context-maintenance-run", source)
        self.assertIn("--report-path \"$PERSONAL_CONTEXT_LOG\"", source)
        self.assertIn("PERSONAL_CONTEXT_STATUS=$?", source)
        self.assertIn('"personalContextMaintenance": personal_context', source)

    def test_scheduled_runner_executes_personal_context_even_when_memory_book_is_not_due(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-maintenance-runner-") as tmp:
            base = Path(tmp)
            app_support = base / "app-support"
            runs_dir = base / "runs"
            db_path = app_support / "rag-ime.sqlite"
            role_books = AgentRoleBookStore(db_path)
            role_books.initialize()
            role_books.ensure_seeded(
                "architect",
                "role-v1",
                display_name="架构角色",
                mission="维护个人上下文",
                created_at_ms=10,
            )
            evidence = AgentMemoryEvidenceStore(db_path, project="project-a")
            evidence.initialize()
            evidence.record_work_receipt(
                work_item_id="work:scheduled",
                receipt_id="receipt:scheduled",
                role_id="architect",
                text="定时入口生成个人上下文草案",
                occurred_at_ms=100,
            )
            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "run_memory_book_maintenance_once.sh"),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_APP_SUPPORT_DIR": str(app_support),
                    "RAG_IME_DB_PATH": str(db_path),
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_DIR": str(runs_dir),
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER": "scheduled",
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_PROJECT": "project-a",
                },
                check=True,
                text=True,
                capture_output=True,
            )
            report_files = list(runs_dir.glob("personal-context-*.json"))

        payload = json.loads(result.stdout)
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["personalContextMaintenanceExitCode"], 0)
        self.assertTrue(payload["personalContextMaintenance"]["ok"])
        self.assertTrue(payload["personalContextMaintenance"]["draftOnly"])
        self.assertEqual(
            payload["personalContextMaintenance"]["summary"]["targetCount"],
            1,
        )
        target = payload["personalContextMaintenance"]["targets"][0]
        self.assertEqual(target["runStatus"], "succeeded")
        self.assertTrue(target["artifacts"]["digestId"])
        self.assertTrue(target["artifacts"]["userMemoryDraftId"])
        self.assertTrue(target["artifacts"]["roleBookDraftId"])
        self.assertEqual(target["artifacts"]["appliedRoleBookRevisionId"], "")
        self.assertEqual(len(report_files), 1)


if __name__ == "__main__":
    unittest.main()
