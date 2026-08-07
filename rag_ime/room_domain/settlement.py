from __future__ import annotations

from dataclasses import dataclass

from .events import past_tense_event
from .model import DomainEvent, DomainPolicyError


@dataclass(frozen=True)
class SettlementFacts:
    room_id: str
    root_id: str
    task_id: str
    dispatch_id: str
    generation: int
    dispatch_state: str
    task_state: str
    decision: str
    idempotency_key: str


@dataclass(frozen=True)
class SettlementDecision:
    next_dispatch_state: str
    next_task_state: str
    event: DomainEvent


def settle_dispatch(facts: SettlementFacts) -> SettlementDecision:
    if facts.dispatch_state != "running":
        raise DomainPolicyError("only a running dispatch can settle")
    transitions = {
        "complete": ("committed", "completed", "dispatch_completed"),
        "dispatch": ("committed", "waiting", "dispatch_handed_off"),
        "wait": ("committed", "waiting", "dispatch_waited"),
        "handoff": ("committed", "completed", "dispatch_handed_off"),
        "deliver": ("committed", "completed", "dispatch_delivered"),
        "block": ("committed", "blocked", "dispatch_blocked"),
    }
    transition = transitions.get(str(facts.decision or "").strip())
    if transition is None:
        raise DomainPolicyError("settlement decision is invalid")
    dispatch_state, task_state, event_kind = transition
    return SettlementDecision(
        next_dispatch_state=dispatch_state,
        next_task_state=task_state,
        event=past_tense_event(
            kind=event_kind,
            room_id=facts.room_id,
            root_id=facts.root_id,
            entity_id=facts.dispatch_id,
            generation=facts.generation,
            idempotency_key=facts.idempotency_key,
            payload={
                "taskId": facts.task_id,
                "previousDispatchState": facts.dispatch_state,
                "previousTaskState": facts.task_state,
                "nextDispatchState": dispatch_state,
                "nextTaskState": task_state,
            },
        ),
    )
