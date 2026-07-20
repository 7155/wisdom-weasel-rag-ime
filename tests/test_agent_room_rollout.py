from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from rag_ime.agent_room_rollout import READINESS_COMPONENTS, RoomRolloutError, RoomRolloutStore


class RoomRolloutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-rollout-")
        self.db = Path(self.tmp.name) / "rollout.sqlite"
        self.store = RoomRolloutStore(self.db, admin_secrets={"admin:release": b"release-secret"})
        self.assertEqual(self.store.initialize(), 95)
        self.readiness = {key: f"sha256:{key}" for key in READINESS_COMPONENTS}
        self.metrics = {"unknown": 0, "deadLetter": 0, "authorizationLeakage": 0, "canaryPassed": True}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _promote(self, stage: str, *, previous: str | None, policy_id: str, cohort: str = ""):
        readiness_hash = self.store.readiness_hash(self.readiness)
        material = self.store.promotion_material(policy_id=policy_id, previous_policy_id=previous, stage=stage,
            cohort_id=cohort, readiness_hash=readiness_hash, canary_metrics=self.metrics,
            rollback_target="named_canary" if stage in {"production_cohort", "kernel_only"} else stage,
            admin_ref="admin:release", created_at_ms=1)
        return self.store.promote(policy_id=policy_id, receipt_id="receipt:" + policy_id, stage=stage, cohort_id=cohort,
            readiness=self.readiness, canary_metrics=self.metrics, rollback_target=str(material["rollbackTarget"]),
            admin_ref="admin:release", approval_signature=self.store.sign(admin_ref="admin:release", material=material), created_at_ms=1)

    def test_monotonic_signed_rollout_and_root_owner_fence(self) -> None:
        off = self._promote("off", previous=None, policy_id="policy:off")
        self.assertEqual(self.store.assign_root(root_id="root:legacy", created_at_ms=2)["owner"], "legacy")
        shadow = self._promote("shadow", previous=off["policyId"], policy_id="policy:shadow")
        canary = self._promote("named_canary", previous=shadow["policyId"], policy_id="policy:canary", cohort="room-v2-canary")
        self.assertEqual(self.store.assign_root(root_id="root:kernel", created_at_ms=3)["owner"], "kernel")
        with self.assertRaisesRegex(RoomRolloutError, "dual execution"):
            self.store.assign_root(root_id="root:legacy", created_at_ms=4)
        production = self._promote("production_cohort", previous=canary["policyId"], policy_id="policy:production", cohort="room-v2-canary")
        self.assertEqual(production["stage"], "production_cohort")
        with self.assertRaisesRegex(RoomRolloutError, "does not match"):
            material = {"policyId": production["policyId"], "targetStage": "shadow", "rootIds": ["root:kernel"], "adminRef": "admin:release", "createdAtMs": 5}
            self.store.rollback(receipt_id="rollback:bad", target_stage="shadow", admin_ref="admin:release",
                approval_signature=self.store.sign(admin_ref="admin:release", material=material), created_at_ms=5, cancel_root=lambda _root: None)
        kernel_only = self._promote("kernel_only", previous=production["policyId"], policy_id="policy:kernel-only", cohort="room-v2-canary")
        material = {"policyId": kernel_only["policyId"], "targetStage": "named_canary", "rootIds": ["root:kernel"], "adminRef": "admin:release", "createdAtMs": 6}
        cancelled = []
        receipt = self.store.rollback(receipt_id="rollback:stop", target_stage="named_canary", admin_ref="admin:release",
            approval_signature=self.store.sign(admin_ref="admin:release", material=material), created_at_ms=6, cancel_root=cancelled.append)
        self.assertEqual(cancelled, ["root:kernel"])
        self.assertTrue(receipt["newRootsStopped"]); self.assertTrue(receipt["ledgerPreserved"])
        with self.assertRaisesRegex(RoomRolloutError, "explicit signed off policy"):
            self.store.assign_root(root_id="root:after-rollback", created_at_ms=7)

    def test_readiness_metrics_and_signature_fail_closed(self) -> None:
        self._promote("off", previous=None, policy_id="policy:off")
        with self.assertRaisesRegex(RoomRolloutError, "exactly once"):
            self.store.readiness_hash({"product": "x"})
        with self.assertRaisesRegex(RoomRolloutError, "signature"):
            self.store.promote(policy_id="policy:shadow", receipt_id="receipt:bad", stage="shadow", cohort_id="",
                readiness=self.readiness, canary_metrics=self.metrics, rollback_target="shadow", admin_ref="admin:release",
                approval_signature="0" * 64, created_at_ms=2)

    def test_kernel_only_rejects_bound_legacy_but_not_ordinary_sessions(self) -> None:
        kernel = RoomKernelStore(self.db, mode="kernel_only")
        self.assertEqual(kernel.normalize_compatibility_entry({}, room_binding_ref=None, source_kind="intercom", source_id="ordinary", now_ms=1), (None, False))
        with self.assertRaisesRegex(RoomKernelFenceError, "kernel_only"):
            kernel.normalize_compatibility_entry({}, room_binding_ref={"schemaVersion": "wisdom-weasel.room-binding.v2"}, source_kind="tool_executor", source_id="legacy-tool", now_ms=2)


if __name__ == "__main__":
    unittest.main()
