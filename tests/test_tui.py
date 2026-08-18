import os
import unittest
from pathlib import Path

from rag_ime.tui import (
    _detail_text,
    _render_room,
    _render_session,
    _room_member_count,
    default_db_path,
    snapshot,
)


class FakeService:
    def __init__(self):
        self.session_payload = None
        self.room_payload = None

    def list_sessions(self, payload=None):
        self.session_payload = payload
        return {
            "items": [
                {"id": "s1", "title": "Build", "status": "active", "phase": "running", "roomParticipant": "r1"},
            ],
            "activeSessionId": "s1",
        }

    def list_rooms(self, payload=None):
        self.room_payload = payload
        return {
            "items": [
                {
                    "id": "r1",
                    "title": "Review",
                    "routingPolicy": "single_leader",
                    "participants": [{"id": "p1"}, {"id": "p2"}],
                },
            ]
        }


class TuiProjectionTests(unittest.TestCase):
    def test_snapshot_reads_session_and_room_projections(self):
        service = FakeService()
        self.assertEqual(
            snapshot(service),
            {
                "sessions": [
                    {
                        "id": "s1",
                        "title": "Build",
                        "status": "active",
                        "phase": "running",
                        "roomParticipant": "r1",
                    }
                ],
                "rooms": [
                    {
                        "id": "r1",
                        "title": "Review",
                        "routingPolicy": "single_leader",
                        "participants": [{"id": "p1"}, {"id": "p2"}],
                    }
                ],
                "activeSessionId": "s1",
            },
        )
        self.assertEqual(service.session_payload, {"limit": 500})
        self.assertEqual(service.room_payload, {"limit": 200})

    def test_render_session_marks_active_and_status(self):
        rendered = _render_session({"id": "s1", "title": "Build", "status": "active"}, "s1")
        self.assertIn("active", rendered)
        self.assertIn("Build", rendered)
        self.assertIn("s1", rendered)

    def test_render_room_includes_routing_policy_and_members(self):
        rendered = _render_room({
            "id": "r1",
            "title": "Review",
            "routingPolicy": "single_leader",
            "participants": [{"id": "p1"}, {"id": "p2"}],
        })
        self.assertIn("Review", rendered)
        self.assertIn("single_leader", rendered)
        self.assertIn("2", rendered)

    def test_room_member_count_from_participants_and_count(self):
        self.assertEqual(
            _room_member_count(
                {"participants": [{"id": "p1"}, {"id": "p2"}], "participantCount": 1}
            ),
            2,
        )
        self.assertEqual(_room_member_count({"participantCount": "3"}), 3)

    def test_detail_text(self):
        text = _detail_text({"id": "s1", "title": "Build", "status": "active"}, "session", active_session_id="s1")
        self.assertIn("Session*", text)
        self.assertIn("ID: s1", text)
        room_bound = _detail_text(
            {
                "id": "s1",
                "title": "Build",
                "status": "active",
                "roomParticipant": {"roomId": "room-1", "participantId": "participant-1"},
            },
            "session",
        )
        self.assertIn("Room: room-1", room_bound)

    def test_default_db_path_uses_env_when_present(self):
        home = str(Path.home())
        os.environ["RAG_IME_DB_PATH"] = str(Path(home) / "tmp" / "agent.sqlite")
        try:
            self.assertTrue(str(default_db_path()).endswith("tmp/agent.sqlite"))
        finally:
            os.environ.pop("RAG_IME_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
