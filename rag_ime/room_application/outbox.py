from __future__ import annotations

import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from ..db import apply_database_migrations


class StaleRoomOutboxLease(RuntimeError):
    """A late dispatcher attempted to settle a lease that was replaced."""


class RoomApplicationOutbox:
    """At-least-once dispatcher with lease fencing and per-Room isolation."""

    def __init__(self, db_path: str | Path, *, lease_ms: int = 120_000) -> None:
        self.db_path = Path(db_path)
        self.lease_ms = int(lease_ms)
        if self.lease_ms < 1_000 or self.lease_ms > 3_600_000:
            raise ValueError("lease_ms must be between 1000 and 3600000")

    def initialize(self) -> int:
        with self._connect(immediate=True) as conn:
            return apply_database_migrations(conn).current_version

    def drain_room(
        self,
        room_id: str,
        *,
        project_room: Callable[[str], object],
        wake_room: Callable[[str], object],
        now_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        applied: list[dict[str, object]] = []
        for _ in range(max(0, min(int(limit), 1000))):
            leased = self._lease(room_id, now_ms=self._now(now_ms))
            if leased is None:
                break
            callback = (
                project_room
                if leased["effectKind"] == "project_room"
                else wake_room
            )
            try:
                callback(room_id)
            except Exception as exc:
                try:
                    self._fail(
                        str(leased["outboxId"]),
                        lease_id=str(leased["leaseId"]),
                        attempt=int(leased["attempt"]),
                        error=f"{type(exc).__name__}: {exc}"[:500],
                        now_ms=self._now(now_ms),
                    )
                except StaleRoomOutboxLease:
                    # Preserve the callback failure while leaving the replacement
                    # worker's newer lease untouched.
                    pass
                raise
            self._apply(
                str(leased["outboxId"]),
                lease_id=str(leased["leaseId"]),
                attempt=int(leased["attempt"]),
                now_ms=self._now(now_ms),
            )
            applied.append(leased)
        return applied

    def drain_ready_rooms(
        self,
        *,
        project_room: Callable[[str], object],
        wake_room: Callable[[str], object],
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._connect() as conn:
            room_ids = [
                str(row["room_id"])
                for row in conn.execute(
                    """SELECT DISTINCT room_id FROM room_application_outbox
                       WHERE (
                         state IN ('pending','retry_wait')
                         AND available_at_ms<=?
                       ) OR (
                         state='leased' AND lease_until_ms<=?
                       )
                       ORDER BY room_id""",
                    (timestamp, timestamp),
                ).fetchall()
            ]
        result: dict[str, object] = {"applied": {}, "failed": {}}
        for room_id in room_ids:
            try:
                result["applied"][room_id] = self.drain_room(
                    room_id,
                    project_room=project_room,
                    wake_room=wake_room,
                    now_ms=timestamp,
                )
            except Exception as exc:
                result["failed"][room_id] = f"{type(exc).__name__}: {exc}"[:500]
        return result

    def pending(self, room_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT payload_json,state,attempt,lease_id,lease_until_ms,last_error
                   FROM room_application_outbox
                   WHERE room_id=? AND state!='applied'
                   ORDER BY created_at_ms,outbox_id""",
                (room_id,),
            ).fetchall()
        return [
            {
                **json.loads(str(row["payload_json"])),
                "state": str(row["state"]),
                "attempt": int(row["attempt"]),
                "leaseId": str(row["lease_id"]),
                "leaseUntilMs": int(row["lease_until_ms"]),
                "lastError": str(row["last_error"]),
            }
            for row in rows
        ]

    def _lease(self, room_id: str, *, now_ms: int) -> dict[str, object] | None:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """SELECT outbox.*
                   FROM room_application_outbox AS outbox
                   JOIN room_domain_events AS event
                     ON event.event_id=outbox.event_id
                   WHERE outbox.room_id=? AND outbox.state!='applied'
                   ORDER BY event.room_sequence,
                            CASE outbox.effect_kind
                              WHEN 'project_room' THEN 0 ELSE 1 END,
                            outbox.outbox_id
                   LIMIT 1""",
                (room_id,),
            ).fetchone()
            if row is None:
                return None
            state = str(row["state"])
            if state == "dead_letter":
                return None
            if (
                state in {"pending", "retry_wait"}
                and int(row["available_at_ms"]) > int(now_ms)
            ):
                return None
            if state == "leased" and int(row["lease_until_ms"]) > int(now_ms):
                return None
            attempt = int(row["attempt"]) + 1
            lease_id = secrets.token_hex(16)
            cursor = conn.execute(
                """UPDATE room_application_outbox
                   SET state='leased',attempt=?,lease_id=?,lease_until_ms=?,updated_at_ms=?
                   WHERE outbox_id=? AND (
                     (state IN ('pending','retry_wait') AND available_at_ms<=?)
                     OR (state='leased' AND lease_until_ms<=?)
                   )""",
                (
                    attempt,
                    lease_id,
                    int(now_ms) + self.lease_ms,
                    int(now_ms),
                    row["outbox_id"],
                    int(now_ms),
                    int(now_ms),
                ),
            )
            if cursor.rowcount != 1:
                return None
            return {
                **json.loads(str(row["payload_json"])),
                "attempt": attempt,
                "leaseId": lease_id,
                "leaseUntilMs": int(now_ms) + self.lease_ms,
            }

    def _apply(
        self,
        outbox_id: str,
        *,
        lease_id: str,
        attempt: int,
        now_ms: int,
    ) -> None:
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """UPDATE room_application_outbox
                   SET state='applied',lease_id='',lease_until_ms=0,
                       last_error='',updated_at_ms=?
                   WHERE outbox_id=? AND state='leased'
                     AND lease_id=? AND attempt=?""",
                (int(now_ms), outbox_id, lease_id, int(attempt)),
            )
            if cursor.rowcount != 1:
                raise StaleRoomOutboxLease(
                    f"outbox lease was replaced before apply: {outbox_id}"
                )

    def _fail(
        self,
        outbox_id: str,
        *,
        lease_id: str,
        attempt: int,
        error: str,
        now_ms: int,
    ) -> None:
        state = "dead_letter" if int(attempt) >= 5 else "retry_wait"
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """UPDATE room_application_outbox
                   SET state=?,available_at_ms=?,lease_id='',lease_until_ms=0,
                       last_error=?,updated_at_ms=?
                   WHERE outbox_id=? AND state='leased'
                     AND lease_id=? AND attempt=?""",
                (
                    state,
                    int(now_ms)
                    + min(30_000, 1_000 * (2 ** max(0, int(attempt) - 1))),
                    error,
                    int(now_ms),
                    outbox_id,
                    lease_id,
                    int(attempt),
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRoomOutboxLease(
                    f"outbox lease was replaced before failure recording: {outbox_id}"
                )

    @staticmethod
    def _now(override: int | None) -> int:
        return int(override if override is not None else time.time() * 1000)

    def _connect(self, *, immediate: bool = False):
        return _Connection(self.db_path, immediate=immediate)


class _Connection:
    def __init__(self, db_path: Path, *, immediate: bool) -> None:
        self.db_path = db_path
        self.immediate = immediate
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.immediate:
            conn.execute("BEGIN IMMEDIATE")
        self.conn = conn
        return conn

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.conn is not None
        try:
            if self.immediate:
                self.conn.rollback() if exc_type else self.conn.commit()
        finally:
            self.conn.close()
