from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_governance_projection import GovernanceProjectionStore


class GovernanceProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="governance-projection-")
        self.db = Path(self.tmp.name) / "governance.sqlite"
        self.store = GovernanceProjectionStore(self.db); self.assertEqual(self.store.initialize(), 90)
        self._seed()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_uses_canonical_sanitized_contracts_and_pointer_is_only_active_truth(self) -> None:
        self.store.record_reflection_dead_letter(dead_letter_id="dead:1", incident_id="incident:1", owner_ref="team:runtime", reason_code="provider_empty", last_evidence_refs=["evidence:1"], next_action="inspect provider", attempt_count=3, created_at_ms=20)
        self.store.record_materialization(materialization_receipt_id="material:1", guard_candidate_id="guard:1", guard_epoch=1, artifact_kind="runtime_policy", status="materialized", artifact_hash="artifact-hash", projection_ref="policy:1", error_code="", created_at_ms=21)
        snapshot = self.store.snapshot(scope_key="room:room:1")

        self.assertEqual(snapshot["incidents"][0]["occurrenceCount"], 2)
        self.assertEqual(snapshot["lessons"][0]["state"], "candidate_only")
        self.assertEqual(snapshot["guardCandidates"][0]["state"], "candidate_only")
        self.assertNotIn("authoritySignature", snapshot["approvals"][0])
        self.assertNotIn("configSignature", snapshot["activations"][0])
        self.assertNotIn("active", snapshot["activations"][0])
        self.assertEqual(snapshot["activePointers"][0]["activeGuardCandidateId"], "guard:1")
        self.assertNotIn("prompt", json.dumps(snapshot).lower())
        self.assertEqual(snapshot["deadLetters"][0]["nextAction"], "inspect provider")
        self.assertEqual(snapshot["materializations"][0]["status"], "materialized")

    def _seed(self) -> None:
        h = "a" * 64
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO room_v2_incidents VALUES ('incident:1','root:1','dispatch:1','receipt:1','loop_detected','A-B-A',?, '[\"evidence:1\"]',?,1)", (h, h))
            conn.execute("INSERT INTO room_v2_incident_occurrences VALUES ('occ:1','incident:1','root:1','dispatch:1','receipt:1','[\"evidence:1\"]',2)")
            conn.execute("INSERT INTO room_v2_incident_occurrences VALUES ('occ:2','incident:1','root:1','dispatch:1','receipt:1','[\"evidence:1\"]',3)")
            conn.execute("INSERT INTO room_v2_lesson_candidates VALUES ('lesson:1','incident:1','[\"fact\"]','[\"cause\"]','{\"scope\":\"room\",\"exclusions\":[\"ordinary\"]}','[\"counter\"]','[\"evidence:1\"]',?,'agent:reflection',4)", (h,))
            conn.execute("INSERT INTO room_v2_guard_candidates VALUES ('guard:1','lesson:1',1,'{\"event\":\"dispatch_enqueue\",\"field\":\"depth\",\"operator\":\"gte\",\"value\":2}','{\"kind\":\"cancel\",\"target\":\"dispatch\"}','{\"kind\":\"room\",\"selector\":\"room:1\"}','high','{\"minIncidentRecall\":0.9,\"maxFalsePositiveRate\":0.05,\"maxRegressionRate\":0}','runtime',9999,?,'agent:reflection',5)", (h,))
            conn.execute("INSERT INTO room_v2_guard_eval_runs VALUES ('eval:1','guard:1',?,'shadow',?,2,2,'{\"incidentRecall\":1}','receipt:runner','passed',?,6)", (h, h, h))
            conn.execute("INSERT INTO room_v2_guard_approval_receipts VALUES ('approval:1','guard:1',?,'admin:1','approve',?,?,7)", (h, h, h))
            conn.execute("INSERT INTO room_v2_guard_activation_receipts VALUES ('activation:1','room:room:1','guard:1',?,NULL,NULL,1,8,'approval:1','[\"eval:1\"]',?,?,8)", (h, h, h))
            conn.execute("INSERT INTO room_v2_guard_active_pointers VALUES ('room:room:1',1,'guard:1',?,'activation:1',8)", (h,))
            conn.execute("INSERT INTO room_v2_guard_rollback_receipts VALUES ('rollback:1','room:room:1','guard:old',NULL,1,'[\"dispatch:old\"]','admin:1','regression',?,?,?,9)", (h, h, h))


if __name__ == "__main__": unittest.main()
