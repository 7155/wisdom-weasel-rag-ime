from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_role_book import AgentRoleBookStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.personal_context import AgentMemoryEvidenceStore
from rag_ime.personal_context_observability import PersonalContextObservability


class PersonalContextObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-context-observability-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite3"
        self.observability = PersonalContextObservability(
            self.db_path,
            project="rag-ime",
        )
        self.observability.initialize()
        self.roles = AgentRoleBookStore(self.db_path)
        self.sessions = AgentSessionStore(self.db_path)
        self.evidence = AgentMemoryEvidenceStore(
            self.db_path,
            project="rag-ime",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_survives_restart_and_exposes_counts_without_raw_text(self) -> None:
        active = self.roles.ensure_seeded(
            "companion-present-v1",
            "1",
            "智鼬",
            "陪用户完成项目",
            "persona-v1",
            created_at_ms=100,
        )
        session = self.sessions.create(
            title="可观测测试",
            role_id="companion-present-v1",
            role_version="1",
            role_book_revision_id=str(active["revisionId"]),
            created_at_ms=110,
        )
        session_id = str(session["id"])
        self.evidence.record_user_message(
            session_id=session_id,
            pi_entry_id="message:user:1",
            role_id="companion-present-v1",
            turn_id="turn:1",
            text="用户原始私密句子不得出现在可观测接口",
            occurred_at_ms=120,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO agent_context_items(
                    item_id, session_id, source_kind, source_id, lane,
                    lifecycle, status, dedupe_key, title, summary, payload_json,
                    available_at_ms, delivered_turn_id, delivered_at_ms,
                    created_at_ms, updated_at_ms
                ) VALUES (
                    'context:bootstrap:1', ?, 'memory_bootstrap', 'bootstrap:1',
                    'fact', 'once', 'consumed', 'memory-bootstrap:test:v1',
                    'bootstrap', '', '{}', 130, 'turn:1', 140, 130, 140
                )
                """,
                (session_id,),
            )
            conn.execute(
                """
                INSERT INTO personal_context_consolidation_runs(
                    run_id, project, role_id, role_version, idempotency_key,
                    status, window_start_ms, window_end_ms,
                    source_evidence_ids_json, output_json, created_at_ms,
                    completed_at_ms, updated_at_ms
                ) VALUES (
                    'run:1', 'rag-ime', 'companion-present-v1', '1', 'daily:1',
                    'succeeded', 100, 200, '[]', ?, 200, 200, 200
                )
                """,
                (
                    json.dumps(
                        {
                            "userMemoryDraft": {"draftId": "user-draft:1"},
                            "roleBookDraft": {"draftId": "role-draft:1"},
                        }
                    ),
                ),
            )

        self.sessions.record_runtime_event(
            event_id=f"{session_id}:1",
            session_id=session_id,
            turn_id="turn:1",
            sequence=1,
            event_type="turn_started",
            created_at_ms=1_000,
        )
        self.sessions.record_runtime_event(
            event_id=f"{session_id}:2",
            session_id=session_id,
            turn_id="turn:1",
            sequence=2,
            event_type="tool_started",
            created_at_ms=1_030,
            metrics={"toolCalls": 1},
        )
        self.sessions.record_runtime_event(
            event_id=f"{session_id}:3",
            session_id=session_id,
            turn_id="turn:1",
            sequence=3,
            event_type="message_completed",
            created_at_ms=1_080,
            metrics={
                "usage": {
                    "inputTokens": 25,
                    "outputTokens": 10,
                    "cacheReadTokens": 4,
                    "cacheWriteTokens": 2,
                    "totalTokens": 35,
                }
            },
        )
        self.sessions.record_runtime_event(
            event_id=f"{session_id}:4",
            session_id=session_id,
            turn_id="turn:1",
            sequence=4,
            event_type="turn_completed",
            created_at_ms=1_100,
        )
        decision = self.observability.record_draft_decision(
            draft_kind="role_book",
            draft_id="role-draft:1",
            run_id="run:1",
            role_id="companion-present-v1",
            role_version="1",
            decision="accepted",
            reason="里面含有不能从接口读回的审核备注",
            created_at_ms=300,
        )
        repeated = self.observability.record_draft_decision(
            draft_kind="role_book",
            draft_id="role-draft:1",
            run_id="run:1",
            role_id="companion-present-v1",
            role_version="1",
            decision="accepted",
            reason="另一段备注也不能改变同一决定的幂等键",
            created_at_ms=400,
        )
        self.assertEqual(decision["decisionId"], repeated["decisionId"])

        restarted = PersonalContextObservability(
            self.db_path,
            project="rag-ime",
        )
        snapshot = restarted.snapshot(session_id=session_id)

        self.assertEqual(snapshot["revisions"]["pinnedRevisionId"], active["revisionId"])
        self.assertEqual(snapshot["evidence"]["total"], 1)
        self.assertEqual(snapshot["bootstrap"]["deliveryCount"], 1)
        self.assertEqual(snapshot["bootstrap"]["sessionsWithMultipleDeliveries"], 0)
        self.assertEqual(snapshot["runtime"]["toolCallCount"], 1)
        self.assertEqual(snapshot["runtime"]["tokens"]["totalTokens"], 35)
        self.assertEqual(snapshot["runtime"]["latencyMs"]["p95"], 100)
        self.assertEqual(snapshot["drafts"]["latestDecisionByOutcome"]["accepted"], 1)
        self.assertEqual(snapshot["drafts"]["acceptanceRate"], 1.0)
        self.assertEqual(snapshot["drafts"]["generatedByKind"]["user_memory"], 1)
        self.assertEqual(snapshot["drafts"]["generatedByKind"]["role_book"], 1)
        self.assertFalse(snapshot["privacy"]["rawTextIncluded"])

        encoded = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("用户原始私密句子", encoded)
        self.assertNotIn("审核备注", encoded)
        self.assertIn(decision["reasonSha256"], encoded)

    def test_draft_outcomes_are_latest_per_draft(self) -> None:
        self.observability.record_draft_decision(
            draft_kind="user_memory",
            draft_id="draft:deferred-then-accepted",
            decision="deferred",
            role_id="companion-present-v1",
            created_at_ms=100,
        )
        self.observability.record_draft_decision(
            draft_kind="user_memory",
            draft_id="draft:deferred-then-accepted",
            decision="accepted",
            role_id="companion-present-v1",
            created_at_ms=200,
        )
        self.observability.record_draft_decision(
            draft_kind="user_memory",
            draft_id="draft:rejected",
            decision="rejected",
            role_id="companion-present-v1",
            created_at_ms=300,
        )

        snapshot = self.observability.snapshot(role_id="companion-present-v1")
        self.assertEqual(
            snapshot["drafts"]["latestDecisionByOutcome"],
            {"accepted": 1, "rejected": 1},
        )
        self.assertEqual(snapshot["drafts"]["acceptanceRate"], 0.5)


if __name__ == "__main__":
    unittest.main()
