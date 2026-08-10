from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    kernel_owns_room_execution,
)
from rag_ime.agent_room_capabilities import (
    canonical_review_finding_fingerprint,
)
from rag_ime.agent_room_context import RoomContextLedgerStore
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_room_workspace_ledger import RoomWorkspaceLedgerStore
from rag_ime.agent_service import AgentService
from rag_ime.db import latest_migration_version
from rag_ime.pi_runtime import PiRuntimeConfig


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
                "sessionId": dispatch_payload["targetSessionId"],
                "generation": dispatch_payload["generation"],
                "capabilityEpoch": dispatch_payload["capabilityEpoch"],
                "turnId": turn_id,
            },
            now_ms=now_ms,
        )

    def record_runtime_evidence(
        self,
        dispatch_id: str,
        *,
        evidence_ref: str,
        now_ms: int,
    ) -> None:
        dispatch_payload = self.store.dispatch(dispatch_id)
        manifest_id = f"manifest:{dispatch_id}:evidence"
        manifest_hash = "c" * 64
        invocation_id = f"invoke:{dispatch_id}:evidence"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO room_v2_capability_manifests(
                   manifest_id,binding_id,room_id,root_id,task_id,dispatch_id,
                   generation,capability_revision,capability_epoch,manifest_hash,
                   payload_json,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)""",
                (
                    manifest_id,
                    f"binding:{dispatch_id}:evidence",
                    "room:1",
                    dispatch_payload["rootId"],
                    dispatch_payload["taskId"],
                    dispatch_id,
                    dispatch_payload["generation"],
                    "capability:test-v1",
                    dispatch_payload["capabilityEpoch"],
                    manifest_hash,
                    now_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_capability_runtime_bindings(
                   session_id,manifest_id,manifest_hash,prompt_compile_receipt_id,
                   prompt_plan_hash,compiled_profile_id,compiled_profile_revision,
                   compiled_profile_hash,room_binding_json,participant_binding_json,
                   capability_epoch,state,created_at_ms,updated_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, 'active', ?, ?)""",
                (
                    dispatch_payload["targetSessionId"],
                    manifest_id,
                    manifest_hash,
                    f"prompt:{dispatch_id}:evidence",
                    "d" * 64,
                    "compiled:test",
                    "1",
                    "e" * 64,
                    dispatch_payload["capabilityEpoch"],
                    now_ms - 2,
                    now_ms - 2,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_invocation_receipts(
                   receipt_id,manifest_id,manifest_hash,load_receipt_id,
                   invocation_key,canonical_tool_name,original_tool_name,
                   command_hash,command_json,authorization_state,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, 'room_state', 'room_state', ?, '{}',
                             'authorized', ?)""",
                (
                    invocation_id,
                    manifest_id,
                    manifest_hash,
                    f"load:{dispatch_id}:evidence",
                    f"call:{dispatch_id}:evidence",
                    "f" * 64,
                    now_ms - 1,
                ),
            )
            conn.execute(
                """INSERT INTO room_v2_tool_execution_receipts(
                   execution_receipt_id,invocation_receipt_id,kernel_receipt_id,
                   session_id,tool_name,status,result_hash,payload_json,created_at_ms
                   ) VALUES (?, ?, NULL, ?, 'room_state', 'applied', ?, '{}', ?)""",
                (
                    evidence_ref,
                    invocation_id,
                    dispatch_payload["targetSessionId"],
                    "a" * 64,
                    now_ms,
                ),
            )

    def test_user_request_posts_survive_outside_the_public_timeline_window(self) -> None:
        self.seed()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO room_kernel_posts(
                   post_id,room_id,root_id,generation,idempotency_key,
                   payload_json,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "post:user",
                    "room:1",
                    "root:1",
                    0,
                    "request:one",
                    json.dumps(
                        {
                            "authorActorRef": "user:local",
                            "content": "开始行动并运行测试。",
                            "createdAtMs": 3,
                            "kind": "request",
                            "rootId": "root:1",
                        },
                        ensure_ascii=False,
                    ),
                    3,
                ),
            )
            conn.execute(
                """INSERT INTO room_kernel_posts(
                   post_id,room_id,root_id,generation,idempotency_key,
                   payload_json,created_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "post:participant",
                    "room:1",
                    "root:1",
                    0,
                    "result:one",
                    json.dumps(
                        {
                            "authorActorRef": "participant:one",
                            "content": "伙伴进展",
                            "createdAtMs": 4,
                            "kind": "result",
                            "rootId": "root:1",
                        },
                        ensure_ascii=False,
                    ),
                    4,
                ),
            )

        self.assertEqual(
            self.store.user_request_posts("root:1"),
            [
                {
                    "role": "user",
                    "text": "开始行动并运行测试。",
                    "turnId": "root:1",
                    "createdAtMs": 3,
                }
            ],
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
        self.assertEqual(shadow.root("root:1")["budgetReserved"], 0)
        with sqlite3.connect(self.db_path) as conn:
            reservation_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM room_kernel_dispatch_resource_reservations "
                    "WHERE root_id='root:1'"
                ).fetchone()[0]
            )
            limits = conn.execute(
                """SELECT input_token_reserved,output_token_reserved,
                          tool_call_reserved,tool_cost_reserved,
                          concurrency_reserved
                   FROM room_kernel_root_limits WHERE root_id='root:1'"""
            ).fetchone()
        self.assertEqual(reservation_count, 0)
        self.assertEqual(tuple(limits or ()), (0, 0, 0, 0, 0))

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

    def test_workspace_delivery_accepts_proven_superseded_owner_lineage(
        self,
    ) -> None:
        self.seed(max_hops=2)
        workspace_ledger = RoomWorkspaceLedgerStore(self.db_path)
        binding, _ = workspace_ledger.reserve_binding(
            room_id="room:1",
            root_id="root:1",
            task_id="task:1",
            work_item_id="work:test",
            dispatch_id="dispatch:a",
            requirement_revision="requirement:test",
            acceptance_aliases=["ac:1"],
            participant_id="participant:a",
            session_id="session:a",
            repository_id="a" * 64,
            base_root="/tmp/room-base",
            base_commit="git:base",
            workspace_root="/tmp/room-child",
            workspace_policy="isolated_writable",
            creation_reason="workspace owner lineage projection test",
            now_ms=3,
        )
        task_payload = self.store.task("task:1")
        task_payload.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/room-child",
                "workspaceBaseRoot": "/tmp/room-base",
                "workspaceBaseCommit": "git:base",
                "workspaceBindingId": binding["workspaceBindingId"],
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
                        task_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

        self.store.enqueue_dispatch(
            dispatch("dispatch:a", key="owner-a", target="participant:a"),
            now_ms=4,
        )
        self.store.set_dispatch_wait_state("dispatch:a", "running", now_ms=5)
        transfer_dispatch = dispatch(
            "dispatch:b",
            key="owner-b",
            target="participant:b",
            hop=1,
            parent="dispatch:a",
        )
        transfer_receipt = self.store.apply_commit(
            {
                **commit("commit:a-to-b", "dispatch:a", coverage=("ac:1",)),
                "action": "dispatch",
                "continuation": {
                    "decision": "dispatch",
                    "taskTransfer": task_transfer(
                        from_participant="participant:a",
                        to_participant="participant:b",
                        ownership_revision=1,
                    ),
                    "childDispatch": transfer_dispatch,
                },
            },
            generation=0,
            now_ms=6,
        )
        self.assertEqual(
            self.store.task("task:1")["currentOwnerParticipantId"],
            "participant:b",
        )
        self.assertEqual(
            transfer_receipt["details"]["ownershipReceiptId"],
            self.store.task("task:1")["ownershipReceiptId"],
        )

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
                    "baseCommit": "git:base",
                    "workspaceSnapshotSha256": "c" * 64,
                    "patchSha256": "d" * 64,
                    "deliveredAtMs": 7,
                    "resultSummary": "Delivered before owner projection caught up.",
                    "manifestSha256": "f" * 64,
                    "files": [],
                    "totals": {
                        "fileCount": 0,
                        "additions": 0,
                        "deletions": 0,
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
                    "verificationRefs": ["test:owner-lineage"],
                    "residualRisks": [],
                },
            },
            now_ms=7,
        )
        self.assertEqual(
            delivered["workspaceDelivery"]["ownerParticipantId"],
            "participant:a",
        )
        self.assertEqual(
            delivered["currentOwnerParticipantId"],
            "participant:b",
        )

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
            "reviewRound": 1,
            "reviewFindings": [],
            "workspacePolicy": "read_only",
            "workspaceRoot": "/tmp/room-review",
            "workspaceBaseRoot": "/tmp/room-review",
            "workspaceSnapshotSha256": "a" * 64,
            "workspaceIntegrationRef": "",
        }
        review_task["reviewTargetRevision"] = (
            self.store.review_target_revision(
                root_id="root:1",
                task_ids=["task:1"],
                review_snapshot=review_task,
            )
        )
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

    def test_participant_resume_keeps_root_blocked_until_other_failure_retries(
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
        self.store.create_task(
            child_task(
                "task:blocked",
                parent="task:1",
                target="participant:c",
            ),
            now_ms=4,
        )
        self.store.enqueue_dispatches(
            (
                dispatch(
                    "dispatch:waiter",
                    key="waiter-with-peer-blocker",
                    target="participant:a",
                ),
                dispatch(
                    "dispatch:peer",
                    key="peer-with-blocker",
                    target="participant:b",
                    task_id="task:peer",
                ),
                dispatch(
                    "dispatch:blocked",
                    key="independent-blocker",
                    target="participant:c",
                    task_id="task:blocked",
                ),
            ),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            "dispatch:blocked",
            turn_id="turn:independent-blocker",
            now_ms=11,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:waiter",
            "running",
            now_ms=12,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:peer",
            "running",
            now_ms=12,
        )
        waiting = wait_commit(
            "commit:waiter-with-peer-blocker",
            "dispatch:waiter",
            dependency_id="dispatch:peer",
        )
        self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=13,
            post_proposal=waiting["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            waiting["postProposal"]
        )
        self.store.record_runtime_failure(
            "dispatch:blocked",
            generation=0,
            source_event_id="event:independent-blocker",
            runtime_turn_id="turn:independent-blocker",
            dispatch_attempt=0,
            now_ms=14,
        )
        self.assertEqual(self.store.root("root:1")["state"], "blocked")

        peer_commit = {
            **commit(
                "commit:peer-with-blocker",
                "dispatch:peer",
                task_id="task:peer",
            ),
            "action": "post",
            "postProposal": post_proposal(
                "commit:peer-with-blocker",
                "dispatch:peer",
                task_id="task:peer",
                author="participant:b",
            ),
            "continuation": {"decision": "complete"},
        }
        receipt = self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=15,
            post_proposal=peer_commit["postProposal"],
        )
        self.assertEqual(len(receipt["details"]["resumedDispatchIds"]), 1)
        self.assertEqual(self.store.task("task:1")["state"], "active")
        self.assertEqual(self.store.task("task:blocked")["state"], "blocked")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")

        # Recover projections persisted before the blocker-preserving fix:
        # retriable blocked work is authoritative even if the aggregate Root
        # row was incorrectly reopened by a different participant resume.
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_roots SET state='running' WHERE root_id=?",
                ("root:1",),
            )
        self.assertEqual(self.store.root("root:1")["state"], "running")

        retry = self.store.apply_control_command(
            control_command(
                "command:retry-independent-blocker",
                "retry_root",
                now_ms=16,
            )
        )
        self.assertEqual(retry["receiptKind"], "root_retried")
        self.assertEqual(len(retry["details"]["retriedDispatchIds"]), 1)
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertEqual(self.store.task("task:blocked")["state"], "active")

    def test_retry_control_resumes_one_explicit_external_wait(self) -> None:
        self.seed(criteria=())
        self.store.enqueue_dispatch(
            dispatch("dispatch:external-wait", key="external-wait"),
            now_ms=3,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:external-wait",
            "running",
            now_ms=4,
        )
        waiting = {
            **commit("commit:external-wait", "dispatch:external-wait"),
            "action": "post",
            "postProposal": {
                **post_proposal(
                    "commit:external-wait",
                    "dispatch:external-wait",
                    task_id="task:1",
                    author="participant:a",
                ),
                "kind": "wait",
            },
            "continuation": {
                "decision": "wait",
                "waitingFor": "external",
                "resumeCondition": "operator confirms the external result",
            },
        }
        waiting["qualityGateReceipt"] = {
            **waiting["qualityGateReceipt"],
            "verdict": "not_ready",
        }
        waiting["evidenceRefs"] = []
        self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=5,
            post_proposal=waiting["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(
            waiting["postProposal"]
        )
        self.assertEqual(self.store.root("root:1")["state"], "waiting")
        self.assertEqual(self.store.task("task:1")["state"], "waiting")
        continuation_id = self.store.continuation(
            "commit:external-wait"
        )["continuationId"]

        command = control_command(
            "command:resume-external-wait",
            "retry_root",
            now_ms=6,
        )
        receipt = self.store.apply_control_command(command)
        resumed_id = receipt["details"]["retriedDispatchIds"][0]
        self.assertEqual(
            receipt["details"]["resumedExternalContinuationIds"],
            [continuation_id],
        )
        self.assertEqual(receipt["details"]["retryLineage"], [])
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertEqual(self.store.task("task:1")["state"], "active")
        self.assertEqual(self.store.dispatch(resumed_id)["state"], "pending")
        self.assertEqual(
            self.store.continuation("commit:external-wait")["state"],
            "resumed",
        )
        replay = self.store.apply_control_command(command)
        self.assertEqual(replay["receiptId"], receipt["receiptId"])
        self.assertEqual(self.store.counts("root:1")["dispatches"], 2)

    def test_one_presentation_repair_does_not_consume_retry_budget(self) -> None:
        self.seed(criteria=())
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_root_limits SET concurrency_limit=8 "
                "WHERE root_id='root:1'"
            )
        dispatch_id = "dispatch:presentation-repair"
        initial_dispatch = dispatch(
            dispatch_id,
            key="presentation-repair",
        )
        initial_dispatch["intentKind"] = "resume"
        self.store.enqueue_dispatch(
            initial_dispatch,
            now_ms=3,
        )
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=4 "
                "WHERE dispatch_id=?",
                (dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=4 "
                "WHERE task_id='task:1'",
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=4 "
                "WHERE root_id='root:1'",
            )
            conn.execute(
                "UPDATE room_kernel_root_limits SET retry_used=retry_limit "
                "WHERE root_id='root:1'",
            )
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="settle_blocked",
                status="rejected",
                generation=0,
                details={
                    "dispatchId": dispatch_id,
                    "attempt": 0,
                    "maxAttempts": 1,
                    "reason": (
                        "publicSummary must be rewritten for users without "
                        "internal Room identifiers, raw receipts, hashes, "
                        "or machine paths"
                    ),
                },
                now_ms=4,
            )
        before = self.store.resource_limits("root:1")["retry_used"]
        receipt = self.store.apply_control_command(
            control_command(
                "command:presentation-repair",
                "retry_root",
                now_ms=5,
            )
        )
        self.assertTrue(receipt["details"]["presentationOnly"])
        self.assertEqual(
            self.store.resource_limits("root:1")["retry_used"],
            before,
        )
        retried_id = receipt["details"]["retriedDispatchIds"][0]
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=6 "
                "WHERE dispatch_id=?",
                (retried_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=6 "
                "WHERE task_id='task:1'",
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=6 "
                "WHERE root_id='root:1'",
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "retry limit exhausted",
        ):
            self.store.apply_control_command(
                control_command(
                    "command:presentation-repair-again",
                    "retry_root",
                    now_ms=7,
                )
            )

        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="settle_blocked",
                status="rejected",
                generation=0,
                details={
                    "dispatchId": retried_id,
                    "attempt": 1,
                    "maxAttempts": 1,
                    "reason": (
                        "仍有实现或检查子任务没有完成；"
                        "先等待其公开工作结果，不要提前发布最终回复"
                    ),
                },
                now_ms=8,
            )
        closure_receipt = self.store.apply_control_command(
            control_command(
                "command:closure-projection-repair",
                "retry_root",
                now_ms=9,
            )
        )
        self.assertTrue(
            closure_receipt["details"]["closureProjectionOnly"]
        )
        self.assertFalse(closure_receipt["details"]["presentationOnly"])
        self.assertEqual(
            self.store.resource_limits("root:1")["retry_used"],
            before,
        )
        closure_dispatch_id = closure_receipt["details"][
            "retriedDispatchIds"
        ][0]
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=10 "
                "WHERE dispatch_id=?",
                (closure_dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=10 "
                "WHERE task_id='task:1'",
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=10 "
                "WHERE root_id='root:1'",
            )
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="settle_blocked",
                status="rejected",
                generation=0,
                details={
                    "dispatchId": closure_dispatch_id,
                    "attempt": 2,
                    "maxAttempts": 1,
                    "reason": (
                        "仍有实现或检查子任务没有完成；"
                        "先等待其公开工作结果，不要提前发布最终回复"
                    ),
                },
                now_ms=10,
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "retry limit exhausted",
        ):
            self.store.apply_control_command(
                control_command(
                    "command:closure-projection-repair-again",
                    "retry_root",
                    now_ms=11,
                )
            )

        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="settle_blocked",
                status="rejected",
                generation=0,
                details={
                    "dispatchId": closure_dispatch_id,
                    "attempt": 2,
                    "maxAttempts": 1,
                    "reason": (
                        "AC-2, AC-3 使用了无法核实的 evidenceRef；"
                        "请使用 Kernel 已接受的精确证据"
                    ),
                },
                now_ms=12,
            )
        evidence_receipt = self.store.apply_control_command(
            control_command(
                "command:evidence-projection-repair",
                "retry_root",
                now_ms=13,
            )
        )
        self.assertTrue(
            evidence_receipt["details"]["evidenceProjectionOnly"]
        )
        self.assertFalse(
            evidence_receipt["details"]["closureProjectionOnly"]
        )
        self.assertEqual(
            self.store.resource_limits("root:1")["retry_used"],
            before,
        )
        evidence_dispatch_id = evidence_receipt["details"][
            "retriedDispatchIds"
        ][0]
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=14 "
                "WHERE dispatch_id=?",
                (evidence_dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=14 "
                "WHERE task_id='task:1'",
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=14 "
                "WHERE root_id='root:1'",
            )
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="settle_blocked",
                status="rejected",
                generation=0,
                details={
                    "dispatchId": evidence_dispatch_id,
                    "attempt": 3,
                    "maxAttempts": 1,
                    "reason": (
                        "AC-2 使用了无法核实的 evidenceRef；"
                        "请使用 Kernel 已接受的精确证据"
                    ),
                },
                now_ms=14,
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "retry limit exhausted",
        ):
            self.store.apply_control_command(
                control_command(
                    "command:evidence-projection-repair-again",
                    "retry_root",
                    now_ms=15,
                )
            )

        aggregation_error = (
            "retry/revision quality evidence must come from the current "
            "attempt; prior accepted evidence was reused: ac:1"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO agent_runtime_events(
                       event_id,session_id,turn_id,sequence,event_type,
                       created_at_ms,redacted_summary,metrics_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    "event:aggregation-projection",
                    "session:participant:a",
                    "turn:aggregation-projection",
                    1,
                    "turn_failed",
                    16,
                    aggregation_error,
                    "{}",
                ),
            )
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="runtime_failed",
                status="applied",
                generation=0,
                details={
                    "dispatchId": evidence_dispatch_id,
                    "reasonCode": "runtime_turn_failed",
                    "sourceEventId": "event:aggregation-projection",
                },
                now_ms=16,
            )
        aggregation_receipt = self.store.apply_control_command(
            control_command(
                "command:aggregation-projection-repair",
                "retry_root",
                now_ms=17,
            )
        )
        self.assertTrue(
            aggregation_receipt["details"]["aggregationProjectionOnly"]
        )
        self.assertEqual(
            self.store.resource_limits("root:1")["retry_used"],
            before,
        )
        aggregation_dispatch_id = aggregation_receipt["details"][
            "retriedDispatchIds"
        ][0]
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=18 "
                "WHERE dispatch_id=?",
                (aggregation_dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=18 "
                "WHERE task_id='task:1'",
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=18 "
                "WHERE root_id='root:1'",
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO agent_runtime_events(
                       event_id,session_id,turn_id,sequence,event_type,
                       created_at_ms,redacted_summary,metrics_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    "event:aggregation-projection-again",
                    "session:participant:a",
                    "turn:aggregation-projection-again",
                    2,
                    "turn_failed",
                    19,
                    aggregation_error,
                    "{}",
                ),
            )
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="runtime_failed",
                status="applied",
                generation=0,
                details={
                    "dispatchId": aggregation_dispatch_id,
                    "reasonCode": "runtime_turn_failed",
                    "sourceEventId": (
                        "event:aggregation-projection-again"
                    ),
                },
                now_ms=19,
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "retry limit exhausted",
        ):
            self.store.apply_control_command(
                control_command(
                    "command:aggregation-projection-repair-again",
                    "retry_root",
                    now_ms=20,
                )
            )

    def test_retry_root_defers_review_until_failed_reviewed_work_is_repaired(
        self,
    ) -> None:
        self.seed(budget=8, max_hops=8, max_depth=4)
        review_task = {
            **child_task(
                "task:review",
                parent="task:1",
                target="participant:reviewer",
                criteria=("ac:1",),
            ),
            "taskKind": "review",
            "reviewAxis": "technical",
            "reviewState": "changes_requested",
            "reviewOfTaskIds": ["task:1"],
            "reviewAuthorParticipantIds": ["participant:a"],
        }
        self.store.create_task(review_task, now_ms=3)
        work_dispatch = dispatch(
            "dispatch:failed-work",
            key="failed-work",
        )
        review_dispatch = {
            **dispatch(
                "dispatch:failed-review",
                key="failed-review",
                target="participant:reviewer",
                task_id="task:review",
                parent="dispatch:failed-work",
                hop=1,
                depth=1,
            ),
            "intentKind": "review",
        }
        self.store.enqueue_dispatches(
            (work_dispatch, review_dispatch),
            now_ms=4,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=5 "
                "WHERE dispatch_id IN ('dispatch:failed-work','dispatch:failed-review')"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=5 "
                "WHERE dispatch_id IN ('dispatch:failed-work','dispatch:failed-review')"
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=5 "
                "WHERE task_id IN ('task:1','task:review')"
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=5 "
                "WHERE root_id='root:1'"
            )

        retry = self.store.apply_control_command(
            control_command(
                "command:retry-work-before-review",
                "retry_root",
                now_ms=6,
            )
        )

        self.assertEqual(len(retry["details"]["retriedDispatchIds"]), 1)
        retried = self.store.dispatch(
            str(retry["details"]["retriedDispatchIds"][0])
        )
        self.assertEqual(retried["taskId"], "task:1")
        self.assertEqual(
            retry["details"]["deferredReviewTaskIds"],
            ["task:review"],
        )
        self.assertEqual(self.store.task("task:1")["state"], "active")
        self.assertEqual(self.store.task("task:review")["state"], "blocked")
        with sqlite3.connect(self.db_path) as conn:
            retry_used = int(
                conn.execute(
                    "SELECT retry_used FROM room_kernel_root_limits "
                    "WHERE root_id='root:1'"
                ).fetchone()[0]
            )
        self.assertEqual(retry_used, 1)

    def test_retry_root_retries_failed_review_with_its_failed_waiter(self) -> None:
        self.seed(
            budget=10,
            max_hops=8,
            max_depth=4,
            criteria=("ac:implemented", "ac:review"),
            independent_review_required=True,
        )
        implementation_task = {
            **task(
                "task:implemented-before-review",
                criteria=("ac:implemented",),
            ),
            "parentTaskId": "task:1",
            "currentOwnerParticipantId": "participant:implementer",
        }
        self.store.create_task(implementation_task, now_ms=3)
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:implemented-before-review",
                key="implemented-before-review",
                target="participant:implementer",
                task_id="task:implemented-before-review",
            ),
            now_ms=4,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:implemented-before-review",
            "running",
            now_ms=5,
        )
        self.store.apply_commit(
            commit(
                "commit:implemented-before-review",
                "dispatch:implemented-before-review",
                coverage=("ac:implemented",),
                task_id="task:implemented-before-review",
            ),
            generation=0,
            now_ms=6,
        )
        review_task = {
            **task(
                "task:review-wait-target",
                criteria=("ac:implemented", "ac:review"),
            ),
            "parentTaskId": "task:1",
            "taskKind": "review",
            "currentOwnerParticipantId": "participant:reviewer",
            "reviewAxis": "technical",
            "reviewState": "required",
            "reviewOfTaskIds": ["task:1"],
            "reviewAuthorParticipantIds": ["participant:a"],
        }
        self.store.create_task(review_task, now_ms=7)
        handoff_dispatch = dispatch(
            "dispatch:review-handoff",
            key="review-handoff",
        )
        review_dispatch = {
            **dispatch(
                "dispatch:failed-review-target",
                key="failed-review-target",
                target="participant:reviewer",
                task_id="task:review-wait-target",
                parent="dispatch:review-handoff",
                hop=1,
                depth=1,
            ),
            "intentKind": "review",
        }
        waiter_dispatch = {
            **dispatch(
                "dispatch:failed-review-waiter",
                key="failed-review-waiter",
                parent="dispatch:review-handoff",
                hop=1,
            ),
            "intentKind": "resume",
            "attempt": 2,
        }
        self.store.enqueue_dispatch(handoff_dispatch, now_ms=8)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='committed',updated_at_ms=9 "
                "WHERE dispatch_id='dispatch:review-handoff'"
            )
        self.store.enqueue_dispatches(
            (review_dispatch, waiter_dispatch),
            now_ms=10,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_outbox SET state='committed',updated_at_ms=9 "
                "WHERE dispatch_id='dispatch:review-handoff'"
            )
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=6 "
                "WHERE dispatch_id IN "
                "('dispatch:failed-review-target','dispatch:failed-review-waiter')"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=6 "
                "WHERE dispatch_id IN "
                "('dispatch:failed-review-target','dispatch:failed-review-waiter')"
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=6 "
                "WHERE task_id IN ('task:1','task:review-wait-target')"
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=6 "
                "WHERE root_id='root:1'"
            )
            conn.execute(
                "UPDATE room_kernel_root_limits SET concurrency_reserved=0 "
                "WHERE root_id='root:1'"
            )
            conn.execute(
                """INSERT INTO room_kernel_continuations(
                   continuation_id,root_id,task_id,parent_dispatch_id,
                   child_dispatch_id,commit_id,decision,state,payload_json,
                   created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    "continuation:failed-review-waiter",
                    "root:1",
                    "task:1",
                    "dispatch:review-handoff",
                    "dispatch:failed-review-waiter",
                    "commit:failed-review-waiter",
                    "dispatch",
                    "resumed",
                    json.dumps(
                        {
                            "waitingFor": "participant",
                            "waitingForDispatchId": "dispatch:failed-review-target",
                            "resumeDispatchId": "dispatch:failed-review-waiter",
                        },
                        sort_keys=True,
                    ),
                    10,
                ),
            )
        retried_review_dispatch = {
            **review_dispatch,
            "dispatchId": "dispatch:failed-review-target:retry",
            "idempotencyKey": "failed-review-target-retry",
            "attempt": 1,
        }
        self.store.enqueue_dispatch(retried_review_dispatch, now_ms=11)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=12 "
                "WHERE dispatch_id='dispatch:failed-review-target:retry'"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=12 "
                "WHERE dispatch_id='dispatch:failed-review-target:retry'"
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=12 "
                "WHERE task_id='task:review-wait-target'"
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=12 "
                "WHERE root_id='root:1'"
            )

        retry = self.store.apply_control_command(
            control_command(
                "command:retry-review-and-waiter",
                "retry_root",
                now_ms=13,
            )
        )

        self.assertEqual(len(retry["details"]["retriedDispatchIds"]), 2)
        self.assertEqual(retry["details"]["deferredReviewTaskIds"], [])
        self.assertEqual(
            set(retry["details"]["retriedTaskIds"]),
            {"task:1", "task:review-wait-target"},
        )
        self.assertEqual(
            self.store.task("task:review-wait-target")[
                "acceptanceCriterionIds"
            ],
            ["ac:review"],
        )

    def test_retry_review_only_requires_unaccepted_criteria(self) -> None:
        self.seed(
            budget=8,
            max_hops=8,
            max_depth=4,
            criteria=("ac:implemented", "ac:review"),
            independent_review_required=True,
        )
        implementation_task = {
            **task(
                "task:implemented",
                criteria=("ac:implemented",),
            ),
            "parentTaskId": "task:1",
            "currentOwnerParticipantId": "participant:implementer",
        }
        self.store.create_task(implementation_task, now_ms=3)
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:accepted-work",
                key="accepted-work",
                target="participant:implementer",
                task_id="task:implemented",
            ),
            now_ms=4,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:accepted-work",
            "running",
            now_ms=5,
        )
        self.store.apply_commit(
            commit(
                "commit:accepted-work",
                "dispatch:accepted-work",
                coverage=("ac:implemented",),
                task_id="task:implemented",
            ),
            generation=0,
            now_ms=6,
        )
        review_task = {
            **task(
                "task:review-only",
                criteria=("ac:implemented", "ac:review"),
            ),
            "parentTaskId": "task:1",
            "taskKind": "review",
            "currentOwnerParticipantId": "participant:reviewer",
            "reviewAxis": "requirements",
            "reviewState": "required",
            "reviewOfTaskIds": ["task:1"],
            "reviewAuthorParticipantIds": ["participant:a"],
        }
        self.store.create_task(review_task, now_ms=7)
        review_dispatch = {
            **dispatch(
                "dispatch:failed-review-only",
                key="failed-review-only",
                target="participant:reviewer",
                task_id="task:review-only",
                parent="dispatch:accepted-work",
                hop=1,
                depth=1,
            ),
            "intentKind": "review",
        }
        self.store.enqueue_dispatch(review_dispatch, now_ms=8)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=9 "
                "WHERE dispatch_id='dispatch:failed-review-only'"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=9 "
                "WHERE dispatch_id='dispatch:failed-review-only'"
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='blocked',updated_at_ms=9 "
                "WHERE task_id='task:review-only'"
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='blocked',updated_at_ms=9 "
                "WHERE root_id='root:1'"
            )

        retry = self.store.apply_control_command(
            control_command(
                "command:retry-review-only",
                "retry_root",
                now_ms=10,
            )
        )

        self.assertEqual(len(retry["details"]["retriedDispatchIds"]), 1)
        self.assertEqual(
            self.store.task("task:review-only")["acceptanceCriterionIds"],
            ["ac:review"],
        )

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

    def test_control_retry_consumes_only_its_exact_committed_failure_lineage(
        self,
    ) -> None:
        self.seed()
        failed_dispatch_id = "dispatch:control-retry-failed"
        self.store.enqueue_dispatch(
            dispatch(failed_dispatch_id, key="control-retry-failed"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            failed_dispatch_id,
            turn_id="turn:control-retry-failed",
            now_ms=11,
        )
        self.store.record_runtime_failure(
            failed_dispatch_id,
            generation=0,
            source_event_id="event:control-retry-failed",
            runtime_turn_id="turn:control-retry-failed",
            dispatch_attempt=0,
            now_ms=12,
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT INTO room_v2_skill_capability_epochs(
                   root_id,capability_epoch,updated_at_ms
                   ) VALUES (?,?,?)""",
                ("root:1", 7, 12),
            )

        retry_receipt = self.store.apply_control_command(
            control_command(
                "command:control-retry",
                "retry_root",
                now_ms=13,
            )
        )
        retry_dispatch_id = str(
            retry_receipt["details"]["retriedDispatchIds"][0]
        )
        self.assertEqual(
            self.store.dispatch(retry_dispatch_id)["capabilityEpoch"],
            7,
        )
        self.assertEqual(
            retry_receipt["details"]["retryLineage"],
            [
                {
                    "failedDispatchId": failed_dispatch_id,
                    "failedDispatchAttempt": 0,
                    "retriedDispatchId": retry_dispatch_id,
                    "retriedDispatchAttempt": 1,
                    "taskId": "task:1",
                    "rootGeneration": 0,
                    "rootRetryOrdinal": 1,
                }
            ],
        )

        self.accept_runtime_attempt(
            retry_dispatch_id,
            turn_id="turn:control-retry-success",
            now_ms=14,
        )
        self.store.apply_commit(
            commit(
                "commit:control-retry-success",
                retry_dispatch_id,
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=15,
        )

        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 0)
        self.assertNotIn("root_not_quiescent", readiness["reasons"])

        self.store.create_task(task("task:unrelated-failure"), now_ms=16)
        unrelated_dispatch_id = "dispatch:unrelated-failure"
        self.store.enqueue_dispatch(
            dispatch(
                unrelated_dispatch_id,
                key="unrelated-failure",
                task_id="task:unrelated-failure",
            ),
            now_ms=17,
        )
        self.accept_runtime_attempt(
            unrelated_dispatch_id,
            turn_id="turn:unrelated-failure",
            now_ms=18,
        )
        self.store.record_runtime_failure(
            unrelated_dispatch_id,
            generation=0,
            source_event_id="event:unrelated-failure",
            runtime_turn_id="turn:unrelated-failure",
            dispatch_attempt=0,
            now_ms=19,
        )
        readiness = self.store.report_readiness("root:1")
        self.assertEqual(
            readiness["unresolvedDispatchFailures"],
            [
                {
                    "dispatchId": unrelated_dispatch_id,
                    "taskId": "task:unrelated-failure",
                    "state": "failed",
                }
            ],
        )

    def test_control_retry_tampered_root_ordinal_cannot_resolve_failure(
        self,
    ) -> None:
        self.seed()
        failed_dispatch_id = "dispatch:retry-ordinal-tamper"
        self.store.enqueue_dispatch(
            dispatch(failed_dispatch_id, key="retry-ordinal-tamper"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            failed_dispatch_id,
            turn_id="turn:retry-ordinal-tamper",
            now_ms=11,
        )
        self.store.record_runtime_failure(
            failed_dispatch_id,
            generation=0,
            source_event_id="event:retry-ordinal-tamper",
            runtime_turn_id="turn:retry-ordinal-tamper",
            dispatch_attempt=0,
            now_ms=12,
        )
        retry_receipt = self.store.apply_control_command(
            control_command(
                "command:retry-ordinal-tamper",
                "retry_root",
                now_ms=13,
            )
        )
        retry_dispatch_id = str(
            retry_receipt["details"]["retriedDispatchIds"][0]
        )
        self.accept_runtime_attempt(
            retry_dispatch_id,
            turn_id="turn:retry-ordinal-tamper:success",
            now_ms=14,
        )
        self.store.apply_commit(
            commit(
                "commit:retry-ordinal-tamper",
                retry_dispatch_id,
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=15,
        )
        self.assertEqual(
            self.store.report_readiness("root:1")["unknownDispatches"],
            0,
        )

        tampered = dict(retry_receipt)
        tampered_details = dict(tampered["details"])
        tampered_lineage = [
            dict(item) for item in tampered_details["retryLineage"]
        ]
        tampered_lineage[0]["rootRetryOrdinal"] = 999
        tampered_details["retryLineage"] = tampered_lineage
        tampered["details"] = tampered_details
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_receipts SET payload_json=? "
                "WHERE receipt_id=?",
                (
                    json.dumps(tampered, ensure_ascii=False),
                    retry_receipt["receiptId"],
                ),
            )

        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 1)
        self.assertEqual(
            readiness["unresolvedDispatchFailures"][0]["dispatchId"],
            failed_dispatch_id,
        )

    def test_control_retry_duplicate_ordinal_breaks_multilevel_lineage(
        self,
    ) -> None:
        self.seed()
        first_failed_id = "dispatch:retry-chain:first"
        self.store.enqueue_dispatch(
            dispatch(first_failed_id, key="retry-chain:first"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            first_failed_id,
            turn_id="turn:retry-chain:first",
            now_ms=11,
        )
        self.store.record_runtime_failure(
            first_failed_id,
            generation=0,
            source_event_id="event:retry-chain:first",
            runtime_turn_id="turn:retry-chain:first",
            dispatch_attempt=0,
            now_ms=12,
        )
        first_retry = self.store.apply_control_command(
            control_command(
                "command:retry-chain:first",
                "retry_root",
                now_ms=13,
            )
        )
        second_failed_id = str(
            first_retry["details"]["retriedDispatchIds"][0]
        )
        self.accept_runtime_attempt(
            second_failed_id,
            turn_id="turn:retry-chain:second",
            now_ms=14,
        )
        self.store.record_runtime_failure(
            second_failed_id,
            generation=0,
            source_event_id="event:retry-chain:second",
            runtime_turn_id="turn:retry-chain:second",
            dispatch_attempt=1,
            now_ms=15,
        )
        second_retry = self.store.apply_control_command(
            control_command(
                "command:retry-chain:second",
                "retry_root",
                now_ms=16,
            )
        )
        successful_id = str(
            second_retry["details"]["retriedDispatchIds"][0]
        )
        self.accept_runtime_attempt(
            successful_id,
            turn_id="turn:retry-chain:success",
            now_ms=17,
        )
        self.store.apply_commit(
            commit(
                "commit:retry-chain:success",
                successful_id,
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=18,
        )
        self.assertEqual(
            self.store.report_readiness("root:1")["unknownDispatches"],
            0,
        )

        tampered = dict(second_retry)
        tampered_details = dict(tampered["details"])
        tampered_lineage = [
            dict(item) for item in tampered_details["retryLineage"]
        ]
        tampered_lineage[0]["rootRetryOrdinal"] = 1
        tampered_details["retryLineage"] = tampered_lineage
        tampered["details"] = tampered_details
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_receipts SET payload_json=? "
                "WHERE receipt_id=?",
                (
                    json.dumps(tampered, ensure_ascii=False),
                    second_retry["receiptId"],
                ),
            )

        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 2)
        self.assertEqual(
            {
                item["dispatchId"]
                for item in readiness["unresolvedDispatchFailures"]
            },
            {first_failed_id, second_failed_id},
        )

    def test_control_retry_skipped_ordinal_invalidates_whole_receipt(
        self,
    ) -> None:
        self.seed()
        self.store.create_task(
            task("task:retry-gap", criteria=()),
            now_ms=3,
        )
        failed_ids = (
            "dispatch:retry-gap:first",
            "dispatch:retry-gap:second",
        )
        task_ids = ("task:1", "task:retry-gap")
        for ordinal, (failed_id, task_id) in enumerate(
            zip(failed_ids, task_ids, strict=True),
            start=10,
        ):
            self.store.enqueue_dispatch(
                dispatch(
                    failed_id,
                    key=failed_id,
                    task_id=task_id,
                ),
                now_ms=ordinal,
            )
            self.accept_runtime_attempt(
                failed_id,
                turn_id=f"turn:{failed_id}",
                now_ms=ordinal + 10,
            )
            self.store.record_runtime_failure(
                failed_id,
                generation=0,
                source_event_id=f"event:{failed_id}",
                runtime_turn_id=f"turn:{failed_id}",
                dispatch_attempt=0,
                now_ms=ordinal + 20,
            )
        retry_receipt = self.store.apply_control_command(
            control_command(
                "command:retry-gap",
                "retry_root",
                now_ms=50,
            )
        )
        retry_ids = [
            str(value)
            for value in retry_receipt["details"]["retriedDispatchIds"]
        ]
        for ordinal, retry_id in enumerate(retry_ids, start=60):
            self.accept_runtime_attempt(
                retry_id,
                turn_id=f"turn:{retry_id}:success",
                now_ms=ordinal,
            )
            retry_task_id = str(
                self.store.dispatch(retry_id)["taskId"]
            )
            coverage = ("ac:1",) if retry_task_id == "task:1" else ()
            self.store.apply_commit(
                commit(
                    f"commit:{retry_id}",
                    retry_id,
                    coverage=coverage,
                    task_id=retry_task_id,
                ),
                generation=0,
                now_ms=ordinal + 10,
            )
        self.assertEqual(
            self.store.report_readiness("root:1")["unknownDispatches"],
            0,
        )

        tampered = dict(retry_receipt)
        tampered_details = dict(tampered["details"])
        tampered_lineage = [
            dict(item) for item in tampered_details["retryLineage"]
        ]
        self.assertEqual(
            [item["rootRetryOrdinal"] for item in tampered_lineage],
            [1, 2],
        )
        tampered_lineage[1]["rootRetryOrdinal"] = 3
        tampered_details["retryLineage"] = tampered_lineage
        tampered["details"] = tampered_details
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_receipts SET payload_json=? "
                "WHERE receipt_id=?",
                (
                    json.dumps(tampered, ensure_ascii=False),
                    retry_receipt["receiptId"],
                ),
            )

        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 2)
        self.assertEqual(
            {
                item["dispatchId"]
                for item in readiness["unresolvedDispatchFailures"]
            },
            set(failed_ids),
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

    def test_runtime_retry_preserves_each_dispatch_attempt_identity(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:attempt-ledger"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="attempt-ledger"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:attempt-ledger:0",
            now_ms=11,
        )

        self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:attempt-ledger:0:failed",
            runtime_turn_id="turn:attempt-ledger:0",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=False,
            reason_code="provider_transport_failure",
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:attempt-ledger:1",
            now_ms=1_012,
        )

        attempts = self.store.dispatch_attempts(dispatch_id)

        self.assertEqual(
            [
                (
                    item["attemptId"],
                    item["dispatchAttempt"],
                    item["state"],
                    item["runtimeTurnId"],
                    item["runtimeReceipt"].get("turnId"),
                    item["terminalReceipt"].get("reasonCode"),
                )
                for item in attempts
            ],
            [
                (
                    "room-dispatch-attempt:dispatch:attempt-ledger:0",
                    0,
                    "failed",
                    "turn:attempt-ledger:0",
                    "turn:attempt-ledger:0",
                    "provider_transport_failure",
                ),
                (
                    "room-dispatch-attempt:dispatch:attempt-ledger:1",
                    1,
                    "runtime_accepted",
                    "turn:attempt-ledger:1",
                    "turn:attempt-ledger:1",
                    None,
                ),
            ],
        )

    def test_waiting_root_keeps_current_generation_runtime_retry_live(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:waiting-root-runtime-retry"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="waiting-root-runtime-retry"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:waiting-root-runtime-retry:1",
            now_ms=11,
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_roots SET state='waiting' "
                "WHERE root_id='root:1'"
            )

        receipt = self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:waiting-root-runtime-retry",
            runtime_turn_id="turn:waiting-root-runtime-retry:1",
            dispatch_attempt=0,
            now_ms=12,
            retryable=True,
            had_tool_activity=False,
            reason_code="provider_transport_failure",
        )

        self.assertEqual(receipt["receiptKind"], "runtime_retry_scheduled")
        self.assertEqual(self.store.root("root:1")["state"], "waiting")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "retry_wait")
        self.assertIsNotNone(self.store.pending_dispatch(now_ms=1_012))

    def test_cancelled_retry_wait_does_not_reuse_prior_runtime_intent(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:cancel-retry-wait"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="cancel-retry-wait"),
            now_ms=10,
        )
        lease = self.store.lease_next(now_ms=11, ttl_ms=30_000)
        self.assertIsNotNone(lease)
        assert lease is not None
        self.store.record_runtime_preflight_failure(
            lease_token=str(lease["leaseToken"]),
            now_ms=12,
            reason_code="session_open_failed",
        )

        receipt = self.store.cancel_root("root:1", now_ms=13)

        self.assertEqual(receipt["details"]["cancelIntents"], 0)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        self.assertIsNone(self.store.lease_cancel(now_ms=14))
        attempts = self.store.dispatch_attempts(dispatch_id)
        self.assertEqual(
            [(item["dispatchAttempt"], item["state"]) for item in attempts],
            [(0, "failed"), (1, "cancelled")],
        )
        self.assertEqual(
            attempts[1]["terminalReceipt"]["reasonCode"],
            "cancelled_before_runtime",
        )

    def test_cancelled_lease_without_runtime_intent_is_terminal_locally(
        self,
    ) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:cancel-before-runtime-intent"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="cancel-before-runtime-intent"),
            now_ms=10,
        )
        self.assertIsNotNone(
            self.store.lease_next(now_ms=11, ttl_ms=30_000)
        )

        receipt = self.store.cancel_root("root:1", now_ms=12)

        self.assertEqual(receipt["details"]["cancelIntents"], 0)
        self.assertEqual(self.store.root("root:1")["state"], "cancelled")
        attempt = self.store.dispatch_attempts(dispatch_id)[0]
        self.assertEqual(attempt["state"], "cancelled")
        self.assertEqual(
            attempt["terminalReceipt"]["reasonCode"],
            "cancelled_before_runtime",
        )

    def test_waiting_root_keeps_current_generation_preflight_retry_live(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:waiting-root-preflight-retry"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="waiting-root-preflight-retry"),
            now_ms=10,
        )
        lease = self.store.lease_next(
            now_ms=11,
            ttl_ms=30_000,
            dispatch_id=dispatch_id,
        )
        self.assertIsNotNone(lease)
        assert lease is not None
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_roots SET state='waiting' "
                "WHERE root_id='root:1'"
            )

        receipt = self.store.record_runtime_preflight_failure(
            lease_token=str(lease["leaseToken"]),
            now_ms=12,
            reason_code="runtime_dispatch_preflight_failed",
        )

        self.assertEqual(receipt["receiptKind"], "runtime_retry_scheduled")
        self.assertEqual(self.store.root("root:1")["state"], "waiting")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "retry_wait")
        self.assertIsNotNone(self.store.pending_dispatch(now_ms=1_012))

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

    def test_retained_workspace_does_not_reopen_a_blocked_failed_task(
        self,
    ) -> None:
        self.seed(criteria=())
        child = child_task(
            "task:workspace-failure",
            parent="task:1",
            target="participant:b",
        )
        child.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/workspace-failure",
                "workspaceBindingId": "binding:workspace-failure",
                "workspaceLifecycleState": "materialized",
                "workspaceCleanupState": "not_authorized",
                "workspaceAttentionRequired": False,
                "workspaceIntegrationState": "pending",
                "workspaceIntegrationRef": None,
            }
        )
        self.store.create_task(child, now_ms=3)
        dispatch_id = "dispatch:workspace-failure"
        self.store.enqueue_dispatch(
            dispatch(
                dispatch_id,
                task_id="task:workspace-failure",
                target="participant:b",
                key="workspace-failure",
            ),
            now_ms=4,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:workspace-failure",
            now_ms=5,
        )
        self.store.record_runtime_failure(
            dispatch_id,
            generation=0,
            source_event_id="event:workspace-failure",
            runtime_turn_id="turn:workspace-failure",
            dispatch_attempt=0,
            now_ms=6,
            retryable=True,
            had_tool_activity=True,
            reason_code="tool_activity_observed",
        )

        retained = self.store.record_workspace_lifecycle(
            "task:workspace-failure",
            operation="retain",
            workspace_result={
                "workspaceBindingId": "binding:workspace-failure",
                "workspaceLifecycleState": "failed",
                "cleanupState": "retained",
                "attentionRequired": True,
                "terminalReason": "runtime failed after workspace activity",
            },
            now_ms=7,
        )

        self.assertEqual(retained["state"], "blocked")
        self.assertEqual(
            self.store.task("task:workspace-failure")["state"],
            "blocked",
        )
        retried = self.store.apply_control_command(
            control_command("command:workspace-retry", "retry_root", now_ms=8)
        )
        self.assertEqual(
            retried["details"]["retriedTaskIds"],
            ["task:workspace-failure"],
        )

    def test_missing_commit_after_tool_activity_blocks_without_replay(
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

        blocked = self.store.record_runtime_failure(
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
        self.assertEqual(blocked["receiptKind"], "runtime_failed")
        self.assertEqual(blocked["details"]["reasonCode"], "room_commit_missing")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(self.store.dispatch(dispatch_id)["state"], "failed")
        self.assertEqual(self.store.resource_limits("root:1")["retry_used"], 0)
        with sqlite3.connect(self.db_path) as connection:
            reason = connection.execute(
                """SELECT reason_code FROM room_kernel_dead_letters
                   WHERE dispatch_id=?""",
                (dispatch_id,),
            ).fetchone()[0]
        self.assertEqual(reason, "room_commit_missing")

    def test_abandoning_one_workspace_does_not_clear_another_root_blocker(
        self,
    ) -> None:
        self.seed(criteria=())

        def blocked_workspace_task(task_id: str, binding_id: str) -> dict[str, object]:
            payload = child_task(
                task_id,
                parent="task:1",
                target=f"participant:{task_id}",
            )
            payload.update(
                {
                    "workspacePolicy": "isolated_writable",
                    "workspaceRoot": f"/tmp/{task_id}",
                    "workspaceBindingId": binding_id,
                    "workspaceLifecycleState": "blocked",
                    "workspaceCleanupState": "retained",
                    "workspaceAttentionRequired": True,
                    "workspaceIntegrationState": "pending",
                    "workspaceIntegrationRef": None,
                    "state": "blocked",
                }
            )
            return payload

        for index in (1, 2):
            self.store.create_task(
                blocked_workspace_task(
                    f"task:workspace:{index}",
                    f"binding:workspace:{index}",
                ),
                now_ms=2 + index,
            )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_roots SET state='blocked' WHERE root_id='root:1'"
            )

        def abandon(task_index: int, now_ms: int) -> None:
            self.store.record_workspace_lifecycle(
                f"task:workspace:{task_index}",
                operation="abandon",
                workspace_result={
                    "workspaceBindingId": f"binding:workspace:{task_index}",
                    "workspaceLifecycleState": "abandoned",
                    "cleanupState": "authorized",
                    "attentionRequired": False,
                    "terminalReason": "receipted test abandonment",
                    "abandonmentReceiptId": f"receipt:abandon:{task_index}",
                    "abandonmentReceiptSha256": str(task_index) * 64,
                    "abandonmentSnapshotSha256": str(task_index) * 64,
                },
                now_ms=now_ms,
            )

        abandon(1, 10)
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(
            self.store.task("task:workspace:2")["state"],
            "blocked",
        )

        abandon(2, 11)
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_report_readiness_ignores_one_canonical_abandoned_failure(
        self,
    ) -> None:
        self.seed(criteria=())
        abandoned_task = child_task(
            "task:abandoned-failure",
            parent="task:1",
            target="participant:worker",
        )
        abandoned_task.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/abandoned-failure",
                "workspaceBindingId": "binding:abandoned-failure",
                "workspaceLifecycleState": "materialized",
                "workspaceCleanupState": "not_authorized",
                "workspaceAttentionRequired": False,
                "workspaceIntegrationState": "pending",
                "workspaceIntegrationRef": None,
            }
        )
        self.store.create_task(abandoned_task, now_ms=3)
        failed_dispatch = dispatch(
            "dispatch:abandoned-failure",
            task_id="task:abandoned-failure",
            target="participant:worker",
            key="abandoned-failure",
        )
        failed_dispatch["intentKind"] = "revise"
        self.store.enqueue_dispatch(failed_dispatch, now_ms=4)
        self.accept_runtime_attempt(
            "dispatch:abandoned-failure",
            turn_id="turn:abandoned-failure",
            now_ms=5,
        )
        self.store.record_runtime_failure(
            "dispatch:abandoned-failure",
            generation=0,
            source_event_id="event:abandoned-failure",
            runtime_turn_id="turn:abandoned-failure",
            dispatch_attempt=0,
            now_ms=6,
            retryable=True,
            had_tool_activity=True,
            reason_code="room_commit_missing",
        )
        self.store.record_workspace_lifecycle(
            "task:abandoned-failure",
            operation="abandon",
            workspace_result={
                "workspaceBindingId": "binding:abandoned-failure",
                "workspaceLifecycleState": "abandoned",
                "cleanupState": "cleaned",
                "attentionRequired": False,
                "terminalReason": "receipted clean abandonment",
                "abandonmentReceiptId": "receipt:abandoned-failure",
                "abandonmentReceiptSha256": "a" * 64,
                "abandonmentSnapshotSha256": "b" * 64,
            },
            now_ms=7,
        )

        self.assertTrue(
            self.store.task_has_canonical_abandonment(
                "task:abandoned-failure"
            )
        )
        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 0, readiness)
        self.assertEqual(readiness["unresolvedDispatchFailures"], [])

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT receipt_id,payload_json
                   FROM room_kernel_receipts
                   WHERE root_id='root:1' AND receipt_kind='accepted'"""
            ).fetchall()
            abandonment_row = next(
                row
                for row in rows
                if json.loads(str(row[1]))["details"].get("purpose")
                == "workspace_abandon"
            )
            tampered = json.loads(str(abandonment_row[1]))
            tampered["details"]["abandonmentReceiptSha256"] = ""
            conn.execute(
                "UPDATE room_kernel_receipts SET payload_json=? "
                "WHERE receipt_id=?",
                (
                    json.dumps(tampered, ensure_ascii=False),
                    str(abandonment_row[0]),
                ),
            )

        self.assertFalse(
            self.store.task_has_canonical_abandonment(
                "task:abandoned-failure"
            )
        )
        tampered_readiness = self.store.report_readiness("root:1")
        self.assertEqual(tampered_readiness["unknownDispatches"], 1)
        self.assertEqual(
            tampered_readiness["unresolvedDispatchFailures"][0][
                "dispatchId"
            ],
            "dispatch:abandoned-failure",
        )

    def test_workspace_retry_rejects_an_unrelated_tool_invocation_receipt(
        self,
    ) -> None:
        root_payload = root("root:1")
        root_payload["facilitatorParticipantId"] = "participant:a"
        self.store.create_root(
            root_payload,
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.store.create_task(task("task:1", criteria=()), now_ms=2)
        parent_dispatch_id = "dispatch:workspace:facilitator"
        self.store.enqueue_dispatch(
            dispatch(
                parent_dispatch_id,
                key="workspace:facilitator",
                target="participant:a",
            ),
            now_ms=3,
        )
        self.store.set_dispatch_wait_state(
            parent_dispatch_id,
            "running",
            now_ms=4,
        )
        task_id = "task:workspace:retry"
        retry_task = child_task(
            task_id,
            parent="task:1",
            target="participant:worker",
        )
        retry_task.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/task-workspace-retry",
                "workspaceBindingId": "binding:workspace:retry",
                "workspaceLifecycleState": "blocked",
                "workspaceCleanupState": "retained",
                "workspaceAttentionRequired": True,
                "workspaceIntegrationState": "pending",
                "workspaceIntegrationRef": None,
                "state": "blocked",
            }
        )
        self.store.create_task(retry_task, now_ms=5)

        manifest_hash = "a" * 64
        unrelated_material = {
            "tool": "room_state",
            "arguments": {},
            "rootId": "root:1",
            "taskId": "task:1",
            "dispatchId": parent_dispatch_id,
            "generation": 0,
            "capabilityEpoch": 1,
        }
        command_hash = hashlib.sha256(
            json.dumps(
                unrelated_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        unrelated_command = {
            **unrelated_material,
            "commandHash": command_hash,
        }
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT INTO room_v2_capability_runtime_bindings(
                   session_id,manifest_id,manifest_hash,prompt_compile_receipt_id,
                   prompt_plan_hash,compiled_profile_id,compiled_profile_revision,
                   compiled_profile_hash,room_binding_json,participant_binding_json,
                   capability_epoch,state,created_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1,'active',6,6)""",
                (
                    "session:participant:a",
                    "manifest:workspace:retry",
                    manifest_hash,
                    "compile:workspace:retry",
                    "b" * 64,
                    "profile:test",
                    "profile:test-v1",
                    "c" * 64,
                    "{}",
                    "{}",
                ),
            )
            connection.execute(
                """INSERT INTO room_v2_tool_invocation_receipts(
                   receipt_id,manifest_id,manifest_hash,load_receipt_id,
                   invocation_key,canonical_tool_name,original_tool_name,
                   command_hash,command_json,authorization_state,created_at_ms)
                   VALUES (?,?,?,?,?,'room_state','room_state',?,?,'authorized',6)""",
                (
                    "invoke:unrelated-room-state",
                    "manifest:workspace:retry",
                    manifest_hash,
                    "load:unrelated-room-state",
                    "call:unrelated-room-state",
                    command_hash,
                    json.dumps(
                        unrelated_command,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

        retry_dispatch = dispatch(
            "dispatch:workspace:retry",
            key="workspace:retry",
            target="participant:worker",
            hop=1,
            depth=1,
            parent=parent_dispatch_id,
            task_id=task_id,
        )
        retry_dispatch["intentKind"] = "retry"
        retry_dispatch["triggerId"] = "invoke:unrelated-room-state"
        with self.assertRaisesRegex(RoomKernelFenceError, "invocation"):
            self.store.enqueue_workspace_retry(
                parent_dispatch_id=parent_dispatch_id,
                task_id=task_id,
                retry_dispatch=retry_dispatch,
                workspace_result={
                    "workspaceBindingId": "binding:workspace:retry",
                    "workspaceLifecycleState": "retry_bound",
                    "attentionRequired": False,
                },
                invocation_receipt_id="invoke:unrelated-room-state",
                now_ms=7,
            )

        self.assertEqual(self.store.task(task_id)["state"], "blocked")
        with self.assertRaises(KeyError):
            self.store.dispatch("dispatch:workspace:retry")


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

    def test_expired_lease_without_runtime_intent_retries_safely(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(
            dispatch("dispatch:preflight-crash", key="preflight-crash"),
            now_ms=10,
        )
        lease = self.store.lease_next(now_ms=11, ttl_ms=5)
        self.assertIsNotNone(lease)

        receipts = self.store.reconcile_expired_leases(now_ms=16)

        self.assertEqual(
            self.store.dispatch("dispatch:preflight-crash")["state"],
            "retry_wait",
        )
        self.assertEqual(
            self.store.outbox("dispatch:preflight-crash")["state"],
            "retry_wait",
        )
        self.assertEqual(
            self.store.lease("dispatch:preflight-crash")["state"],
            "completed",
        )
        self.assertEqual(receipts[0]["receiptKind"], "runtime_retry_scheduled")
        self.assertFalse(receipts[0]["details"]["hadRuntimeIntent"])
        self.assertEqual(self.store.root("root:1")["state"], "running")
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 0)

    def test_expired_lease_after_runtime_intent_becomes_unknown_and_dead_letter(
        self,
    ) -> None:
        self.seed()
        self.store.enqueue_dispatch(dispatch("dispatch:crash", key="crash"), now_ms=10)
        lease = self.store.lease_next(now_ms=11, ttl_ms=5)
        self.assertIsNotNone(lease)
        self.store.record_runtime_dispatch_intent(
            "dispatch:crash",
            now_ms=12,
        )

        receipts = self.store.reconcile_expired_leases(now_ms=16)

        self.assertEqual(self.store.dispatch("dispatch:crash")["state"], "unknown")
        self.assertEqual(self.store.outbox("dispatch:crash")["state"], "dead_letter")
        self.assertEqual(self.store.lease("dispatch:crash")["state"], "expired")
        self.assertEqual(receipts[0]["receiptKind"], "dispatch_unknown")
        self.assertEqual(self.store.receipt(str(receipts[0]["receiptId"])), receipts[0])
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)
        attempt = self.store.dispatch_attempts("dispatch:crash")[0]
        self.assertEqual(attempt["state"], "unknown")
        self.assertEqual(
            attempt["terminalReceipt"]["reasonCode"],
            "lease_expired_result_unknown",
        )
        self.assertIsNone(self.store.lease_next(now_ms=17, ttl_ms=5))
        final = self.store.finalize_root("root:1", now_ms=18)
        self.assertEqual(final["status"], "rejected")
        self.assertEqual(final["details"]["unknownDispatches"], 1)

    def test_cancel_completion_requires_exact_intent_and_active_runtime_lineage(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:cancel-lineage"
        turn_id = "turn:cancel-lineage"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="cancel-lineage"),
            now_ms=10,
        )
        self.accept_runtime_attempt(dispatch_id, turn_id=turn_id, now_ms=11)
        self.store.cancel_root("root:1", now_ms=12)
        requested_attempt = self.store.dispatch_attempts(dispatch_id)[0]
        self.assertEqual(requested_attempt["state"], "cancel_requested")
        self.assertEqual(
            requested_attempt["runtimeReceipt"]["turnId"],
            turn_id,
        )
        self.assertEqual(requested_attempt["terminalReceipt"], {})

        intent = self.store.lease_cancel(now_ms=13)
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent["turnId"], turn_id)
        self.assertEqual(intent["capabilityEpoch"], 1)
        receipt = {
            **intent,
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "cancellationSurfaces": {
                surface: {
                    "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                    "surface": surface,
                    "state": "terminated",
                    "targetIds": [],
                }
                for surface in (
                    "provider",
                    "tool",
                    "exec",
                    "retry",
                    "compaction",
                    "branch_summary",
                    "timer",
                    "continuation",
                    "session",
                )
            },
            "pendingTargets": [],
        }
        for field in (
            "cancelId",
            "rootId",
            "dispatchId",
            "sessionId",
            "generation",
            "turnId",
            "capabilityEpoch",
        ):
            forged = dict(receipt)
            forged[field] = (
                int(receipt[field]) + 1
                if field in {"generation", "capabilityEpoch"}
                else f"forged:{field}"
            )
            with self.subTest(field=field), self.assertRaisesRegex(
                RoomKernelFenceError,
                "does not match",
            ):
                self.store.complete_cancel(
                    str(intent["cancelId"]),
                    forged,
                    now_ms=14,
                )

        completed = self.store.complete_cancel(
            str(intent["cancelId"]),
            receipt,
            now_ms=15,
        )
        self.assertEqual(completed["state"], "applied")
        cancelled_attempt = self.store.dispatch_attempts(dispatch_id)[0]
        self.assertEqual(cancelled_attempt["state"], "cancelled")
        self.assertEqual(
            cancelled_attempt["runtimeReceipt"]["turnId"],
            turn_id,
        )
        self.assertEqual(
            cancelled_attempt["terminalReceipt"]["cancelId"],
            intent["cancelId"],
        )

    def test_apply_commit_completes_runtime_effect_and_excludes_it_from_cancel(self) -> None:
        self.seed(criteria=())
        dispatch_id = "dispatch:completed-effect"
        self.store.enqueue_dispatch(
            dispatch(dispatch_id, key="completed-effect"),
            now_ms=10,
        )
        self.accept_runtime_attempt(
            dispatch_id,
            turn_id="turn:completed-effect",
            now_ms=11,
        )

        applied = self.store.apply_commit(
            commit("commit:completed-effect", dispatch_id),
            generation=0,
            now_ms=12,
        )

        self.assertEqual(applied["status"], "applied")
        with sqlite3.connect(self.db_path) as connection:
            runtime_state = connection.execute(
                "SELECT state FROM room_kernel_runtime_effects WHERE dispatch_id=?",
                (dispatch_id,),
            ).fetchone()[0]
        self.assertEqual(runtime_state, "completed")
        self.assertEqual(self.store.abort_scope(dispatch_id)["state"], "completed")

        cancelled = self.store.cancel_target(
            root_id="root:1",
            target_kind="dispatch",
            target_id=dispatch_id,
            now_ms=13,
        )
        self.assertEqual(cancelled["details"]["cancelIntents"], 0)
        self.assertIsNone(self.store.lease_cancel(now_ms=14))
        self.assertEqual(self.store.abort_scope(dispatch_id)["state"], "completed")

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
                            "impact": "critical",
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
        workspace_ledger = RoomWorkspaceLedgerStore(self.db_path)
        binding, _ = workspace_ledger.reserve_binding(
            room_id="room:1",
            root_id="root:1",
            task_id="task:1",
            work_item_id="work:test",
            dispatch_id="dispatch:worker",
            requirement_revision="requirement:test",
            acceptance_aliases=["ac:1"],
            participant_id="participant:worker",
            session_id="session:worker",
            repository_id="a" * 64,
            base_root="/tmp/room-base",
            base_commit="git:base",
            workspace_root="/tmp/room-child",
            workspace_policy="isolated_writable",
            creation_reason="workspace receipt projection test",
            now_ms=3,
        )
        binding_id = str(binding["workspaceBindingId"])
        payload = self.store.task("task:1")
        payload.update(
            {
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": "/tmp/room-child",
                "workspaceBaseRoot": "/tmp/room-base",
                "workspaceBaseCommit": "git:base",
                "workspaceBindingId": binding_id,
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
                "workspaceBindingId": binding_id,
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
                    "baseCommit": "git:base",
                    "workspaceSnapshotSha256": "c" * 64,
                    "patchSha256": "d" * 64,
                    "deliveredAtMs": 5,
                    "resultSummary": "Scoped delivery",
                    "manifestSha256": "f" * 64,
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
        self.store.enqueue_dispatch(
            dispatch("dispatch:worker", key="workspace-worker"),
            now_ms=5,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:worker",
            "running",
            now_ms=5,
        )
        self.store.apply_commit(
            commit(
                "commit:workspace-worker",
                "dispatch:worker",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=6,
        )
        conflict = self.store.record_workspace_integration_failure(
            "task:1",
            integration_ref="integration:stable",
            workspace_result={
                "integrated": False,
                "workspaceBindingId": binding_id,
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
        workspace_ledger.mark_materialized(
            binding_id,
            workspace_snapshot_sha256="b" * 64,
            actor_ref="participant:worker",
            now_ms=6,
        )
        workspace_ledger.record_work_started(
            binding_id,
            dispatch_id="dispatch:worker",
            actor_ref="participant:worker",
            now_ms=6,
        )
        workspace_ledger.record_delivery(
            binding_id,
            delivery_revision="sha256:" + "b" * 64,
            delivery_head="git:base",
            workspace_snapshot_sha256="c" * 64,
            patch_sha256="d" * 64,
            manifest_sha256="f" * 64,
            artifacts=["README.md"],
            verification_refs=["test:focused"],
            residual_risks=[],
            actor_ref="participant:worker",
            now_ms=6,
        )
        workspace_ledger.record_source_lease_revoked(
            binding_id,
            delivery_revision="sha256:" + "b" * 64,
            workspace_snapshot_sha256="c" * 64,
            patch_sha256="d" * 64,
            patch_artifact_path="/tmp/sealed.patch",
            patch_artifact_size=1,
            owner_session_id="session:worker",
            revoked_policy_sha256="9" * 64,
            workspace_content_sha256="8" * 64,
            changed_files=["README.md"],
            actor_ref="system:test",
            now_ms=6,
        )
        workspace_ledger.begin_integration(
            binding_id,
            integration_ref="integration:stable",
            patch_sha256="d" * 64,
            target_before_snapshot_sha256="7" * 64,
            actor_ref="participant:facilitator",
            now_ms=6,
        )
        workspace_ledger.record_target_applied(
            binding_id,
            integration_ref="integration:stable",
            patch_sha256="d" * 64,
            target_before_snapshot_sha256="7" * 64,
            target_after_snapshot_sha256="e" * 64,
            target_snapshot_provider=lambda: "e" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        workspace_ledger.record_integrated(
            binding_id,
            integration_ref="integration:stable",
            patch_sha256="d" * 64,
            integrated_revision="git:integrated",
            integrated_snapshot_sha256="e" * 64,
            changed_files=["README.md"],
            target_snapshot_provider=lambda: "e" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        delivery_receipt = workspace_ledger.delivery_receipt(binding_id)
        source_receipt = workspace_ledger.source_lease_receipt(binding_id)
        target_receipt = workspace_ledger.target_applied_receipt(binding_id)
        integrated_receipt = workspace_ledger.integrated_receipt(binding_id)
        workspace_ledger.record_cleanup(
            binding_id,
            result="failed",
            reason="legacy cleanup deferred",
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        failed_cleanup_receipt = workspace_ledger.cleanup_receipt(binding_id)
        assert (
            delivery_receipt
            and source_receipt
            and target_receipt
            and integrated_receipt
            and failed_cleanup_receipt
        )
        stranded = self.store.record_workspace_integration(
            "task:1",
            integration_ref="integration:stable",
            workspace_result={
                "integrated": True,
                "workspaceBindingId": binding_id,
                "integrationRef": "integration:stable",
                "integrationPatchSha256": "d" * 64,
                "integratedRevision": "git:integrated",
                "integratedSnapshotSha256": "e" * 64,
                "workspaceLifecycleState": "cleanup_failed",
                "cleanupState": "failed",
                "reason": "legacy cleanup deferred",
                "attentionRequired": True,
                "workspaceDeliveryReceiptId": delivery_receipt["eventId"],
                "workspaceDeliveryReceiptSha256": delivery_receipt[
                    "payloadSha256"
                ],
                "workspaceSourceLeaseReceiptId": source_receipt["eventId"],
                "workspaceSourceLeaseReceiptSha256": source_receipt[
                    "payloadSha256"
                ],
                "workspaceTargetAppliedReceiptId": target_receipt["eventId"],
                "workspaceTargetAppliedReceiptSha256": target_receipt[
                    "payloadSha256"
                ],
                "workspaceIntegratedReceiptId": integrated_receipt["eventId"],
                "workspaceIntegratedReceiptSha256": integrated_receipt[
                    "payloadSha256"
                ],
                "workspaceCleanupReceiptId": failed_cleanup_receipt["eventId"],
                "workspaceCleanupReceiptSha256": failed_cleanup_receipt[
                    "payloadSha256"
                ],
            },
            now_ms=7,
        )
        self.assertEqual(stranded["workspaceIntegrationState"], "applied")
        self.assertEqual(stranded["workspaceCleanupState"], "failed")
        self.assertTrue(stranded["workspaceAttentionRequired"])
        workspace_ledger.record_writer_quiescence(
            binding_id,
            receipt={
                "schemaVersion": "wisdom-weasel.room-workspace-writer-quiescence.v1",
                "receiptRevision": "test:writer-quiescence",
                "workspaceBindingId": binding_id,
                "rootId": "root:1",
                "taskId": "task:1",
                "dispatchId": "dispatch:worker",
                "deliveryRevision": "sha256:" + "b" * 64,
                "ownerSessionId": "session:worker",
                "sourceLeaseReceiptId": source_receipt["eventId"],
                "sourceLeaseReceiptSha256": source_receipt["payloadSha256"],
                "integratedReceiptId": integrated_receipt["eventId"],
                "integratedReceiptSha256": integrated_receipt["payloadSha256"],
                "foregroundMutatingInvocations": {
                    "known": True,
                    "activeCount": 0,
                },
                "backgroundWork": {"known": True, "activeCount": 0},
                "managedPiTurn": {
                    "known": True,
                    "settled": True,
                    "sessionId": "session:worker",
                    "dispatchId": "dispatch:worker",
                },
            },
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        workspace_ledger.record_quarantined(
            binding_id,
            quarantined_workspace_root="/tmp/room-quarantine",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        workspace_ledger.authorize_cleanup_removal(
            binding_id,
            quarantined_workspace_root="/tmp/room-quarantine",
            vault_workspace_root="/tmp/room-vault",
            workspace_content_sha256="8" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="participant:facilitator",
            now_ms=7,
        )
        removal_receipt = (
            workspace_ledger.cleanup_removal_authorization_receipt(binding_id)
        )
        assert removal_receipt is not None
        workspace_ledger.record_vaulted(
            binding_id,
            removal_authorization_receipt_id=str(removal_receipt["eventId"]),
            removal_authorization_receipt_sha256=str(
                removal_receipt["payloadSha256"]
            ),
            quarantined_workspace_root="/tmp/room-quarantine",
            vault_workspace_root="/tmp/room-vault",
            authorized_workspace_content_sha256="8" * 64,
            vault_content_sha256="7" * 64,
            target_snapshot_sha256="e" * 64,
            actor_ref="system:guarded-workspace-cleanup",
            now_ms=7,
        )
        workspace_ledger.record_cleanup(
            binding_id,
            result="cleaned",
            reason="test cleanup",
            actor_ref="participant:facilitator",
            now_ms=7,
            retained_workspace_root="/tmp/room-vault",
        )
        source_receipt = workspace_ledger.source_lease_receipt(binding_id)
        target_receipt = workspace_ledger.target_applied_receipt(binding_id)
        integrated_receipt = workspace_ledger.integrated_receipt(binding_id)
        writer_receipt = workspace_ledger.writer_quiescence_receipt(binding_id)
        quarantine_receipt = workspace_ledger.quarantine_receipt(binding_id)
        removal_receipt = (
            workspace_ledger.cleanup_removal_authorization_receipt(binding_id)
        )
        vault_receipt = workspace_ledger.vault_receipt(binding_id)
        cleanup_receipt = workspace_ledger.cleanup_receipt(binding_id)
        assert (
            delivery_receipt
            and source_receipt
            and target_receipt
            and integrated_receipt
            and writer_receipt
            and quarantine_receipt
            and removal_receipt
            and vault_receipt
            and cleanup_receipt
        )
        with self.assertRaisesRegex(
            (RoomKernelFenceError, ValueError),
            "workspaceWriterQuiescenceReceiptId",
        ):
            self.store.record_workspace_integration(
                "task:1",
                integration_ref="integration:stable",
                workspace_result={
                    "integrated": True,
                    "workspaceBindingId": binding_id,
                    "integrationRef": "integration:stable",
                    "integrationPatchSha256": "d" * 64,
                    "integratedRevision": "git:integrated",
                    "integratedSnapshotSha256": "e" * 64,
                    "workspaceLifecycleState": "cleaned",
                    "cleanupState": "cleaned",
                    "attentionRequired": False,
                    "workspaceDeliveryReceiptId": delivery_receipt["eventId"],
                    "workspaceDeliveryReceiptSha256": delivery_receipt[
                        "payloadSha256"
                    ],
                    "workspaceSourceLeaseReceiptId": source_receipt["eventId"],
                    "workspaceSourceLeaseReceiptSha256": source_receipt[
                        "payloadSha256"
                    ],
                    "workspaceTargetAppliedReceiptId": target_receipt["eventId"],
                    "workspaceTargetAppliedReceiptSha256": target_receipt[
                        "payloadSha256"
                    ],
                    "workspaceIntegratedReceiptId": integrated_receipt["eventId"],
                    "workspaceIntegratedReceiptSha256": integrated_receipt[
                        "payloadSha256"
                    ],
                    "workspaceCleanupReceiptId": cleanup_receipt["eventId"],
                    "workspaceCleanupReceiptSha256": cleanup_receipt[
                        "payloadSha256"
                    ],
                },
                now_ms=8,
            )
        restarted = AgentService(
            db_path=self.db_path,
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=Path(self.tmp.name) / "agent-config",
                session_dir=Path(self.tmp.name) / "sessions",
                logs_dir=Path(self.tmp.name) / "logs",
            ),
            room_kernel_worker_enabled=False,
            background_job_execution_owner=False,
        )
        try:
            integrated = restarted.room_kernel.task("task:1")
            accepted_evidence = (
                restarted.room_kernel.accepted_evidence_by_criterion("root:1")
            )
        finally:
            restarted.close()
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
        self.assertTrue(accepted_evidence["ac:1"])
        with sqlite3.connect(self.db_path) as conn:
            receipts_after_first_projection = int(
                conn.execute(
                    "SELECT COUNT(*) FROM room_kernel_receipts"
                ).fetchone()[0]
            )
        restarted_again = AgentService(
            db_path=self.db_path,
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=Path(self.tmp.name) / "agent-config-2",
                session_dir=Path(self.tmp.name) / "sessions-2",
                logs_dir=Path(self.tmp.name) / "logs-2",
            ),
            room_kernel_worker_enabled=False,
            background_job_execution_owner=False,
        )
        try:
            replayed = restarted_again.room_kernel.task("task:1")
        finally:
            restarted_again.close()
        self.assertEqual(replayed, integrated)
        with sqlite3.connect(self.db_path) as conn:
            receipts_after_replay = int(
                conn.execute(
                    "SELECT COUNT(*) FROM room_kernel_receipts"
                ).fetchone()[0]
            )
        self.assertEqual(
            receipts_after_replay,
            receipts_after_first_projection,
        )

    def test_revision_bound_accepted_review_and_integration_finalize_once(self) -> None:
        self.seed()
        integrated_payload = self.store.task("task:1")
        integrated_payload.update(
            {
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
            "currentOwnerParticipantId": "participant:reviewer",
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
            target="participant:reviewer",
        )
        review_dispatch["intentKind"] = "review"
        self.store.enqueue_dispatch(review_dispatch, now_ms=5)
        self.store.set_dispatch_wait_state(
            review_dispatch_id,
            "running",
            now_ms=5,
        )
        self.record_runtime_evidence(
            review_dispatch_id,
            evidence_ref="test:room-kernel",
            now_ms=6,
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
        open_advisory_commit = {
            **review_commit,
            "reviewFindings": [
                {
                    "findingId": "finding:open-advisory",
                    "fingerprint": canonical_review_finding_fingerprint(
                        category="maintainability",
                        scope={"criterionId": "ac:1"},
                        observation="命名仍可改进",
                        expected="明确处置后再结束复核",
                        user_impact="当前功能不受影响",
                    ),
                    "gateEffect": "advisory",
                    "impact": "normal",
                    "category": "maintainability",
                    "scope": {"criterionId": "ac:1"},
                    "observation": "命名仍可改进",
                    "expected": "明确处置后再结束复核",
                    "userImpact": "当前功能不受影响",
                    "evidenceRefs": ["test:room-kernel"],
                    "reproduction": ["检查相关命名"],
                    "state": "open",
                    "dispositionRationale": None,
                    "ownerParticipantId": None,
                    "firstSeenRevision": target_revision,
                    "lastCheckedRevision": target_revision,
                    "failedRechecks": 0,
                    "response": None,
                }
            ],
        }
        applied = self.store.apply_commit(
            open_advisory_commit,
            generation=0,
            now_ms=6,
        )
        self.assertEqual(applied["status"], "applied")
        accepted_review = self.store.task(review_task_id)
        self.assertEqual(
            accepted_review["reviewState"],
            "accepted_with_notes",
        )
        self.assertEqual(
            accepted_review["reviewTargetRevision"],
            target_revision,
        )
        forged_authors = {
            **accepted_review,
            "reviewAuthorParticipantIds": ["participant:reviewer"],
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        forged_authors,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    review_task_id,
                ),
            )
        rejected = self.store.finalize_root("root:1", now_ms=7)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            rejected["details"]["reason"],
            "reviewer_not_independent",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        accepted_review,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    review_task_id,
                ),
            )
        with patch.object(
            self.store,
            "_review_target_revision_locked",
            wraps=self.store._review_target_revision_locked,
        ) as revision_check:
            terminal = self.store.finalize_root("root:1", now_ms=8)
        terminal_revision_calls = [
            call
            for call in revision_check.call_args_list
            if call.kwargs.get("root_id") == "root:1"
        ]
        self.assertTrue(terminal_revision_calls)
        self.assertTrue(
            all(
                call.kwargs.get("commit_not_after_ms") is None
                for call in terminal_revision_calls
            ),
            "terminal review validation must include every later target commit",
        )
        replay = self.store.finalize_root("root:1", now_ms=9)
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
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "exact coordinator result",
        ):
            self.store.record_workspace_integration(
                "task:1",
                integration_ref="integration:post-review-mutation",
                now_ms=13,
            )
        self.assertEqual(
            self.store.review_target_revision(
                root_id="root:1",
                task_ids=["task:1"],
            ),
            pending_revision,
        )

    def test_latest_review_attempt_is_selected_per_reviewed_task_lineage(
        self,
    ) -> None:
        self.seed()
        self.store.create_task(task("task:2"), now_ms=2)

        def create_review(
            *,
            review_task_id: str,
            target_task_id: str,
            review_round: int,
            revision: int,
            now_ms: int,
        ) -> None:
            snapshot = {
                **task(review_task_id),
                "taskKind": "review",
                "currentOwnerParticipantId": (
                    f"participant:reviewer:{review_task_id}"
                ),
                "reviewState": "required",
                "reviewOfTaskIds": [target_task_id],
                "reviewAuthorParticipantIds": ["participant:a"],
                "reviewEvidenceNotBeforeMs": now_ms,
                "reviewRound": review_round,
                "reviewFindings": [],
                "revision": revision,
                "workspacePolicy": "read_only",
                "workspaceRoot": f"/tmp/{review_task_id}",
                "workspaceBaseRoot": f"/tmp/{review_task_id}",
                "workspaceSnapshotSha256": (
                    hashlib.sha256(review_task_id.encode("utf-8")).hexdigest()
                ),
                "workspaceIntegrationRef": "",
            }
            snapshot["reviewTargetRevision"] = (
                self.store.review_target_revision(
                    root_id="root:1",
                    task_ids=[target_task_id],
                    review_snapshot=snapshot,
                )
            )
            self.store.create_task(snapshot, now_ms=now_ms)

        create_review(
            review_task_id="task:review:task-1:round-2",
            target_task_id="task:1",
            review_round=2,
            revision=2,
            now_ms=3,
        )
        create_review(
            review_task_id="task:review:task-1:late-round-1",
            target_task_id="task:1",
            review_round=1,
            revision=1,
            now_ms=10,
        )
        create_review(
            review_task_id="task:review:task-2",
            target_task_id="task:2",
            review_round=1,
            revision=1,
            now_ms=11,
        )

        attempts = self.store.latest_review_attempts("root:1")
        selected = {
            tuple(attempt["reviewOfTaskIds"]): attempt["taskId"]
            for attempt in attempts
        }
        self.assertEqual(
            selected,
            {
                ("task:1",): "task:review:task-1:round-2",
                ("task:2",): "task:review:task-2",
            },
        )

    def test_defined_lane_gate_uses_actual_split_graph_not_declared_worker(
        self,
    ) -> None:
        self.seed()
        with patch.object(
            self.store,
            "definition_fence",
            return_value={
                "implementationParticipantId": "participant:declared",
                "executionDispatchId": "dispatch:declared",
            },
        ):
            with self.store._connect() as conn:
                lane = self.store._defined_lane_fences_locked(
                    conn,
                    root_id="root:1",
                )

        self.assertTrue(lane["definitionRequired"])
        self.assertEqual(lane["lanePlanDispatchIds"], [])
        self.assertEqual(lane["fences"], [])

    def test_receipted_retry_supersedes_historical_failed_dispatch_readiness(
        self,
    ) -> None:
        self.seed()
        self.store.enqueue_dispatch(
            dispatch("dispatch:failed-attempt", key="failed-attempt"),
            now_ms=3,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=4 "
                "WHERE dispatch_id='dispatch:failed-attempt'"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=4 "
                "WHERE dispatch_id='dispatch:failed-attempt'"
            )

        retry = dispatch(
            "dispatch:successful-retry",
            key="successful-retry",
        )
        retry["intentKind"] = "retry"
        self.store.enqueue_dispatch(retry, now_ms=5)
        self.store.set_dispatch_wait_state(
            "dispatch:successful-retry",
            "running",
            now_ms=6,
        )
        self.store.apply_commit(
            commit(
                "commit:successful-retry",
                "dispatch:successful-retry",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=7,
        )
        with self.store._connect(immediate=True) as conn:
            self.store._receipt(
                conn,
                root_id="root:1",
                command_id=None,
                receipt_kind="accepted",
                status="applied",
                generation=0,
                details={
                    "purpose": "workspace_retry",
                    "parentTaskId": "task:coordinator",
                    "parentDispatchId": "dispatch:coordinator",
                    "childTaskId": "task:1",
                    "childDispatchId": "dispatch:successful-retry",
                    "workspaceBindingId": "workspace:test",
                    "invocationReceiptId": "invoke:retry",
                },
                now_ms=8,
            )

        readiness = self.store.report_readiness("root:1")
        self.assertEqual(readiness["unknownDispatches"], 0)
        self.assertNotIn("root_not_quiescent", readiness["reasons"])

    def test_acceptance_evidence_uses_only_current_task_attempt(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(
            dispatch("dispatch:evidence-pass", key="evidence-pass"),
            now_ms=3,
        )
        self.store.enqueue_dispatch(
            dispatch("dispatch:evidence-newer", key="evidence-newer"),
            now_ms=4,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:evidence-pass",
            "running",
            now_ms=5,
        )
        self.store.apply_commit(
            commit(
                "commit:evidence-pass",
                "dispatch:evidence-pass",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=6,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='failed',updated_at_ms=7 "
                "WHERE dispatch_id='dispatch:evidence-newer'"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=7 "
                "WHERE dispatch_id='dispatch:evidence-newer'"
            )

        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:1"),
            {},
        )
        readiness = self.store.report_readiness("root:1")
        self.assertEqual(
            readiness["unprovenAcceptanceCriteria"],
            ["ac:1"],
        )

    def test_failed_report_dispatch_has_one_receipted_replacement(self) -> None:
        self.seed()
        self.store.enqueue_dispatch(
            dispatch("dispatch:work-for-report", key="work-for-report"),
            now_ms=3,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:work-for-report",
            "running",
            now_ms=4,
        )
        self.store.apply_commit(
            commit(
                "commit:work-for-report",
                "dispatch:work-for-report",
                coverage=("ac:1",),
            ),
            generation=0,
            now_ms=5,
        )

        def report_workspace(seed: str) -> dict[str, object]:
            return {
                "workspacePolicy": "read_only",
                "workspaceRoot": f"/tmp/report-{seed}",
                "workspaceBaseRoot": f"/tmp/report-{seed}",
                "workspaceSnapshotSha256": hashlib.sha256(
                    seed.encode("utf-8")
                ).hexdigest(),
                "workspaceIntegrationRef": "",
            }

        first = self.store.ensure_report_dispatch(
            "root:1",
            reporter_participant_id="kernel-v2",
            reporter_session_id="session:reporter",
            workspace=report_workspace("first"),
            now_ms=6,
        )
        self.assertTrue(first["created"])
        first_dispatch_id = str(first["dispatch"]["dispatchId"])
        first_task_id = str(first["task"]["taskId"])
        self.accept_runtime_attempt(
            first_dispatch_id,
            turn_id="turn:first-report-failed",
            now_ms=7,
        )
        failed = self.store.record_runtime_failure(
            first_dispatch_id,
            generation=0,
            source_event_id="event:first-report-failed",
            runtime_turn_id="turn:first-report-failed",
            dispatch_attempt=0,
            now_ms=8,
        )
        self.assertEqual(failed["receiptKind"], "runtime_failed")
        self.assertEqual(self.store.task(first_task_id)["state"], "failed")
        failed_readiness = self.store.report_readiness("root:1")
        self.assertEqual(failed_readiness["openTasks"], 0)
        self.assertTrue(failed_readiness["ready"], failed_readiness)

        replacement = self.store.ensure_report_dispatch(
            "root:1",
            reporter_participant_id="kernel-v2",
            reporter_session_id="session:reporter",
            workspace=report_workspace("replacement"),
            now_ms=9,
        )
        self.assertTrue(replacement["created"])
        self.assertNotEqual(
            replacement["dispatch"]["dispatchId"],
            first_dispatch_id,
        )
        self.assertEqual(
            replacement["receipt"]["details"]["replacesReportTaskId"],
            first_task_id,
        )
        self.assertEqual(
            replacement["receipt"]["details"][
                "replacesReportDispatchId"
            ],
            first_dispatch_id,
        )
        self.assertEqual(
            replacement["receipt"]["details"]["reportAttempt"],
            1,
        )
        self.assertFalse(self.store.is_report_dispatch(first_dispatch_id))
        self.assertTrue(
            self.store.is_report_dispatch(
                str(replacement["dispatch"]["dispatchId"])
            )
        )

        replacement_dispatch_id = str(
            replacement["dispatch"]["dispatchId"]
        )
        replacement_task_id = str(replacement["task"]["taskId"])
        self.accept_runtime_attempt(
            replacement_dispatch_id,
            turn_id="turn:replacement-report",
            now_ms=10,
        )
        report_commit = commit(
            "commit:replacement-report",
            replacement_dispatch_id,
            coverage=("ac:1",),
            task_id=replacement_task_id,
        )
        report_commit["action"] = "post"
        report_commit["postProposal"] = post_proposal(
            "commit:replacement-report",
            replacement_dispatch_id,
            task_id=replacement_task_id,
            author="kernel-v2",
        )
        report_commit["continuation"] = {"decision": "complete"}
        self.store.apply_commit(
            report_commit,
            generation=0,
            now_ms=11,
            post_proposal=report_commit["postProposal"],
        )
        terminal = self.store.finalize_root("root:1", now_ms=12)
        self.assertEqual(terminal["receiptKind"], "terminal")
        self.assertEqual(terminal["status"], "applied")
        with sqlite3.connect(self.db_path) as conn:
            final_posts = conn.execute(
                "SELECT payload_json FROM room_kernel_posts WHERE root_id=?",
                ("root:1",),
            ).fetchall()
        self.assertEqual(
            sum(
                1
                for row in final_posts
                if json.loads(str(row[0])).get("kind") == "result"
            ),
            1,
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
