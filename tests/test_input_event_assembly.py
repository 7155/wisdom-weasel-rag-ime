from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rag_ime.input_event_assembly import assemble_input_rows, recent_complete_input_context
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent


class InputEventAssemblyTests(unittest.TestCase):
    def test_adjacent_rime_fragments_become_one_complete_input(self) -> None:
        rows = [
            {
                "id": index,
                "created_at_ms": 1_000 + index * 500,
                "source": "squirrel_rime_commit_burst",
                "committed_text": text,
                "recent_context": "",
                "app": "com.openai.codex",
                "project": "wisdom-weasel-rag-ime",
                "context_group_id": "codex-thread",
                "context_group_level": "document",
            }
            for index, text in enumerate(("我", "今天", "完成", "了输入法测试"), start=1)
        ]

        records = assemble_input_rows(rows)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "我今天完成了输入法测试")
        self.assertEqual(records[0]["sourceEventIds"], [1, 2, 3, 4])
        self.assertTrue(records[0]["complete"])

    def test_dynamic_budget_can_select_more_than_twenty_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-recent-context-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            for index in range(30):
                _record(core, f"最近完整输入第 {index + 1} 条，包含可检索的完整语义。", created_at_ms=10_000 + index)
            with core._connect() as conn:
                result = recent_complete_input_context(
                    conn,
                    baseline_records=10,
                    max_records=40,
                    token_budget=16_384,
                    reserved_tokens=512,
                )

        self.assertEqual(result["observability"]["baselineRecordCount"], 10)
        self.assertEqual(result["observability"]["selectedRecordCount"], 30)
        self.assertIn("第 1 条", result["rendered"])
        self.assertIn("第 30 条", result["rendered"])

    def test_explicit_yesterday_query_uses_yesterday_window(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-yesterday-context-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            now = datetime.now().astimezone()
            yesterday = now - timedelta(days=1)
            _record(core, "昨天完成了 RAG 上下文修复。", created_at_ms=int(yesterday.timestamp() * 1000))
            _record(core, "今天继续做配置备份。", created_at_ms=int(now.timestamp() * 1000))
            with core._connect() as conn:
                result = recent_complete_input_context(conn, query_text="我昨天做了什么？")

        self.assertIn("昨天完成了 RAG 上下文修复", result["rendered"])
        self.assertNotIn("今天继续做配置备份", result["rendered"])
        self.assertEqual(result["observability"]["temporalWindow"]["label"], "昨天")
        self.assertTrue(result["observability"]["explicitTemporalQuery"])

    def test_long_complete_input_is_not_cut_to_twenty_characters(self) -> None:
        text = "这是一条用于验证上下文完整性的输入，" + "包含完整工程背景和后续约束。" * 12
        with tempfile.TemporaryDirectory(prefix="rag-ime-long-context-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            _record(core, text, created_at_ms=20_000)
            with core._connect() as conn:
                result = recent_complete_input_context(
                    conn,
                    token_budget=8_192,
                    reserved_tokens=512,
                )

        self.assertEqual(result["records"][0]["text"], text)
        self.assertGreater(len(result["records"][0]["text"]), 100)
        self.assertFalse(result["records"][0].get("truncated", False))


def _record(core: LocalSqliteCoreClient, text: str, *, created_at_ms: int) -> None:
    core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=created_at_ms,
            source="manual",
            committed_text=text,
            privacy_disposition="allowed",
            project="wisdom-weasel-rag-ime",
            app="com.openai.codex",
        )
    )


if __name__ == "__main__":
    unittest.main()
