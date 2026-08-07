from __future__ import annotations

import tempfile
import unittest
import json
import sqlite3
from pathlib import Path

from rag_ime.agent_room_kernel import (
    SYSTEM_MAX_BUDGET,
    SYSTEM_MAX_DEPTH,
    SYSTEM_MAX_HOPS,
    RoomKernelFenceError,
    RoomKernelStore,
)
from rag_ime.agent_room_kernel_worker import RoomKernelWorker
from rag_ime.agent_routes import agent_room_kernel_route


REPO = Path(__file__).resolve().parents[1]


class _AcceptedRuntime:
    def __init__(self) -> None:
        self.active_dispatches: list[str] = []
        self.cancel_calls: list[tuple[str, str, int]] = []

    def dispatch_room(
        self,
        payload,
        *,
        message: str,
        lease_token: str,
        record_intent,
    ):
        record_intent()
        self.active_dispatches.append(str(payload["dispatchId"]))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "sessionId": payload["targetSessionId"],
            "capabilityEpoch": payload["capabilityEpoch"],
            "turnId": f"turn:{payload['dispatchId']}",
        }

    def cancel_room(
        self,
        *,
        cancel_id: str,
        session_id: str,
        root_id: str,
        dispatch_id: str,
        generation: int,
        turn_id: str,
        capability_epoch: int,
    ):
        self.cancel_calls.append((session_id, root_id, generation))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "cancelId": cancel_id,
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "sessionId": session_id,
            "generation": generation,
            "turnId": turn_id,
            "capabilityEpoch": capability_epoch,
            "cancellationSurfaces": {surface: {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": surface, "state": "terminated", "targetIds": [],
            } for surface in (
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session")},
            "pendingTargets": [],
        }


class _CancelUnavailableRuntime(_AcceptedRuntime):
    def cancel_room(self, **lineage: object):
        session_id = str(lineage["session_id"])
        root_id = str(lineage["root_id"])
        generation = int(lineage["generation"])
        self.cancel_calls.append((session_id, root_id, generation))
        raise ConnectionError("Pi Host is unavailable")


class RoomV2SafetyExitAuditTests(unittest.TestCase):
    """Safety invariants plus explicit characterization of remaining release gates."""

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

    def test_runtime_ack_lost_before_persistence_stays_unknown_without_blind_cancel(self) -> None:
        original = self.store.accept_runtime_receipt

        def crash_after_runtime_effect(**_kwargs):
            raise RuntimeError("simulated process crash after Pi accepted the Dispatch")

        self.store.accept_runtime_receipt = crash_after_runtime_effect  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "after Pi accepted"):
            self.worker.run_once(lease_ttl_ms=5)
        self.store.accept_runtime_receipt = original  # type: ignore[method-assign]

        self.clock = 20
        self.worker.reconcile()
        self.assertEqual(self.store.dispatch("dispatch:1")["state"], "unknown")
        self.assertEqual(self.runtime.cancel_calls, [])
        self.assertEqual(self.revoked, ["session:b"])
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")
        self.assertIsNone(self.store.root("root:1")["terminalReceiptId"])

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
        room_application = (
            REPO / "rag_ime/agent_room_application.py"
        ).read_text(encoding="utf-8")
        kernel_application = (
            REPO / "rag_ime/agent_room_kernel_application.py"
        ).read_text(encoding="utf-8")
        runtime_coordinator = (
            REPO / "rag_ime/agent_room_runtime_coordinator.py"
        ).read_text(encoding="utf-8")
        event_projection = (
            REPO / "rag_ime/agent_event_projection.py"
        ).read_text(encoding="utf-8")
        kernel = (REPO / "rag_ime/agent_room_kernel.py").read_text(encoding="utf-8")
        prompt = (REPO / "rag_ime/agent_prompt_plans.py").read_text(encoding="utf-8")
        integrations = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (REPO / "integrations/pi").rglob("*.ts")
        )

        # Product routes converge on one command bus; store methods are persistence internals.
        self.assertIn("self.commands.create_root_task(", room_application)
        self.assertIn("self.commands.dispatch_many(", room_application)
        self.assertIn("self.commands.finalize(", kernel_application)
        self.assertIn("Canonical durable Room state machine", kernel)

        # Bound Room Sessions consume the compiled provider payload and one governed Skill.
        self.assertIn("Durable six-layer PromptPlan", prompt)
        self.assertIn('"mode": "live_room_binding"', prompt)
        self.assertIn("RoomSkillPolicyStore", service)
        self.assertIn("_runtime_session_context", service)
        self.assertIn("_accept_managed_room_runtime_context", service)

        # A Root pins one immutable CollaborationProfile; dispatch compilation consumes it.
        self.assertIn("_resolve_room_collaboration_profile", service)
        self.assertIn("profile=active_profile", runtime_coordinator)
        self.assertNotIn("profile=None", runtime_coordinator)

        # Product integration pins the reviewed Pi runtime handlers and typed methods.
        self.assertIn("room.dispatch", integrations)
        self.assertIn("room.cancel", integrations)

        # Legacy projection still exists for ordinary rooms, but managed Room bindings suppress it.
        self.assertIn('return "participant_message", {', event_projection)
        self.assertIn('"message": message', event_projection)
        # The managed-mode guard now has one policy owner instead of an inline
        # set literal; the audit keeps proving the guard exists in the service.
        self.assertIn("kernel_owns_room_execution(self.room_kernel.mode)", service)

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

    def test_system_ceilings_cannot_be_relaxed_by_a_root_request(self) -> None:
        root = {
            "schemaVersion": "wisdom-weasel.room-root-execution.v3",
            "rootId": "root:over-limit",
            "roomId": "room:1",
            "generation": 0,
            "state": "running",
            "facilitatorParticipantId": "participant:a",
            "reporterParticipantId": None,
            "reporterSelectionReceiptId": None,
            "requirementAnchorRef": "requirement:limits",
            "createdByActorRef": "user:1",
            "terminalReceiptId": None,
            "activeProfileRef": None,
            "budgetPolicyRef": "budget:limits",
            "independentReviewRequired": False,
            "createdAtMs": 1,
        }
        for overrides in (
            {"budget": SYSTEM_MAX_BUDGET + 1, "max_hops": 1, "max_depth": 1},
            {"budget": 1, "max_hops": SYSTEM_MAX_HOPS + 1, "max_depth": 1},
            {"budget": 1, "max_hops": 1, "max_depth": SYSTEM_MAX_DEPTH + 1},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(RoomKernelFenceError, "system safety ceiling"):
                    self.store.create_root(root, **overrides, now_ms=1)

    def test_reviewed_pi_handler_source_and_methods_are_pinned(self) -> None:
        contract = json.loads(
            (REPO / "integrations/pi/room-runtime-host-contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            contract["minimumHandlersCommit"],
            "aa3d7f5c41f976264414b8962ebe5a52d728a4d6",
        )
        self.assertEqual(contract["sourceRepository"], "https://github.com/7155/pi.git")
        self.assertEqual(
            contract["handlerSources"]["toolArtifacts"],
            "packages/rag-ime-runtime-host/src/tool-artifact-buffer.ts",
        )
        self.assertEqual(
            contract["handlerSources"]["cancellationReceipts"],
            "packages/rag-ime-runtime-host/src/cancellation-receipts.ts",
        )
        self.assertEqual(
            contract["handlerSources"]["providerContextJournal"],
            "packages/rag-ime-runtime-host/src/provider-context-journal.ts",
        )
        self.assertEqual(
            contract["handlerSources"]["workflowControl"],
            "packages/rag-ime-runtime-host/src/workflow-control.ts",
        )
        self.assertEqual(
            contract["handlerSources"]["lifecycleHooks"],
            "packages/rag-ime-runtime-host/src/lifecycle-hooks.ts",
        )
        self.assertEqual(
            contract["handlerSources"]["deterministicTestAdapter"],
            "packages/rag-ime-runtime-host/src/deterministic-test-adapter.ts",
        )
        self.assertTrue(
            {
                "workflowControl",
                "lifecycleHooks",
                "deterministicTestAdapter",
                "contextInspection",
                "summarizationCompletion",
            }
            <= set(contract["requiredSourceMarkers"])
        )
        self.assertIn(
            "return record ? structuredClone(record) : undefined;",
            contract["requiredSourceMarkers"]["contextInspection"],
        )
        self.assertIn(
            "const DEFAULT_STORAGE_BYTES = 5 * 1024 * 1024 * 1024;",
            contract["requiredSourceMarkers"]["contextInspection"],
        )
        self.assertIn(
            "const MAX_STORAGE_BYTES = 64 * 1024 * 1024 * 1024;",
            contract["requiredSourceMarkers"]["contextInspection"],
        )
        self.assertEqual(
            set(contract["requiredMethods"]),
            {
                "session.control_state",
                "session.await_settled",
                "room.dispatch",
                "room.cancel",
            },
        )
        build = (REPO / "scripts/build_managed_pi_runtime_v2.py").read_text(encoding="utf-8")
        self.assertIn('"git", "merge-base", "--is-ancestor"', build)
        self.assertIn("Pi source does not contain the reviewed Room runtime handler commit", build)

    def test_cancel_dead_letter_finalizes_with_visible_unknown_surfaces(self) -> None:
        """Exhausted runtime cancellation is terminal without hiding uncertainty."""

        runtime = _CancelUnavailableRuntime()
        worker = RoomKernelWorker(
            self.store,
            runtime,
            clock_ms=lambda: self.clock,
            revoke_session=lambda _session_id, _now_ms: None,
        )
        worker.run_once()
        worker.cancel_root("root:1")
        for attempt in range(1, 5):
            self.clock = attempt * 100_000
            worker.drain_cancel_outbox()

        with sqlite3.connect(self.store.db_path) as conn:
            state, attempts = conn.execute(
                "SELECT state,attempt_count FROM room_kernel_cancel_outbox"
            ).fetchone()
        root = self.store.root("root:1")
        self.assertEqual((state, attempts), ("dead_letter", 5))
        self.assertEqual(root["state"], "cancelled_with_unknowns")
        self.assertIsNotNone(root["terminalReceiptId"])
        terminal = self.store.receipt(str(root["terminalReceiptId"]))
        self.assertEqual(
            terminal["details"],
            {"terminalState": "cancelled_with_unknowns", "quiescent": True},
        )
        self.assertEqual(self.store.abort_scope("dispatch:1")["state"], "unknown")
        self.assertEqual(
            {
                item["state"]
                for item in self.store.cancellation_surface_projection("room:1")
            },
            {"unknown"},
        )

    def test_reconcile_recovers_existing_exhausted_cancel_dead_letter(self) -> None:
        self.worker.run_once()
        self.store.cancel_root("root:1", now_ms=self.clock)
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                """UPDATE room_kernel_cancel_outbox
                   SET state='dead_letter',attempt_count=5,last_error='session failed'"""
            )
            conn.execute(
                """UPDATE room_v2_runtime_cancel_surface_receipts
                   SET state='unknown'"""
            )
            conn.execute(
                """UPDATE room_kernel_dispatches
                   SET state='unknown' WHERE dispatch_id='dispatch:1'"""
            )

        self.assertIsNone(self.store.root("root:1")["terminalReceiptId"])
        receipts = self.worker.reconcile()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["receiptKind"], "terminal")

        root = self.store.root("root:1")
        self.assertEqual(root["state"], "cancelled_with_unknowns")
        terminal = self.store.receipt(str(root["terminalReceiptId"]))
        self.assertEqual(
            terminal["details"],
            {"terminalState": "cancelled_with_unknowns", "quiescent": True},
        )
        self.assertEqual(self.store.abort_scope("dispatch:1")["state"], "unknown")

    def _seed_dispatch(self) -> None:
        self.store.create_root(
            {
                "schemaVersion": "wisdom-weasel.room-root-execution.v3",
                "rootId": "root:1",
                "roomId": "room:1",
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": "participant:a",
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement:1",
                "createdByActorRef": "user:1",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "budget:1",
                "independentReviewRequired": False,
                "createdAtMs": 1,
            },
            budget=10,
            max_hops=4,
            max_depth=4,
            acceptance_criteria=("ac:1",),
            now_ms=1,
        )
        self.store.create_task(
            {
                "schemaVersion": "wisdom-weasel.room-task.v3",
                "taskId": "task:1",
                "rootId": "root:1",
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": "participant:b",
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "objective": "audit",
                "expectedOutput": "a safe terminal receipt",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": ["ac:1"],
                "contextEvidenceRefs": [],
                "invitationId": None,
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "reviewState": "not_required",
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
