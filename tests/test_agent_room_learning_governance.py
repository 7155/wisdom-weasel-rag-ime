from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_learning_governance import LearningGovernanceError, RoomLearningGovernanceStore
from rag_ime.agent_room_peer_review import RoomPeerReviewStore
from rag_ime.agent_room_requirements import RequirementGovernanceStore


class RoomLearningGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-learning-")
        self.db = Path(self.tmp.name) / "room.sqlite"
        self.requirements = RequirementGovernanceStore(self.db); self.requirements.initialize()
        self.peer = RoomPeerReviewStore(self.db, runner_secrets={"runner:test": b"runner-secret"}); self.peer.initialize()
        self.store = RoomLearningGovernanceStore(self.db, authority_secrets={"admin:1": b"approval-secret", "user:1": b"user-secret"}, config_secret=b"config-secret", evidence_ttl_ms=1_000); self.assertEqual(self.store.initialize(), 86)
        self._seed_runtime()
        self.incident, _ = self._incident("incident:1", "occurrence:1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loop_incident_deduplicates_candidate_but_preserves_occurrences_and_no_binding_is_noop(self) -> None:
        ordinary, created = self.store.record_incident(incident_id="ordinary", occurrence_id="ordinary:1", binding_id=None, root_id="root:1", dispatch_id="dispatch:1", kernel_receipt_id="kernel-receipt:1", evidence_refs=["runner-receipt:1"], taxonomy="loop_detected", failure_signature="A-B-A", observed_at_ms=3)
        self.assertIsNone(ordinary); self.assertFalse(created)
        duplicate, duplicate_created = self._incident("incident:duplicate", "occurrence:2")
        self.assertFalse(duplicate_created); self.assertEqual(duplicate["incidentId"], "incident:1")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_incidents").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_incident_occurrences").fetchone()[0], 2)

    def test_bad_lesson_and_free_text_guard_fail_closed_and_candidate_is_immutable(self) -> None:
        with self.assertRaises(LearningGovernanceError):
            self.store.nominate_lesson(lesson_candidate_id="bad", incident_id="incident:1", facts=["loop"], causes=["unknown"], applicability_boundary={"scope": "room"}, counterexamples=[], provenance=["runner-receipt:1"], nominated_by="agent:reflection", created_at_ms=4)
        lesson = self._lesson()
        with self.assertRaisesRegex(LearningGovernanceError, "free-text"):
            self.store.nominate_guard(guard_candidate_id="guard:bad", lesson_candidate_id=lesson["lessonCandidateId"], guard_version=1, condition={"event": "dispatch_enqueue", "field": "depth", "operator": "gte", "value": 2, "ruleText": "cancel everything"}, action={"kind": "cancel", "target": "dispatch"}, scope={"kind": "room", "selector": "room:1"}, risk="high", thresholds=self._thresholds(), owner="team", sunset_at_ms=10_000, nominated_by="agent:reflection", created_at_ms=5)
        guard = self._guard()
        with sqlite3.connect(self.db) as conn, self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            conn.execute("UPDATE room_v2_guard_candidates SET risk='low' WHERE guard_candidate_id=?", (guard["guardCandidateId"],))

    def test_eval_gaming_failure_and_expired_evidence_cannot_activate(self) -> None:
        self._lesson(); guard = self._guard()
        with self.assertRaisesRegex(LearningGovernanceError, "gamed"):
            self.store.record_eval(eval_run_id="eval:gaming", guard_candidate_id="guard:1", mode="shadow", dataset_hash="a" * 64, positive_fixture_count=2, negative_fixture_count=2, metrics={"incidentRecall": 1, "falsePositiveRate": 0, "regressionRate": 0, "sampleCount": 3}, runner_receipt_id="runner-receipt:1", created_at_ms=10)
        failed = self.store.record_eval(eval_run_id="eval:failed", guard_candidate_id="guard:1", mode="shadow", dataset_hash="b" * 64, positive_fixture_count=2, negative_fixture_count=2, metrics={"incidentRecall": .2, "falsePositiveRate": .8, "regressionRate": .5, "sampleCount": 4}, runner_receipt_id="runner-receipt:1", created_at_ms=10)
        self.assertEqual(failed["status"], "failed")
        with self.assertRaisesRegex(LearningGovernanceError, "expired"):
            self.store.record_eval(eval_run_id="eval:expired", guard_candidate_id="guard:1", mode="canary", dataset_hash="c" * 64, positive_fixture_count=2, negative_fixture_count=2, metrics=self._metrics(), runner_receipt_id="runner-receipt:1", created_at_ms=2_000)
        approval = self.store.approve_guard(approval_receipt_id="approval:1", guard_candidate_id="guard:1", authority_ref="admin:1", decision="approve", created_at_ms=11, authority_secret=b"approval-secret")
        signature = self.store.expected_config_signature(scope={"kind": "room", "selector": "room:1"}, guard_candidate_id="guard:1", candidate_hash=guard["candidateHash"], guard_epoch=1, applies_after_ms=20, eval_run_ids=["eval:failed"])
        with self.assertRaisesRegex(LearningGovernanceError, "failed"):
            self.store.activate_guard(activation_receipt_id="activation:bad", guard_candidate_id="guard:1", approval_receipt_id=approval["approvalReceiptId"], eval_run_ids=["eval:failed"], now_ms=20, config_signature=signature)

    def test_self_approval_and_automatic_activation_are_impossible(self) -> None:
        self._lesson(); guard = self._guard(nominated_by="admin:1")
        with self.assertRaisesRegex(LearningGovernanceError, "self-approve"):
            self.store.approve_guard(approval_receipt_id="approval:self", guard_candidate_id="guard:1", authority_ref="admin:1", decision="approve", created_at_ms=10, authority_secret=b"approval-secret")
        with self.assertRaisesRegex(LearningGovernanceError, "automatic reflection"):
            self.store.activate_guard(activation_receipt_id="activation:auto", guard_candidate_id="guard:1", approval_receipt_id="missing", eval_run_ids=[], now_ms=20, config_signature="", automatic=True)

    def test_high_risk_activation_only_affects_new_root_and_rollback_is_atomic(self) -> None:
        self._lesson(); guard = self._guard()
        for eval_id, mode in (("eval:shadow", "shadow"), ("eval:canary", "canary")):
            result = self.store.record_eval(eval_run_id=eval_id, guard_candidate_id="guard:1", mode=mode, dataset_hash=("1" if mode == "shadow" else "2") * 64, positive_fixture_count=2, negative_fixture_count=2, metrics=self._metrics(), runner_receipt_id="runner-receipt:1", created_at_ms=10)
            self.assertEqual(result["status"], "passed")
        approval = self.store.approve_guard(approval_receipt_id="approval:1", guard_candidate_id="guard:1", authority_ref="admin:1", decision="approve", created_at_ms=11, authority_secret=b"approval-secret")
        evals = ["eval:shadow", "eval:canary"]
        signature = self.store.expected_config_signature(scope={"kind": "room", "selector": "room:1"}, guard_candidate_id="guard:1", candidate_hash=guard["candidateHash"], guard_epoch=1, applies_after_ms=100, eval_run_ids=evals)
        active = self.store.activate_guard(activation_receipt_id="activation:1", guard_candidate_id="guard:1", approval_receipt_id=approval["approvalReceiptId"], eval_run_ids=evals, now_ms=100, config_signature=signature)
        self.assertEqual(active["guardEpoch"], 1)
        with self.assertRaisesRegex(LearningGovernanceError, "signed config"):
            self.store.activate_guard(activation_receipt_id="activation:1", guard_candidate_id="guard:1", approval_receipt_id=approval["approvalReceiptId"], eval_run_ids=evals, now_ms=100, config_signature=signature)
        self.assertIsNone(self.store.guard_for_root(binding_id="binding:1", root_id="root:1", scope_key="room:room:1"))
        self._seed_new_root()
        self.assertEqual(self.store.guard_for_root(binding_id="participant-binding:dispatch:new", root_id="root:new", scope_key="room:room:1")["guardEpoch"], 1)
        self.store.bind_execution(dispatch_id="dispatch:new", root_id="root:new", scope_key="room:room:1", guard_epoch=1, now_ms=102)
        with self.assertRaisesRegex(LearningGovernanceError, "injected"):
            self.store.rollback(rollback_receipt_id="rollback:crash", scope_key="room:room:1", authority_ref="user:1", authority_secret=b"user-secret", reason="emergency", now_ms=103, fail_before_pointer=True)
        self.store.accept_writeback(dispatch_id="dispatch:new", guard_epoch=1)
        rollback = self.store.rollback(rollback_receipt_id="rollback:1", scope_key="room:room:1", authority_ref="user:1", authority_secret=b"user-secret", reason="regression", now_ms=104)
        self.assertEqual(rollback["guardEpoch"], 2); self.assertEqual(rollback["cancelledDispatchIds"], ["dispatch:new"])
        with self.assertRaisesRegex(LearningGovernanceError, "old Guard epoch"):
            self.store.accept_writeback(dispatch_id="dispatch:new", guard_epoch=1)
        with self.assertRaises(LearningGovernanceError):
            self.store.rollback(rollback_receipt_id="rollback:replay", scope_key="room:room:1", authority_ref="user:1", authority_secret=b"user-secret", reason="again", now_ms=105)

    def _seed_runtime(self) -> None:
        raw = b"prevent agent routing loop"
        self.requirements.append_anchor(anchor_id="anchor:1", root_id="root:1", original_content=raw, created_by="user", provenance={"event": "1"}, created_at_ms=1)
        self.requirements.revise_catalog(catalog_revision_id="catalog:1", root_id="root:1", expected_current_revision=0, anchor_refs=["anchor:1"], items=[{"itemId": "req:1", "kind": "explicit_user_requirement", "statement": "prevent loop", "origin": "user", "state": "active", "sourceSpans": [{"anchorId": "anchor:1", "startByte": 0, "endByte": len(raw)}]}], acceptance_criteria=[{"criterionId": "criterion:1", "itemId": "req:1", "acceptanceCriterionFullNameZh": "循环防护验收标准", "criterionKind": "requirement", "expectedReceiptTypes": ["test"], "statement": "loop is bounded"}], change_reason="initial", provenance={"source": "user"}, created_by="catalog", created_at_ms=1)
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO room_kernel_roots(root_id,room_id,generation,state,owner,requirement_anchor_ref,budget_remaining,max_hops,max_depth,payload_json,created_at_ms,updated_at_ms) VALUES ('root:1','room:1',0,'running','owner','anchor:1',10,4,4,'{}',1,1)")
            conn.execute("INSERT INTO room_kernel_tasks(task_id,root_id,state,payload_json,updated_at_ms) VALUES ('task:1','root:1','running','{}',1)")
            conn.execute("INSERT INTO room_kernel_dispatches(dispatch_id,root_id,task_id,generation,hop_count,depth,budget_cost,target_session_id,target_participant_id,trigger_id,intent_kind,idempotency_key,state,payload_json,created_at_ms,updated_at_ms) VALUES ('dispatch:1','root:1','task:1',0,2,2,1,'session','participant','trigger','mention','key','failed','{}',1,2)")
            conn.execute("INSERT INTO room_kernel_receipts(receipt_id,root_id,receipt_kind,status,generation,payload_json,created_at_ms) VALUES ('kernel-receipt:1','root:1','dispatch_failed','failed',0,'{}',2)")
            conn.execute("INSERT INTO room_v2_capability_manifests(manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,generation,capability_revision,capability_epoch,manifest_hash,payload_json,created_at_ms) VALUES ('manifest:1','binding:1','room:1','root:1','task:1','dispatch:1',0,'1',1,?,'{}',1)", ("a" * 64,))
        material = {"receiptId": "runner-receipt:1", "rootId": "root:1", "catalogRevisionId": "catalog:1", "receiptType": "test", "sourceCommit": "commit:1", "environment": "room-v2-test", "worktreeHash": "b" * 64, "commandOrAction": "loop regression", "exitStatus": 0, "outputHash": "c" * 64, "artifactHash": "d" * 64, "toolVersion": "runner-1", "issuerId": "runner:test", "createdAtMs": 3}
        self.peer.record_runner_receipt(self.peer.issue_runner_receipt(material, issuer_secret=b"runner-secret"))

    def _seed_new_root(self) -> None:
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO room_kernel_roots(root_id,room_id,generation,state,owner,requirement_anchor_ref,budget_remaining,max_hops,max_depth,payload_json,created_at_ms,updated_at_ms) VALUES ('root:new','room:1',0,'running','owner','anchor:1',10,4,4,'{}',101,101)")
            conn.execute("INSERT INTO room_kernel_tasks(task_id,root_id,state,payload_json,updated_at_ms) VALUES ('task:new','root:new','running','{}',101)")
            conn.execute("INSERT INTO room_kernel_dispatches(dispatch_id,root_id,task_id,generation,hop_count,depth,budget_cost,target_session_id,target_participant_id,trigger_id,intent_kind,idempotency_key,state,payload_json,created_at_ms,updated_at_ms) VALUES ('dispatch:new','root:new','task:new',0,0,0,1,'session','participant','trigger','mention','new-key','running','{}',101,101)")
            conn.execute("INSERT INTO room_v2_capability_manifests(manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,generation,capability_revision,capability_epoch,manifest_hash,payload_json,created_at_ms) VALUES ('manifest:new','binding:new','room:1','root:new','task:new','dispatch:new',0,'1',1,?,'{}',101)", ("e" * 64,))

    def _incident(self, incident_id, occurrence_id):
        return self.store.record_incident(incident_id=incident_id, occurrence_id=occurrence_id, binding_id="binding:1", root_id="root:1", dispatch_id="dispatch:1", kernel_receipt_id="kernel-receipt:1", evidence_refs=["runner-receipt:1"], taxonomy="loop_detected", failure_signature="A -> B -> A exceeded depth", observed_at_ms=3)

    def _lesson(self):
        return self.store.nominate_lesson(lesson_candidate_id="lesson:1", incident_id="incident:1", facts=["dispatch loop repeated"], causes=["cycle not fenced"], applicability_boundary={"scope": "Room mention routing", "exclusions": ["ordinary sessions"]}, counterexamples=["A to B once is valid"], provenance=["incident:1", "runner-receipt:1"], nominated_by="agent:reflection", created_at_ms=4)

    def _guard(self, nominated_by="agent:reflection"):
        return self.store.nominate_guard(guard_candidate_id="guard:1", lesson_candidate_id="lesson:1", guard_version=1, condition={"event": "dispatch_enqueue", "field": "depth", "operator": "gte", "value": 2}, action={"kind": "cancel", "target": "dispatch"}, scope={"kind": "room", "selector": "room:1"}, risk="high", thresholds=self._thresholds(), owner="room-runtime", sunset_at_ms=10_000, nominated_by=nominated_by, created_at_ms=5)

    @staticmethod
    def _thresholds(): return {"minIncidentRecall": .9, "maxFalsePositiveRate": .05, "maxRegressionRate": 0}

    @staticmethod
    def _metrics(): return {"incidentRecall": 1, "falsePositiveRate": 0, "regressionRate": 0, "sampleCount": 4}


if __name__ == "__main__": unittest.main()
