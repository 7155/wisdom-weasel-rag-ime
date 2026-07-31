from __future__ import annotations

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

    def seed(self, *, budget: int = 10, max_hops: int = 3, max_depth: int = 2, criteria: tuple[str, ...] = ("ac:1",)) -> None:
        self.store.create_root(
            root("root:1"),
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
        terminal = self.store.finalize_root("root:1", now_ms=13)
        root_after = self.store.root("root:1")
        self.assertEqual(terminal["receiptKind"], "terminal")
        self.assertTrue(terminal["details"]["quiescent"])
        self.assertEqual(root_after["state"], "completed")
        self.assertEqual(root_after["terminalReceiptId"], terminal["receiptId"])

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
        # `test` runs the same machinery inside unit tests but must never be
        # collapsed into production authority; `shadow` observes; `off` disables.
        for mode in ("cohort", "kernel_only"):
            self.assertTrue(kernel_owns_room_execution(mode), mode)
        for mode in ("off", "shadow", "test", "", None, "production_cohort"):
            self.assertFalse(kernel_owns_room_execution(mode), repr(mode))


def root(root_id: str) -> dict[str, object]:
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
