from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.rooms.store import AgentRoomEventHub, AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


def _sse_payload(frame: bytes) -> dict[str, object]:
    data = next(
        line.removeprefix("data: ")
        for line in frame.decode("utf-8").splitlines()
        if line.startswith("data: ")
    )
    value = json.loads(data)
    if not isinstance(value, dict):
        raise AssertionError("Room SSE data must be an object")
    return value


class AgentRoomEventHubGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-gap-")
        root = Path(self.tmp.name)
        db_path = root / "rag-ime.sqlite"
        sessions = AgentSessionStore(db_path)
        sessions.initialize()
        self.store = AgentRoomStore(db_path, room_dir=root / "rooms")
        self.store.initialize()
        participants = []
        for ordinal, role_id in enumerate(
            ("companion-present-v1", "companion-future-v1"),
            start=1,
        ):
            session = sessions.create(
                title=f"Room participant {ordinal}",
                role_id=role_id,
                role_version="1",
            )
            participants.append(
                {
                    "sessionId": str(session["id"]),
                    "roleId": role_id,
                    "roleVersion": "1",
                    "displayName": f"Participant {ordinal}",
                }
            )
        room = self.store.create(
            title="Replay gap",
            routing_policy="natural",
            participants=participants,
        )
        self.room_id = str(room["id"])
        self.hub = AgentRoomEventHub(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gap_control_is_subscriber_local_and_live_delivery_recovers(self) -> None:
        first = self.hub.publish(
            room_id=self.room_id,
            event_type="user_message",
            payload={"text": "first"},
        )
        before_events = self.store.list_events(self.room_id)
        before_bounds = self.store.event_bounds(self.room_id)
        before_sequence = self.store.get(self.room_id)["lastEventSequence"]

        ordinary = self.hub.subscribe(
            self.room_id,
            after_event_id=str(first["eventId"]),
            heartbeat_seconds=0.01,
        )
        gap = self.hub.subscribe(
            self.room_id,
            after_event_id=f"{self.room_id}:999",
            heartbeat_seconds=0.01,
        )
        self.assertEqual(next(ordinary), b": connected\n\n")
        self.assertEqual(next(gap), b": connected\n\n")

        control = _sse_payload(next(gap))
        self.assertEqual(control["eventType"], "snapshot_required")
        self.assertEqual(control["payload"]["reason"], "room_event_replay_gap")
        self.assertEqual(self.store.list_events(self.room_id), before_events)
        self.assertEqual(self.store.event_bounds(self.room_id), before_bounds)
        self.assertEqual(
            self.store.get(self.room_id)["lastEventSequence"], before_sequence
        )

        second = self.hub.publish(
            room_id=self.room_id,
            event_type="participant_message",
            payload={"text": "second"},
        )
        self.assertEqual(_sse_payload(next(ordinary))["eventId"], second["eventId"])
        self.assertEqual(_sse_payload(next(gap))["eventId"], second["eventId"])
        self.assertEqual(
            [event["eventType"] for event in self.store.list_events(self.room_id)],
            ["user_message", "participant_message"],
        )
        self.assertEqual(
            [event["sequence"] for event in self.store.list_events(self.room_id)],
            [1, 2],
        )
        ordinary.close()
        gap.close()


if __name__ == "__main__":
    unittest.main()
