from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .agent_room_kernel_contracts import validate_kernel_contract
from .agent_sessions import agent_todo_projection
from .db import apply_database_migrations


class RoomKernelProjection:
    """Durable ordered read model derived only from Kernel-owned tables."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        with self._connect(immediate=True) as conn:
            return apply_database_migrations(conn).current_version

    def sync_room(self, room_id: str, *, now_ms: int | None = None) -> list[dict[str, object]]:
        room_id = _required(room_id, "room_id")
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._connect(immediate=True) as conn:
            records = self._records(conn, room_id)
            emitted: list[dict[str, object]] = []
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM room_kernel_events WHERE room_id = ?",
                    (room_id,),
                ).fetchone()[0]
            )
            for projection_kind, projection_id, entity_kind, entity_id, event_kind, payload in records:
                content_hash = _hash(payload)
                prior = conn.execute(
                    """SELECT content_hash FROM room_kernel_projection_hashes
                       WHERE room_id = ? AND projection_kind = ? AND projection_id = ?""",
                    (room_id, projection_kind, projection_id),
                ).fetchone()
                if prior is not None and str(prior["content_hash"]) == content_hash:
                    continue
                sequence += 1
                event = {
                    "schemaVersion": "wisdom-weasel.room-event-envelope.v2",
                    "entityKind": entity_kind,
                    "entityId": entity_id,
                    "eventKind": event_kind,
                    "sequence": sequence,
                    "occurredAtMs": timestamp,
                    "payload": payload,
                }
                validate_kernel_contract("eventEnvelope", event)
                conn.execute(
                    """INSERT INTO room_kernel_events(
                       room_id, sequence, entity_kind, entity_id, event_kind,
                       payload_json, occurred_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        room_id,
                        sequence,
                        entity_kind,
                        entity_id,
                        event_kind,
                        _json(event),
                        timestamp,
                    ),
                )
                conn.execute(
                    """INSERT INTO room_kernel_projection_hashes(
                       room_id, projection_kind, projection_id, content_hash)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(room_id, projection_kind, projection_id)
                       DO UPDATE SET content_hash = excluded.content_hash""",
                    (room_id, projection_kind, projection_id, content_hash),
                )
                emitted.append(event)
            return emitted

    def snapshot(self, room_id: str) -> dict[str, object]:
        room_id = _required(room_id, "room_id")
        with self._connect() as conn:
            records = self._records(conn, room_id)
            roots: list[dict[str, object]] = []
            tasks: list[dict[str, object]] = []
            dispatches: list[dict[str, object]] = []
            posts: list[dict[str, object]] = []
            sessions: list[dict[str, object]] = []
            receipts: list[dict[str, object]] = []
            for kind, _projection_id, _entity_kind, _entity_id, _event_kind, payload in records:
                value = next(iter(payload.values()))
                if kind == "root":
                    roots.append(value)
                elif kind == "task":
                    tasks.append(value)
                elif kind == "dispatch":
                    dispatches.append(value)
                elif kind == "post":
                    posts.append(value)
                elif kind == "session":
                    sessions.append(value)
                elif kind == "receipt":
                    receipts.append(value)
            task_updated_at_ms_by_id = {
                str(row["task_id"]): int(row["updated_at_ms"])
                for row in conn.execute(
                    """SELECT task.task_id,task.updated_at_ms
                       FROM room_kernel_tasks AS task
                       JOIN room_kernel_roots AS root
                         ON root.root_id=task.root_id
                       WHERE root.room_id=?
                       ORDER BY task.task_id""",
                    (room_id,),
                ).fetchall()
            }
            last_sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM room_kernel_events WHERE room_id = ?",
                    (room_id,),
                ).fetchone()[0]
            )
        material = {
            "roomId": room_id,
            "lastSequence": last_sequence,
            "roots": roots,
            "tasks": tasks,
            "taskUpdatedAtMsById": task_updated_at_ms_by_id,
            "dispatches": dispatches,
            "posts": posts,
            "sessions": sessions,
            "receipts": receipts,
        }
        return {**material, "snapshotHash": f"sha256:{_hash(material)}"}

    def events(self, room_id: str, *, after_sequence: int = 0, limit: int = 2000) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT payload_json FROM room_kernel_events
                   WHERE room_id = ? AND sequence > ? ORDER BY sequence LIMIT ?""",
                (_required(room_id, "room_id"), max(0, int(after_sequence)), max(1, min(int(limit), 5000))),
            ).fetchall()
            return [json.loads(str(row["payload_json"])) for row in rows]

    def event_bounds(self, room_id: str) -> tuple[int, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MIN(sequence), 0), COALESCE(MAX(sequence), 0) FROM room_kernel_events WHERE room_id = ?",
                (_required(room_id, "room_id"),),
            ).fetchone()
            return int(row[0]), int(row[1])

    def subscribe(
        self,
        room_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        room_id = _required(room_id, "room_id")
        after_sequence = _event_sequence(room_id, after_event_id)
        first, last = self.event_bounds(room_id)
        if after_sequence > last or (first and after_sequence < first - 1):
            yield _sse(
                "snapshot_required",
                f"{room_id}#{last}",
                {"roomId": room_id, "lastSequence": last, "reason": "event_replay_gap"},
            )
            return
        delivered = after_sequence
        yield b": connected\n\n"
        while True:
            replay = self.events(room_id, after_sequence=delivered)
            for event in replay:
                delivered = int(event["sequence"])
                yield _sse("room_kernel_event", f"{room_id}#{delivered}", event)
            time.sleep(max(0.01, float(heartbeat_seconds)))
            if not replay:
                yield b": heartbeat\n\n"

    def publish_post(self, payload: Mapping[str, object]) -> dict[str, object]:
        validate_kernel_contract("roomPost", payload)
        encoded = _json(payload)
        with self._connect(immediate=True) as conn:
            root = conn.execute(
                "SELECT room_id, generation FROM room_kernel_roots WHERE root_id = ?",
                (payload["rootId"],),
            ).fetchone()
            if root is None or root["room_id"] != payload["roomId"] or int(root["generation"]) != int(payload["generation"]):
                raise ValueError("RoomPost does not match the current Root generation")
            existing = conn.execute(
                "SELECT payload_json FROM room_kernel_posts WHERE room_id = ? AND idempotency_key = ?",
                (payload["roomId"], payload["idempotencyKey"]),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != encoded:
                    raise ValueError("RoomPost idempotency key was rebound")
                return json.loads(str(existing["payload_json"]))
            conn.execute(
                """INSERT INTO room_kernel_posts(
                   post_id, room_id, root_id, generation, idempotency_key,
                   payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["postId"], payload["roomId"], payload["rootId"],
                    payload["generation"], payload["idempotencyKey"], encoded,
                    payload["createdAtMs"],
                ),
            )
        return dict(payload)

    def _records(self, conn: sqlite3.Connection, room_id: str):
        records: list[tuple[str, str, str, str, str, dict[str, object]]] = []
        roots = conn.execute(
            "SELECT * FROM room_kernel_roots WHERE room_id = ? ORDER BY created_at_ms, root_id",
            (room_id,),
        ).fetchall()
        root_ids = [str(row["root_id"]) for row in roots]
        for row in roots:
            root = json.loads(str(row["payload_json"]))
            root.update(
                generation=int(row["generation"]),
                state=str(row["state"]),
                terminalReceiptId=row["terminal_receipt_id"],
            )
            records.append(("root", str(row["root_id"]), "root", str(row["root_id"]), "state_changed", {"root": root}))
        if not root_ids:
            return records
        placeholders = ",".join("?" for _ in root_ids)
        tasks = conn.execute(
            f"SELECT * FROM room_kernel_tasks WHERE root_id IN ({placeholders}) ORDER BY task_id",
            root_ids,
        ).fetchall()
        for row in tasks:
            task = json.loads(str(row["payload_json"]))
            task["state"] = str(row["state"])
            records.append(("task", str(row["task_id"]), "task", str(row["task_id"]), "state_changed", {"task": task}))
        dispatches = conn.execute(
            f"SELECT * FROM room_kernel_dispatches WHERE root_id IN ({placeholders}) ORDER BY dispatch_id",
            root_ids,
        ).fetchall()
        for row in dispatches:
            dispatch = json.loads(str(row["payload_json"]))
            dispatch["state"] = str(row["state"])
            records.append(("dispatch", str(row["dispatch_id"]), "dispatch", str(row["dispatch_id"]), "state_changed", {"dispatch": dispatch}))
        posts = conn.execute(
            "SELECT * FROM room_kernel_posts WHERE room_id = ? ORDER BY created_at_ms, post_id",
            (room_id,),
        ).fetchall()
        for row in posts:
            post = json.loads(str(row["payload_json"]))
            records.append(("post", str(row["post_id"]), "post", str(row["post_id"]), "published", {"post": post}))
        receipts = conn.execute(
            f"SELECT * FROM room_kernel_receipts WHERE root_id IN ({placeholders}) ORDER BY created_at_ms, receipt_id",
            root_ids,
        ).fetchall()
        for row in receipts:
            receipt = json.loads(str(row["payload_json"]))
            records.append(("receipt", str(row["receipt_id"]), "root", str(row["root_id"]), "kernel_receipt", {"receipt": receipt}))
        latest_sessions: dict[str, sqlite3.Row] = {}
        session_state_rank = {
            "running": 0,
            "leased": 1,
            "retry_wait": 2,
            "timer_wait": 3,
            "pending": 4,
        }
        for row in dispatches:
            session_id = str(row["target_session_id"])
            current = latest_sessions.get(session_id)
            candidate_key = (
                session_state_rank.get(str(row["state"]), 5),
                -int(row["updated_at_ms"]),
                str(row["dispatch_id"]),
            )
            current_key = (
                session_state_rank.get(str(current["state"]), 5),
                -int(current["updated_at_ms"]),
                str(current["dispatch_id"]),
            ) if current is not None else None
            if current_key is None or candidate_key < current_key:
                latest_sessions[session_id] = row
        participants = conn.execute(
            """
            SELECT id,session_id,participant_status,created_at_ms
            FROM agent_room_participants
            WHERE room_id=? AND participant_status='active'
            ORDER BY ordinal,id
            """,
            (room_id,),
        ).fetchall()
        participants_by_session = {
            str(row["session_id"]): row
            for row in participants
            if str(row["session_id"] or "").strip()
        }
        session_ids = sorted(
            set(latest_sessions) | set(participants_by_session)
        )
        for session_id in session_ids:
            row = latest_sessions.get(session_id)
            participant = participants_by_session.get(session_id)
            state = str(row["state"]) if row is not None else "idle"
            todo = agent_todo_projection(conn, session_id)
            task_payload: dict[str, object] = {}
            if row is not None:
                task_row = conn.execute(
                    "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                    (row["task_id"],),
                ).fetchone()
                if task_row is not None:
                    decoded_task = json.loads(str(task_row["payload_json"]))
                    if isinstance(decoded_task, Mapping):
                        task_payload = dict(decoded_task)
            session = {
                "sessionId": session_id,
                "rootId": str(row["root_id"]) if row is not None else None,
                "taskId": str(row["task_id"]) if row is not None else None,
                "taskKind": (
                    str(task_payload.get("taskKind") or "") or None
                    if row is not None
                    else None
                ),
                "workItemId": (
                    str(task_payload.get("workItemId") or "") or None
                    if row is not None
                    else None
                ),
                "dispatchId": (
                    str(row["dispatch_id"]) if row is not None else None
                ),
                "generation": int(row["generation"]) if row is not None else 0,
                "state": _session_state(state) if row is not None else "idle",
                "updatedAtMs": max(
                    int(row["updated_at_ms"]) if row is not None else 0,
                    int(todo.get("updatedAtMs") or 0),
                    int(participant["created_at_ms"])
                    if participant is not None
                    else 0,
                ),
                "todo": todo,
            }
            if participant is not None:
                session["participantId"] = str(participant["id"])
            if row is None:
                records.append(("session", session_id, "binding", session_id, "session_projection", {"session": session}))
                continue
            capability = conn.execute(
                """SELECT b.*, m.root_id, m.task_id, m.dispatch_id, m.generation
                   FROM room_v2_capability_runtime_bindings b
                   JOIN room_v2_capability_manifests m ON m.manifest_id = b.manifest_id
                   WHERE b.session_id = ? AND m.root_id = ? AND m.dispatch_id = ?""",
                (session_id, row["root_id"], row["dispatch_id"]),
            ).fetchone()
            if capability is not None:
                session["capabilityManifest"] = {
                    "manifestId": str(capability["manifest_id"]),
                    "manifestHash": str(capability["manifest_hash"]),
                    "status": str(capability["state"]),
                    "rootId": str(capability["root_id"]),
                    "taskId": str(capability["task_id"]),
                    "dispatchId": str(capability["dispatch_id"]),
                    "generation": int(capability["generation"]),
                    "capabilityEpoch": int(capability["capability_epoch"]),
                    "promptCompileReceiptId": str(capability["prompt_compile_receipt_id"]),
                    "promptPlanHash": str(capability["prompt_plan_hash"]),
                    "compiledRuntimeProfileRef": {
                        "profileId": str(capability["compiled_profile_id"]),
                        "revision": str(capability["compiled_profile_revision"]),
                        "contentHash": str(capability["compiled_profile_hash"]),
                    },
                }
            requirement = conn.execute(
                "SELECT * FROM room_v2_dispatch_requirement_bindings WHERE dispatch_id = ?",
                (row["dispatch_id"],),
            ).fetchone()
            if requirement is not None:
                session["requirementObservation"] = {
                    "anchorRefs": json.loads(str(requirement["anchor_refs_json"])),
                    "catalogRevisionId": str(requirement["catalog_revision_id"]) if requirement["catalog_revision_id"] else None,
                    "proofReceiptRefs": json.loads(str(requirement["proof_receipt_refs_json"])),
                    "warnings": json.loads(str(requirement["observation_warnings_json"])),
                    "gateObservationRef": str(requirement["gate_observation_ref"]) if requirement["gate_observation_ref"] else None,
                    "state": str(requirement["state"]),
                }
            records.append(("session", session_id, "binding", session_id, "session_projection", {"session": session}))
        return records

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if immediate:
                conn.commit()
        except Exception:
            if immediate:
                conn.rollback()
            raise
        finally:
            conn.close()


def _session_state(state: str) -> str:
    if state in {"pending", "leased", "retry_wait", "timer_wait"}:
        return "queued"
    if state == "running":
        return "running"
    if state == "committed":
        return "completed"
    if state == "cancelled":
        return "cancelled"
    if state in {"unknown", "dead_letter", "failed"}:
        return "failed"
    return "idle"


def _event_sequence(room_id: str, event_id: str) -> int:
    if not event_id:
        return 0
    prefix = f"{room_id}#"
    if not event_id.startswith(prefix):
        raise ValueError("Room Kernel event resume token belongs to another Room")
    value = event_id[len(prefix) :]
    if not value.isdigit():
        raise ValueError("Room Kernel event resume token is invalid")
    return int(value)


def _sse(event: str, event_id: str, payload: Mapping[str, object]) -> bytes:
    return (
        f"id: {event_id}\nevent: {event}\ndata: {_json(payload)}\n\n"
    ).encode("utf-8")


def _required(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
