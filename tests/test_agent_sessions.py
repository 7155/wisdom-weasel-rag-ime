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

    def test_create_list_bind_archive_restore_and_delete(self) -> None:
        session = self.store.create(title=" 输入助手   今天 ", created_at_ms=100)
        session_id = str(session["id"])

        self.assertEqual(session["title"], "输入助手 今天")
        self.assertEqual(session["mode"], "assistant")
        self.assertEqual(session["workspaceRoots"], [])
        self.assertEqual(self.store.list()[0]["id"], session_id)

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
