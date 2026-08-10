from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from threading import Event, Lock
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_worker import (
    KernelCommandBus,
    RoomKernelWorker,
    RoomKernelWorkerLoop,
)
from tests.test_agent_room_kernel import dispatch, root, task


class FakeRoomRuntime:
    def __init__(
        self,
        *,
        fail_dispatch: bool = False,
        preflight_failures: int = 0,
        fail_cancel: bool = False,
        surface_state: str = "terminated",
        host_terminated: bool = False,
    ) -> None:
        self.fail_dispatch = fail_dispatch
        self.preflight_failures = preflight_failures
        self.fail_cancel = fail_cancel
        self.surface_state = surface_state
        self.host_terminated = host_terminated
        self.dispatches: list[tuple[dict[str, object], str, str]] = []
        self.cancellations: list[dict[str, object]] = []

    def dispatch_room(
        self,
        payload,
        *,
        message: str,
        lease_token: str,
        record_intent,
    ):
        self.dispatches.append((dict(payload), message, lease_token))
        if self.preflight_failures > 0:
            self.preflight_failures -= 1
            raise ConnectionError("runtime preflight unavailable")
        record_intent()
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
            "capabilityEpoch": payload["capabilityEpoch"],
            "turnId": "turn:room-1",
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
        if self.fail_cancel:
            raise ConnectionError("runtime cancellation unavailable")
        receipt = {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "cancelId": cancel_id,
            "sessionId": session_id,
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "generation": generation,
            "turnId": turn_id,
            "capabilityEpoch": capability_epoch,
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
        if self.host_terminated:
            receipt["runtimeHostTermination"] = {
                "schemaVersion": "wisdom-weasel.runtime-host-kill-receipt.v1",
                "killReceiptId": "runtime-kill:sidecar-writer",
                "hostIdentity": "runtime-host:accepted",
                "requestKind": "cancel_timeout",
                "requestedBy": f"session:{session_id}",
                "state": "terminated",
                "pendingTargets": [],
                "requestedAtMs": 10,
                "acknowledgedAtMs": 10,
                "terminatedAtMs": 10,
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
            acceptance_criteria=("ac:1",),
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
                "继续当前 Room 工作卡片；本轮要做什么、由谁负责，以 Room Context 为准。"
                "需要核对自己的部分、验收条件或伙伴状态时，先调用 room_state。"
                "AC-1 表示 room_state 验收清单中的第一项，AC-2 表示第二项，以此类推。"
                "结束本轮只调用 room_commit：evidence.acceptance 只能填写 room_state "
                "返回的 AC-1、AC-2 等验收短名；每项只放直接支持它的最小 refs 集合。"
                "refs 必须原样复制最新 room_state 或成功工具结果返回的完整 evidenceRef，"
                "不得改写、拼接或猜测；不要填写内部 criterionId，也不要自行宣布已通过"
                "或最终裁决，服务端会根据实际结果判断。summary、evidence 和接手指令放在"
                "结构化私有字段；publicSummary 用自然语言写给用户，不暴露这些内部字段或"
                "私下推理。"
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

    def test_host_exit_without_runtime_ack_stays_unknown_and_is_not_blindly_cancelled(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:crash", key="worker:crash"), now_ms=3)
        runtime = FakeRoomRuntime(fail_dispatch=True)
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        with self.assertRaisesRegex(ConnectionError, "host exited"):
            worker.run_once(lease_ttl_ms=5)
        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "leased")
        self.now_ms = 15
        receipts = worker.reconcile()

        self.assertEqual(receipts[0]["receiptKind"], "dispatch_unknown")
        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "unknown")
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")
        self.assertEqual(runtime.cancellations, [])
        self.assertIsNone(worker.run_once())
        self.assertEqual(len(runtime.dispatches), 1)

    def test_preflight_failure_retries_without_unknown_delivery(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:preflight", key="worker:preflight"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(preflight_failures=1)
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        retry = worker.run_once(lease_ttl_ms=5)

        self.assertEqual(retry["receiptKind"], "runtime_retry_scheduled")
        self.assertFalse(retry["details"]["hadRuntimeIntent"])
        self.assertEqual(
            self.store.dispatch("dispatch:preflight")["state"],
            "retry_wait",
        )
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.now_ms = int(retry["details"]["availableAtMs"])

        accepted = worker.run_once(lease_ttl_ms=5)

        self.assertEqual(accepted["receiptKind"], "runtime_accepted")
        self.assertEqual(
            [int(item[0].get("attempt") or 0) for item in runtime.dispatches],
            [0, 1],
        )
        self.assertEqual(
            self.store.dispatch("dispatch:preflight")["state"],
            "running",
        )
        self.assertEqual(runtime.cancellations, [])

    def test_preflight_retry_exhaustion_blocks_without_unknown_delivery(
        self,
    ) -> None:
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                """UPDATE room_kernel_root_limits
                   SET retry_limit=0 WHERE root_id='root:1'"""
            )
        self.store.enqueue_dispatch(
            dispatch("dispatch:preflight-exhausted", key="worker:preflight-exhausted"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(preflight_failures=1)
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        failed = worker.run_once(lease_ttl_ms=5)

        self.assertEqual(failed["receiptKind"], "runtime_failed")
        self.assertFalse(failed["details"]["hadRuntimeIntent"])
        self.assertEqual(
            self.store.dispatch("dispatch:preflight-exhausted")["state"],
            "failed",
        )
        self.assertEqual(
            self.store.outbox("dispatch:preflight-exhausted")["state"],
            "dead_letter",
        )
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(runtime.cancellations, [])

    def test_cancelled_root_keeps_preflight_failure_as_a_noop_receipt(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:cancelled-preflight", key="worker:cancelled-preflight"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime()

        def cancel_then_fail(
            payload,
            *,
            message: str,
            lease_token: str,
            record_intent,
        ):
            del payload, message, lease_token, record_intent
            self.store.cancel_root("root:1", now_ms=self.clock())
            raise ConnectionError("runtime preflight unavailable after cancellation")

        runtime.dispatch_room = cancel_then_fail  # type: ignore[method-assign]
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)

        receipt = worker.run_once(lease_ttl_ms=5)

        self.assertEqual(receipt["receiptKind"], "runtime_failed")
        self.assertEqual(receipt["status"], "noop")
        self.assertFalse(receipt["details"]["hadRuntimeIntent"])
        self.assertEqual(receipt["details"]["previousState"], "cancelled")
        self.assertEqual(
            self.store.dispatch("dispatch:cancelled-preflight")["state"],
            "cancelled",
        )
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 0)

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

    def test_runtime_host_kill_waits_for_exact_sidecar_execution_receipt(
        self,
    ) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:sidecar-writer", key="worker:sidecar-writer"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(host_terminated=True)
        writer_active = True
        quiescence_calls: list[dict[str, object]] = []

        def foreground_quiescence(
            request: dict[str, object],
        ) -> dict[str, object]:
            quiescence_calls.append(dict(request))
            pending = ["invoke:workspace-shell"] if writer_active else []
            receipt = {
                "schemaVersion": (
                    "wisdom-weasel.room-workspace-writer-quiescence.v1"
                ),
                **dict(request),
                "foregroundMutatingInvocations": {
                    "known": True,
                    "activeCount": len(pending),
                    "pendingInvocationReceiptIds": pending,
                    "hostTerminatedInvocationReceiptIds": [],
                    "invalidExecutionReceiptIds": [],
                },
                "backgroundWork": {
                    "known": True,
                    "activeCount": 0,
                },
                "managedPiTurn": {
                    "known": True,
                    "settled": False,
                },
            }
            receipt["receiptRevision"] = hashlib.sha256(
                json.dumps(
                    receipt,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return receipt

        worker = RoomKernelWorker(
            self.store,
            runtime,
            foreground_invocation_quiescence=foreground_quiescence,
            clock_ms=self.clock,
        )
        worker.run_once()

        first = worker.cancel_root("root:1")

        self.assertEqual(
            self.store.root("root:1")["state"],
            "cancelled_with_unknowns",
        )
        self.assertEqual(
            first["runtimeReceipts"][0]["pendingTargets"],
            ["tool", "exec"],
        )
        self.assertEqual(len(quiescence_calls), 1)
        self.assertEqual(len(runtime.cancellations), 1)

        writer_active = False
        self.now_ms = 510
        retried = worker.drain_cancel_outbox()

        self.assertEqual(retried[0]["pendingTargets"], [])
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        # The retry re-checks the persisted Host-kill proof plus Sidecar
        # receipt; it must not call the already-dead Runtime Host again.
        self.assertEqual(len(runtime.cancellations), 1)
        self.assertEqual(len(quiescence_calls), 2)

    def test_passive_command_bus_defers_runtime_cancel_to_effect_owner(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:passive", key="worker:passive"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(
            self.store,
            runtime,
            clock_ms=self.clock,
        )
        worker.run_once()
        passive_bus = KernelCommandBus(
            self.store,
            worker,
            runtime_effects_enabled=False,
        )

        result = passive_bus.cancel_root("root:1")

        self.assertEqual(result["runtimeReceipts"], [])
        self.assertEqual(runtime.cancellations, [])
        self.assertEqual(self.store.root("root:1")["state"], "cancelling")

        receipts = worker.drain_cancel_outbox()

        self.assertEqual(receipts[0]["receiptKind"], "cancel_applied")
        self.assertEqual(len(runtime.cancellations), 1)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")

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

    def test_unknown_child_cancel_surface_does_not_terminalize_root(self) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:target-unknown", key="worker:target-unknown"),
            now_ms=3,
        )
        runtime = FakeRoomRuntime(surface_state="unknown")
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()

        self.store.cancel_target(
            root_id="root:1",
            target_kind="dispatch",
            target_id="dispatch:target-unknown",
            now_ms=self.now_ms,
        )
        receipts = worker.drain_cancel_outbox()

        self.assertEqual(receipts[0]["pendingTargets"], [
            "provider", "tool", "exec", "retry", "compaction",
            "branch_summary", "timer", "continuation", "session",
        ])
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

    def test_loop_survives_a_projection_callback_failure(self) -> None:
        recovered = Event()
        callback_count = 0

        class FakeStore:
            mode = "cohort"

        class FakeWorker:
            store = FakeStore()

            @staticmethod
            def reconcile() -> bool:
                return False

            @staticmethod
            def run_once(
                *,
                on_claim=None,
            ) -> dict[str, bool]:
                del on_claim
                return {"changed": True}

        def on_change() -> None:
            nonlocal callback_count
            callback_count += 1
            if callback_count == 1:
                raise RuntimeError("stale projection")
            recovered.set()

        loop = RoomKernelWorkerLoop(
            FakeWorker(),  # type: ignore[arg-type]
            on_change=on_change,
            poll_seconds=0.01,
        )
        try:
            self.assertTrue(loop.start())
            self.assertTrue(recovered.wait(1.0))
            self.assertTrue(loop.running)
        finally:
            loop.close()

    def test_loop_does_not_let_one_slow_runtime_ack_block_another_dispatch(
        self,
    ) -> None:
        self.store.create_task(task("task:2"), now_ms=2)
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:slow-ack",
                key="worker:slow-ack",
                session_id="session:slow-ack",
            ),
            now_ms=3,
        )
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:ready-behind-slow-ack",
                key="worker:ready-behind-slow-ack",
                task_id="task:2",
                session_id="session:ready-behind-slow-ack",
            ),
            now_ms=4,
        )
        slow_started = Event()
        ready_started = Event()
        release_slow = Event()

        class SlowAckRuntime(FakeRoomRuntime):
            @staticmethod
            def runtime_status() -> dict[str, object]:
                return {"capabilities": {"maxSessions": 2}}

            def dispatch_room(
                self,
                payload,
                *,
                message: str,
                lease_token: str,
                record_intent,
            ):
                self.dispatches.append((dict(payload), message, lease_token))
                record_intent()
                if payload["dispatchId"] == "dispatch:slow-ack":
                    slow_started.set()
                    if not release_slow.wait(1.0):
                        raise TimeoutError("test did not release slow runtime ACK")
                else:
                    ready_started.set()
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

        cohort_store = RoomKernelStore(self.db_path, mode="cohort")
        loop = RoomKernelWorkerLoop(
            RoomKernelWorker(
                cohort_store,
                SlowAckRuntime(),
                clock_ms=self.clock,
            ),
            poll_seconds=0.01,
        )
        try:
            self.assertTrue(loop.start())
            self.assertTrue(slow_started.wait(0.5))
            self.assertTrue(
                ready_started.wait(0.25),
                "one slow runtime ACK blocked a different ready Dispatch",
            )
        finally:
            release_slow.set()
            loop.close()

    def test_loop_never_exceeds_the_runtime_session_budget(self) -> None:
        self.store.create_task(task("task:2"), now_ms=2)
        self.store.create_task(task("task:3"), now_ms=2)
        for ordinal in range(1, 4):
            self.store.enqueue_dispatch(
                dispatch(
                    f"dispatch:bounded-{ordinal}",
                    key=f"worker:bounded-{ordinal}",
                    task_id=f"task:{ordinal}",
                    session_id=f"session:bounded-{ordinal}",
                ),
                now_ms=2 + ordinal,
            )
        two_started = Event()
        third_started = Event()
        release = Event()
        started: list[str] = []
        started_lock = Lock()

        class BoundedRuntime(FakeRoomRuntime):
            @staticmethod
            def runtime_status() -> dict[str, object]:
                return {"capabilities": {"maxSessions": 2}}

            def dispatch_room(
                self,
                payload,
                *,
                message: str,
                lease_token: str,
                record_intent,
            ):
                self.dispatches.append((dict(payload), message, lease_token))
                record_intent()
                with started_lock:
                    started.append(str(payload["dispatchId"]))
                    if len(started) >= 2:
                        two_started.set()
                    if len(started) >= 3:
                        third_started.set()
                if not release.wait(1.0):
                    raise TimeoutError("test did not release Runtime ACKs")
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

        cohort_store = RoomKernelStore(self.db_path, mode="cohort")
        loop = RoomKernelWorkerLoop(
            RoomKernelWorker(
                cohort_store,
                BoundedRuntime(),
                clock_ms=self.clock,
            ),
            poll_seconds=0.01,
        )
        try:
            self.assertEqual(loop.max_concurrent_dispatches, 2)
            self.assertTrue(loop.start())
            self.assertTrue(two_started.wait(0.5))
            self.assertFalse(
                third_started.wait(0.1),
                "Room delivery exceeded the Runtime maxSessions budget",
            )
            self.assertEqual(
                cohort_store.dispatch("dispatch:bounded-3")["state"],
                "pending",
            )
        finally:
            release.set()
            loop.close()

    def test_loop_does_not_expire_a_lease_while_its_runtime_ack_is_in_flight(
        self,
    ) -> None:
        self.store.enqueue_dispatch(
            dispatch("dispatch:ack-in-flight", key="worker:ack-in-flight"),
            now_ms=3,
        )
        ack_started = Event()
        release_ack = Event()

        class InFlightRuntime(FakeRoomRuntime):
            @staticmethod
            def runtime_status() -> dict[str, object]:
                return {"capabilities": {"maxSessions": 2}}

            def dispatch_room(
                self,
                payload,
                *,
                message: str,
                lease_token: str,
                record_intent,
            ):
                self.dispatches.append((dict(payload), message, lease_token))
                record_intent()
                ack_started.set()
                if not release_ack.wait(1.0):
                    raise TimeoutError("test did not release Runtime ACK")
                return {
                    "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
                    "receiptKind": "dispatch_accepted",
                    "status": "accepted",
                    "rootId": payload["rootId"],
                    "dispatchId": payload["dispatchId"],
                    "generation": payload["generation"],
                    "sessionId": payload["targetSessionId"],
                    "capabilityEpoch": payload["capabilityEpoch"],
                    "turnId": "turn:ack-in-flight",
                }

        cohort_store = RoomKernelStore(self.db_path, mode="cohort")
        loop = RoomKernelWorkerLoop(
            RoomKernelWorker(
                cohort_store,
                InFlightRuntime(),
                clock_ms=self.clock,
            ),
            poll_seconds=0.01,
        )
        try:
            self.assertTrue(loop.start())
            self.assertTrue(ack_started.wait(0.5))
            self.now_ms = 40_010
            self.assertFalse(release_ack.wait(0.05))
            self.assertEqual(
                cohort_store.dispatch("dispatch:ack-in-flight")["state"],
                "leased",
            )
            self.assertEqual(cohort_store.root("root:1")["state"], "running")
        finally:
            release_ack.set()
            loop.close()

    def test_shadow_worker_never_leases_or_calls_runtime(self) -> None:
        shadow = RoomKernelStore(self.db_path, mode="shadow")
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(shadow, runtime, clock_ms=self.clock)

        self.assertIsNone(worker.run_once())
        self.assertEqual(runtime.dispatches, [])


if __name__ == "__main__":
    unittest.main()
