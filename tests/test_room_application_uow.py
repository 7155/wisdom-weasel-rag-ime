from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.room_application.outbox import RoomApplicationOutbox
from rag_ime.room_application.repositories import RoomDomainEventRepository
from rag_ime.room_application.unit_of_work import RoomUnitOfWork
from rag_ime.room_domain.events import past_tense_event


class RoomApplicationUnitOfWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "room.db"
        self.uow = RoomUnitOfWork(self.db_path)
        self.uow.initialize()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_transition_event_and_effects_commit_together(self) -> None:
        with self.uow.transaction() as conn:
            self._insert_root(conn, room_id="room:a", root_id="root:a")
            RoomDomainEventRepository.append(
                conn,
                self._event(room_id="room:a", root_id="root:a"),
                created_at_ms=10,
            )

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM room_domain_events").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM room_application_outbox").fetchone()[0],
                2,
            )

    def test_rollback_leaves_neither_half_state_nor_half_event(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.uow.transaction() as conn:
                self._insert_root(conn, room_id="room:a", root_id="root:a")
                RoomDomainEventRepository.append(
                    conn,
                    self._event(room_id="room:a", root_id="root:a"),
                    created_at_ms=10,
                )
                raise RuntimeError("force rollback")

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_kernel_roots").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_domain_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_application_outbox").fetchone()[0], 0)

    def test_one_malformed_room_does_not_stop_another_room_outbox(self) -> None:
        with self.uow.transaction() as conn:
            for suffix in ("a", "b"):
                self._insert_root(
                    conn,
                    room_id=f"room:{suffix}",
                    root_id=f"root:{suffix}",
                )
                RoomDomainEventRepository.append(
                    conn,
                    self._event(
                        room_id=f"room:{suffix}",
                        root_id=f"root:{suffix}",
                    ),
                    created_at_ms=10,
                )

        projected: list[str] = []
        woken: list[str] = []

        def project(room_id: str) -> None:
            if room_id == "room:a":
                raise ValueError("malformed projection")
            projected.append(room_id)

        outbox = RoomApplicationOutbox(self.db_path)
        result = outbox.drain_ready_rooms(
            project_room=project,
            wake_room=woken.append,
            now_ms=10,
        )

        self.assertIn("room:a", result["failed"])
        self.assertEqual(projected, ["room:b"])
        self.assertEqual(woken, ["room:b"])
        self.assertEqual(outbox.pending("room:b"), [])
        pending_a = outbox.pending("room:a")
        self.assertEqual(len(pending_a), 2)
        self.assertEqual(pending_a[0]["state"], "retry_wait")

    def test_expired_lease_is_reclaimed_after_process_restart(self) -> None:
        with self.uow.transaction() as conn:
            self._insert_root(conn, room_id="room:a", root_id="root:a")
            RoomDomainEventRepository.append(
                conn,
                self._event(room_id="room:a", root_id="root:a"),
                created_at_ms=10,
            )
            conn.execute(
                """UPDATE room_application_outbox
                   SET state='leased',attempt=1,lease_until_ms=20
                   WHERE room_id='room:a' AND effect_kind='project_room'"""
            )

        projected: list[str] = []
        woken: list[str] = []
        outbox = RoomApplicationOutbox(self.db_path)
        result = outbox.drain_ready_rooms(
            project_room=projected.append,
            wake_room=woken.append,
            now_ms=21,
        )
        applied = result["applied"]["room:a"]

        self.assertEqual(
            [item["effectKind"] for item in applied],
            ["project_room", "wake_room"],
        )
        self.assertEqual(projected, ["room:a"])
        self.assertEqual(woken, ["room:a"])
        self.assertEqual(outbox.pending("room:a"), [])

    def test_wake_cannot_overtake_projection_retry(self) -> None:
        with self.uow.transaction() as conn:
            self._insert_root(conn, room_id="room:a", root_id="root:a")
            RoomDomainEventRepository.append(
                conn,
                self._event(room_id="room:a", root_id="root:a"),
                created_at_ms=10,
            )

        projected: list[str] = []
        woken: list[str] = []
        failures = 0

        def project(room_id: str) -> None:
            nonlocal failures
            if failures == 0:
                failures += 1
                raise ValueError("projection temporarily unavailable")
            projected.append(room_id)

        outbox = RoomApplicationOutbox(self.db_path)
        with self.assertRaises(ValueError):
            outbox.drain_room(
                "room:a",
                project_room=project,
                wake_room=woken.append,
                now_ms=10,
            )

        self.assertEqual(
            outbox.drain_room(
                "room:a",
                project_room=project,
                wake_room=woken.append,
                now_ms=11,
            ),
            [],
        )
        self.assertEqual(woken, [])

        applied = outbox.drain_room(
            "room:a",
            project_room=project,
            wake_room=woken.append,
            now_ms=1_010,
        )
        self.assertEqual(
            [item["effectKind"] for item in applied],
            ["project_room", "wake_room"],
        )
        self.assertEqual(projected, ["room:a"])
        self.assertEqual(woken, ["room:a"])

    @staticmethod
    def _insert_root(
        conn: sqlite3.Connection,
        *,
        room_id: str,
        root_id: str,
    ) -> None:
        conn.execute(
            """INSERT INTO room_kernel_roots(
               root_id,room_id,generation,state,facilitator_participant_id,
               requirement_anchor_ref,
               budget_remaining,budget_reserved,max_hops,max_depth,
               acceptance_criteria_json,covered_criteria_json,
               terminal_receipt_id,payload_json,created_at_ms,updated_at_ms)
               VALUES (?, ?, 1, 'running', 'kernel', 'requirement:1',
                       10, 0, 4, 4, '[\"criterion:1\"]', '[]', NULL,
                       '{}', 1, 1)""",
            (root_id, room_id),
        )

    @staticmethod
    def _event(*, room_id: str, root_id: str):
        return past_tense_event(
            kind="dispatch_completed",
            room_id=room_id,
            root_id=root_id,
            entity_id=f"dispatch:{root_id}",
            generation=1,
            idempotency_key=f"commit:{root_id}",
            payload={"taskId": f"task:{root_id}"},
        )


if __name__ == "__main__":
    unittest.main()
