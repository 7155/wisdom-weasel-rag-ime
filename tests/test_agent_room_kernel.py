from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)


class RoomKernelCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-kernel-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), 86)

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
        self.store.create_task(task("task:1"), now_ms=2)

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

    def test_a_to_b_to_a_is_bounded_by_hop_and_depth_fences(self) -> None:
        self.seed(max_hops=2, max_depth=1)
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
            ),
            now_ms=11,
        )
        third, _ = self.store.enqueue_dispatch(
            dispatch(
                "dispatch:a2",
                key="a2",
                target="participant:a",
                hop=2,
                depth=1,
                parent=str(second["dispatchId"]),
            ),
            now_ms=12,
        )
        self.assertEqual(third["hopCount"], 2)
        with self.assertRaisesRegex(RoomKernelFenceError, "hop limit"):
            self.store.enqueue_dispatch(
                dispatch(
                    "dispatch:b2",
                    key="b2",
                    target="participant:b",
                    hop=3,
                    depth=1,
                    parent="dispatch:a2",
                ),
                now_ms=13,
            )

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

    def test_old_generation_commit_is_rejected_without_commit_or_outbox_writeback(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:stale", key="stale"), now_ms=10)
        before = self.store.counts("root:1")
        cancellation = self.store.cancel_root("root:1", now_ms=20)
        receipt = self.store.apply_commit(commit("commit:stale", "dispatch:stale"), generation=0, now_ms=21)
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
            self.store.enqueue_dispatch(dispatch(dispatch_id, key=f"key:{ordinal}"), now_ms=10 + ordinal)
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


def root(root_id: str) -> dict[str, object]:
    return {
        "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
        "rootId": root_id,
        "roomId": "room:1",
        "generation": 0,
        "state": "running",
        "owner": "kernel-v2",
        "requirementAnchorRef": "requirement-anchor:1@sha256:test",
        "createdByActorRef": "user:local",
        "terminalReceiptId": None,
        "activeProfileRef": None,
        "budgetPolicyRef": "room-budget:test-v1",
        "createdAtMs": 1,
    }


def task(task_id: str) -> dict[str, object]:
    return {
        "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
        "taskId": task_id,
        "rootId": "root:1",
        "parentTaskId": None,
        "ownerParticipantId": "participant:a",
        "assigneeParticipantId": "participant:a",
        "objective": "Complete bounded work.",
        "expectedOutput": "A tested result.",
        "requirementItemIds": ["requirement:1"],
        "acceptanceCriterionIds": ["ac:1"],
        "revision": 0,
        "state": "active",
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
) -> dict[str, object]:
    return {
        "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
        "dispatchId": dispatch_id,
        "rootId": "root:1",
        "taskId": "task:1",
        "parentDispatchId": parent,
        "generation": 0,
        "hopCount": hop,
        "depth": depth,
        "budgetCost": cost,
        "targetSessionId": f"session:{target}",
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
) -> dict[str, object]:
    return {
        "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
        "commitId": commit_id,
        "dispatchId": dispatch_id,
        "action": "complete",
        "contentHash": "sha256:test",
        "postProposal": None,
        "evidenceRefs": ["test:room-kernel"],
        "requirementCoverage": list(coverage),
        "createdAtMs": 12,
    }


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
