from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.room_runtime_host_kill_gate import RuntimeHostKillGate


class RuntimeHostKillGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="runtime-host-kill-gate-")
        self.db_path = Path(self.tmp.name) / "room.sqlite"
        self.observed: dict[int, tuple[int, str]] = {101: (101, "birth:101")}
        self.signals: list[int] = []
        self.gate = RuntimeHostKillGate(
            self.db_path,
            signal_tree=self.signals.append,
            identity_probe=lambda pid: self.observed.get(pid),
        )
        self.assertEqual(self.gate.initialize(), 92)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def register(self, *, owner: str = "runtime:old") -> None:
        self.gate.register_process(
            host_identity="host:1",
            owner_instance_id=owner,
            pid=101,
            process_group_id=101,
            job_identity="job:1",
            process_birth_token="birth:101",
            executable_ref="/managed/pi-host",
            now_ms=10,
        )

    def test_admin_panic_is_durable_and_kills_the_registered_process_tree(self) -> None:
        self.register()
        receipt = self.gate.request_kill(
            "host:1",
            request_kind="admin_panic",
            requested_by="admin:root",
            reason="operator panic",
            now_ms=20,
        )
        self.assertEqual(self.signals, [101])
        self.assertEqual(receipt["state"], "acknowledged")
        self.assertEqual(receipt["pendingTargets"][0]["jobIdentity"], "job:1")

        self.gate.mark_terminated("host:1", now_ms=21)
        terminal = self.gate.receipt(str(receipt["killReceiptId"]))
        self.assertEqual(terminal["state"], "terminated")
        self.assertEqual(terminal["pendingTargets"], [])

    def test_panic_requires_explicit_admin_identity(self) -> None:
        self.register()
        with self.assertRaises(PermissionError):
            self.gate.request_kill(
                "host:1",
                request_kind="admin_panic",
                requested_by="user:1",
                reason="not allowed",
                now_ms=20,
            )
        self.assertEqual(self.signals, [])

    def test_pid_reuse_fails_closed_without_signalling_an_unrelated_process(self) -> None:
        self.register()
        self.observed[101] = (101, "different-birth")
        receipt = self.gate.request_kill(
            "host:1",
            request_kind="cancel_timeout",
            requested_by="session:1",
            reason="abort did not settle",
            now_ms=20,
        )
        self.assertEqual(receipt["state"], "unknown")
        self.assertEqual(receipt["errorCode"], "process_identity_mismatch")
        self.assertEqual(self.signals, [])

    def test_restart_reconciles_an_orphan_but_not_the_current_owner(self) -> None:
        self.register(owner="runtime:old")
        receipts = self.gate.reconcile_orphans(owner_instance_id="runtime:new", now_ms=20)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["requestKind"], "orphan_reconcile")
        self.assertEqual(self.signals, [101])

        self.gate.mark_terminated("host:1", now_ms=21)
        self.observed[202] = (202, "birth:202")
        self.gate.register_process(
            host_identity="host:2",
            owner_instance_id="runtime:new",
            pid=202,
            process_group_id=202,
            job_identity="job:2",
            process_birth_token="birth:202",
            executable_ref="/managed/pi-host",
            now_ms=22,
        )
        self.assertEqual(self.gate.reconcile_orphans(owner_instance_id="runtime:new", now_ms=23), [])

    def test_already_exited_target_records_terminated_without_signal(self) -> None:
        self.register()
        self.observed.clear()
        receipt = self.gate.request_kill(
            "host:1",
            request_kind="cancel_timeout",
            requested_by="session:1",
            reason="abort timeout",
            now_ms=20,
        )
        self.assertEqual(receipt["state"], "terminated")
        self.assertEqual(receipt["pendingTargets"], [])
        self.assertEqual(self.signals, [])


if __name__ == "__main__":
    unittest.main()
