"""Durable scene-trial admission and lifecycle; no Provider execution or resume.

Only job_input/claim are private application APIs. All read/admit/mutation
responses project the public spec and aggregate report, never prepared input.
The adapter owns publicSpec/report redaction and prepare must be read-only.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from ..db import apply_database_migrations, sqlite_connection

SCHEMA_VERSION = "rag-ime.agent-lab-trial.v1"
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class AgentLabTrialConflict(RuntimeError):
    http_status = 409
    reason_code = "request_id_conflict"

    def __init__(self):
        super().__init__("The trial request ID is already bound to different input.")

    def response_payload(self):
        return {"ok": False, "code": "AGENT_LAB_TRIAL_CONFLICT", "reasonCode": self.reason_code, "error": str(self)}


class AgentLabTrialNotFound(KeyError):
    http_status = 404

    def __init__(self):
        super().__init__("Lab trial not found")


class AgentLabTrialServiceUnavailable(RuntimeError):
    http_status = 503

    def __init__(self):
        super().__init__("Lab trial execution owner is unavailable.")

    def response_payload(self) -> dict:
        return {"ok": False, "code": "AGENT_LAB_TRIAL_SERVICE_UNAVAILABLE", "error": str(self)}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON mapping")
    encoded = _json(dict(value))
    if len(encoded.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError(f"{name} exceeds the 8 MiB trial input/report limit")
    return json.loads(encoded)


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a nonempty identifier of at most 256 characters")
    return value


def _now() -> int:
    return time.time_ns() // 1_000_000


def _public(row: sqlite3.Row) -> dict:
    return {
        "jobId": row["job_id"], "clientRequestId": row["client_request_id"],
        "sceneId": row["scene_id"], "state": row["state"],
        "publicSpec": json.loads(row["public_spec_json"]),
        "cancelRequested": bool(row["cancel_requested"]),
        "progress": row["progress"], "sessions": json.loads(row["sessions_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] is not None else None,
        "error": row["error"], "createdAtMs": row["created_at_ms"], "updatedAtMs": row["updated_at_ms"],
        "resumeAvailable": False,
    }


def _row(conn, job_id):
    row = conn.execute("SELECT * FROM agent_lab_trials WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise AgentLabTrialNotFound()
    return row


class AgentLabTrialStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._initialize_lock = threading.Lock()
        self._initialized = False
        self.initialize()

    def initialize(self) -> None:
        with self._initialize_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite_connection(self.db_path) as conn:
                apply_database_migrations(conn)
            self._initialized = True

    def _connection(self):
        return sqlite_connection(self.db_path, row_factory=sqlite3.Row)

    def admit(self, client_request_id: str, scene_id: str, spec: Mapping, prepare: Callable) -> dict:
        _identifier(client_request_id, "client_request_id")
        _identifier(scene_id, "scene_id")
        request_spec = _mapping(spec, "spec")
        fingerprint = hashlib.sha256(_json({"sceneId": scene_id, "spec": request_spec}).encode()).hexdigest()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM agent_lab_trials WHERE client_request_id=?", (client_request_id,)).fetchone()
            if previous is not None:
                if previous["request_sha256"] != fingerprint:
                    raise AgentLabTrialConflict()
                return {"schemaVersion": SCHEMA_VERSION, "job": _public(previous), "replayed": True}
            job_id = "lab-trial:" + uuid.uuid4().hex
            # Atomic admission ensures another click cannot independently
            # freeze a different recipe. prepare must do no paid/mutating work.
            prepared = prepare(request_spec, job_id)
            if not isinstance(prepared, Mapping) or set(prepared) != {"publicSpec", "privateInput"}:
                raise ValueError("Adapter prepare must return publicSpec and privateInput")
            public = _mapping(prepared["publicSpec"], "publicSpec")
            private = _mapping(prepared["privateInput"], "privateInput")
            timestamp = _now()
            conn.execute(
                "INSERT INTO agent_lab_trials(job_id,client_request_id,scene_id,request_sha256,public_spec_json,private_input_json,state,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,'queued',?,?)",
                (job_id, client_request_id, scene_id, fingerprint, _json(public), _json(private), timestamp, timestamp),
            )
            return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id)), "replayed": False}

    def read(self, job_id: str = "") -> dict:
        with self._connection() as conn:
            if job_id:
                return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id))}
            rows = conn.execute("SELECT * FROM agent_lab_trials ORDER BY created_at_ms DESC, job_id DESC").fetchall()
            return {"schemaVersion": SCHEMA_VERSION, "jobs": [_public(row) for row in rows]}

    def job_input(self, job_id: str) -> dict:
        """Private execution-only read; never expose via a route or UI."""
        with self._connection() as conn:
            row = _row(conn, job_id)
            return {"job": _public(row), "privateInput": json.loads(row["private_input_json"])}

    def claim(self, job_id: str) -> dict | None:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _row(conn, job_id)
            if row["state"] != "queued":
                return None
            conn.execute("UPDATE agent_lab_trials SET state='running',progress='Starting registered scene execution',updated_at_ms=? WHERE job_id=?", (_now(), job_id))
            row = _row(conn, job_id)
            return {"job": _public(row), "privateInput": json.loads(row["private_input_json"])}

    def request_cancel(self, job_id: str) -> dict:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _row(conn, job_id)
            if row["state"] not in TERMINAL_STATES:
                state = "cancelled" if row["state"] == "queued" else "cancelling"
                conn.execute("UPDATE agent_lab_trials SET state=?,cancel_requested=1,progress=?,updated_at_ms=? WHERE job_id=?", (state, "Cancelled before execution" if state == "cancelled" else "Cancellation requested; awaiting execution cleanup", _now(), job_id))
            return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id))}

    def progress(self, job_id: str, message: str) -> dict:
        if not isinstance(message, str) or len(message) > 2000:
            raise ValueError("progress must be public text of at most 2000 characters")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _row(conn, job_id)
            if row["state"] == "running":
                conn.execute("UPDATE agent_lab_trials SET progress=?,updated_at_ms=? WHERE job_id=?", (message, _now(), job_id))
            return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id))}

    def bind_session(self, job_id: str, session_id: str, turn_id: str = "") -> dict:
        _identifier(session_id, "session_id")
        if turn_id:
            _identifier(turn_id, "turn_id")
        binding = {"sessionId": session_id, "turnId": turn_id}
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _row(conn, job_id)
            if row["state"] in {"running", "cancelling"}:
                sessions = json.loads(row["sessions_json"])
                if binding not in sessions:
                    sessions.append(binding)
                    conn.execute("UPDATE agent_lab_trials SET sessions_json=?,updated_at_ms=? WHERE job_id=?", (_json(sessions), _now(), job_id))
            return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id))}

    def finish(self, job_id: str, state: str, *, result: Mapping | None = None, error: str = "") -> dict:
        if state not in TERMINAL_STATES:
            raise ValueError("finish requires a terminal state")
        report = _mapping(result, "report") if result is not None else None
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _row(conn, job_id)
            if row["state"] not in TERMINAL_STATES:
                if row["state"] == "queued" and state != "interrupted":
                    raise ValueError("Queued jobs must be claimed before completion")
                if row["cancel_requested"] and state != "interrupted":
                    state = "cancelled"
                    # A settled failure/cancellation report can explain the
                    # stop and retain actual cost. Late success remains unable
                    # to overwrite cancellation or publish a success report.
                    if report is None or report.get("status") not in {"failed", "cancelled", "interrupted"}:
                        report = None
                conn.execute("UPDATE agent_lab_trials SET state=?,result_json=?,error=?,progress=?,updated_at_ms=? WHERE job_id=?", (state, _json(report) if report is not None else None, error, state, _now(), job_id))
            return {"schemaVersion": SCHEMA_VERSION, "job": _public(_row(conn, job_id))}

    def recover_interrupted(self) -> list[dict]:
        """Called once by a replacement Application, never by read or replay.

        The host must have stopped the prior Application before replacing it.
        No queue or uncertain paid request is automatically re-executed.
        """
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT job_id FROM agent_lab_trials WHERE state IN ('queued','running','cancelling')").fetchall()
            conn.execute("UPDATE agent_lab_trials SET state='interrupted',error='Execution owner stopped; inspect the original bindings. Resume is unavailable.',progress='interrupted',updated_at_ms=? WHERE state IN ('queued','running','cancelling')", (_now(),))
            return [_public(_row(conn, row["job_id"])) for row in rows]
