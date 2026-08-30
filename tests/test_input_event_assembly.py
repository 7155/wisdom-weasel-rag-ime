from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rag_ime.input_event_assembly import assemble_input_rows, recent_complete_input_context
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent


class InputEventAssemblyTests(unittest.TestCase):
    def test_codex_history_is_disabled_without_explicit_memory_opt_in(self) -> None:
        rows = [
            {
                "id": 1,
                "created_at_ms": 1_000,
                "source": "codex_history",
                "committed_text": "我继续按计划检查代码。",
                "tags_json": '["codex-history","role:event_msg"]',
                "app": "codex",
            },
            {
                "id": 2,
                "created_at_ms": 2_000,
                "source": "codex_history",
                "committed_text": "以后整理记忆时要保留完整历史。",
                "tags_json": '["codex-history","role:user"]',
                "app": "codex",
            },
            {
                "id": 3,
                "created_at_ms": 3_000,
                "source": "codex_history",
                "committed_text": "这条会话已经经过人工选择，可以进入记忆上下文。",
                "tags_json": '["codex-history","role:user","memory-context-opt-in"]',
                "app": "codex",
            },
        ]

        records = assemble_input_rows(rows)

        self.assertEqual([item["sourceEventIds"] for item in records], [[3]])
        self.assertEqual(records[0]["text"], "这条会话已经经过人工选择，可以进入记忆上下文。")

    def test_adjacent_legacy_fragments_are_assembled_but_never_injectable_without_enter(self) -> None:
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
        self.assertFalse(records[0]["complete"])
        self.assertFalse(records[0]["injectable"])
        self.assertIn("missing_finalized_boundary", records[0]["qualityReasons"])

    def test_backspace_snapshot_revisions_collapse_to_the_final_context(self) -> None:
        rows = [
            {
                "id": 1,
                "created_at_ms": 1_000,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "整里",
                "recent_context": "记忆系统需要先完成输入重建与整里",
                "app": "com.openai.codex",
                "project": "wisdom-weasel-rag-ime",
                "context_group_id": "codex-thread",
                "context_group_level": "document",
            },
            {
                "id": 2,
                "created_at_ms": 1_700,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "整理",
                "recent_context": "记忆系统需要先完成输入重建与整理",
                "app": "com.openai.codex",
                "project": "wisdom-weasel-rag-ime",
                "context_group_id": "codex-thread",
                "context_group_level": "document",
            },
        ]

        records = assemble_input_rows(rows)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "记忆系统需要先完成输入重建与整理")
        self.assertEqual(records[0]["sourceEventIds"], [1, 2])

    def test_short_gap_does_not_merge_different_context_snapshots(self) -> None:
        rows = [
            {
                "id": 1,
                "created_at_ms": 1_000,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "整理",
                "recent_context": "今天先整理输入法的完整历史记录",
                "app": "com.openai.codex",
                "context_group_id": "codex-thread",
            },
            {
                "id": 2,
                "created_at_ms": 1_700,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "验证",
                "recent_context": "随后验证浏览器中的真实前台交互",
                "app": "com.openai.codex",
                "context_group_id": "codex-thread",
            },
        ]

        records = assemble_input_rows(rows)

        self.assertEqual(len(records), 2)

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

    def test_char_budget_records_requested_effective_actual_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-recent-char-budget-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            _record(core, "第一条完整输入。", created_at_ms=10_000)
            _record(core, "第二条完整输入，字符预算会保留这一条。", created_at_ms=11_000)
            _record(core, "第三条完整输入，应该因为字符预算被截断。", created_at_ms=12_000)
            with core._connect() as conn:
                result = recent_complete_input_context(
                    conn,
                    baseline_records=1,
                    max_records=10,
                    char_budget=24,
                    token_budget=16_384,
                    reserved_tokens=512,
                )

        receipt = result["observability"]["recentInputPolicy"]
        self.assertEqual(receipt["requestedCount"], 10)
        self.assertEqual(receipt["requestedChars"], 24)
        self.assertEqual(receipt["effectiveCount"], 1)
        self.assertLessEqual(receipt["effectiveChars"], 24)
        self.assertEqual(receipt["actualCount"], 3)
        self.assertTrue(receipt["truncated"])

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

    def test_isolated_words_and_transport_tokens_never_enter_agent_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-noise-gate-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            _record(core, "ai", created_at_ms=1_000)
            _record(core, "sidecar-selected", created_at_ms=2_000)
            _record(core, "这是已经完成并且可以理解的一整段输入。", created_at_ms=3_000)
            with core._connect() as conn:
                result = recent_complete_input_context(conn)

        self.assertNotIn("sidecar-selected", result["rendered"])
        self.assertNotIn("] ai", result["rendered"])
        self.assertIn("一整段输入", result["rendered"])
        self.assertEqual(result["observability"]["blockedRecordCount"], 2)

    def test_new_squirrel_segment_requires_finalized_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-finalized-gate-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            _record(
                core,
                "这段输入还没有按下回车所以不能注入上下文",
                created_at_ms=1_000,
                source="squirrel_input_segment",
            )
            _record(
                core,
                "这段输入已经按下回车，可以进入普通 Agent 上下文。",
                created_at_ms=2_000,
                source="squirrel_input_segment",
                tags=("input-segment", "finalized", "complete-input"),
            )
            with core._connect() as conn:
                result = recent_complete_input_context(conn)

        self.assertNotIn("还没有按下回车", result["rendered"])
        self.assertIn("已经按下回车", result["rendered"])

    def test_records_are_split_by_app_and_app_is_rendered_for_agent(self) -> None:
        rows = [
            {
                "id": 1,
                "created_at_ms": 1_000,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "我正在 Codex 里整理记忆功能",
                "app": "com.openai.codex",
                "context_group_id": "app:codex",
            },
            {
                "id": 2,
                "created_at_ms": 1_200,
                "source": "squirrel_rime_commit_burst",
                "committed_text": "随后切到微信回复另一件完全不同的事情",
                "app": "com.tencent.xinWeChat",
                "context_group_id": "app:wechat",
            },
        ]

        records = assemble_input_rows(rows)

        self.assertEqual(len(records), 2)
        self.assertEqual([item["app"] for item in records], ["com.openai.codex", "com.tencent.xinWeChat"])

        with tempfile.TemporaryDirectory(prefix="rag-ime-app-context-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            _record(core, "我正在 Codex 里整理记忆功能。", created_at_ms=1_000, app="com.openai.codex")
            with core._connect() as conn:
                result = recent_complete_input_context(conn)
        self.assertIn("[App: com.openai.codex]", result["rendered"])

    def test_recent_context_never_replaces_the_committed_utterance(self) -> None:
        records = assemble_input_rows(
            [
                {
                    "id": 1,
                    "created_at_ms": 1_000,
                    "source": "manual",
                    "committed_text": "这是本次真正完成的输入。",
                    "recent_context": "这里是编辑器里很长的旧文档，它不是本次用户输入，不能冒充记忆。",
                    "app": "com.openai.codex",
                }
            ]
        )

        self.assertEqual(records[0]["text"], "这是本次真正完成的输入。")


def _record(
    core: LocalSqliteCoreClient,
    text: str,
    *,
    created_at_ms: int,
    source: str = "manual",
    tags: tuple[str, ...] = (),
    app: str = "com.openai.codex",
) -> None:
    core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=created_at_ms,
            source=source,
            committed_text=text,
            privacy_disposition="allowed",
            project="wisdom-weasel-rag-ime",
            app=app,
            tags=tags,
        )
    )


if __name__ == "__main__":
    unittest.main()
