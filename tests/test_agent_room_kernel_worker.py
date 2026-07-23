from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_worker import RoomKernelWorker
from tests.test_agent_room_kernel import dispatch, root, task


class FakeRoomRuntime:
    def __init__(
        self,
        *,
        fail_dispatch: bool = False,
        fail_cancel: bool = False,
        surface_state: str = "terminated",
    ) -> None:
        self.fail_dispatch = fail_dispatch
        self.fail_cancel = fail_cancel
        self.surface_state = surface_state
        self.dispatches: list[tuple[dict[str, object], str, str]] = []
        self.cancellations: list[dict[str, object]] = []

    def dispatch_room(self, payload, *, message: str, lease_token: str):
        self.dispatches.append((dict(payload), message, lease_token))
        if self.fail_dispatch:
            raise ConnectionError("runtime host exited after lease")
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "sessionId": payload["targetSessionId"],
            "turnId": "turn:room-1",
        }

    def cancel_room(self, *, session_id: str, root_id: str, generation: int):
        if self.fail_cancel:
            raise ConnectionError("runtime cancellation unavailable")
        receipt = {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "sessionId": session_id,
            "rootId": root_id,
            "generation": generation,
            "cancellationSurfaces": {surface: {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": surface, "state": self.surface_state, "targetIds": [],
            } for surface in (
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session")},
            "pendingTargets": ([
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session"
            ] if self.surface_state in {"requested", "acknowledged", "unknown"} else []),
        }
        self.cancellations.append(receipt)
        return receipt


class RoomKernelWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-worker-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.store.initialize()
        self.store.create_root(
            root("root:1"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.store.create_task(task("task:1"), now_ms=2)
        self.now_ms = 10

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def clock(self) -> int:
        return self.now_ms

    def test_worker_leases_dispatch_and_fences_typed_runtime_receipt(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:1", key="worker:1"), now_ms=3)
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        receipt = worker.run_once(lease_ttl_ms=50)

        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["receiptKind"], "runtime_accepted")
        self.assertEqual(self.store.dispatch("dispatch:1")["state"], "running")
        self.assertEqual(self.store.outbox("dispatch:1")["state"], "running")
        private_trigger = runtime.dispatches[0][1]
        self.assertEqual(
            private_trigger,
            (
                "执行当前受管 Room 任务；任务事实与责任以本轮 Room Context 为准。"
                "提交 deliver 时，把 acceptance.criteria[].criterionId 原样放入 "
                "requirementCoverage，禁止自造标签。"
            ),
        )
        for internal_id in ("root:1", "dispatch:1", "task:1", "session:1"):
            self.assertNotIn(internal_id, private_trigger)

    def test_runtime_ack_closes_delivery_lease_without_expiring_the_agent_run(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:long-run", key="worker:long-run"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        worker.run_once(lease_ttl_ms=5)
        self.now_ms = 20

        self.assertEqual(worker.reconcile(), [])
        self.assertEqual(self.store.dispatch("dispatch:long-run")["state"], "running")
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertEqual(runtime.cancellations, [])

    def test_worker_refreshes_generic_agent_rag_before_runtime(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:rag", key="worker:rag"),
            now_ms=3,
        )
        order: list[str] = []
        runtime = FakeRoomRuntime()
        dispatch_room = runtime.dispatch_room

        def observed_dispatch(*args, **kwargs):
            order.append("runtime")
            return dispatch_room(*args, **kwargs)

        runtime.dispatch_room = observed_dispatch
        worker = RoomKernelWorker(
            self.store,
            runtime,
            prepare_memory_context=lambda _dispatch, _now: (
                order.append("generic_rag")
                or {"ok": True, "status": "ready"}
            ),
            clock_ms=self.clock,
        )

        worker.run_once()

        self.assertEqual(
            order,
            ["generic_rag", "runtime"],
        )

    def test_host_exit_after_lease_is_cancelled_via_durable_reconciliation(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:crash", key="worker:crash"), now_ms=3)
        runtime = FakeRoomRuntime(fail_dispatch=True)
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        with self.assertRaisesRegex(ConnectionError, "host exited"):
            worker.run_once(lease_ttl_ms=5)
        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "leased")
        self.now_ms = 15
        receipts = worker.reconcile()

        self.assertEqual(receipts[0]["receiptKind"], "dispatch_unknown")
        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "cancelled")
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertIsNone(worker.run_once())
        self.assertEqual(len(runtime.dispatches), 1)

    def test_post_ack_context_failure_cancels_root_without_unknown_lease(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:context-failure", key="worker:context-failure"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime()
        observed: list[dict[str, object]] = []

        def reject_context(_receipt: object) -> None:
            raise RuntimeError("governed context projection rejected")

        worker = RoomKernelWorker(
            self.store,
            runtime,
            accept_runtime_context=reject_context,
            learning_observer=lambda signal: observed.append(dict(signal)),
            clock_ms=self.clock,
        )

        with self.assertRaisesRegex(RuntimeError, "projection rejected"):
            worker.run_once(lease_ttl_ms=5)

        self.assertEqual(
            self.store.dispatch("dispatch:context-failure")["state"],
            "cancelled",
        )
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertEqual(len(runtime.dispatches), 1)
        self.assertEqual(len(runtime.cancellations), 1)
        self.assertEqual(observed[0]["eventKind"], "runtime_context_failed")
        self.now_ms = 20
        self.assertEqual(worker.reconcile(), [])

    def test_cancel_root_reaches_every_active_runtime_target(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:cancel", key="worker:cancel"), now_ms=3)
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()
        registered = self.store.abort_scope("dispatch:cancel")
        self.assertEqual(
            set(registered["surfaces"]),
            {"queued", "running", "provider", "tool", "process", "exec", "retry", "compaction", "branch_summary", "timer", "continuation", "session"},
        )

        result = worker.cancel_root("root:1")

        self.assertEqual(result["kernelReceipt"]["receiptKind"], "root_cancelled")
        self.assertEqual(result["runtimeReceipts"][0]["receiptKind"], "cancel_applied")
        self.assertEqual(runtime.cancellations[0]["generation"], 1)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertEqual(self.store.abort_scope("dispatch:cancel")["state"], "cancelled")

    def test_cancel_target_reaches_runtime_without_terminalizing_root(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:target", key="worker:target"), now_ms=3)
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()

        self.store.cancel_target(
            root_id="root:1",
            target_kind="dispatch",
            target_id="dispatch:target",
            now_ms=self.now_ms,
        )
        worker.drain_cancel_outbox()

        self.assertEqual(len(runtime.cancellations), 1)
        self.assertEqual(self.store.dispatch("dispatch:target")["state"], "cancelled")
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertIsNone(self.store.root("root:1")["terminalReceiptId"])

    def test_pending_surface_proof_keeps_root_cancelling(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:pending", key="worker:pending"), now_ms=3)
        runtime = FakeRoomRuntime(surface_state="acknowledged")
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()

        result = worker.cancel_root("root:1")

        self.assertEqual(result["kernelReceipt"]["receiptKind"], "root_cancelled")
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")
        self.assertIsNone(self.store.root("root:1")["terminalReceiptId"])

    def test_cancel_delivery_failure_stays_visible_as_requested_instead_of_terminal(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:cancel-failure", key="worker:cancel-failure"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(fail_cancel=True)
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()

        result = worker.cancel_root("root:1")

        self.assertEqual(result["runtimeReceipts"], [])
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")
        surfaces = self.store.cancellation_surface_projection("room:1")
        self.assertEqual(
            {item["surface"] for item in surfaces},
            {
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session",
            },
        )
        self.assertEqual({item["state"] for item in surfaces}, {"requested"})

    def test_cancel_closes_approvals_before_runtime_and_replays_evidence_on_retry(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:approval-retry", key="worker:approval-retry"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(fail_cancel=True)
        invalidations: list[tuple[str, str, str, int]] = []

        def invalidate(session_id: str, root_id: str, dispatch_id: str, now_ms: int):
            invalidations.append((session_id, root_id, dispatch_id, now_ms))
            return {
                "schemaVersion": "rag-ime.room-approval-cancellation-summary.v1",
                "sessionId": session_id,
                "rootId": root_id,
                "dispatchId": dispatch_id,
                "state": "terminated",
                "cancelledApprovalIds": ["approval:bound"],
                "createdAtMs": now_ms,
            }

        worker = RoomKernelWorker(
            self.store,
            runtime,
            invalidate_room_approvals=invalidate,
            clock_ms=self.clock,
        )
        worker.run_once()

        result = worker.cancel_root("root:1")

        self.assertEqual(result["runtimeReceipts"], [])
        self.assertEqual(
            invalidations,
            [
                (
                    "session:participant:a",
                    "root:1",
                    "dispatch:approval-retry",
                    10,
                )
            ],
        )
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")

        runtime.fail_cancel = False
        self.now_ms = 2_010
        receipts = worker.drain_cancel_outbox()

        self.assertEqual(
            receipts[0]["approvalCancellation"]["cancelledApprovalIds"],
            ["approval:bound"],
        )
        self.assertEqual(len(invalidations), 2)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")

    def test_approval_invalidation_failure_blocks_runtime_cancel_ack(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:approval-failure", key="worker:approval-failure"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime()

        def invalidate(*_args):
            raise RuntimeError("approval store unavailable")

        worker = RoomKernelWorker(
            self.store,
            runtime,
            invalidate_room_approvals=invalidate,
            clock_ms=self.clock,
        )
        worker.run_once()

        result = worker.cancel_root("root:1")

        self.assertEqual(result["runtimeReceipts"], [])
        self.assertEqual(runtime.cancellations, [])
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")

    def test_unknown_surface_proof_is_visible_in_terminal_outcome(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:unknown", key="worker:unknown"), now_ms=3)
        runtime = FakeRoomRuntime(surface_state="unknown")
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()

        worker.cancel_root("root:1")

        root_projection = self.store.root("root:1")
        self.assertEqual(root_projection["state"], "cancelled_with_unknowns")
        self.assertIsNone(root_projection["terminalReceiptId"])
        surfaces = self.store.cancellation_surface_projection("room:1")
        self.assertEqual({item["state"] for item in surfaces}, {"unknown"})
        self.assertEqual(self.store.lease_cancel(now_ms=510)["rootId"], "root:1")

    def test_unknown_cancel_only_finalizes_after_reconcile_proves_every_surface_terminated(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:reconcile", key="worker:reconcile"), now_ms=3)
        runtime = FakeRoomRuntime(surface_state="unknown")
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()
        worker.cancel_root("root:1")
        self.assertIsNone(self.store.root("root:1")["terminalReceiptId"])

        runtime.surface_state = "terminated"
        self.now_ms = 510
        worker.drain_cancel_outbox()
        root_projection = self.store.root("root:1")
        self.assertEqual(root_projection["state"], "cancelled")
        self.assertIsNotNone(root_projection["terminalReceiptId"])
        self.assertEqual({item["state"] for item in self.store.cancellation_surface_projection("room:1")}, {"terminated"})

    def test_shadow_worker_never_leases_or_calls_runtime(self) -> None:
        shadow = RoomKernelStore(self.db_path, mode="shadow")
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(shadow, runtime, clock_ms=self.clock)

        self.assertIsNone(worker.run_once())
        self.assertEqual(runtime.dispatches, [])


if __name__ == "__main__":
    unittest.main()
