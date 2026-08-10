from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_worker import RoomKernelWorker
from rag_ime.agent_service import AgentService
from rag_ime.pi_runtime import PiRuntimeConfig
from tests.test_agent_room_kernel import commit, dispatch, root, task
from tests.test_agent_room_kernel_worker import FakeRoomRuntime


class _RestartedRuntime(FakeRoomRuntime):
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"
    default_model_profile = "pi/default"

    def __init__(
        self,
        session_root: Path,
        *,
        include_orphan_receipt: bool,
    ) -> None:
        super().__init__()
        self.session_root = session_root
        self.stopped = False
        restarted_at_ms = int(time.time() * 1000)
        self._status = {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "managed": True,
            "status": "ready",
            "driverId": self.driver_id,
            "runtimeKind": self.runtime_kind,
            "runtimeVersion": "test-restarted",
            "piVersion": "test-restarted",
            "idleTimeoutSeconds": 0,
            "activeSessionId": None,
            "activeSessionIds": [],
            "openSessionIds": [],
            "lastError": "",
            "capabilities": {"sessions": True, "modelConfigured": True},
            "runtimeHostKillGate": {
                "ownerInstanceId": "runtime:new",
                "orphanReconcileReceipts": ([
                    {
                        "schemaVersion": (
                            "wisdom-weasel.runtime-host-kill-receipt.v1"
                        ),
                        "killReceiptId": "runtime-kill:startup",
                        "hostIdentity": "pi-host:old",
                        "requestKind": "orphan_reconcile",
                        "requestedBy": "runtime:runtime:new",
                        "state": "terminated",
                        "pendingTargets": [],
                        "errorCode": "",
                        "requestedAtMs": restarted_at_ms,
                        "acknowledgedAtMs": restarted_at_ms,
                        "terminatedAtMs": restarted_at_ms,
                    }
                ] if include_orphan_receipt else []),
                "lastKillReceipt": None,
            },
        }

    def runtime_status(self):
        return dict(self._status)

    def stop(self):
        self.stopped = True


class _RestartedRuntimeFactory:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"
    default_model_profile = "pi/default"

    def __init__(
        self,
        root: Path,
        *,
        include_orphan_receipt: bool = True,
    ) -> None:
        self.session_root = root / "sessions"
        self.runtime: _RestartedRuntime | None = None
        self.include_orphan_receipt = include_orphan_receipt

    def apply_policy(self, _policy) -> None:
        return None

    def reconfigure(self, _config) -> None:
        return None

    def create(self, _context, *, purpose, session_context_provider=None):
        del purpose, session_context_provider
        self.runtime = _RestartedRuntime(
            self.session_root,
            include_orphan_receipt=self.include_orphan_receipt,
        )
        return self.runtime


class RoomRuntimeRestartRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-runtime-restart-"
        )
        self.root_dir = Path(self.tmp.name)
        self.db_path = self.root_dir / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.store.initialize()
        self.store.create_root(
            root("root:restart"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.store.create_task(
            task("task:restart", root_id="root:restart", criteria=()),
            now_ms=2,
        )
        payload = dispatch(
            "dispatch:restart",
            key="restart",
            task_id="task:restart",
        )
        payload["rootId"] = "root:restart"
        self.store.enqueue_dispatch(payload, now_ms=3)
        lease = self.store.lease_next(
            now_ms=4,
            ttl_ms=30_000,
            dispatch_id="dispatch:restart",
        )
        assert lease is not None
        self.store.record_runtime_dispatch_intent(
            "dispatch:restart",
            now_ms=5,
        )
        self.store.accept_runtime_receipt(
            lease_token=str(lease["leaseToken"]),
            runtime_receipt={
                "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
                "receiptKind": "dispatch_accepted",
                "status": "accepted",
                "rootId": "root:restart",
                "dispatchId": "dispatch:restart",
                "sessionId": payload["targetSessionId"],
                "generation": 0,
                "capabilityEpoch": 1,
                "turnId": "turn:restart",
            },
            now_ms=6,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _terminated_receipt() -> dict[str, object]:
        return {
            "schemaVersion": "wisdom-weasel.runtime-host-kill-receipt.v1",
            "killReceiptId": "runtime-kill:restart",
            "hostIdentity": "pi-host:old",
            "requestKind": "orphan_reconcile",
            "requestedBy": "runtime:runtime:new",
            "state": "terminated",
            "pendingTargets": [],
            "errorCode": "",
            "requestedAtMs": 7,
            "acknowledgedAtMs": 8,
            "terminatedAtMs": 9,
        }

    def test_terminated_host_fails_old_attempt_and_retries_once(self) -> None:
        targets = self.store.startup_accepted_runtime_targets(
            captured_at_ms=7
        )
        runtime = FakeRoomRuntime()
        clock = {"nowMs": 10}
        worker = RoomKernelWorker(
            self.store,
            runtime,
            clock_ms=lambda: clock["nowMs"],
        )

        first = worker.recover_terminated_runtime_host(
            targets,
            [self._terminated_receipt()],
        )
        clock["nowMs"] = 11
        replay = worker.recover_terminated_runtime_host(
            targets,
            [self._terminated_receipt()],
        )

        self.assertEqual(first, replay)
        self.assertEqual(first["failedDispatchIds"], ["dispatch:restart"])
        self.assertEqual(len(first["retriedDispatchIds"]), 1)
        retried_dispatch_id = str(first["retriedDispatchIds"][0])
        self.assertNotEqual(retried_dispatch_id, "dispatch:restart")
        self.assertEqual(
            self.store.dispatch("dispatch:restart")["state"],
            "failed",
        )
        retried = self.store.dispatch(retried_dispatch_id)
        self.assertEqual(retried["state"], "pending")
        self.assertEqual(retried["attempt"], 1)
        self.assertEqual(retried["capabilityEpoch"], 2)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT reason_code FROM room_kernel_dead_letters "
                    "WHERE dispatch_id='dispatch:restart'"
                ).fetchone()[0],
                "runtime_host_restarted",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM room_kernel_dispatches"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM room_kernel_commands "
                    "WHERE command_kind='retry_root'"
                ).fetchone()[0],
                1,
            )

        worker.run_once()
        self.assertIn("这是恢复轮次", runtime.dispatches[-1][1])

    def test_same_root_multiple_targets_use_one_retry_root_command(self) -> None:
        peer_task = task(
            "task:restart-peer",
            root_id="root:restart",
            criteria=(),
        )
        peer_task["currentOwnerParticipantId"] = "participant:b"
        self.store.create_task(peer_task, now_ms=2)
        peer_dispatch = dispatch(
            "dispatch:restart-peer",
            key="restart-peer",
            target="participant:b",
            task_id="task:restart-peer",
        )
        peer_dispatch["rootId"] = "root:restart"
        self.store.enqueue_dispatch(peer_dispatch, now_ms=3)
        lease = self.store.lease_next(
            now_ms=4,
            ttl_ms=30_000,
            dispatch_id="dispatch:restart-peer",
        )
        assert lease is not None
        self.store.record_runtime_dispatch_intent(
            "dispatch:restart-peer",
            now_ms=5,
        )
        self.store.accept_runtime_receipt(
            lease_token=str(lease["leaseToken"]),
            runtime_receipt={
                "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
                "receiptKind": "dispatch_accepted",
                "status": "accepted",
                "rootId": "root:restart",
                "dispatchId": "dispatch:restart-peer",
                "sessionId": peer_dispatch["targetSessionId"],
                "generation": 0,
                "capabilityEpoch": 1,
                "turnId": "turn:restart-peer",
            },
            now_ms=6,
        )
        targets = self.store.startup_accepted_runtime_targets(
            captured_at_ms=7
        )
        worker = RoomKernelWorker(
            self.store,
            FakeRoomRuntime(),
            clock_ms=lambda: 10,
        )

        result = worker.recover_terminated_runtime_host(targets, [])

        self.assertEqual(
            result["failedDispatchIds"],
            ["dispatch:restart", "dispatch:restart-peer"],
        )
        self.assertEqual(len(result["retriedDispatchIds"]), 2)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM room_kernel_commands "
                    "WHERE command_kind='retry_root'"
                ).fetchone()[0],
                1,
            )
            retry_attempts = [
                json.loads(row[0])["attempt"]
                for row in connection.execute(
                    "SELECT payload_json FROM room_kernel_dispatches "
                    "WHERE dispatch_id NOT IN "
                    "('dispatch:restart','dispatch:restart-peer')"
                ).fetchall()
            ]
        self.assertEqual(retry_attempts, [1, 1])

    def test_retry_budget_exhaustion_leaves_root_truthfully_blocked(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_root_limits SET retry_limit=0 "
                "WHERE root_id='root:restart'"
            )
        targets = self.store.startup_accepted_runtime_targets(
            captured_at_ms=7
        )
        worker = RoomKernelWorker(
            self.store,
            FakeRoomRuntime(),
            clock_ms=lambda: 10,
        )

        result = worker.recover_terminated_runtime_host(
            targets,
            [self._terminated_receipt()],
        )

        self.assertEqual(result["retriedDispatchIds"], [])
        self.assertEqual(result["blockedRootIds"], ["root:restart"])
        self.assertEqual(self.store.root("root:restart")["state"], "blocked")
        self.assertEqual(
            self.store.dispatch("dispatch:restart")["state"],
            "failed",
        )

    def test_intentional_runtime_restart_recovers_without_kill_receipt(self) -> None:
        targets = self.store.startup_accepted_runtime_targets(
            captured_at_ms=7
        )
        worker = RoomKernelWorker(
            self.store,
            FakeRoomRuntime(),
            clock_ms=lambda: 10,
        )
        intentional = worker.recover_terminated_runtime_host(targets, [])

        self.assertEqual(
            intentional["failedDispatchIds"],
            ["dispatch:restart"],
        )
        self.assertEqual(len(intentional["retriedDispatchIds"]), 1)
        self.assertEqual(
            self.store.dispatch("dispatch:restart")["state"],
            "failed",
        )

    def test_captured_target_already_settled_is_not_recovered(self) -> None:
        targets = self.store.startup_accepted_runtime_targets(
            captured_at_ms=7
        )
        settled = commit(
            "commit:restart",
            "dispatch:restart",
            coverage=(),
            task_id="task:restart",
        )
        settled["qualityGateReceipt"] = {
            **settled["qualityGateReceipt"],
            "rootId": "root:restart",
        }
        self.store.apply_commit(
            settled,
            generation=0,
            now_ms=8,
        )
        worker = RoomKernelWorker(
            self.store,
            FakeRoomRuntime(),
            clock_ms=lambda: 10,
        )

        result = worker.recover_terminated_runtime_host(targets, [])

        self.assertEqual(result["failedDispatchIds"], [])
        self.assertEqual(result["retriedDispatchIds"], [])
        self.assertEqual(
            self.store.dispatch("dispatch:restart")["state"],
            "committed",
        )

    def test_agent_service_recovers_snapshot_before_worker_start(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_root_limits SET deadline_at_ms=? "
                "WHERE root_id='root:restart'",
                (int(time.time() * 1000) + 60_000,),
            )
        first = AgentService(
            db_path=self.db_path,
            runtime_factory=_RestartedRuntimeFactory(self.root_dir),
            room_kernel_mode="cohort",
            room_kernel_worker_enabled=False,
        )
        first.close()
        factory = _RestartedRuntimeFactory(self.root_dir)

        with patch(
            "rag_ime.agent_service.RoomKernelWorkerLoop.start",
            return_value=True,
        ) as start:
            service = AgentService(
                db_path=self.db_path,
                runtime_factory=factory,
                room_kernel_mode="cohort",
                room_kernel_worker_enabled=True,
            )

        try:
            start.assert_called_once_with()
            self.assertEqual(
                service.room_kernel.dispatch("dispatch:restart")["state"],
                "failed",
            )
            with sqlite3.connect(self.db_path) as connection:
                retry_rows = connection.execute(
                    "SELECT payload_json FROM room_kernel_dispatches "
                    "WHERE dispatch_id!='dispatch:restart'"
                ).fetchall()
            self.assertEqual(len(retry_rows), 1)
            self.assertEqual(
                int(json.loads(retry_rows[0][0])["attempt"]),
                1,
            )
        finally:
            service.close()

    def test_agent_service_reconfigure_recovers_without_kill_receipt(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_root_limits SET deadline_at_ms=? "
                "WHERE root_id='root:restart'",
                (int(time.time() * 1000) + 60_000,),
            )
        factory = _RestartedRuntimeFactory(
            self.root_dir,
            include_orphan_receipt=False,
        )
        service = AgentService(
            db_path=self.db_path,
            runtime_factory=factory,
            room_kernel_mode="cohort",
            room_kernel_worker_enabled=False,
        )
        service._room_kernel_worker_enabled = True
        config = PiRuntimeConfig(
            enabled=False,
            executable=None,
            agent_dir=self.root_dir / "agent-config",
            session_dir=self.root_dir / "sessions",
            logs_dir=self.root_dir / "logs",
        )

        try:
            with patch(
                "rag_ime.agent_service.RoomKernelWorkerLoop.start",
                return_value=True,
            ) as start:
                service.reconfigure_runtime(config)

            start.assert_called_once_with()
            self.assertEqual(
                service.room_kernel.dispatch("dispatch:restart")["state"],
                "failed",
            )
            self.assertEqual(
                service._room_runtime_startup_recovery["killReceiptId"],
                "",
            )
            self.assertEqual(
                len(
                    service._room_runtime_startup_recovery[
                        "retriedDispatchIds"
                    ]
                ),
                1,
            )
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
