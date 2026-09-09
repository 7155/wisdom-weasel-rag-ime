from __future__ import annotations

import unittest
from unittest.mock import patch

from rag_ime.rooms.intercom import AgentRoomIntercomRouter, AgentRoomIntercomStore
from rag_ime.rooms.work_application import RoomWorkApplicationService
from rag_ime.rooms.store import AgentRoomEventHub
from tests import test_agent_room_work as fixtures


class RoomWorkApplicationTests(unittest.TestCase):
    # Reuse the real SQLite/participant fixture without inheriting its test cases.
    _assignment = fixtures.AgentRoomWorkTests._assignment
    tearDown = fixtures.AgentRoomWorkTests.tearDown

    def setUp(self) -> None:
        fixtures.AgentRoomWorkTests.setUp(self)
        self.audit = []
        self.events = AgentRoomEventHub(self.rooms)
        self.events.add_observer(self.audit.append)
        self.guards = []
        self.router = AgentRoomIntercomRouter(
            AgentRoomIntercomStore(self.db_path),
            generation_provider=lambda _: 1,
            idle_probe=lambda _: False,
            delivery_handler=lambda _: {},
            audit_publisher=lambda *_: None,
        )
        self.addCleanup(self.router.close)
        notify = patch.object(self.router, "notify")
        notify.start()
        self.addCleanup(notify.stop)
        self.app = RoomWorkApplicationService(
            rooms=self.rooms, room_work=self.work, room_intercom=self.router,
            room_events=self.events, guard_session_route=self._guard,
        )

    def _guard(self, route, session_id):
        self.guards.append((route, session_id))
        self.sessions.get(session_id)

    def _assign(self):
        return self.app.assign_room_work(
            str(self.coordinator["id"]), self._assignment("assignment-1", self.worker_participant["id"]),
        )

    def _active(self):
        work = self._assign()["work"]
        return self.work.accept_assignment(
            str(work["id"]), target_participant_id=str(self.worker_participant["id"]),
            accepted_turn_id="turn:worker",
        )

    def _submit(self, work):
        return self.app.submit_room_work(str(self.worker["id"]), {
            "workId": work["id"], "resultSummary": "implemented", "artifactRefs": ["src/room.py"],
            "evidenceRefs": ["test:room"],
        })

    def test_constructs_with_only_owned_dependencies_and_queries_real_store(self):
        self.assertFalse(hasattr(self.app, "host"))
        self.assertIs(self.app.rooms, self.rooms)
        self.assertIs(self.app.room_work, self.work)
        self.assertIs(self.app.room_intercom, self.router)
        self.assertIs(self.app.room_events, self.events)
        room_id = str(self.room["id"])
        result = self.app.create_room_work_item(room_id, {
            "currentOwnerParticipantId": self.worker_participant["id"], "clientMessageId": "created-1",
            "objective": "implement", "expectedOutput": "source", "acceptanceCriteria": ["tested"],
        })
        work_id = str(result["workItem"]["id"])
        self.assertEqual(self.app.room_work_item(room_id, work_id)["workItem"], result["workItem"])
        self.assertEqual(len(self.app.room_work_items(room_id)["items"]), 1)
        moved = self.app.reassign_room_work_item(room_id, work_id, {
            "actorParticipantId": self.worker_participant["id"],
            "targetParticipantId": self.researcher_participant["id"], "reason": "handoff",
        })
        self.assertEqual(moved["workItem"]["currentOwnerParticipantId"], self.researcher_participant["id"])

    def test_duplicate_assignment_preserves_message_identity_and_event_count(self):
        first = self._assign()
        second = self._assign()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["work"]["id"], second["work"]["id"])
        self.assertEqual(first["delivery"]["id"], second["delivery"]["id"])
        self.assertEqual([e["payload"]["phase"] for e in self.audit], ["assigned"])
        self.assertEqual(len(self.app.list_room_intercom(str(self.worker["id"]))["items"]), 1)
        self.assertIn(("intercom.send", str(self.worker["id"])), self.guards)

    def test_guard_and_membership_reject_before_assignment(self):
        with patch.object(self.app, "_guard_session_route", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(PermissionError, "denied"):
                self._assign()
        outsider = self.sessions.create(title="outsider")
        with self.assertRaisesRegex(ValueError, "participant"):
            self.app.assign_room_work(str(outsider["id"]), self._assignment("outside", self.worker_participant["id"]))
        self.assertEqual(self.app.room_work_items(str(self.room["id"]))["items"], [])

    def test_assignment_notification_failure_persists_failure_then_reraises(self):
        with patch.object(self.router, "enqueue", side_effect=RuntimeError("queue failed")):
            with self.assertRaisesRegex(RuntimeError, "queue failed"):
                self._assign()
        self.assertEqual([e["payload"]["phase"] for e in self.audit], ["assigned", "assignment_failed"])
        work = self.work.get(str(self.audit[-1]["payload"]["workItemId"]))
        self.assertEqual(work["state"], self.audit[-1]["payload"]["work"]["state"])
        self.assertNotEqual(work["state"], "queued")

    def test_submit_return_resubmit_accept_preserves_review_and_correlation(self):
        active = self._active()
        submitted = self._submit(active)["work"]
        returned = self.app.return_room_work(str(self.coordinator["id"]), {
            "workId": active["id"], "expectedRevision": submitted["revision"],
            "operabilityVerdict": "passed", "requirementVerdict": "not_satisfied",
            "evidenceRefs": ["test:room"], "reason": "missing edge case",
        })["work"]
        submitted = self._submit(returned)["work"]
        accepted = self.app.accept_room_work(str(self.coordinator["id"]), {
            "workId": active["id"], "expectedRevision": submitted["revision"],
            "operabilityVerdict": "passed", "requirementVerdict": "satisfied",
            "evidenceRefs": ["test:room"], "reason": "verified",
        })
        self.assertEqual(accepted["work"]["state"], "done")
        self.assertEqual(accepted["delivery"]["clientMessageId"], f"work-accepted:{active['id']}:{submitted['revision']}")
        self.assertEqual([e["payload"]["phase"] for e in self.audit], ["assigned", "submitted", "returned", "submitted", "completed"])
        self.assertEqual(len(self.app.list_room_work(str(self.worker["id"]))["items"]), 1)
        self.app._publish_room_work_activity(accepted["work"], phase="synced", actor=self.worker_participant, document_sync={"status": "updated"})
        self.assertEqual(self.audit[-1]["payload"]["documentSync"], {"status": "updated"})

    def test_submission_notification_failure_keeps_persisted_review_and_event(self):
        work = self._active()
        def fail_after_event(*_args, **_kwargs):
            self.assertEqual(self.audit[-1]["payload"]["phase"], "submitted")
            self.assertEqual(self.work.get(str(work["id"]))["state"], "review")
            raise RuntimeError("notification failed")
        with patch.object(self.router, "enqueue", side_effect=fail_after_event):
            with self.assertRaisesRegex(RuntimeError, "notification failed"):
                self._submit(work)
