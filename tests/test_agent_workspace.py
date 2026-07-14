from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

from rag_ime.agent_workspace import WorkspaceHarness, WorkspaceHarnessError


class AgentWorkspaceHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rag-ime-workspace-")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "README.md").write_text("hello 智鼬\n", encoding="utf-8")
        (self.root / ".env").write_text("API_KEY=must-not-leak\n", encoding="utf-8")
        (self.root / "state.sqlite").write_bytes(b"SQLite format 3\x00")
        nested = self.root / "src"
        nested.mkdir()
        (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.outside = Path(self.temp.name) / "outside.txt"
        self.outside.write_text("outside-secret-content", encoding="utf-8")
        (self.root / "escape").symlink_to(self.outside)
        self.session = {
            "id": "agent:coordinator",
            "mode": "coordinator",
            "workspaceRoots": [str(self.root.resolve())],
        }
        self.assistant = {
            "id": "agent:assistant",
            "mode": "assistant",
            "workspaceRoots": [],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_list_and_read_stay_inside_roots_and_hide_sensitive_files(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        listing = harness.list(self.session, {"path": str(self.root), "depth": 2})
        serialized = str(listing)

        self.assertIn("README.md", serialized)
        self.assertIn("main.py", serialized)
        self.assertNotIn(".env", serialized)
        self.assertNotIn("state.sqlite", serialized)
        read = harness.read(self.session, {"path": str(self.root / "README.md")})
        self.assertEqual(read["content"], "hello 智鼬\n")

    def test_sensitive_binary_symlink_and_outside_reads_fail_closed(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        for path in (
            self.root / ".env",
            self.root / "state.sqlite",
            self.root / "escape",
            self.outside,
        ):
            with self.subTest(path=path), self.assertRaises(WorkspaceHarnessError):
                harness.read(self.session, {"path": str(path)})

    def test_shell_requires_coordinator_and_rejects_privilege_destruction_and_secrets(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        with self.assertRaisesRegex(WorkspaceHarnessError, "coordinator"):
            harness.prepare_command(self.assistant, {"command": "pwd"})
        for command in (
            "sudo ls",
            "security find-generic-password -a user",
            "rm -rf build",
            "git reset --hard HEAD~1",
            "TOKEN=abc123 make test",
            "cat .env",
            "sqlite3 state.sqlite .dump",
            "sleep 10 &",
        ):
            with self.subTest(command=command), self.assertRaises(WorkspaceHarnessError):
                harness.prepare_command(self.session, {"command": command})

    def test_network_requires_explicit_preview_and_executor_gets_normalized_contract(self) -> None:
        captured = []

        def execute(prepared):
            captured.append(prepared)
            return {"mutationApplied": True, "exitCode": 0, "output": "ok"}

        harness = WorkspaceHarness(executor=execute)
        with self.assertRaisesRegex(WorkspaceHarnessError, "allowNetwork"):
            harness.prepare_command(self.session, {"command": "curl https://example.com"})
        prepared = harness.prepare_command(
            self.session,
            {
                "command": "curl https://example.com",
                "cwd": str(self.root),
                "timeoutSeconds": 12,
                "allowNetwork": True,
            },
        )
        preview = harness.preview(prepared)
        receipt = harness.execute(prepared)

        self.assertTrue(prepared.allow_network)
        self.assertEqual(prepared.timeout_seconds, 12)
        self.assertEqual(preview["actionPayload"]["cwd"], str(self.root.resolve()))
        self.assertEqual(receipt["exitCode"], 0)
        self.assertEqual(captured, [prepared])

    def test_missing_sandbox_never_falls_back_to_an_unsandboxed_shell(self) -> None:
        harness = WorkspaceHarness(sandbox_executable=self.root / "missing-sandbox")
        prepared = harness.prepare_command(self.session, {"command": "pwd"})
        with self.assertRaisesRegex(WorkspaceHarnessError, "refusing unsandboxed"):
            harness.execute(prepared)

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS sandbox harness")
    def test_real_harness_runs_inside_workspace_and_denies_outside_read(self) -> None:
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            self.skipTest("sandbox-exec is unavailable")
        harness = WorkspaceHarness()
        inside = harness.execute(
            harness.prepare_command(self.session, {"command": "/bin/pwd", "cwd": str(self.root)})
        )
        outside = harness.execute(
            harness.prepare_command(
                self.session,
                {"command": f"/bin/cat {self.outside}", "cwd": str(self.root)},
            )
        )

        self.assertEqual(inside["exitCode"], 0)
        self.assertIn(str(self.root.resolve()), inside["output"])
        self.assertNotEqual(outside["exitCode"], 0)
        self.assertNotIn("outside-secret-content", outside["output"])

        wildcard = harness.execute(
            harness.prepare_command(
                self.session,
                {"command": "/usr/bin/find . -type f -exec /bin/cat {} +", "cwd": str(self.root)},
            )
        )
        self.assertNotIn("must-not-leak", wildcard["output"])


if __name__ == "__main__":
    unittest.main()
