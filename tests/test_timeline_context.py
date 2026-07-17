from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms
from rag_ime.timeline_context import build_timeline_context_pack, timeline_evidence_pack_from_core


class TimelineContextTests(unittest.TestCase):
    def test_short_standalone_commit_keeps_longer_trusted_field_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-field-context-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            context = "请检查当前前台上下文是否完整注入，并在证据为空时明确降级。"
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="squirrel",
                    committed_text="改正",
                    privacy_disposition="allowed",
                    recent_context=context,
                    project="wisdom-weasel-rag-ime",
                    tags=("user-input",),
                )
            )

            pack = build_timeline_context_pack(core, project="wisdom-weasel-rag-ime")

        self.assertIn(context, str(pack["recentInput"]))
        record = pack["recentRecords"][0]
        self.assertEqual(record["text"], context)
        self.assertEqual(record["reconstruction"]["method"], "standalone-context")

    def test_timeline_preserves_recent_complete_inputs_within_configured_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-eight-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            for index in range(1, 11):
                _record_event(core, f"语义完整的最近输入第{index}条")

            pack = build_timeline_context_pack(core, project="wisdom-weasel-rag-ime")

        recent = str(pack["recentInput"])
        for index in range(1, 11):
            self.assertIn(f"第{index}条", recent)

    def test_timeline_can_exceed_twenty_records_and_reports_source_budgets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-dynamic-budget-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            for index in range(1, 31):
                _record_event(core, f"这是一条语义完整且用于动态上下文预算验证的最近输入记录编号{index}")

            pack = build_timeline_context_pack(
                core,
                project="wisdom-weasel-rag-ime",
                current_context="请结合最近完整输入和今日计划继续回答",
            )

        observability = pack["contextObservability"]
        recent = observability["recentCompleteInputs"]
        self.assertGreater(recent["recordCount"], 20)
        self.assertLessEqual(recent["recordCount"], 80)
        self.assertEqual(observability["tokenBudget"], 4096)
        self.assertEqual(observability["reservedOutputTokens"], 1024)
        self.assertEqual(observability["availableContextTokens"], 3072)
        self.assertGreater(observability["currentInput"]["estimatedTokens"], 0)
        self.assertGreater(observability["ragEvidence"]["recordCount"], 20)
        self.assertGreater(observability["totalEstimatedTokens"], 0)

    def test_timeline_context_pack_includes_recent_input_and_daily_books(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-context-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            event_id = _record_event(core, "主动 DeepSeek 生成按钮已经接入候选框")
            _insert_daily_book(core, event_id=event_id)

            pack = build_timeline_context_pack(
                core,
                project="wisdom-weasel-rag-ime",
                current_context="正在测试输入法时间线笔记本",
                selected_text="候选框",
            )
            evidence = timeline_evidence_pack_from_core(core, project="wisdom-weasel-rag-ime")

        self.assertEqual(pack["schemaVersion"], "rag-ime.timeline-context.v1")
        self.assertIn("主动 DeepSeek 生成按钮", pack["recentInput"])
        self.assertEqual(pack["dailyBooks"][0]["title"], "Active RAG 时间线")
        self.assertEqual([item["sourceType"] for item in evidence], ["daily_book", "recent_input_context"])
        self.assertEqual(evidence[0]["surfaceHints"], ["DeepSeek 生成", "主动候选"])

    def test_timeline_slice_does_not_let_history_starve_books(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-grounding-first-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            event_id = 0
            for index in range(12):
                event_id = _record_event(core, f"历史句子{index}：这是一条完整但只用于连续性的输入")
            _insert_daily_book(core, event_id=event_id)

            evidence = timeline_evidence_pack_from_core(
                core,
                project="wisdom-weasel-rag-ime",
                max_items=2,
            )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["sourceType"], "daily_book")
        self.assertEqual(evidence[1]["sourceType"], "recent_input_context")


def _record_event(core: LocalSqliteCoreClient, text: str) -> int:
    memory_id = core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source="manual",
            committed_text=text,
            privacy_disposition="allowed",
            recent_context="RAG-IME 真实前台验收",
            project="wisdom-weasel-rag-ime",
            tags=("RAG", "DeepSeek"),
        )
    )
    return int(str(memory_id).split(":", 1)[1])


def _insert_daily_book(core: LocalSqliteCoreClient, *, event_id: int) -> None:
    core.initialize()
    timestamp = now_ms()
    with core._connect() as conn:
        conn.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status, confidence,
                quality_score, created_at_ms, updated_at_ms, metadata_json
            )
            VALUES (?, 'daily', '2026-07-07', ?, ?, ?, ?, '', ?, ?, ?, ?, '[]', 'active', 0.8, 0.8, ?, ?, '{}')
            """,
            (
                "book:daily:2026-07-07",
                "Active RAG 时间线",
                "用户把 RAG 作为 evidence，由 DeepSeek 生成一条候选。",
                "active rag timeline deepseek",
                "wisdom-weasel-rag-ime",
                json.dumps(["RAG", "DeepSeek"], ensure_ascii=False),
                json.dumps(["DeepSeek 生成", "主动候选"], ensure_ascii=False),
                json.dumps(["Active RAG", "候选框"], ensure_ascii=False),
                json.dumps([event_id], ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )


if __name__ == "__main__":
    unittest.main()
