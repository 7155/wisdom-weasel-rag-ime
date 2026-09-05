"""Same-host supervisor leases; all claims and fenced mutations use SQLite.

The deadline uses the host's monotonic clock, not wall time or log activity.
This is not a protocol for sharing a SQLite file across machines. A lease
generation identifies a supervisor, not another execution of the command.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .db import sqlite_connection
from .room_runtime_host_kill_gate import _process_identity


class BackgroundJobLeaseLost(RuntimeError):
    """The old supervisor must detach without killing or cleaning the worker."""


class BackgroundJobOwnership:
    def __init__(self, db_path: Path, *, lease_seconds: float = 10.0) -> None:
        if not 1 <= lease_seconds <= 300:
            raise ValueError("background job lease must be between 1 and 300 seconds")
        self.db_path = db_path
        self.lease_ms = int(lease_seconds * 1000)
        self.owner_id = uuid.uuid4().hex
        self.pid = os.getpid()
        identity = _process_identity(self.pid)
        if identity is None:
            raise RuntimeError("background supervisor process identity is unavailable")
        self.birth = identity[1]
        # Never reuse a retired generation in this instance. A restarted service
        # or another supervisor can claim it; old callbacks remain fenced.
        self.tokens: dict[str, int] = {}
        self._local = threading.local()

    def _write_claim(self, conn, job_id: str, generation: int) -> None:
        conn.execute(
            """INSERT INTO agent_background_job_owner_leases
               (job_id, owner_id, generation, owner_pid, owner_birth_token,
                heartbeat_at_ms, deadline_tick_ms) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET owner_id=excluded.owner_id,
                generation=excluded.generation, owner_pid=excluded.owner_pid,
                owner_birth_token=excluded.owner_birth_token,
                heartbeat_at_ms=excluded.heartbeat_at_ms,
                deadline_tick_ms=excluded.deadline_tick_ms""",
            (job_id, self.owner_id, generation, self.pid, self.birth,
             int(time.time() * 1000), _tick_ms() + self.lease_ms),
        )
        self.tokens[job_id] = generation

    def admit(self, conn, job_id: str) -> None:
        """Called in the same transaction that admits a new queued command."""
        self._write_claim(conn, job_id, 1)

    def claim(self, job_id: str) -> bool:
        if job_id in self.tokens:
            return False
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute("SELECT status FROM agent_background_jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None or job["status"] not in {"queued", "running", "cancelling"}:
                return False
            lease = conn.execute("SELECT * FROM agent_background_job_owner_leases WHERE job_id=?", (job_id,)).fetchone()
            if lease is not None and int(lease["deadline_tick_ms"]) > _tick_ms():
                if not _owner_proven_dead(int(lease["owner_pid"]), str(lease["owner_birth_token"])):
                    return False
            self._write_claim(conn, job_id, int(lease["generation"]) + 1 if lease else 1)
            return True

    @contextmanager
    def guard(self, job_id: str, *, renew_expired: bool = False):
        """Validate and mutate under one write transaction, including local I/O.

        Nested helpers reuse this connection. Another claimant cannot pass the
        fence between the ownership check and a result write, signal or cleanup.
        Event publication is deferred until the outer transaction is committed.
        """
        active = getattr(self._local, "active", None)
        if active is not None:
            current_job, conn, _callbacks = active
            if current_job != job_id:
                raise RuntimeError("cannot nest background ownership for different jobs")
            yield conn
            return
        callbacks = []
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            lease = conn.execute("SELECT * FROM agent_background_job_owner_leases WHERE job_id=?", (job_id,)).fetchone()
            tick = _tick_ms()
            if (lease is None or lease["owner_id"] != self.owner_id
                or int(lease["generation"]) != self.tokens.get(job_id)
                or (int(lease["deadline_tick_ms"]) <= tick and not renew_expired)):
                raise BackgroundJobLeaseLost(f"background job ownership was lost: {job_id}")
            # A heartbeat can recover a scheduling pause only while the exact
            # owner/generation is still current. It cannot renew after takeover.
            if int(lease["deadline_tick_ms"]) - tick < self.lease_ms * 2 // 3:
                conn.execute(
                    "UPDATE agent_background_job_owner_leases SET heartbeat_at_ms=?, deadline_tick_ms=? WHERE job_id=?",
                    (int(time.time() * 1000), tick + self.lease_ms, job_id),
                )
            self._local.active = (job_id, conn, callbacks)
            try:
                yield conn
            finally:
                self._local.active = None
        for callback in callbacks:
            callback()

    def defer_event(self, callback) -> bool:
        active = getattr(self._local, "active", None)
        if active is None:
            return False
        active[2].append(callback)
        return True

    def current_connection(self, job_id: str):
        active = getattr(self._local, "active", None)
        return active[1] if active is not None and active[0] == job_id else None

    def release_all(self) -> None:
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                "UPDATE agent_background_job_owner_leases SET deadline_tick_ms=0 WHERE owner_id=?",
                (self.owner_id,),
            )


def _tick_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _owner_proven_dead(pid: int, birth: str) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    observed = _process_identity(pid)
    return observed is not None and observed[1] != birth
