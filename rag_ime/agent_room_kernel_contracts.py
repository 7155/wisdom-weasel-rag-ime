from __future__ import annotations

from collections.abc import Mapping

from .contracts.json_schema import validate_contract


ROOT_EXECUTION_SCHEMA_VERSION = "wisdom-weasel.room-root-execution.v3"
ROOM_TASK_SCHEMA_VERSION = "wisdom-weasel.room-task.v3"
DISPATCH_ENVELOPE_SCHEMA_VERSION = "wisdom-weasel.room-dispatch-envelope.v2"
ROOM_COMMIT_SCHEMA_VERSION = "wisdom-weasel.room-commit.v4"
ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION = (
    "wisdom-weasel.room-quality-gate-receipt.v1"
)
EVENT_ENVELOPE_SCHEMA_VERSION = "wisdom-weasel.room-event-envelope.v2"
ROOM_BINDING_SCHEMA_VERSION = "wisdom-weasel.room-binding.v2"
PARTICIPANT_BINDING_SCHEMA_VERSION = "wisdom-weasel.room-participant-binding.v2"
KERNEL_COMMAND_SCHEMA_VERSION = "wisdom-weasel.room-kernel-command.v1"
KERNEL_RECEIPT_SCHEMA_VERSION = "wisdom-weasel.room-kernel-receipt.v1"
ROOM_POST_SCHEMA_VERSION = "wisdom-weasel.room-post.v2"
ROOM_SETTLE_RECEIPT_SCHEMA_VERSION = "wisdom-weasel.room-settle-receipt.v1"
ROOM_SETTLE_RESULT_SCHEMA_VERSION = "wisdom-weasel.room-settle-result.v1"
AGENT_APPROVAL_MODEL_DECISION_SCHEMA_VERSION = (
    "rag-ime.agent-approval-model-decision.v1"
)
# Default value of the `runtimeProfileRevision` field carried by a dispatch
# envelope. It lives with the other versioned contract identifiers because both
# the application that opens a Root and the domain that builds a continuation
# stamp it; keeping it in the application layer forced the domain to import
# upward for a constant.
DEFAULT_RUNTIME_PROFILE_REVISION = "room-runtime-profile:interactive-v1"

CONTRACT_FILES = {
    "rootExecution": "room-root-execution.v3.json",
    "roomTask": "room-task.v3.json",
    "dispatchEnvelope": "room-dispatch-envelope.v2.json",
    "roomCommit": "room-commit.v4.json",
    "roomQualityGateReceipt": "room-quality-gate-receipt.v1.json",
    "eventEnvelope": "room-event-envelope.v2.json",
    "roomBinding": "room-binding.v2.json",
    "participantBinding": "room-participant-binding.v2.json",
    "kernelCommand": "room-kernel-command.v1.json",
    "kernelReceipt": "room-kernel-receipt.v1.json",
    "roomPost": "room-post.v2.json",
    "roomSettleReceipt": "room-settle-receipt.v1.json",
    "roomSettleResult": "room-settle-result.v1.json",
    "agentApprovalModelDecision": "agent-approval-model-decision.v1.json",
}

_ROOT_EXECUTION_V2 = "wisdom-weasel.room-root-execution.v2"
_ROOM_COMMIT_V2 = "wisdom-weasel.room-commit.v2"
_ROOM_COMMIT_V3 = "wisdom-weasel.room-commit.v3"
_UNSET = object()


