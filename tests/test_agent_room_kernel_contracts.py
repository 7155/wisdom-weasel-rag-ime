from __future__ import annotations

import json
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel_contracts import (
    AGENT_APPROVAL_MODEL_DECISION_SCHEMA_VERSION,
    CONTRACT_FILES,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    EVENT_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    KERNEL_RECEIPT_SCHEMA_VERSION,
    PARTICIPANT_BINDING_SCHEMA_VERSION,
    ROOM_BINDING_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
    ROOM_POST_SCHEMA_VERSION,
    ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
    ROOM_SETTLE_RESULT_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    validate_kernel_contract,
)
from rag_ime.contracts.json_schema import ContractValidationError, load_contract


class AgentRoomKernelContractsTest(unittest.TestCase):
    def test_source_refresh_freezes_all_five_compatibility_scenarios(self) -> None:
        path = (
            Path(__file__).parent
            / "fixtures"
            / "room_v2_baseline"
            / "behavior-matrix.v1.json"
        )
        baseline = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            baseline["baselineCommit"],
            "519094e04638afff7a0c675f9d902ddec892ff85",
        )
        self.assertEqual(
            {item["id"] for item in baseline["scenarios"]},
            {
                "ordinary-assistant",
                "ordinary-coordinator",
                "collaboration-room-participant",
                "roleplay-room-participant",
                "readonly-delegated-agent",
            },
        )
        ordinary = baseline["scenarios"][:2]
        self.assertTrue(all(item["roomBinding"] is None for item in ordinary))
        self.assertTrue(all(not item["roomWritesExpected"] for item in ordinary))

    def test_contract_names_ids_and_wire_versions_are_frozen(self) -> None:
        expected = {
            "rootExecution": (
                "room-root-execution.v3.json",
                "https://wisdom-weasel.local/contracts/room-root-execution.v3.json",
                ROOT_EXECUTION_SCHEMA_VERSION,
            ),
            "roomTask": (
                "room-task.v3.json",
                "https://wisdom-weasel.local/contracts/room-task.v3.json",
                ROOM_TASK_SCHEMA_VERSION,
            ),
            "dispatchEnvelope": (
                "room-dispatch-envelope.v2.json",
                "https://wisdom-weasel.local/contracts/room-dispatch-envelope.v2.json",
                DISPATCH_ENVELOPE_SCHEMA_VERSION,
            ),
            "roomCommit": (
                "room-commit.v4.json",
                "https://wisdom-weasel.local/contracts/room-commit.v4.json",
                ROOM_COMMIT_SCHEMA_VERSION,
            ),
            "roomQualityGateReceipt": (
                "room-quality-gate-receipt.v1.json",
                (
                    "https://wisdom-weasel.local/contracts/"
                    "room-quality-gate-receipt.v1.json"
                ),
                ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
            ),
            "eventEnvelope": (
                "room-event-envelope.v2.json",
                "https://wisdom-weasel.local/contracts/room-event-envelope.v2.json",
                EVENT_ENVELOPE_SCHEMA_VERSION,
            ),
            "roomBinding": (
                "room-binding.v2.json",
                "https://wisdom-weasel.local/contracts/room-binding.v2.json",
                ROOM_BINDING_SCHEMA_VERSION,
            ),
            "participantBinding": (
                "room-participant-binding.v2.json",
                "https://wisdom-weasel.local/contracts/room-participant-binding.v2.json",
                PARTICIPANT_BINDING_SCHEMA_VERSION,
            ),
            "kernelCommand": (
                "room-kernel-command.v1.json",
                "https://wisdom-weasel.local/contracts/room-kernel-command.v1.json",
                KERNEL_COMMAND_SCHEMA_VERSION,
            ),
            "kernelReceipt": (
                "room-kernel-receipt.v1.json",
                "https://wisdom-weasel.local/contracts/room-kernel-receipt.v1.json",
                KERNEL_RECEIPT_SCHEMA_VERSION,
            ),
            "roomPost": (
                "room-post.v2.json",
                "https://wisdom-weasel.local/contracts/room-post.v2.json",
                ROOM_POST_SCHEMA_VERSION,
            ),
            "roomSettleReceipt": (
                "room-settle-receipt.v1.json",
                "https://wisdom-weasel.local/contracts/room-settle-receipt.v1.json",
                ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            ),
            "roomSettleResult": (
                "room-settle-result.v1.json",
                "https://wisdom-weasel.local/contracts/room-settle-result.v1.json",
                ROOM_SETTLE_RESULT_SCHEMA_VERSION,
            ),
            "agentApprovalModelDecision": (
                "agent-approval-model-decision.v1.json",
                "https://wisdom-weasel.local/contracts/agent-approval-model-decision.v1.json",
                AGENT_APPROVAL_MODEL_DECISION_SCHEMA_VERSION,
            ),
        }

        self.assertEqual(CONTRACT_FILES, {key: value[0] for key, value in expected.items()})
        for key, (filename, contract_id, wire_version) in expected.items():
            with self.subTest(contract=key):
                schema = load_contract(filename)
                self.assertEqual(schema["$id"], contract_id)
                self.assertEqual(
                    schema["properties"]["schemaVersion"]["const"],
                    wire_version,
                )

    def test_validates_root_task_dispatch_commit_and_event(self) -> None:
        validate_kernel_contract(
            "rootExecution",
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:1",
                "roomId": "room:1",
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": "participant:coordinator",
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:1@sha256:abc",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:default-v1",
                "independentReviewRequired": False,
                "createdAtMs": 1,
            },
        )
        validate_kernel_contract(
            "roomTask",
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:1",
                "rootId": "root:1",
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": "participant:worker",
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "objective": "Inspect the route.",
                "expectedOutput": "A source-backed report.",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": ["criterion:1"],
                "contextEvidenceRefs": [],
                "invitationId": None,
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "reviewState": "not_required",
                "revision": 0,
                "state": "active",
            },
        )
        validate_kernel_contract(
            "dispatchEnvelope",
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": "dispatch:1",
                "rootId": "root:1",
                "taskId": "task:1",
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 1,
                "targetSessionId": "session:worker",
                "targetParticipantId": "participant:worker",
                "triggerId": "post:1",
                "intentKind": "execute",
                "idempotencyKey": "root:1:task:1:0",
                "attempt": 0,
                "capabilityEpoch": 2,
                "runtimeProfileRevision": "profile:worker@2",
                "state": "pending",
            },
        )
        validate_kernel_contract(
            "roomCommit",
            {
                "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
                "commitId": "commit:1",
                "dispatchId": "dispatch:1",
                "action": "complete",
                "contentHash": "sha256:abc",
                "postProposal": None,
                "qualityGateReceipt": {
                    "schemaVersion": (
                        "wisdom-weasel.room-quality-gate-receipt.v1"
                    ),
                    "receiptId": "quality:1",
                    "rootId": "root:1",
                    "taskId": "task:1",
                    "dispatchId": "dispatch:1",
                    "generation": 0,
                    "originalRequestChecked": True,
                    "verdict": "ready_to_deliver",
                    "items": [
                        {
                            "criterionId": "requirement:1",
                            "status": "pass",
                            "evidenceRefs": ["test:test_route"],
                        }
                    ],
                    "residualRisks": [],
                    "createdAtMs": 2,
                },
                "evidenceRefs": ["test:test_route"],
                "requirementCoverage": ["requirement:1"],
                "createdAtMs": 2,
            },
        )
        validate_kernel_contract(
            "eventEnvelope",
            {
                "schemaVersion": EVENT_ENVELOPE_SCHEMA_VERSION,
                "entityKind": "dispatch",
                "entityId": "dispatch:1",
                "eventKind": "dispatch_leased",
                "sequence": 1,
                "occurredAtMs": 2,
                "payload": {},
            },
        )

    def test_public_task_verification_contract_rejects_internal_acceptance_ids(
        self,
    ) -> None:
        payload = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": "task:public-verification",
            "rootId": "root:1",
            "parentTaskId": None,
            "taskKind": "work",
            "currentOwnerParticipantId": "participant:worker",
            "ownershipRevision": 0,
            "ownershipReceiptId": None,
            "objective": "Inspect the route.",
            "expectedOutput": "A source-backed report.",
            "requirementItemIds": ["requirement:1"],
            "acceptanceCriterionIds": ["criterion:private"],
            "contextEvidenceRefs": [],
            "invitationId": None,
            "reviewOfTaskIds": [],
            "reviewAuthorParticipantIds": [],
            "reviewState": "not_required",
            "verifications": [
                {
                    "label": "验收项 1",
                    "result": "pass",
                    "source": "quality_gate",
                }
            ],
            "revision": 0,
            "state": "active",
        }
        validate_kernel_contract("roomTask", payload)
        for verification in (
            {
                "label": "AC-1",
                "result": "pass",
                "source": "quality_gate",
            },
            {
                "label": "验收项 1",
                "result": "pass",
                "source": "criterionId:criterion:private",
            },
        ):
            with self.subTest(verification=verification):
                with self.assertRaises(ContractValidationError):
                    validate_kernel_contract(
                        "roomTask",
                        {**payload, "verifications": [verification]},
                    )

    def test_room_task_contract_accepts_isolated_workspace_reservation_baseline(
        self,
    ) -> None:
        payload = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": "task:isolated-workspace",
            "rootId": "root:1",
            "parentTaskId": "task:parent",
            "taskKind": "work",
            "currentOwnerParticipantId": "participant:worker",
            "ownershipRevision": 0,
            "ownershipReceiptId": None,
            "objective": "Implement a bounded change in an isolated worktree.",
            "expectedOutput": "A tested patch and delivery receipt.",
            "requirementItemIds": ["requirement:1"],
            "acceptanceCriterionIds": ["criterion:1"],
            "contextEvidenceRefs": [],
            "invitationId": None,
            "reviewOfTaskIds": [],
            "reviewAuthorParticipantIds": [],
            "reviewState": "not_required",
            "workspacePolicy": "isolated_writable",
            "workspaceBaseSnapshotSha256": "a" * 64,
            "workspaceBaseDirtyStatusSha256": "b" * 64,
            "workspaceBaseDirtyPaths": ["user-notes.local"],
            "workspaceBaseDirtyPathCount": 1,
            "workspaceBaseDirtyPathsTruncated": False,
            "workspaceBaseDirty": True,
            "workspaceReservationReceiptId": "room-workspace-event:1",
            "workspaceReservationReceiptSha256": "c" * 64,
            "revision": 0,
            "state": "active",
        }

        validate_kernel_contract("roomTask", payload)

    def test_structured_wait_question_round_trips_through_post_and_commit_contracts(
        self,
    ) -> None:
        options = [
            {
                "value": "safe",
                "label": "稳妥方案",
                "description": "保留当前边界",
                "recommended": True,
            },
            {
                "value": "fast",
                "label": "快速方案",
            },
        ]
        post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": "post:question",
            "roomId": "room:1",
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:worker",
            "kind": "wait",
            "visibility": "room",
            "content": "需要用户澄清",
            "question": {
                "prompt": "采用哪个方案？",
                "options": options,
            },
            "idempotencyKey": "post:question",
            "publicationSource": {
                "kind": "room_commit",
                "ref": "commit:question",
            },
            "createdAtMs": 2,
        }
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:question",
            "dispatchId": "dispatch:1",
            "action": "post",
            "contentHash": "sha256:question",
            "postProposal": post,
            "continuation": {
                "decision": "wait",
                "waitingFor": "user",
                "resumeCondition": "用户选择一个方案",
                "question": "采用哪个方案？",
                "questionOptions": options,
            },
            "qualityGateReceipt": {
                "schemaVersion": (
                    "wisdom-weasel.room-quality-gate-receipt.v1"
                ),
                "receiptId": "quality:question",
                "rootId": "root:1",
                "taskId": "task:1",
                "dispatchId": "dispatch:1",
                "generation": 0,
                "originalRequestChecked": True,
                "verdict": "not_ready",
                "items": [],
                "residualRisks": ["等待用户选择"],
                "createdAtMs": 2,
            },
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 2,
        }

        round_tripped = json.loads(
            json.dumps(
                {"post": post, "commit": commit},
                ensure_ascii=False,
            )
        )
        validate_kernel_contract("roomPost", round_tripped["post"])
        validate_kernel_contract("roomCommit", round_tripped["commit"])
        self.assertEqual(
            round_tripped["commit"]["continuation"]["questionOptions"],
            round_tripped["post"]["question"]["options"],
        )

    def test_room_binding_has_stable_identity_and_generation_fence(self) -> None:
        validate_kernel_contract(
            "roomBinding",
            {
                "schemaVersion": ROOM_BINDING_SCHEMA_VERSION,
                "bindingId": "binding:1",
                "rootId": "root:1",
                "roomId": "room:1",
                "participantId": "participant:worker",
                "taskId": None,
                "generation": 3,
                "protocolRevision": "room-kernel.v2",
                "capabilityRevision": "capability:4",
                "access": "write",
            },
        )
        with self.assertRaises(ContractValidationError):
            validate_kernel_contract(
                "roomBinding",
                {
                    "schemaVersion": ROOM_BINDING_SCHEMA_VERSION,
                    "bindingId": "binding:1",
                    "rootId": "root:1",
                    "roomId": "room:1",
                    "participantId": "participant:worker",
                    "taskId": None,
                    "generation": -1,
                    "protocolRevision": "room-kernel.v2",
                    "capabilityRevision": "capability:4",
                    "access": "write",
                },
            )

    def test_participant_binding_keeps_ordinary_agent_room_ref_null(self) -> None:
        payload = {
            "schemaVersion": PARTICIPANT_BINDING_SCHEMA_VERSION,
            "bindingId": "participant-binding:1",
            "sessionId": "session:ordinary-assistant",
            "personaRef": "rag-ime-definition://persona/present?version=1&contentHash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "collaborationRoleRef": "rag-ime-definition://collaboration-role/companion?version=1&contentHash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "agentTemplateRef": "rag-ime-definition://agent-template/assistant?version=1&contentHash=sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "collaborationProfileRef": None,
            "compiledRuntimeProfileRef": {
                "profileId": "runtime-profile:assistant",
                "revision": "1",
                "contentHash": "sha256:abcdef",
            },
            "capabilityRevision": "capability:assistant@1",
            "capabilityEpoch": 0,
            "roomBindingRef": None,
        }
        validate_kernel_contract("participantBinding", payload)

        payload["roomBindingRef"] = {
            "bindingId": "binding:1",
            "schemaVersion": "wrong.version",
        }
        with self.assertRaises(ContractValidationError):
            validate_kernel_contract("participantBinding", payload)


if __name__ == "__main__":
    unittest.main()
