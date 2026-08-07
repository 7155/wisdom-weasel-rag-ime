from __future__ import annotations

import unittest

from rag_ime.room_domain.completion import CompletionFacts, evaluate_completion
from rag_ime.room_domain.review import ReviewTarget, evaluate_review
from rag_ime.room_domain.scheduling import (
    DomainPolicyError,
    dependency_ids,
    runnable_frontier,
    validate_task_graph,
)
from rag_ime.room_domain.settlement import SettlementFacts, settle_dispatch
from rag_ime.room_domain.waiting import (
    ManagedRetryWaitFacts,
    canonical_wait,
    match_managed_retry_wait,
    select_active_peer_wait,
)


class RoomWaitingPolicyTests(unittest.TestCase):
    def test_managed_retry_converts_external_wait_to_typed_participant_wait(self) -> None:
        decision = canonical_wait(
            waiting_for="external",
            reason="等待受管重试",
            managed_retry={
                "dispatchId": "dispatch:retry",
                "participantId": "participant:peer",
            },
        )

        self.assertEqual(decision.kind, "participant")
        self.assertEqual(decision.dispatch_id, "dispatch:retry")
        self.assertFalse(decision.requires_user_action)

    def test_managed_retry_match_is_exact_and_stale_attempts_do_not_match(self) -> None:
        base = ManagedRetryWaitFacts(
            continuation_decision="wait",
            waiting_for="external",
            child_dispatch_id=None,
            commit_schema_version="wisdom-weasel.room-commit.v4",
            commit_dispatch_id="dispatch:parent",
            commit_continuation_decision="wait",
            commit_waiting_for="external",
            parent_dispatch_id="dispatch:parent",
            parent_intent_kind="execute",
            parent_participant_id="participant:facilitator",
            facilitator_participant_id="participant:facilitator",
            parent_task_id="task:root",
            task_parent_id=None,
            root_generation=4,
            parent_generation=4,
            parent_capability_epoch=7,
            continuation_created_at_ms=100,
            candidates=(
                {
                    "dispatchId": "dispatch:retry",
                    "participantId": "participant:peer",
                    "taskId": "task:peer",
                    "generation": 4,
                    "capabilityEpoch": 7,
                    "createdAtMs": 90,
                    "updatedAtMs": 110,
                    "state": "committed",
                    "taskState": "completed",
                },
            ),
        )
        self.assertEqual(match_managed_retry_wait(base), {
            "dispatchId": "dispatch:retry",
            "participantId": "participant:peer",
        })
        stale = ManagedRetryWaitFacts(
            **{
                **base.__dict__,
                "candidates": ({**base.candidates[0], "generation": 3},),
            }
        )
        self.assertIsNone(match_managed_retry_wait(stale))

    def test_peer_wait_selection_ignores_settled_and_facilitator_work(self) -> None:
        target = select_active_peer_wait(
            (
                {"dispatchId": "self", "targetParticipantId": "facilitator", "intentKind": "execute", "state": "running"},
                {"dispatchId": "done", "targetParticipantId": "peer-a", "intentKind": "execute", "state": "committed", "resultPublic": True},
                {"dispatchId": "peer", "targetParticipantId": "peer-b", "intentKind": "revise", "state": "running"},
            ),
            facilitator_id="facilitator",
        )
        self.assertEqual(target["dispatchId"], "peer")


class RoomSchedulingPolicyTests(unittest.TestCase):
    def test_dependency_ids_are_unique_non_empty_and_never_self_referential(self) -> None:
        self.assertEqual(
            dependency_ids({"dispatchId": "dispatch:b", "dependsOnDispatchIds": ["dispatch:a"]}),
            ["dispatch:a"],
        )
        for invalid in ([""], ["dispatch:a", "dispatch:a"], ["dispatch:b"]):
            with self.assertRaises(DomainPolicyError):
                dependency_ids({"dispatchId": "dispatch:b", "dependsOnDispatchIds": invalid})

    def test_task_graph_rejects_missing_targets_self_dependencies_and_cycles(self) -> None:
        with self.assertRaises(DomainPolicyError):
            validate_task_graph({"a": ["missing"]})
        with self.assertRaises(DomainPolicyError):
            validate_task_graph({"a": ["a"]})
        with self.assertRaises(DomainPolicyError):
            validate_task_graph({"a": ["b"], "b": ["a"]})

    def test_frontier_is_derived_from_dependencies_in_stable_waves(self) -> None:
        graph = {"a": [], "b": [], "c": ["a", "b"], "d": ["c"]}
        self.assertEqual(runnable_frontier(graph, completed=set()), ["a", "b"])
        self.assertEqual(runnable_frontier(graph, completed={"a", "b"}), ["c"])
        self.assertEqual(runnable_frontier(graph, completed={"a", "b", "c"}), ["d"])