def validate_kernel_contract(
    kind: str,
    payload: Mapping[str, object],
) -> None:
    """Validate a Room V2 wire object without applying any state transition."""

    try:
        filename = CONTRACT_FILES[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported Room Kernel contract kind: {kind}") from exc
    validate_contract(payload, filename)


def upcast_room_root_execution(
    payload: Mapping[str, object],
    *,
    facilitator_participant_id: object = _UNSET,
    reporter_participant_id: object = _UNSET,
    reporter_selection_receipt_id: object = _UNSET,
) -> dict[str, object]:
    """Return the current Root wire shape without rewriting durable history.

    A v2 Root predates both the facilitator/reporter split and the explicit
    independent-review policy.  Relational columns are authoritative for the
    participant identities after migration 0124.  An absent review policy is
    projected as required: this is a conservative read meaning (unproven work
    may not bypass review), not a claim that a historical review occurred.
    """

    version = str(payload.get("schemaVersion") or "")
    if version == _ROOT_EXECUTION_V2:
        validate_contract(payload, "room-root-execution.v2.json")
        result = dict(payload)
        legacy_owner = _required_text(result.pop("owner"), "owner")
        result["schemaVersion"] = ROOT_EXECUTION_SCHEMA_VERSION
        result["facilitatorParticipantId"] = _relational_identity(
            facilitator_participant_id,
            fallback=legacy_owner,
            field="facilitatorParticipantId",
        )
        result["reporterParticipantId"] = _relational_nullable_identity(
            reporter_participant_id,
            fallback=None,
            field="reporterParticipantId",
        )
        result["reporterSelectionReceiptId"] = _relational_nullable_identity(
            reporter_selection_receipt_id,
            fallback=None,
            field="reporterSelectionReceiptId",
        )
        result["independentReviewRequired"] = True
    elif version == ROOT_EXECUTION_SCHEMA_VERSION:
        result = dict(payload)
        result["facilitatorParticipantId"] = _relational_identity(
            facilitator_participant_id,
            fallback=result.get("facilitatorParticipantId"),
            field="facilitatorParticipantId",
        )
        result["reporterParticipantId"] = _relational_nullable_identity(
            reporter_participant_id,
            fallback=result.get("reporterParticipantId"),
            field="reporterParticipantId",
        )
        result["reporterSelectionReceiptId"] = _relational_nullable_identity(
            reporter_selection_receipt_id,
            fallback=result.get("reporterSelectionReceiptId"),
            field="reporterSelectionReceiptId",
        )
        review_required = result.get("independentReviewRequired", _UNSET)
        if review_required is _UNSET:
            result["independentReviewRequired"] = True
        elif not isinstance(review_required, bool):
            raise ValueError("independentReviewRequired must be boolean")
    else:
        raise ValueError(f"unsupported Room Root execution version: {version!r}")

    validate_kernel_contract("rootExecution", result)
    return result


def upcast_room_commit(
    payload: Mapping[str, object],
    *,
    root_id: object = None,
    task_id: object = None,
    generation: object = None,
) -> dict[str, object]:
    """Return a current RoomCommit while preserving immutable stored bytes.

    RoomCommit v2 had no quality-gate receipt.  Its current read projection
    therefore receives a deterministic ``not_ready`` receipt with no passing
    evidence.  This keeps every settlement/evidence consumer fail-closed.
    """

    version = str(payload.get("schemaVersion") or "")
    if version == ROOM_COMMIT_SCHEMA_VERSION:
        result = dict(payload)
    elif version in {_ROOM_COMMIT_V2, _ROOM_COMMIT_V3}:
        _validate_legacy_room_commit(
            payload,
            source_version=version,
        )
        result = dict(payload)
        result["schemaVersion"] = ROOM_COMMIT_SCHEMA_VERSION
        continuation = result.get("continuation")
        if isinstance(continuation, Mapping):
            result["continuation"] = _upcast_room_commit_continuation(
                continuation,
                source_version=version,
                commit_id=_required_text(result.get("commitId"), "commitId"),
            )
        if version == _ROOM_COMMIT_V2:
            commit_id = _required_text(result.get("commitId"), "commitId")
            dispatch_id = _required_text(
                result.get("dispatchId"),
                "dispatchId",
            )
            result["qualityGateReceipt"] = {
                "schemaVersion": ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
                "receiptId": f"legacy-read-upcast:{commit_id}:quality-gate",
                "rootId": _required_text(root_id, "root_id"),
                "taskId": _required_text(task_id, "task_id"),
                "dispatchId": dispatch_id,
                "generation": _non_negative_integer(generation, "generation"),
                "originalRequestChecked": False,
                "verdict": "not_ready",
                "items": [],
                "residualRisks": [
                    "Historical RoomCommit v2 has no quality-gate receipt; "
                    "delivery remains unverified."
                ],
                "createdAtMs": _non_negative_integer(
                    result.get("createdAtMs"),
                    "createdAtMs",
                ),
            }
    else:
        raise ValueError(f"unsupported Room Commit version: {version!r}")

    validate_kernel_contract("roomCommit", result)
    return result


def _upcast_room_commit_continuation(
    continuation: Mapping[str, object],
    *,
    source_version: str,
    commit_id: str,
) -> dict[str, object]:
    result = dict(continuation)
    if (
        result.get("decision") == "wait"
        and source_version in {_ROOM_COMMIT_V2, _ROOM_COMMIT_V3}
        and not str(result.get("waitingFor") or "").strip()
    ):
        result.setdefault("waitingFor", "external")
        result.setdefault(
            "resumeCondition",
            "Historical RoomCommit did not persist a wait condition; "
            "explicit recovery is required.",
        )
        return result
    if result.get("decision") != "dispatch":
        return result
    if source_version == _ROOM_COMMIT_V2 and "childTask" not in result:
        # The first v2 writer dispatched another participant on the same Task;
        # a later schema revision added childTask without changing the version.
        # The empty object exists only to satisfy the current wire shape and is
        # never execution authorization.
        result["childTask"] = {}
    if "childTask" not in result:
        return result
    child_dispatch = result.get("childDispatch")
    if not isinstance(child_dispatch, Mapping):
        raise ValueError("legacy child continuation has no child Dispatch")
    target_participant_id = str(
        child_dispatch.get("targetParticipantId") or ""
    ).strip()
    child_dispatch_id = str(child_dispatch.get("dispatchId") or "").strip()
    result["waitingFor"] = "participant"
    result["waitingForParticipantId"] = (
        target_participant_id
        or str(result.get("waitingForParticipantId") or "").strip()
        or f"legacy-unresolved-participant:{commit_id}"
    )
    result["waitingForDispatchId"] = (
        child_dispatch_id
        or str(result.get("waitingForDispatchId") or "").strip()
        or f"legacy-unresolved-dispatch:{commit_id}"
    )
    if not str(result.get("resumeCondition") or "").strip():
        result["resumeCondition"] = (
            "Historical child Dispatch must publish its terminal result."
            if target_participant_id and child_dispatch_id
            else "Historical child Dispatch identity was not persisted; "
            "explicit recovery is required."
        )
    return result


def _validate_legacy_room_commit(
    payload: Mapping[str, object],
    *,
    source_version: str,
) -> None:
    """Validate frozen same-version shapes through a narrow compatibility copy.

    Both v2 and v3 tightened their continuation requirements without changing
    ``schemaVersion``.  Only the two writer-produced shapes below are relaxed;
    every other field is still checked by the retained latest legacy schema.
    """

    candidate = dict(payload)
    continuation = payload.get("continuation")
    if isinstance(continuation, Mapping):
        adapted = dict(continuation)
        keys = set(adapted)
        if (
            source_version == _ROOM_COMMIT_V2
            and adapted.get("decision") == "dispatch"
            and keys <= {"decision", "childDispatch"}
            and isinstance(adapted.get("childDispatch"), Mapping)
        ):
            adapted["childTask"] = {}
        elif (
            source_version == _ROOM_COMMIT_V3
            and adapted.get("decision") == "wait"
            and keys == {"decision"}
        ):
            adapted["waitingFor"] = "external"
            adapted["resumeCondition"] = (
                "Historical RoomCommit did not persist a wait condition; "
                "explicit recovery is required."
            )
        candidate["continuation"] = adapted
    validate_contract(
        candidate,
        (
            "room-commit.v2.json"
            if source_version == _ROOM_COMMIT_V2
            else "room-commit.v3.json"
        ),
    )


def _relational_identity(value: object, *, fallback: object, field: str) -> str:
    if value is not _UNSET:
        return _required_text(value, field)
    return _required_text(fallback, field)


def _relational_nullable_identity(
    value: object,
    *,
    fallback: object,
    field: str,
) -> str | None:
    selected = fallback if value is _UNSET else value
    if selected is None:
        return None
    return _required_text(selected, field)


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value
