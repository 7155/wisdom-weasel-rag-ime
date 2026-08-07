from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewTarget:
    revision: str
    task_ids: tuple[str, ...]
    author_participant_ids: tuple[str, ...]
    repair_participant_ids: tuple[str, ...]
    integration_participant_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewDecision:
    eligible: bool
    reason: str | None


def evaluate_review(
    *,
    target: ReviewTarget,
    reviewer_participant_id: str,
    reviewed_task_ids: tuple[str, ...],
    observed_revision: str,
    unresolved_blocking_findings: int,
) -> ReviewDecision:
    reviewer = str(reviewer_participant_id or "").strip()
    disallowed = {
        *target.author_participant_ids,
        *target.repair_participant_ids,
        *target.integration_participant_ids,
    }
    if not reviewer or not target.author_participant_ids or reviewer in disallowed:
        return ReviewDecision(False, "reviewer_not_independent")
    if not set(target.task_ids).issubset(reviewed_task_ids):
        return ReviewDecision(False, "review_scope_incomplete")
    if not target.revision or observed_revision != target.revision:
        return ReviewDecision(False, "review_target_stale")
    if unresolved_blocking_findings:
        return ReviewDecision(False, "review_findings_unresolved")
    return ReviewDecision(True, None)
