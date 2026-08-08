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
from rag_ime.agent_room_workspace_ledger import RoomWorkspaceLedgerStore
from rag_ime.db import latest_migration_version


_TARGET_REVISION = f"sha256:{'b' * 64}"


def _root() -> dict[str, object]:
    return {
        "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
        "rootId": "root:freshness",
        "roomId": "room:freshness",
        "generation": 0,
        "state": "running",
        "facilitatorParticipantId": "participant:facilitator",
        "reporterParticipantId": None,
        "reporterSelectionReceiptId": None,
        "requirementAnchorRef": "requirement-anchor:freshness@sha256:test",
        "createdByActorRef": "user:local",
        "terminalReceiptId": None,
        "activeProfileRef": None,
        "budgetPolicyRef": "room-budget:test-v1",
        "independentReviewRequired": True,
        "createdAtMs": 1,
    }


def _task(
    task_id: str,
    *,
    owner: str,
    criteria: tuple[str, ...] = ("ac:1",),
    parent_task_id: str | None = None,
    task_kind: str = "work",
    state: str = "active",
    review_state: str = "not_required",
    review_of: tuple[str, ...] = (),
    authors: tuple[str, ...] = (),
    findings: list[dict[str, object]] | None = None,
    revision: int = 0,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
        "taskId": task_id,
        "rootId": "root:freshness",
        "parentTaskId": parent_task_id,
        "taskKind": task_kind,
        "currentOwnerParticipantId": owner,
        "ownershipRevision": 0,
        "ownershipReceiptId": None,
        "invitationId": None,
        "reviewState": review_state,
        "reviewOfTaskIds": list(review_of),
        "reviewAuthorParticipantIds": list(authors),
        "contextEvidenceRefs": [],
        "objective": f"Complete {task_id}",
        "expectedOutput": f"Verified output for {task_id}",
        "requirementItemIds": ["requirement:1"],
        "acceptanceCriterionIds": list(criteria),
        "revision": revision,
        "state": state,
    }
    if task_kind == "review":
        payload.update(
            {
                "reviewRound": max(1, revision),
                "reviewTargetRevision": _TARGET_REVISION,
                "reviewEvidenceNotBeforeMs": 2,
                "reviewFindings": findings or [],
            }
        )
    return payload


def _dispatch(
    dispatch_id: str,
    *,
    task_id: str,
    owner: str,
    intent: str,
    attempt: int = 1,
    created_at_ms: int = 2,
) -> tuple[dict[str, object], int]:
    return (
        {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": dispatch_id,
            "rootId": "root:freshness",
            "taskId": task_id,
            "parentDispatchId": None,
            "generation": 0,
            "hopCount": 0,
            "depth": 0,
            "budgetCost": 1,
            "targetSessionId": f"session:{owner}",
            "targetParticipantId": owner,
            "triggerId": f"trigger:{dispatch_id}",
            "intentKind": intent,
            "idempotencyKey": f"key:{dispatch_id}",
            "attempt": attempt,
            "capabilityEpoch": attempt,
            "runtimeProfileRevision": "runtime-profile:test-v1",
            "state": "pending",
        },
        created_at_ms,
    )


