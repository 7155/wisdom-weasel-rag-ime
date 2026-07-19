from __future__ import annotations

import json
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel_contracts import (
    CONTRACT_FILES,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    EVENT_ENVELOPE_SCHEMA_VERSION,
    LEGACY_REF_SCHEMA_VERSION,
    PARTICIPANT_BINDING_SCHEMA_VERSION,
    ROOM_BINDING_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
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
                "room-root-execution.v2.json",
                "https://wisdom-weasel.local/contracts/room-root-execution.v2.json",
                ROOT_EXECUTION_SCHEMA_VERSION,
            ),
            "roomTask": (
                "room-task.v2.json",
                "https://wisdom-weasel.local/contracts/room-task.v2.json",
                ROOM_TASK_SCHEMA_VERSION,
            ),
            "dispatchEnvelope": (
                "room-dispatch-envelope.v2.json",
                "https://wisdom-weasel.local/contracts/room-dispatch-envelope.v2.json",
                DISPATCH_ENVELOPE_SCHEMA_VERSION,
            ),
            "roomCommit": (
                "room-commit.v2.json",
                "https://wisdom-weasel.local/contracts/room-commit.v2.json",
                ROOM_COMMIT_SCHEMA_VERSION,
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
            "legacyRef": (
                "room-legacy-ref.v1.json",
                "https://wisdom-weasel.local/contracts/room-legacy-ref.v1.json",
                LEGACY_REF_SCHEMA_VERSION,
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
                "owner": "kernel-v2",
                "requirementAnchorRef": "requirement-anchor:1@sha256:abc",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:default-v1",
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
                "ownerParticipantId": "participant:coordinator",
                "assigneeParticipantId": "participant:worker",
                "objective": "Inspect the route.",
                "expectedOutput": "A source-backed report.",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": ["criterion:1"],
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
