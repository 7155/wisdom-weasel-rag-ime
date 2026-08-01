from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionNotFound, AgentSessionStore
from rag_ime.contracts.json_schema import validate_contract


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

    def test_retired_builtin_role_ids_are_read_only_compatibility_aliases(
        self,
    ) -> None:
        session = self.store.create(
            title="canonical identity",
            role_id="vcp-v1",
            role_book_revision_id="role-book:vcp-v1:1:test",
        )

        self.assertEqual(session["roleId"], "companion-future-v1")
        self.assertEqual(
            session["roleBookRevisionId"],
            "role-book:companion-future-v1:1:test",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            stored = conn.execute(
                """
                SELECT role_id, role_book_revision_id
                FROM agent_sessions
                WHERE id = ?
                """,
                (session["id"],),
            ).fetchone()
        self.assertEqual(
            stored,
            (
                "companion-future-v1",
                "role-book:companion-future-v1:1:test",
            ),
        )

    def test_create_list_bind_archive_restore_and_delete(self) -> None:
        session = self.store.create(title=" 输入助手   今天 ", created_at_ms=100)
        session_id = str(session["id"])

        self.assertEqual(session["title"], "输入助手 今天")
        self.assertEqual(session["mode"], "assistant")
        self.assertEqual(session["roleId"], "companion-future-v1")
        self.assertEqual(session["modelProfile"], "openai-codex/gpt-5.6-sol")
        self.assertEqual(session["thinkingLevel"], "max")
        self.assertEqual(session["executionMode"], "per_action")
        self.assertFalse(session["workspaceScopeGranted"])
        self.assertFalse(session["projectContextEnabled"])
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

    def test_workspace_execution_grant_is_invalidated_and_can_be_regranted(self) -> None:
        first_root = self.tmp.name
        second_root = str(Path(self.tmp.name) / "second")
        Path(second_root).mkdir()
        session = self.store.create(
            title="托管工作区",
            mode="coordinator",
            execution_mode="workspace_managed",
            workspace_roots=[first_root],
            created_at_ms=100,
        )

        self.assertEqual(session["executionMode"], "workspace_managed")
        self.assertTrue(session["workspaceScopeGranted"])
        first_digest = session["workspaceScopeSha256"]

        unchanged = self.store.set_runtime_policy(
            str(session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="workspace_managed",
            allowed_tools=None,
            workspace_roots=[first_root],
            updated_at_ms=200,
        )
        self.assertTrue(unchanged["workspaceScopeGranted"])
        self.assertEqual(unchanged["workspaceScopeSha256"], first_digest)

        changed = self.store.set_runtime_policy(
            str(session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="workspace_managed",
            allowed_tools=None,
            workspace_roots=[second_root],
            updated_at_ms=300,
        )
        self.assertFalse(changed["workspaceScopeGranted"])
        self.assertEqual(changed["workspaceScopeSha256"], "")

        regranted = self.store.set_runtime_policy(
            str(session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="workspace_managed",
            grant_workspace_scope=True,
            allowed_tools=None,
            workspace_roots=[second_root],
            updated_at_ms=400,
        )
        self.assertTrue(regranted["workspaceScopeGranted"])
        self.assertNotEqual(regranted["workspaceScopeSha256"], first_digest)

        per_action = self.store.set_runtime_policy(
            str(session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="per_action",
            allowed_tools=None,
            workspace_roots=[second_root],
            updated_at_ms=500,
        )
        self.assertFalse(per_action["workspaceScopeGranted"])
        self.assertEqual(per_action["workspaceScopeSha256"], "")

    def test_legacy_auto_approve_profile_is_not_persisted_as_new_policy(self) -> None:
        session = self.store.create(
            title="旧策略兼容",
            mode="coordinator",
            tool_profile_version="control-center-auto-approve-v1",
            workspace_roots=[self.tmp.name],
            created_at_ms=100,
        )

        self.assertEqual(session["executionMode"], "full_trust")
        self.assertEqual(session["toolProfileVersion"], "control-center-v1")
        self.assertTrue(session["workspaceScopeGranted"])

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

    def test_agent_plan_serializes_concurrent_in_progress_transitions(self) -> None:
        session_id = str(self.store.create(title="concurrent plan")["id"])
        first_id = str(
            self.store.update_agent_plan_item(
                session_id,
                title="第一项",
                status="pending",
            )["event"]["itemId"]
        )
        second_id = str(
            self.store.update_agent_plan_item(
                session_id,
                title="第二项",
                status="pending",
            )["event"]["itemId"]
        )

        def promote(item_id: str) -> str:
            try:
                self.store.update_agent_plan_item(
                    session_id,
                    item_id=item_id,
                    status="in_progress",
                )
            except ValueError as exc:
                self.assertIn("only one", str(exc))
                return "blocked"
            return "promoted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(promote, (first_id, second_id)))

        self.assertEqual(sorted(outcomes), ["blocked", "promoted"])
        plan = self.store.agent_plan(session_id)
        self.assertEqual(plan["counts"]["inProgress"], 1)
        self.assertEqual(plan["revision"], 3)
        with closing(sqlite3.connect(self.db_path)) as conn:
            sequences = [
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT sequence FROM agent_plan_events
                    WHERE session_id = ? ORDER BY sequence
                    """,
                    (session_id,),
                ).fetchall()
            ]
        self.assertEqual(sequences, [1, 2, 3])

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

    def test_completed_plan_can_finish_without_a_late_approval_transition(self) -> None:
        for submitted_for_review in (False, True):
            with self.subTest(submitted_for_review=submitted_for_review):
                session_id = str(
                    self.store.create(
                        title=f"complete plan {submitted_for_review}",
                    )["id"]
                )
                plan = self.store.mutate_agent_plan(
                    session_id,
                    {
                        "action": "save",
                        "title": "已按用户请求执行",
                        "items": [{"title": "完成并核验", "status": "completed"}],
                    },
                )["plan"]
                if submitted_for_review:
                    plan = self.store.mutate_agent_plan(
                        session_id,
                        {
                            "action": "submit_review",
                            "expectedRevision": plan["revision"],
                        },
                    )["plan"]
                    self.assertEqual(plan["status"], "review")
                completed = self.store.mutate_agent_plan(
                    session_id,
                    {
                        "action": "complete",
                        "expectedRevision": plan["revision"],
                    },
                )["plan"]
                self.assertEqual(completed["status"], "completed")

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
        review_gate = self.store.workflow_state(session_id)["actGate"]
        self.assertTrue(review_gate["allowed"])
        self.assertEqual(review_gate["reason"], "user_execution_request")
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

        executing = self.store.record_agent_plan_execution_started(session_id)["plan"]
        self.assertEqual(executing["status"], "executing")
        replayed_execution = self.store.record_agent_plan_execution_started(
            session_id
        )["plan"]
        self.assertEqual(replayed_execution["revision"], executing["revision"])
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
        completed_state = self.store.workflow_state(session_id)
        validate_contract(
            completed_state,
            "agent-workflow-state.v1.json",
        )
        completed_gate = completed_state["actGate"]
        self.assertTrue(completed_gate["allowed"])
        self.assertEqual(completed_gate["reason"], "user_execution_request")
        self.assertIn("原有策略审批", completed_gate["message"])

    def test_cancelled_plan_does_not_revoke_a_new_user_execution_request(self) -> None:
        session_id = str(self.store.create(title="cancelled")["id"])
        saved = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "save",
                "title": "取消前计划",
                "items": [{"title": "不再执行", "status": "pending"}],
            },
        )["plan"]
        self.store.mutate_agent_plan(
            session_id,
            {
                "action": "cancel",
                "expectedRevision": saved["revision"],
            },
        )

        state = self.store.workflow_state(session_id)
        validate_contract(state, "agent-workflow-state.v1.json")
        self.assertTrue(state["actGate"]["allowed"])
        self.assertEqual(state["actGate"]["reason"], "user_execution_request")


    def test_plan_return_to_draft_requires_provenance_and_rejects_replay(
        self,
    ) -> None:
        session_id = str(self.store.create(title="review provenance")["id"])
        review = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "submit_review",
                "title": "审阅计划",
                "items": [{"title": "修复反馈", "status": "pending"}],
            },
        )["plan"]
        with self.assertRaisesRegex(ValueError, "note must not be empty"):
            self.store.mutate_agent_plan(
                session_id,
                {
                    "action": "return_to_draft",
                    "expectedRevision": review["revision"],
                },
                actor="reviewer:alice",
            )

        returned = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "return_to_draft",
                "expectedRevision": review["revision"],
                "note": "补充失败路径与验收证据",
            },
            actor="reviewer:alice",
            updated_at_ms=777,
        )["plan"]
        self.assertEqual(returned["status"], "draft")
        self.assertEqual(returned["actor"], "reviewer:alice")
        self.assertEqual(returned["note"], "补充失败路径与验收证据")
        with self.assertRaisesRegex(ValueError, "changed; refresh"):
            self.store.mutate_agent_plan(
                session_id,
                {
                    "action": "return_to_draft",
                    "expectedRevision": review["revision"],
                    "note": "重复提交",
                },
                actor="reviewer:alice",
            )
        self.assertEqual(
            AgentSessionStore(self.db_path).agent_plan(session_id),
            returned,
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.store.mutate_agent_plan(
                session_id,
                {
                    "action": "start_execution",
                    "expectedRevision": returned["revision"],
                },
            )

    def test_plan_and_goal_mutation_contracts_require_review_and_setup_fences(
        self,
    ) -> None:
        validate_contract(
            {
                "action": "return_to_draft",
                "expectedRevision": 4,
                "note": "补充验收证据",
            },
            "agent-plan-mutation.v1.json",
        )
        with self.assertRaisesRegex(ValueError, "missing required field"):
            validate_contract(
                {"action": "return_to_draft", "expectedRevision": 4},
                "agent-plan-mutation.v1.json",
            )
        validate_contract(
            {
                "action": "confirm_setup",
                "expectedRevision": 0,
                "confirmed": True,
                "objective": "交付可验证结果",
                "successCriteria": "验收通过",
                "evidenceExpectations": ["测试回执"],
            },
            "agent-goal-mutation.v1.json",
        )
        with self.assertRaisesRegex(ValueError, "missing required field"):
            validate_contract(
                {
                    "action": "confirm_setup",
                    "confirmed": True,
                    "objective": "缺少 revision",
                },
                "agent-goal-mutation.v1.json",
            )
        with self.assertRaisesRegex(ValueError, "missing required field"):
            validate_contract(
                {
                    "action": "cancel",
                    "expectedRevision": 1,
                },
                "agent-goal-mutation.v1.json",
            )


    def test_fenced_room_dispatch_is_a_work_authority_without_rewriting_the_plan(self) -> None:
        session = self.store.create(title="Room worker", created_at_ms=100)
        session_id = str(session["id"])

        ordinary = self.store.workflow_state(session_id)
        room = self.store.require_workspace_act(
            session_id,
            room_dispatch_authorized=True,
        )

        self.assertTrue(ordinary["actGate"]["allowed"])
        self.assertEqual(ordinary["actGate"]["reason"], "user_execution_request")
        self.assertEqual(room["plan"]["status"], "draft")
        self.assertTrue(room["actGate"]["allowed"])
        self.assertIn("当前 Room 任务已经开始", room["actGate"]["message"])

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
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": 0,
                "successCriteria": "所有计划项完成并有可核验回执",
                "evidenceExpectations": ["聚焦测试结果", "交付产物引用"],
                "objective": "在固定预算内交付可验证实现",
                "tokenBudget": 1_000,
                "timeBudgetMs": 60_000,
            },
        )["workflow"]["goal"]
        self.assertEqual(
            goal["successCriteria"],
            "所有计划项完成并有可核验回执",
        )
        self.assertEqual(
            goal["evidenceExpectations"],
            ["聚焦测试结果", "交付产物引用"],
        )
        reconnected_goal = AgentSessionStore(self.db_path).agent_goal(session_id)
        self.assertEqual(reconnected_goal, goal)
        workflow = self.store.workflow_state(session_id)
        self.assertEqual(
            workflow["actGate"]["planRevision"],
            workflow["plan"]["revision"],
        )
        self.assertEqual(
            workflow["actGate"]["goalRevision"],
            workflow["goal"]["revision"],
        )
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

    def test_cancelled_goal_is_terminal_audited_and_blocks_future_work(
        self,
    ) -> None:
        session_id = str(self.store.create(title="cancelled goal")["id"])
        review = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "submit_review",
                "title": "可取消 Goal",
                "items": [{"title": "执行工作", "status": "in_progress"}],
            },
        )["plan"]
        self.store.mutate_agent_plan(
            session_id,
            {"action": "approve", "expectedRevision": review["revision"]},
        )
        goal = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": 0,
                "objective": "在用户终止前持续执行",
                "successCriteria": "用户验收",
                "evidenceExpectations": ["运行回执"],
            },
            actor="control-center-user",
        )["workflow"]["goal"]
        cancelled = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "cancel",
                "expectedRevision": goal["revision"],
                "reason": "目标优先级已经变化",
            },
            actor="user:owner",
            updated_at_ms=900,
        )["workflow"]

        self.assertEqual(cancelled["goal"]["status"], "cancelled")
        self.assertEqual(cancelled["actGate"]["reason"], "goal_cancelled")
        self.assertEqual(
            cancelled["goal"]["cancellationAudit"]["reason"],
            "目标优先级已经变化",
        )
        self.assertEqual(
            cancelled["goal"]["cancellationAudit"]["cancelledBy"],
            "user:owner",
        )
        validate_contract(cancelled, "agent-workflow-state.v1.json")
        reconnected = AgentSessionStore(self.db_path).workflow_state(session_id)
        self.assertEqual(reconnected, cancelled)
        with self.assertRaisesRegex(ValueError, "goal_cancelled"):
            self.store.require_goal_execution(session_id)
        with self.assertRaisesRegex(ValueError, "active goal"):
            self.store.record_agent_goal_usage(
                session_id,
                idempotency_key="cancelled:usage",
                token_delta=1,
            )
        continuation = self.store.claim_agent_goal_continuation(
            session_id,
            goal_id=str(goal["goalId"]),
            request_key="cancelled:continuation",
            limit=4,
        )
        self.assertFalse(continuation["claimed"])
        self.assertEqual(continuation["reason"], "goal_cancelled")
        with self.assertRaisesRegex(ValueError, "changed; refresh"):
            self.store.mutate_agent_goal(
                session_id,
                {
                    "action": "cancel",
                    "expectedRevision": goal["revision"],
                    "reason": "重复提交",
                },
            )
        self.assertEqual(
            self.store.agent_goal(session_id)["cancellationAudit"],
            cancelled["goal"]["cancellationAudit"],
        )
        with self.assertRaisesRegex(ValueError, "active or paused"):
            self.store.mutate_agent_goal(
                session_id,
                {
                    "action": "update",
                    "expectedRevision": cancelled["goal"]["revision"],
                    "objective": "不能复活的目标",
                },
            )
        cleared = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "clear",
                "expectedRevision": cancelled["goal"]["revision"],
            },
        )["workflow"]
        self.assertFalse(cleared["goal"]["configured"])
        self.assertEqual(cleared["goal"]["status"], "cleared")
        self.assertTrue(cleared["actGate"]["allowed"])


    def test_goal_continuation_budget_persists_and_resets_only_on_lifecycle(
        self,
    ) -> None:
        session = self.store.create(title="goal continuation", created_at_ms=100)
        session_id = str(session["id"])
        review = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "submit_review",
                "title": "完成持久 Goal",
                "items": [{"title": "收集验收证据", "status": "in_progress"}],
            },
        )["plan"]
        self.store.mutate_agent_plan(
            session_id,
            {"action": "approve", "expectedRevision": review["revision"]},
        )
        goal = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": 0,
                "objective": "跨运行时保持续投上限",
            },
        )["workflow"]["goal"]
        goal_id = str(goal["goalId"])

        for index in range(1, 3):
            claim = self.store.claim_agent_goal_continuation(
                session_id,
                goal_id=goal_id,
                request_key=f"scope:{index}:attempt:1",
                limit=4,
                updated_at_ms=100 + index,
            )
            self.assertTrue(claim["claimed"])
            self.assertEqual(claim["issuedCount"], index)
        replay_first = self.store.claim_agent_goal_continuation(
            session_id,
            goal_id=goal_id,
            request_key="scope:1:attempt:1",
            limit=4,
            updated_at_ms=103,
        )
        self.assertTrue(replay_first["claimed"])
        self.assertTrue(replay_first["replayed"])
        self.assertEqual(replay_first["issuedCount"], 2)
        self.assertEqual(replay_first["remaining"], 2)
        for index in range(3, 5):
            claim = self.store.claim_agent_goal_continuation(
                session_id,
                goal_id=goal_id,
                request_key=f"scope:{index}:attempt:1",
                limit=4,
                updated_at_ms=100 + index,
            )
            self.assertTrue(claim["claimed"])
            self.assertEqual(claim["issuedCount"], index)
        replay = self.store.claim_agent_goal_continuation(
            session_id,
            goal_id=goal_id,
            request_key="scope:4:attempt:1",
            limit=4,
            updated_at_ms=200,
        )
        blocked = self.store.claim_agent_goal_continuation(
            session_id,
            goal_id=goal_id,
            request_key="new-process-scope:attempt:1",
            limit=4,
            updated_at_ms=201,
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["issuedCount"], 4)
        self.assertFalse(blocked["claimed"])
        self.assertEqual(blocked["reason"], "goal_continuation_limit")

        paused = self.store.mutate_agent_goal(
            session_id,
            {"action": "pause", "expectedRevision": goal["revision"]},
            updated_at_ms=300,
        )["workflow"]["goal"]
        paused_budget = self.store.agent_goal_continuation_budget(
            session_id,
            goal_id=goal_id,
            limit=4,
        )
        self.assertEqual(paused_budget["issuedCount"], 0)
        self.assertEqual(paused_budget["epoch"], 2)
        resumed = self.store.mutate_agent_goal(
            session_id,
            {"action": "resume", "expectedRevision": paused["revision"]},
            updated_at_ms=301,
        )["workflow"]["goal"]
        with self.assertRaisesRegex(ValueError, "another lifecycle epoch"):
            self.store.claim_agent_goal_continuation(
                session_id,
                goal_id=goal_id,
                request_key="scope:1:attempt:1",
                limit=4,
                updated_at_ms=302,
            )
        resumed_claim = self.store.claim_agent_goal_continuation(
            session_id,
            goal_id=goal_id,
            request_key="after-resume:attempt:1",
            limit=4,
            updated_at_ms=303,
        )
        self.assertTrue(resumed_claim["claimed"])
        self.assertEqual(resumed_claim["issuedCount"], 1)
        self.assertEqual(resumed_claim["epoch"], 3)

        completed = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "complete",
                "expectedRevision": resumed["revision"],
                "summary": "持久续投上限已验证",
                "evidence": [
                    {
                        "kind": "test",
                        "summary": "聚焦测试通过",
                        "reference": "tests.test_agent_sessions",
                    }
                ],
            },
            updated_at_ms=400,
        )["workflow"]["goal"]
        completed_budget = self.store.agent_goal_continuation_budget(
            session_id,
            goal_id=goal_id,
            limit=4,
        )
        self.assertEqual(completed_budget["issuedCount"], 0)
        self.assertEqual(completed_budget["epoch"], 4)
        cleared = self.store.mutate_agent_goal(
            session_id,
            {"action": "clear", "expectedRevision": completed["revision"]},
            updated_at_ms=401,
        )["workflow"]["goal"]
        replacement = self.store.mutate_agent_goal(
            session_id,
            {
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": cleared["revision"],
                "objective": "新的持久 Goal",
            },
            updated_at_ms=402,
        )["workflow"]["goal"]
        replacement_budget = self.store.agent_goal_continuation_budget(
            session_id,
            goal_id=str(replacement["goalId"]),
            limit=4,
        )
        with self.assertRaisesRegex(ValueError, "another goal"):
            self.store.claim_agent_goal_continuation(
                session_id,
                goal_id=str(replacement["goalId"]),
                request_key="scope:1:attempt:1",
                limit=4,
                updated_at_ms=403,
            )
        self.assertFalse(cleared["configured"])
        self.assertNotEqual(replacement["goalId"], goal_id)
        self.assertEqual(
            replacement_budget,
            {"epoch": 1, "issuedCount": 0, "limit": 4, "remaining": 4},
        )

    def test_goal_continuation_budget_serializes_concurrent_claims(self) -> None:
        session_id = str(
            self.store.create(title="concurrent continuation")["id"]
        )
        review = self.store.mutate_agent_plan(
            session_id,
            {
                "action": "submit_review",
                "title": "并发续投上限",
                "items": [{"title": "验证原子上限", "status": "in_progress"}],
            },
        )["plan"]
        self.store.mutate_agent_plan(
            session_id,
            {"action": "approve", "expectedRevision": review["revision"]},
        )
        goal_id = str(
            self.store.mutate_agent_goal(
                session_id,
                {
                    "action": "confirm_setup",
                    "confirmed": True,
                    "expectedRevision": 0,
                    "objective": "并发请求最多续投四次",
                },
            )["workflow"]["goal"]["goalId"]
        )

        def claim(index: int) -> dict[str, object]:
            return self.store.claim_agent_goal_continuation(
                session_id,
                goal_id=goal_id,
                request_key=f"concurrent-scope:{index}",
                limit=4,
                updated_at_ms=500 + index,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, range(8)))

        claimed = [result for result in results if result["claimed"] is True]
        blocked = [result for result in results if result["claimed"] is False]
        self.assertEqual(
            sorted(int(result["issuedCount"]) for result in claimed),
            [1, 2, 3, 4],
        )
        self.assertEqual(len(blocked), 4)
        self.assertTrue(
            all(
                result["reason"] == "goal_continuation_limit"
                for result in blocked
            )
        )
        self.assertEqual(
            self.store.agent_goal_continuation_budget(
                session_id,
                goal_id=goal_id,
                limit=4,
            ),
            {"epoch": 1, "issuedCount": 4, "limit": 4, "remaining": 0},
        )

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
            tool_name="input",
            operation="apply_settings",
            payload_sha256="a" * 64,
            preview={"summary": "关闭模糊音", "changes": [{"field": "pinyin.fuzzy", "after": False}]},
            risk_level="R1",
            requested_at_ms=1_000,
            ttl_ms=60_000,
        )
        self.assertEqual(approval["state"], "pending")
        self.assertEqual(self.store.list_approvals(session_id=session_id, now_ms=2_000), [approval])

        rebound = self.store.rebind_pending_approval(
            str(approval["approvalId"]),
            expected_payload_sha256="a" * 64,
            payload_sha256="f" * 64,
            preview={
                "summary": "关闭模糊音",
                "baseState": {"roomInvocationReceiptId": "invoke:room:1"},
            },
            now_ms=1_500,
            causal_turn_id="root:room:1",
        )
        self.assertEqual(rebound["payloadSha256"], "f" * 64)
        self.assertEqual(
            rebound["preview"]["baseState"]["roomInvocationReceiptId"],
            "invoke:room:1",
        )
        self.assertTrue(rebound["causalMetadata"]["roomBound"])
        self.assertEqual(
            rebound["causalMetadata"]["turnId"],
            "root:room:1",
        )

        decided = self.store.decide_approval(
            str(approval["approvalId"]),
            approved=True,
            payload_sha256="f" * 64,
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
            tool_name="runtime",
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
            tool_name="input",
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
            tool_name="runtime",
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
