from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_worker import RoomKernelWorker
from rag_ime.agent_routes import agent_room_kernel_route


REPO = Path(__file__).resolve().parents[1]


class _AcceptedRuntime:
    def __init__(self) -> None:
        self.active_dispatches: list[str] = []
        self.cancel_calls: list[tuple[str, str, int]] = []

    def dispatch_room(self, payload, *, message: str, lease_token: str):
        self.active_dispatches.append(str(payload["dispatchId"]))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
        }

    def cancel_room(self, *, session_id: str, root_id: str, generation: int):
        self.cancel_calls.append((session_id, root_id, generation))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "rootId": root_id,
            "sessionId": session_id,
            "generation": generation,
            "cancellationSurfaces": {surface: {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": surface, "state": "terminated", "targetIds": [],
            } for surface in (
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session")},
            "pendingTargets": [],
        }


class RoomV2SafetyExitAuditTests(unittest.TestCase):
    """Executable characterization of safety-exit blockers, not readiness claims."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-v2-safety-audit-")
        self.clock = 10
        self.store = RoomKernelStore(Path(self.tmp.name) / "room.sqlite", mode="test")
        self.store.initialize()
        self.runtime = _AcceptedRuntime()
        self.revoked: list[str] = []
        self.worker = RoomKernelWorker(
            self.store,
            self.runtime,
            clock_ms=lambda: self.clock,
            revoke_session=lambda session_id, _now_ms: self.revoked.append(session_id),
        )
        self._seed_dispatch()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_runtime_accept_then_kernel_ack_crash_is_reconciled_by_durable_cancel(self) -> None:
        original = self.store.accept_runtime_receipt

        def crash_after_runtime_effect(**_kwargs):
            raise RuntimeError("simulated process crash after Pi accepted the Dispatch")

        self.store.accept_runtime_receipt = crash_after_runtime_effect  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "after Pi accepted"):
            self.worker.run_once(lease_ttl_ms=5)
        self.store.accept_runtime_receipt = original  # type: ignore[method-assign]

        self.clock = 20
        self.worker.reconcile()
        self.assertEqual(self.store.dispatch("dispatch:1")["state"], "cancelled")
        self.assertEqual(self.runtime.cancel_calls, [("session:b", "root:1", 1)])
        self.assertEqual(self.revoked, ["session:b"])
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertIsNotNone(self.store.root("root:1")["terminalReceiptId"])

    def test_direct_store_cancel_persists_runtime_effect_for_replay(self) -> None:
        self.worker.run_once()
        self.assertEqual(self.store.dispatch("dispatch:1")["state"], "running")

        self.store.cancel_root("root:1", now_ms=20)
        self.clock = 20
        self.worker.drain_cancel_outbox()
        self.assertEqual(self.runtime.cancel_calls, [("session:b", "root:1", 1)])
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")

    def test_source_census_records_live_context_and_governed_cutover_paths(self) -> None:
        service = (REPO / "rag_ime/agent_service.py").read_text(encoding="utf-8")
        kernel = (REPO / "rag_ime/agent_room_kernel.py").read_text(encoding="utf-8")
        prompt = (REPO / "rag_ime/agent_prompt_plans.py").read_text(encoding="utf-8")
        integrations = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (REPO / "integrations/pi").rglob("*.ts")
        )

        # Product routes converge on one command bus; store methods are persistence internals.
        self.assertIn("room_kernel_commands.create_root_task(", service)
        self.assertIn("room_kernel_commands.dispatch(", service)
        self.assertIn("room_kernel_commands.finalize(", service)
        self.assertIn("Canonical durable Room state machine", kernel)

        # Bound Room Sessions consume the compiled provider payload and one governed Skill.
        self.assertIn("Durable six-layer PromptPlan", prompt)
        self.assertIn('"mode": "live_room_binding"', prompt)
        self.assertIn("RoomSkillPolicyStore", service)
        self.assertIn("_runtime_session_context", service)
        self.assertIn("_accept_managed_room_runtime_context", service)

        # A Root pins one immutable CollaborationProfile; dispatch compilation consumes it.
        self.assertIn("_resolve_room_collaboration_profile", service)
        self.assertIn("profile=active_profile", service)
        self.assertNotIn("profile=None", service)

        # Product integration pins the reviewed Pi runtime handlers and typed methods.
        self.assertIn("room.dispatch", integrations)
        self.assertIn("room.cancel", integrations)

        # Legacy projection still exists for ordinary rooms, but managed Room bindings suppress it.
        self.assertIn('return "participant_message", {"message": message}', service)
        self.assertIn('self.room_kernel.mode in {"cohort", "kernel_only"}', service)

        recognized = {
            action
            for action in ("snapshot", "events", "commands", "settle", "create", "dispatch", "finalize")
            if agent_room_kernel_route(f"/api/agent/rooms/room:1/kernel/{action}")[1]
        }
        self.assertEqual(
            recognized,
            {"snapshot", "events", "commands", "settle", "create", "dispatch", "finalize"},
        )

    def test_cancelled_root_closes_tasks_and_has_authoritative_terminal_receipt(self) -> None:
        self.worker.run_once()
        self.worker.cancel_root("root:1")
        root = self.store.root("root:1")
        rejected = self.store.finalize_root("root:1", now_ms=30)

        self.assertEqual(root["state"], "cancelled")
        self.assertIsNotNone(root["terminalReceiptId"])
        self.assertEqual(rejected["status"], "applied")
        self.assertEqual(rejected["receiptKind"], "terminal")

    def _seed_dispatch(self) -> None:
        self.store.create_root(
            {
                "schemaVersion": "wisdom-weasel.room-root-execution.v2",
                "rootId": "root:1",
                "roomId": "room:1",
                "generation": 0,
                "state": "running",
                "owner": "user:1",
                "requirementAnchorRef": "requirement:1",
                "createdByActorRef": "user:1",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "budget:1",
                "createdAtMs": 1,
            },
            budget=10,
            max_hops=4,
            max_depth=4,
            now_ms=1,
        )
        self.store.create_task(
            {
                "schemaVersion": "wisdom-weasel.room-task.v2",
                "taskId": "task:1",
                "rootId": "root:1",
                "parentTaskId": None,
                "ownerParticipantId": "participant:b",
                "assigneeParticipantId": "participant:b",
                "objective": "audit",
                "expectedOutput": "a safe terminal receipt",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": ["ac:1"],
                "revision": 1,
                "state": "active",
            },
            now_ms=1,
        )
        self.store.enqueue_dispatch(
            {
                "schemaVersion": "wisdom-weasel.room-dispatch-envelope.v2",
                "dispatchId": "dispatch:1",
                "rootId": "root:1",
                "taskId": "task:1",
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 1,
                "targetSessionId": "session:b",
                "targetParticipantId": "participant:b",
                "triggerId": "trigger:1",
                "intentKind": "execute",
                "idempotencyKey": "root:1:task:1:participant:b",
                "attempt": 0,
                "capabilityEpoch": 0,
                "runtimeProfileRevision": "profile:1",
                "state": "pending",
            },
            now_ms=1,
        )

    @staticmethod
    def _panic_command() -> dict[str, object]:
        return {
            "schemaVersion": "wisdom-weasel.room-kernel-command.v1",
            "commandId": "panic:1",
            "rootId": None,
            "roomId": "room:1",
            "commandKind": "panic",
            "targetKind": None,
            "targetId": None,
            "sourceKind": "admin",
            "sourceId": "audit",
            "idempotencyKey": "panic:1",
            "generation": 0,
            "payload": {},
            "createdAtMs": 21,
        }


if __name__ == "__main__":
    unittest.main()
