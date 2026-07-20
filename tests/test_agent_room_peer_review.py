from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_peer_review import PeerReviewFenceError, RoomPeerReviewStore, RunnerReceiptError
from rag_ime.agent_room_requirements import RequirementGovernanceStore


class RoomPeerReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="peer-review-")
        self.db = Path(self.tmp.name) / "room.sqlite"
        self.requirements = RequirementGovernanceStore(self.db); self.requirements.initialize()
        self.peer = RoomPeerReviewStore(self.db, runner_secrets={"runner:test": b"secret"}); self.peer.initialize()
        self._seed_catalog()
        self._seed_room_participant("author", "researcher")
        self._seed_room_participant("reviewer-a", "reviewer")
        self._seed_room_participant("reviewer-b", "reviewer")
        self._seed_room_participant("arbiter", "coordinator")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_blind_input_rejects_author_identity_and_author_cannot_self_review(self) -> None:
        with self.assertRaisesRegex(PeerReviewFenceError, "leaks"):
            self.peer.open_round(**self._round_args("round:leak", blind_input={"artifact": "x", "authorIdentity": "author"}))
        self.peer.open_round(**self._round_args("round:1"))
        with self.assertRaisesRegex(PeerReviewFenceError, "self-review"):
            self.peer.submit_judgment(**self._judgment_args("judgment:self", "round:1", "author", "pass"))
        self.assertNotIn("author", json.dumps(self.peer.blind_input("round:1")))

    def test_duplicate_or_colluding_reviewer_identity_is_rejected(self) -> None:
        self.peer.open_round(**self._round_args("round:dup"))
        self.peer.submit_judgment(**self._judgment_args("judgment:a", "round:dup", "reviewer-a", "pass"))
        with self.assertRaisesRegex(PeerReviewFenceError, "duplicate or colluding"):
            self.peer.submit_judgment(**self._judgment_args("judgment:a2", "round:dup", "reviewer-a", "pass"))

    def test_disagreement_creates_revisioned_matrix_and_only_independent_authority_resolves(self) -> None:
        self.peer.open_round(**self._round_args("round:conflict"))
        self.peer.submit_judgment(**self._judgment_args("judgment:a", "round:conflict", "reviewer-a", "pass"))
        self.peer.submit_judgment(**self._judgment_args("judgment:b", "round:conflict", "reviewer-b", "fail"))
        final = self.peer.finalize_round(final_receipt_id="final:conflict", round_id="round:conflict", matrix_revision_id="matrix:1", created_at_ms=5)
        self.assertEqual(final["status"], "conflict")
        with self.assertRaisesRegex(PeerReviewFenceError, "independent"):
            self.peer.resolve_conflict(resolution_receipt_id="resolution:bad", round_id="round:conflict", open_matrix_revision_id="matrix:1", resolved_matrix_revision_id="matrix:2bad", authority_kind="independent_arbiter", authority_ref="reviewer-a", resolution_verdict="pass", rationale="self", created_at_ms=6)
        resolved = self.peer.resolve_conflict(resolution_receipt_id="resolution:ok", round_id="round:conflict", open_matrix_revision_id="matrix:1", resolved_matrix_revision_id="matrix:2", authority_kind="independent_arbiter", authority_ref="arbiter", resolution_verdict="pass", rationale="evidence wins", created_at_ms=6)
        self.assertEqual(resolved["resolutionVerdict"], "pass")

    def test_runner_receipt_tamper_copy_replay_and_old_revision_fail_closed(self) -> None:
        receipt = self._signed_receipt("receipt:1")
        self.peer.record_runner_receipt(receipt)
        tampered = {**receipt, "receiptId": "receipt:tamper", "exitStatus": 1}
        with self.assertRaisesRegex(RunnerReceiptError, "signature"):
            self.peer.record_runner_receipt(tampered)
        copied = {**receipt, "receiptId": "receipt:copy"}
        copied = self.peer.issue_runner_receipt({key: value for key, value in copied.items() if key not in {"schemaVersion", "contentHash", "issuerSignature"}}, issuer_secret=b"secret")
        with self.assertRaisesRegex(RunnerReceiptError, "copied"):
            self.peer.record_runner_receipt(copied)
        self._revise_catalog()
        old = self._signed_receipt("receipt:old", catalog="catalog:1")
        with self.assertRaisesRegex(RunnerReceiptError, "old"):
            self.peer.record_runner_receipt(old)

    def test_test_cohort_preview_blocks_unknown_and_production_never_enforces(self) -> None:
        self._complete_passing_round_and_proof("round:gate")
        production = self.peer.preview_delivery_gate(preview_receipt_id="preview:prod", root_id="root:1", catalog_revision_id="catalog:1", peer_round_id="round:gate", target_commit="commit:1", environment="production", created_at_ms=8)
        self.assertEqual(production["mode"], "observe_warn"); self.assertFalse(production["terminalAllowed"])
        preview = self.peer.preview_delivery_gate(preview_receipt_id="preview:test", root_id="root:1", catalog_revision_id="catalog:1", peer_round_id="round:gate", target_commit="commit:1", environment="room-v2-test", created_at_ms=8)
        self.assertTrue(preview["terminalAllowed"])
        self.requirements.record_obstacle(obstacle_id="unknown:1", root_id="root:1", catalog_revision_id="catalog:1", obstacle_kind="unknown", statement="installation unknown", created_at_ms=9)
        blocked = self.peer.preview_delivery_gate(preview_receipt_id="preview:blocked", root_id="root:1", catalog_revision_id="catalog:1", peer_round_id="round:gate", target_commit="commit:1", environment="room-v2-test", created_at_ms=10)
        self.assertFalse(blocked["terminalAllowed"]); self.assertIn("unresolved_unknown", blocked["reasons"])

    def test_preview_blocks_failed_blind_review_user_journey_and_blocker(self) -> None:
        self.peer.open_round(**self._round_args("round:failed"))
        self.peer.submit_judgment(**self._judgment_args("judgment:fa", "round:failed", "reviewer-a", "fail"))
        self.peer.submit_judgment(**self._judgment_args("judgment:fb", "round:failed", "reviewer-b", "fail"))
        self.peer.finalize_round(final_receipt_id="final:failed", round_id="round:failed", matrix_revision_id="unused", created_at_ms=6)
        failed = self._signed_receipt("receipt:failed")
        failed = self.peer.issue_runner_receipt({**{key: value for key, value in failed.items() if key not in {"schemaVersion", "contentHash", "issuerSignature"}}, "exitStatus": 1}, issuer_secret=b"secret")
        self.peer.record_runner_receipt(failed)
        self.requirements.link_proof(proof_id="proof:failed", root_id="root:1", catalog_revision_id="catalog:1", criterion_id="criterion:journey", receipt_id="receipt:failed", linked_by="runner:test", created_at_ms=7)
        self.requirements.record_obstacle(obstacle_id="blocker:1", root_id="root:1", catalog_revision_id="catalog:1", obstacle_kind="blocker", statement="installer failed", created_at_ms=7)
        preview = self.peer.preview_delivery_gate(preview_receipt_id="preview:failed", root_id="root:1", catalog_revision_id="catalog:1", peer_round_id="round:failed", target_commit="commit:1", environment="room-v2-test", created_at_ms=8)
        self.assertFalse(preview["terminalAllowed"])
        self.assertIn("blind_review_not_passed", preview["reasons"])
        self.assertIn("criterion_without_signed_proof:criterion:journey", preview["reasons"])
        self.assertIn("unresolved_blocker", preview["reasons"])

    def _seed_catalog(self) -> None:
        raw = "保留原始需求并验证用户旅程".encode()
        self.requirements.append_anchor(anchor_id="anchor:1", root_id="root:1", original_content=raw, created_by="user", provenance={"event": "1"}, created_at_ms=1)
        self.requirements.revise_catalog(catalog_revision_id="catalog:1", root_id="root:1", expected_current_revision=0, anchor_refs=["anchor:1"], items=[{"itemId": "req:1", "kind": "explicit_user_requirement", "statement": "保留并验证", "origin": "user", "state": "active", "sourceSpans": [{"anchorId": "anchor:1", "startByte": 0, "endByte": len(raw)}]}], acceptance_criteria=[{"criterionId": "criterion:journey", "itemId": "req:1", "acceptanceCriterionFullNameZh": "用户旅程验收标准", "criterionKind": "user_journey", "expectedReceiptTypes": ["browser"], "statement": "journey passes"}], change_reason="initial", provenance={"source": "user"}, created_by="catalog", created_at_ms=1)

    def _revise_catalog(self) -> None:
        raw_len = len(self.requirements.original_bytes("anchor:1"))
        self.requirements.revise_catalog(catalog_revision_id="catalog:2", root_id="root:1", expected_current_revision=1, anchor_refs=["anchor:1"], items=[{"itemId": "req:1", "kind": "explicit_user_requirement", "statement": "changed", "origin": "user", "state": "active", "sourceSpans": [{"anchorId": "anchor:1", "startByte": 0, "endByte": raw_len}]}], acceptance_criteria=[{"criterionId": "criterion:journey", "itemId": "req:1", "acceptanceCriterionFullNameZh": "用户旅程验收标准", "criterionKind": "user_journey", "expectedReceiptTypes": ["browser"], "statement": "changed"}], change_reason="discovery", provenance={"source": "user"}, created_by="catalog", created_at_ms=10)

    def _seed_room_participant(self, participant: str, role: str) -> None:
        session = "session:" + participant; binding_id = "binding:" + participant; manifest = "manifest:" + participant
        h = "a" * 64
        participant_binding = {"schemaVersion": "wisdom-weasel.room-participant-binding.v2", "bindingId": binding_id, "sessionId": session, "roomBindingRef": {"bindingId": "room-binding:" + participant, "schemaVersion": "wisdom-weasel.room-binding.v2"}, "personaRef": f"rag-ime-definition://persona/test?version=1&contentHash=sha256:{h}", "collaborationRoleRef": f"rag-ime-definition://collaboration-role/{role}?version=1&contentHash=sha256:{h}", "agentTemplateRef": f"rag-ime-definition://agent-template/test?version=1&contentHash=sha256:{h}", "collaborationProfileRef": None, "compiledRuntimeProfileRef": {"profileId": "profile:" + participant, "revision": "1", "contentHash": "sha256:" + h}, "capabilityRevision": "1", "capabilityEpoch": 1}
        room_binding = {"rootId": "root:1", "roomId": "room:1", "bindingId": "room-binding:" + participant}
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT OR IGNORE INTO agent_sessions(id,title,session_mode,role_id,role_version,model_profile,tool_profile_version,created_at_ms,updated_at_ms,last_opened_at_ms,status) VALUES (?, ?, 'coordinator', ?, '1', 'test', 'test', 1, 1, 1, 'active')", (session, participant, role))
            conn.execute("INSERT OR IGNORE INTO agent_rooms(id,title,routing_policy,status,room_file,created_at_ms,updated_at_ms) VALUES ('room:1','room','manual_mentions','active','room.md',1,1)")
            collaboration = "coordinator" if role == "coordinator" else "researcher"
            conn.execute("INSERT INTO agent_room_participants(id,room_id,session_id,role_id,role_version,display_name,participant_status,ordinal,created_at_ms,collaboration_role) VALUES (?, 'room:1', ?, ?, '1', ?, 'active', (SELECT COUNT(*) FROM agent_room_participants), 1, ?)", (participant, session, role, participant, collaboration))
            conn.execute("INSERT INTO room_v2_capability_manifests(manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,generation,capability_revision,capability_epoch,manifest_hash,payload_json,created_at_ms) VALUES (?, ?, 'room:1','root:1','task','dispatch:'||?,0,'1',1,?, '{}',1)", (manifest, binding_id, participant, h))
            conn.execute("INSERT INTO room_v2_capability_runtime_bindings(session_id,manifest_id,manifest_hash,prompt_compile_receipt_id,prompt_plan_hash,compiled_profile_id,compiled_profile_revision,compiled_profile_hash,room_binding_json,participant_binding_json,capability_epoch,state,created_at_ms,updated_at_ms) VALUES (?, ?, ?, 'prompt', ?, ?, '1', ?, ?, ?, 1, 'active', 1, 1)", (session, manifest, h, h, "profile:" + participant, h, json.dumps(room_binding), json.dumps(participant_binding)))

    def _round_args(self, round_id: str, blind_input=None):
        return {"round_id": round_id, "room_id": "room:1", "root_id": "root:1", "catalog_revision_id": "catalog:1", "target_commit": "commit:1", "artifact_content_hash": "c" * 64, "blind_input": blind_input or {"requirements": ["criterion:journey"], "artifactRefs": ["artifact:1"]}, "author_participant_ids": ["author"], "minimum_reviewers": 2, "created_at_ms": 2}

    def _judgment_args(self, judgment: str, round_id: str, reviewer: str, verdict: str):
        return {"judgment_id": judgment, "round_id": round_id, "reviewer_participant_id": reviewer, "verdict": verdict, "findings": [] if verdict == "pass" else [{"severity": "high", "code": "journey-failed", "criterionId": "criterion:journey"}], "requirement_coverage": ["criterion:journey"], "created_at_ms": 4}

    def _signed_receipt(self, receipt_id: str, *, catalog="catalog:1"):
        return self.peer.issue_runner_receipt({"receiptId": receipt_id, "rootId": "root:1", "catalogRevisionId": catalog, "receiptType": "browser", "sourceCommit": "commit:1", "environment": "room-v2-test", "worktreeHash": "d" * 64, "commandOrAction": "browser journey", "exitStatus": 0, "outputHash": "e" * 64, "artifactHash": "f" * 64, "toolVersion": "playwright-1", "issuerId": "runner:test", "createdAtMs": 3}, issuer_secret=b"secret")

    def _complete_passing_round_and_proof(self, round_id: str) -> None:
        self.peer.open_round(**self._round_args(round_id))
        self.peer.submit_judgment(**self._judgment_args("judgment:a:" + round_id, round_id, "reviewer-a", "pass"))
        self.peer.submit_judgment(**self._judgment_args("judgment:b:" + round_id, round_id, "reviewer-b", "pass"))
        self.peer.finalize_round(final_receipt_id="final:" + round_id, round_id=round_id, matrix_revision_id="unused:" + round_id, created_at_ms=6)
        receipt = self._signed_receipt("receipt:" + round_id); self.peer.record_runner_receipt(receipt)
        self.requirements.link_proof(proof_id="proof:" + round_id, root_id="root:1", catalog_revision_id="catalog:1", criterion_id="criterion:journey", receipt_id=receipt["receiptId"], linked_by="runner:test", created_at_ms=7)


if __name__ == "__main__": unittest.main()
