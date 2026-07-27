from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_workspace import WorkspaceHarness, WorkspaceHarnessError


class AgentWorkspaceHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rag-ime-workspace-")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "README.md").write_text("hello 澄\n", encoding="utf-8")
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
        self.assertEqual(read["content"], "hello 澄\n")

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

    def test_read_chunks_reconstruct_exact_text_within_pi_result_budget(self) -> None:
        target = self.root / "large-unicode.txt"
        original = "".join(
            f'第{index:04d}行 "quoted" \\\\ path 澄数据\n'
            for index in range(4_200)
        )
        target.write_text(original, encoding="utf-8")
        harness = WorkspaceHarness(executor=lambda prepared: {})

        offset = 0
        chunks: list[str] = []
        receipts: list[dict[str, object]] = []
        while True:
            receipt = harness.read(
                self.session,
                {
                    "path": str(target),
                    "offset": offset,
                    "limit": 65_536,
                },
            )
            receipts.append(receipt)
            content = str(receipt["content"])
            content_bytes = len(content.encode("utf-8"))
            serialized_bytes = len(
                json.dumps(
                    receipt,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self.assertLessEqual(serialized_bytes, 50 * 1024)
            self.assertLessEqual(content_bytes, 50 * 1024)
            self.assertLessEqual(int(receipt["contentLines"]), 2_000)
            self.assertEqual(receipt["contentChars"], len(content))
            self.assertEqual(receipt["contentBytes"], content_bytes)
            self.assertEqual(receipt["nextOffset"], offset + content_bytes)
            self.assertGreater(int(receipt["nextOffset"]), offset)
            chunks.append(content)
            offset = int(receipt["nextOffset"])
            if receipt["truncated"] is False:
                break
            self.assertLess(len(receipts), 20, "workspace_read did not make bounded progress")

        self.assertGreater(len(receipts), 2)
        self.assertEqual("".join(chunks), original)
        self.assertEqual(offset, len(original.encode("utf-8")))
        self.assertTrue(any(item["modelResultBounded"] is True for item in receipts))

    def test_read_uses_pi_line_limit_and_preserves_continuation(self) -> None:
        target = self.root / "many-lines.txt"
        original = "x\n" * 2_501
        target.write_text(original, encoding="utf-8")
        harness = WorkspaceHarness(executor=lambda prepared: {})

        first = harness.read(
            self.session,
            {"path": str(target), "offset": 0, "limit": 65_536},
        )
        second = harness.read(
            self.session,
            {
                "path": str(target),
                "offset": first["nextOffset"],
                "limit": 65_536,
            },
        )

        self.assertEqual(first["contentLines"], 2_000)
        self.assertEqual(first["truncatedBy"], "lines")
        self.assertEqual(first["content"], "x\n" * 2_000)
        self.assertEqual(str(first["content"]) + str(second["content"]), original)
        self.assertFalse(second["truncated"])

    def test_read_never_splits_utf8_and_rejects_invalid_boundaries(self) -> None:
        target = self.root / "unicode-boundary.txt"
        target.write_text("智智", encoding="utf-8")
        invalid = self.root / "invalid-utf8.txt"
        invalid.write_bytes(b"valid\n\xe6\x99")
        harness = WorkspaceHarness(executor=lambda prepared: {})

        first = harness.read(
            self.session,
            {"path": str(target), "offset": 0, "limit": 4},
        )
        second = harness.read(
            self.session,
            {"path": str(target), "offset": first["nextOffset"], "limit": 4},
        )
        self.assertEqual(first["content"], "智")
        self.assertEqual(first["nextOffset"], 3)
        self.assertEqual(second["content"], "智")
        self.assertFalse(second["truncated"])
        with self.assertRaisesRegex(WorkspaceHarnessError, "at least 3 bytes"):
            harness.read(
                self.session,
                {"path": str(target), "offset": 0, "limit": 1},
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "UTF-8 character boundary"):
            harness.read(
                self.session,
                {"path": str(target), "offset": 1, "limit": 4},
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "only accepts UTF-8"):
            harness.read(self.session, {"path": str(invalid), "limit": 65_536})
        with self.assertRaisesRegex(WorkspaceHarnessError, "beyond end of file"):
            harness.read(
                self.session,
                {"path": str(target), "offset": 7, "limit": 4},
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "between 1 and 65536"):
            harness.read(
                self.session,
                {"path": str(target), "limit": 65_537},
            )

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

    def test_search_is_bounded_and_skips_sensitive_binary_and_symlink_files(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        result = harness.search(self.session, {"query": "澄", "mode": "both", "limit": 10})

        self.assertEqual(result["filesScanned"], 2)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["lineNumber"], 1)
        self.assertNotIn("must-not-leak", str(result))
        self.assertNotIn("outside-secret-content", str(result))
        with self.assertRaisesRegex(WorkspaceHarnessError, "coordinator"):
            harness.search(self.assistant, {"query": "hello"})

    def test_name_search_checks_shallow_project_files_before_deep_trees(self) -> None:
        search_root = Path(self.temp.name) / "search-project"
        deep = search_root / "a-huge" / "one" / "two"
        agent_docs = search_root / "docs" / "agent"
        deep.mkdir(parents=True)
        agent_docs.mkdir(parents=True)
        (deep / "decoy.txt").write_text("not the target\n", encoding="utf-8")
        target = agent_docs / "questions.md"
        target.write_text("learning trail\n", encoding="utf-8")
        session = {
            "id": "agent:search",
            "mode": "coordinator",
            "workspaceRoots": [str(search_root.resolve())],
        }
        harness = WorkspaceHarness(executor=lambda prepared: {})

        with patch("rag_ime.agent_workspace._MAX_SEARCH_FILES", 1):
            result = harness.search(session, {"query": "questions.md", "mode": "name"})

        self.assertEqual(result["filesScanned"], 1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["path"], str(target.resolve()))

    def test_patch_preview_is_hash_bound_and_apply_is_atomic(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        path = self.root / "README.md"
        prepared = harness.prepare_patch(
            self.session,
            {"path": str(path), "oldText": "hello", "newText": "你好"},
        )
        preview = harness.patch_preview(prepared)

        self.assertIn("-hello 澄", prepared.diff)
        self.assertIn("+你好 澄", prepared.diff)
        receipt = harness.apply_patch(
            self.session,
            preview["actionPayload"],
            preview["baseState"],
        )
        self.assertEqual(path.read_text(encoding="utf-8"), "你好 澄\n")
        self.assertEqual(
            receipt["postimageSha256"],
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def test_patch_rejects_ambiguous_match_sensitive_path_and_stale_preimage(self) -> None:
        harness = WorkspaceHarness(executor=lambda prepared: {})
        path = self.root / "README.md"
        path.write_text("same same\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceHarnessError, "occurrence count"):
            harness.prepare_patch(
                self.session,
                {"path": str(path), "oldText": "same", "newText": "next"},
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "non-sensitive"):
            harness.prepare_patch(
                self.session,
                {"path": str(self.root / ".env"), "oldText": "API", "newText": "KEY"},
            )
        path.write_text("before\n", encoding="utf-8")
        prepared = harness.prepare_patch(
            self.session,
            {"path": str(path), "oldText": "before", "newText": "after"},
        )
        preview = harness.patch_preview(prepared)
        path.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceHarnessError, "changed"):
            harness.apply_patch(self.session, preview["actionPayload"], preview["baseState"])
        self.assertEqual(path.read_text(encoding="utf-8"), "changed\n")

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

        dev_null = harness.execute(
            harness.prepare_command(
                self.session,
                {"command": "/bin/sh -c 'echo ok >/dev/null'", "cwd": str(self.root)},
            )
        )
        self.assertEqual(dev_null["exitCode"], 0)

        wildcard = harness.execute(
            harness.prepare_command(
                self.session,
                {"command": "/usr/bin/find . -type f -exec /bin/cat {} +", "cwd": str(self.root)},
            )
        )
        self.assertNotIn("must-not-leak", wildcard["output"])

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS sandbox harness")
    def test_real_harness_timeout_kills_the_process_group_before_a_late_write(self) -> None:
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            self.skipTest("sandbox-exec is unavailable")
        harness = WorkspaceHarness()
        late_path = self.root / "late.txt"

        receipt = harness.execute(
            harness.prepare_command(
                self.session,
                {
                    "command": "/bin/sh -c 'sleep 2; echo late > late.txt'",
                    "cwd": str(self.root),
                    "timeoutSeconds": 1,
                },
            )
        )

        self.assertTrue(receipt["timedOut"])
        self.assertFalse(receipt["mutationApplied"])
        self.assertFalse(late_path.exists())
        time.sleep(1.25)
        self.assertFalse(late_path.exists(), "a timed-out descendant wrote after cancellation")


if __name__ == "__main__":
    unittest.main()
