from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.memory_models import ImeQueryContext
from rag_ime.memory_schema_v2 import ensure_memory_v2_schema, memory_v2_table_names
from rag_ime.models import InputEvent


class MemorySchemaV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-v2-schema-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _approve_phrase(self, event_token: str, text: str) -> None:
        event_id = int(event_token.split(":", 1)[1])
        plan = memory_book_plan_from_compile_output(
            {
                "phraseCandidates": [
                    {
                        "text": text,
                        "sourceEventIds": [event_id],
                        "tags": ["输入法短语"],
                        "weight": 0.8,
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            apply_memory_book_plan(conn, plan)

    def test_initialize_creates_v2_tables_repeatably(self) -> None:
        self.core.initialize()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        for table_name in memory_v2_table_names():
            self.assertIn(table_name, names)

    def test_feedback_schema_is_order_independent_and_keeps_legacy_defaults(self) -> None:
        alternate_path = Path(self.tmp.name) / "v2-first.sqlite"
        with closing(sqlite3.connect(alternate_path)) as conn, conn:
            ensure_memory_v2_schema(conn)
        LocalSqliteCoreClient(alternate_path).initialize()

        with closing(sqlite3.connect(alternate_path)) as conn, conn:
            columns = {str(row[1]): row for row in conn.execute("PRAGMA table_info(memory_feedback_events)")}
            self.assertEqual(columns["candidate_text"][4], "''")
            self.assertEqual(columns["candidate_source"][4], "'unknown'")
            conn.execute(
                "INSERT INTO memory_feedback_events(id, candidate_id, action, created_at_ms) VALUES (?, ?, ?, ?)",
                ("feedback:defaults", "candidate:1", "skipped", 1),
            )
            row = conn.execute(
                "SELECT candidate_text, candidate_source FROM memory_feedback_events WHERE id = ?",
                ("feedback:defaults",),
            ).fetchone()
        self.assertEqual(row, ("", "unknown"))

    def test_record_event_stays_hidden_until_dsv4_compiles_a_phrase(self) -> None:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_000,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="我们在做 sequenceFork 的输入法实验",
                project="wisdom-weasel-rag-ime",
                app="com.apple.TextEdit",
                tags=("source-metadata", "sequenceFork"),
            )
        )
        self.assertTrue(memory_id.startswith("event:"))
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            raw = conn.execute(
                "SELECT id, status, metadata_json FROM memory_items WHERE memory_id = ?",
                ("raw:event:1",),
            ).fetchone()
            self.assertIsNotNone(raw)
            self.assertEqual(raw["status"], "hidden")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_items_fts WHERE rowid = ?", (raw["id"],)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_item_vectors WHERE memory_item_id = ?", (raw["id"],)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_item_tags WHERE memory_item_id = ?", (raw["id"],)).fetchone()[0],
                0,
            )
            self.assertIn("source_tags", raw["metadata_json"])
            self.assertIsNone(
                conn.execute("SELECT id FROM memory_items WHERE memory_id = ?", ("phrase:连续预测",)).fetchone()
            )

        self._approve_phrase(memory_id, "连续预测")
        payload = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=10)
        memory_ids = {item["memoryId"] for item in payload["items"]}
        self.assertIn("raw:event:1", memory_ids)
        self.assertIn("phrase:连续预测", memory_ids)

    def test_sensitive_event_does_not_become_direct_phrase_candidate(self) -> None:
        phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_001,
                source="manual",
                committed_text="Bearer sk-secret-value",
                privacy_disposition="allowed",
                recent_context="敏感 token",
                project="wisdom-weasel-rag-ime",
            )
        )
        payload = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=10)
        sensitive = next(item for item in payload["items"] if item["memoryId"] == f"raw:{phrase_event}")
        self.assertEqual(sensitive["text"], "[REDACTED]")
        self.assertEqual(sensitive["status"], "hidden")
        self.assertNotIn("Bearer sk-secret-value", str(payload))
        self.assertFalse(any(item["memoryId"].startswith("phrase:") for item in payload["items"]))

    def test_retrieve_candidates_v2_prefers_phrase_memory_and_filters_raw_echo(self) -> None:
        phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_002,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="sequenceFork 连续预测",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory", "sequenceFork"),
            )
        )
        self._approve_phrase(phrase_event, "连续预测")
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_003,
                source="manual",
                committed_text="这是一个很长的历史输入句子，不应该直接复读出来",
                privacy_disposition="allowed",
                recent_context="连续预测",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        payload = self.core.retrieve_candidates_v2(
            context=ImeQueryContext(
                current_input="连续",
                recent_context="sequenceFork",
                project="wisdom-weasel-rag-ime",
                top_k=3,
            )
        )
        texts = [item["text"] for item in payload["candidates"]]
        self.assertIn("连续预测", texts)
        self.assertNotIn("这是一个很长的历史输入句子，不应该直接复读出来", texts)

    def test_suggest_for_input_falls_back_to_v2_phrase_memory_when_legacy_is_empty(self) -> None:
        phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_004,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(phrase_event, "连续预测")
        suggestions = self.core.suggest_for_input(
            current_input="我想继续写连续 连续",
            recent_context="我想继续写连续",
            project="wisdom-weasel-rag-ime",
            top_k=2,
        )
        self.assertEqual([item.surface_text for item in suggestions], ["连续预测"])
        self.assertEqual(suggestions[0].metadata.get("memory_id"), "phrase:连续预测")

    def test_suggest_for_input_prefers_v2_compiled_phrase_over_legacy_raw_history_echo(self) -> None:
        phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_005,
                source="manual",
                committed_text="这是一个很长的历史输入句子，里面一直在讲候选展示方式和排序细节，不应该直接整段复读出来",
                privacy_disposition="allowed",
                recent_context="用户之前的大段抱怨",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_006,
                source="manual",
                committed_text="设计一个候选展示方式",
                privacy_disposition="allowed",
                recent_context="Prediction-first RAG IME",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(phrase_event, "设计一个候选展示方式")

        suggestions = self.core.suggest_for_input(
            current_input="候选展示",
            recent_context="我想继续写候选展示",
            project="wisdom-weasel-rag-ime",
            top_k=3,
        )

        self.assertEqual(suggestions[0].surface_text, "设计一个候选展示方式")
        self.assertFalse(any(item.surface_text.startswith("这是一个很长的历史输入句子") for item in suggestions))

    def test_suggest_for_input_respects_tombstone_for_legacy_phrase_memory(self) -> None:
        first_phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_007,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        second_phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_008,
                source="manual",
                committed_text="连续补齐",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(first_phrase_event, "连续预测")
        self._approve_phrase(second_phrase_event, "连续补齐")
        self.core.add_memory_tombstone(
            target_type="normalized_text",
            target_value="连续预测",
            reason="manual-test",
        )

        suggestions = self.core.suggest_for_input(
            current_input="连续",
            recent_context="我想继续写连续",
            project="wisdom-weasel-rag-ime",
            top_k=3,
        )

        self.assertEqual(suggestions[0].surface_text, "连续补齐")
        self.assertNotIn("连续预测", [item.surface_text for item in suggestions])

    def test_suggest_for_input_respects_repeated_skip_suppression_for_legacy_phrase_memory(self) -> None:
        first_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_009,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        second_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_010,
                source="manual",
                committed_text="连续补齐",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(first_id, "连续预测")
        self._approve_phrase(second_id, "连续补齐")
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": first_id,
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:test-legacy-skip",
                "timestampMs": 1,
            }
        )
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": first_id,
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:test-legacy-skip",
                "timestampMs": 2,
            }
        )

        suggestions = self.core.suggest_for_input(
            current_input="连续",
            recent_context="我想继续写连续",
            project="wisdom-weasel-rag-ime",
            top_k=3,
        )

        self.assertEqual(suggestions[0].surface_text, "连续补齐")
        self.assertNotIn("连续预测", [item.surface_text for item in suggestions])

    def test_retrieve_candidates_v2_respects_repeated_skip_suppression(self) -> None:
        first_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_011,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        second_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_012,
                source="manual",
                committed_text="连续补齐",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(first_id, "连续预测")
        self._approve_phrase(second_id, "连续补齐")
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": first_id,
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:test-v2-skip",
                "timestampMs": 3,
            }
        )
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": first_id,
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:test-v2-skip",
                "timestampMs": 4,
            }
        )

        payload = self.core.retrieve_candidates_v2(
            context=ImeQueryContext(
                current_input="连续",
                recent_context="我想继续写连续",
                project="wisdom-weasel-rag-ime",
                top_k=3,
            )
        )

        texts = [item["text"] for item in payload["candidates"]]
        self.assertIn("连续补齐", texts)
        self.assertNotIn("连续预测", texts)

    def test_retrieve_candidates_v2_never_surfaces_status_tombstoned_item(self) -> None:
        first_phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_013,
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        second_phrase_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_014,
                source="manual",
                committed_text="连续补齐",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要更好的候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self._approve_phrase(first_phrase_event, "连续预测")
        self._approve_phrase(second_phrase_event, "连续补齐")
        self.core.add_memory_tombstone(
            target_type="memory_id",
            target_value="phrase:连续预测",
            reason="manual-test",
        )
        self.core.v2_governance_filter_enabled = False

        payload = self.core.retrieve_candidates_v2(
            context=ImeQueryContext(
                current_input="连续",
                recent_context="我想继续写连续",
                project="wisdom-weasel-rag-ime",
                top_k=3,
            )
        )
        inspect_payload = self.core.inspect_memory_v2(status="tombstoned", project="wisdom-weasel-rag-ime", limit=10)

        tombstoned_ids = {item["memoryId"] for item in inspect_payload["items"]}
        texts = [item["text"] for item in payload["candidates"]]
        self.assertIn("raw:event:1", tombstoned_ids)
        self.assertIn("phrase:连续预测", tombstoned_ids)
        self.assertIn("连续补齐", texts)
        self.assertNotIn("连续预测", texts)
