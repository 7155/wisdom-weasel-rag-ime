from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.management_service import ManagementService
from rag_ime.management_work_contract import ManagementWorkError
from rag_ime.models import InputEvent
from rag_ime.runtime_config import RuntimeConfigResolver
from rag_ime.settings_store import ManagementSettingsStore


ROOT = Path(__file__).resolve().parents[1]


class HistoryDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-history-detail-")
        self.db_path = Path(self.tmp.name) / "history.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.settings = ManagementSettingsStore(self.db_path)
        self.settings.initialize()
        resolver = RuntimeConfigResolver(self.settings, environ={})
        self.management = ManagementService(
            db_path=self.db_path,
            project="wisdom-weasel-rag-ime",
            repo_root=ROOT,
            settings_store=self.settings,
            health_provider=lambda: {"ok": True},
            input_source_provider=lambda: {},
            predictor_provider=lambda: {},
            runtime_config_provider=resolver.resolve,
        )
        event_ref = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_200_000,
                source="voice",
                committed_text="服务端保存的完整语音输入",
                privacy_disposition="allowed",
                recent_context="详情响应不能泄露这段上下文",
                preedit="sensitive-preedit",
                app="com.openai.codex",
                project="wisdom-weasel-rag-ime",
                candidate_rank=1,
                provider_name="volcengine-asr",
                context_group_id="document:test",
                context_group_level="document",
            )
        )
        self.event_id = int(event_ref.split(":", 1)[1])

    def tearDown(self) -> None:
        self.management.close()
        self.tmp.cleanup()

    def test_reads_one_real_event_and_verified_feedback_without_context_fields(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_state
                SET accepted_count = 2, skipped_count = 1, pinned = 1,
                    downranked = 0, updated_at_ms = ?
                WHERE event_id = ?
                """,
                (1_900_000_200_010, self.event_id),
            )
            conn.execute(
                """
                INSERT INTO memory_actions(
                    created_at_ms, memory_id, event_id, action_type,
                    query, suggestion_id, metadata_json
                ) VALUES (?, ?, ?, 'accept', '', '', '{}')
                """,
                (1_900_000_200_010, f"event:{self.event_id}", self.event_id),
            )

        detail = self.management.history_detail(self.event_id)

        self.assertTrue(detail["ok"])
        self.assertTrue(detail["rawTextVisible"])
        self.assertEqual(detail["item"]["text"], "服务端保存的完整语音输入")
        self.assertEqual(detail["item"]["provider"], "volcengine-asr")
        self.assertEqual(detail["item"]["feedback"]["acceptedCount"], 2)
        self.assertEqual(detail["item"]["feedback"]["latestAction"], "accept")
        for forbidden in ("recentContext", "preedit", "tags", "prompt", "reasoning"):
            self.assertNotIn(forbidden, detail["item"])

    def test_rejects_invalid_ids_and_reports_missing_events(self) -> None:
        with self.assertRaises(ManagementWorkError):
            self.management.history_detail("1 OR 1=1")
        with self.assertRaises(ManagementWorkError):
            self.management.history_detail(0)

        missing = self.management.history_detail(9_000_000)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["errorCode"], "not_found")


if __name__ == "__main__":
    unittest.main()
