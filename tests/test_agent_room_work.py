from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_work import AgentRoomWorkStore
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

    def test_kernel_root_lifecycle_projects_claimed_work_once(self) -> None:
        notifications: list[tuple[str, str]] = []
        self.work.set_terminal_observer(
            lambda kind, identifier: notifications.append(
                (kind, identifier)
            )
        )
        assigned, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment(
                "kernel-root-work",
                self.worker_participant["id"],
            ),
            created_at_ms=10,
        )
        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
            updated_at_ms=20,
        )
        root_id = "room-root:kernel-complete"
        claimed = self.work.claim_dispatch(
            str(active["id"]),
            room_id=str(self.room["id"]),
            owner_participant_id=str(self.worker_participant["id"]),
            assignment_key=str(active["assignmentKey"]),
            previous_accepted_turn_id=str(active["acceptedTurnId"]),
            room_turn_id=root_id,
            claimed_at_ms=30,
        )

        blocked = self.work.project_kernel_root(
            {
                "rootId": root_id,
                "roomId": self.room["id"],
                "state": "blocked",
                "terminalReceiptId": None,
                "updatedAtMs": 35,
            }
        )
        self.assertEqual(blocked[0]["state"], "blocked")
        self.assertEqual(
            blocked[0]["blocker"]["kernelRootState"],
            "blocked",
        )
        self.assertEqual(
            self.work.project_kernel_root(
                {
                    "rootId": root_id,
                    "roomId": self.room["id"],
                    "state": "blocked",
                    "terminalReceiptId": None,
                    "updatedAtMs": 36,
                }
            ),
            [],
        )
        resumed = self.work.project_kernel_root(
            {
                "rootId": root_id,
                "roomId": self.room["id"],
                "state": "running",
                "terminalReceiptId": None,
                "updatedAtMs": 37,
            }
        )
        self.assertEqual(resumed[0]["state"], "active")
        self.assertEqual(resumed[0]["blocker"], {})

        settled = self.work.project_kernel_root(
            {
                "rootId": root_id,
                "roomId": self.room["id"],
                "state": "completed",
                "terminalReceiptId": "room-receipt:complete",
                "updatedAtMs": 40,
            }
        )

        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0]["state"], "done")
        self.assertEqual(settled[0]["completedAtMs"], 40)
        self.assertEqual(
            settled[0]["evidenceRefs"],
            ["room-receipt:complete"],
        )
        self.assertEqual(
            notifications,
            [("room_work_item", str(claimed["id"]))],
        )
        self.assertEqual(
            [event["eventType"] for event in self.work.list_events(
                str(claimed["id"])
            )],
            ["assigned", "accepted", "accepted", "blocked", "accepted", "completed"],
        )
        self.assertEqual(
            self.work.list_events(str(claimed["id"]))[-1]["payload"][
                "source"
            ],
            "room_kernel",
        )
        self.assertEqual(
            self.work.project_kernel_root(
                {
                    "rootId": root_id,
                    "roomId": self.room["id"],
                    "state": "completed",
                    "terminalReceiptId": "room-receipt:complete",
                    "updatedAtMs": 50,
                }
            ),
            [],
        )

    def test_kernel_waiting_keeps_parent_active_with_open_child(self) -> None:
        assigned, _ = self.work.assign(
            str(self.coordinator["id"]),
            self._assignment(
                "kernel-waiting-parent",
                self.worker_participant["id"],
            ),
            created_at_ms=10,
        )
        active = self.work.accept_assignment(
            str(assigned["id"]),
            target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
            updated_at_ms=20,
        )
        root_id = "room-root:kernel-waiting"
        claimed = self.work.claim_dispatch(
            str(active["id"]),
            room_id=str(self.room["id"]),
            owner_participant_id=str(self.worker_participant["id"]),
            assignment_key=str(active["assignmentKey"]),
            previous_accepted_turn_id=str(active["acceptedTurnId"]),
            room_turn_id=root_id,
            claimed_at_ms=30,
        )

        blocked = self.work.project_kernel_root(
            {
                "rootId": root_id,
                "roomId": self.room["id"],
                "state": "waiting",
                "terminalReceiptId": None,
                "updatedAtMs": 35,
            }
        )
        self.assertEqual(blocked[0]["state"], "blocked")

        child, _ = self.work.assign(
            str(self.worker["id"]),
            {
                **self._assignment(
                    "kernel-waiting-child",
                    self.researcher_participant["id"],
                ),
                "parentWorkId": claimed["id"],
            },
            created_at_ms=40,
        )
        self.assertEqual(child["state"], "queued")
        self.assertEqual(child["parentWorkId"], claimed["id"])

        resumed = self.work.project_kernel_root(
            {
                "rootId": root_id,
                "roomId": self.room["id"],
                "state": "waiting",
                "terminalReceiptId": None,
                "updatedAtMs": 45,
            }
        )
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0]["state"], "active")
        self.assertEqual(resumed[0]["blocker"], {})

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
