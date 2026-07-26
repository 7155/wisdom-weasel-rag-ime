from __future__ import annotations

from collections.abc import Mapping

from .contracts.json_schema import validate_contract


ROOT_EXECUTION_SCHEMA_VERSION = "wisdom-weasel.room-root-execution.v2"
ROOM_TASK_SCHEMA_VERSION = "wisdom-weasel.room-task.v2"
DISPATCH_ENVELOPE_SCHEMA_VERSION = "wisdom-weasel.room-dispatch-envelope.v2"
ROOM_COMMIT_SCHEMA_VERSION = "wisdom-weasel.room-commit.v3"
ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION = (
    "wisdom-weasel.room-quality-gate-receipt.v1"
)
EVENT_ENVELOPE_SCHEMA_VERSION = "wisdom-weasel.room-event-envelope.v2"
ROOM_BINDING_SCHEMA_VERSION = "wisdom-weasel.room-binding.v2"
PARTICIPANT_BINDING_SCHEMA_VERSION = "wisdom-weasel.room-participant-binding.v2"
LEGACY_REF_SCHEMA_VERSION = "wisdom-weasel.room-legacy-ref.v1"
KERNEL_COMMAND_SCHEMA_VERSION = "wisdom-weasel.room-kernel-command.v1"
KERNEL_RECEIPT_SCHEMA_VERSION = "wisdom-weasel.room-kernel-receipt.v1"
ROOM_POST_SCHEMA_VERSION = "wisdom-weasel.room-post.v2"
ROOM_SETTLE_RECEIPT_SCHEMA_VERSION = "wisdom-weasel.room-settle-receipt.v1"
ROOM_SETTLE_RESULT_SCHEMA_VERSION = "wisdom-weasel.room-settle-result.v1"
# Default value of the `runtimeProfileRevision` field carried by a dispatch
# envelope. It lives with the other versioned contract identifiers because both
# the application that opens a Root and the domain that builds a continuation
# stamp it; keeping it in the application layer forced the domain to import
# upward for a constant.
DEFAULT_RUNTIME_PROFILE_REVISION = "room-runtime-profile:interactive-v1"

CONTRACT_FILES = {
    "rootExecution": "room-root-execution.v2.json",
    "roomTask": "room-task.v2.json",
    "dispatchEnvelope": "room-dispatch-envelope.v2.json",
    "roomCommit": "room-commit.v3.json",
    "roomQualityGateReceipt": "room-quality-gate-receipt.v1.json",
    "eventEnvelope": "room-event-envelope.v2.json",
    "roomBinding": "room-binding.v2.json",
    "participantBinding": "room-participant-binding.v2.json",
    "legacyRef": "room-legacy-ref.v1.json",
    "kernelCommand": "room-kernel-command.v1.json",
    "kernelReceipt": "room-kernel-receipt.v1.json",
    "roomPost": "room-post.v2.json",
    "roomSettleReceipt": "room-settle-receipt.v1.json",
    "roomSettleResult": "room-settle-result.v1.json",
}


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
