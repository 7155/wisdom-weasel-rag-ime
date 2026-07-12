from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent, MemoryAction


class MemoryCleanupDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-v2-cleanup-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cleanup_plan_build_apply_and_rollback(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_010,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=1_900_000_000_011,
                memory_id="event:1",
                action_type="accepted",
                query="连续",
                metadata={"project": "wisdom-weasel-rag-ime"},
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_012,
                source="manual",
                committed_text="这是一条很长且没有被接受过的历史输入，应该在 cleanup 里被 tombstone",
                privacy_disposition="allowed",
                recent_context="输入法 old raw event",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )

        plan = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")
        ops = [item["op"] for item in plan["diffs"]]
        self.assertIn("add_stable_memory", ops)
        self.assertIn("tombstone", ops)

        applied = self.core.apply_memory_cleanup_plan(run_id=plan["runId"])
        statuses = {item["status"] for item in applied["diffs"]}
        self.assertIn("applied", statuses)

        inspect_after = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        memory_ids = {item["memoryId"] for item in inspect_after["items"]}
        self.assertIn("stable:连续预测", memory_ids)

        rolled_back = self.core.rollback_memory_cleanup_plan(run_id=plan["runId"])
        rollback_statuses = {item["status"] for item in rolled_back["diffs"]}
        self.assertIn("rolled_back", rollback_statuses)

    def test_cleanup_diff_apply_and_rollback_by_diff_id(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_020,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=1_900_000_000_021,
                memory_id="event:1",
                action_type="accepted",
                query="连续",
                metadata={"project": "wisdom-weasel-rag-ime"},
            )
        )

        plan = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")
        stored_run = self.core.list_memory_cleanup_runs(run_id=plan["runId"], limit=5)
        stable_diff = next(item for item in stored_run["items"][0]["diffs"] if item["op"] == "add_stable_memory")

        applied = self.core.apply_memory_cleanup_diff(diff_id=int(stable_diff["diffId"]))
        inspect_after = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        memory_ids = {item["memoryId"] for item in inspect_after["items"]}

        self.assertEqual(applied["schemaVersion"], "rag-ime.memory-cleanup-diff.v1")
        self.assertEqual(applied["diff"]["status"], "applied")
        self.assertIn("stable:连续预测", memory_ids)

        rolled_back = self.core.rollback_memory_cleanup_diff(diff_id=int(stable_diff["diffId"]))
        inspect_final = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        final_memory_ids = {item["memoryId"] for item in inspect_final["items"]}

        self.assertEqual(rolled_back["diff"]["status"], "rolled_back")
        self.assertNotIn("stable:连续预测", final_memory_ids)

    def test_invalid_stored_cleanup_diff_is_not_applied(self) -> None:
        with self.core._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_cleanup_runs(run_id, created_at_ms, provider, model, status, summary, metadata_json)
                VALUES ('cleanup_invalid_apply', 1, 'deepseek-v4', 'deepseek-v4-flash', 'draft', 'stable=1', '{}')
                """
            )
            conn.execute(
                """
                INSERT INTO memory_cleanup_diffs(run_id, op, target_memory_id, payload_json, status, created_at_ms, rollback_json)
                VALUES (?, 'add_stable_memory', ?, ?, 'pending', 2, '{}')
                """,
                (
                    "cleanup_invalid_apply",
                    "stable:无证据记忆",
                    json.dumps(
                        {
                            "memoryId": "stable:无证据记忆",
                            "text": "无证据记忆",
                            "project": "wisdom-weasel-rag-ime",
                            "confidence": 0.9,
                            "evidenceEventIds": [],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        with self.assertRaisesRegex(ValueError, "missing_evidence_event_ids"):
            self.core.apply_memory_cleanup_plan(run_id="cleanup_invalid_apply")

        inspect_after = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        stored_run = self.core.list_memory_cleanup_runs(run_id="cleanup_invalid_apply", limit=5)

        self.assertNotIn("stable:无证据记忆", {item["memoryId"] for item in inspect_after["items"]})
        self.assertEqual(stored_run["items"][0]["diffs"][0]["status"], "pending")
