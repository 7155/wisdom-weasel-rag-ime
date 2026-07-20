from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionNotFound, AgentSessionStore


class AgentSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-sessions-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = AgentSessionStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_rejects_empty_model_profile_before_insert(self) -> None:
        with self.assertRaisesRegex(ValueError, "model profile must not be empty"):
            self.store.create(title="bad", model_profile="  ")

        self.assertEqual(self.store.list(), [])
        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0]
        self.assertEqual(count, 0)

    def test_list_recovers_legacy_empty_model_profile(self) -> None:
        session = self.store.create(title="legacy", model_profile="pi/default")
        session_id = str(session["id"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE agent_sessions SET model_profile = '' WHERE id = ?",
                (session_id,),
            )
            conn.commit()

        self.assertEqual(self.store.get(session_id)["modelProfile"], "pi/default")
        self.assertEqual(self.store.list()[0]["modelProfile"], "pi/default")

    def test_create_list_bind_archive_restore_and_delete(self) -> None:
        session = self.store.create(title=" 输入助手   今天 ", created_at_ms=100)
        session_id = str(session["id"])

        self.assertEqual(session["title"], "输入助手 今天")
        self.assertEqual(session["mode"], "assistant")
        self.assertEqual(session["roleId"], "vcp-v1")
        self.assertEqual(session["modelProfile"], "gpt/gpt-5.6-sol")
        self.assertEqual(session["thinkingLevel"], "max")
        self.assertTrue(session["projectContextEnabled"])
        self.assertFalse(session["piSkillsEnabled"])
        self.assertFalse(session["codexSkillsEnabled"])
        self.assertEqual(session["workspaceRoots"], [])
        self.assertEqual(self.store.list()[0]["id"], session_id)

        without_project_context = self.store.set_runtime_policy(
            session_id,
            mode="assistant",
            tool_profile_version="control-center-v1",
            allowed_tools=None,
            project_context_enabled=False,
            pi_skills_enabled=True,
            codex_skills_enabled=True,
            updated_at_ms=150,
        )
        self.assertFalse(without_project_context["projectContextEnabled"])
        self.assertTrue(without_project_context["piSkillsEnabled"])
        self.assertTrue(without_project_context["codexSkillsEnabled"])

        bound = self.store.bind_pi_session(
            session_id,
            pi_session_id="pi-1",
            session_file="/managed/sessions/pi-1.jsonl",
            message_count=3,
            updated_at_ms=200,
        )
        self.assertEqual(bound["status"], "active")
        self.assertEqual(bound["messageCount"], 3)
        self.assertEqual(bound["runtimeBinding"]["runtimeKind"], "pi_rpc")
        self.assertEqual(bound["runtimeBinding"]["generation"], 1)
        private_binding = self.store.runtime_binding(session_id)
        self.assertEqual(private_binding["transcriptRef"], "/managed/sessions/pi-1.jsonl")

        rebound = self.store.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id="pi-1",
            transcript_ref="/managed/sessions/pi-1.jsonl",
            binding_state="active",
            message_count=4,
            updated_at_ms=220,
        )
        self.assertEqual(rebound["runtimeBinding"]["generation"], 2)
        with self.assertRaisesRegex(ValueError, "cannot change runtime driver"):
            self.store.bind_runtime_session(
                session_id,
                driver_id="remote-gateway",
                runtime_kind="gateway_http",
                external_session_id="remote-1",
            )

        selected = self.store.set_model_profile(
            session_id,
            "openrouter/anthropic/claude-sonnet",
            updated_at_ms=250,
        )
        self.assertEqual(selected["modelProfile"], "openrouter/anthropic/claude-sonnet")

        archived = self.store.archive(session_id, updated_at_ms=300)
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self.store.list(), [])
        self.assertEqual(len(self.store.list(include_archived=True)), 1)

        restored = self.store.archive(session_id, archived=False, updated_at_ms=400)
        self.assertEqual(restored["status"], "idle")
        deleted = self.store.delete(session_id)
        self.assertEqual(deleted["id"], session_id)
        with self.assertRaises(AgentSessionNotFound):
            self.store.get(session_id)

    def test_assistant_rejects_workspace_and_coordinator_persists_normalized_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot carry workspace roots"):
            self.store.create(title="bad", workspace_roots=[self.tmp.name])

        coordinator = self.store.create(
            title="运行协调",
            mode="coordinator",
            workspace_roots=[self.tmp.name, self.tmp.name],
            created_at_ms=100,
        )
        self.assertEqual(coordinator["workspaceRoots"], [str(Path(self.tmp.name).resolve())])
        self.assertEqual(coordinator["shellPolicyVersion"], "coordinator-per-command-v1")

        switched = self.store.set_mode(
            str(coordinator["id"]),
            "assistant",
            updated_at_ms=200,
        )
        self.assertEqual(switched["mode"], "assistant")
        self.assertEqual(switched["workspaceRoots"], [])
        self.assertEqual(switched["shellPolicyVersion"], "assistant-no-shell-v1")

        switched_back = self.store.set_mode(
            str(coordinator["id"]),
            "coordinator",
            workspace_roots=[self.tmp.name],
            updated_at_ms=300,
        )
        self.assertEqual(switched_back["mode"], "coordinator")
        self.assertEqual(switched_back["workspaceRoots"], [str(Path(self.tmp.name).resolve())])

    def test_role_book_revision_can_only_be_pinned_once(self) -> None:
        session = self.store.create(title="pinned role book", created_at_ms=100)
        session_id = str(session["id"])

        first = self.store.set_role_book_revision(
            session_id,
            "role-book:one",
            updated_at_ms=200,
        )
        repeated = self.store.set_role_book_revision(
            session_id,
            "role-book:one",
            updated_at_ms=300,
        )

        self.assertEqual(first["roleBookRevisionId"], "role-book:one")
        self.assertEqual(repeated["roleBookRevisionId"], "role-book:one")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.store.set_role_book_revision(
                session_id,
                "role-book:two",
                updated_at_ms=400,
            )

    def test_runtime_event_sequence_survives_store_recreation(self) -> None:
        session = self.store.create(title="sequence", created_at_ms=100)
        session_id = str(session["id"])
        for sequence in range(1, 4):
            self.store.record_runtime_event(
                event_id=f"{session_id}:{sequence}",
                session_id=session_id,
                turn_id="turn-1",
                sequence=sequence,
                event_type="status_changed",
                created_at_ms=100 + sequence,
                redacted_summary="busy",
            )

        recreated = AgentSessionStore(self.db_path)
        recreated.initialize()
        self.assertEqual(recreated.max_event_sequence(session_id), 3)

        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM agent_runtime_events WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_agent_plan_is_append_only_and_projects_latest_item_state(self) -> None:
        session = self.store.create(title="plan", created_at_ms=100)
        session_id = str(session["id"])

        created = self.store.update_agent_plan_item(
            session_id,
            title="核对权限边界",
            status="pending",
            updated_at_ms=200,
        )
        item_id = str(created["event"]["itemId"])
        advanced = self.store.update_agent_plan_item(
            session_id,
            item_id=item_id,
            status="in_progress",
            updated_at_ms=300,
        )

        self.assertEqual(advanced["plan"]["revision"], 2)
        self.assertEqual(
            advanced["plan"]["items"],
            [
                {
                    "id": item_id,
                    "title": "核对权限边界",
                    "status": "in_progress",
                    "position": 1,
                    "sequence": 2,
                    "updatedAtMs": 300,
                }
            ],
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            events = conn.execute(
                """
                SELECT sequence, status FROM agent_plan_events
                WHERE session_id = ? ORDER BY sequence
                """,
                (session_id,),
            ).fetchall()
        self.assertEqual(events, [(1, "pending"), (2, "in_progress")])

    def test_agent_plan_allows_only_one_in_progress_item(self) -> None:
        session = self.store.create(title="plan", created_at_ms=100)
        session_id = str(session["id"])
        first = self.store.update_agent_plan_item(
            session_id,
            title="第一项",
            status="in_progress",
        )
        second = self.store.update_agent_plan_item(
            session_id,
            title="第二项",
            status="pending",
        )

        with self.assertRaisesRegex(ValueError, "only one"):
            self.store.update_agent_plan_item(
                session_id,
                item_id=str(second["event"]["itemId"]),
                status="in_progress",
            )
        self.store.update_agent_plan_item(
            session_id,
            item_id=str(first["event"]["itemId"]),
            status="completed",
        )
        promoted = self.store.update_agent_plan_item(
            session_id,
            item_id=str(second["event"]["itemId"]),
            status="in_progress",
        )
        self.assertEqual(promoted["plan"]["counts"]["inProgress"], 1)
        self.assertEqual(promoted["plan"]["counts"]["completed"], 1)

    def test_agent_plan_keeps_creation_order_when_item_status_changes(self) -> None:
        session = self.store.create(title="stable plan", created_at_ms=100)
        session_id = str(session["id"])
        first = self.store.update_agent_plan_item(
            session_id,
            title="读取现状",
            status="pending",
            updated_at_ms=200,
        )
        second = self.store.update_agent_plan_item(
            session_id,
            title="实现界面",
            status="pending",
            updated_at_ms=300,
        )
        self.store.update_agent_plan_item(
            session_id,
            item_id=str(first["event"]["itemId"]),
            status="completed",
            updated_at_ms=400,
        )
        plan = self.store.update_agent_plan_item(
            session_id,
            item_id=str(second["event"]["itemId"]),
            status="in_progress",
            updated_at_ms=500,
        )["plan"]

        self.assertEqual(
            [item["title"] for item in plan["items"]],
            ["读取现状", "实现界面"],
        )
        self.assertEqual(
            [item["status"] for item in plan["items"]],
            ["completed", "in_progress"],
        )

    def test_plan_review_gate_preserves_approved_scope_and_tracks_execution(self) -> None:
        session = self.store.create(title="reviewed plan", created_at_ms=100)
        session_id = str(session["id"])
        saved = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "save",
                "title": "交付 Goal Mode",
                "items": [
                    {"title": "核对契约", "status": "pending"},
                    {"title": "实现并验收", "status": "pending"},
                ],
            },
            updated_at_ms=200,
        )["plan"]
        first_id, second_id = [str(item["id"]) for item in saved["items"]]

        reordered = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "save",
                "expectedRevision": saved["revision"],
                "title": "交付 Goal Mode",
                "items": [
                    {"id": second_id, "title": "实现并验收", "status": "pending"},
                    {"id": first_id, "title": "核对契约", "status": "pending"},
                ],
            },
            updated_at_ms=300,
        )["plan"]
        self.assertEqual([item["id"] for item in reordered["items"]], [second_id, first_id])
        self.assertEqual([item["position"] for item in reordered["items"]], [1, 2])

        review = self.store.mutate_agent_plan(
            session_id,
            {"action": "submit_review", "expectedRevision": reordered["revision"]},
            updated_at_ms=400,
        )["plan"]
        self.assertEqual(review["status"], "review")
        self.assertEqual(self.store.workflow_state(session_id)["actGate"]["reason"], "plan_not_approved")
        with self.assertRaisesRegex(ValueError, "while plan is review"):
            self.store.update_agent_plan_item(session_id, item_id=second_id, status="in_progress")

        approved = self.store.mutate_agent_plan(
            session_id,
            {"action": "approve", "expectedRevision": review["revision"]},
            updated_at_ms=500,
        )["plan"]
        self.assertEqual(approved["status"], "approved")
        self.assertTrue(self.store.workflow_state(session_id)["actGate"]["allowed"])
        with self.assertRaisesRegex(ValueError, "titles cannot change"):
            self.store.update_agent_plan_item(
                session_id,
                item_id=second_id,
                title="悄悄扩大范围",
            )
        with self.assertRaisesRegex(ValueError, "cannot add new items"):
            self.store.update_agent_plan_item(session_id, title="未审阅步骤", status="pending")

        executing = self.store.begin_agent_plan_execution(session_id)["plan"]
        self.assertEqual(executing["status"], "executing")
        self.store.update_agent_plan_item(session_id, item_id=second_id, status="completed")
        finished_items = self.store.update_agent_plan_item(
            session_id,
            item_id=first_id,
            status="completed",
        )["plan"]
        completed = self.store.mutate_agent_plan(
            session_id,
            {"action": "complete", "expectedRevision": finished_items["revision"]},
            updated_at_ms=600,
        )["plan"]
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["actApproved"])

    def test_thread_goal_budget_pause_and_evidence_audit_control_act_gate(self) -> None:
        session = self.store.create(title="goal", created_at_ms=100)
        session_id = str(session["id"])
        plan = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "submit_review",
                "title": "完成 Goal",
                "items": [{"title": "实现并验证", "status": "pending"}],
            },
        )["plan"]
        self.store.mutate_agent_plan(
            session_id,
            {"action": "approve", "expectedRevision": plan["revision"]},
        )

        goal = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "set",
                "objective": "在固定预算内交付可验证实现",
                "tokenBudget": 1_000,
                "timeBudgetMs": 60_000,
            },
        )["workflow"]["goal"]
        usage = self.store.record_agent_goal_usage(
            session_id,
            idempotency_key="turn:1:usage",
            turn_id="turn:1",
            event_id="event:1",
            token_delta=600,
            elapsed_delta_ms=30_000,
        )["goal"]
        self.assertEqual(usage["usage"], {"tokens": 600, "elapsedMs": 30_000})
        duplicate = self.store.record_agent_goal_usage(
            session_id,
            idempotency_key="turn:1:usage",
            turn_id="turn:1",
            event_id="event:1",
            token_delta=600,
            elapsed_delta_ms=30_000,
        )["goal"]
        self.assertEqual(duplicate["usage"], {"tokens": 600, "elapsedMs": 30_000})
        with self.assertRaisesRegex(ValueError, "reused with different data"):
            self.store.record_agent_goal_usage(
                session_id,
                idempotency_key="turn:1:usage",
                turn_id="turn:1",
                event_id="event:1",
                token_delta=601,
                elapsed_delta_ms=30_000,
            )

        paused = self.store.mutate_agent_goal(
            session_id,
            {"action": "pause", "expectedRevision": usage["revision"]},
        )["workflow"]
        self.assertEqual(paused["actGate"]["reason"], "goal_paused")
        with self.assertRaisesRegex(ValueError, "goal_paused"):
            self.store.require_goal_execution(session_id)
        resumed = self.store.mutate_agent_goal(
            session_id,
            {"action": "resume", "expectedRevision": paused["goal"]["revision"]},
        )["workflow"]["goal"]
        exhausted = self.store.record_agent_goal_usage(
            session_id,
            idempotency_key="turn:2:usage",
            turn_id="turn:2",
            event_id="event:2",
            token_delta=400,
            elapsed_delta_ms=1,
        )
        self.assertTrue(exhausted["goal"]["budgetExceeded"])
        self.assertEqual(exhausted["actGate"]["reason"], "goal_budget_exhausted")
        with self.assertRaisesRegex(ValueError, "goal_budget_exhausted"):
            self.store.require_goal_execution(session_id)

        expanded = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "update",
                "expectedRevision": exhausted["goal"]["revision"],
                "objective": goal["objective"],
                "tokenBudget": 2_000,
                "timeBudgetMs": 120_000,
            },
        )["workflow"]["goal"]
        completed = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "complete",
                "expectedRevision": expanded["revision"],
                "summary": "契约、测试与产物均已验收",
                "evidence": [
                    {
                        "kind": "test",
                        "summary": "聚焦测试通过",
                        "reference": "python3 -m unittest tests.test_agent_sessions",
                    }
                ],
            },
        )["workflow"]
        self.assertEqual(completed["goal"]["completionAudit"]["evidence"][0]["kind"], "test")
        self.assertEqual(completed["actGate"]["reason"], "goal_completed")
        cleared = self.store.mutate_agent_goal(
            session_id,
            {"action": "clear", "expectedRevision": completed["goal"]["revision"]},
        )["workflow"]
        self.assertFalse(cleared["goal"]["configured"])
        self.assertTrue(cleared["actGate"]["allowed"])

    def test_unknown_mode_and_status_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "assistant or coordinator"):
            self.store.create(title="bad", mode="admin")
        session = self.store.create(title="safe", created_at_ms=100)
        with self.assertRaisesRegex(ValueError, "unsupported agent session status"):
            self.store.set_status(str(session["id"]), "executing_without_approval")
        with self.assertRaisesRegex(ValueError, "provider/model"):
            self.store.set_model_profile(str(session["id"]), "missing-provider")

    def test_approval_is_hash_bound_expiring_and_receipted(self) -> None:
        session = self.store.create(title="approval", created_at_ms=100)
        session_id = str(session["id"])
        approval = self.store.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation="apply_settings",
            payload_sha256="a" * 64,
            preview={"summary": "关闭模糊音", "changes": [{"field": "pinyin.fuzzy", "after": False}]},
            risk_level="R1",
            requested_at_ms=1_000,
            ttl_ms=60_000,
        )
        self.assertEqual(approval["state"], "pending")
        self.assertEqual(self.store.list_approvals(session_id=session_id, now_ms=2_000), [approval])

        decided = self.store.decide_approval(
            str(approval["approvalId"]),
            approved=True,
            payload_sha256="a" * 64,
            decided_at_ms=2_000,
        )
        self.assertEqual(decided["state"], "approved")
        applied = self.store.complete_approval(
            str(approval["approvalId"]),
            state="applied",
            receipt={"auditId": 42, "rollbackAvailable": True},
        )
        self.assertEqual(applied["state"], "applied")
        self.assertEqual(applied["receipt"]["auditId"], 42)

        external = self.store.create_approval(
            session_id=session_id,
            tool_name="ime_runtime",
            operation="restart_sidecar",
            payload_sha256="e" * 64,
            preview={"summary": "重启 Sidecar"},
            risk_level="R2",
            requested_at_ms=2_100,
        )
        external_decided = self.store.decide_approval(
            str(external["approvalId"]),
            approved=True,
            payload_sha256="e" * 64,
            decided_at_ms=2_200,
        )
        external_pending = self.store.complete_approval(
            str(external_decided["approvalId"]),
            state="external_pending",
            receipt={"externalActionPending": True, "externalAction": "restart_sidecar"},
        )
        self.assertEqual(external_pending["state"], "external_pending")
        external_applied = self.store.finalize_external_approval(
            str(external["approvalId"]),
            state="applied",
            receipt={"externalActionPending": False, "mutationApplied": True},
        )
        self.assertEqual(external_applied["state"], "applied")
        with self.assertRaisesRegex(ValueError, "cannot complete from state applied"):
            self.store.finalize_external_approval(
                str(external["approvalId"]),
                state="failed",
                receipt={"mutationApplied": False},
            )

        stale = self.store.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation="apply_settings",
            payload_sha256="b" * 64,
            preview={"summary": "变更已过期"},
            risk_level="R1",
            requested_at_ms=3_000,
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            self.store.decide_approval(
                str(stale["approvalId"]),
                approved=True,
                payload_sha256="c" * 64,
                decided_at_ms=4_000,
            )
        self.assertEqual(self.store.get_approval(str(stale["approvalId"]), now_ms=4_000)["state"], "stale")

        expired = self.store.create_approval(
            session_id=session_id,
            tool_name="ime_runtime",
            operation="restart",
            payload_sha256="d" * 64,
            preview={"summary": "重启运行组件"},
            risk_level="R2",
            requested_at_ms=5_000,
            ttl_ms=1_000,
        )
        self.assertEqual(self.store.get_approval(str(expired["approvalId"]), now_ms=6_000)["state"], "expired")
        with self.assertRaisesRegex(ValueError, "already expired"):
            self.store.decide_approval(
                str(expired["approvalId"]),
                approved=True,
                payload_sha256="d" * 64,
                decided_at_ms=6_001,
            )


if __name__ == "__main__":
    unittest.main()