class RoomSettlementPolicyTests(unittest.TestCase):
    def test_identical_settlement_input_produces_the_same_past_tense_event(self) -> None:
        facts = SettlementFacts(
            room_id="room:a",
            root_id="root:a",
            task_id="task:a",
            dispatch_id="dispatch:a",
            generation=2,
            dispatch_state="running",
            task_state="active",
            decision="complete",
            idempotency_key="settle:a",
        )
        first = settle_dispatch(facts)
        second = settle_dispatch(facts)
        self.assertEqual(first, second)
        self.assertEqual(first.event.kind, "dispatch_completed")
        self.assertEqual(first.next_dispatch_state, "committed")

    def test_illegal_or_replayed_settlement_fails_closed(self) -> None:
        with self.assertRaises(DomainPolicyError):
            settle_dispatch(SettlementFacts(
                room_id="room:a", root_id="root:a", task_id="task:a",
                dispatch_id="dispatch:a", generation=1,
                dispatch_state="failed", task_state="failed",
                decision="complete", idempotency_key="settle:a",
            ))


class RoomCompletionAndReviewPolicyTests(unittest.TestCase):
    def test_completion_gate_orders_governance_quiescence_evidence_and_reporter(self) -> None:
        ready = CompletionFacts(
            governance_reason=None,
            active_dispatches=0,
            unknown_dispatches=0,
            open_outbox=0,
            active_leases=0,
            open_tasks=0,
            acceptance_criteria=("criterion:a",),
            proven_acceptance_criteria=("criterion:a",),
            reporter_terminal_ready=True,
        )
        self.assertTrue(evaluate_completion(ready).ready)
        self.assertEqual(
            evaluate_completion(CompletionFacts(**{**ready.__dict__, "open_tasks": 1})).reason,
            "root_not_quiescent",
        )
        self.assertEqual(
            evaluate_completion(CompletionFacts(**{**ready.__dict__, "proven_acceptance_criteria": ()})).reason,
            "acceptance_evidence_missing",
        )
        self.assertEqual(
            evaluate_completion(CompletionFacts(**{**ready.__dict__, "reporter_terminal_ready": False})).reason,
            "reporter_terminal_missing",
        )

    def test_review_eligibility_is_target_scoped_and_provenance_aware(self) -> None:
        target = ReviewTarget(
            revision="sha256:target",
            task_ids=("task:a", "task:b"),
            author_participant_ids=("participant:a",),
            repair_participant_ids=("participant:b",),
            integration_participant_ids=("participant:c",),
        )
        self.assertTrue(evaluate_review(
            target=target,
            reviewer_participant_id="participant:d",
            reviewed_task_ids=("task:a", "task:b"),
            observed_revision="sha256:target",
            unresolved_blocking_findings=0,
        ).eligible)
        for participant_id in ("participant:a", "participant:b", "participant:c"):
            self.assertEqual(evaluate_review(
                target=target,
                reviewer_participant_id=participant_id,
                reviewed_task_ids=("task:a", "task:b"),
                observed_revision="sha256:target",
                unresolved_blocking_findings=0,
            ).reason, "reviewer_not_independent")
        self.assertEqual(evaluate_review(
            target=target,
            reviewer_participant_id="participant:d",
            reviewed_task_ids=("task:a",),
            observed_revision="sha256:target",
            unresolved_blocking_findings=0,
        ).reason, "review_scope_incomplete")
        self.assertEqual(evaluate_review(
            target=target,
            reviewer_participant_id="participant:d",
            reviewed_task_ids=("task:a", "task:b"),
            observed_revision="sha256:late",
            unresolved_blocking_findings=0,
        ).reason, "review_target_stale")


if __name__ == "__main__":
    unittest.main()
