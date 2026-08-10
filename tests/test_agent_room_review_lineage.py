from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.db import latest_migration_version


_FIRST_REVISION = f"sha256:{'a' * 64}"
_TARGET_REVISION = f"sha256:{'b' * 64}"


def _fingerprint(*, scope: dict[str, str]) -> str:
    material = {
        "category": "correctness",
        "scope": scope,
        "observation": "The reviewed command still returns the stale value.",
        "expected": "The command returns the current value.",
        "userImpact": "The user receives an incorrect result.",
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finding(
    *,
    scope: dict[str, str] | None = None,
    state: str = "open",
    failed_rechecks: int = 0,
    response: dict[str, object] | None = None,
) -> dict[str, object]:
    canonical_scope = scope or {"criterionId": "ac:1"}
    return {
        "findingId": "finding:F1",
        "fingerprint": _fingerprint(scope=canonical_scope),
        "gateEffect": "blocking",
        "impact": "critical",
        "category": "correctness",
        "scope": canonical_scope,
        "observation": "The reviewed command still returns the stale value.",
        "expected": "The command returns the current value.",
        "userImpact": "The user receives an incorrect result.",
        "evidenceRefs": ["test:review-lineage"],
        "reproduction": ["Run the reviewed command once."],
        "state": state,
        "dispositionRationale": (
            "Independent arbiter superseded the blocker."
            if state == "dismissed"
            else None
        ),
        "ownerParticipantId": "participant:a",
        "firstSeenRevision": _FIRST_REVISION,
        "lastCheckedRevision": _FIRST_REVISION,
        "failedRechecks": failed_rechecks,
        "response": response,
    }


class RoomKernelReviewFindingLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-review-lineage-"
        )
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), latest_migration_version())
        self.store.create_root_with_task(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:1",
                "roomId": "room:1",
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": "participant:a",
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:1@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": True,
                "createdAtMs": 1,
            },
            self._task("task:work", task_kind="work"),
            budget=4,
            max_hops=4,
            max_depth=2,
            acceptance_criteria=("ac:1",),
            now_ms=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _task(
        task_id: str,
        *,
        task_kind: str,
        findings: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        is_review = task_kind == "review"
        payload: dict[str, object] = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": task_id,
            "rootId": "root:1",
            "parentTaskId": "task:work" if is_review else None,
            "taskKind": task_kind,
            "currentOwnerParticipantId": (
                "participant:reviewer" if is_review else "participant:a"
            ),
            "ownershipRevision": 0,
            "ownershipReceiptId": None,
            "invitationId": None,
            "reviewState": "in_review" if is_review else "not_required",
            "reviewOfTaskIds": ["task:work"] if is_review else [],
            "reviewAuthorParticipantIds": ["participant:a"] if is_review else [],
            "contextEvidenceRefs": [],
            "objective": "Review the bounded implementation.",
            "expectedOutput": "A lineage-preserving review result.",
            "requirementItemIds": ["requirement:1"],
            "acceptanceCriterionIds": ["ac:1"],
            "revision": 1 if is_review else 0,
            "state": "active",
        }
        if is_review:
            payload.update(
                {
                    "reviewRound": 2,
                    "reviewTargetRevision": _TARGET_REVISION,
                    "reviewEvidenceNotBeforeMs": 2,
                    "reviewFindings": findings or [],
                }
            )
        return payload

    def _start_review(
        self,
        prior: dict[str, object] | None,
        *,
        dispatch_id: str,
        now_ms: int = 2,
    ) -> None:
        review_task = self._task(
            "task:review",
            task_kind="review",
            findings=[] if prior is None else [prior],
        )
        review_task["reviewRound"] = 1 if prior is None else 2
        self.store.create_task(review_task, now_ms=now_ms)
        self.store.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": dispatch_id,
                "rootId": "root:1",
                "taskId": "task:review",
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 1,
                "budgetCost": 1,
                "targetSessionId": "session:reviewer",
                "targetParticipantId": "participant:reviewer",
                "triggerId": f"trigger:{dispatch_id}",
                "intentKind": "review",
                "idempotencyKey": f"key:{dispatch_id}",
                "attempt": 1,
                "capabilityEpoch": 1,
                "runtimeProfileRevision": "runtime-profile:test-v1",
                "state": "pending",
            },
            now_ms=now_ms + 1,
        )
        self.store.set_dispatch_wait_state(
            dispatch_id,
            "running",
            now_ms=now_ms + 2,
        )
        self._record_runtime_evidence(
            dispatch_id=dispatch_id,
            created_at_ms=now_ms + 3,
        )

    def _record_runtime_evidence(
        self,
        *,
        dispatch_id: str,
        created_at_ms: int,
        evidence_ref: str = "test:review-lineage",
    ) -> None:
        manifest_id = f"manifest:{dispatch_id}"
        manifest_hash = "c" * 64
        invocation_id = f"invoke:{dispatch_id}:evidence"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO room_v2_capability_manifests(
                   manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,
                   generation,capability_revision,capability_epoch,manifest_hash,
                   payload_json,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest_id,
                    f"binding:{dispatch_id}",
                    "room:1",
                    "root:1",
                    "task:review",
                    dispatch_id,
                    0,
                    "capability:test-v1",
                    1,
                    manifest_hash,
                    "{}",
                    created_at_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_capability_runtime_bindings(
                   session_id,manifest_id,manifest_hash,prompt_compile_receipt_id,
                   prompt_plan_hash,compiled_profile_id,compiled_profile_revision,
                   compiled_profile_hash,room_binding_json,participant_binding_json,
                   capability_epoch,state,created_at_ms,updated_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    "session:reviewer",
                    manifest_id,
                    manifest_hash,
                    f"prompt:{dispatch_id}",
                    "d" * 64,
                    "compiled:test",
                    "1",
                    "e" * 64,
                    "{}",
                    "{}",
                    1,
                    created_at_ms - 2,
                    created_at_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_invocation_receipts(
                   receipt_id,manifest_id,manifest_hash,load_receipt_id,
                   invocation_key,canonical_tool_name,original_tool_name,
                   command_hash,command_json,authorization_state,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'authorized', ?)""",
                (
                    invocation_id,
                    manifest_id,
                    manifest_hash,
                    f"load:{dispatch_id}:evidence",
                    f"call:{dispatch_id}:evidence",
                    "room_state",
                    "room_state",
                    "f" * 64,
                    "{}",
                    created_at_ms - 1,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_execution_receipts(
                   execution_receipt_id,invocation_receipt_id,kernel_receipt_id,
                   session_id,tool_name,status,result_hash,payload_json,created_at_ms
                   ) VALUES (?, ?, NULL, ?, 'room_state', 'applied', ?, ?, ?)""",
                (
                    evidence_ref,
                    invocation_id,
                    "session:reviewer",
                    "a" * 64,
                    "{}",
                    created_at_ms,
                ),
            )

    @staticmethod
    def _commit(
        dispatch_id: str,
        findings: list[dict[str, object]],
        *,
        action: str = "complete",
        evidence_refs: list[str] | None = None,
    ) -> dict[str, object]:
        committed_evidence = evidence_refs or ["test:review-lineage"]
        binding_material = {
            "reviewTargetRevision": _TARGET_REVISION,
            "taskId": "task:review",
            "dispatchId": dispatch_id,
            "evidenceRefs": sorted(committed_evidence),
            "notBeforeMs": 2,
        }
        binding_id = "review-evidence-binding:" + hashlib.sha256(
            json.dumps(
                binding_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": f"commit:{dispatch_id}",
            "dispatchId": dispatch_id,
            "action": action,
            "contentHash": "sha256:test-review-lineage",
            "postProposal": None,
            "qualityGateReceipt": {
                "schemaVersion": "wisdom-weasel.room-quality-gate-receipt.v1",
                "receiptId": f"quality:{dispatch_id}",
                "rootId": "root:1",
                "taskId": "task:review",
                "dispatchId": dispatch_id,
                "generation": 0,
                "originalRequestChecked": True,
                "verdict": (
                    "ready_to_deliver" if action == "complete" else "not_ready"
                ),
                "items": [
                    {
                        "criterionId": "ac:1",
                        "status": "pass" if action == "complete" else "fail",
                        "evidenceRefs": committed_evidence,
                    }
                ],
                "residualRisks": [],
                "createdAtMs": 5,
            },
            "evidenceRefs": committed_evidence,
            "requirementCoverage": ["ac:1"] if action == "complete" else [],
            "reviewFindings": findings,
            "reviewEvidenceBinding": {
                "schemaVersion": "wisdom-weasel.review-evidence-binding.v1",
                "bindingId": binding_id,
                **binding_material,
            },
            "createdAtMs": 5,
        }

    def test_new_finding_rejects_forged_canonical_fingerprint(self) -> None:
        self._start_review(None, dispatch_id="dispatch:forged-fingerprint")
        forged = {
            **_finding(),
            "fingerprint": f"sha256:{'e' * 64}",
        }

        with self.assertRaisesRegex(RoomKernelFenceError, "fingerprint"):
            self.store.apply_commit(
                self._commit(
                    "dispatch:forged-fingerprint",
                    [forged],
                    action="block",
                ),
                generation=0,
                now_ms=6,
            )

        self.assertEqual(
            self.store.dispatch("dispatch:forged-fingerprint")["state"],
            "running",
        )

    def test_new_finding_rejects_fabricated_self_consistent_evidence(self) -> None:
        self._start_review(None, dispatch_id="dispatch:foreign-evidence")
        foreign_ref = "execution:foreign"
        forged = {
            **_finding(),
            "evidenceRefs": [foreign_ref],
        }

        with self.assertRaisesRegex(RoomKernelFenceError, "stale or foreign evidence"):
            self.store.apply_commit(
                self._commit(
                    "dispatch:foreign-evidence",
                    [forged],
                    action="block",
                    evidence_refs=[foreign_ref],
                ),
                generation=0,
                now_ms=6,
            )

        self.assertEqual(
            self.store.dispatch("dispatch:foreign-evidence")["state"],
            "running",
        )

    def test_new_finding_accepts_current_runtime_evidence(self) -> None:
        self._start_review(None, dispatch_id="dispatch:current-evidence")

        applied = self.store.apply_commit(
            self._commit(
                "dispatch:current-evidence",
                [_finding()],
                action="block",
            ),
            generation=0,
            now_ms=6,
        )

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(
            self.store.task("task:review")["reviewFindings"][0]["findingId"],
            "finding:F1",
        )

    def test_existing_review_commit_replay_skips_new_runtime_authority_check(
        self,
    ) -> None:
        self._start_review(None, dispatch_id="dispatch:review-replay")
        commit = self._commit(
            "dispatch:review-replay",
            [_finding()],
            action="block",
        )
        applied = self.store.apply_commit(commit, generation=0, now_ms=6)
        self.assertEqual(applied["status"], "applied")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_v2_capability_runtime_bindings "
                "SET state='revoked',updated_at_ms=7 "
                "WHERE session_id='session:reviewer'"
            )

        replay = self.store.apply_commit(commit, generation=0, now_ms=7)

        self.assertEqual(replay["status"], "noop")
        self.assertEqual(replay["details"]["commitId"], commit["commitId"])

    def test_re_review_cannot_omit_prior_open_blocker(self) -> None:
        prior = _finding()
        self._start_review(prior, dispatch_id="dispatch:omit")

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "prior unresolved Blocking Finding",
        ):
            self.store.apply_commit(
                self._commit("dispatch:omit", []),
                generation=0,
                now_ms=5,
            )

        review_task = self.store.task("task:review")
        self.assertEqual(review_task["reviewFindings"], [prior])
        self.assertEqual(self.store.dispatch("dispatch:omit")["state"], "running")

    def test_re_review_cannot_rebind_prior_blocker_scope_or_fingerprint(self) -> None:
        fixed_response = {
            "findingId": "finding:F1",
            "action": "fixed",
            "rationale": "The stale-value path was replaced and retested.",
            "evidenceRefs": ["test:review-lineage"],
            "participantId": "participant:a",
            "createdAtMs": 3,
        }
        prior = _finding(response=fixed_response)
        self._start_review(prior, dispatch_id="dispatch:scope-rebind")
        rebound = _finding(
            scope={"invariantId": "room-governance:runtime-authority"},
            state="resolved",
            response=fixed_response,
        )

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "findingId and fingerprint",
        ):
            self.store.apply_commit(
                self._commit("dispatch:scope-rebind", [rebound]),
                generation=0,
                now_ms=5,
            )

    def test_exact_fixed_response_allows_prior_blocker_to_resolve(self) -> None:
        fixed_response = {
            "findingId": "finding:F1",
            "action": "fixed",
            "rationale": "The stale-value path was replaced and retested.",
            "evidenceRefs": ["test:review-lineage"],
            "participantId": "participant:a",
            "createdAtMs": 3,
        }
        prior = _finding(response=fixed_response)
        self._start_review(prior, dispatch_id="dispatch:fixed")
        resolved = {
            **prior,
            "state": "resolved",
            "lastCheckedRevision": _TARGET_REVISION,
        }

        applied = self.store.apply_commit(
            self._commit("dispatch:fixed", [resolved]),
            generation=0,
            now_ms=5,
        )

        self.assertEqual(applied["status"], "applied")
        final_task = self.store.task("task:review")
        self.assertEqual(final_task["reviewState"], "accepted")
        self.assertEqual(final_task["reviewFindings"][0]["state"], "resolved")
        self.assertEqual(
            final_task["reviewFindings"][0]["firstSeenRevision"],
            _FIRST_REVISION,
        )

    def test_exact_independent_arbiter_receipt_allows_dismissal(self) -> None:
        prior = _finding()
        self._start_review(prior, dispatch_id="dispatch:arbiter")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO room_v2_peer_judgment_rounds VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "round:arbiter",
                    "room:1",
                    "root:1",
                    "catalog:test",
                    _TARGET_REVISION,
                    "c" * 64,
                    "d" * 64,
                    "{}",
                    "[]",
                    2,
                    3,
                ),
            )
            conn.execute(
                "INSERT INTO room_v2_conflict_matrix_revisions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "matrix:resolved",
                    "round:arbiter",
                    2,
                    None,
                    "resolved",
                    json.dumps(
                        {"entries": [{"findingCodes": ["finding:F1"]}]}
                    ),
                    "e" * 64,
                    4,
                ),
            )
            conn.execute(
                "INSERT INTO room_v2_conflict_resolution_receipts VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "resolution:arbiter",
                    "round:arbiter",
                    "matrix:resolved",
                    "independent_arbiter",
                    "participant:arbiter",
                    "pass",
                    "The independent evidence supersedes the blocker.",
                    "f" * 64,
                    4,
                ),
            )
        dismissed = {
            **prior,
            "state": "dismissed",
            "dispositionRationale": "Resolved by an independent arbiter.",
            "lastCheckedRevision": _TARGET_REVISION,
        }

        applied = self.store.apply_commit(
            self._commit("dispatch:arbiter", [dismissed]),
            generation=0,
            now_ms=5,
        )

        self.assertEqual(applied["status"], "applied")
        final_task = self.store.task("task:review")
        self.assertEqual(final_task["reviewState"], "accepted")
        self.assertEqual(final_task["reviewFindings"][0]["state"], "dismissed")

    def test_failed_rechecks_are_kernel_derived_and_escalate_at_two(self) -> None:
        prior = _finding(failed_rechecks=1)
        self._start_review(prior, dispatch_id="dispatch:escalate")
        attacker_reset = {
            **prior,
            "failedRechecks": 0,
            "lastCheckedRevision": _TARGET_REVISION,
        }

        applied = self.store.apply_commit(
            self._commit(
                "dispatch:escalate",
                [attacker_reset],
                action="block",
            ),
            generation=0,
            now_ms=5,
        )

        self.assertEqual(applied["status"], "applied")
        finding = self.store.task("task:review")["reviewFindings"][0]
        self.assertEqual(finding["failedRechecks"], 2)
        self.assertEqual(finding["state"], "escalated")


if __name__ == "__main__":
    unittest.main()