def _commit(
    dispatch_id: str,
    *,
    task_id: str,
    evidence_by_criterion: dict[str, str],
    review_findings: list[dict[str, object]] | None = None,
    action: str = "complete",
) -> dict[str, object]:
    evidence_refs = list(evidence_by_criterion.values())
    commit = {
        "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
        "commitId": f"commit:{dispatch_id}",
        "dispatchId": dispatch_id,
        "action": action,
        "contentHash": f"sha256:{hashlib.sha256(dispatch_id.encode()).hexdigest()}",
        "postProposal": None,
        "qualityGateReceipt": {
            "schemaVersion": "wisdom-weasel.room-quality-gate-receipt.v1",
            "receiptId": f"quality:{dispatch_id}",
            "rootId": "root:freshness",
            "taskId": task_id,
            "dispatchId": dispatch_id,
            "generation": 0,
            "originalRequestChecked": True,
            "verdict": "ready_to_deliver",
            "items": [
                {
                    "criterionId": criterion_id,
                    "status": "pass",
                    "evidenceRefs": [evidence_ref],
                }
                for criterion_id, evidence_ref in evidence_by_criterion.items()
            ],
            "residualRisks": [],
            "createdAtMs": 10,
        },
        "evidenceRefs": evidence_refs,
        "requirementCoverage": list(evidence_by_criterion),
        **(
            {"reviewFindings": review_findings}
            if review_findings is not None
            else {}
        ),
        "createdAtMs": 10,
    }
    if review_findings is not None:
        binding_material = {
            "reviewTargetRevision": _TARGET_REVISION,
            "taskId": task_id,
            "dispatchId": dispatch_id,
            "evidenceRefs": sorted(evidence_refs),
            "notBeforeMs": 2,
        }
        commit["reviewEvidenceBinding"] = {
            "schemaVersion": "wisdom-weasel.review-evidence-binding.v1",
            "bindingId": (
                "review-evidence-binding:"
                + hashlib.sha256(
                    json.dumps(
                        binding_material,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            ),
            **binding_material,
        }
    return commit


def _finding(
    *,
    gate_effect: str = "blocking",
    state: str = "open",
    observation: str = "The implementation returns stale data.",
) -> dict[str, object]:
    scope = {"criterionId": "ac:1"}
    fingerprint_material = {
        "category": "correctness",
        "scope": scope,
        "observation": "The implementation returns stale data.",
        "expected": "The implementation returns current data.",
        "userImpact": "The user sees the wrong result.",
    }
    fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(
            fingerprint_material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "findingId": "finding:shared",
        "fingerprint": fingerprint,
        "gateEffect": gate_effect,
        "impact": "high" if gate_effect == "blocking" else "normal",
        "category": "correctness",
        "scope": scope,
        "observation": observation,
        "expected": "The implementation returns current data.",
        "userImpact": "The user sees the wrong result.",
        "evidenceRefs": ["evidence:review"],
        "reproduction": ["Run the failing command."],
        "state": state,
        "dispositionRationale": (
            "The newer review treated this as non-blocking."
            if state in {"dismissed", "accepted_risk"}
            else None
        ),
        "ownerParticipantId": "participant:facilitator",
        "firstSeenRevision": _TARGET_REVISION,
        "lastCheckedRevision": _TARGET_REVISION,
        "failedRechecks": 0,
        "response": None,
    }


class RoomAcceptanceEvidenceFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-evidence-freshness-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), latest_migration_version())
        self.store.create_root_with_task(
            _root(),
            _task(
                "task:work",
                owner="participant:facilitator",
                criteria=("ac:1", "ac:2"),
            ),
            budget=16,
            max_hops=8,
            max_depth=4,
            acceptance_criteria=("ac:1", "ac:2"),
            now_ms=1,
        )
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:freshness",
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=0,
                details={
                    "operation": "room_define",
                    "dispatchId": "dispatch:definition",
                    "taskId": "task:work",
                    "catalogRevisionId": "catalog:freshness-v1",
                },
                now_ms=1,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _start(self, payload: dict[str, object], now_ms: int) -> None:
        self.store.enqueue_dispatch(payload, now_ms=now_ms)
        self.store.set_dispatch_wait_state(
            str(payload["dispatchId"]),
            "running",
            now_ms=now_ms + 1,
        )

    def _commit_baseline(self) -> dict[str, object]:
        dispatch, now_ms = _dispatch(
            "dispatch:authority-baseline",
            task_id="task:work",
            owner="participant:facilitator",
            intent="execute",
        )
        self._start(dispatch, now_ms)
        return self.store.apply_commit(
            _commit(
                "dispatch:authority-baseline",
                task_id="task:work",
                evidence_by_criterion={
                    "ac:1": "evidence:authority-one",
                    "ac:2": "evidence:authority-two",
                },
            ),
            generation=0,
            now_ms=10,
        )

    def _project_isolated_delivery(
        self,
        *,
        binding_id: str = "workspace-binding:freshness",
    ) -> None:
        payload = self.store.task("task:work")
        payload.update(
            {
                "workItemId": "work:freshness",
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/freshness-child",
                "workspaceBaseRoot": "/tmp/freshness-base",
                "workspaceBaseCommit": "git:base",
                "workspaceSnapshotSha256": "a" * 64,
                "workspaceBindingId": binding_id,
                "workspaceRepositoryId": "b" * 64,
                "workspaceLifecycleState": "delivered",
                "workspaceCleanupState": "not_authorized",
                "workspaceAttentionRequired": False,
                "workspaceDeliveryRevision": "sha256:" + "c" * 64,
                "workspaceDeliveryHead": "git:base",
                "workspaceDeliverySnapshotSha256": "d" * 64,
                "workspaceDelivery": {
                    "schemaVersion": (
                        "wisdom-weasel.room-workspace-delivery.v1"
                    ),
                    "ownerParticipantId": "participant:facilitator",
                    "ownerSessionId": "session:participant:facilitator",
                    "workItemId": "work:freshness",
                    "taskId": "task:work",
                    "deliveryRevision": "sha256:" + "c" * 64,
                    "baseCommit": "git:base",
                    "workspaceSnapshotSha256": "d" * 64,
                    "patchSha256": "e" * 64,
                    "deliveredAtMs": 2,
                    "resultSummary": "Fresh isolated delivery.",
                    "manifestSha256": "f" * 64,
                    "files": [],
                    "totals": {
                        "fileCount": 0,
                        "additions": 0,
                        "deletions": 0,
                        "binaryFiles": 0,
                        "generatedFiles": 0,
                        "redactedFiles": 0,
                    },
                    "artifactRefs": [],
                    "verificationCount": 1,
                    "verifications": [
                        {
                            "label": "Fresh isolated delivery",
                            "result": "pass",
                            "source": "quality_gate",
                        }
                    ],
                    "verificationRefs": ["test:fresh-isolated"],
                    "residualRisks": [],
                },
                "workspaceIntegrationState": "pending",
                "workspaceIntegrationRef": None,
            }
        )
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:work",
                ),
            )

    def _record_canonical_workspace_integration(
        self,
        *,
        cleanup_state: str = "cleaned",
        attention_required: bool | None = None,
        apply: bool = True,
    ) -> dict[str, object]:
        ledger = RoomWorkspaceLedgerStore(self.db_path)
        binding, _ = ledger.reserve_binding(
            room_id="room:freshness",
            root_id="root:freshness",
            task_id="task:work",
            work_item_id="work:freshness",
            dispatch_id="dispatch:authority-baseline",
            requirement_revision="requirement:freshness",
            acceptance_aliases=["ac:1", "ac:2"],
            participant_id="participant:facilitator",
            session_id="session:participant:facilitator",
            repository_id="b" * 64,
            base_root="/tmp/freshness-base",
            base_commit="git:base",
            workspace_root="/tmp/freshness-child",
            workspace_policy="isolated_writable",
            creation_reason="fresh integration authority test",
            now_ms=2,
        )
        binding_id = str(binding["workspaceBindingId"])
        self._project_isolated_delivery(binding_id=binding_id)
        self._commit_baseline()
        ledger.mark_materialized(
            binding_id,
            workspace_snapshot_sha256="a" * 64,
            actor_ref="participant:facilitator",
            now_ms=3,
        )
        ledger.record_work_started(
            binding_id,
            dispatch_id="dispatch:authority-baseline",
            actor_ref="participant:facilitator",
            now_ms=4,
        )
        ledger.record_delivery(
            binding_id,
            delivery_revision="sha256:" + "c" * 64,
            delivery_head="git:base",
            workspace_snapshot_sha256="d" * 64,
            patch_sha256="e" * 64,
            manifest_sha256="f" * 64,
            artifacts=[],
            verification_refs=["test:fresh-isolated"],
            residual_risks=[],
            actor_ref="participant:facilitator",
            now_ms=5,
        )
        ledger.record_source_lease_revoked(
            binding_id,
            delivery_revision="sha256:" + "c" * 64,
            workspace_snapshot_sha256="d" * 64,
            patch_sha256="e" * 64,
            patch_artifact_path="/tmp/freshness-sealed.patch",
            patch_artifact_size=1,
            owner_session_id="session:participant:facilitator",
            revoked_policy_sha256="7" * 64,
            workspace_content_sha256="8" * 64,
            changed_files=[],
            actor_ref="system:test",
            now_ms=6,
        )
        ledger.begin_integration(
            binding_id,
            integration_ref="integration:canonical",
            patch_sha256="e" * 64,
            target_before_snapshot_sha256="6" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        ledger.record_target_applied(
            binding_id,
            integration_ref="integration:canonical",
            patch_sha256="e" * 64,
            target_before_snapshot_sha256="6" * 64,
            target_after_snapshot_sha256="2" * 64,
            target_snapshot_provider=lambda: "2" * 64,
            actor_ref="participant:facilitator",
            now_ms=8,
        )
        ledger.record_integrated(
            binding_id,
            integration_ref="integration:canonical",
            patch_sha256="e" * 64,
            integrated_revision="git:integrated",
            integrated_snapshot_sha256="2" * 64,
            changed_files=[],
            target_snapshot_provider=lambda: "2" * 64,
            actor_ref="participant:facilitator",
            now_ms=9,
        )
        source = ledger.source_lease_receipt(binding_id)
        integrated = ledger.integrated_receipt(binding_id)
        assert source is not None and integrated is not None
        ledger.record_writer_quiescence(
            binding_id,
            receipt={
                "schemaVersion": (
                    "wisdom-weasel.room-workspace-writer-quiescence.v1"
                ),
                "receiptRevision": "test:fresh-writer-quiescence",
                "workspaceBindingId": binding_id,
                "rootId": "root:freshness",
                "taskId": "task:work",
                "dispatchId": "dispatch:authority-baseline",
                "deliveryRevision": "sha256:" + "c" * 64,
                "ownerSessionId": "session:participant:facilitator",
                "sourceLeaseReceiptId": source["eventId"],
                "sourceLeaseReceiptSha256": source["payloadSha256"],
                "integratedReceiptId": integrated["eventId"],
                "integratedReceiptSha256": integrated["payloadSha256"],
                "foregroundMutatingInvocations": {
                    "known": True,
                    "activeCount": 0,
                },
                "backgroundWork": {"known": True, "activeCount": 0},
                "managedPiTurn": {
                    "known": True,
                    "settled": True,
                    "sessionId": "session:participant:facilitator",
                    "dispatchId": "dispatch:authority-baseline",
                },
            },
            actor_ref="participant:facilitator",
            now_ms=10,
        )
        ledger.record_quarantined(
            binding_id,
            quarantined_workspace_root="/tmp/freshness-quarantine",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="2" * 64,
            actor_ref="participant:facilitator",
            now_ms=11,
        )
        ledger.authorize_cleanup_removal(
            binding_id,
            quarantined_workspace_root="/tmp/freshness-quarantine",
            vault_workspace_root="/tmp/freshness-vault",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="2" * 64,
            actor_ref="participant:facilitator",
            now_ms=12,
        )
        removal = ledger.cleanup_removal_authorization_receipt(binding_id)
        assert removal is not None
        if cleanup_state == "cleaned":
            ledger.record_vaulted(
                binding_id,
                removal_authorization_receipt_id=str(removal["eventId"]),
                removal_authorization_receipt_sha256=str(
                    removal["payloadSha256"]
                ),
                quarantined_workspace_root="/tmp/freshness-quarantine",
                vault_workspace_root="/tmp/freshness-vault",
                authorized_workspace_content_sha256="8" * 64,
                vault_content_sha256="9" * 64,
                target_snapshot_sha256="2" * 64,
                actor_ref="system:test",
                now_ms=13,
            )
            ledger.record_cleanup(
                binding_id,
                result="cleaned",
                reason="fresh integration complete",
                actor_ref="participant:facilitator",
                now_ms=14,
                retained_workspace_root="/tmp/freshness-vault",
            )
        elif cleanup_state == "failed":
            ledger.record_cleanup(
                binding_id,
                result="failed",
                reason="fresh integration cleanup failed",
                actor_ref="participant:facilitator",
                now_ms=14,
                retained_workspace_root="/tmp/freshness-quarantine",
            )
        else:
            self.fail(f"unsupported test cleanup state: {cleanup_state}")
        delivery_receipt = next(
            event
            for event in ledger.events(binding_id)
            if event["eventKind"] == "delivered"
        )
        receipt_names = {
            "Delivery": delivery_receipt,
            "SourceLease": ledger.source_lease_receipt(binding_id),
            "TargetApplied": ledger.target_applied_receipt(binding_id),
            "Integrated": ledger.integrated_receipt(binding_id),
            "WriterQuiescence": ledger.writer_quiescence_receipt(binding_id),
            "Quarantine": ledger.quarantine_receipt(binding_id),
            "RemovalAuthorization": (
                ledger.cleanup_removal_authorization_receipt(binding_id)
            ),
            "Vault": ledger.vault_receipt(binding_id),
            "Cleanup": ledger.cleanup_receipt(binding_id),
        }
        result: dict[str, object] = {
            "integrated": True,
            "workspaceBindingId": binding_id,
            "integrationRef": "integration:canonical",
            "integrationPatchSha256": "e" * 64,
            "integratedRevision": "git:integrated",
            "integratedSnapshotSha256": "2" * 64,
            "workspaceLifecycleState": (
                "cleaned" if cleanup_state == "cleaned" else "cleanup_failed"
            ),
            "cleanupState": cleanup_state,
            "attentionRequired": (
                cleanup_state != "cleaned"
                if attention_required is None
                else attention_required
            ),
        }
        for name, receipt in receipt_names.items():
            if receipt is None:
                continue
            result[f"workspace{name}ReceiptId"] = receipt["eventId"]
            result[f"workspace{name}ReceiptSha256"] = receipt[
                "payloadSha256"
            ]
        if apply:
            self.store.record_workspace_integration(
                "task:work",
                integration_ref="integration:canonical",
                workspace_result=result,
                now_ms=15,
            )
        return result

    def _replace_receipt_payload(
        self,
        receipt_id: str,
        payload: dict[str, object],
    ) -> None:
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_receipts SET payload_json=? "
                "WHERE receipt_id=?",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    receipt_id,
                ),
            )

    def _commit_masking_task(self) -> None:
        self.store.create_task(
            _task(
                "task:mask",
                owner="participant:facilitator",
                criteria=("ac:1", "ac:2"),
                parent_task_id="task:work",
            ),
            now_ms=20,
        )
        dispatch, now_ms = _dispatch(
            "dispatch:mask",
            task_id="task:mask",
            owner="participant:facilitator",
            intent="execute",
            created_at_ms=21,
        )
        self._start(dispatch, now_ms)
        self.store.apply_commit(
            _commit(
                "dispatch:mask",
                task_id="task:mask",
                evidence_by_criterion={
                    "ac:1": "evidence:mask-one",
                    "ac:2": "evidence:mask-two",
                },
            ),
            generation=0,
            now_ms=22,
        )

    def _assert_masked_workspace_authority_is_terminally_fenced(self) -> None:
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {
                "ac:1": ["evidence:mask-one"],
                "ac:2": ["evidence:mask-two"],
            },
        )
        readiness = self.store.report_readiness("root:freshness")
        self.assertEqual(readiness["unprovenAcceptanceCriteria"], [])
        self.assertIn(
            "task:work",
            {
                str(item["taskId"])
                for item in readiness["governance"]["pendingIntegrations"]
            },
        )
        terminal = self.store.finalize_root("root:freshness", now_ms=30)
        self.assertEqual(terminal["receiptKind"], "rejected")
        self.assertIn(
            "task:work",
            {
                str(item["taskId"])
                for item in terminal["details"]["governance"][
                    "pendingIntegrations"
                ]
            },
        )

    def _resolve_failed_workspace_cleanup(
        self,
        failed_result: dict[str, object],
    ) -> dict[str, object]:
        ledger = RoomWorkspaceLedgerStore(self.db_path)
        binding_id = str(failed_result["workspaceBindingId"])
        removal = ledger.cleanup_removal_authorization_receipt(binding_id)
        assert removal is not None
        ledger.record_vaulted(
            binding_id,
            removal_authorization_receipt_id=str(removal["eventId"]),
            removal_authorization_receipt_sha256=str(
                removal["payloadSha256"]
            ),
            quarantined_workspace_root="/tmp/freshness-quarantine",
            vault_workspace_root="/tmp/freshness-vault",
            authorized_workspace_content_sha256="8" * 64,
            vault_content_sha256="9" * 64,
            target_snapshot_sha256="2" * 64,
            actor_ref="system:test-recovery",
            now_ms=16,
        )
        ledger.record_cleanup(
            binding_id,
            result="cleaned",
            reason="fresh cleanup retry complete",
            actor_ref="participant:facilitator",
            now_ms=17,
            retained_workspace_root="/tmp/freshness-vault",
        )
        resolved = {
            **failed_result,
            "workspaceLifecycleState": "cleaned",
            "cleanupState": "cleaned",
            "attentionRequired": False,
        }
        receipt_names = {
            "Delivery": next(
                event
                for event in ledger.events(binding_id)
                if event["eventKind"] == "delivered"
            ),
            "SourceLease": ledger.source_lease_receipt(binding_id),
            "TargetApplied": ledger.target_applied_receipt(binding_id),
            "Integrated": ledger.integrated_receipt(binding_id),
            "WriterQuiescence": ledger.writer_quiescence_receipt(binding_id),
            "Quarantine": ledger.quarantine_receipt(binding_id),
            "RemovalAuthorization": (
                ledger.cleanup_removal_authorization_receipt(binding_id)
            ),
            "Vault": ledger.vault_receipt(binding_id),
            "Cleanup": ledger.cleanup_receipt(binding_id),
        }
        for name, receipt in receipt_names.items():
            assert receipt is not None
            resolved[f"workspace{name}ReceiptId"] = receipt["eventId"]
            resolved[f"workspace{name}ReceiptSha256"] = receipt[
                "payloadSha256"
            ]
        return resolved

    def test_missing_authority_payload_invalidates_commit_evidence(self) -> None:
        receipt = self._commit_baseline()
        tampered = json.loads(json.dumps(receipt))
        tampered["details"]["acceptanceEvidenceAuthority"] = {}
        self._replace_receipt_payload(str(receipt["receiptId"]), tampered)

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )
        self.assertEqual(
            self.store.report_readiness("root:freshness")[
                "unprovenAcceptanceCriteria"
            ],
            ["ac:1", "ac:2"],
        )

    def test_forged_mutable_integration_projection_cannot_prove_evidence(
        self,
    ) -> None:
        self._project_isolated_delivery()
        self._commit_baseline()
        forged = self.store.task("task:work")
        forged.update(
            {
                "revision": int(forged.get("revision") or 0) + 1,
                "workspaceIntegrationState": "applied",
                "workspaceIntegrationRef": "integration:forged",
                "workspaceIntegrationPatchSha256": "1" * 64,
                "workspaceIntegratedRevision": "git:forged",
                "workspaceIntegratedSnapshotSha256": "2" * 64,
                "workspaceLifecycleState": "cleaned",
                "workspaceCleanupState": "cleaned",
            }
        )
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? "
                "WHERE task_id=?",
                (
                    json.dumps(
                        forged,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    11,
                    "task:work",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )
        self.assertEqual(
            self.store.report_readiness("root:freshness")[
                "unprovenAcceptanceCriteria"
            ],
            ["ac:1", "ac:2"],
        )

    def test_canonical_integration_authority_proves_worker_evidence(
        self,
    ) -> None:
        self._record_canonical_workspace_integration()

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {
                "ac:1": ["evidence:authority-one"],
                "ac:2": ["evidence:authority-two"],
            },
        )
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM room_kernel_receipts "
                "WHERE root_id=? AND receipt_kind='accepted'",
                ("root:freshness",),
            ).fetchall()
        authorities = [
            json.loads(str(row["payload_json"]))["details"][
                "integrationAuthority"
            ]
            for row in rows
            if json.loads(str(row["payload_json"]))["details"].get(
                "operation"
            )
            == "room_integrate"
        ]
        self.assertEqual(len(authorities), 1)
        authority = authorities[0]
        self.assertEqual(
            authority["acceptanceAuthorityBindingId"],
            self._commit_receipt()["details"]["acceptanceEvidenceAuthority"][
                "bindingId"
            ],
        )
        self.assertEqual(
            authority["workspaceIntegrationPatchSha256"],
            "e" * 64,
        )
        self.assertIn(
            "workspaceVaultReceiptId",
            authority["workspaceReceiptRefs"],
        )

    def test_cleanup_failed_integration_authority_remains_a_terminal_fence(
        self,
    ) -> None:
        self._record_canonical_workspace_integration(
            cleanup_state="failed",
        )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )
        readiness = self.store.report_readiness("root:freshness")
        self.assertEqual(
            readiness["governance"]["pendingIntegrations"],
            [
                {
                    "taskId": "task:work",
                    "taskState": "completed",
                    "workspaceIntegrationState": "applied",
                    "hasIntegrationRef": True,
                }
            ],
        )
        self.assertFalse(readiness["ready"])

    def test_cleanup_failed_integration_resolves_once_with_same_ref(
        self,
    ) -> None:
        failed = self._record_canonical_workspace_integration(
            cleanup_state="failed",
        )
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )
        with self.store._connect() as conn:
            prior_rows = conn.execute(
                "SELECT payload_json FROM room_kernel_receipts "
                "WHERE root_id=?",
                ("root:freshness",),
            ).fetchall()
        prior = [json.loads(str(row["payload_json"])) for row in prior_rows]
        self.assertEqual(
            [
                receipt
                for receipt in prior
                if receipt["receiptKind"] == "accepted"
                and receipt["details"].get("operation") == "room_integrate"
            ],
            [],
        )
        self.assertEqual(
            len(
                [
                    receipt
                    for receipt in prior
                    if receipt["details"].get("operation")
                    == "room_integrate_pending_cleanup"
                ]
            ),
            1,
        )

        resolved = self._resolve_failed_workspace_cleanup(failed)
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "integrationRef",
        ):
            self.store.record_workspace_integration(
                "task:work",
                integration_ref="integration:different",
                workspace_result={
                    **resolved,
                    "integrationRef": "integration:different",
                },
                now_ms=18,
            )
        stale = {
            **resolved,
            "workspaceDeliveryReceiptId": resolved[
                "workspaceSourceLeaseReceiptId"
            ],
            "workspaceDeliveryReceiptSha256": resolved[
                "workspaceSourceLeaseReceiptSha256"
            ],
        }
        with self.assertRaises(RoomKernelFenceError):
            self.store.record_workspace_integration(
                "task:work",
                integration_ref="integration:canonical",
                workspace_result=stale,
                now_ms=18,
            )

        self.store.record_workspace_integration(
            "task:work",
            integration_ref="integration:canonical",
            workspace_result=resolved,
            now_ms=18,
        )
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {
                "ac:1": ["evidence:authority-one"],
                "ac:2": ["evidence:authority-two"],
            },
        )
        self.assertEqual(
            self.store.report_readiness("root:freshness")["governance"][
                "pendingIntegrations"
            ],
            [],
        )
        self.store.record_workspace_integration(
            "task:work",
            integration_ref="integration:canonical",
            workspace_result=resolved,
            now_ms=19,
        )
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM room_kernel_receipts "
                "WHERE root_id=? AND receipt_kind='accepted'",
                ("root:freshness",),
            ).fetchall()
        accepted_authorities = [
            json.loads(str(row["payload_json"]))
            for row in rows
            if json.loads(str(row["payload_json"]))["details"].get(
                "operation"
            )
            == "room_integrate"
        ]
        self.assertEqual(len(accepted_authorities), 1)

    def test_attention_tamper_keeps_canonical_integration_fenced(self) -> None:
        self._record_canonical_workspace_integration()
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:work",),
            ).fetchone()
            tampered = json.loads(str(row["payload_json"]))
            tampered["workspaceAttentionRequired"] = True
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        tampered,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:work",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )
        self.assertEqual(
            self.store.report_readiness("root:freshness")["governance"][
                "pendingIntegrations"
            ][0]["taskId"],
            "task:work",
        )

    def test_missing_delivered_receipt_authority_is_rejected(self) -> None:
        result = self._record_canonical_workspace_integration(apply=False)
        result.pop("workspaceDeliveryReceiptId")
        result.pop("workspaceDeliveryReceiptSha256")

        with self.assertRaisesRegex(
            (RoomKernelFenceError, ValueError),
            "workspaceDeliveryReceiptId|receipt chain",
        ):
            self.store.record_workspace_integration(
                "task:work",
                integration_ref="integration:canonical",
                workspace_result=result,
                now_ms=15,
            )

    def test_stale_delivered_receipt_authority_is_rejected(self) -> None:
        result = self._record_canonical_workspace_integration(apply=False)
        result["workspaceDeliveryReceiptId"] = result[
            "workspaceSourceLeaseReceiptId"
        ]
        result["workspaceDeliveryReceiptSha256"] = result[
            "workspaceSourceLeaseReceiptSha256"
        ]

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "delivery receipt kind or digest does not match",
        ):
            self.store.record_workspace_integration(
                "task:work",
                integration_ref="integration:canonical",
                workspace_result=result,
                now_ms=15,
            )

    def test_tampered_delivered_receipt_digest_fails_closed(self) -> None:
        result = self._record_canonical_workspace_integration()
        self._commit_masking_task()
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_workspace_events SET payload_sha256=? "
                "WHERE event_id=?",
                ("0" * 64, result["workspaceDeliveryReceiptId"]),
            )

        self._assert_masked_workspace_authority_is_terminally_fenced()

    def test_missing_delivered_receipt_is_terminally_fenced_per_task(
        self,
    ) -> None:
        result = self._record_canonical_workspace_integration()
        self._commit_masking_task()
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "DELETE FROM room_workspace_events WHERE event_id=?",
                (result["workspaceDeliveryReceiptId"],),
            )

        self._assert_masked_workspace_authority_is_terminally_fenced()

    def test_duplicate_delivered_receipt_authority_fails_closed(self) -> None:
        result = self._record_canonical_workspace_integration()
        self._commit_masking_task()
        with self.store._connect(immediate=True) as conn:
            original = conn.execute(
                "SELECT * FROM room_workspace_events WHERE event_id=?",
                (result["workspaceDeliveryReceiptId"],),
            ).fetchone()
            sequence = int(
                conn.execute(
                    "SELECT MAX(sequence) FROM room_workspace_events "
                    "WHERE binding_id=?",
                    (original["binding_id"],),
                ).fetchone()[0]
            ) + 1
            idempotency_key = "delivered:duplicate-authority"
            event_material = "\0".join(
                (
                    "room-workspace-event",
                    str(original["binding_id"]),
                    str(sequence),
                    "delivered",
                    idempotency_key,
                )
            ).encode("utf-8")
            event_id = "room-workspace-event:" + hashlib.sha256(
                event_material
            ).hexdigest()[:32]
            conn.execute(
                """INSERT INTO room_workspace_events(
                       event_id,binding_id,sequence,event_kind,idempotency_key,
                       actor_ref,payload_sha256,payload_json,created_at_ms
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    original["binding_id"],
                    sequence,
                    "delivered",
                    idempotency_key,
                    original["actor_ref"],
                    original["payload_sha256"],
                    original["payload_json"],
                    16,
                ),
            )
            conn.execute(
                "UPDATE room_workspace_bindings "
                "SET last_event_sequence=? WHERE binding_id=?",
                (sequence, original["binding_id"]),
            )

        self._assert_masked_workspace_authority_is_terminally_fenced()

    def test_duplicate_integration_authority_fails_closed(self) -> None:
        self._record_canonical_workspace_integration()
        integration_receipt = self._integration_receipt()
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:freshness",
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=0,
                details=dict(integration_receipt["details"]),
                now_ms=16,
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def test_stale_integration_task_projection_fails_closed(self) -> None:
        self._record_canonical_workspace_integration()
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:work",),
            ).fetchone()
            stale = json.loads(str(row["payload_json"]))
            stale["workspaceIntegrationRef"] = "integration:stale"
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        stale,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:work",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def test_tampered_or_none_integration_authority_fails_closed(self) -> None:
        self._record_canonical_workspace_integration()
        original = self._integration_receipt()
        for field, value in (
            ("workspaceIntegratedRevision", "git:tampered"),
            ("workspaceIntegrationRef", None),
        ):
            with self.subTest(field=field):
                tampered = json.loads(json.dumps(original))
                tampered["details"]["integrationAuthority"][field] = value
                self._replace_receipt_payload(
                    str(original["receiptId"]),
                    tampered,
                )
                self.assertEqual(
                    self.store.accepted_evidence_by_criterion(
                        "root:freshness"
                    ),
                    {},
                )
                self._replace_receipt_payload(
                    str(original["receiptId"]),
                    original,
                )

    def test_tampered_workspace_receipt_payload_fails_closed(self) -> None:
        result = self._record_canonical_workspace_integration()
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_workspace_events "
                "WHERE event_id=?",
                (result["workspaceIntegratedReceiptId"],),
            ).fetchone()
            tampered = json.loads(str(row["payload_json"]))
            tampered["changedFiles"] = ["forged.py"]
            conn.execute(
                "UPDATE room_workspace_events SET payload_json=? "
                "WHERE event_id=?",
                (
                    json.dumps(
                        tampered,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    result["workspaceIntegratedReceiptId"],
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def _commit_receipt(self) -> dict[str, object]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM room_kernel_receipts "
                "WHERE root_id=? AND receipt_kind='accepted'",
                ("root:freshness",),
            ).fetchall()
        for row in rows:
            receipt = json.loads(str(row["payload_json"]))
            if receipt["details"].get("commitId") == (
                "commit:dispatch:authority-baseline"
            ):
                return receipt
        self.fail("canonical Commit receipt is missing")

    def _integration_receipt(self) -> dict[str, object]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM room_kernel_receipts "
                "WHERE root_id=? AND receipt_kind='accepted'",
                ("root:freshness",),
            ).fetchall()
        for row in rows:
            receipt = json.loads(str(row["payload_json"]))
            if receipt["details"].get("operation") == "room_integrate":
                return receipt
        self.fail("canonical integration receipt is missing")

    def test_commit_payload_tamper_invalidates_bound_evidence(self) -> None:
        self._commit_baseline()
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_commits "
                "WHERE commit_id=?",
                ("commit:dispatch:authority-baseline",),
            ).fetchone()
            tampered = json.loads(str(row["payload_json"]))
            tampered["qualityGateReceipt"]["items"][0]["evidenceRefs"] = [
                "evidence:forged"
            ]
            tampered["evidenceRefs"][0] = "evidence:forged"
            conn.execute(
                "UPDATE room_kernel_commits SET payload_json=? "
                "WHERE commit_id=?",
                (
                    json.dumps(
                        tampered,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "commit:dispatch:authority-baseline",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def test_every_authority_field_is_consumed_fail_closed(self) -> None:
        receipt = self._commit_baseline()
        original = json.loads(json.dumps(receipt))
        authority = original["details"]["acceptanceEvidenceAuthority"]
        mutations: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.acceptance-evidence-authority.bad",
            "rootId": "root:wrong",
            "taskId": "task:wrong",
            "taskRevision": int(authority["taskRevision"]) + 1,
            "dispatchId": "dispatch:wrong",
            "dispatchAttempt": int(authority["dispatchAttempt"]) + 1,
            "generation": int(authority["generation"]) + 1,
            "requirementCatalogRevisionId": "catalog:wrong",
            "requirementAnchorRef": "requirement-anchor:wrong",
            "workspacePolicy": "isolated_writable",
            "workspaceBindingId": "workspace-binding:wrong",
            "workspaceDeliveryRevision": "sha256:wrong-delivery",
            "workspaceDeliveryHead": "git:wrong",
            "workspaceDeliverySnapshotSha256": "wrong-delivery-snapshot",
            "workspaceIntegratedRevision": "git:wrong-integrated",
            "workspaceIntegratedSnapshotSha256": "wrong-integrated-snapshot",
            "workspaceIntegrationPatchSha256": "wrong-patch",
            "workspaceIntegrationRef": "integration:wrong",
            "workspaceSnapshotSha256": "wrong-base-snapshot",
            "qualityGateReceiptId": "quality:wrong",
            "taskAcceptanceCriterionIds": ["ac:wrong"],
            "criteria": [],
            "evidenceRefs": ["evidence:wrong"],
            "requirementCoverage": ["ac:wrong"],
            "workspaceDeliveryManifestSha256": "wrong-manifest",
            "workspaceDeliveryPatchSha256": "wrong-delivery-patch",
            "commitId": "commit:wrong",
            "commitDeclaredContentHash": "sha256:wrong-declared",
            "commitCanonicalContentHash": "sha256:wrong-canonical",
            "bindingId": "acceptance-evidence-authority:wrong",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                tampered = json.loads(json.dumps(original))
                tampered["details"]["acceptanceEvidenceAuthority"][field] = value
                self._replace_receipt_payload(
                    str(receipt["receiptId"]),
                    tampered,
                )
                self.assertEqual(
                    self.store.accepted_evidence_by_criterion(
                        "root:freshness"
                    ),
                    {},
                )
                self._replace_receipt_payload(
                    str(receipt["receiptId"]),
                    original,
                )

    def test_commit_content_hash_tamper_invalidates_bound_evidence(self) -> None:
        self._commit_baseline()
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_commits "
                "WHERE commit_id=?",
                ("commit:dispatch:authority-baseline",),
            ).fetchone()
            tampered = json.loads(str(row["payload_json"]))
            tampered["contentHash"] = "sha256:forged-content"
            conn.execute(
                "UPDATE room_kernel_commits SET payload_json=? "
                "WHERE commit_id=?",
                (
                    json.dumps(
                        tampered,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "commit:dispatch:authority-baseline",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def test_duplicate_authority_receipt_invalidates_commit_evidence(self) -> None:
        receipt = self._commit_baseline()
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:freshness",
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=0,
                details=dict(receipt["details"]),
                now_ms=11,
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {},
        )

    def test_canonical_authority_preserves_legal_nonoverlapping_evidence(
        self,
    ) -> None:
        self._commit_baseline()
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {
                "ac:1": ["evidence:authority-one"],
                "ac:2": ["evidence:authority-two"],
            },
        )

    def test_revise_child_immediately_invalidates_only_overlapping_old_evidence(
        self,
    ) -> None:
        original, now_ms = _dispatch(
            "dispatch:original",
            task_id="task:work",
            owner="participant:facilitator",
            intent="execute",
        )
        self._start(original, now_ms)
        original_receipt = self.store.apply_commit(
            _commit(
                "dispatch:original",
                task_id="task:work",
                evidence_by_criterion={
                    "ac:1": "evidence:old-overlap",
                    "ac:2": "evidence:independent",
                },
            ),
            generation=0,
            now_ms=10,
        )
        original_authority = original_receipt["details"][
            "acceptanceEvidenceAuthority"
        ]
        self.assertEqual(original_authority["taskId"], "task:work")
        self.assertEqual(original_authority["taskRevision"], 0)
        self.assertEqual(original_authority["dispatchAttempt"], 1)
        self.assertEqual(
            original_authority["requirementCatalogRevisionId"],
            "catalog:freshness-v1",
        )
        self.assertTrue(
            str(original_authority["bindingId"]).startswith(
                "acceptance-evidence-authority:"
            )
        )

        self.store.create_task(
            _task(
                "task:revision",
                owner="participant:facilitator",
                criteria=("ac:1",),
                parent_task_id="task:work",
                revision=1,
            ),
            now_ms=11,
        )
        revision, revision_ms = _dispatch(
            "dispatch:revision",
            task_id="task:revision",
            owner="participant:facilitator",
            intent="revise",
            created_at_ms=12,
        )
        self.store.enqueue_dispatch(revision, now_ms=revision_ms)

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {"ac:2": ["evidence:independent"]},
        )
        self.assertIn(
            "ac:1",
            self.store.report_readiness("root:freshness")[
                "unprovenAcceptanceCriteria"
            ],
        )

        self.store.set_dispatch_wait_state(
            "dispatch:revision",
            "running",
            now_ms=13,
        )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "current attempt",
        ):
            self.store.apply_commit(
                _commit(
                    "dispatch:revision",
                    task_id="task:revision",
                    evidence_by_criterion={"ac:1": "evidence:old-overlap"},
                ),
                generation=0,
                now_ms=19,
            )
        revision_receipt = self.store.apply_commit(
            _commit(
                "dispatch:revision",
                task_id="task:revision",
                evidence_by_criterion={"ac:1": "evidence:new-revision"},
            ),
            generation=0,
            now_ms=20,
        )
        revision_authority = revision_receipt["details"][
            "acceptanceEvidenceAuthority"
        ]
        self.assertEqual(revision_authority["taskId"], "task:revision")
        self.assertEqual(revision_authority["taskRevision"], 1)
        self.assertEqual(
            revision_authority["criteria"],
            [
                {
                    "criterionId": "ac:1",
                    "status": "pass",
                    "evidenceRefs": ["evidence:new-revision"],
                }
            ],
        )
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {
                "ac:1": ["evidence:new-revision"],
                "ac:2": ["evidence:independent"],
            },
        )

    def test_failed_revise_child_keeps_overlapping_old_evidence_invalidated(
        self,
    ) -> None:
        original, now_ms = _dispatch(
            "dispatch:original-failed-case",
            task_id="task:work",
            owner="participant:facilitator",
            intent="execute",
        )
        self._start(original, now_ms)
        self.store.apply_commit(
            _commit(
                "dispatch:original-failed-case",
                task_id="task:work",
                evidence_by_criterion={
                    "ac:1": "evidence:old-overlap-failed-case",
                    "ac:2": "evidence:independent-failed-case",
                },
            ),
            generation=0,
            now_ms=10,
        )
        revision_task = _task(
            "task:failed-revision",
            owner="participant:facilitator",
            criteria=("ac:1",),
            parent_task_id="task:work",
            revision=1,
        )
        self.store.create_task(revision_task, now_ms=11)
        revision, revision_ms = _dispatch(
            "dispatch:failed-revision",
            task_id="task:failed-revision",
            owner="participant:facilitator",
            intent="revise",
            created_at_ms=12,
        )
        self.store.enqueue_dispatch(revision, now_ms=revision_ms)
        failed_task = {**revision_task, "state": "failed"}
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=? "
                "WHERE dispatch_id=?",
                (13, "dispatch:failed-revision"),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='failed',payload_json=?,"
                "updated_at_ms=? WHERE task_id=?",
                (
                    json.dumps(
                        failed_task,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    13,
                    "task:failed-revision",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {"ac:2": ["evidence:independent-failed-case"]},
        )
        self.assertIn(
            "ac:1",
            self.store.report_readiness("root:freshness")[
                "unprovenAcceptanceCriteria"
            ],
        )

    def test_newer_revise_task_wins_even_with_lower_local_revision(
        self,
    ) -> None:
        original, now_ms = _dispatch(
            "dispatch:original-local-revision",
            task_id="task:work",
            owner="participant:facilitator",
            intent="execute",
        )
        self._start(original, now_ms)
        self.store.apply_commit(
            _commit(
                "dispatch:original-local-revision",
                task_id="task:work",
                evidence_by_criterion={
                    "ac:1": "evidence:original-local-revision",
                    "ac:2": "evidence:independent-local-revision",
                },
            ),
            generation=0,
            now_ms=10,
        )
        self.store.create_task(
            _task(
                "task:older-high-local-revision",
                owner="participant:facilitator",
                criteria=("ac:1",),
                parent_task_id="task:work",
                revision=9,
            ),
            now_ms=11,
        )
        older, older_ms = _dispatch(
            "dispatch:older-high-local-revision",
            task_id="task:older-high-local-revision",
            owner="participant:facilitator",
            intent="revise",
            created_at_ms=12,
        )
        self._start(older, older_ms)
        self.store.apply_commit(
            _commit(
                "dispatch:older-high-local-revision",
                task_id="task:older-high-local-revision",
                evidence_by_criterion={
                    "ac:1": "evidence:older-high-local-revision"
                },
            ),
            generation=0,
            now_ms=20,
        )
        self.store.create_task(
            _task(
                "task:newer-low-local-revision",
                owner="participant:facilitator",
                criteria=("ac:1",),
                parent_task_id="task:work",
                revision=1,
            ),
            now_ms=21,
        )
        newer, newer_ms = _dispatch(
            "dispatch:newer-low-local-revision",
            task_id="task:newer-low-local-revision",
            owner="participant:facilitator",
            intent="revise",
            created_at_ms=22,
        )
        self.store.enqueue_dispatch(newer, now_ms=newer_ms)

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {"ac:2": ["evidence:independent-local-revision"]},
        )

    def test_revise_scope_survives_task_projection_tamper(self) -> None:
        original, now_ms = _dispatch(
            "dispatch:original-scope-tamper",
            task_id="task:work",
            owner="participant:facilitator",
            intent="execute",
        )
        self._start(original, now_ms)
        self.store.apply_commit(
            _commit(
                "dispatch:original-scope-tamper",
                task_id="task:work",
                evidence_by_criterion={
                    "ac:1": "evidence:scope-old",
                    "ac:2": "evidence:scope-independent",
                },
            ),
            generation=0,
            now_ms=10,
        )
        revision_task = _task(
            "task:revision-scope-tamper",
            owner="participant:facilitator",
            criteria=("ac:1",),
            parent_task_id="task:work",
            revision=1,
        )
        self.store.create_task(revision_task, now_ms=11)
        revision, revision_ms = _dispatch(
            "dispatch:revision-scope-tamper",
            task_id="task:revision-scope-tamper",
            owner="participant:facilitator",
            intent="revise",
            created_at_ms=12,
        )
        self.store.enqueue_dispatch(revision, now_ms=revision_ms)
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:revision-scope-tamper",),
            ).fetchone()
            tampered = json.loads(str(row["payload_json"]))
            tampered["acceptanceCriterionIds"] = []
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        tampered,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:revision-scope-tamper",
                ),
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:freshness"),
            {"ac:2": ["evidence:scope-independent"]},
        )


class RoomReviewCrossTaskFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-review-freshness-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), latest_migration_version())
        self.store.create_root_with_task(
            _root(),
            _task("task:work", owner="participant:author"),
            budget=32,
            max_hops=8,
            max_depth=4,
            acceptance_criteria=("ac:1",),
            now_ms=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_review(
        self,
        task_id: str,
        dispatch_id: str,
        *,
        reviewer: str,
        reviewed_task_id: str,
        authors: tuple[str, ...],
        findings: list[dict[str, object]],
        state: str,
        review_state: str,
        revision: int,
        now_ms: int,
    ) -> None:
        requested_payload = _task(
                task_id,
                owner=reviewer,
                parent_task_id="task:work",
                task_kind="review",
                state="active",
                review_state="in_review",
                review_of=(reviewed_task_id,),
                authors=authors,
                findings=findings,
                revision=revision,
            )
        self.store.create_task(
            requested_payload,
            now_ms=now_ms,
        )
        dispatch, dispatch_ms = _dispatch(
            dispatch_id,
            task_id=task_id,
            owner=reviewer,
            intent="review",
            created_at_ms=now_ms + 1,
        )
        self.store.enqueue_dispatch(dispatch, now_ms=dispatch_ms)
        self.store.set_dispatch_wait_state(
            dispatch_id,
            "running",
            now_ms=now_ms + 2,
        )
        if state != "active":
            terminal_payload = {
                **requested_payload,
                "state": state,
                "reviewState": review_state,
            }
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    "UPDATE room_kernel_dispatches SET state='committed',updated_at_ms=? WHERE dispatch_id=?",
                    (now_ms + 2, dispatch_id),
                )
                conn.execute(
                    "UPDATE room_kernel_tasks SET state=?,review_state=?,payload_json=?,updated_at_ms=? WHERE task_id=?",
                    (
                        state,
                        (
                            "accepted"
                            if review_state == "accepted_with_notes"
                            else review_state
                        ),
                        json.dumps(
                            terminal_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        now_ms + 2,
                        task_id,
                    ),
                )

    def _record_review_evidence(
        self,
        *,
        task_id: str,
        dispatch_id: str,
        reviewer: str,
        evidence_ref: str,
        created_at_ms: int,
    ) -> None:
        manifest_id = f"manifest:{dispatch_id}:evidence"
        manifest_hash = "c" * 64
        invocation_id = f"invoke:{dispatch_id}:evidence"
        session_id = f"session:{reviewer}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO room_v2_capability_manifests(
                   manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,
                   generation,capability_revision,capability_epoch,manifest_hash,
                   payload_json,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1, ?, '{}', ?)""",
                (
                    manifest_id,
                    f"binding:{dispatch_id}:evidence",
                    "room:freshness",
                    "root:freshness",
                    task_id,
                    dispatch_id,
                    "capability:test-v1",
                    manifest_hash,
                    created_at_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_capability_runtime_bindings(
                   session_id,manifest_id,manifest_hash,prompt_compile_receipt_id,
                   prompt_plan_hash,compiled_profile_id,compiled_profile_revision,
                   compiled_profile_hash,room_binding_json,participant_binding_json,
                   capability_epoch,state,created_at_ms,updated_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', 1, 'active', ?, ?)""",
                (
                    session_id,
                    manifest_id,
                    manifest_hash,
                    f"prompt:{dispatch_id}:evidence",
                    "d" * 64,
                    "compiled:test",
                    "1",
                    "e" * 64,
                    created_at_ms - 2,
                    created_at_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_invocation_receipts(
                   receipt_id,manifest_id,manifest_hash,load_receipt_id,
                   invocation_key,canonical_tool_name,original_tool_name,
                   command_hash,command_json,authorization_state,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, 'room_state', 'room_state', ?, '{}',
                             'authorized', ?)""",
                (
                    invocation_id,
                    manifest_id,
                    manifest_hash,
                    f"load:{dispatch_id}:evidence",
                    f"call:{dispatch_id}:evidence",
                    "f" * 64,
                    created_at_ms - 1,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_execution_receipts(
                   execution_receipt_id,invocation_receipt_id,kernel_receipt_id,
                   session_id,tool_name,status,result_hash,payload_json,created_at_ms
                   ) VALUES (?, ?, NULL, ?, 'room_state', 'applied', ?, '{}', ?)""",
                (
                    evidence_ref,
                    invocation_id,
                    session_id,
                    "a" * 64,
                    created_at_ms,
                ),
            )

    def test_new_review_task_cannot_downgrade_prior_blocker(self) -> None:
        prior = _finding()
        self._create_review(
            "task:review-old",
            "dispatch:review-old",
            reviewer="participant:reviewer-old",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[prior],
            state="completed",
            review_state="accepted",
            revision=1,
            now_ms=3,
        )
        self._create_review(
            "task:review-new",
            "dispatch:review-new",
            reviewer="participant:reviewer-new",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="active",
            review_state="in_review",
            revision=2,
            now_ms=10,
        )
        downgraded = _finding(gate_effect="advisory", state="dismissed")

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "cannot be downgraded|stable scope or content",
        ):
            self.store.apply_commit(
                _commit(
                    "dispatch:review-new",
                    task_id="task:review-new",
                    evidence_by_criterion={"ac:1": "evidence:review"},
                    review_findings=[downgraded],
                ),
                generation=0,
                now_ms=20,
            )
    def test_advisory_in_new_review_task_cannot_pop_prior_blocker(self) -> None:
        prior = _finding()
        self._create_review(
            "task:review-old",
            "dispatch:review-old",
            reviewer="participant:reviewer-old",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[prior],
            state="completed",
            review_state="accepted",
            revision=1,
            now_ms=3,
        )
        self._create_review(
            "task:review-new",
            "dispatch:review-new",
            reviewer="participant:reviewer-new",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[_finding(gate_effect="advisory", state="dismissed")],
            state="completed",
            review_state="accepted_with_notes",
            revision=2,
            now_ms=10,
        )

        with self.store._connect() as conn:
            lineage = self.store._review_lineage_fences_locked(
                conn,
                root_id="root:freshness",
            )
        self.assertEqual(
            [
                item["findingId"]
                for item in lineage["unresolvedFindings"]
                if item.get("gateEffect") == "blocking"
            ],
            ["finding:shared"],
        )

    def test_immutable_old_review_commit_survives_corrupt_task_projection(
        self,
    ) -> None:
        prior = _finding()
        self._create_review(
            "task:review-old",
            "dispatch:review-old",
            reviewer="participant:reviewer-old",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="active",
            review_state="in_review",
            revision=1,
            now_ms=3,
        )
        review_evidence = "evidence:review-old"
        self._record_review_evidence(
            task_id="task:review-old",
            dispatch_id="dispatch:review-old",
            reviewer="participant:reviewer-old",
            evidence_ref=review_evidence,
            created_at_ms=8,
        )
        prior = {**prior, "evidenceRefs": [review_evidence]}
        self.store.apply_commit(
            _commit(
                "dispatch:review-old",
                task_id="task:review-old",
                evidence_by_criterion={"ac:1": review_evidence},
                review_findings=[prior],
                action="wait",
            ),
            generation=0,
            now_ms=9,
        )
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:review-old",),
            ).fetchone()
            corrupted = json.loads(str(row["payload_json"]))
            corrupted["reviewFindings"] = []
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        corrupted,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:review-old",
                ),
            )
        self._create_review(
            "task:review-new",
            "dispatch:review-new",
            reviewer="participant:reviewer-new",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="active",
            review_state="in_review",
            revision=2,
            now_ms=10,
        )

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "cannot be downgraded|stable scope or content",
        ):
            self.store.apply_commit(
                _commit(
                    "dispatch:review-new",
                    task_id="task:review-new",
                    evidence_by_criterion={"ac:1": "evidence:review-new"},
                    review_findings=[
                        _finding(gate_effect="advisory", state="dismissed")
                    ],
                ),
                generation=0,
                now_ms=20,
            )
        self._create_review(
            "task:review-scanner",
            "dispatch:review-scanner",
            reviewer="participant:reviewer-scanner",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[_finding(gate_effect="advisory", state="dismissed")],
            state="completed",
            review_state="accepted_with_notes",
            revision=3,
            now_ms=30,
        )
        with self.store._connect() as conn:
            lineage = self.store._review_lineage_fences_locked(
                conn,
                root_id="root:freshness",
            )
        self.assertEqual(
            [
                item["findingId"]
                for item in lineage["unresolvedFindings"]
                if item.get("gateEffect") == "blocking"
            ],
            ["finding:shared"],
        )

    def test_each_reviewed_task_lineage_rechecks_independence(self) -> None:
        self.store.create_task(
            _task(
                "task:work-b",
                owner="participant:author-b",
                parent_task_id="task:work",
            ),
            now_ms=2,
        )
        self._create_review(
            "task:self-review",
            "dispatch:self-review",
            reviewer="participant:author",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=1,
            now_ms=3,
        )
        self._create_review(
            "task:independent-review",
            "dispatch:independent-review",
            reviewer="participant:reviewer",
            reviewed_task_id="task:work-b",
            authors=("participant:author-b",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=2,
            now_ms=20,
        )

        with self.store._connect() as conn:
            governance = self.store._terminal_governance_fences(
                conn,
                root_id="root:freshness",
            )
        self.assertTrue(
            any(
                item.get("reason") == "reviewer_not_independent"
                and item.get("taskId") == "task:self-review"
                for item in governance["reviewFences"]
            ),
            governance["reviewFences"],
        )

    def test_same_lineage_new_independent_review_does_not_hide_self_review(
        self,
    ) -> None:
        self._create_review(
            "task:self-review-old",
            "dispatch:self-review-old",
            reviewer="participant:author",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=1,
            now_ms=3,
        )
        self._create_review(
            "task:independent-review-new",
            "dispatch:independent-review-new",
            reviewer="participant:reviewer",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=2,
            now_ms=10,
        )

        with self.store._connect() as conn:
            governance = self.store._terminal_governance_fences(
                conn,
                root_id="root:freshness",
            )
        self.assertTrue(
            any(
                item.get("reason") == "reviewer_not_independent"
                and item.get("taskId") == "task:self-review-old"
                for item in governance["reviewFences"]
            ),
            governance["reviewFences"],
        )

    def test_same_lineage_new_self_review_remains_fail_closed(self) -> None:
        self._create_review(
            "task:independent-review-old",
            "dispatch:independent-review-old",
            reviewer="participant:reviewer",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=1,
            now_ms=3,
        )
        self._create_review(
            "task:self-review-new",
            "dispatch:self-review-new",
            reviewer="participant:author",
            reviewed_task_id="task:work",
            authors=("participant:author",),
            findings=[],
            state="completed",
            review_state="accepted",
            revision=2,
            now_ms=10,
        )

        with self.store._connect() as conn:
            governance = self.store._terminal_governance_fences(
                conn,
                root_id="root:freshness",
            )
        self.assertTrue(
            any(
                item.get("reason") == "reviewer_not_independent"
                and item.get("taskId") == "task:self-review-new"
                for item in governance["reviewFences"]
            ),
            governance["reviewFences"],
        )


class RoomTerminalStateProjectionTests(unittest.TestCase):
    def test_cancelled_with_unknowns_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-terminal-projection-") as tmp:
            store = RoomKernelStore(Path(tmp) / "rag-ime.sqlite", mode="test")
            self.assertEqual(store.initialize(), latest_migration_version())
            store.create_root_with_task(
                _root(),
                _task("task:work", owner="participant:facilitator"),
                budget=4,
                max_hops=2,
                max_depth=2,
                acceptance_criteria=("ac:1",),
                now_ms=1,
            )
            with store._connect(immediate=True) as conn:
                conn.execute(
                    "UPDATE room_kernel_roots SET state='cancelled_with_unknowns' WHERE root_id=?",
                    ("root:freshness",),
                )
            self.assertTrue(store.is_root_terminal("root:freshness"))


if __name__ == "__main__":
    unittest.main()
