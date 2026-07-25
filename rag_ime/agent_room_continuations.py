from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from .agent_room_application import DEFAULT_RUNTIME_PROFILE_REVISION
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_kernel import RoomKernelStore
from .agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
)
from .agent_rooms import AgentRoomStore


class RoomContinuationProposalError(ValueError):
    """A model-proposed Room continuation cannot be bound safely."""


class RoomContinuationFactory:
    """Build canonical child Task/Dispatch pairs for one Kernel queue."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        kernel: RoomKernelStore,
        capabilities: RoomCapabilityManifestStore,
    ) -> None:
        self.rooms = rooms
        self.kernel = kernel
        self.capabilities = capabilities

    def build(
        self,
        *,
        parent_dispatch: Mapping[str, object],
        parent_task: Mapping[str, object],
        room_id: str,
        target_participant_id: str,
        trigger_id: str,
        intent_kind: str,
        objective: str,
        expected_output: str,
        acceptance_criterion_ids: Sequence[str],
        context_evidence_refs: Sequence[str] = (),
        kind: str,
    ) -> dict[str, object]:
        if kind not in {"handoff", "collaboration"}:
            raise ValueError("Room continuation kind is invalid")
        target = self.rooms.participant(target_participant_id)
        if target.get("roomId") != room_id or target.get("status") != "active":
            raise RoomContinuationProposalError(
                f"{kind} target is not an active participant in this Room"
            )
        if target.get("id") == parent_dispatch.get("targetParticipantId"):
            raise RoomContinuationProposalError(
                f"{kind} target must differ from the current participant"
            )
        session_id = str(target.get("sessionId") or "").strip()
        if not session_id or self.kernel.session_binding(session_id) is not None:
            raise RoomContinuationProposalError(f"{kind} target is currently busy")
        previous = self.capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        if previous is not None and previous.get("state") in {"active", "prepared"}:
            raise RoomContinuationProposalError(
                f"{kind} target capability is still active"
            )

        parent_criteria = [
            str(item)
            for item in parent_task.get("acceptanceCriterionIds") or []
            if str(item).strip()
        ]
        criteria = _unique_text(acceptance_criterion_ids)
        if not criteria:
            raise RoomContinuationProposalError(
                f"{kind} requires at least one acceptance criterion"
            )
        unknown = sorted(set(criteria) - set(parent_criteria))
        if unknown:
            raise RoomContinuationProposalError(
                f"{kind} acceptance criteria are outside the parent Task"
            )
        parent_epoch = max(1, int(parent_dispatch.get("capabilityEpoch") or 0))
        # capabilityEpoch is a Root execution wave, not a target Session counter.
        # A sequential handoff advances the wave. Parallel collaboration, and a
        # handoff inside an already-parallel wave, must stay in the current wave
        # so one sibling cannot revoke another sibling's Skill fence.
        capability_epoch = parent_epoch
        if kind == "handoff" and not self.kernel.has_active_capability_peer(
            str(parent_dispatch["dispatchId"])
        ):
            capability_epoch += 1
        task_id = _stable_id(
            "room-task",
            trigger_id,
            target_participant_id,
            kind,
        )
        dispatch_id = _stable_id(
            "room-dispatch",
            trigger_id,
            target_participant_id,
            kind,
        )
        current_participant_id = str(
            parent_dispatch.get("targetParticipantId") or ""
        )
        task = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": task_id,
            "rootId": parent_dispatch["rootId"],
            "parentTaskId": parent_task["taskId"],
            "ownerParticipantId": (
                target_participant_id
                if kind == "handoff"
                else current_participant_id
            ),
            "assigneeParticipantId": target_participant_id,
            "objective": _required(objective, "objective"),
            "expectedOutput": _required(expected_output, "expected_output"),
            "requirementItemIds": _unique_text(
                parent_task.get("requirementItemIds") or []
            ),
            "acceptanceCriterionIds": criteria,
            "contextEvidenceRefs": _unique_text(
                context_evidence_refs
            )[:32],
            "revision": 0,
            "state": "active",
        }
        dispatch = {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": dispatch_id,
            "rootId": parent_dispatch["rootId"],
            "taskId": task_id,
            "parentDispatchId": parent_dispatch["dispatchId"],
            "generation": parent_dispatch["generation"],
            "hopCount": int(parent_dispatch["hopCount"]) + 1,
            "depth": int(parent_dispatch["depth"]) + (
                1 if kind == "collaboration" else 0
            ),
            "budgetCost": 1,
            "targetSessionId": session_id,
            "targetParticipantId": target_participant_id,
            "triggerId": trigger_id,
            "intentKind": intent_kind,
            "idempotencyKey": (
                f"room-{kind}:{trigger_id}:{target_participant_id}"
            ),
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": (
                f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                f"{target.get('roleId')}@{target.get('roleVersion') or '1'}"
            ),
            "state": "pending",
        }
        result: dict[str, object] = {
            "childTask": task,
            "childDispatch": dispatch,
        }
        if kind == "handoff" and intent_kind == "close":
            wait_for = self.kernel.close_barrier_dispatch_ids(
                str(parent_dispatch["dispatchId"])
            )
            if wait_for:
                # A final closer must observe results from work that was
                # already running in the same execution wave. Keep the
                # dependency in Kernel metadata rather than exposing internal
                # Dispatch IDs to the model.
                result["waitForDispatchIds"] = wait_for
        return result


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:40]}"


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RoomContinuationProposalError(f"{name} must not be empty")
    return text


def _unique_text(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
