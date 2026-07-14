from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


ROOM_EVENT_TYPES = frozenset(
    {
        "user_message",
        "route_decision",
        "participant_status",
        "participant_delta",
        "participant_activity",
        "participant_message",
        "turn_completed",
        "turn_failed",
        "snapshot_required",
    }
)


class AgentRoomNotFound(KeyError):
    pass


class AgentParticipantNotFound(KeyError):
    pass


class AgentRoomStore:
    """Persistent cross-session room timeline with a JSONL audit mirror."""

    def __init__(self, db_path: str | Path, *, room_dir: str | Path | None = None):
        self.db_path = Path(db_path)
        self.room_dir = Path(room_dir) if room_dir is not None else self.db_path.parent / "Agent" / "rooms"

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.room_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def create(
        self,
        *,
        title: str,
        routing_policy: str,
        participants: Sequence[Mapping[str, object]],
        moderator_ordinal: int = 0,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_title = " ".join(str(title).split())[:120]
        if not normalized_title:
            raise ValueError("agent room title must not be empty")
        if routing_policy not in {"manual_mentions", "moderator"}:
            raise ValueError("agent room routing policy must be manual_mentions or moderator")
        values = [dict(item) for item in participants]
        if not 2 <= len(values) <= 4:
            raise ValueError("agent room requires between 2 and 4 participants")
        if not 0 <= moderator_ordinal < len(values):
            raise ValueError("agent room moderator ordinal is out of range")

        timestamp = _timestamp(created_at_ms)
        room_id = f"room:{uuid.uuid4()}"
        participant_ids = [f"participant:{uuid.uuid4()}" for _ in values]
        moderator_id = participant_ids[moderator_ordinal] if routing_policy == "moderator" else ""
        room_file = self._room_file(room_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_rooms(
                    id, title, routing_policy, moderator_participant_id, status,
                    room_file, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    room_id,
                    normalized_title,
                    routing_policy,
                    moderator_id,
                    str(room_file),
                    timestamp,
                    timestamp,
                ),
            )
            for ordinal, (participant_id, value) in enumerate(zip(participant_ids, values, strict=True)):
                session_id = _required_text(value, "sessionId")
                role_id = _required_text(value, "roleId")
                role_version = _required_text(value, "roleVersion")
                display_name = " ".join(_required_text(value, "displayName").split())[:40]
                conn.execute(
                    """
                    INSERT INTO agent_room_participants(
                        id, room_id, session_id, role_id, role_version, display_name,
                        participant_status, ordinal, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        participant_id,
                        room_id,
                        session_id,
                        role_id,
                        role_version,
                        display_name,
                        ordinal,
                        timestamp,
                    ),
                )
        return self.get(room_id)

    def get(self, room_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agent_rooms WHERE id = ?", (room_id,)).fetchone()
            if row is None:
                raise AgentRoomNotFound(room_id)
            participants = conn.execute(
                """
                SELECT * FROM agent_room_participants
                WHERE room_id = ? ORDER BY ordinal ASC
                """,
                (room_id,),
            ).fetchall()
        return _room_payload(row, participants)

    def list(self, *, include_archived: bool = False, limit: int = 100) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 200))
        where = "" if include_archived else "WHERE status = 'active'"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM agent_rooms {where} ORDER BY updated_at_ms DESC LIMIT ?",  # noqa: S608
                (bounded,),
            ).fetchall()
        return [self.get(str(row["id"])) for row in rows]

    def archive(self, room_id: str, *, archived: bool, updated_at_ms: int | None = None) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_rooms SET status = ?, updated_at_ms = ? WHERE id = ?",
                ("archived" if archived else "active", timestamp, room_id),
            )
            if cursor.rowcount != 1:
                raise AgentRoomNotFound(room_id)
        return self.get(room_id)

    def participant(self, participant_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_participants WHERE id = ?",
                (participant_id,),
            ).fetchone()
        if row is None:
            raise AgentParticipantNotFound(participant_id)
        return _participant_payload(row)

    def participant_for_session(
        self,
        session_id: str,
        *,
        active_only: bool = True,
    ) -> dict[str, object] | None:
        active_filter = (
            "AND p.participant_status = 'active' AND r.status = 'active'"
            if active_only
            else ""
        )
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT p.* FROM agent_room_participants p
                JOIN agent_rooms r ON r.id = p.room_id
                WHERE p.session_id = ? {active_filter}
                """,  # noqa: S608 - active_filter is a fixed internal clause
                (session_id,),
            ).fetchone()
        return _participant_payload(row) if row is not None else None

    def route_target(self, room_id: str, text: str) -> dict[str, object]:
        room = self.get(room_id)
        if room["status"] != "active":
            raise ValueError("agent room is archived")
        participants = [
            dict(item)
            for item in room["participants"]
            if isinstance(item, Mapping) and item.get("status") == "active"
        ]
        lowered = str(text).casefold()
        matched: list[dict[str, object]] = []
        for participant in participants:
            aliases = {
                f"@{str(participant['displayName']).casefold()}",
                f"@{str(participant['roleId']).casefold()}",
            }
            if any(alias in lowered for alias in aliases):
                matched.append(participant)
        if len(matched) > 1:
            raise ValueError("first room version supports exactly one addressed participant")
        if matched:
            return matched[0]
        if room["routingPolicy"] == "moderator":
            moderator_id = str(room["moderatorParticipantId"] or "")
            for participant in participants:
                if participant["id"] == moderator_id:
                    return participant
            raise ValueError("agent room moderator is unavailable")
        raise ValueError("message must mention one room participant, for example @智鼬")

    def append_event(
        self,
        *,
        room_id: str,
        event_type: str,
        payload: Mapping[str, object],
        turn_id: str = "",
        participant_id: str | None = None,
        source_session_id: str = "",
        created_at_ms: int | None = None,
        retain_per_room: int = 2000,
    ) -> dict[str, object]:
        if event_type not in ROOM_EVENT_TYPES:
            raise ValueError(f"unsupported agent room event type: {event_type}")
        timestamp = _timestamp(created_at_ms)
        safe_payload = dict(payload)
        payload_json = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            room = conn.execute("SELECT * FROM agent_rooms WHERE id = ?", (room_id,)).fetchone()
            if room is None:
                raise AgentRoomNotFound(room_id)
            if participant_id:
                participant = conn.execute(
                    "SELECT session_id FROM agent_room_participants WHERE id = ? AND room_id = ?",
                    (participant_id, room_id),
                ).fetchone()
                if participant is None:
                    raise AgentParticipantNotFound(participant_id)
            sequence = int(room["last_event_sequence"]) + 1
            event_id = f"{room_id}:{sequence}"
            event = {
                "schemaVersion": "rag-ime.agent-room-event.v1",
                "eventId": event_id,
                "roomId": room_id,
                "sequence": sequence,
                "turnId": str(turn_id or ""),
                "eventType": event_type,
                "participantId": participant_id,
                "sourceSessionId": str(source_session_id or ""),
                "createdAtMs": timestamp,
                "payload": safe_payload,
                "resumeToken": event_id,
            }
            validate_contract(event, "agent-room-event.v1.json")
            conn.execute(
                """
                INSERT INTO agent_room_events(
                    event_id, room_id, sequence, turn_id, event_type,
                    participant_id, source_session_id, created_at_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    room_id,
                    sequence,
                    str(turn_id or ""),
                    event_type,
                    participant_id,
                    str(source_session_id or ""),
                    timestamp,
                    payload_json,
                ),
            )
            conn.execute(
                """
                UPDATE agent_rooms
                SET last_event_sequence = ?, updated_at_ms = ? WHERE id = ?
                """,
                (sequence, timestamp, room_id),
            )
            if participant_id and event_type in {"participant_message", "turn_completed"}:
                conn.execute(
                    "UPDATE agent_room_participants SET last_spoke_at_ms = ? WHERE id = ?",
                    (timestamp, participant_id),
                )
            conn.execute(
                "DELETE FROM agent_room_events WHERE room_id = ? AND sequence <= ?",
                (room_id, max(0, sequence - max(100, int(retain_per_room)))),
            )
            self._append_jsonl(Path(str(room["room_file"])), event)
        return event

    def list_events(
        self,
        room_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        self.get(room_id)
        bounded = max(1, min(int(limit), 2000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_room_events
                WHERE room_id = ? AND sequence > ?
                ORDER BY sequence ASC LIMIT ?
                """,
                (room_id, max(0, int(after_sequence)), bounded),
            ).fetchall()
        return [_room_event_payload(row) for row in rows]

    def event_bounds(self, room_id: str) -> tuple[int, int]:
        self.get(room_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MIN(sequence), 0), COALESCE(MAX(sequence), 0)
                FROM agent_room_events WHERE room_id = ?
                """,
                (room_id,),
            ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else (0, 0)

    def _room_file(self, room_id: str) -> Path:
        safe_name = room_id.replace(":", "-")
        return self.room_dir / f"{safe_name}.jsonl"

    @staticmethod
    def _append_jsonl(path: Path, event: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            payload = (json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


class AgentRoomEventHub:
    """Ordered room SSE fan-out backed by AgentRoomStore replay."""

    def __init__(self, store: AgentRoomStore) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._subscribers: dict[str, set[queue.Queue[dict[str, object]]]] = {}

    def publish(self, **values: object) -> dict[str, object]:
        with self._lock:
            event = self.store.append_event(**values)  # type: ignore[arg-type]
            subscribers = tuple(self._subscribers.get(str(event["roomId"]), ()))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass
        return event

    def subscribe(
        self,
        room_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        after_sequence = _room_event_sequence(room_id, after_event_id)
        if after_event_id and after_sequence is None:
            raise ValueError("room event resume token does not belong to this room")
        subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=128)
        with self._lock:
            first_sequence, last_sequence = self.store.event_bounds(room_id)
            gap = bool(
                after_sequence
                and (
                    after_sequence > last_sequence
                    or (first_sequence > 0 and after_sequence < first_sequence - 1)
                )
            )
            if gap:
                replay = [
                    self.store.append_event(
                        room_id=room_id,
                        event_type="snapshot_required",
                        payload={
                            "reason": "room_event_replay_gap",
                            "afterEventId": after_event_id,
                        },
                    )
                ]
            else:
                replay = self.store.list_events(room_id, after_sequence=after_sequence or 0, limit=2000)
            self._subscribers.setdefault(room_id, set()).add(subscriber)
        delivered_sequence = after_sequence or 0
        try:
            yield b": connected\n\n"
            for event in replay:
                delivered_sequence = max(delivered_sequence, int(event["sequence"]))
                yield _room_event_sse(event)
            while True:
                try:
                    event = subscriber.get(timeout=heartbeat_seconds)
                    if int(event["sequence"]) <= delivered_sequence:
                        continue
                    delivered_sequence = int(event["sequence"])
                    yield _room_event_sse(event)
                except queue.Empty:
                    yield b": heartbeat\n\n"
        finally:
            with self._lock:
                self._subscribers.get(room_id, set()).discard(subscriber)
                if not self._subscribers.get(room_id):
                    self._subscribers.pop(room_id, None)


def _room_payload(row: sqlite3.Row, participants: Sequence[sqlite3.Row]) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-room.v1",
        "id": str(row["id"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "routingPolicy": str(row["routing_policy"]),
        "moderatorParticipantId": str(row["moderator_participant_id"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "lastEventSequence": int(row["last_event_sequence"]),
        "participants": [_participant_payload(item) for item in participants],
    }
    validate_contract(payload, "agent-room.v1.json")
    return payload


def _participant_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-participant.v1",
        "id": str(row["id"]),
        "roomId": str(row["room_id"]),
        "sessionId": str(row["session_id"]),
        "roleId": str(row["role_id"]),
        "roleVersion": str(row["role_version"]),
        "displayName": str(row["display_name"]),
        "status": str(row["participant_status"]),
        "ordinal": int(row["ordinal"]),
        "createdAtMs": int(row["created_at_ms"]),
        "lastSpokeAtMs": int(row["last_spoke_at_ms"]) if row["last_spoke_at_ms"] is not None else None,
    }
    validate_contract(payload, "agent-participant.v1.json")
    return payload


def _room_event_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-room-event.v1",
        "eventId": str(row["event_id"]),
        "roomId": str(row["room_id"]),
        "sequence": int(row["sequence"]),
        "turnId": str(row["turn_id"] or ""),
        "eventType": str(row["event_type"]),
        "participantId": str(row["participant_id"]) if row["participant_id"] is not None else None,
        "sourceSessionId": str(row["source_session_id"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "payload": json.loads(str(row["payload_json"] or "{}")),
        "resumeToken": str(row["event_id"]),
    }
    validate_contract(payload, "agent-room-event.v1.json")
    return payload


def _room_event_sse(event: Mapping[str, object]) -> bytes:
    body = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {event['eventId']}\n"
        f"event: {event['eventType']}\n"
        f"data: {body}\n\n"
    ).encode("utf-8")


def _room_event_sequence(room_id: str, event_id: str) -> int | None:
    if not event_id:
        return 0
    prefix = f"{room_id}:"
    if not event_id.startswith(prefix):
        return None
    try:
        return int(event_id[len(prefix) :])
    except ValueError:
        return None


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = " ".join(str(payload.get(key) or "").split())
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def _timestamp(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)
