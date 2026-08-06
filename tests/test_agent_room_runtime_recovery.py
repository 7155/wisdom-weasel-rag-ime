from __future__ import annotations

import errno
import json
import sqlite3
import unittest
from threading import Event

from rag_ime.agent_service import _runtime_target_inactive_long_enough
from tests import test_agent_room_kernel_service as kernel_service_fixture


class RoomRuntimeRecoveryTests(unittest.TestCase):
    def test_periodic_recovery_heals_a_swallowed_terminal_projection_enospc(
        self,
    ) -> None:
        fixture = kernel_service_fixture.RoomKernelServiceTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        service = fixture.service

        service.room_kernel.enqueue_dispatch(fixture._dispatch(), now_ms=3)
        self.assertIsNotNone(service.room_kernel_worker.run_once())
        binding = service.room_kernel.session_binding(fixture.session_id)
        self.assertIsNotNone(binding)
        runtime_turn_id = str(binding["runtimeTurnId"])

        original_projection = (
            service.event_projection_application.record_runtime_failure
        )
        projection_attempts = 0

        def fail_projection_once(**values: object) -> dict[str, object]:
            nonlocal projection_attempts
            projection_attempts += 1
            if projection_attempts == 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            return original_projection(**values)

        service.event_projection_application.record_runtime_failure = (
            fail_projection_once
        )
        try:
            service.events.publish(
                fixture.session_id,
                "turn_completed",
                {
                    "status": "completed",
                    "terminalEvent": "agent_settled",
                },
                turn_id=runtime_turn_id,
            )
            self.assertTrue(service.events.flush(timeout=1.0))
        finally:
            service.event_projection_application.record_runtime_failure = (
                original_projection
            )

        self.assertEqual(projection_attempts, 1)
        self.assertEqual(
            service.room_kernel.dispatch("dispatch:service")["state"],
            "running",
        )
        self.assertEqual(
            service.room_kernel.task("task:service")["state"],
            "active",
        )
        self.assertEqual(
            service.room_kernel.root("root:service")["state"],
            "running",
        )

        recovered = Event()

        def recover_interrupted() -> int:
            count = service._recover_interrupted_room_runtime_dispatches(
                observed_at_ms=12,
                minimum_inactive_ms=0,
            )
            if count:
                recovered.set()
            return count

        worker_loop = service.room_kernel_worker_loop
        service.room_kernel_worker.clock_ms = lambda: 12
        worker_loop.recover_interrupted = recover_interrupted
        worker_loop.recovery_poll_seconds = 0.01
        worker_loop.poll_seconds = 0.01
        self.assertTrue(worker_loop.start())
        try:
            self.assertTrue(recovered.wait(1.0))
        finally:
            worker_loop.close()

        self.assertEqual(
            service.room_kernel.dispatch("dispatch:service")["state"],
            "failed",
        )
        self.assertEqual(
            service.room_kernel.task("task:service")["state"],
            "active",
        )
        self.assertEqual(
            service.room_kernel.root("root:service")["state"],
            "running",
        )
        with sqlite3.connect(service.db_path) as conn:
            rows = conn.execute(
                """
                SELECT dispatch_id, state, payload_json
                FROM room_kernel_dispatches
                WHERE root_id = 'root:service'
                """
            ).fetchall()
        self.assertEqual(len(rows), 2)
        fresh = next(row for row in rows if row[0] != "dispatch:service")
        fresh_payload = json.loads(str(fresh[2]))
        self.assertIn(str(fresh[1]), {"pending", "leased", "running"})
        self.assertEqual(fresh_payload["attempt"], 1)
        self.assertEqual(fresh_payload["intentKind"], "execute")

    def test_periodic_recovery_waits_for_the_runtime_grace_period(self) -> None:
        target = {"updatedAtMs": 10_000}

        self.assertFalse(
            _runtime_target_inactive_long_enough(
                target,
                observed_at_ms=14_999,
                minimum_inactive_ms=5_000,
            )
        )
        self.assertTrue(
            _runtime_target_inactive_long_enough(
                target,
                observed_at_ms=15_000,
                minimum_inactive_ms=5_000,
            )
        )

    def test_startup_recovery_accepts_legacy_targets_without_age(self) -> None:
        self.assertTrue(
            _runtime_target_inactive_long_enough(
                {},
                observed_at_ms=15_000,
                minimum_inactive_ms=0,
            )
        )
        self.assertFalse(
            _runtime_target_inactive_long_enough(
                {},
                observed_at_ms=15_000,
                minimum_inactive_ms=5_000,
            )
        )


if __name__ == "__main__":
    unittest.main()
