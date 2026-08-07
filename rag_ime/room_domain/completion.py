from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionFacts:
    governance_reason: str | None
    active_dispatches: int
    unknown_dispatches: int
    open_outbox: int
    active_leases: int
    open_tasks: int
    acceptance_criteria: tuple[str, ...]
    proven_acceptance_criteria: tuple[str, ...]
    reporter_terminal_ready: bool


@dataclass(frozen=True)
class CompletionDecision:
    ready: bool
    reason: str | None
    missing_acceptance_criteria: tuple[str, ...] = ()


def evaluate_completion(facts: CompletionFacts) -> CompletionDecision:
    if facts.governance_reason:
        return CompletionDecision(False, facts.governance_reason)
    if any((
        facts.active_dispatches,
        facts.unknown_dispatches,
        facts.open_outbox,
        facts.active_leases,
        facts.open_tasks,
    )):
        return CompletionDecision(False, "root_not_quiescent")
    expected = {value for value in facts.acceptance_criteria if value}
    proven = {value for value in facts.proven_acceptance_criteria if value}
    missing = tuple(sorted(expected - proven))
    if not expected or missing:
        return CompletionDecision(False, "acceptance_evidence_missing", missing)
    if not facts.reporter_terminal_ready:
        return CompletionDecision(False, "reporter_terminal_missing")
    return CompletionDecision(True, None)
