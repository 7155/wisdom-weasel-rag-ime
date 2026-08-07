from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.room_application.outbox import (
    RoomApplicationOutbox,
    StaleRoomOutboxLease,
)


class RoomApplicationOutboxLeaseFencingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "room.sqlite3"
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE room_domain_events (
                    event_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    room_sequence INTEGER NOT NULL
                );
                CREATE TABLE room_application_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    effect_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    available_at_ms INTEGER NOT NULL,
                    lease_id TEXT NOT NULL DEFAULT '',
                    lease_until_ms INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT INTO room_domain_events(event_id,room_id,room_sequence) VALUES (?,?,?)",
                ("event-1", "room-1", 1),
            )
            payload = {
                "outboxId": "outbox-1",
                "eventId": "event-1",
                "effectKind": "wake_room",
                "roomId": "room-1",
                "rootId": "root-1",
                "generation": 1,
            }
            conn.execute(
                """INSERT INTO room_application_outbox(
                   outbox_id,event_id,room_id,root_id,effect_kind,state,attempt,
                   available_at_ms,lease_id,lease_until_ms,last_error,payload_json,
                   created_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,'pending',0,?,'',0,'',?,?,?)""",
                (
                    "outbox-1",
                    "event-1",
                    "room-1",
                    "root-1",
                    "wake_room",
                    0,
                    json.dumps(payload),
                    0,
                    0,
                ),
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_late_worker_cannot_apply_replacement_lease(self) -> None:
        outbox = RoomApplicationOutbox(self.db_path, lease_ms=1_000)
        first = outbox._lease("room-1", now_ms=100)
        second = outbox._lease("room-1", now_ms=1_101)
        assert first is not None and second is not None
        self.assertNotEqual(first["leaseId"], second["leaseId"])

        with self.assertRaises(StaleRoomOutboxLease):
            outbox._apply(
                "outbox-1",
                lease_id=str(first["leaseId"]),
                attempt=int(first["attempt"]),
                now_ms=1_102,
            )

        outbox._apply(
            "outbox-1",
            lease_id=str(second["leaseId"]),
            attempt=int(second["attempt"]),
            now_ms=1_103,
        )
        with sqlite3.connect(self.db_path) as conn:
            state, attempt, lease_id = conn.execute(
                "SELECT state,attempt,lease_id FROM room_application_outbox"
            ).fetchone()
        self.assertEqual((state, attempt, lease_id), ("applied", 2, ""))

    def test_late_failure_cannot_overwrite_newer_lease(self) -> None:
        outbox = RoomApplicationOutbox(self.db_path, lease_ms=1_000)
        first = outbox._lease("room-1", now_ms=100)
        second = outbox._lease("room-1", now_ms=1_101)
        assert first is not None and second is not None

        with self.assertRaises(StaleRoomOutboxLease):
            outbox._fail(
                "outbox-1",
                lease_id=str(first["leaseId"]),
                attempt=int(first["attempt"]),
                error="late failure",
                now_ms=1_102,
            )
        with sqlite3.connect(self.db_path) as conn:
            state, attempt, lease_id = conn.execute(
                "SELECT state,attempt,lease_id FROM room_application_outbox"
            ).fetchone()
        self.assertEqual((state, attempt, lease_id), ("leased", 2, second["leaseId"]))

    def test_callback_error_is_not_masked_after_lease_replacement(self) -> None:
        outbox = RoomApplicationOutbox(self.db_path, lease_ms=1_000)

        def replace_then_fail(_room_id: str) -> None:
            replacement = outbox._lease("room-1", now_ms=1_101)
            self.assertIsNotNone(replacement)
            raise ValueError("projection failed")

        with self.assertRaisesRegex(ValueError, "projection failed"):
            outbox.drain_room(
                "room-1",
                project_room=replace_then_fail,
                wake_room=replace_then_fail,
                now_ms=100,
                limit=1,
            )

        with sqlite3.connect(self.db_path) as conn:
            state, attempt, lease_id = conn.execute(
                "SELECT state,attempt,lease_id FROM room_application_outbox"
            ).fetchone()
        self.assertEqual(state, "leased")
        self.assertEqual(attempt, 2)
        self.assertTrue(lease_id)


if __name__ == "__main__":
    unittest.main()
