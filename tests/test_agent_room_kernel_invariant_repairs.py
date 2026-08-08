from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from rag_ime.agent_room_context import RoomContextLedgerStore
from rag_ime.agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    _stable_id,
)
from rag_ime.agent_room_kernel_contracts import ROOM_POST_SCHEMA_VERSION
from rag_ime.agent_room_kernel_projection import RoomKernelProjection
from rag_ime.agent_room_requirements import RequirementGovernanceStore
from rag_ime.db import latest_migration_version
from tests.test_agent_room_kernel import (
    child_task,
    commit,
    control_command,
    dispatch,
    post_proposal,
    root,
    task,
    wait_commit,
)


class RoomKernelInvariantRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-kernel-invariant-repairs-"
        )
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.assertEqual(self.store.initialize(), latest_migration_version())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_root(
        self,
        *,
        root_id: str = "root:1",
        task_id: str = "task:1",
        criteria: tuple[str, ...] = (),
        facilitator_id: str = "kernel-v2",
    ) -> None:
        root_payload = {
            **root(root_id),
            "facilitatorParticipantId": facilitator_id,
        }
        self.store.create_root_with_task(
            root_payload,
            task(task_id, root_id=root_id, criteria=criteria),
            budget=20,
            max_hops=4,
            max_depth=3,
            acceptance_criteria=criteria,
            now_ms=1,
        )

    def _seed_alignment(self) -> tuple[dict[str, object], dict[str, object]]:
        self._seed_root(
            criteria=("criterion:alignment",),
            facilitator_id="participant:a",
        )
        alignment = {
            **dispatch(
                "dispatch:alignment",
                key="alignment",
                target="participant:a",
            ),
            "intentKind": "align",
        }
        self.store.enqueue_dispatch(alignment, now_ms=2)
        self.store.set_dispatch_wait_state(
            "dispatch:alignment",
            "running",
            now_ms=3,
        )
        execute = {
            **dispatch(
                "dispatch:definition-execute",
                key="definition-execute",
                target="participant:a",
                hop=1,
                parent="dispatch:alignment",
            ),
            "intentKind": "execute",
            "capabilityEpoch": 2,
        }
        return self.store.task("task:1"), execute

    def _seed_user_wait(
        self,
        *,
        resume_key: str = "resume-user-wait",
    ) -> tuple[dict[str, object], dict[str, str]]:
        self._seed_root()
        parent = {
            **dispatch(
                "dispatch:user-wait-parent",
                key="user-wait-parent",
                target="participant:a",
            ),
            "intentKind": "align",
        }
        self.store.enqueue_dispatch(parent, now_ms=2)
        self.store.set_dispatch_wait_state(
            "dispatch:user-wait-parent",
            "running",
            now_ms=3,
        )
        commit_id = "commit:user-wait"
        question_post_id = _stable_id("room-post", commit_id)
        proposal = {
            **post_proposal(
                commit_id,
                "dispatch:user-wait-parent",
                task_id="task:1",
                author="participant:a",
            ),
            "postId": question_post_id,
            "idempotencyKey": f"post:{question_post_id}",
        }
        waiting = {
            **commit(commit_id, "dispatch:user-wait-parent"),
            "action": "post",
            "postProposal": proposal,
            "continuation": {
                "decision": "wait",
                "waitingFor": "user",
                "resumeCondition": "The user answers the clarification.",
                "question": "Continue?",
                "questionOptions": [
                    {"label": "Continue", "value": "yes"},
                    {"label": "Stop", "value": "no"},
                ],
            },
        }
        waiting["qualityGateReceipt"] = {
            **waiting["qualityGateReceipt"],
            "verdict": "not_ready",
        }
        self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=4,
            post_proposal=proposal,
        )
        pending = self.store.pending_user_wait(
            "room:1",
            root_id="root:1",
            question_post_id=question_post_id,
        )
        self.assertIsNotNone(pending)
        resume = {
            **dispatch(
                "dispatch:user-wait-resume",
                key=resume_key,
                target="participant:a",
                hop=1,
                parent="dispatch:user-wait-parent",
            ),
            "intentKind": "resume",
            "capabilityEpoch": 2,
        }
        identities = {
            "continuation_id": str(pending["continuationId"]),
            "question_post_id": question_post_id,
            "answer_root_id": "root:1",
            "answer_post_id": "post:user-wait-answer",
            "answer_anchor_id": "anchor:user-wait-answer",
        }
        return resume, identities

    def _resume_user_wait(
        self,
        resume: dict[str, object],
        identities: dict[str, str],
        *,
        now_ms: int,
    ) -> dict[str, object]:
        return self.store.resume_user_wait(
            continuation_id=identities["continuation_id"],
            dispatch_payload=resume,
            question_post_id=identities["question_post_id"],
            answer_root_id=identities["answer_root_id"],
            answer_post_id=identities["answer_post_id"],
            answer_anchor_id=identities["answer_anchor_id"],
            now_ms=now_ms,
        )

    def _seed_participant_wait(self) -> dict[str, object]:
        self._seed_root(facilitator_id="participant:a")
        self.store.create_task(
            child_task(
                "task:peer",
                parent="task:1",
                target="participant:b",
            ),
            now_ms=2,
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
            now_ms=3,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:waiter",
            "running",
            now_ms=4,
        )
        self.store.set_dispatch_wait_state(
            "dispatch:peer",
            "running",
            now_ms=4,
        )
        waiting = wait_commit(
            "commit:waiter",
            "dispatch:waiter",
            dependency_id="dispatch:peer",
        )
        self.store.apply_commit(
            waiting,
            generation=0,
            now_ms=5,
            post_proposal=waiting["postProposal"],
        )
        RoomContextLedgerStore(self.db_path).publish_post(waiting["postProposal"])
        return waiting

    def test_initial_peer_dispatches_requires_and_uses_root_identity(self) -> None:
        self._seed_root()
        self.store.enqueue_dispatch(
            dispatch("dispatch:initial", key="initial"),
            now_ms=2,
        )

        initial = self.store.initial_peer_dispatches("root:1")

        self.assertEqual(
            [item["dispatchId"] for item in initial],
            ["dispatch:initial"],
        )

    def test_room_define_requires_exact_task_and_root_criteria(self) -> None:
        current_task, execute = self._seed_alignment()
        mismatched_task = {
            **current_task,
            "acceptanceCriterionIds": ["criterion:task-only"],
            "revision": 1,
        }

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "exactly match.*Root",
        ):
            with self.store._connect(immediate=True) as conn:
                self.store.revise_definition_in_transaction(
                    conn,
                    root_id="root:1",
                    dispatch_id="dispatch:alignment",
                    invocation_receipt_id="invocation:criteria-mismatch",
                    task_payload=mismatched_task,
                    acceptance_criteria=("criterion:root-only",),
                    independent_review_required=False,
                    execute_dispatch_payload=execute,
                    details={"definitionFenceId": "fence:criteria-mismatch"},
                    now_ms=4,
                )

    def test_receipt_details_cannot_override_reserved_definition_fields(self) -> None:
        current_task, execute = self._seed_alignment()
        defined_task = {
            **current_task,
            "acceptanceCriterionIds": ["criterion:definition"],
            "revision": 1,
        }

        with self.assertRaisesRegex(RoomKernelFenceError, "reserved.*requiresStartAction"):
            with self.store._connect(immediate=True) as conn:
                self.store.revise_definition_in_transaction(
                    conn,
                    root_id="root:1",
                    dispatch_id="dispatch:alignment",
                    invocation_receipt_id="invocation:reserved-details",
                    task_payload=defined_task,
                    acceptance_criteria=("criterion:definition",),
                    independent_review_required=False,
                    execute_dispatch_payload=execute,
                    details={"requiresStartAction": True},
                    now_ms=4,
                )

    def test_intake_receipt_details_cannot_override_reserved_fields(self) -> None:
        self._seed_root()

        with self.assertRaisesRegex(RoomKernelFenceError, "reserved.*phase"):
            with self.store._connect(immediate=True) as conn:
                self.store._record_intake_phase_locked(
                    conn,
                    root_id="root:1",
                    phase="aligning",
                    clarification_occurred=False,
                    source="test",
                    generation=0,
                    details={"phase": "executing"},
                    now_ms=2,
                )

    def test_user_wait_resume_is_durable_and_directly_idempotent(self) -> None:
        resume, identities = self._seed_user_wait()

        first = self._resume_user_wait(resume, identities, now_ms=5)
        replay = self._resume_user_wait(resume, identities, now_ms=6)

        self.assertEqual(replay, first)
        self.assertEqual(
            self.store.continuation("commit:user-wait")["state"],
            "resumed",
        )
        self.assertIsNone(self.store.pending_user_wait("room:1"))
        recoverable = self.store.pending_user_wait(
            "room:1",
            root_id="root:1",
            question_post_id=identities["question_post_id"],
        )
        self.assertIsNotNone(recoverable)
        self.assertEqual(recoverable["state"], "resumed")

    def test_resume_user_wait_scopes_idempotency_to_its_root(self) -> None:
        resume_key = "same-resume-key-in-two-roots"
        resume, identities = self._seed_user_wait(resume_key=resume_key)
        self._seed_root(root_id="root:2", task_id="task:2")
        foreign = {
            **dispatch("dispatch:foreign", key=resume_key, target="participant:a"),
            "rootId": "root:2",
            "taskId": "task:2",
        }
        self.store.enqueue_dispatch(foreign, now_ms=5)

        resumed = self._resume_user_wait(resume, identities, now_ms=6)

        self.assertEqual(resumed["dispatch"]["rootId"], "root:1")
        self.assertEqual(
            resumed["dispatch"]["dispatchId"],
            "dispatch:user-wait-resume",
        )

    def test_user_wait_ingress_rolls_back_every_store_before_commit(self) -> None:
        resume, identities = self._seed_user_wait()
        requirements = RequirementGovernanceStore(self.db_path)
        projection = RoomKernelProjection(self.db_path)
        context = RoomContextLedgerStore(self.db_path)
        user_post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": identities["answer_post_id"],
            "roomId": "room:1",
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "authorActorRef": "user:local",
            "kind": "request",
            "visibility": "room",
            "content": "yes",
            "idempotencyKey": "user-message:rollback",
            "publicationSource": {"kind": "user", "ref": "rollback"},
            "createdAtMs": 5,
        }
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            requirements.append_anchor_in_transaction(
                conn,
                anchor_id=identities["answer_anchor_id"],
                root_id="root:1",
                original_content="yes",
                created_by="user:local",
                provenance={"surface": "test"},
                created_at_ms=5,
            )
            requirements.revise_catalog_in_transaction(
                conn,
                catalog_revision_id="catalog:rollback",
                root_id="root:1",
                expected_current_revision=0,
                anchor_refs=[identities["answer_anchor_id"]],
                items=[
                    {
                        "itemId": "requirement:rollback",
                        "kind": "explicit_user_requirement",
                        "statement": "yes",
                        "origin": "room_user_answer",
                        "state": "active",
                        "sourceSpans": [
                            {
                                "anchorId": identities["answer_anchor_id"],
                                "startByte": 0,
                                "endByte": 3,
                            }
                        ],
                        "confirmation": "captured_from_user",
                    }
                ],
                acceptance_criteria=[],
                change_reason="exercise rollback",
                provenance={"surface": "test"},
                created_by="room-ingress",
                created_at_ms=5,
            )
            projection.publish_post_in_transaction(conn, user_post)
            context.publish_post_in_transaction(conn, user_post)
            context.append_entry_in_transaction(
                conn,
                root_id="root:1",
                room_id="room:1",
                generation=0,
                entry_kind="requirement_anchor",
                source_ref=identities["answer_anchor_id"],
                dedupe_key="requirement-anchor:rollback",
                content="yes",
                created_at_ms=5,
            )
            self.store.resume_user_wait_in_transaction(
                conn,
                continuation_id=identities["continuation_id"],
                dispatch_payload=resume,
                question_post_id=identities["question_post_id"],
                answer_root_id=identities["answer_root_id"],
                answer_post_id=identities["answer_post_id"],
                answer_anchor_id=identities["answer_anchor_id"],
                now_ms=5,
            )
            raise RuntimeError("simulated crash before commit")
        except RuntimeError:
            conn.rollback()
        finally:
            conn.close()

        self.assertEqual(
            self.store.continuation("commit:user-wait")["state"],
            "applied",
        )
        with self.store._connect() as check:
            for table, identity_column, identity_value in (
                (
                    "room_v2_requirement_anchors",
                    "anchor_id",
                    identities["answer_anchor_id"],
                ),
                (
                    "room_v2_requirement_catalog_revisions",
                    "catalog_revision_id",
                    "catalog:rollback",
                ),
                (
                    "room_kernel_posts",
                    "post_id",
                    identities["answer_post_id"],
                ),
                (
                    "room_v2_posts",
                    "post_id",
                    identities["answer_post_id"],
                ),
            ):
                self.assertEqual(
                    check.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {identity_column}=?",
                        (identity_value,),
                    ).fetchone()[0],
                    0,
                    table,
                )
        with self.assertRaises(KeyError):
            self.store.dispatch("dispatch:user-wait-resume")

    def test_participant_terminal_outcome_resumes_facilitator(self) -> None:
        for terminal_state in ("failed", "cancelled", "unknown"):
            with self.subTest(terminal_state=terminal_state):
                self.tearDown()
                self.setUp()
                self._seed_participant_wait()
                with self.store._connect(immediate=True) as conn:
                    conn.execute(
                        "UPDATE room_kernel_dispatches SET state=?,updated_at_ms=6 "
                        "WHERE dispatch_id='dispatch:peer'",
                        (terminal_state,),
                    )
                    conn.execute(
                        "UPDATE room_kernel_outbox SET state='dead_letter',updated_at_ms=6 "
                        "WHERE dispatch_id='dispatch:peer'"
                    )

                ready = self.store.pending_dispatch(now_ms=7)

                self.assertIsNotNone(ready)
                self.assertEqual(ready["intentKind"], "resume")
                self.assertEqual(ready["targetParticipantId"], "participant:a")
                self.assertEqual(
                    self.store.continuation("commit:waiter")["state"],
                    "resumed",
                )
                self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_bad_wait_row_does_not_hide_later_ready_wait(self) -> None:
        self._seed_participant_wait()
        self.store.create_task(
            child_task(
                "task:bad-wait",
                parent="task:1",
                target="participant:c",
            ),
            now_ms=6,
        )
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:bad-wait",
                key="bad-wait",
                target="participant:c",
                task_id="task:bad-wait",
            ),
            now_ms=6,
        )
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='committed' "
                "WHERE dispatch_id='dispatch:bad-wait'"
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='committed' "
                "WHERE dispatch_id='dispatch:bad-wait'"
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='waiting' "
                "WHERE task_id='task:bad-wait'"
            )
            conn.execute(
                """INSERT INTO room_kernel_continuations(
                   continuation_id,root_id,task_id,parent_dispatch_id,
                   child_dispatch_id,commit_id,decision,state,payload_json,created_at_ms
                   ) VALUES (?,?,?,?,NULL,?,'wait','applied','{',0)""",
                (
                    "continuation:bad-row",
                    "root:1",
                    "task:bad-wait",
                    "dispatch:bad-wait",
                    "commit:bad-row",
                ),
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

        receipt = self.store.apply_commit(
            peer_commit,
            generation=0,
            now_ms=7,
            post_proposal=peer_commit["postProposal"],
        )

        self.assertEqual(len(receipt["details"]["resumedDispatchIds"]), 1)
        self.assertEqual(
            self.store.continuation("commit:waiter")["state"],
            "resumed",
        )
        with self.store._connect() as conn:
            bad = conn.execute(
                "SELECT state FROM room_kernel_continuations "
                "WHERE continuation_id='continuation:bad-row'"
            ).fetchone()
        self.assertEqual(str(bad["state"]), "blocked")
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_dispatch_idempotency_key_cannot_rebind_payload(self) -> None:
        self._seed_root()
        self.store.enqueue_dispatch(
            dispatch("dispatch:first", key="same-key"),
            now_ms=2,
        )

        with self.assertRaisesRegex(RoomKernelFenceError, "idempotency.*rebound"):
            self.store.enqueue_dispatch(
                dispatch("dispatch:rebound", key="same-key"),
                now_ms=3,
            )

    def test_non_atomic_root_creation_is_explicitly_test_only(self) -> None:
        product_store = RoomKernelStore(self.db_path, mode="kernel_only")

        with self.assertRaisesRegex(RoomKernelFenceError, "test-only"):
            product_store.create_root(
                root("root:non-atomic"),
                budget=1,
                max_hops=1,
                max_depth=1,
                now_ms=2,
            )

        self.assertTrue(hasattr(RoomKernelStore, "create_root_with_task"))

    def test_multi_root_panic_replays_exact_aggregate_receipt(self) -> None:
        self._seed_root(root_id="root:a", task_id="task:a")
        self._seed_root(root_id="root:b", task_id="task:b")
        command = control_command(
            "command:panic-two-roots",
            "panic",
            root_id=None,
            now_ms=20,
        )

        first = self.store.apply_control_command(command)
        replay = self.store.apply_control_command(command)

        self.assertEqual(replay, first)
        self.assertIsNone(first["rootId"])
        self.assertEqual(first["details"]["rootCount"], 2)


if __name__ == "__main__":
    unittest.main()
