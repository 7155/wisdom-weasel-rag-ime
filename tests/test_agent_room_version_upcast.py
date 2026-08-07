from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from rag_ime.agent_room_kernel_contracts import validate_kernel_contract
from rag_ime.agent_room_kernel_projection import RoomKernelProjection
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.db import apply_database_migrations
from rag_ime.db.migration_runner import load_migrations
from tests.test_agent_room_kernel import child_task, commit, dispatch, root, task


REPLAY_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "room_version_replay"
    / "pre_0124_root_replay.json"
)
CONTINUATION_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "room_version_replay"
    / "pre_0124_continuations.json"
)


class HistoricalRoomRootReplayTests(unittest.TestCase):
    def test_pre_0124_v2_root_upgrades_through_current_snapshot_and_replay(self) -> None:
        fixture = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(
            prefix="rag-ime-room-root-v2-replay-"
        ) as temporary:
            root_dir = Path(temporary)
            migrations_0123 = root_dir / "migrations"
            migrations_0123.mkdir()
            for migration in load_migrations():
                if migration.version <= 123:
                    shutil.copy2(
                        migration.path,
                        migrations_0123 / migration.path.name,
                    )

            db_path = root_dir / "rag-ime.sqlite"
            legacy_root = {
                "schemaVersion": "wisdom-weasel.room-root-execution.v2",
                "rootId": "root:legacy-version-replay",
                "roomId": "room:legacy-version-replay",
                "generation": 0,
                "state": "running",
                "owner": "participant:legacy-facilitator",
                "requirementAnchorRef": (
                    "requirement-anchor:legacy@sha256:test"
                ),
                "createdByActorRef": "user:legacy",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:legacy-v1",
                "createdAtMs": 100,
            }
            validate_contract(legacy_root, "room-root-execution.v2.json")
            legacy_event = {
                "schemaVersion": "wisdom-weasel.room-event-envelope.v2",
                "entityKind": "root",
                "entityId": legacy_root["rootId"],
                "eventKind": "state_changed",
                "sequence": 1,
                "occurredAtMs": 110,
                "payload": {"root": legacy_root},
            }
            validate_kernel_contract("eventEnvelope", legacy_event)

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                pre_upgrade = apply_database_migrations(
                    conn,
                    migrations_dir=migrations_0123,
                    applied_at_ms=90,
                )
                self.assertEqual(pre_upgrade.current_version, 123)
                conn.execute(
                    """
                    INSERT INTO room_kernel_roots(
                        root_id,room_id,generation,state,owner,
                        requirement_anchor_ref,budget_remaining,budget_reserved,
                        max_hops,max_depth,acceptance_criteria_json,
                        covered_criteria_json,terminal_receipt_id,payload_json,
                        created_at_ms,updated_at_ms
                    ) VALUES(?,?,?,?,?,?,10,0,3,2,'[]','[]',NULL,?,?,?)
                    """,
                    (
                        legacy_root["rootId"],
                        legacy_root["roomId"],
                        legacy_root["generation"],
                        legacy_root["state"],
                        legacy_root["owner"],
                        legacy_root["requirementAnchorRef"],
                        _json(legacy_root),
                        legacy_root["createdAtMs"],
                        legacy_root["createdAtMs"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO room_kernel_events(
                        room_id,sequence,entity_kind,entity_id,event_kind,
                        payload_json,occurred_at_ms
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        legacy_root["roomId"],
                        legacy_event["sequence"],
                        legacy_event["entityKind"],
                        legacy_event["entityId"],
                        legacy_event["eventKind"],
                        _json(legacy_event),
                        legacy_event["occurredAtMs"],
                    ),
                )

                upgraded = apply_database_migrations(conn, applied_at_ms=130)
                self.assertEqual(upgraded.current_version, load_migrations()[-1].version)
                relational_root = conn.execute(
                    """
                    SELECT facilitator_participant_id,reporter_participant_id,
                           reporter_selection_receipt_id,payload_json
                    FROM room_kernel_roots
                    WHERE root_id=?
                    """,
                    (legacy_root["rootId"],),
                ).fetchone()
                self.assertEqual(
                    relational_root[:3],
                    ("participant:legacy-facilitator", None, None),
                )
                self.assertEqual(
                    json.loads(str(relational_root[3]))["schemaVersion"],
                    "wisdom-weasel.room-root-execution.v2",
                )

            projection = RoomKernelProjection(db_path)
            projection.initialize()
            emitted = projection.sync_room(
                "room:legacy-version-replay",
                now_ms=200,
            )
            snapshot = projection.snapshot("room:legacy-version-replay")
            replay = projection.events("room:legacy-version-replay")

            self.assertEqual(snapshot, fixture["snapshot"])
            self.assertEqual(replay, fixture["replayEvents"])
            self.assertEqual(emitted, fixture["replayEvents"][1:])
            self.assertTrue(
                snapshot["roots"][0]["independentReviewRequired"],
                "missing historical review policy must upcast fail-closed",
            )


class HistoricalRoomCommitReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-commit-version-replay-"
        )
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.store.initialize()
        self.store.create_root(
            root("root:1"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("ac:1",),
            now_ms=1,
        )
        for suffix in ("v2", "v3"):
            task_id = f"task:{suffix}"
            dispatch_id = f"dispatch:{suffix}"
            self.store.create_task(task(task_id), now_ms=2)
            self.store.enqueue_dispatch(
                dispatch(
                    dispatch_id,
                    key=f"legacy-commit:{suffix}",
                    task_id=task_id,
                ),
                now_ms=3,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_v2_and_v3_commit_rows_replay_as_current_v4(self) -> None:
        v2 = {
            "schemaVersion": "wisdom-weasel.room-commit.v2",
            "commitId": "commit:v2",
            "dispatchId": "dispatch:v2",
            "action": "wait",
            "contentHash": "sha256:legacy-v2",
            "postProposal": None,
            "continuation": {"decision": "wait"},
            "evidenceRefs": ["evidence:legacy-v2-unverified"],
            "requirementCoverage": ["ac:1"],
            "createdAtMs": 20,
        }
        v3_child_dispatch = dispatch(
            "dispatch:v3-child",
            key="legacy-commit:v3-child",
            target="participant:reviewer",
            task_id="task:v3-child",
        )
        v3 = {
            "schemaVersion": "wisdom-weasel.room-commit.v3",
            "commitId": "commit:v3",
            "dispatchId": "dispatch:v3",
            "action": "dispatch",
            "contentHash": "sha256:legacy-v3",
            "postProposal": None,
            "continuation": {
                "decision": "dispatch",
                "childTask": {"taskId": "task:v3-child"},
                "childDispatch": v3_child_dispatch,
            },
            "qualityGateReceipt": {
                "schemaVersion": (
                    "wisdom-weasel.room-quality-gate-receipt.v1"
                ),
                "receiptId": "quality:legacy-v3",
                "rootId": "root:1",
                "taskId": "task:v3",
                "dispatchId": "dispatch:v3",
                "generation": 0,
                "originalRequestChecked": True,
                "verdict": "ready_to_deliver",
                "items": [
                    {
                        "criterionId": "ac:1",
                        "status": "pass",
                        "evidenceRefs": ["evidence:legacy-v3-verified"],
                    }
                ],
                "residualRisks": [],
                "createdAtMs": 30,
            },
            "evidenceRefs": ["evidence:legacy-v3-verified"],
            "requirementCoverage": ["ac:1"],
            "createdAtMs": 30,
        }
        validate_contract(v2, "room-commit.v2.json")
        validate_contract(v3, "room-commit.v3.json")
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO room_kernel_commits(
                    commit_id,root_id,dispatch_id,generation,payload_json,
                    created_at_ms
                ) VALUES(?, 'root:1', ?, 0, ?, ?)
                """,
                (
                    ("commit:v2", "dispatch:v2", _json(v2), 20),
                    ("commit:v3", "dispatch:v3", _json(v3), 30),
                ),
            )
            # The historical Commit row is immutable, but accepted evidence is
            # now selected only from the current durable attempt of a completed
            # Task.  Recreate that authoritative relational state explicitly;
            # merely inserting an old Commit beside a pending Dispatch would
            # describe a superseded/incomplete attempt under today's model.
            task_payload = json.loads(
                str(
                    conn.execute(
                        "SELECT payload_json FROM room_kernel_tasks "
                        "WHERE task_id='task:v3'"
                    ).fetchone()[0]
                )
            )
            task_payload["state"] = "completed"
            conn.execute(
                """UPDATE room_kernel_tasks
                   SET state='completed',payload_json=?,updated_at_ms=30
                   WHERE task_id='task:v3'""",
                (_json(task_payload),),
            )
            conn.execute(
                """UPDATE room_kernel_dispatches
                   SET state='committed',updated_at_ms=30
                   WHERE dispatch_id='dispatch:v3'"""
            )
            conn.execute(
                """UPDATE room_kernel_outbox
                   SET state='committed',updated_at_ms=30
                   WHERE dispatch_id='dispatch:v3'"""
            )

        replayed_v2 = self.store.commit("commit:v2")
        replayed_v3 = self.store.commit("commit:v3")

        validate_kernel_contract("roomCommit", replayed_v2)
        validate_kernel_contract("roomCommit", replayed_v3)
        self.assertEqual(
            replayed_v2["schemaVersion"],
            "wisdom-weasel.room-commit.v4",
        )
        self.assertEqual(
            replayed_v2["qualityGateReceipt"]["verdict"],
            "not_ready",
        )
        self.assertFalse(
            replayed_v2["qualityGateReceipt"]["originalRequestChecked"]
        )
        self.assertEqual(replayed_v2["qualityGateReceipt"]["items"], [])
        self.assertEqual(
            replayed_v2["continuation"]["waitingFor"],
            "external",
        )
        self.assertIn(
            "explicit recovery",
            replayed_v2["continuation"]["resumeCondition"],
        )
        self.assertEqual(
            replayed_v2["qualityGateReceipt"]["taskId"],
            "task:v2",
        )
        self.assertEqual(
            replayed_v3["schemaVersion"],
            "wisdom-weasel.room-commit.v4",
        )
        self.assertEqual(
            replayed_v3["continuation"]["waitingFor"],
            "participant",
        )
        self.assertEqual(
            replayed_v3["continuation"]["waitingForParticipantId"],
            "participant:reviewer",
        )
        self.assertEqual(
            self.store.latest_task_commit("task:v3"),
            replayed_v3,
        )
        self.assertEqual(
            self.store.accepted_evidence_by_criterion("root:1"),
            {},
            "historical display upcasting must not synthesize the canonical "
            "acceptance authority required by current evidence gates",
        )
        with sqlite3.connect(self.db_path) as conn:
            raw_versions = [
                json.loads(str(row[0]))["schemaVersion"]
                for row in conn.execute(
                    """
                    SELECT payload_json FROM room_kernel_commits
                    ORDER BY commit_id
                    """
                )
            ]
        self.assertEqual(
            raw_versions,
            [
                "wisdom-weasel.room-commit.v2",
                "wisdom-weasel.room-commit.v3",
            ],
            "immutable historical Commit rows must not be rewritten",
        )


class HistoricalMaterializedContinuationReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-continuation-version-replay-"
        )
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.store.initialize()
        self.store.create_root(
            root("root:1"),
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.store.create_task(task("task:1", criteria=()), now_ms=2)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_late_v3_participant_wait_blocks_for_explicit_recovery_once(
        self,
    ) -> None:
        historical = self._fixture_case("lateV3ParticipantWait")
        self._seed_parent_and_peer(separate_task=True)
        raw_before = self._insert_historical_continuation(
            historical,
            child_dispatch_id=None,
            task_state="waiting",
            root_state="waiting",
        )

        replayed = self.store.continuation("commit:legacy-parent")

        self.assertEqual(replayed["payload"]["waitingFor"], "participant")
        self.assertEqual(
            replayed["payload"]["waitingForParticipantId"],
            "participant:b",
        )
        self.assertEqual(
            replayed["payload"]["waitingForDispatchId"],
            "dispatch:legacy-peer",
        )
        self.assertEqual(self._raw_continuation(), raw_before)

        receipt = self._complete_peer(task_id="task:legacy-peer")

        self.assertEqual(receipt["details"]["resumedDispatchIds"], [])
        blocked = receipt["details"]["blockedWaitContinuations"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(
            blocked[0]["continuationId"],
            "continuation:legacy-parent",
        )
        self.assertEqual(
            blocked[0]["reasonCode"],
            "historical_continuation_recovery_required",
        )
        self.assertIn("explicit recovery", blocked[0]["reason"])
        self.assertEqual(self.store.task("task:1")["state"], "blocked")
        self.assertEqual(self.store.root("root:1")["state"], "blocked")
        self.assertEqual(
            self.store.continuation("commit:legacy-parent")["state"],
            "blocked",
        )
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)
        self.assertNotIn(
            "resumeDispatchId",
            self.store.continuation("commit:legacy-parent")["payload"],
        )
        with self.store._connect(immediate=True) as conn:
            resumed_again, blocked_again = (
                self.store._resume_ready_participant_waits(
                    conn,
                    root_id="root:1",
                    generation=0,
                    now_ms=21,
                )
            )
        self.assertEqual(resumed_again, [])
        self.assertEqual(blocked_again, [])
        self.assertEqual(self.store.counts("root:1")["deadLetters"], 1)

    def test_v2_same_task_dispatch_does_not_resume_or_block(self) -> None:
        historical = self._fixture_case("v2SameTaskDispatch")
        self._seed_parent_and_peer(separate_task=False)
        raw_before = self._insert_historical_continuation(
            historical,
            child_dispatch_id="dispatch:legacy-peer",
            task_state="active",
            root_state="running",
        )

        replayed = self.store.continuation("commit:legacy-parent")

        validate_kernel_contract(
            "roomCommit",
            self.store.commit("commit:legacy-parent"),
        )
        self.assertEqual(replayed["payload"]["waitingFor"], "participant")
        self.assertEqual(self._raw_continuation(), raw_before)

        receipt = self._complete_peer(task_id="task:1")

        self.assertEqual(receipt["details"]["resumedDispatchIds"], [])
        self.assertEqual(receipt["details"]["blockedWaitContinuations"], [])
        self.assertEqual(
            self.store.continuation("commit:legacy-parent")["state"],
            "applied",
        )
        self.assertEqual(self.store.root("root:1")["state"], "running")

    def test_identityless_v2_wait_projects_external_without_auto_resume(
        self,
    ) -> None:
        historical = self._fixture_case("v2IdentitylessWait")
        self._seed_parent_and_peer(separate_task=True)
        raw_before = self._insert_historical_continuation(
            historical,
            child_dispatch_id=None,
            task_state="waiting",
            root_state="waiting",
        )

        replayed = self.store.continuation("commit:legacy-parent")

        self.assertEqual(replayed["payload"]["waitingFor"], "external")
        self.assertIn(
            "explicit recovery",
            replayed["payload"]["resumeCondition"],
        )
        self.assertEqual(self._raw_continuation(), raw_before)

        receipt = self._complete_peer(task_id="task:legacy-peer")

        self.assertEqual(receipt["details"]["resumedDispatchIds"], [])
        self.assertEqual(receipt["details"]["blockedWaitContinuations"], [])
        self.assertEqual(
            self.store.continuation("commit:legacy-parent")["state"],
            "applied",
        )

    def test_initial_v3_identityless_wait_uses_restricted_decoder(self) -> None:
        historical = self._fixture_case("initialV3IdentitylessWait")
        self._seed_parent_and_peer(separate_task=True)
        raw_before = self._insert_historical_continuation(
            historical,
            child_dispatch_id=None,
            task_state="waiting",
            root_state="waiting",
        )

        replayed_commit = self.store.commit("commit:legacy-parent")
        replayed = self.store.continuation("commit:legacy-parent")

        validate_kernel_contract("roomCommit", replayed_commit)
        self.assertEqual(replayed["payload"]["waitingFor"], "external")
        self.assertIn(
            "explicit recovery",
            replayed["payload"]["resumeCondition"],
        )
        self.assertEqual(self._raw_continuation(), raw_before)

    def test_orphan_materialized_wait_is_rejected_fail_closed(self) -> None:
        self.store.enqueue_dispatch(
            dispatch(
                "dispatch:orphan-parent",
                key="orphan-parent",
            ),
            now_ms=3,
        )
        orphan_payload = {
            "decision": "wait",
            "waitingFor": "user",
            "resumeCondition": "answer",
            "question": "Should not be trusted without its Commit.",
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO room_kernel_continuations(
                    continuation_id,root_id,task_id,parent_dispatch_id,
                    child_dispatch_id,commit_id,decision,state,payload_json,
                    created_at_ms
                ) VALUES(
                    'continuation:orphan','root:1','task:1',
                    'dispatch:orphan-parent',NULL,'commit:missing',
                    'wait','applied',?,10
                )
                """,
                (_json(orphan_payload),),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='waiting' WHERE task_id='task:1'"
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='waiting' WHERE root_id='root:1'"
            )

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "no authoritative Commit",
        ):
            self.store.continuation("commit:missing")
        self.assertIsNone(
            self.store.pending_user_wait("room:1"),
            "an orphan continuation must never become the public pending "
            "question or capture the Room composer",
        )

    def _seed_parent_and_peer(self, *, separate_task: bool) -> None:
        peer_task_id = "task:legacy-peer" if separate_task else "task:1"
        if separate_task:
            self.store.create_task(
                child_task(
                    peer_task_id,
                    parent="task:1",
                    target="participant:b",
                ),
                now_ms=3,
            )
        parent_dispatch = dispatch(
            "dispatch:legacy-parent",
            key="legacy-parent",
        )
        peer_dispatch = dispatch(
            "dispatch:legacy-peer",
            key="legacy-peer",
            target="participant:b" if separate_task else "participant:a",
            hop=1,
            depth=1 if separate_task else 0,
            parent="dispatch:legacy-parent",
            task_id=peer_task_id,
        )
        if not separate_task:
            # Seed through today's legal batch contract first.  The historical
            # v2 shape is restored below only after both Dispatches exist, so
            # this fixture does not ask production code to bypass the
            # same-Session ordering fence.
            peer_dispatch = {
                **peer_dispatch,
                "targetSessionId": "session:historical-staging",
            }
        self.store.enqueue_dispatches(
            (parent_dispatch, peer_dispatch),
            now_ms=4,
        )
        if not separate_task:
            # The v2 writer predates the current Task-owner enqueue fence and
            # persisted a cross-participant child Dispatch on the same Task.
            historical_peer = {
                **peer_dispatch,
                "targetSessionId": "session:participant:b",
                "targetParticipantId": "participant:b",
            }
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE room_kernel_dispatches
                    SET target_session_id=?,target_participant_id=?,payload_json=?
                    WHERE dispatch_id='dispatch:legacy-peer'
                    """,
                    (
                        historical_peer["targetSessionId"],
                        historical_peer["targetParticipantId"],
                        _json(historical_peer),
                    ),
                )
        for dispatch_id in (
            "dispatch:legacy-parent",
            "dispatch:legacy-peer",
        ):
            self.store.set_dispatch_wait_state(
                dispatch_id,
                "running",
                now_ms=5,
            )

    def _complete_peer(self, *, task_id: str) -> dict[str, object]:
        return self.store.apply_commit(
            commit(
                "commit:legacy-peer",
                "dispatch:legacy-peer",
                task_id=task_id,
            ),
            generation=0,
            now_ms=20,
        )

    def _fixture_case(self, name: str) -> dict[str, object]:
        fixture = json.loads(
            CONTINUATION_FIXTURE.read_text(encoding="utf-8")
        )
        self.assertEqual(fixture["capturedBeforeMigrationVersion"], 124)
        historical = fixture[name]
        self.assertEqual(
            historical["materializedContinuation"],
            historical["commit"]["continuation"],
        )
        return historical

    def _insert_historical_continuation(
        self,
        historical: dict[str, object],
        *,
        child_dispatch_id: str | None,
        task_state: str,
        root_state: str,
    ) -> str:
        legacy_commit = historical["commit"]
        materialized = historical["materializedContinuation"]
        decision = str(materialized["decision"])
        encoded = _json(materialized)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO room_kernel_commits(
                    commit_id,root_id,dispatch_id,generation,payload_json,
                    created_at_ms
                ) VALUES(?, 'root:1', 'dispatch:legacy-parent', 0, ?, 10)
                """,
                (legacy_commit["commitId"], _json(legacy_commit)),
            )
            conn.execute(
                """
                INSERT INTO room_kernel_continuations(
                    continuation_id,root_id,task_id,parent_dispatch_id,
                    child_dispatch_id,commit_id,decision,state,payload_json,
                    created_at_ms
                ) VALUES(
                    'continuation:legacy-parent','root:1','task:1',
                    'dispatch:legacy-parent',?,'commit:legacy-parent',
                    ?,'applied',?,10
                )
                """,
                (child_dispatch_id, decision, encoded),
            )
            conn.execute(
                """
                UPDATE room_kernel_dispatches
                SET state='committed'
                WHERE dispatch_id='dispatch:legacy-parent'
                """
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state=? WHERE task_id='task:1'",
                (task_state,),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state=? WHERE root_id='root:1'",
                (root_state,),
            )
        return encoded

    def _raw_continuation(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM room_kernel_continuations
                WHERE continuation_id='continuation:legacy-parent'
                """
            ).fetchone()
        assert row is not None
        return str(row[0])


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    unittest.main()
