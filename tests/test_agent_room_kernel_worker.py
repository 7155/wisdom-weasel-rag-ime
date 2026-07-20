from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_worker import RoomKernelWorker
from tests.test_agent_room_kernel import dispatch, root, task


class FakeRoomRuntime:
    def __init__(self, *, fail_dispatch: bool = False) -> None:
        self.fail_dispatch = fail_dispatch
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
        receipt = {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "sessionId": session_id,
            "rootId": root_id,
            "generation": generation,
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
        self.assertIn("[ROOM_DISPATCH_V2]", runtime.dispatches[0][1])

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

    def test_cancel_root_reaches_every_active_runtime_target(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:cancel", key="worker:cancel"), now_ms=3)
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(self.store, runtime, clock_ms=self.clock)
        worker.run_once()
        registered = self.store.abort_scope("dispatch:cancel")
        self.assertEqual(
            set(registered["surfaces"]),
            {"queued", "running", "provider", "tool", "process", "retry", "compaction", "timer", "continuation"},
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

    def test_shadow_worker_never_leases_or_calls_runtime(self) -> None:
        shadow = RoomKernelStore(self.db_path, mode="shadow")
        runtime = FakeRoomRuntime()
        worker = RoomKernelWorker(shadow, runtime, clock_ms=self.clock)

        self.assertIsNone(worker.run_once())
        self.assertEqual(runtime.dispatches, [])


if __name__ == "__main__":
    unittest.main()
