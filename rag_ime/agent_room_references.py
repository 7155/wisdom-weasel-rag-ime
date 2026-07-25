from __future__ import annotations

from collections.abc import Mapping, Sequence


class ParticipantReferenceError(ValueError):
    """A short model-facing participant reference cannot be resolved."""


def participant_ref_map(
    participants: Sequence[object],
) -> dict[str, str]:
    """Map active Room members to stable short refs in Room order."""

    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_participant in participants:
        if not isinstance(raw_participant, Mapping):
            continue
        if str(raw_participant.get("status") or "") != "active":
            continue
        participant_id = str(raw_participant.get("id") or "").strip()
        if not participant_id or participant_id in seen:
            continue
        seen.add(participant_id)
        result[f"P{len(result) + 1}"] = participant_id
    return result


def resolve_participant_ref(
    participant_ref: object,
    refs: Mapping[str, str],
) -> str:
    normalized = str(participant_ref or "").strip().upper()
    participant_id = refs.get(normalized)
    if participant_id is None:
        raise ParticipantReferenceError(
            "participant reference is outside the active Room directory"
        )
    return participant_id


def ref_for_participant(
    participant_id: object,
    refs: Mapping[str, str],
) -> str | None:
    target = str(participant_id or "").strip()
    return next(
        (ref for ref, value in refs.items() if value == target),
        None,
    )
