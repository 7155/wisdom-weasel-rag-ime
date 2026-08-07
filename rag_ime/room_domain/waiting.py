from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .model import DomainPolicyError


@dataclass(frozen=True)
class WaitDecision:
    kind: str
    reason: str
    requires_user_action: bool
    participant_id: str = ""
    dispatch_id: str = ""


@dataclass(frozen=True)
class ManagedRetryWaitFacts:
    continuation_decision: str
    waiting_for: str
    child_dispatch_id: str | None
    commit_schema_version: str
    commit_dispatch_id: str
    commit_continuation_decision: str
    commit_waiting_for: str
    parent_dispatch_id: str
    parent_intent_kind: str
    parent_participant_id: str
    facilitator_participant_id: str
    parent_task_id: str
    task_parent_id: str | None
    root_generation: int
    parent_generation: int
    parent_capability_epoch: int
    continuation_created_at_ms: int
    candidates: tuple[Mapping[str, object], ...]


def canonical_wait(
    *,
    waiting_for: str,
    reason: str,
    participant_id: str = "",
    dispatch_id: str = "",
    managed_retry: Mapping[str, object] | None = None,
) -> WaitDecision:
    kind = str(waiting_for or "").strip()
    detail = str(reason or "").strip() or "任务正在安全等待"
    if managed_retry is not None:
        managed_dispatch = str(managed_retry.get("dispatchId") or "").strip()
        managed_participant = str(managed_retry.get("participantId") or "").strip()
        if not managed_dispatch or not managed_participant:
            raise DomainPolicyError("managed retry wait identity is incomplete")
        return WaitDecision(
            kind="participant",
            reason=detail,
            requires_user_action=False,
            participant_id=managed_participant,
            dispatch_id=managed_dispatch,
        )
    if kind == "participant":
        participant = str(participant_id or "").strip()
        dispatch = str(dispatch_id or "").strip()
        if not participant or not dispatch:
            raise DomainPolicyError("participant wait identity is incomplete")
        return WaitDecision(kind, detail, False, participant, dispatch)
    if kind == "user":
        return WaitDecision(kind, detail, True)
    if kind in {"external", "dependency", "retry", "timer", "managed"}:
        return WaitDecision(kind, detail, False)
    raise DomainPolicyError("waiting_for is not a supported wait kind")


def select_active_peer_wait(
    children: Sequence[Mapping[str, object]],
    *,
    facilitator_id: str,
) -> Mapping[str, object] | None:
    for child in children:
        participant_id = str(child.get("targetParticipantId") or "")
        if (
            not participant_id
            or participant_id == facilitator_id
            or child.get("resultPublic") is True
            or str(child.get("intentKind") or "") not in {"execute", "revise"}
            or str(child.get("state") or "")
            in {"committed", "failed", "cancelled", "stale"}
        ):
            continue
        if str(child.get("dispatchId") or ""):
            return child
    return None


def match_managed_retry_wait(
    facts: ManagedRetryWaitFacts,
) -> dict[str, str] | None:
    if (
        facts.continuation_decision != "wait"
        or facts.waiting_for != "external"
        or facts.child_dispatch_id is not None
        or facts.commit_schema_version != "wisdom-weasel.room-commit.v4"
        or facts.commit_dispatch_id != facts.parent_dispatch_id
        or facts.commit_continuation_decision != "wait"
        or facts.commit_waiting_for != "external"
        or facts.task_parent_id is not None
        or facts.parent_participant_id != facts.facilitator_participant_id
        or facts.parent_intent_kind not in {"execute", "resume"}
        or facts.parent_generation != facts.root_generation
    ):
        return None
    matches: list[dict[str, str]] = []
    for candidate in facts.candidates:
        state = str(candidate.get("state") or "")
        task_state = str(candidate.get("taskState") or "")
        terminal = state in {"failed", "cancelled", "unknown"} or (
            state == "committed"
            and task_state in {"completed", "blocked", "failed", "cancelled"}
        )
        if (
            not terminal
            or int(
                candidate["generation"]
                if candidate.get("generation") is not None
                else -1
            )
            != facts.root_generation
            or int(candidate.get("capabilityEpoch") or -1)
            != facts.parent_capability_epoch
            or str(candidate.get("participantId") or "")
            == facts.parent_participant_id
            or str(candidate.get("taskId") or "") == facts.parent_task_id
            or int(candidate.get("createdAtMs") or -1)
            > facts.continuation_created_at_ms
            or int(candidate.get("updatedAtMs") or -1)
            <= facts.continuation_created_at_ms
        ):
            continue
        dispatch_id = str(candidate.get("dispatchId") or "").strip()
        participant_id = str(candidate.get("participantId") or "").strip()
        if dispatch_id and participant_id:
            matches.append({
                "dispatchId": dispatch_id,
                "participantId": participant_id,
            })
    return matches[0] if len(matches) == 1 else None
