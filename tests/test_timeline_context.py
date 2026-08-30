from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.daily_planner import local_date_string
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.settings_store import ManagementSettingsStore
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

    def test_timeline_keeps_only_the_latest_four_complete_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-eight-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            for index in range(1, 11):
                _record_event(core, f"语义完整的最近输入第{index}条")

            pack = build_timeline_context_pack(core, project="wisdom-weasel-rag-ime")

        recent = str(pack["recentInput"])
        for index in range(1, 7):
            self.assertNotIn(f"第{index}条", recent)
        for index in range(7, 11):
            self.assertIn(f"第{index}条", recent)
        self.assertEqual(len(pack["recentRecords"]), 4)
        recent_evidence = [
            item for item in pack["evidencePack"]
            if item["sourceType"] == "recent_input_context"
        ]
        self.assertEqual(len(recent_evidence), 4)
        self.assertTrue(
            all(item["metadata"]["maySupportFacts"] is False for item in recent_evidence)
        )

    def test_timeline_caps_recent_history_and_reports_source_budgets(self) -> None:
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
        self.assertEqual(recent["recordCount"], 4)
        self.assertEqual(observability["tokenBudget"], 4096)
        self.assertEqual(observability["reservedOutputTokens"], 1024)
        self.assertEqual(observability["availableContextTokens"], 3072)
        self.assertGreater(observability["currentInput"]["estimatedTokens"], 0)
        self.assertEqual(observability["ragEvidence"]["recordCount"], 4)
        self.assertGreater(observability["totalEstimatedTokens"], 0)

    def test_timeline_applies_configured_recent_input_count_and_char_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-configured-input-budget-") as tmp:
            db_path = Path(tmp) / "timeline.sqlite"
            core = LocalSqliteCoreClient(db_path)
            for index in range(1, 31):
                _record_event(core, f"配置预算下仍应保留的最近输入第{index}条")
            settings = ManagementSettingsStore(db_path)
            settings.update_settings(
                {
                    "context": {
                        "recentInputMaximum": 20,
                        "recentInputCharMaximum": 256,
                    }
                }
            )

            pack = build_timeline_context_pack(core, project="wisdom-weasel-rag-ime")

        recent = pack["contextObservability"]["recentCompleteInputs"]
        policy = pack["recentContextObservability"]["recentInputPolicy"]
        self.assertLessEqual(recent["recordCount"], 20)
        self.assertEqual(recent["maxRecordCount"], 20)
        self.assertEqual(policy["requestedCount"], 20)
        self.assertEqual(policy["requestedChars"], 256)
        self.assertGreater(policy["effectiveCount"], 4)
        self.assertLessEqual(policy["effectiveCount"], 20)
        self.assertLessEqual(policy["effectiveChars"], 256)

    def test_timeline_injects_planning_before_latest_approved_semantic_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-work-context-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            _insert_planning_and_approved_timeline(core)

            pack = build_timeline_context_pack(
                core,
                project="wisdom-weasel-rag-ime",
                current_context="继续完成输入法上下文链路",
            )

        self.assertEqual(pack["planning"]["openTasks"][0]["title"], "修复生成上下文链路")
        self.assertLessEqual(len(pack["planning"]["openTasks"]), 6)
        activities = pack["activityTimeline"]["items"]
        self.assertEqual([item["title"] for item in activities], ["整理记忆召回", "验证候选生成"])
        self.assertEqual(len(activities), 2)
        self.assertTrue(all(item["maySupportFacts"] is False for item in activities))
        source_types = [item["sourceType"] for item in pack["evidencePack"]]
        self.assertLess(source_types.index("todo"), source_types.index("activity_timeline"))
        self.assertEqual(pack["contextObservability"]["activityTimeline"]["recordCount"], 2)

    def test_approved_timeline_is_not_injected_after_source_event_is_forgotten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-timeline-forget-closed-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "timeline.sqlite")
            event_ids = _insert_planning_and_approved_timeline(core)
            with core._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_tombstones(
                        created_at_ms, target_type, target_value, reason, active
                    ) VALUES (?, 'source_event_id', ?, 'user_forget', 1)
                    """,
                    (now_ms(), str(event_ids[0])),
                )

            pack = build_timeline_context_pack(
                core,
                project="wisdom-weasel-rag-ime",
                current_context="继续完成输入法上下文链路",
            )

        self.assertEqual(pack["activityTimeline"]["items"], [])
        self.assertNotIn("整理记忆召回", json.dumps(pack, ensure_ascii=False))

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
        self.assertEqual([item["sourceType"] for item in evidence], ["recent_input_context", "daily_book"])
        self.assertEqual(evidence[1]["surfaceHints"], ["DeepSeek 生成", "主动候选"])


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


def _insert_planning_and_approved_timeline(core: LocalSqliteCoreClient) -> list[int]:
    core.initialize()
    timestamp = now_ms()
    day = local_date_string()
    event_ids = [
        _record_event(core, "整理个人记忆证据"),
        _record_event(core, "梳理主题书和混合检索边界"),
        _record_event(core, "确认计划和时间线进入模型请求"),
        _record_event(core, "完善控制中心时间线界面"),
    ]
    segments = [
        {
            "segmentId": "task:memory",
            "title": "整理记忆召回",
            "summary": "梳理个人记忆、主题书和混合检索边界。",
            "startMs": timestamp - 7_200_000,
            "endMs": timestamp - 5_400_000,
            "apps": ["Codex", "Ghostty"],
            "eventCount": 8,
            "sourceEventIds": event_ids[:2],
        },
        {
            "segmentId": "task:generation",
            "title": "验证候选生成",
            "summary": "确认计划、时间线和最近输入进入模型请求。",
            "startMs": timestamp - 5_200_000,
            "endMs": timestamp - 3_800_000,
            "apps": ["Ghostty"],
            "eventCount": 5,
            "sourceEventIds": [event_ids[2]],
        },
        {
            "segmentId": "task:ui",
            "title": "完善控制中心",
            "summary": "第三个任务不应进入显式生成的活动时间线预算。",
            "startMs": timestamp - 3_000_000,
            "endMs": timestamp - 2_000_000,
            "apps": ["Chrome"],
            "eventCount": 3,
            "sourceEventIds": [event_ids[3]],
        },
    ]
    with core._connect() as conn:
        conn.execute(
            """
            INSERT INTO planning_daily(
                plan_id, plan_date, project, intention, notes, reflection,
                assistant_summary, created_at_ms, updated_at_ms, metadata_json
            ) VALUES (?, ?, ?, ?, '', '', '', ?, ?, '{}')
            """,
            (
                "plan:today",
                day,
                "wisdom-weasel-rag-ime",
                "今天完成记忆召回与生成链路验证",
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO planning_tasks(
                task_id, plan_date, title, detail, status, priority, due_at_ms,
                project, goal_id, source, confidence, created_at_ms, updated_at_ms,
                completed_at_ms, metadata_json
            ) VALUES (?, ?, ?, ?, 'in_progress', 5, NULL, ?, '', 'manual', 1.0, ?, ?, NULL, '{}')
            """,
            (
                "task:context-chain",
                day,
                "修复生成上下文链路",
                "让计划和时间线进入 provider payload。",
                "wisdom-weasel-rag-ime",
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO daily_activity_timelines(
                timeline_id, project, timeline_date, timezone, status,
                source_event_ids_json, source_event_hash, segments_json,
                summary_text, event_count, segment_count, approved_book_id,
                approved_by, approved_at_ms, rejection_reason, metadata_json,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, 'Asia/Shanghai', 'approved', ?, ?, ?, ?, 16, 3,
                      '', 'user:test', ?, '', '{}', ?, ?)
            """,
            (
                "activity-timeline:today",
                "wisdom-weasel-rag-ime",
                day,
                json.dumps(event_ids),
                "sha256:test-approved-timeline",
                json.dumps(segments, ensure_ascii=False),
                "上午主要完成记忆召回与候选生成链路。",
                timestamp,
                timestamp,
                timestamp,
            ),
        )
    return event_ids


if __name__ == "__main__":
    unittest.main()
