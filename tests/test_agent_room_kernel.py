from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path

from rag_ime.agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    kernel_owns_room_execution,
)
from rag_ime.agent_room_context import RoomContextLedgerStore
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.db import latest_migration_version


class RoomKernelCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-kernel-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), latest_migration_version())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def seed(
        self,
        *,
        budget: int = 10,
        max_hops: int = 3,
        max_depth: int = 2,
        criteria: tuple[str, ...] = ("ac:1",),
        independent_review_required: bool = False,
    ) -> None:
        self.store.create_root(
            root("root:1", independent_review_required=independent_review_required),
            budget=budget,
            max_hops=max_hops,
            max_depth=max_depth,
            acceptance_criteria=criteria,
            now_ms=1,
        )
        self.store.create_task(
            task("task:1", criteria=criteria),
            now_ms=2,
        )

    def accept_runtime_attempt(
        self,
        dispatch_id: str,
        *,
        turn_id: str,
        now_ms: int,
    ) -> None:
        lease = self.store.lease_next(
            now_ms=now_ms,
            ttl_ms=30_000,
            dispatch_id=dispatch_id,
        )
        self.assertIsNotNone(lease)
        assert lease is not None
        dispatch_payload = self.store.dispatch(dispatch_id)
        self.store.record_runtime_dispatch_intent(
            dispatch_id,
            now_ms=now_ms,
        )
        self.store.accept_runtime_receipt(
            lease_token=str(lease["leaseToken"]),
            runtime_receipt={
                "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
                "receiptKind": "dispatch_accepted",
                "status": "accepted",
                "rootId": dispatch_payload["rootId"],
                "dispatchId": dispatch_id,
                "generation": dispatch_payload["generation"],
                "turnId": turn_id,
            },
            now_ms=now_ms,
        )

    def test_all_legacy_entries_normalize_to_one_shadow_dispatch(self) -> None:
        shadow = RoomKernelStore(self.db_path, mode="shadow")
        self.seed()
        envelope = dispatch("dispatch:legacy", key="same-semantic-operation")
        binding = {"schemaVersion": "wisdom-weasel.room-binding.v2", "bindingId": "binding:1"}

        created = []
        for ordinal, source_kind in enumerate(("intercom", "work_item", "mention", "wake"), start=1):
            _command, was_created = shadow.normalize_compatibility_entry(
                envelope,
                room_binding_ref=binding,
                source_kind=source_kind,
                source_id=f"legacy:{ordinal}",
                now_ms=10 + ordinal,
            )
            created.append(was_created)

        self.assertEqual(created, [True, False, False, False])
        self.assertEqual(shadow.counts("root:1")["commands"], 1)
        self.assertEqual(shadow.counts("root:1")["dispatches"], 1)
        self.assertEqual(shadow.counts("root:1")["outbox"], 1)
        self.assertIsNone(shadow.lease_next(now_ms=100, ttl_ms=10))

    def test_product_root_and_initial_task_are_created_atomically(self) -> None:
        created = self.store.create_root_with_task(
            root("root:atomic"),
            task("task:atomic", root_id="root:atomic"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("ac:1",),
            now_ms=1,
        )
        self.assertEqual(created["task"]["rootId"], created["root"]["rootId"])
        replayed = self.store.create_root_with_task(
            root("root:atomic"),
            task("task:atomic", root_id="root:atomic"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("ac:1",),
            now_ms=2,
        )
        self.assertEqual(replayed, created)

        with self.assertRaises(Exception):
            self.store.create_root_with_task(
                root("root:rollback"),
                task("task:atomic", root_id="root:rollback"),
                budget=10,
                max_hops=3,
                max_depth=2,
                acceptance_criteria=("ac:1",),
                now_ms=2,
            )
        with self.assertRaises(KeyError):
            self.store.root("root:rollback")

    def test_multi_participant_dispatch_batch_is_atomic(self) -> None:
        self.seed(budget=2)
        self.store.create_task(
            child_task(
                "task:batch:b",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=3,
        )
        first = dispatch(
            "dispatch:batch:a",
            key="batch:a",
            target="participant:a",
        )
        second = dispatch(
            "dispatch:batch:b",
            key="batch:b",
            target="participant:b",
            task_id="task:batch:b",
        )

        queued = self.store.enqueue_dispatches((first, second), now_ms=10)

        self.assertEqual(
            [item["dispatchId"] for item, _created in queued],
            ["dispatch:batch:a", "dispatch:batch:b"],
        )
        self.assertTrue(all(created for _item, created in queued))
        self.assertEqual(self.store.counts("root:1")["dispatches"], 2)

    def test_invalid_member_rolls_back_complete_dispatch_batch(self) -> None:
        self.seed(budget=1)
        first = dispatch(
            "dispatch:batch:rollback:a",
            key="batch:rollback:a",
            target="participant:a",
        )
        second = dispatch(
            "dispatch:batch:rollback:b",
            key="batch:rollback:b",
            target="participant:b",
        )

        with self.assertRaisesRegex(RoomKernelFenceError, "budget exhausted"):
            self.store.enqueue_dispatches((first, second), now_ms=10)

        self.assertEqual(self.store.counts("root:1")["dispatches"], 0)
        with self.assertRaises(KeyError):
            self.store.dispatch("dispatch:batch:rollback:a")

    def test_target_session_dispatches_queue_and_lease_serially(self) -> None:
        self.seed(budget=3, criteria=())
        for task_id in ("task:target-session:first", "task:target-session:second"):
            self.store.create_task(
                child_task(
                    task_id,
                    parent="task:1",
                    target="participant:a",
                ),
                now_ms=9,
            )
        first, created = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:target-session:first",
                key="target-session:first",
                target="participant:a",
                task_id="task:target-session:first",
            ),
            now_ms=10,
        )
        second, second_created = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:target-session:second",
                key="target-session:second",
                target="participant:a",
                task_id="task:target-session:second",
            ),
            now_ms=11,
        )

        first_lease = self.store.lease_next(now_ms=12, ttl_ms=30_000)
        self.assertIsNotNone(first_lease)
        assert first_lease is not None
        self.assertEqual(first_lease["dispatchId"], first["dispatchId"])
        self.assertIsNone(
            self.store.lease_next(
                now_ms=13,
                ttl_ms=30_000,
                dispatch_id=second["dispatchId"],
            )
        )

        self.store.set_dispatch_wait_state(
            first["dispatchId"],
            "running",
            now_ms=14,
        )
        self.store.apply_commit(
            commit(
                "commit:target-session:first",
                first["dispatchId"],
                task_id="task:target-session:first",
            ),
            generation=0,
            now_ms=15,
        )
        second_lease = self.store.lease_next(now_ms=16, ttl_ms=30_000)
        self.assertIsNotNone(second_lease)
        assert second_lease is not None
        self.assertEqual(second_lease["dispatchId"], second["dispatchId"])

        replay, replay_created = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:target-session:first",
                key="target-session:first",
                target="participant:a",
                task_id="task:target-session:first",
            ),
            now_ms=17,
        )
        self.assertTrue(created)
        self.assertTrue(second_created)
        self.assertFalse(replay_created)
        self.assertEqual(replay["dispatchId"], first["dispatchId"])
        self.assertEqual(self.store.counts("root:1")["dispatches"], 2)

    def test_multi_member_chain_is_bounded_by_hop_and_depth_fences(self) -> None:
        self.seed(max_hops=2, max_depth=1)
        self.store.create_task(
            child_task(
                "task:chain:b",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=3,
        )
        self.store.create_task(
            child_task(
                "task:chain:c",
                parent="task:chain:b",
                target="participant:c",
            ),
            now_ms=4,
        )
        first, _ = self.store.enqueue_dispatch(
            dispatch("dispatch:a1", key="a1", target="participant:a", hop=0), now_ms=10
        )
        second, _ = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:b",
                key="b",
                target="participant:b",
                hop=1,
                depth=1,
                parent=str(first["dispatchId"]),
                task_id="task:chain:b",
            ),
            now_ms=11,
        )
        third, _ = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:a2",
                key="a2",
                target="participant:c",
                hop=2,
                depth=1,
                parent=str(second["dispatchId"]),
                task_id="task:chain:c",
            ),
            now_ms=12,
        )
        self.assertEqual(third["hopCount"], 2)
        with self.assertRaisesRegex(RoomKernelFenceError, "hop limit"):
            self.store.enqueue_dispatch(
                dispatch(
                    "dispatch:b2",
                    key="b2",
                    target="participant:d",
                    hop=3,
                    depth=1,
                    parent="dispatch:a2",
                ),
                now_ms=13,
            )

    def test_dispatch_commit_atomically_transfers_one_task_a_to_b_to_a(self) -> None:
        self.seed(max_hops=3)
        first, _ = self.store.enqueue_dispatch(
            dispatch("dispatch:a1", key="a1", target="participant:a"),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state("dispatch:a1", "running", now_ms=11)
        child_b = dispatch(
            "dispatch:b1",
            key="b1",
            target="participant:b",
            hop=1,
            parent=str(first["dispatchId"]),
        )
        first_commit = {
            **commit(
                "commit:a-to-b",
                "dispatch:a1",
                coverage=("ac:1",),
            ),
            "action": "dispatch",
            "continuation": {
                "decision": "dispatch",
                "taskTransfer": task_transfer(
                    from_participant="participant:a",
                    to_participant="participant:b",
                    ownership_revision=1,
                ),
                "childDispatch": child_b,
            },
        }

        receipt = self.store.apply_commit(first_commit, generation=0, now_ms=12)

        self.assertEqual(receipt["details"]["transferredTaskId"], "task:1")
        self.assertIsNotNone(receipt["details"]["ownershipReceiptId"])
        self.assertEqual(self.store.dispatch("dispatch:b1")["state"], "pending")
        continuation = self.store.continuation("commit:a-to-b")
        self.assertEqual(continuation["decision"], "dispatch")
        self.assertEqual(continuation["transferredTaskId"], "task:1")
        transferred = self.store.task("task:1")
        self.assertEqual(
            transferred["currentOwnerParticipantId"],
            "participant:b",
        )
        self.assertEqual(transferred["ownershipRevision"], 1)
        self.assertEqual(
            transferred["ownershipReceiptId"],
            receipt["details"]["ownershipReceiptId"],
        )
        self.store.set_dispatch_wait_state("dispatch:b1", "running", now_ms=13)
        child_a = dispatch(
            "dispatch:a2",
            key="a2",
            target="participant:a",
            hop=2,
            parent="dispatch:b1",
        )
        second_commit = {
            **commit(
                "commit:b-to-a",
                "dispatch:b1",
                coverage=("ac:1",),
            ),
            "action": "dispatch",
            "continuation": {
                "decision": "dispatch",
                "taskTransfer": task_transfer(
                    from_participant="participant:b",
                    to_participant="participant:a",
                    ownership_revision=2,
                ),
                "childDispatch": child_a,
            },
        }
        self.store.apply_commit(second_commit, generation=0, now_ms=14)
        self.assertEqual(
            self.store.dispatch("dispatch:a2")["parentDispatchId"],
            "dispatch:b1",
        )
        self.assertEqual(self.store.counts("root:1")["tasks"], 1)
        transferred_back = self.store.task("task:1")
        self.assertEqual(
            transferred_back["currentOwnerParticipantId"],
            "participant:a",
        )
        self.assertEqual(transferred_back["ownershipRevision"], 2)
        self.assertEqual(transferred_back["state"], "active")

    def test_reviewer_revision_dispatch_marks_review_changes_requested(
        self,
    ) -> None:
        self.seed(max_hops=3, max_depth=2)
        review_task = {
            **child_task(
                "task:review",
                parent="task:1",
                target="participant:b",
                criteria=("ac:1",),
            ),
            "taskKind": "review",
            "reviewState": "required",
            "reviewOfTaskIds": ["task:1"],
            "reviewAuthorParticipantIds": ["participant:a"],
            "acceptanceCriterionIds": ["ac:1"],
        }
        self.store.create_task(review_task, now_ms=3)
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:review",
                key="review",
                target="participant:b",
                depth=1,
                task_id="task:review",
            ),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:review",
            "running",
            now_ms=11,
        )
        revision_task = child_task(
            "task:revision",
            parent="task:review",
            target="participant:a",
            criteria=(),
        )
        revision_dispatch = {
            **dispatch(
                "dispatch:revision",
                key="revision",
                target="participant:a",
                hop=1,
                depth=2,
                parent="dispatch:review",
                task_id="task:revision",
            ),
            "intentKind": "revise",
        }
        self.store.apply_commit(
            {
                **commit(
                    "commit:review-revision",
                    "dispatch:review",
                    coverage=("ac:1",),
                    task_id="task:review",
                ),
                "action": "dispatch",
                "continuation": {
                    "decision": "dispatch",
                    "childTask": revision_task,
                    "childDispatch": revision_dispatch,
                    "waitingFor": "participant",
                    "waitingForParticipantId": "participant:a",
                    "waitingForDispatchId": "dispatch:revision",
                    "resumeCondition": "Facilitator completes the requested revision.",
                },
            },
            generation=0,
            now_ms=12,
        )

        review = self.store.task("task:review")
        self.assertEqual(review["reviewState"], "changes_requested")
        self.assertEqual(review["state"], "waiting")

    def test_task_transfer_cancels_racing_old_owner_dispatch(self) -> None:
        self.seed(max_hops=3)
        self.store.enqueue_dispatches(
            (
                dispatch(
                    "dispatch:a-source",
                    key="a-source",
                    target="participant:a",
                    session_id="session:a-source",
                ),
                dispatch(
                    "dispatch:a-stale",
                    key="a-stale",
                    target="participant:a",
                    session_id="session:a-stale",
                ),
            ),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:a-source",
            "running",
            now_ms=11,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:a-stale",
            "running",
            now_ms=11,
        )
        transfer_commit = {
            **commit(
                "commit:a-source",
                "dispatch:a-source",
                coverage=("ac:1",),
            ),
            "action": "dispatch",
            "continuation": {
                "decision": "dispatch",
                "taskTransfer": task_transfer(
                    from_participant="participant:a",
                    to_participant="participant:b",
                    ownership_revision=1,
                ),
                "childDispatch": dispatch(
                    "dispatch:b-owner",
                    key="b-owner",
                    target="participant:b",
                    session_id="session:b-owner",
                    hop=1,
                    parent="dispatch:a-source",
                ),
            },
        }

        receipt = self.store.apply_commit(
            transfer_commit,
            generation=0,
            now_ms=12,
        )

        ownership_receipt = self.store.receipt(
            str(receipt["details"]["ownershipReceiptId"])
        )
        self.assertEqual(
            ownership_receipt["details"]["supersededDispatchIds"],
            ["dispatch:a-stale"],
        )
        self.assertEqual(
            self.store.dispatch("dispatch:a-stale")["state"],
            "cancelled",
        )
        self.assertEqual(
            self.store.dispatch("dispatch:b-owner")["state"],
            "pending",
        )
        stale = self.store.apply_commit(
            commit(
                "commit:a-stale",
                "dispatch:a-stale",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=13,
        )
        self.assertEqual(stale["status"], "rejected")
        self.assertEqual(stale["details"]["reason"], "dispatch_not_running")
        self.assertEqual(
            self.store.task("task:1")["currentOwnerParticipantId"],
            "participant:b",
        )

    def test_close_barrier_waits_for_peer_public_result(self) -> None:
        self.seed(max_hops=3)
        self.store.create_task(
            child_task(
                "task:peer",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=3,
        )
        first, peer = self.store.enqueue_dispatches(
            (
                dispatch(
                    "dispatch:closer-parent",
                    key="closer-parent",
                    target="participant:a",
                ),
                dispatch(
                    "dispatch:peer",
                    key="peer",
                    target="participant:b",
                    task_id="task:peer",
                ),
            ),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:closer-parent",
            "running",
            now_ms=11,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:peer",
            "running",
            now_ms=11,
        )
        self.assertEqual(
            self.store.close_barrier_dispatch_ids(
                "dispatch:closer-parent"
            ),
            ["dispatch:peer"],
        )
        closing_dispatch = dispatch(
            "dispatch:closer",
            key="closer",
            target="participant:c",
            hop=1,
            parent=str(first[0]["dispatchId"]),
        )
        closing_commit = {
            **commit(
                "commit:closer-parent",
                "dispatch:closer-parent",
                coverage=("ac:1",),
            ),
            "action": "post",
            "postProposal": post_proposal(
                "commit:closer-parent",
                "dispatch:closer-parent",
                task_id="task:1",
                author="participant:a",
            ),
            "continuation": {
                "decision": "dispatch",
                "taskTransfer": task_transfer(
                    from_participant="participant:a",
                    to_participant="participant:c",
                    ownership_revision=1,
                ),
                "childDispatch": closing_dispatch,
                "waitForDispatchIds": [str(peer[0]["dispatchId"])],
            },
        }
        self.store.apply_commit(
            closing_commit,
            generation=0,
            now_ms=12,
            post_proposal=closing_commit["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            closing_commit["postProposal"]
        )
        self.assertIsNone(self.store.pending_dispatch(now_ms=13))

        peer_commit = {
            **commit(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
            ),
            "action": "post",
            "postProposal": post_proposal(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
                author="participant:b",
            ),
            "continuation": {"decision": "complete"},
        }
        self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=14,
            post_proposal=peer_commit["postProposal"],
        )
        self.assertIsNone(self.store.pending_dispatch(now_ms=15))

        RoomContextLedgerStore(self.db_path).publish_post(
            peer_commit["postProposal"]
        )
        ready = self.store.pending_dispatch(now_ms=16)
        self.assertIsNotNone(ready)
        self.assertEqual(ready["dispatchId"], "dispatch:closer")

    def test_participant_wait_resumes_once_after_exact_result_is_public(
        self,
    ) -> None:
        self.seed(max_hops=3, criteria=())
        self.store.create_task(
            child_task(
                "task:peer",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=3,
        )
        self.store.enqueue_dispatches(
            (
                dispatch(
                    "dispatch:waiter",
                    key="waiter",
                    target="participant:a",
                ),
                dispatch(
                    "dispatch:peer",
                    key="peer",
                    target="participant:b",
                    task_id="task:peer",
                ),
            ),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:waiter",
            "running",
            now_ms=11,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:peer",
            "running",
            now_ms=11,
        )
        waiting = wait_commit(
            "commit:waiter",
            "dispatch:waiter",
            dependency_id="dispatch:peer",
        )
        self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=12,
            post_proposal=waiting["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            waiting["postProposal"]
        )
        self.assertEqual(self.store.root("root:1")["state"], "waiting")

        peer_commit = {
            **commit(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
            ),
            "action": "post",
            "postProposal": post_proposal(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
                author="participant:b",
            ),
            "continuation": {"decision": "complete"},
        }
        receipt = self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=13,
            post_proposal=peer_commit["postProposal"],
        )
        resumed = receipt["details"]["resumedDispatchIds"]
        self.assertEqual(len(resumed), 1)
        resume_dispatch_id = resumed[0]
        self.assertEqual(
            self.store.continuation("commit:waiter")[
                "childDispatchId"
            ],
            resume_dispatch_id,
        )
        self.assertEqual(self.store.task("task:1")["state"], "active")
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertIsNone(self.store.pending_dispatch(now_ms=14))

        RoomContextLedgerStore(self.db_path).publish_post(
            peer_commit["postProposal"]
        )
        ready = self.store.pending_dispatch(now_ms=15)
        self.assertIsNotNone(ready)
        self.assertEqual(ready["dispatchId"], resume_dispatch_id)
        replay = self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=16,
            post_proposal=peer_commit["postProposal"],
        )
        self.assertEqual(replay["status"], "noop")
        self.assertEqual(self.store.counts("root:1")["dispatches"], 3)

    def test_already_finished_participant_waits_for_own_post_before_resume(
        self,
    ) -> None:
        self.seed(max_hops=3, criteria=())
        self.store.create_task(
            child_task(
                "task:peer",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=3,
        )
        self.store.enqueue_dispatches(
            (
                dispatch(
                    "dispatch:waiter",
                    key="waiter",
                    target="participant:a",
                ),
                dispatch(
                    "dispatch:peer",
                    key="peer",
                    target="participant:b",
                    task_id="task:peer",
                ),
            ),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:waiter",
            "running",
            now_ms=11,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:peer",
            "running",
            now_ms=11,
        )
        peer_commit = {
            **commit(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
            ),
            "action": "post",
            "postProposal": post_proposal(
                "commit:peer",
                "dispatch:peer",
                task_id="task:peer",
                author="participant:b",
            ),
            "continuation": {"decision": "complete"},
        }
        self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=12,
            post_proposal=peer_commit["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            peer_commit["postProposal"]
        )

        waiting = wait_commit(
            "commit:waiter",
            "dispatch:waiter",
            dependency_id="dispatch:peer",
        )
        receipt = self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=13,
            post_proposal=waiting["postProposal"],
        )
        resume_dispatch_id = receipt["details"]["resumedDispatchIds"][0]
        self.assertIsNone(self.store.pending_dispatch(now_ms=14))

        RoomContextLedgerStore(self.db_path).publish_post(
            waiting["postProposal"]
        )
        ready = self.store.pending_dispatch(now_ms=15)
        self.assertIsNotNone(ready)
        self.assertEqual(ready["dispatchId"], resume_dispatch_id)

    def test_fifteen_agent_mentions_are_stopped_by_system_hop_ceiling(self) -> None:
        self.seed(budget=100, max_hops=12, max_depth=4)
        first, _ = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:hop-0",
                key="hop-0",
                target="participant:a",
            ),
            now_ms=10,
        )
        parent = str(first["dispatchId"])
        from_participant = "participant:a"
        for hop in range(1, 13):
            self.store.set_dispatch_wait_state(parent, "running", now_ms=10 + hop)
            to_participant = f"participant:{hop % 15}"
            child = dispatch(
                f"dispatch:hop-{hop}",
                key=f"hop-{hop}",
                target=to_participant,
                hop=hop,
                parent=parent,
            )
            self.store.apply_commit(
                {
                    **commit(
                        f"commit:hop-{hop - 1}",
                        parent,
                        coverage=("ac:1",),
                    ),
                    "action": "dispatch",
                    "continuation": {
                        "decision": "dispatch",
                        "taskTransfer": task_transfer(
                            from_participant=from_participant,
                            to_participant=to_participant,
                            ownership_revision=hop,
                        ),
                        "childDispatch": child,
                    },
                },
                generation=0,
                now_ms=11 + hop,
            )
            parent = str(child["dispatchId"])
            from_participant = to_participant
        self.store.set_dispatch_wait_state(parent, "running", now_ms=29)
        with self.assertRaisesRegex(RoomKernelFenceError, "hop limit"):
            child = dispatch(
                "dispatch:hop-13",
                key="hop-13",
                target="participant:13",
                hop=13,
                parent=parent,
            )
            self.store.apply_commit(
                {
                    **commit(
                        "commit:hop-12",
                        parent,
                        coverage=("ac:1",),
                    ),
                    "action": "dispatch",
                    "continuation": {
                        "decision": "dispatch",
                        "taskTransfer": task_transfer(
                            from_participant=from_participant,
                            to_participant="participant:13",
                            ownership_revision=13,
                        ),
                        "childDispatch": child,
                    },
                },
                generation=0,
                now_ms=30,
            )

    def test_missing_commit_retries_are_bounded_then_block_root(self) -> None:
        self.seed(criteria=())
        self.store.enqueue_dispatch(dispatch("dispatch:settle", key="settle"), now_ms=10)
        self.accept_runtime_attempt(
            "dispatch:settle",
            turn_id="turn:settle",
            now_ms=11,
        )

        first = self.store.record_uncommitted_settle(
            "dispatch:settle", generation=0,
            runtime_turn_id="turn:settle", dispatch_attempt=0,
            now_ms=12, max_attempts=3,
        )
        second = self.store.record_uncommitted_settle(
            "dispatch:settle", generation=0,
            runtime_turn_id="turn:settle", dispatch_attempt=0,
            now_ms=13, max_attempts=3,
        )
        third = self.store.record_uncommitted_settle(
            "dispatch:settle", generation=0,
            runtime_turn_id="turn:settle", dispatch_attempt=0,
            now_ms=14, max_attempts=3,
        )

        self.assertEqual(first["receiptKind"], "settle_retry_required")
        self.assertEqual(second["details"]["attempt"], 2)
        self.assertEqual(third["receiptKind"], "settle_blocked")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(self.store.task("task:1")["state"], "blocked")

    def test_runtime_failure_is_idempotent_and_blocks_the_dispatch(self) -> None:
        self.seed(criteria=())
        self.store.enqueue_dispatch(
            dispatch("dispatch:runtime-failure", key="runtime-failure"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            "dispatch:runtime-failure",
            turn_id="turn:runtime-failure",
            now_ms=11,
        )

        first = self.store.record_runtime_failure(
            "dispatch:runtime-failure",
            generation=0,
            source_event_id="event:turn-failed",
            runtime_turn_id="turn:runtime-failure",
            dispatch_attempt=0,
            now_ms=12,
        )
        replay = self.store.record_runtime_failure(
            "dispatch:runtime-failure",
            generation=0,
            source_event_id="event:turn-failed",
            runtime_turn_id="turn:runtime-failure",
            dispatch_attempt=0,
            now_ms=12,
        )

        self.assertEqual(first, replay)
        self.assertEqual(first["receiptKind"], "runtime_failed")
        self.assertEqual(first["status"], "applied")
        self.assertEqual(first["details"]["reasonCode"], "runtime_turn_failed")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(self.store.task("task:1")["state"], "blocked")
        self.assertEqual(
            self.store.dispatch("dispatch:runtime-failure")["state"],
            "failed",
        )
        self.assertEqual(
            self.store.outbox("dispatch:runtime-failure")["state"],
            "dead_letter",
        )
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)
        with sqlite3.connect(self.db_path) as connection:
            runtime_state = connection.execute(
                """
                SELECT state FROM room_kernel_runtime_effects
                WHERE dispatch_id = ?
                """,
                ("dispatch:runtime-failure",),
            ).fetchone()[0]
        self.assertEqual(runtime_state, "failed")
        self.assertEqual(
            self.store.abort_scope("dispatch:runtime-failure")["state"],
            "failed",
        )

    def test_transient_runtime_failure_without_tools_uses_root_retry_budget(
        self,
    ) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:runtime-retry"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="runtime-retry"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:runtime-retry:1",
            now_ms=11,
        )

        first = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:transport-failed",
            runtime_turn_id="turn:runtime-retry:1",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=False,
            reason_code="provider_transport_failure",
        )
        replay = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:transport-failed",
            runtime_turn_id="turn:runtime-retry:1",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=False,
            reason_code="provider_transport_failure",
        )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "active runtime turn",
        ):
            self.store.record_runtime_failure(
                dispatch_id,
                generation=0,
                source_event_id="event:late-transport-failed",
                runtime_turn_id="turn:runtime-retry:1",
                dispatch_attempt=0,
                now_ms=13,
                retryable=True,
                had_tool_activity=False,
                reason_code="provider_transport_failure",
            )

        self.assertEqual(first, replay)
        self.assertEqual(first["receiptKind"], "runtime_retry_scheduled")
        self.assertEqual(first["status"], "applied")
        self.assertEqual(first["details"]["attempt"], 1)
        self.assertEqual(first["details"]["availableAtMs"], 1_012)
        self.assertTrue(
            self.store.is_managed_runtime_turn(
                "session:participant:a",
                "turn:runtime-retry:1",
            )
        )
        self.assertFalse(
            self.store.is_managed_runtime_turn(
                "session:participant:a",
                "turn:ordinary",
            )
        )
        self.assertFalse(
            self.store.is_managed_runtime_turn(
                "session:participant:b",
                "turn:runtime-retry:1",
            )
        )
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertEqual(self.store.task("task:1")["state"], "active")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "retry_wait")
        self.assertEqual(self.store.outbox(dispatch_id)["state"], "retry_wait")
        self.assertEqual(self.store.resource_limits("root:1")["retry_used"], 1)
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 0)
        self.assertIsNone(self.store.pending_dispatch(now_ms=1_011))
        ready = self.store.pending_dispatch(now_ms=1_012)
        self.assertIsNotNone(ready)
        self.assertEqual(ready["dispatchId"], dispatch_id)
        self.assertEqual(ready["state"], "retry_wait")
        self.assertEqual(ready["attempt"], 1)
        self.assertEqual(
            self.store.outbox(dispatch_id)["payload"]["attempt"],
            1,
        )

    def test_transient_runtime_failure_after_tool_activity_stays_fail_closed(
        self,
    ) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:runtime-tool-failure"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="runtime-tool-failure"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:runtime-tool-failure",
            now_ms=11,
        )

        receipt = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:tool-then-transport-failed",
            runtime_turn_id="turn:runtime-tool-failure",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=True,
            reason_code="tool_activity_observed",
        )

        self.assertEqual(receipt["receiptKind"], "runtime_failed")
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "failed")
        self.assertEqual(self.store.resource_limits("root:1")["retry_used"], 0)
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)

    def test_missing_commit_retries_despite_tool_activity_then_blocks(
        self,
    ) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:missing-commit"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="missing-commit"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:missing-commit:1",
            now_ms=11,
        )

        retry = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:missing-commit:1",
            runtime_turn_id="turn:missing-commit:1",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=True,
            reason_code="room_commit_missing",
        )
        self.assertEqual(retry["receiptKind"], "runtime_retry_scheduled")
        self.assertEqual(retry["details"]["reasonCode"], "room_commit_missing")
        self.assertTrue(retry["details"]["hadToolActivity"])

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """UPDATE room_kernel_root_limits
                   SET retry_limit=1 WHERE root_id='root:1'"""
            )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:missing-commit:2",
            now_ms=1_012,
        )
        blocked = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:missing-commit:2",
            runtime_turn_id="turn:missing-commit:2",
            dispatch_attempt=1,
            now_ms=1_013,
            retryable=True,
            had_tool_activity=True,
            reason_code="room_commit_missing",
        )

        self.assertEqual(blocked["receiptKind"], "runtime_failed")
        self.assertEqual(blocked["details"]["reasonCode"], "room_commit_missing")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "failed")
        with sqlite3.connect(self.db_path) as connection:
            reason = connection.execute(
                """SELECT reason_code FROM room_kernel_dead_letters
                   WHERE dispatch_id=?""",
                (dispatch_id,),
            ).fetchone()[0]
        self.assertEqual(reason, "room_commit_missing")


    def test_budget_is_reserved_at_enqueue_and_released_by_cancel(self) -> None:
        self.seed(budget=10, criteria=())
        self.store.enqueue_dispatch(dispatch("dispatch:seven", key="seven", cost=7), now_ms=10)
        self.assertEqual(self.store.root("root:1")["budgetReserved"], 7)
        with self.assertRaisesRegex(RoomKernelFenceError, "budget exhausted"):
            self.store.enqueue_dispatch(dispatch("dispatch:four", key="four", cost=4), now_ms=11)

        self.store.cancel_target(
            root_id="root:1", target_kind="dispatch", target_id="dispatch:seven", now_ms=12
        )
        self.assertEqual(self.store.root("root:1")["budgetReserved"], 0)
        _created, was_created = self.store.enqueue_dispatch(
            dispatch("dispatch:four", key="four", cost=4), now_ms=13
        )
        self.assertTrue(was_created)

    def test_hard_resource_limits_reserve_atomically_and_release_on_cancel(self) -> None:
        self.seed(budget=100, criteria=())
        for index in range(4):
            self.store.enqueue_dispatch(
                dispatch(
                    f"dispatch:parallel-{index}",
                    key=f"parallel-{index}",
                    target="participant:a",
                    session_id=f"session:parallel:{index}",
                ),
                now_ms=10 + index,
            )
        with self.assertRaisesRegex(RoomKernelFenceError, "concurrency limit"):
            self.store.enqueue_dispatch(
                dispatch(
                    "dispatch:parallel-4",
                    key="parallel-4",
                    target="participant:a",
                    session_id="session:parallel:4",
                ),
                now_ms=20,
            )

        self.store.cancel_target(
            root_id="root:1", target_kind="dispatch",
            target_id="dispatch:parallel-0", now_ms=21,
        )
        _item, created = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:parallel-4",
                key="parallel-4",
                target="participant:a",
                session_id="session:parallel:4",
            ),
            now_ms=22,
        )
        self.assertTrue(created)
        limits = self.store.resource_limits("root:1")
        self.assertEqual(limits["concurrency_reserved"], 4)
        self.assertEqual(limits["dispatch_reserved"], 4)

    def test_dependency_blocked_dispatch_defers_concurrency_until_ready(self) -> None:
        self.seed(budget=100, criteria=())
        for index in range(4):
            alignment = dispatch(
                f"dispatch:alignment-{index}",
                key=f"alignment-{index}",
                target="participant:a",
                session_id=f"session:alignment:{index}",
            )
            alignment["intentKind"] = "align"
            self.store.enqueue_dispatch(
                alignment,
                now_ms=10 + index,
            )
        execution = dispatch(
            "dispatch:execution",
            key="execution",
            target="participant:a",
            session_id="session:execution",
        )
        execution["dependsOnDispatchIds"] = ["dispatch:alignment-0"]

        queued, created = self.store.enqueue_dispatch(execution, now_ms=20)

        self.assertTrue(created)
        self.assertEqual(queued["dispatchId"], "dispatch:execution")
        limits = self.store.resource_limits("root:1")
        self.assertEqual(limits["concurrency_reserved"], 4)
        self.assertEqual(limits["dispatch_reserved"], 5)
        self.assertIsNone(
            self.store.lease_next(
                now_ms=21,
                ttl_ms=30_000,
                dispatch_id="dispatch:execution",
            )
        )

        self.accept_runtime_attempt(
            "dispatch:alignment-0",
            turn_id="turn:alignment-0",
            now_ms=22,
        )
        alignment_commit = {
            **commit("commit:alignment-0", "dispatch:alignment-0"),
            "action": "post",
            "postProposal": post_proposal(
                "commit:alignment-0",
                "dispatch:alignment-0",
                task_id="task:1",
                author="participant:a",
            ),
            "continuation": {"decision": "complete"},
        }
        self.store.apply_commit(
            alignment_commit,
            generation=0,
            now_ms=23,
            post_proposal=alignment_commit["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            alignment_commit["postProposal"]
        )
        self.assertEqual(
            self.store.resource_limits("root:1")["concurrency_reserved"],
            3,
        )
        lease = self.store.lease_next(
            now_ms=24,
            ttl_ms=30_000,
            dispatch_id="dispatch:execution",
        )
        self.assertIsNotNone(lease)
        self.assertEqual(
            self.store.resource_limits("root:1")["concurrency_reserved"],
            4,
        )

    def test_resource_usage_consumes_actuals_without_overselling_other_reservations(self) -> None:
        self.seed(budget=20, criteria=())
        self.store.enqueue_dispatch(dispatch("dispatch:usage", key="usage"), now_ms=10)
        self.store.set_dispatch_wait_state("dispatch:usage", "running", now_ms=11)
        self.store.apply_commit(
            commit("commit:usage", "dispatch:usage"), generation=0, now_ms=12,
            resource_usage={
                "inputTokens": 1200, "outputTokens": 300, "toolCalls": 2,
                "toolCost": 40, "retryCount": 1, "repairCount": 0,
            },
        )
        limits = self.store.resource_limits("root:1")
        self.assertEqual(limits["dispatch_used"], 1)
        self.assertEqual(limits["dispatch_reserved"], 0)
        self.assertEqual(limits["input_token_used"], 1200)
        self.assertEqual(limits["tool_call_used"], 2)

    def test_kernel_rejects_missing_or_forged_quality_gate_receipts(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(
            dispatch("dispatch:quality", key="quality"),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:quality",
            "running",
            now_ms=11,
        )
        missing = commit(
            "commit:quality-missing",
            "dispatch:quality",
            coverage=("ac:1",),
        )
        del missing["qualityGateReceipt"]
        with self.assertRaisesRegex(ValueError, "qualityGateReceipt"):
            self.store.apply_commit(
                missing,
                generation=0,
                now_ms=12,
            )

        forged = commit(
            "commit:quality-forged",
            "dispatch:quality",
            coverage=("ac:1",),
        )
        forged["qualityGateReceipt"]["taskId"] = "task:other"
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "does not match the committing Dispatch",
        ):
            self.store.apply_commit(
                forged,
                generation=0,
                now_ms=13,
            )
        self.assertEqual(
            self.store.counts("root:1")["commits"],
            0,
        )

    def test_deadline_and_dispatch_count_are_kernel_owned_hard_limits(self) -> None:
        self.seed(budget=100, criteria=())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_root_limits SET dispatch_limit=1 WHERE root_id='root:1'"
            )
        self.store.enqueue_dispatch(dispatch("dispatch:first", key="first"), now_ms=10)
        with self.assertRaisesRegex(RoomKernelFenceError, "dispatch limit"):
            self.store.enqueue_dispatch(
                dispatch(
                    "dispatch:second",
                    key="second",
                    target="participant:a",
                    session_id="session:dispatch:second",
                ),
                now_ms=11,
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_root_limits SET deadline_at_ms=12 WHERE root_id='root:1'"
            )
        receipts = self.store.cancel_expired_roots(now_ms=12)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")

    def test_old_generation_commit_is_rejected_without_commit_or_outbox_writeback(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:stale", key="stale"), now_ms=10)
        before = self.store.counts("root:1")
        cancellation = self.store.cancel_root("root:1", now_ms=20)
        receipt = self.store.apply_commit(
            commit(
                "commit:stale",
                "dispatch:stale",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=21,
        )
        after = self.store.counts("root:1")

        self.assertEqual(cancellation["generation"], 1)
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["details"]["reason"], "stale_generation")
        self.assertEqual(after["commits"], before["commits"])
        self.assertEqual(after["outbox"], before["outbox"])

    def test_expired_lease_becomes_unknown_and_dead_letter_not_retry(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:crash", key="crash"), now_ms=10)
        lease = self.store.lease_next(now_ms=11, ttl_ms=5)
        self.assertIsNotNone(lease)

        receipts = self.store.reconcile_expired_leases(now_ms=16)

        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "unknown")
        self.assertEqual(self.store.outbox("dispatch:crash")["state"], "dead_letter")
        self.assertEqual(self.store.lease("dispatch:crash")["state"], "expired")
        self.assertEqual(receipts[0]["receiptKind"], "dispatch_unknown")
        self.assertEqual(self.store.receipt(str(receipts[0]["receiptId"])), receipts[0])
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)
        self.assertIsNone(self.store.lease_next(now_ms=17, ttl_ms=5))
        final = self.store.finalize_root("root:1", now_ms=18)
        self.assertEqual(final["status"], "rejected")
        self.assertEqual(final["details"]["unknownDispatches"], 1)

    def test_stop_covers_queued_running_retry_timer_and_targeted_cancel_is_typed(self) -> None:
        self.seed(criteria=())
        states = ("pending", "running", "retry_wait", "timer_wait")
        for ordinal, state in enumerate(states):
            dispatch_id = f"dispatch:{state}"
            self.store.enqueue_dispatch(
                dispatch(
                    dispatch_id,
                    key=f"key:{ordinal}",
                    target="participant:a",
                    session_id=f"session:state:{ordinal}",
                ),
                now_ms=10 + ordinal,
            )
            if state != "pending":
                self.store.set_dispatch_wait_state(dispatch_id, state, now_ms=20 + ordinal)

        targeted_command = control_command(
            "command:target", "cancel_target", target_kind="dispatch", target_id="dispatch:running", now_ms=30
        )
        targeted = self.store.apply_control_command(targeted_command)
        self.assertEqual(targeted["receiptKind"], "target_cancelled")
        self.assertEqual(targeted["commandId"], "command:target")
        self.assertEqual(self.store.dispatch("dispatch:pending")["state"], "pending")

        root_command = control_command("command:root-stop", "cancel_root", now_ms=31)
        stopped = self.store.apply_control_command(root_command)
        self.assertEqual(stopped["receiptKind"], "root_cancelled")
        self.assertEqual(stopped["commandId"], "command:root-stop")
        self.assertEqual(stopped["details"]["cancelledDispatches"], 3)
        self.assertTrue(all(self.store.dispatch(f"dispatch:{state}")["state"] == "cancelled" for state in states))

    def test_panic_command_cancels_the_room_and_is_idempotent(self) -> None:
        self.seed(criteria=())
        self.store.enqueue_dispatch(dispatch("dispatch:panic", key="panic-work"), now_ms=10)
        command = control_command("command:panic", "panic", root_id=None, now_ms=20)

        receipt = self.store.apply_control_command(command)
        duplicate = self.store.apply_control_command(command)

        self.assertEqual(receipt["receiptKind"], "panic")
        self.assertEqual(receipt["details"]["rootCount"], 1)
        self.assertEqual(receipt["commandId"], "command:panic")
        self.assertEqual(duplicate, receipt)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")

    def test_root_final_requires_quiescence_acceptance_and_terminal_receipt(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:done", key="done"), now_ms=10)
        early = self.store.finalize_root("root:1", now_ms=11)
        self.assertEqual(early["status"], "rejected")
        self.store.set_dispatch_wait_state("dispatch:done", "running", now_ms=11)

        applied = self.store.apply_commit(
            commit("commit:done", "dispatch:done", coverage=("ac:1",)),
            generation=0,
            now_ms=12,
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(self.store.commit("commit:done")["dispatchId"], "dispatch:done")
        task_after_commit = self.store.task("task:1")
        self.assertEqual(task_after_commit["resultKind"], "complete")
        self.assertEqual(task_after_commit["resultAtMs"], 12)
        self.assertEqual(task_after_commit["verificationCount"], 1)
        self.assertEqual(
            task_after_commit["verifications"],
            [
                {
                    "label": "验收项 1",
                    "result": "pass",
                    "source": "quality_gate",
                }
            ],
        )
        self.assertNotIn("AC-", json.dumps(task_after_commit, ensure_ascii=False))
        self.assertNotIn("ac:1", json.dumps(task_after_commit["verifications"]))
        terminal = self.store.finalize_root("root:1", now_ms=13)
        root_after = self.store.root("root:1")
        self.assertEqual(terminal["receiptKind"], "terminal")
        self.assertTrue(terminal["details"]["quiescent"])
        self.assertEqual(root_after["state"], "completed")
        self.assertEqual(root_after["terminalReceiptId"], terminal["receiptId"])

    def test_review_required_root_rejects_quiescent_completion_without_review(self) -> None:
        self.seed(independent_review_required=True)
        self.store.enqueue_dispatch(dispatch("dispatch:review-required", key="review-required"), now_ms=10)
        self.store.set_dispatch_wait_state(
            "dispatch:review-required",
            "running",
            now_ms=11,
        )
        self.store.apply_commit(
            commit(
                "commit:review-required",
                "dispatch:review-required",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=12,
        )

        rejected = self.store.finalize_root("root:1", now_ms=13)

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            rejected["details"]["reason"],
            "independent_review_required",
        )
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_missing_root_review_policy_fails_closed_at_terminal_fence(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:missing-policy", key="missing-policy"), now_ms=10)
        self.store.set_dispatch_wait_state(
            "dispatch:missing-policy",
            "running",
            now_ms=11,
        )
        self.store.apply_commit(
            commit(
                "commit:missing-policy",
                "dispatch:missing-policy",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=12,
        )
        with sqlite3.connect(self.db_path) as conn:
            payload = json.loads(
                str(
                    conn.execute(
                        "SELECT payload_json FROM room_kernel_roots WHERE root_id=?",
                        ("root:1",),
                    ).fetchone()[0]
                )
            )
            payload.pop("independentReviewRequired", None)
            conn.execute(
                "UPDATE room_kernel_roots SET payload_json=? WHERE root_id=?",
                (json.dumps(payload, sort_keys=True), "root:1"),
            )

        rejected = self.store.finalize_root("root:1", now_ms=13)

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            rejected["details"]["reason"],
            "independent_review_policy_missing_or_invalid",
        )
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_root_without_acceptance_criteria_cannot_be_delivered(self) -> None:
        self.seed(criteria=())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE room_kernel_tasks SET state = 'completed' WHERE root_id = 'root:1'")

        rejected = self.store.finalize_root("root:1", now_ms=13)

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["details"]["reason"], "acceptance_evidence_missing")
        self.assertEqual(rejected["details"]["acceptanceCriteria"], [])
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_forged_coverage_without_commit_evidence_cannot_finalize_root(self) -> None:
        self.seed()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_roots SET covered_criteria_json = ? WHERE root_id = 'root:1'",
                ('["ac:1"]',),
            )
            conn.execute("UPDATE room_kernel_tasks SET state = 'completed' WHERE root_id = 'root:1'")

        rejected = self.store.finalize_root("root:1", now_ms=13)

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["details"]["reason"], "acceptance_evidence_missing")
        self.assertEqual(rejected["details"]["unprovenAcceptanceCriteria"], ["ac:1"])

    def test_terminal_receipt_reports_evidence_ref_count_per_criterion(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:done", key="done"), now_ms=10)
        self.store.set_dispatch_wait_state("dispatch:done", "running", now_ms=11)
        self.store.apply_commit(
            commit("commit:done", "dispatch:done", coverage=("ac:1",)),
            generation=0,
            now_ms=12,
        )

        terminal = self.store.finalize_root("root:1", now_ms=13)

        self.assertEqual(terminal["receiptKind"], "terminal")
        self.assertEqual(terminal["details"]["acceptanceEvidenceRefCounts"], {"ac:1": 1})

    def test_cancelled_room_obligations_still_fence_terminal_completion(self) -> None:
        cases = (
            (
                "pending_review",
                {
                    "taskKind": "review",
                    "reviewState": "required",
                    "reviewFindings": [],
                },
                "review_cancelled",
                "reviewFences",
            ),
            (
                "unresolved_blocker",
                {
                    "taskKind": "review",
                    "reviewState": "accepted",
                    "reviewFindings": [
                        {
                            "findingId": "finding:blocker",
                            "gateEffect": "blocking",
                            "state": "open",
                            "category": "correctness",
                        }
                    ],
                },
                "review_cancelled",
                "unresolvedBlockingFindings",
            ),
            (
                "stale_review",
                {
                    "taskKind": "review",
                    "reviewState": "stale",
                    "reviewFindings": [],
                },
                "review_cancelled",
                "reviewFences",
            ),
            (
                "pending_integration",
                {
                    "workspacePolicy": "isolated_writable",
                    "workspaceIntegrationState": "pending",
                    "workspaceIntegrationRef": None,
                },
                "workspace_integration_pending",
                "pendingIntegrations",
            ),
        )
        for index, (name, updates, expected_reason, evidence_key) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(name=name):
                root_id = f"root:governance:{name}"
                task_id = f"task:governance:{name}"
                self.store.create_root(
                    root(root_id),
                    budget=10,
                    max_hops=3,
                    max_depth=2,
                    acceptance_criteria=("ac:1",),
                    now_ms=index,
                )
                self.store.create_task(
                    task(task_id, root_id=root_id),
                    now_ms=index + 1,
                )
                with sqlite3.connect(self.db_path) as conn:
                    row = conn.execute(
                        "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    payload = json.loads(str(row[0]))
                    payload.update(updates)
                    conn.execute(
                        "UPDATE room_kernel_tasks SET state=?,payload_json=?,updated_at_ms=? WHERE task_id=?",
                        (
                            "completed"
                            if name == "pending_integration"
                            else "active",
                            json.dumps(
                                payload,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            index + 2,
                            task_id,
                        ),
                    )
                cancelled = self.store.apply_control_command(
                    control_command(
                        f"command:governance:{name}",
                        "cancel_target",
                        target_kind="task",
                        target_id=task_id,
                        root_id=root_id,
                        now_ms=index + 3,
                    )
                )
                self.assertEqual(cancelled["receiptKind"], "target_cancelled")
                rejected = self.store.finalize_root(
                    root_id,
                    now_ms=index + 4,
                )
                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(rejected["details"]["reason"], expected_reason)
                self.assertTrue(rejected["details"]["governance"][evidence_key])
                self.assertNotEqual(self.store.root(root_id)["state"], "completed")

    def test_workspace_lifecycle_receipts_project_complete_task_audit_fields(self) -> None:
        self.seed()
        payload = self.store.task("task:1")
        payload.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/room-child",
                "workspaceBaseRoot": "/tmp/room-base",
                "workspaceBaseCommit": "git:base",
                "workspaceBindingId": "workspace-binding:test",
                "workspaceRepositoryId": "a" * 64,
                "workspaceLifecycleState": "materialized",
                "workspaceCleanupState": "not_authorized",
                "workspaceAttentionRequired": False,
                "workspaceIntegrationState": "pending",
                "workspaceIntegrationRef": None,
                "workItemId": "work:test",
            }
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id='task:1'",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

        started = self.store.record_workspace_work_started(
            "task:1",
            lifecycle={
                "workspaceBindingId": "workspace-binding:test",
                "workspaceLifecycleState": "work_started",
                "workspaceAttentionRequired": False,
            },
            dispatch_id="dispatch:worker",
            now_ms=4,
        )
        self.assertEqual(started["workspaceLifecycleState"], "work_started")
        delivered = self.store.record_workspace_delivery(
            "task:1",
            delivery={
                "deliveryRevision": "sha256:" + "b" * 64,
                "deliveryHead": "git:base",
                "deliverySnapshotSha256": "c" * 64,
                "workspaceLifecycleState": "delivered",
                "workspaceDelivery": {
                    "schemaVersion": "wisdom-weasel.room-workspace-delivery.v1",
                    "ownerParticipantId": "participant:a",
                    "ownerSessionId": "session:a",
                    "workItemId": "work:test",
                    "taskId": "task:1",
                    "deliveryRevision": "sha256:" + "b" * 64,
                    "deliveredAtMs": 5,
                    "resultSummary": "Scoped delivery",
                    "manifestSha256": "d" * 64,
                    "files": [
                        {
                            "path": "README.md",
                            "additions": 1,
                            "deletions": 1,
                            "binary": False,
                            "generated": False,
                            "redacted": False,
                        }
                    ],
                    "totals": {
                        "fileCount": 1,
                        "additions": 1,
                        "deletions": 1,
                        "binaryFiles": 0,
                        "generatedFiles": 0,
                        "redactedFiles": 0,
                    },
                    "artifactRefs": [],
                    "verificationCount": 1,
                    "verifications": [
                        {
                            "label": "验收项 1",
                            "result": "pass",
                            "source": "quality_gate",
                        }
                    ],
                    "verificationRefs": ["test:focused"],
                    "residualRisks": [],
                },
            },
            now_ms=5,
        )
        self.assertEqual(
            delivered["workspaceDeliveryRevision"],
            "sha256:" + "b" * 64,
        )
        self.assertEqual(delivered["workspaceDeliveryHead"], "git:base")
        self.assertEqual(
            delivered["workspaceDeliverySnapshotSha256"],
            "c" * 64,
        )
        self.assertEqual(
            delivered["workspaceDelivery"]["workItemId"],
            "work:test",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET state='completed' WHERE task_id='task:1'"
            )
        conflict = self.store.record_workspace_integration(
            "task:1",
            integration_ref="integration:stable",
            workspace_result={
                "integrated": False,
                "workspaceLifecycleState": "conflict",
                "cleanupState": "retained",
                "reason": "patch conflict; child retained",
                "attentionRequired": True,
            },
            now_ms=6,
        )
        self.assertEqual(conflict["workspaceIntegrationState"], "pending")
        self.assertEqual(conflict["workspaceLifecycleState"], "conflict")
        self.assertEqual(conflict["workspaceCleanupState"], "retained")
        self.assertTrue(conflict["workspaceAttentionRequired"])
        self.assertEqual(
            conflict["workspaceTerminalReason"],
            "patch conflict; child retained",
        )
        integrated = self.store.record_workspace_integration(
            "task:1",
            integration_ref="integration:stable",
            workspace_result={
                "integrated": True,
                "integrationPatchSha256": "d" * 64,
                "integratedRevision": "git:integrated",
                "integratedSnapshotSha256": "e" * 64,
                "workspaceLifecycleState": "cleaned",
                "cleanupState": "cleaned",
                "attentionRequired": False,
            },
            now_ms=7,
        )
        self.assertEqual(integrated["workspaceIntegrationState"], "applied")
        self.assertEqual(
            integrated["workspaceIntegrationPatchSha256"],
            "d" * 64,
        )
        self.assertEqual(
            integrated["workspaceIntegratedRevision"],
            "git:integrated",
        )
        self.assertEqual(
            integrated["workspaceIntegratedSnapshotSha256"],
            "e" * 64,
        )
        self.assertEqual(integrated["workspaceLifecycleState"], "cleaned")
        self.assertEqual(integrated["workspaceCleanupState"], "cleaned")
        self.assertFalse(integrated["workspaceAttentionRequired"])

    def test_revision_bound_accepted_review_and_integration_finalize_once(self) -> None:
        self.seed()
        integrated_payload = self.store.task("task:1")
        integrated_payload.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceIntegrationState": "applied",
                "workspaceIntegrationRef": "integration:task-1",
                "revision": 1,
            }
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET state='completed',payload_json=?,updated_at_ms=? WHERE task_id='task:1'",
                (
                    json.dumps(
                        integrated_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    3,
                ),
            )
        review_task_id = "task:accepted-review"
        review_snapshot = {
            **task(review_task_id),
            "taskKind": "review",
            "reviewState": "required",
            "reviewOfTaskIds": ["task:1"],
            "reviewAuthorParticipantIds": ["participant:a"],
            "reviewEvidenceNotBeforeMs": 5,
            "reviewFindings": [],
            "workspacePolicy": "read_only",
            "workspaceRoot": "/tmp/room-review",
            "workspaceBaseRoot": "/tmp/room-review",
            "workspaceSnapshotSha256": "a" * 64,
            "workspaceIntegrationRef": "",
        }
        target_revision = self.store.review_target_revision(
            root_id="root:1",
            task_ids=["task:1"],
            review_snapshot=review_snapshot,
        )
        self.store.create_task(
            {
                **review_snapshot,
                "reviewTargetRevision": target_revision,
            },
            now_ms=4,
        )
        review_dispatch_id = "dispatch:accepted-review"
        review_dispatch = dispatch(
            review_dispatch_id,
            key="accepted-review",
            task_id=review_task_id,
        )
        review_dispatch["intentKind"] = "review"
        self.store.enqueue_dispatch(review_dispatch, now_ms=5)
        self.store.set_dispatch_wait_state(
            review_dispatch_id,
            "running",
            now_ms=5,
        )
        review_commit = commit(
            "commit:accepted-review",
            review_dispatch_id,
            coverage=("ac:1",),
            task_id=review_task_id,
        )
        binding_material = {
            "reviewTargetRevision": target_revision,
            "taskId": review_task_id,
            "dispatchId": review_dispatch_id,
            "evidenceRefs": ["test:room-kernel"],
            "notBeforeMs": 5,
        }
        review_commit["reviewEvidenceBinding"] = {
            "schemaVersion": "wisdom-weasel.review-evidence-binding.v1",
            "bindingId": (
                "review-evidence-binding:"
                + hashlib.sha256(
                    json.dumps(
                        binding_material,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            ),
            **binding_material,
        }
        applied = self.store.apply_commit(
            review_commit,
            generation=0,
            now_ms=6,
        )
        self.assertEqual(applied["status"], "applied")
        accepted_review = self.store.task(review_task_id)
        self.assertEqual(
            accepted_review["reviewTargetRevision"],
            target_revision,
        )
        terminal = self.store.finalize_root("root:1", now_ms=7)
        replay = self.store.finalize_root("root:1", now_ms=8)
        self.assertEqual(terminal["receiptKind"], "terminal")
        self.assertEqual(terminal["details"]["governance"]["reviewFences"], [])
        self.assertEqual(
            terminal["details"]["governance"]["pendingIntegrations"],
            [],
        )
        self.assertEqual(replay, terminal)
        self.assertEqual(self.store.root("root:1")["state"], "completed")

    def test_pending_review_snapshot_matches_commit_then_real_mutation_stales_it(
        self,
    ) -> None:
        self.seed()
        target_task = {
            **self.store.task("task:1"),
            "workspacePolicy": "isolated_writable",
            "workspaceIntegrationState": "pending",
            "workspaceIntegrationRef": "",
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        target_task,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:1",
                ),
            )
        self.store.enqueue_dispatch(
            dispatch("dispatch:pending-review", key="pending-review"),
            now_ms=10,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:pending-review",
            "running",
            now_ms=11,
        )
        pending_commit = commit(
            "commit:pending-review",
            "dispatch:pending-review",
            coverage=("ac:1",),
        )
        pending_task = self.store.project_task_result_payload(
            target_task,
            result_kind="complete",
            post_proposal=None,
            quality_gate_receipt=pending_commit["qualityGateReceipt"],
            evidence_refs=pending_commit["evidenceRefs"],
            now_ms=12,
        )
        pending_task["state"] = "completed"
        pending_revision = self.store.review_target_revision(
            root_id="root:1",
            task_ids=["task:1"],
            pending_commit_ids={"task:1": "commit:pending-review"},
            pending_task_snapshots={"task:1": pending_task},
        )

        self.store.apply_commit(
            pending_commit,
            generation=0,
            now_ms=12,
        )

        self.assertEqual(self.store.task("task:1"), pending_task)
        self.assertEqual(
            self.store.review_target_revision(
                root_id="root:1",
                task_ids=["task:1"],
            ),
            pending_revision,
        )
        self.store.record_workspace_integration(
            "task:1",
            integration_ref="integration:post-review-mutation",
            now_ms=13,
        )
        self.assertNotEqual(
            self.store.review_target_revision(
                root_id="root:1",
                task_ids=["task:1"],
            ),
            pending_revision,
        )

    def test_task_cannot_claim_acceptance_criteria_outside_root_or_parent(self) -> None:
        self.seed()

        with self.assertRaisesRegex(RoomKernelFenceError, "outside its Root"):
            self.store.create_task(task("task:forged", criteria=("ac:other",)), now_ms=3)

        self.store.create_task(
            {**task("task:narrow", criteria=()), "parentTaskId": "task:1"},
            now_ms=3,
        )
        with self.assertRaisesRegex(RoomKernelFenceError, "outside its parent Task"):
            self.store.create_task(
                {**task("task:widen", criteria=("ac:1",)), "parentTaskId": "task:narrow"},
                now_ms=4,
            )

    def test_ordinary_session_without_room_binding_has_zero_side_effects(self) -> None:
        self.seed()
        before = self.store.counts("root:1")
        normalized, created = self.store.normalize_compatibility_entry(
            dispatch("dispatch:ordinary", key="ordinary"),
            room_binding_ref=None,
            source_kind="mention",
            source_id="ordinary-message:1",
            now_ms=10,
        )
        self.assertIsNone(normalized)
        self.assertFalse(created)
        self.assertEqual(self.store.counts("root:1"), before)

        disabled = RoomKernelStore(self.db_path, mode="off")
        command, created = disabled.normalize_compatibility_entry(
            dispatch("dispatch:disabled", key="disabled"),
            room_binding_ref={"schemaVersion": "wisdom-weasel.room-binding.v2", "bindingId": "binding:1"},
            source_kind="wake",
            source_id="wake:disabled",
            now_ms=11,
        )
        self.assertIsNotNone(command)
        self.assertFalse(created)
        self.assertEqual(self.store.counts("root:1"), before)


class KernelModeAuthorityTests(unittest.TestCase):
    def test_only_cohort_and_kernel_only_claim_room_execution_authority(self) -> None:
        # collapsed into production authority; `shadow` observes; `off` disables.
        for mode in ("cohort", "kernel_only"):
            self.assertTrue(kernel_owns_room_execution(mode), mode)
        for mode in ("off", "shadow", "test", "", None, "production_cohort"):
            self.assertFalse(kernel_owns_room_execution(mode), repr(mode))


def root(
    root_id: str,
    *,
    independent_review_required: bool = False,
) -> dict[str, object]:
    return {
        "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
        "rootId": root_id,
        "roomId": "room:1",
        "generation": 0,
        "state": "running",
        "facilitatorParticipantId": "kernel-v2",
        "reporterParticipantId": None,
        "reporterSelectionReceiptId": None,
        "requirementAnchorRef": "requirement-anchor:1@sha256:test",
        "createdByActorRef": "user:local",
        "terminalReceiptId": None,
        "activeProfileRef": None,
        "budgetPolicyRef": "room-budget:test-v1",
        "independentReviewRequired": independent_review_required,
        "createdAtMs": 1,
    }


def task(
    task_id: str,
    *,
    root_id: str = "root:1",
    criteria: tuple[str, ...] = ("ac:1",),
) -> dict[str, object]:
    return {
        "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
        "taskId": task_id,
        "rootId": root_id,
        "parentTaskId": None,
        "taskKind": "work",
        "currentOwnerParticipantId": "participant:a",
        "ownershipRevision": 0,
        "ownershipReceiptId": None,
        "invitationId": None,
        "reviewState": "not_required",
        "reviewOfTaskIds": [],
        "reviewAuthorParticipantIds": [],
        "contextEvidenceRefs": [],
        "objective": "Complete bounded work.",
        "expectedOutput": "A tested result.",
        "requirementItemIds": ["requirement:1"],
        "acceptanceCriterionIds": list(criteria),
        "revision": 0,
        "state": "active",
    }


def child_task(
    task_id: str,
    *,
    parent: str,
    target: str,
    criteria: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        **task(task_id, criteria=criteria),
        "parentTaskId": parent,
        "currentOwnerParticipantId": target,
        "acceptanceCriterionIds": [],
    }

def task_transfer(
    *,
    from_participant: str,
    to_participant: str,
    ownership_revision: int,
    criteria: tuple[str, ...] = ("ac:1",),
) -> dict[str, object]:
    return {
        "taskId": "task:1",
        "fromParticipantId": from_participant,
        "toParticipantId": to_participant,
        "objective": "Continue the same bounded work.",
        "expectedOutput": "The same accepted result.",
        "acceptanceCriterionIds": list(criteria),
        "contextEvidenceRefs": ["evidence:handoff"],
        "ownershipRevision": ownership_revision,
    }


def dispatch(
    dispatch_id: str,
    *,
    key: str,
    target: str = "participant:a",
    hop: int = 0,
    depth: int = 0,
    cost: int = 1,
    parent: str | None = None,
    task_id: str = "task:1",
    session_id: str | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
        "dispatchId": dispatch_id,
        "rootId": "root:1",
        "taskId": task_id,
        "parentDispatchId": parent,
        "generation": 0,
        "hopCount": hop,
        "depth": depth,
        "budgetCost": cost,
        "targetSessionId": session_id or f"session:{target}",
        "targetParticipantId": target,
        "triggerId": f"trigger:{key}",
        "intentKind": "execute",
        "idempotencyKey": key,
        "attempt": 0,
        "capabilityEpoch": 1,
        "runtimeProfileRevision": "runtime-profile:test-v1",
        "state": "pending",
    }


def commit(
    commit_id: str,
    dispatch_id: str,
    *,
    coverage: tuple[str, ...] = (),
    task_id: str = "task:1",
) -> dict[str, object]:
    items = [
        {
            "criterionId": criterion_id,
            "status": "pass",
            "evidenceRefs": ["test:room-kernel"],
        }
        for criterion_id in coverage
    ]
    return {
        "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
        "commitId": commit_id,
        "dispatchId": dispatch_id,
        "action": "complete",
        "contentHash": "sha256:test",
        "postProposal": None,
        "qualityGateReceipt": {
            "schemaVersion": "wisdom-weasel.room-quality-gate-receipt.v1",
            "receiptId": f"quality:{commit_id}",
            "rootId": "root:1",
            "taskId": task_id,
            "dispatchId": dispatch_id,
            "generation": 0,
            "originalRequestChecked": True,
            "verdict": "ready_to_deliver",
            "items": items,
            "residualRisks": [],
            "createdAtMs": 12,
        },
        "evidenceRefs": ["test:room-kernel"],
        "requirementCoverage": list(coverage),
        "createdAtMs": 12,
    }


def post_proposal(
    commit_id: str,
    dispatch_id: str,
    *,
    task_id: str,
    author: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "wisdom-weasel.room-post.v2",
        "postId": f"post:{commit_id}",
        "roomId": "room:1",
        "rootId": "root:1",
        "generation": 0,
        "taskId": task_id,
        "dispatchId": dispatch_id,
        "authorActorRef": author,
        "kind": "result",
        "visibility": "room",
        "content": f"public result for {dispatch_id}",
        "idempotencyKey": f"post:{commit_id}",
        "publicationSource": {
            "kind": "room_commit",
            "ref": commit_id,
        },
        "createdAtMs": 12,
    }


def wait_commit(
    commit_id: str,
    dispatch_id: str,
    *,
    dependency_id: str,
) -> dict[str, object]:
    proposal = post_proposal(
        commit_id,
        dispatch_id,
        task_id="task:1",
        author="participant:a",
    )
    payload = commit(commit_id, dispatch_id)
    payload.update(
        {
            "action": "post",
            "postProposal": proposal,
            "continuation": {
                "decision": "wait",
                "waitingFor": "participant",
                "waitingForParticipantId": "participant:b",
                "waitingForDispatchId": dependency_id,
                "resumeCondition": "peer result is public",
            },
        }
    )
    payload["qualityGateReceipt"] = {
        **payload["qualityGateReceipt"],
        "verdict": "not_ready",
    }
    return payload


def control_command(
    command_id: str,
    kind: str,
    *,
    root_id: str | None = "root:1",
    target_kind: str | None = "root",
    target_id: str | None = "root:1",
    now_ms: int,
) -> dict[str, object]:
    return {
        "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
        "commandId": command_id,
        "rootId": root_id,
        "roomId": "room:1",
        "commandKind": kind,
        "targetKind": None if kind == "panic" else target_kind,
        "targetId": None if kind == "panic" else target_id,
        "sourceKind": "user_control",
        "sourceId": command_id,
        "idempotencyKey": command_id,
        "generation": 0,
        "payload": {},
        "createdAtMs": now_ms,
    }
