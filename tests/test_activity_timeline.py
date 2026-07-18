from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from rag_ime.activity_timeline import (
    DailyActivityTimelineStore,
    StaleActivityTimelineError,
)
from rag_ime.agent_role_book import AgentRoleBookStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.personal_context import (
    AgentMemoryEvidenceStore,
    MemoryBootstrapBuilder,
    load_activity_timeline_context,
)
from rag_ime.personal_context_maintenance import (
    PersonalContextMaintenanceConfig,
    PersonalContextMaintenanceRunner,
)
from rag_ime.personal_context_observability import PersonalContextObservability


class DailyActivityTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-activity-timeline-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.project = "wisdom-weasel-rag-ime"
        self.zone = ZoneInfo("Asia/Shanghai")
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.role_books = AgentRoleBookStore(self.db_path)
        self.role_books.initialize()
        self.role_books.ensure_seeded(
            "architect",
            "role-v1",
            display_name="架构师",
            mission="维护个人上下文",
            created_at_ms=self._ms(8, 0),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_maintenance_draft_review_approve_and_bootstrap_form_closed_loop(
        self,
    ) -> None:
        own_event_ids = [
            self._record(
                9,
                0,
                app="com.openai.chat",
                source="squirrel_commit",
                text="讨论个人记忆重构",
                context_group_id="topic:memory",
            ),
            self._record(
                9,
                5,
                app="com.openai.chat",
                source="squirrel_commit",
                text="明确新 Session 只注入一次上下文",
                context_group_id="topic:memory",
            ),
            self._record(
                9,
                8,
                app="com.google.Chrome",
                source="browser_extension",
                text="查阅 LongMemEval 评测说明",
                context_group_id="tab:benchmark",
            ),
            self._record(
                9,
                14,
                app="com.apple.TextEdit",
                source="squirrel_rime_commit",
                text="实现跨应用活动时间线",
                context_group_id="document:design",
            ),
            self._record(
                9,
                18,
                app="com.apple.TextEdit",
                source="squirrel_rime_commit",
                text="token=secret-value",
                context_group_id="document:design",
            ),
        ]
        self._record(
            9,
            20,
            app="com.google.Chrome",
            source="browser_extension",
            text="另一个项目不可混入",
            project="another-project",
        )
        evidence = AgentMemoryEvidenceStore(self.db_path, project=self.project)
        evidence.record_user_message(
            session_id="session:timeline",
            pi_entry_id="entry:user:timeline",
            role_id="architect",
            text="今天继续把个人上下文闭环做完",
            occurred_at_ms=self._ms(9, 30),
        )

        before = MemoryBootstrapBuilder(
            self.db_path,
            project=self.project,
        ).build(
            "session:before-approval",
            role_id="architect",
            generated_at_ms=self._ms(10, 0),
        )
        self.assertEqual(before["payload"]["sections"]["recentTimeline"], [])

        report = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(
                project=self.project,
                min_interval_ms=0,
            ),
        ).run_once(
            now_ms=self._ms(10, 0),
            force=True,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["activityTimelineSummary"]["draftCount"], 1)
        built = report["activityTimelines"][0]
        timeline_id = built["timeline"]["timelineId"]
        timeline = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        ).review(timeline_id)
        self.assertEqual(timeline["status"], "draft")
        self.assertEqual(timeline["sourceEventIds"], own_event_ids)
        self.assertEqual(timeline["eventCount"], 5)
        self.assertEqual(timeline["segmentCount"], 3)
        self.assertEqual(
            [segment["app"] for segment in timeline["segments"]],
            [
                "com.openai.chat",
                "com.google.Chrome",
                "com.apple.TextEdit",
            ],
        )
        self.assertEqual(timeline["segments"][-1]["redactedEventCount"], 1)
        self.assertNotIn("secret-value", json.dumps(timeline, ensure_ascii=False))
        self.assertFalse(timeline["policy"]["longTermFact"])
        self.assertFalse(timeline["policy"]["automaticPromotion"])

        with sqlite3.connect(self.db_path) as conn:
            output = json.loads(
                conn.execute(
                    """
                    SELECT output_json
                    FROM personal_context_consolidation_runs
                    WHERE project = ? AND role_id = 'architect'
                    """,
                    (self.project,),
                ).fetchone()[0]
            )
            self.assertEqual(
                output["digest"]["activityTimelineId"],
                timeline_id,
            )
            self.assertNotIn("segments", output["digest"])
            self.assertEqual(output["userMemoryDraft"]["candidates"], [])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0],
                0,
            )

        store = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        )
        with self.assertRaisesRegex(ValueError, "confirm_text"):
            store.approve(
                timeline_id,
                expected_source_event_hash=timeline["sourceEventHash"],
                approved_by="user:local-control-center",
                confirm_text="yes",
                approved_at_ms=self._ms(10, 5),
            )
        approved = store.approve(
            timeline_id,
            expected_source_event_hash=timeline["sourceEventHash"],
            approved_by="user:local-control-center",
            confirm_text="approve",
            approved_at_ms=self._ms(10, 5),
        )
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(approved["approvedBookId"])

        after = MemoryBootstrapBuilder(
            self.db_path,
            project=self.project,
        ).build(
            "session:after-approval",
            role_id="architect",
            generated_at_ms=self._ms(10, 6),
        )
        recent = after["payload"]["sections"]["recentTimeline"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["sourceId"], approved["approvedBookId"])
        self.assertEqual(recent[0]["provenance"]["timelineId"], timeline_id)
        self.assertEqual(
            recent[0]["provenance"]["sourceEventHash"],
            timeline["sourceEventHash"],
        )
        self.assertFalse(recent[0]["maySupportFacts"])
        self.assertNotIn("secret-value", json.dumps(recent, ensure_ascii=False))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            book = conn.execute(
                """
                SELECT status, source_event_ids_json, metadata_json
                FROM memory_books
                WHERE book_id = ?
                """,
                (approved["approvedBookId"],),
            ).fetchone()
            outbox = conn.execute(
                """
                SELECT projection_kind, aggregate_type, operation, state
                FROM memory_projection_outbox
                WHERE aggregate_id = ?
                """,
                (timeline_id,),
            ).fetchone()
        self.assertEqual(book["status"], "active")
        self.assertEqual(json.loads(book["source_event_ids_json"]), own_event_ids)
        self.assertFalse(json.loads(book["metadata_json"])["maySupportFacts"])
        self.assertEqual(
            tuple(outbox),
            (
                "retrieval_docs",
                "daily_activity_timeline",
                "approve",
                "pending",
            ),
        )

    def test_changed_input_events_make_reviewed_draft_stale(self) -> None:
        self._record(
            13,
            0,
            app="com.openai.chat",
            source="squirrel_commit",
            text="先生成时间线草案",
        )
        store = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        )
        first = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(13, 5),
        )["timeline"]
        self._record(
            13,
            10,
            app="com.google.Chrome",
            source="browser_extension",
            text="草案审核后又新增了活动",
        )

        with self.assertRaisesRegex(
            StaleActivityTimelineError,
            "input events changed",
        ):
            store.approve(
                first["timelineId"],
                expected_source_event_hash=first["sourceEventHash"],
                approved_by="user:test",
                confirm_text="approve",
                approved_at_ms=self._ms(13, 15),
            )

        second = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(13, 16),
        )["timeline"]
        self.assertNotEqual(second["timelineId"], first["timelineId"])
        self.assertEqual(store.review(first["timelineId"])["status"], "superseded")
        self.assertEqual(second["status"], "draft")
        bootstrap = MemoryBootstrapBuilder(
            self.db_path,
            project=self.project,
        ).build(
            "session:stale-draft",
            role_id="architect",
            generated_at_ms=self._ms(13, 17),
        )
        self.assertEqual(bootstrap["payload"]["sections"]["recentTimeline"], [])

    def test_daily_digest_uses_evidence_day_timeline_after_midnight(self) -> None:
        self._record(
            22,
            0,
            app="com.apple.TextEdit",
            source="squirrel_commit",
            text="实现输入法每日联合上下文",
        )
        AgentMemoryEvidenceStore(self.db_path, project=self.project).record_user_message(
            session_id="session:late",
            pi_entry_id="entry:late",
            role_id="architect",
            text="今晚继续验证记忆整理",
            occurred_at_ms=self._ms(22, 5),
        )

        next_day = int(
            datetime(2026, 7, 18, 0, 10, tzinfo=self.zone).timestamp() * 1_000
        )
        report = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(
                project=self.project,
                min_interval_ms=0,
            ),
        ).run_once(now_ms=next_day, force=True)

        self.assertTrue(report["ok"])
        with sqlite3.connect(self.db_path) as conn:
            output = json.loads(
                conn.execute(
                    """
                    SELECT output_json FROM personal_context_consolidation_runs
                    WHERE project = ? AND role_id = 'architect'
                    ORDER BY completed_at_ms DESC LIMIT 1
                    """,
                    (self.project,),
                ).fetchone()[0]
            )
        digest = output["digest"]
        self.assertEqual(digest["activityContext"]["date"], "2026-07-17")
        self.assertIn("实现输入法每日联合上下文", digest["activityContext"]["summary"])
        self.assertIn(
            "今晚继续验证记忆整理",
            [item["text"] for item in digest["highlights"]],
        )
        self.assertTrue(digest["activityContext"]["corroborationOnly"])
        self.assertFalse(digest["activityContext"]["maySupportFacts"])

    def test_model_timeline_context_filters_internal_duplicates_and_sensitive_text(
        self,
    ) -> None:
        self._record(
            18,
            0,
            app="RagImeControl",
            source="squirrel_commit",
            text="完成联合上下文测试",
        )
        self._record(
            18,
            1,
            app="RagImeControl",
            source="pi_agent_user",
            text="完成联合上下文测试",
        )
        self._record(
            18,
            2,
            app="RagImeControl",
            source="pi_agent_compaction",
            text="内部压缩摘要不应进入模型",
        )
        self._record(
            18,
            3,
            app="RagImeControl",
            source="pi_agent_tool_receipt",
            text="内部工具回执不应进入模型",
        )
        self._record(
            18,
            4,
            app="RagImeControl",
            source="squirrel_commit",
            text="token=secret-value",
        )
        store = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        )
        timeline = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(18, 5),
        )["timeline"]
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            context = load_activity_timeline_context(
                conn,
                project=self.project,
                timeline_date="2026-07-17",
                timeline_id=timeline["timelineId"],
            )

        serialized = json.dumps(context, ensure_ascii=False)
        self.assertIn("完成联合上下文测试", serialized)
        self.assertNotIn("内部压缩摘要", serialized)
        self.assertNotIn("内部工具回执", serialized)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("sourceEventIds", serialized)
        self.assertEqual(context["filteredInternalEventCount"], 2)
        self.assertEqual(context["deduplicatedEventCount"], 1)
        self.assertEqual(context["redactedEventCount"], 1)
        self.assertEqual(context["retainedEventCount"], 1)

    def test_approval_and_projection_outbox_share_one_transaction(self) -> None:
        self._record(
            15,
            0,
            app="com.apple.TextEdit",
            source="squirrel_rime_commit",
            text="验证时间线批准事务",
        )
        store = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        )
        draft = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(15, 5),
        )["timeline"]

        with patch(
            "rag_ime.activity_timeline.enqueue_memory_projection",
            side_effect=RuntimeError("projection outbox unavailable"),
        ), self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            store.approve(
                draft["timelineId"],
                expected_source_event_hash=draft["sourceEventHash"],
                approved_by="user:test",
                confirm_text="approve",
                approved_at_ms=self._ms(15, 10),
            )

        self.assertEqual(store.review(draft["timelineId"])["status"], "draft")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM memory_projection_outbox
                    WHERE aggregate_id = ?
                    """,
                    (draft["timelineId"],),
                ).fetchone()[0],
                0,
            )

    def test_decisions_are_recorded_without_raw_rejection_reason(self) -> None:
        observability = PersonalContextObservability(
            self.db_path,
            project=self.project,
        )
        observability.initialize()
        store = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
            observability=observability,
        )
        self._record(
            16,
            0,
            app="com.apple.TextEdit",
            source="squirrel_rime_commit",
            text="生成可批准的活动时间线",
        )
        first = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(16, 1),
        )["timeline"]
        store.approve(
            first["timelineId"],
            expected_source_event_hash=first["sourceEventHash"],
            approved_by="control-center-user",
            confirm_text="approve",
            approved_at_ms=self._ms(16, 2),
        )

        self._record(
            16,
            5,
            app="com.google.Chrome",
            source="browser_extension",
            text="生成第二份待拒绝的活动时间线",
        )
        second = store.build_draft(
            "2026-07-17",
            generated_at_ms=self._ms(16, 6),
        )["timeline"]
        store.reject(
            second["timelineId"],
            reason="private rejection detail",
            rejected_by="control-center-user",
            rejected_at_ms=self._ms(16, 7),
        )

        snapshot = observability.snapshot(current_ms=self._ms(16, 8))
        self.assertEqual(
            snapshot["drafts"]["activityTimelineByStatus"],
            {"approved": 1, "rejected": 1},
        )
        self.assertEqual(
            snapshot["drafts"]["latestDecisionByOutcome"],
            {"accepted": 1, "rejected": 1},
        )
        self.assertEqual(
            snapshot["drafts"]["generatedByKind"]["activity_timeline"],
            2,
        )
        self.assertNotIn(
            "private rejection detail",
            json.dumps(snapshot, ensure_ascii=False),
        )

    def _record(
        self,
        hour: int,
        minute: int,
        *,
        app: str,
        source: str,
        text: str,
        project: str | None = None,
        context_group_id: str = "",
    ) -> int:
        result = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=self._ms(hour, minute),
                source=source,
                committed_text=text,
                privacy_disposition="allowed",
                app=app,
                project=self.project if project is None else project,
                context_group_id=context_group_id,
                context_group_level="topic" if context_group_id else "app",
            )
        )
        return int(result.split(":", 1)[1])

    def _ms(self, hour: int, minute: int) -> int:
        return int(
            datetime(
                2026,
                7,
                17,
                hour,
                minute,
                tzinfo=self.zone,
            ).timestamp()
            * 1_000
        )


if __name__ == "__main__":
    unittest.main()
