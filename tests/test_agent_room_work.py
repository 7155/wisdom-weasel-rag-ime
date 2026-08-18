from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_work import (
    AgentRoomWorkAttemptChanged,
    AgentRoomWorkStore,
)
from rag_ime.agent_rooms import AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


class AgentRoomWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-work-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.coordinator = self.sessions.create(title="协调者")
        self.worker = self.sessions.create(title="实施者")
        self.researcher = self.sessions.create(title="调研者")
        self.rooms = AgentRoomStore(self.db_path, room_dir=self.root / "rooms")
        self.rooms.initialize()
        self.room = self.rooms.create(
            title="责任协议",
            routing_policy="moderator",
            participants=[
                {
                    "sessionId": self.coordinator["id"],
                    "roleId": "coordinator",
                    "roleVersion": "1",
                    "displayName": "协调者",
                    "collaborationRole": "coordinator",
                },
                {
                    "sessionId": self.worker["id"],
                    "roleId": "worker",
                    "roleVersion": "1",
                    "displayName": "实施者",
                    "collaborationRole": "implementer",
                },
                {
                    "sessionId": self.researcher["id"],
                    "roleId": "researcher",
                    "roleVersion": "1",
                    "displayName": "调研者",
                    "collaborationRole": "researcher",
                },
            ],
        )
        self.coordinator_participant = self.room["participants"][0]
        self.worker_participant = self.room["participants"][1]
        self.researcher_participant = self.room["participants"][2]
        self.work = AgentRoomWorkStore(self.db_path)
        self.work.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_assignment_changes_owner_only_after_target_turn_is_accepted(self) -> None:
        assigned, created = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-1", self.worker_participant["id"]),
            root_turn_id="room-turn:1",
            topic_id=str(self.room["activeTopicId"]),
            created_at_ms=10,
        )

        self.assertTrue(created)
        self.assertEqual(assigned["state"], "queued")
        self.assertEqual(
            assigned["currentOwnerParticipantId"],
            self.coordinator_participant["id"],
        )
        self.assertEqual(
            assigned["offeredToParticipantId"],
            self.worker_participant["id"],
        )

        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
            updated_at_ms=20,
        )
        self.assertEqual(active["state"], "active")
        self.assertEqual(
            active["currentOwnerParticipantId"],
            self.worker_participant["id"],
        )

        submitted = self.work.submit(
            str(self.worker["id"]),
            {
                "workId": active["id"],
                "resultSummary": "完成了实现和窄测试。",
                "artifactRefs": ["src/room.py"],
                "evidenceRefs": ["test:test_room"],
            },
            updated_at_ms=30,
        )
        self.assertEqual(submitted["state"], "review")

        completed = self.work.accept(
            str(self.coordinator["id"]),
            {"workId": active["id"]},
            updated_at_ms=40,
        )
        self.assertEqual(completed["state"], "done")
        self.assertEqual(completed["completedAtMs"], 40)
        self.assertEqual(
            self.rooms.get(str(self.room["id"]))["workItems"][0]["state"],
            "done",
        )
        with self.assertRaisesRegex(ValueError, "active or review"):
            self.work.authoritative_owner(
                str(completed["id"]),
                room_id=str(self.room["id"]),
            )
        with sqlite3.connect(self.db_path) as conn:
            events = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT event_type FROM agent_room_work_events
                    WHERE work_id = ? ORDER BY sequence
                    """,
                    (active["id"],),
                )
            ]
        self.assertEqual(
            events,
            ["assigned", "accepted", "submitted", "completed"],
        )

    def test_assignment_is_idempotent_and_rejects_ancestor_bounce(self) -> None:
        payload = self._assignment("root-2", self.worker_participant["id"])
        first, created = self.work.assign(str(self.coordinator["id"]), payload)
        repeated, repeated_created = self.work.assign(
            str(self.coordinator["id"]),
            payload,
        )

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated["id"], first["id"])

        active = self.work.accept_assignment(
            str(first["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
        )
        with self.assertRaisesRegex(ValueError, "ancestor owner"):
            self.work.assign(
                str(self.worker["id"]),
                {
                    **self._assignment(
                        "child-1",
                        self.coordinator_participant["id"],
                    ),
                    "parentWorkId": active["id"],
                },
            )

    def test_revision_budget_requires_escalation_after_two_returns(self) -> None:
        assigned, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-3", self.worker_participant["id"]),
        )
        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
        )
        for revision in (1, 2):
            self.work.submit(
                str(self.worker["id"]),
                {
                    "workId": active["id"],
                    "resultSummary": f"第 {revision} 版",
                    "evidenceRefs": [f"test:revision-{revision}"],
                },
            )
            active = self.work.return_for_revision(
                str(self.coordinator["id"]),
                {
                    "workId": active["id"],
                    "reason": f"第 {revision} 次反馈",
                },
            )
            self.assertEqual(active["revision"], revision)

        self.work.submit(
            str(self.worker["id"]),
            {
                "workId": active["id"],
                "resultSummary": "第三版",
                "evidenceRefs": ["test:revision-3"],
            },
        )
        with self.assertRaisesRegex(ValueError, "revision limit"):
            self.work.return_for_revision(
                str(self.coordinator["id"]),
                {"workId": active["id"], "reason": "仍不通过"},
            )

    def test_submit_requires_evidence_and_closed_children(self) -> None:
        assigned, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-4", self.worker_participant["id"]),
        )
        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
        )
        with self.assertRaisesRegex(ValueError, "artifactRefs or evidenceRefs"):
            self.work.submit(
                str(self.worker["id"]),
                {
                    "workId": active["id"],
                    "resultSummary": "只有一句完成声明",
                },
            )

        child, _ = self.work.assign(
            str(self.worker["id"]),
            {
                **self._assignment(
                    "child-2",
                    self.researcher_participant["id"],
                ),
                "parentWorkId": active["id"],
            },
        )
        self.work.accept_assignment(
            str(child["id"]),
            target_participant_id=str(self.researcher_participant["id"]),
            accepted_turn_id="turn:researcher",
        )
        with self.assertRaisesRegex(ValueError, "child WorkItems are open"):
            self.work.submit(
                str(self.worker["id"]),
                {
                    "workId": active["id"],
                    "resultSummary": "子任务尚未闭环",
                    "evidenceRefs": ["test:parent"],
                },
            )

    def test_attempt_fence_rejects_late_results_after_resume_and_reassign(self) -> None:
        assigned, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-fence", self.worker_participant["id"]),
            root_turn_id="room-turn:fence",
        )
        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="attempt:worker:0",
        )
        blocked = self.work.block_attempt(
            str(self.worker["id"]),
            {
                "workId": active["id"],
                "reason": "provider unavailable",
                "nextStep": "resume after recovery",
            },
            attempt_id="attempt:worker:0",
            expected_revision=0,
        )
        self.assertEqual(blocked["state"], "blocked")
        resumed = self.work.resume(
            str(self.coordinator["id"]),
            {"workId": active["id"]},
        )
        claimed = self.work.claim_dispatch(
            str(resumed["id"]),
            room_id=str(self.room["id"]),
            owner_participant_id=str(self.worker_participant["id"]),
            assignment_key=str(resumed["assignmentKey"]),
            previous_accepted_turn_id="",
            room_turn_id="attempt:worker:1",
            root_turn_id="room-turn:fence",
        )
        with self.assertRaises(AgentRoomWorkAttemptChanged):
            self.work.submit_attempt(
                str(self.worker["id"]),
                {
                    "workId": claimed["id"],
                    "resultSummary": "late result",
                    "evidenceRefs": ["attempt:worker:0"],
                },
                attempt_id="attempt:worker:0",
                expected_revision=0,
            )

        reassigned = self.work.reassign(
            str(claimed["id"]),
            actor_participant_id=str(self.coordinator_participant["id"]),
            current_owner_participant_id=str(self.researcher_participant["id"]),
            reason="owner recovery",
        )
        self.assertEqual(reassigned["state"], "active")
        self.assertEqual(reassigned["acceptedTurnId"], "")
        with self.assertRaises(AgentRoomWorkAttemptChanged):
            self.work.submit_attempt(
                str(self.worker["id"]),
                {
                    "workId": claimed["id"],
                    "resultSummary": "stale owner result",
                    "evidenceRefs": ["attempt:worker:1"],
                },
                attempt_id="attempt:worker:1",
                expected_revision=0,
            )
        owner, owner_id = self.work.authoritative_owner(
            str(reassigned["id"]),
            room_id=str(self.room["id"]),
        )
        self.assertEqual(owner_id, self.researcher_participant["id"])
        self.assertEqual(owner["id"], reassigned["id"])

    def test_explicit_fail_and_abandon_are_terminal_and_rebuildable(self) -> None:
        failed_item, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-fail", self.worker_participant["id"]),
            root_turn_id="room-turn:terminal",
        )
        failed = self.work.fail(
            str(self.coordinator["id"]),
            {
                "workId": failed_item["id"],
                "reason": "cannot satisfy the delivery contract",
                "nextStep": "publish the bounded failure",
            },
        )
        self.assertEqual(failed["state"], "failed")

        abandoned_item, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment("root-abandon", self.researcher_participant["id"]),
            root_turn_id="room-turn:terminal",
        )
        abandoned = self.work.abandon(
            str(self.coordinator["id"]),
            {
                "workId": abandoned_item["id"],
                "reason": "optional investigation no longer needed",
            },
        )
        self.assertEqual(abandoned["state"], "cancelled")
        restarted = AgentRoomWorkStore(self.db_path)
        self.assertEqual(
            restarted.open_for_root(
                room_id=str(self.room["id"]),
                root_turn_id="room-turn:terminal",
            ),
            [],
        )
        self.assertEqual(
            [event["eventType"] for event in restarted.list_events(failed["id"])][-1],
            "failed",
        )
        self.assertEqual(
            [event["eventType"] for event in restarted.list_events(abandoned["id"])][-1],
            "abandoned",
        )

    def _assignment(
        self,
        client_message_id: str,
        target_participant_id: object,
    ) -> dict[str, object]:
        return {
            "targetParticipantId": target_participant_id,
            "clientMessageId": client_message_id,
            "objective": "检查 Room 责任协议",
            "expectedOutput": "实现、证据和风险说明",
            "acceptanceCriteria": [
                "目标回合接受后才转移 owner",
                "交付可被协调者验收",
            ],
        }


if __name__ == "__main__":
    unittest.main()
