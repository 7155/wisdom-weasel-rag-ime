from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.activity_timeline import DailyActivityTimelineStore
from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_lifecycle import set_memory_book_archive_status
from rag_ime.memory_book_compiler import (
    apply_stored_memory_book_run,
    rollback_memory_book_run,
    update_stored_memory_book_diff,
)
from rag_ime.models import InputEvent
from rag_ime.owner_memory_curation import OwnerMemoryCurator
from rag_ime.personal_context import (
    AgentMemoryEvidenceStore,
    local_date_for_timestamp,
)


class _FakeOrganizer:
    provider_name = "fixture"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("fixture organizer unavailable")
        self.calls.append(
            {
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "inputs": list(bundle.get("inputs") or []),
            }
        )
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        event_ids = [
            int(event_id)
            for item in inputs
            for event_id in item.get("sourceEventIds") or []
        ]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.96,
                }
                for item in inputs
            ],
            "topicBooks": [
                {
                    "summary": "保留这一批跨会话仍然有效的决定和约束。",
                    "sourceEventIds": event_ids,
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                }
            ],
            "memoryAtoms": [
                {
                    "canonicalText": str(item["text"]),
                    "summary": "长期有效的记忆证据",
                    "kind": "project_decision",
                    "sourceEventIds": list(item["sourceEventIds"]),
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
                for item in inputs
            ],
            "warnings": [],
        }


class _DecisionOnlyOrganizer:
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        self.calls.append([str(item["text"]) for item in inputs])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": (
                        "needs_review"
                        if "指代不清" in str(item["text"])
                        else "not_for_memory"
                    ),
                    "reasonCode": (
                        "ambiguous_reference"
                        if "指代不清" in str(item["text"])
                        else "one_batch_test_input"
                    ),
                    "confidence": 0.95,
                }
                for item in inputs
            ],
            "topicBooks": [],
            "memoryAtoms": [],
        }


class _AtomOnlyOrganizer(_FakeOrganizer):
    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        result = super().curate_owner_memory(
            bundle=bundle,
            project=project,
            owner_kind=owner_kind,
            owner_id=owner_id,
            instruction=instruction,
        )
        result["topicBooks"] = []
        return result


class _OmittingOrganizer:
    provider_name = "fixture"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        first = dict((bundle.get("inputs") or [])[0])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": first["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.95,
                }
            ],
            "topicBooks": [],
            "memoryAtoms": [
                {
                    "canonicalText": str(first["text"]),
                    "summary": "模型已覆盖的稳定证据",
                    "kind": "project_requirement",
                    "sourceEventIds": list(first["sourceEventIds"]),
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
            ],
        }


class _TimelineOnlyFactOrganizer:
    provider_name = "fixture"

    def __init__(self, timeline_event_id: int) -> None:
        self.timeline_event_id = timeline_event_id
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.9,
                }
                for item in inputs
            ],
            "topicBooks": [],
            "memoryAtoms": [
                {
                    "canonicalText": "仅由活动时间线猜测出的完成事实",
                    "summary": "不应通过治理",
                    "kind": "project_fact",
                    "sourceEventIds": [self.timeline_event_id],
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
            ],
        }


class OwnerMemoryCuratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-owner-curation-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.user_session = self.sessions.create(
            title="知游",
            role_id="zhiyou-v1",
            role_version="1",
            created_at_ms=1,
        )
        self.other_session = self.sessions.create(
            title="另一个角色",
            role_id="librarian-v1",
            role_version="1",
            created_at_ms=2,
        )
        self.sources = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        self.sources.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rime_fragments_are_curated_as_one_input_without_crossing_projects(self) -> None:
        core = LocalSqliteCoreClient(self.db_path)
        core.initialize()
        project_a_ids: list[int] = []
        for offset, committed, context in (
            (100, "BM", "目前BM"),
            (200, "25", "目前BM25"),
            (300, "这些", "目前BM25这些"),
            (400, "真实", "目前BM25这些真实实现"),
        ):
            event = core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=offset,
                    source="squirrel_rime_commit_burst",
                    committed_text=committed,
                    recent_context=context,
                    privacy_disposition="allowed",
                    app="com.openai.codex",
                    project="project-a",
                    context_group_id="app:codex",
                )
            )
            project_a_ids.append(int(event.split(":", 1)[1]))
        core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=500,
                source="manual_commit",
                committed_text="项目 B 的私有决定",
                privacy_disposition="allowed",
                project="project-b",
            )
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="project-a",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(report["ranScopeCount"], 1)
        self.assertEqual(len(organizer.calls), 1)
        inputs = organizer.calls[0]["inputs"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["text"], "目前BM25这些真实实现")
        self.assertEqual(inputs[0]["sourceEventIds"], project_a_ids)
        self.assertEqual(len(inputs[0]["sourceIds"]), 4)
        self.assertEqual(report["results"][0]["sourceCount"], 4)
        self.assertEqual(report["results"][0]["logicalInputCount"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT e.project, s.disposition
                FROM agent_memory_sources AS s
                JOIN input_events AS e ON e.id = s.input_event_id
                ORDER BY e.id
                """
            ).fetchall()
        self.assertEqual(
            rows,
            [
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-b", "pending"),
            ],
        )

    def test_daily_run_separates_user_and_role_books_and_forgets_noise_reversibly(self) -> None:
        noise = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:noise",
            turn_id="turn:noise",
            text="嗯嗯那个这个",
            created_at_ms=100,
        )
        durable = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:decision",
            turn_id="turn:decision",
            text="不要截图，桌面上下文默认读取 Accessibility Tree。",
            created_at_ms=200,
        )
        compaction = self.sources.checkpoint_compaction(
            session_id=str(self.other_session["id"]),
            result={
                "summary": "用户要求这个角色每天整理自己的主题书，但不读取助手逐轮输出。",
                "firstKeptEntryId": "entry:kept",
            },
            trigger="automatic",
            created_at_ms=300,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(report["ranScopeCount"], 2)
        self.assertEqual(
            {(call["ownerKind"], call["ownerId"]) for call in organizer.calls},
            {("user", "default"), ("agent", "librarian-v1")},
        )
        self.assertEqual(
            self.sources.get(str(noise["source"]["sourceId"]))["disposition"],
            "not_for_memory",
        )
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "remember",
        )
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "remember",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            runs = conn.execute(
                """
                SELECT run_id, owner_kind, owner_id, run_kind, status
                FROM memory_cleanup_runs
                WHERE run_kind = 'daily_curation'
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
            self.assertEqual(
                [(row["owner_kind"], row["owner_id"], row["status"]) for row in runs],
                [
                    ("agent", "librarian-v1", "draft"),
                    ("user", "default", "draft"),
                ],
            )
            agent_run_id = next(
                str(row["run_id"])
                for row in runs
                if row["owner_kind"] == "agent"
            )
            for row in runs:
                apply_stored_memory_book_run(conn, run_id=str(row["run_id"]))
            books = conn.execute(
                """
                SELECT owner_kind, owner_id, title
                FROM memory_books
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
            atoms = conn.execute(
                """
                SELECT owner_kind, owner_id, canonical_text
                FROM memory_atoms
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
        self.assertEqual(
            [(row["owner_kind"], row["owner_id"]) for row in books],
            [("agent", "librarian-v1"), ("user", "default")],
        )
        self.assertEqual(
            [(row["owner_kind"], row["owner_id"]) for row in atoms],
            [("agent", "librarian-v1"), ("user", "default")],
        )
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "consolidated",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            rollback_memory_book_run(conn, run_id=agent_run_id)
            conn.commit()
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "remember",
        )
        role_scope = curator.status(
            owner_kind="agent",
            owner_id="librarian-v1",
            current_ms=1_200,
        )["scopes"][0]
        self.assertTrue(role_scope["due"])
        self.assertEqual(role_scope["status"], "idle")

        restored = self.sources.set_disposition(
            str(noise["source"]["sourceId"]),
            disposition="pending",
            reason_code="user_restored",
            actor_kind="rollback",
            created_at_ms=1_100,
        )
        self.assertEqual(restored["source"]["disposition"], "pending")

    def test_daily_model_sees_dialogue_and_timeline_but_timeline_cannot_prove_fact(
        self,
    ) -> None:
        timestamp = 1_784_318_400_000
        checkpoint = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:joint-context",
            turn_id="turn:joint-context",
            text="输入法个人记忆需要按可追溯证据整理。",
            created_at_ms=timestamp,
        )
        evidence = AgentMemoryEvidenceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        evidence.record_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="evidence:user:joint-context",
            turn_id="turn:joint-context",
            role_id="zhiyou-v1",
            text="继续整理输入法个人记忆",
            occurred_at_ms=timestamp,
        )
        evidence.record_assistant_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="evidence:assistant:joint-context",
            turn_id="turn:joint-context",
            role_id="zhiyou-v1",
            text="我会先验证联合上下文，再生成待审草案。",
            occurred_at_ms=timestamp + 1_000,
        )
        core = LocalSqliteCoreClient(self.db_path)
        timeline_event_id = int(
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=timestamp + 2_000,
                    source="squirrel_commit",
                    committed_text="在 TextEdit 实现时间线过滤",
                    privacy_disposition="allowed",
                    app="com.apple.TextEdit",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        timeline_date = local_date_for_timestamp(timestamp)
        DailyActivityTimelineStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        ).build_draft(timeline_date, generated_at_ms=timestamp + 3_000)
        organizer = _TimelineOnlyFactOrganizer(timeline_event_id)
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: timestamp + 10_000,
            initial_settle_ms=0,
        )

        result = curator.run_due(current_ms=timestamp + 10_000)

        self.assertTrue(result["ok"])
        self.assertEqual(result["ranScopeCount"], 1)
        self.assertEqual(result["results"][0]["runStatus"], "idle")
        self.assertEqual(result["results"][0]["diffCount"], 0)
        bundle = organizer.calls[0]
        self.assertIn("在 TextEdit 实现时间线过滤", bundle["activityContext"]["summary"])
        messages = bundle["agentConversationContext"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertIn("联合上下文", messages[1]["text"])
        serialized_activity = json.dumps(bundle["activityContext"], ensure_ascii=False)
        serialized_conversation = json.dumps(
            bundle["agentConversationContext"], ensure_ascii=False
        )
        self.assertNotIn("sourceEventIds", serialized_activity)
        self.assertNotIn("evidenceId", serialized_conversation)
        legal_ids = bundle["legalSourceEventIds"]
        self.assertEqual(
            legal_ids,
            [int(checkpoint["source"]["inputEventId"])],
        )
        self.assertNotIn(timeline_event_id, legal_ids)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_cleanup_diffs"
                ).fetchone()[0],
                0,
            )

    def test_needs_review_source_stays_ahead_of_cursor_for_next_daily_pass(self) -> None:
        first = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:stable",
            turn_id="turn:stable",
            text="每天整理一次长期记忆。",
            created_at_ms=100,
        )
        second = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:ambiguous",
            turn_id="turn:ambiguous",
            text="这个以后照旧，但当前指代不清。",
            created_at_ms=200,
        )
        organizer = _DecisionOnlyOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()

        first_report = curator.run_due(current_ms=1_000)
        first_status = curator.status(current_ms=1_000)
        second_report = curator.run_due(current_ms=61_001)

        self.assertTrue(first_report["ok"], first_report)
        self.assertEqual(
            first_status["scopes"][0]["lastSourceCursor"]["sourceId"],
            str(first["source"]["sourceId"]),
        )
        self.assertEqual(first_status["needsReviewSourceCount"], 1)
        self.assertEqual(
            self.sources.get(str(second["source"]["sourceId"]))["disposition"],
            "needs_review",
        )
        self.assertTrue(second_report["ok"])
        self.assertEqual(
            organizer.calls,
            [
                ["每天整理一次长期记忆。", "这个以后照旧，但当前指代不清。"],
                ["这个以后照旧，但当前指代不清。"],
            ],
        )

    def test_organizer_omission_fails_closed_and_does_not_advance_past_source(self) -> None:
        first = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:covered",
            turn_id="turn:covered",
            text="每天整理一次长期记忆。",
            created_at_ms=100,
        )
        omitted = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:omitted",
            turn_id="turn:omitted",
            text="这条证据不能因为模型漏项而消失。",
            created_at_ms=200,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_OmittingOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)
        status = report["status"]["scopes"][0]

        self.assertTrue(report["ok"], report)
        self.assertEqual(
            self.sources.get(str(first["source"]["sourceId"]))["disposition"],
            "remember",
        )
        omitted_source = self.sources.get(str(omitted["source"]["sourceId"]))
        self.assertEqual(omitted_source["disposition"], "needs_review")
        self.assertEqual(
            omitted_source["dispositionReason"],
            "model_decision_missing",
        )
        self.assertEqual(
            status["lastSourceCursor"]["sourceId"],
            str(first["source"]["sourceId"]),
        )
        self.assertEqual(status["needsReviewSourceCount"], 1)

    def test_draft_blocks_repeated_model_calls(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:preference",
            turn_id="turn:preference",
            text="每天只整理一次角色记忆。",
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        first = curator.run_due(current_ms=1_000)
        second = curator.run_due(current_ms=100_000_000)

        self.assertEqual(first["ranScopeCount"], 1)
        self.assertEqual(second["ranScopeCount"], 0)
        self.assertEqual(len(organizer.calls), 1)
        scope = second["status"]["scopes"][0]
        self.assertEqual(scope["dueReason"], "draft_pending_review")

    def test_transient_tool_receipts_are_not_promoted_to_long_term_memory(self) -> None:
        source = self.sources.checkpoint_tool_receipt(
            {
                "approvalId": "approval:pause-ai",
                "sessionId": str(self.user_session["id"]),
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "AI 辅助已暂停，普通 Rime 拼音仍可使用。",
                },
            },
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            owner_kind="shared",
            owner_id="wisdom-weasel-rag-ime",
            current_ms=1_000,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        result = report["results"][0]
        self.assertEqual(result["modelSourceCount"], 0)
        self.assertEqual(
            result["deterministicDecisions"][0]["reasonCode"],
            "transient_runtime_receipt",
        )
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "not_for_memory")

    def test_fact_free_questions_workflow_noise_duplicates_and_commands_are_filtered(self) -> None:
        texts = [
            "Pi Runtime 的新 Session 个人记忆应该如何注入？",
            "Pi Runtime 的新 Session 个人记忆应该如何注入？",
            "请调用 ime_memory Tool 的 curation_prepare，只生成草案并返回 runId。",
            "合并分支并记录改动",
        ]
        sources = [
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:noise:{index}",
                turn_id=f"turn:noise:{index}",
                text=text,
                created_at_ms=100 + index,
            )
            for index, text in enumerate(texts)
        ]
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        reasons = [
            self.sources.get(str(source["source"]["sourceId"]))["dispositionReason"]
            for source in sources
        ]
        self.assertEqual(
            reasons,
            [
                "duplicate_repeated_input",
                "standalone_question_no_durable_claim",
                "memory_workflow_instruction",
                "transient_user_instruction",
            ],
        )
        self.assertTrue(
            all(
                self.sources.get(str(source["source"]["sourceId"]))["disposition"]
                == "not_for_memory"
                for source in sources
            )
        )

    def test_failed_tool_receipt_is_audit_only(self) -> None:
        source = self.sources.checkpoint_tool_receipt(
            {
                "approvalId": "approval:failed-memory-draft",
                "sessionId": str(self.user_session["id"]),
                # Simulate a legacy/malformed row that passed the old receipt
                # checkpoint despite carrying a failed outcome in its text.
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "草案生成被网关校验拒绝，尚未生成 runId。",
                },
            },
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            owner_kind="shared",
            owner_id="wisdom-weasel-rag-ime",
            current_ms=1_000,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "not_for_memory")
        self.assertEqual(stored["dispositionReason"], "failed_tool_receipt")

    def test_verbatim_long_source_cannot_become_atom_or_book(self) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:verbatim-long",
            turn_id="turn:verbatim-long",
            text=(
                "输入法记忆整理需要先核对每条证据，再生成事实原子和主题书，"
                "同时不得把这段长输入原封不动复制进长期记忆正文。"
            ),
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        result = report["results"][0]
        self.assertEqual(result["runStatus"], "idle")
        self.assertEqual(result["diffCount"], 0)
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "needs_review")
        self.assertEqual(
            stored["dispositionReason"],
            "remember_without_durable_atom",
        )

    def test_rejecting_every_semantic_write_resolves_review_without_forgetting_evidence(
        self,
    ) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:reject-synthesis",
            turn_id="turn:reject-synthesis",
            text="保留原始证据，但这次模型生成的整理内容不准确。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()

        generated = curator.run_due(current_ms=1_000)
        run_id = str(generated["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            diff_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM memory_cleanup_diffs WHERE run_id = ? ORDER BY id",
                    (run_id,),
                ).fetchall()
            ]
            for diff_id in diff_ids:
                update_stored_memory_book_diff(
                    conn,
                    run_id=run_id,
                    diff_id=diff_id,
                    selected=False,
                )
            resolved = apply_stored_memory_book_run(conn, run_id=run_id)
            cursor = conn.execute(
                """
                SELECT status
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                  AND project = 'wisdom-weasel-rag-ime' AND lane = 'daily'
                """
            ).fetchone()

        self.assertEqual(resolved["status"], "empty")
        self.assertEqual(
            resolved["metadata"]["curationOutcome"],
            "review_rejected_all_writes",
        )
        self.assertEqual(cursor["status"], "idle")
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "remember",
        )
        status = curator.status(current_ms=61_001)["scopes"][0]
        self.assertEqual(status["dueReason"], "no_sources")
        self.assertFalse(status["due"])

    def test_daily_curation_does_not_reactivate_an_archived_owner_book(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:first-book",
            turn_id="turn:first-book",
            text="桌面上下文默认读取 Accessibility Tree。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()
        first = curator.run_due(current_ms=1_000)
        first_run_id = str(first["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            applied = apply_stored_memory_book_run(conn, run_id=first_run_id)
            book_id = str(
                next(
                    diff["payload"]["bookId"]
                    for diff in applied["diffs"]
                    if diff["op"] == "upsert_memory_book"
                )
            )
            set_memory_book_archive_status(
                conn,
                book_id=book_id,
                archived=True,
                reason="user_archive",
                current_ms=2_000,
            )
            conn.commit()

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:after-archive",
            turn_id="turn:after-archive",
            text="每日整理仍可保留新原子，但不能偷偷恢复归档书。",
            created_at_ms=70_000,
        )
        second = curator.run_due(current_ms=70_001)
        second_run_id = str(second["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            second_diffs = conn.execute(
                "SELECT op FROM memory_cleanup_diffs WHERE run_id = ?",
                (second_run_id,),
            ).fetchall()
            apply_stored_memory_book_run(conn, run_id=second_run_id)
            book = conn.execute(
                """
                SELECT status, archived_at_ms, archive_reason
                FROM memory_books
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()

        self.assertNotIn("upsert_memory_book", {str(row["op"]) for row in second_diffs})
        self.assertEqual(
            tuple(book),
            ("archived", 2_000, "user_archive"),
        )

    def test_atom_only_model_output_still_updates_the_existing_owner_book(self) -> None:
        first_text = "每天整理一次角色自己的长期记忆。"
        second_text = "没有输出 topicBooks 时也要把新原子并入原有主题书。"
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:first-organic-book",
            turn_id="turn:first-organic-book",
            text=first_text,
            created_at_ms=100,
        )
        first_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        first_curator.initialize()
        first = first_curator.run_due(current_ms=1_000)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            apply_stored_memory_book_run(
                conn,
                run_id=str(first["results"][0]["runId"]),
            )

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:second-organic-book",
            turn_id="turn:second-organic-book",
            text=second_text,
            created_at_ms=70_000,
        )
        second_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_AtomOnlyOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        second = second_curator.run_due(current_ms=70_001)
        second_run_id = str(second["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            draft = conn.execute(
                """
                SELECT payload_json
                FROM memory_cleanup_diffs
                WHERE run_id = ? AND op = 'upsert_memory_book'
                """,
                (second_run_id,),
            ).fetchone()
            apply_stored_memory_book_run(conn, run_id=second_run_id)
            book = conn.execute(
                "SELECT summary, memory_atom_ids_json FROM memory_books"
            ).fetchone()

        self.assertIsNotNone(draft)
        self.assertIn(second_text, str(book["summary"]))
        self.assertEqual(len(json.loads(book["memory_atom_ids_json"])), 2)

    def test_failure_keeps_cursor_and_enters_backoff(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:failure",
            turn_id="turn:failure",
            text="这条重要决定不能因为模型失败而丢失。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(fail=True),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertFalse(report["ok"])
        scope = report["status"]["scopes"][0]
        self.assertEqual(scope["status"], "backoff")
        self.assertEqual(scope["pendingSourceCount"], 1)
        self.assertEqual(scope["lastSourceCursor"]["createdAtMs"], 0)
        self.assertGreater(scope["nextDueAtMs"], 1_000)


if __name__ == "__main__":
    unittest.main()
