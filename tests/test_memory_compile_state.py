from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import (
    apply_memory_book_plan,
    build_memory_book_source_bundle,
    memory_book_plan_from_compile_output,
    memory_compile_due,
    memory_compile_state,
    inspect_memory_book_plan,
)
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class MemoryCompileStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-compile-state-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_apply_advances_incremental_cursor_and_next_bundle_only_reads_new_events(self) -> None:
        first_id = int(self.core.record_event(self._event("完成真实前台闭环", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "phraseCandidates": [
                        {
                            "text": "完成前台闭环",
                            "sourceEventIds": [first_id],
                            "groupId": "doc:a",
                        }
                    ]
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            apply_memory_book_plan(conn, plan)
            state = memory_compile_state(conn, project="ime")
            self.assertEqual(state["lastCompiledEventId"], first_id)
            self.assertEqual(build_memory_book_source_bundle(conn, project="ime")["recentEvents"], [])

        second_id = int(self.core.record_event(self._event("限制模型调用频率", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            next_bundle = build_memory_book_source_bundle(conn, project="ime")
            self.assertEqual([item["eventId"] for item in next_bundle["recentEvents"]], [second_id])

    def test_invalid_apply_does_not_advance_cursor(self) -> None:
        self.core.record_event(self._event("保持普通拼音稳定", "doc:a"))
        with self._connect() as conn:
            before = memory_compile_state(conn, project="ime")
            with self.assertRaises(ValueError):
                apply_memory_book_plan(conn, {"schemaVersion": "bad", "runId": "bad", "diffs": []})
            after = memory_compile_state(conn, project="ime")
            self.assertEqual(after["lastCompiledEventId"], before["lastCompiledEventId"])

    def test_due_policy_supports_event_idle_daily_and_manual_triggers(self) -> None:
        self.core.record_event(self._event("保持普通拼音稳定", "doc:a"))
        with self._connect() as conn:
            self.assertEqual(memory_compile_due(conn, project="ime", manual=True)[1], "manual")
            self.assertEqual(memory_compile_due(conn, project="ime", idle_ms=20 * 60 * 1000)[1], "idle")
            due, reason, _ = memory_compile_due(conn, project="ime", current_ms=24 * 60 * 60 * 1000 + 1)
            self.assertTrue(due)
            self.assertEqual(reason, "daily")

    def test_negative_phrase_and_supersede_apply_with_source_provenance(self) -> None:
        event_id = int(self.core.record_event(self._event("旧事实需要更新", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "atomId": "atom:old",
                            "canonicalText": "旧事实",
                            "sourceEventIds": [event_id],
                            "groupId": "doc:a",
                        },
                        {
                            "atomId": "atom:new",
                            "canonicalText": "新事实",
                            "sourceEventIds": [event_id],
                            "groupId": "doc:a",
                        },
                    ],
                    "negativePhrases": [
                        {"text": "根据上述", "sourceEventIds": [event_id]}
                    ],
                    "supersedes": [
                        {"oldId": "atom:old", "newId": "atom:new", "sourceEventIds": [event_id]}
                    ],
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            self.assertTrue(inspect_memory_book_plan(plan)["ok"])
            apply_memory_book_plan(conn, plan)
            self.assertEqual(conn.execute("SELECT status FROM memory_atoms WHERE id = 'atom:old'").fetchone()[0], "superseded")
            self.assertEqual(
                conn.execute("SELECT match_value FROM memory_candidate_suppressions WHERE match_value = '根据上述'").fetchone()[0],
                "根据上述",
            )

    def test_validator_rejects_model_invented_group(self) -> None:
        event_id = int(self.core.record_event(self._event("合法 Group", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "phraseCandidates": [
                        {"text": "完成前台闭环", "sourceEventIds": [event_id], "groupId": "doc:invented"}
                    ]
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            report = inspect_memory_book_plan(plan)
            self.assertFalse(report["ok"])
            self.assertTrue(any(item["code"] == "context_group_not_in_source_bundle" for item in report["errors"]))

    @staticmethod
    def _event(text: str, group_id: str) -> InputEvent:
        return InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source="squirrel",
            committed_text=text,
            app="com.apple.TextEdit",
            project="ime",
            context_group_id=group_id,
            context_group_level="document",
        )


if __name__ == "__main__":
    unittest.main()
