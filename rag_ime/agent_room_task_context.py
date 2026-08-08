from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .agent_prompt_support import bounded_text
from .agent_room_kernel import RoomKernelFenceError

ROOM_TASK_HANDOFF_SCHEMA_VERSION = "wisdom-weasel.room-task-handoff.v1"


def room_task_handoff_contract() -> dict[str, object]:
    """Return compact audit fields for the stable Room handoff policy."""

    return {
        "schemaVersion": ROOM_TASK_HANDOFF_SCHEMA_VERSION,
        "contextModeRule": "fork_if_parent_context_materially_helps_else_fresh",
        "independentReview": "fresh_read_only",
        "promptPrefix": "exact_managed_pi_transcript_prefix_plus_bounded_child_brief",
        "questionOwner": "facilitator_reporter",
        "participantQuestionPath": "structured_blocker_or_room_commit_wait",
        "standaloneParentAsk": "native_ask_1_to_4_material_questions",
        "lspReadonlyOperations": [
            "status",
            "symbols",
            "hover",
            "definition",
            "references",
            "diagnostics",
        ],
        "lspWriteOperations": ["rename", "code_action_apply"],
        "lspWriteApproval": "existing_hash_bound_approval",
        "exportedSymbolRule": "references_before_apply",
    }



class RoomTaskContextProjector:
    """Compose one immutable, bounded task packet for a Room Dispatch."""

    def __init__(
        self,
        requirements: Any,
        *,
        accepted_evidence_provider: Callable[
            [str], Mapping[str, Sequence[object]]
        ] | None = None,
    ) -> None:
        self.requirements = requirements
        self.accepted_evidence_provider = accepted_evidence_provider

    def render(
        self,
        task: Mapping[str, object],
        dispatch: Mapping[str, object],
        *,
        room_id: str = "",
    ) -> str:
        snapshot = self.requirements.dispatch_context(
            str(dispatch.get("dispatchId") or "")
        )
        if not isinstance(snapshot, Mapping):
            raise RoomKernelFenceError(
                "Room Dispatch has no frozen requirement observation"
            )
        binding = _mapping(snapshot.get("binding"))
        self._validate_binding(task, dispatch, binding)
        catalog = _mapping(snapshot.get("catalog"))
        requirement_ids = _string_set(
            task.get("requirementItemIds")
        )
        criterion_order = [
            str(value)
            for value in task.get("acceptanceCriterionIds") or []
            if str(value or "").strip()
        ]
        criterion_ids = set(criterion_order)
        raw_originals = _mappings(snapshot.get("originalRequirements"))[:8]
        originals = [
            {
                "anchorId": bounded_text(
                    original.get("anchorId"), maximum=240
                ),
                "text": bounded_text(
                    original.get("text"), maximum=4_000
                ),
                "sha256": bounded_text(
                    original.get("sha256"), maximum=64
                ),
                "authenticity": bounded_text(
                    original.get("authenticity"), maximum=40
                ),
            }
            for original in raw_originals
        ]
        original_statement_sources = {
            str(original.get("text") or "").strip(): f"original[{index}]"
            for index, original in enumerate(raw_originals)
            if str(original.get("text") or "").strip()
        }
        items = [
            _requirement_item(
                item,
                original_statement_sources=original_statement_sources,
            )
            for item in _mappings(catalog.get("items"))
            if str(item.get("itemId") or "") in requirement_ids
        ][:64]
        catalog_criteria = {
            str(criterion.get("criterionId") or ""): criterion
            for criterion in _mappings(
                catalog.get("acceptanceCriteria")
            )
        }
        accepted_evidence = (
            self.accepted_evidence_provider(str(dispatch["rootId"]))
            if self.accepted_evidence_provider is not None
            else {}
        )
        criteria = [
            _acceptance_criterion(
                catalog_criteria[criterion_id],
                accepted_evidence_refs=accepted_evidence.get(
                    criterion_id,
                    (),
                ),
            )
            for criterion_id in criterion_order
            if criterion_id in catalog_criteria
        ][:64]
        packet = {
            "schemaVersion": "wisdom-weasel.room-task-context.v1",
            "rootId": str(dispatch["rootId"]),
            "dispatchId": str(dispatch["dispatchId"]),
            "generation": int(dispatch["generation"]),
            "handoff": room_task_handoff_contract(),
            "task": {
                "taskId": str(task["taskId"]),
                "parentTaskId": task.get("parentTaskId"),
                "revision": int(task.get("revision") or 0),
                "state": str(task.get("state") or ""),
                "objective": bounded_text(
                    task.get("objective"), maximum=4_000
                ),
                "expectedOutput": bounded_text(
                    task.get("expectedOutput"), maximum=2_000
                ),
            },
            "responsibility": {
                "currentOwnerParticipantId": task.get(
                    "currentOwnerParticipantId"
                ),
                "ownershipRevision": int(
                    task.get("ownershipRevision") or 0
                ),
                "ownershipReceiptId": task.get(
                    "ownershipReceiptId"
                ),
                "currentParticipantId": dispatch.get(
                    "targetParticipantId"
                ),
            },
            "workspace": _workspace_ledger_projection(
                task,
                room_id=room_id,
                root_id=str(dispatch["rootId"]),
            ),
            "requirements": {
                "original": originals,
                "catalogRevisionId": (
                    catalog.get("catalogRevisionId") or None
                ),
                "catalogRevision": (
                    int(catalog.get("revision") or 0)
                    if catalog
                    else None
                ),
                "items": items,
                "missingItemIds": sorted(
                    requirement_ids
                    - {
                        str(item.get("itemId") or "")
                        for item in items
                    }
                ),
                "observationWarnings": list(
                    binding.get("observationWarnings") or []
                )[:16],
            },
            "acceptance": {
                "criteria": criteria,
                "missingCriterionIds": sorted(
                    criterion_ids
                    - {
                        str(criterion.get("criterionId") or "")
                        for criterion in criteria
                    }
                ),
            },
            "sharedEvidenceRefs": [
                bounded_text(value, maximum=500)
                for value in task.get("contextEvidenceRefs") or []
                if str(value or "").strip()
            ][:32],
            "blockers": {
                "obstacles": [
                    _obstacle(value)
                    for value in _mappings(
                        catalog.get("openObstacles")
                    )[:32]
                ],
                "conflicts": [
                    _conflict(value)
                    for value in _mappings(
                        catalog.get("openConflicts")
                    )[:32]
                ],
            },
            "continuation": {
                "intentKind": str(
                    dispatch.get("intentKind") or ""
                ),
                "parentDispatchId": dispatch.get(
                    "parentDispatchId"
                ),
                "hopCount": int(dispatch.get("hopCount") or 0),
                "depth": int(dispatch.get("depth") or 0),
            },
        }
        return json.dumps(
            packet,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _validate_binding(
        task: Mapping[str, object],
        dispatch: Mapping[str, object],
        binding: Mapping[str, object],
    ) -> None:
        expected = (
            ("dispatchId", dispatch.get("dispatchId")),
            ("rootId", dispatch.get("rootId")),
            ("taskId", task.get("taskId")),
            ("sessionId", dispatch.get("targetSessionId")),
            ("generation", dispatch.get("generation")),
        )
        for key, value in expected:
            if binding.get(key) != value:
                raise RoomKernelFenceError(
                    f"Room task context binding mismatch: {key}"
                )


def _workspace_ledger_projection(
    task: Mapping[str, object],
    *,
    room_id: str,
    root_id: str,
) -> dict[str, object]:
    """Project the Task's authoritative workspace receipt into private context.

    The packet lets the implementation Skill mirror one compact Workspace
    Ledger block in its existing WorkDocument.  It is not a second lifecycle
    owner: every value is copied from the canonical Task projection, and an
    absent binding remains explicit instead of being inferred from a path.
    """

    binding_id = bounded_text(task.get("workspaceBindingId"), maximum=240)
    policy = bounded_text(task.get("workspacePolicy"), maximum=80)
    lifecycle = bounded_text(
        task.get("workspaceLifecycleState"), maximum=80
    )
    cleanup = bounded_text(task.get("workspaceCleanupState"), maximum=80)
    bound = bool(binding_id or policy or lifecycle or cleanup)
    return {
        "bound": bound,
        "roomId": bounded_text(room_id, maximum=240),
        "rootId": bounded_text(root_id, maximum=240),
        "bindingId": binding_id,
        "repositoryId": bounded_text(
            task.get("workspaceRepositoryId"), maximum=128
        ),
        "policy": policy,
        "workspaceRoot": bounded_text(
            task.get("workspaceRoot"), maximum=2_000
        ),
        "baseline": {
            "root": bounded_text(
                task.get("workspaceBaseRoot"), maximum=2_000
            ),
            "commit": bounded_text(
                task.get("workspaceBaseCommit"), maximum=240
            ),
            "snapshotSha256": bounded_text(
                task.get("workspaceSnapshotSha256"), maximum=128
            ),
        },
        "lifecycleState": lifecycle,
        "attentionRequired": bool(
            task.get("workspaceAttentionRequired")
        ),
        "delivery": {
            "revision": bounded_text(
                task.get("workspaceDeliveryRevision"), maximum=240
            ),
            "head": bounded_text(
                task.get("workspaceDeliveryHead"), maximum=240
            ),
            "snapshotSha256": bounded_text(
                task.get("workspaceDeliverySnapshotSha256"), maximum=128
            ),
        },
        "integration": {
            "state": bounded_text(
                task.get("workspaceIntegrationState"), maximum=80
            ),
            "ref": bounded_text(
                task.get("workspaceIntegrationRef"), maximum=240
            ),
            "patchSha256": bounded_text(
                task.get("workspaceIntegrationPatchSha256"), maximum=128
            ),
            "revision": bounded_text(
                task.get("workspaceIntegratedRevision"), maximum=240
            ),
            "snapshotSha256": bounded_text(
                task.get("workspaceIntegratedSnapshotSha256"), maximum=128
            ),
        },
        "cleanupState": cleanup,
        "terminalReason": bounded_text(
            task.get("workspaceTerminalReason"), maximum=2_000
        ),
    }


def _requirement_item(
    value: Mapping[str, object],
    *,
    original_statement_sources: Mapping[str, str],
) -> dict[str, object]:
    raw_statement = str(value.get("statement") or "").strip()
    source = (
        original_statement_sources.get(raw_statement)
        if value.get("kind") == "explicit_user_requirement"
        else None
    )
    item = {
        "itemId": bounded_text(value.get("itemId"), maximum=240),
        "kind": bounded_text(value.get("kind"), maximum=80),
        "state": bounded_text(value.get("state"), maximum=40),
    }
    if source is not None:
        item["statementSource"] = source
    else:
        item["statement"] = bounded_text(
            value.get("statement"), maximum=1_500
        )
    return item


def _acceptance_criterion(
    value: Mapping[str, object],
    *,
    accepted_evidence_refs: Sequence[object] = (),
) -> dict[str, object]:
    proofs = [
        {
            "receiptId": bounded_text(
                proof.get("receiptId"), maximum=240
            ),
            "receiptType": bounded_text(
                proof.get("receiptType"), maximum=40
            ),
            "sourceCommit": bounded_text(
                proof.get("sourceCommit"), maximum=240
            ),
            "exitStatus": int(proof.get("exitStatus") or 0),
        }
        for proof in _mappings(value.get("proofs"))[:16]
    ]
    inherited_refs = list(
        dict.fromkeys(
            str(raw_ref or "").strip()
            for raw_ref in accepted_evidence_refs
            if str(raw_ref or "").strip()
        )
    )[:32]
    return {
        "criterionId": bounded_text(
            value.get("criterionId"), maximum=240
        ),
        "itemId": bounded_text(value.get("itemId"), maximum=240),
        "fullNameZh": bounded_text(
            value.get("fullNameZh"), maximum=240
        ),
        "kind": bounded_text(value.get("kind"), maximum=40),
        "statement": bounded_text(
            value.get("statement"), maximum=1_000
        ),
        "expectedReceiptTypes": list(
            value.get("expectedReceiptTypes") or []
        )[:8],
        "proofs": proofs,
        "acceptedEvidenceRefs": inherited_refs,
        "passed": any(
            int(proof.get("exitStatus") or 0) == 0
            for proof in proofs
        )
        or bool(inherited_refs),
    }


def _obstacle(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "obstacleId": bounded_text(
            value.get("obstacleId"), maximum=240
        ),
        "kind": bounded_text(value.get("kind"), maximum=40),
        "statement": bounded_text(
            value.get("statement"), maximum=1_000
        ),
    }


def _conflict(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "conflictId": bounded_text(
            value.get("conflictId"), maximum=240
        ),
        "kind": bounded_text(value.get("kind"), maximum=40),
        "leftItemId": bounded_text(
            value.get("leftItemId"), maximum=240
        ),
        "rightItemId": bounded_text(
            value.get("rightItemId"), maximum=240
        ),
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes)
    ):
        return []
    return [
        dict(item) for item in value if isinstance(item, Mapping)
    ]


def _string_set(value: object) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes)
    ):
        return set()
    return {
        str(item).strip() for item in value if str(item).strip()
    }
