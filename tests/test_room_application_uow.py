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

    def test_dead_letter_head_is_reported_as_a_room_blocker(self) -> None:
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

        outbox = RoomApplicationOutbox(self.db_path)
        expected_head = outbox.pending("room:a")[0]

        def broken_projection(_room_id: str) -> None:
            raise ValueError("projection permanently broken")

        for attempt, now_ms in enumerate((10, 1_010, 3_010, 7_010, 15_010), start=1):
            with self.assertRaisesRegex(ValueError, "projection permanently broken"):
                outbox.drain_room(
                    "room:a",
                    project_room=broken_projection,
                    wake_room=lambda _room_id: None,
                    now_ms=now_ms,
                )
            self.assertEqual(outbox.pending("room:a")[0]["attempt"], attempt)

        projected: list[str] = []
        woken: list[str] = []
        result = outbox.drain_ready_rooms(
            project_room=projected.append,
            wake_room=woken.append,
            now_ms=31_010,
        )

        self.assertEqual(projected, ["room:b"])
        self.assertEqual(woken, ["room:b"])
        self.assertEqual(result["applied"]["room:b"][0]["effectKind"], "project_room")
        blocker = result["blocked"]["room:a"]
        self.assertEqual(blocker["outboxId"], expected_head["outboxId"])
        self.assertEqual(blocker["eventId"], expected_head["eventId"])
        self.assertEqual(
            blocker,
            {
                "outboxId": expected_head["outboxId"],
                "eventId": expected_head["eventId"],
                "rootId": "root:a",
                "effectKind": "project_room",
                "state": "dead_letter",
                "attempt": 5,
                "lastError": "ValueError: projection permanently broken",
            },
        )

    def test_dead_letter_projection_does_not_starve_later_room_events(self) -> None:
        with self.uow.transaction() as conn:
            self._insert_root(conn, room_id="room:a", root_id="root:a")
            RoomDomainEventRepository.append(
                conn,
                self._event(room_id="room:a", root_id="root:a", suffix="first"),
                created_at_ms=10,
            )
            RoomDomainEventRepository.append(
                conn,
                self._event(room_id="room:a", root_id="root:a", suffix="later"),
                created_at_ms=11,
            )

        outbox = RoomApplicationOutbox(self.db_path)

        def broken_projection(_room_id: str) -> None:
            raise ValueError("projection permanently broken")

        for now_ms in (10, 1_010, 3_010, 7_010, 15_010):
            with self.assertRaisesRegex(ValueError, "projection permanently broken"):
                outbox.drain_room(
                    "room:a",
                    project_room=broken_projection,
                    wake_room=lambda _room_id: None,
                    now_ms=now_ms,
                )

        projected: list[str] = []
        woken: list[str] = []
        result = outbox.drain_ready_rooms(
            project_room=projected.append,
            wake_room=woken.append,
            now_ms=31_010,
        )

        self.assertEqual(projected, ["room:a"])
        self.assertEqual(woken, ["room:a"])
        self.assertEqual(
            [item["effectKind"] for item in result["applied"]["room:a"]],
            ["project_room", "wake_room"],
        )
        self.assertEqual(result["blocked"]["room:a"]["state"], "dead_letter")
        self.assertEqual(
            [item["state"] for item in outbox.pending("room:a")],
            ["dead_letter", "dead_letter"],
        )

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
    def _event(*, room_id: str, root_id: str, suffix: str = ""):
        identity = f"{root_id}:{suffix}" if suffix else root_id
        return past_tense_event(
            kind="dispatch_completed",
            room_id=room_id,
            root_id=root_id,
            entity_id=f"dispatch:{identity}",
            generation=1,
            idempotency_key=f"commit:{identity}",
            payload={"taskId": f"task:{identity}"},
        )


if __name__ == "__main__":
    unittest.main()
