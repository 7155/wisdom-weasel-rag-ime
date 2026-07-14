from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


_KINDS = frozenset({"send", "ask", "reply"})
_STATUSES = frozenset(
    {"queued", "delivering", "delivered", "replied", "failed", "stale", "cancelled"}
)
_MAX_PENDING_PER_ROOM = 100


class AgentRoomTargetBusy(RuntimeError):
    """The target changed state after the idle gate; delivery may be retried."""


class AgentRoomIntercomStore:
    """Durable, idempotent participant-to-participant room messages."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)
            now = _now_ms()
            cursor = conn.execute(
                """
                UPDATE agent_room_intercom_messages
                SET status = 'failed',
                    error = 'delivery outcome unknown after Sidecar restart',
                    updated_at_ms = ?
                WHERE status = 'delivering'
                """,
                (now,),
            )
        return max(0, int(cursor.rowcount))

    def resolve_route(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        with self._connect() as conn:
            return self._resolve_route_conn(conn, source_session_id, payload)

    def enqueue(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
        *,
        source_generation: int,
        target_generation: int,
        expected_target_participant_id: str,
        created_at_ms: int | None = None,
    ) -> tuple[dict[str, object], bool]:
        timestamp = int(created_at_ms if created_at_ms is not None else _now_ms())
        with self._connect(immediate=True) as conn:
            route = self._resolve_route_conn(conn, source_session_id, payload)
            existing = route.get("existing")
            if isinstance(existing, Mapping):
                return dict(existing), False
            target = route["target"]
            if str(target["id"]) != str(expected_target_participant_id):
                raise ValueError("room intercom target changed before enqueue")
            room_id = str(route["roomId"])
            pending = conn.execute(
                """
                SELECT COUNT(*) FROM agent_room_intercom_messages
                WHERE room_id = ? AND status IN ('queued', 'delivering')
                """,
                (room_id,),
            ).fetchone()
            if int(pending[0] if pending else 0) >= _MAX_PENDING_PER_ROOM:
                raise ValueError("agent room intercom queue is full")

            source = route["source"]
            message_id = f"room-message:{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO agent_room_intercom_messages(
                    id, room_id, kind, source_participant_id, target_participant_id,
                    source_session_id, target_session_id, source_generation,
                    target_generation, client_message_id, reply_to_message_id,
                    status, content, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    message_id,
                    room_id,
                    route["kind"],
                    source["id"],
                    target["id"],
                    source["sessionId"],
                    target["sessionId"],
                    max(0, int(source_generation)),
                    max(0, int(target_generation)),
                    route["clientMessageId"],
                    route["replyTo"] or None,
                    route["content"],
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_room_intercom_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the insert transaction
            raise RuntimeError("room intercom enqueue did not persist")
        return _intercom_payload(row), True

    def get(self, message_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_intercom_messages WHERE id = ?",
                (str(message_id or "").strip(),),
            ).fetchone()
        if row is None:
            raise KeyError(message_id)
        return _intercom_payload(row)

    def list_for_session(
        self,
        session_id: str,
        *,
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        normalized_status = str(status or "").strip()
        if normalized_status and normalized_status not in _STATUSES:
            raise ValueError("unsupported room intercom status")
        bounded = max(1, min(int(limit), 200))
        with self._connect() as conn:
            participant = conn.execute(
                "SELECT room_id FROM agent_room_participants WHERE session_id = ?",
                (str(session_id or "").strip(),),
            ).fetchone()
            if participant is None:
                raise ValueError("session is not a room participant")
            if normalized_status:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_room_intercom_messages
                    WHERE room_id = ? AND status = ?
                    ORDER BY created_at_ms DESC, id DESC LIMIT ?
                    """,
                    (str(participant["room_id"]), normalized_status, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_room_intercom_messages
                    WHERE room_id = ?
                    ORDER BY created_at_ms DESC, id DESC LIMIT ?
                    """,
                    (str(participant["room_id"]), bounded),
                ).fetchall()
        return [_intercom_payload(row) for row in rows]

    def next_queued(self) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_room_intercom_messages
                WHERE status = 'queued'
                ORDER BY created_at_ms ASC, id ASC LIMIT 1
                """
            ).fetchone()
        return _intercom_payload(row) if row is not None else None

    def claim(self, message_id: str) -> dict[str, object] | None:
        now = _now_ms()
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE agent_room_intercom_messages
                SET status = 'delivering', updated_at_ms = ?, error = ''
                WHERE id = ? AND status = 'queued'
                """,
                (now, message_id),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM agent_room_intercom_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        return _intercom_payload(row) if row is not None else None

    def requeue(self, message_id: str, *, error: str = "") -> dict[str, object]:
        return self._transition(
            message_id,
            expected="delivering",
            status="queued",
            error=error,
        )

    def mark_failed(
        self,
        message_id: str,
        *,
        error: str,
        stale: bool = False,
        expected: str | None = None,
    ) -> dict[str, object]:
        return self._transition(
            message_id,
            expected=expected,
            status="stale" if stale else "failed",
            error=error,
        )

    def mark_delivered(self, message_id: str, *, accepted_turn_id: str) -> dict[str, object]:
        now = _now_ms()
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE agent_room_intercom_messages
                SET status = 'delivered', accepted_turn_id = ?, error = '',
                    delivered_at_ms = ?, updated_at_ms = ?
                WHERE id = ? AND status = 'delivering'
                """,
                (str(accepted_turn_id or "")[:240], now, now, message_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("room intercom message is no longer delivering")
            row = conn.execute(
                "SELECT * FROM agent_room_intercom_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is not None and str(row["kind"]) == "reply" and row["reply_to_message_id"]:
                conn.execute(
                    """
                    UPDATE agent_room_intercom_messages
                    SET status = 'replied', replied_at_ms = ?, updated_at_ms = ?
                    WHERE id = ? AND kind = 'ask' AND status = 'delivered'
                    """,
                    (now, now, str(row["reply_to_message_id"])),
                )
        if row is None:  # pragma: no cover - guarded by the update
            raise KeyError(message_id)
        return _intercom_payload(row)

    def _transition(
        self,
        message_id: str,
        *,
        expected: str | None,
        status: str,
        error: str,
    ) -> dict[str, object]:
        if status not in _STATUSES:
            raise ValueError("unsupported room intercom transition")
        now = _now_ms()
        where = "id = ?" if expected is None else "id = ? AND status = ?"
        values: tuple[object, ...] = (
            (status, _bounded_error(error), now, message_id)
            if expected is None
            else (status, _bounded_error(error), now, message_id, expected)
        )
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                f"""
                UPDATE agent_room_intercom_messages
                SET status = ?, error = ?, updated_at_ms = ? WHERE {where}
                """,  # noqa: S608 - where is selected from fixed internal clauses
                values,
            )
            if cursor.rowcount != 1:
                raise ValueError("room intercom message state changed before transition")
            row = conn.execute(
                "SELECT * FROM agent_room_intercom_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by the update
            raise KeyError(message_id)
        return _intercom_payload(row)

    def _resolve_route_conn(
        self,
        conn: sqlite3.Connection,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        kind = str(payload.get("kind") or "").strip()
        if kind not in _KINDS:
            raise ValueError("room intercom kind must be send, ask, or reply")
        content = _content(payload.get("content"))
        client_message_id = _client_message_id(payload.get("clientMessageId"))
        reply_to = str(payload.get("replyTo") or "").strip()
        source = conn.execute(
            """
            SELECT p.*, r.status AS room_status
            FROM agent_room_participants p
            JOIN agent_rooms r ON r.id = p.room_id
            WHERE p.session_id = ?
            """,
            (str(source_session_id or "").strip(),),
        ).fetchone()
        if source is None or str(source["participant_status"]) != "active":
            raise ValueError("source session is not an active room participant")
        if str(source["room_status"]) != "active":
            raise ValueError("agent room is archived")
        room_id = str(source["room_id"])

        existing = conn.execute(
            """
            SELECT * FROM agent_room_intercom_messages
            WHERE room_id = ? AND source_participant_id = ? AND client_message_id = ?
            """,
            (room_id, str(source["id"]), client_message_id),
        ).fetchone()
        requested_target = str(payload.get("targetParticipantId") or "").strip()
        if existing is not None:
            if (
                str(existing["kind"]) != kind
                or str(existing["content"]) != content
                or str(existing["reply_to_message_id"] or "") != reply_to
                or requested_target
                and str(existing["target_participant_id"]) != requested_target
            ):
                raise ValueError("clientMessageId was already used for a different room message")
            target = conn.execute(
                "SELECT * FROM agent_room_participants WHERE id = ?",
                (str(existing["target_participant_id"]),),
            ).fetchone()
            return {
                "roomId": room_id,
                "kind": kind,
                "content": content,
                "clientMessageId": client_message_id,
                "replyTo": reply_to,
                "source": _participant_identity(source),
                "target": _participant_identity(target),
                "existing": _intercom_payload(existing),
            }

        if kind == "reply":
            if not reply_to:
                raise ValueError("room reply requires replyTo")
            if requested_target:
                raise ValueError("room reply target is derived from the original ask")
            ask = conn.execute(
                """
                SELECT * FROM agent_room_intercom_messages
                WHERE id = ? AND room_id = ? AND kind = 'ask'
                """,
                (reply_to, room_id),
            ).fetchone()
            if ask is None:
                raise ValueError("room replyTo does not identify an ask in this room")
            if str(ask["target_participant_id"]) != str(source["id"]):
                raise ValueError("only the addressed participant may reply to this ask")
            if str(ask["status"]) not in {"delivered", "replied"}:
                raise ValueError("room ask must be delivered before it can be replied to")
            duplicate_reply = conn.execute(
                "SELECT id FROM agent_room_intercom_messages WHERE reply_to_message_id = ?",
                (reply_to,),
            ).fetchone()
            if duplicate_reply is not None:
                raise ValueError("room ask already has a reply")
            target_id = str(ask["source_participant_id"])
        else:
            if reply_to:
                raise ValueError("replyTo is only valid for room replies")
            if not requested_target:
                raise ValueError("targetParticipantId is required")
            target_id = requested_target

        target = conn.execute(
            """
            SELECT * FROM agent_room_participants
            WHERE id = ? AND room_id = ? AND participant_status = 'active'
            """,
            (target_id, room_id),
        ).fetchone()
        if target is None:
            raise ValueError("target is not an active participant in the same room")
        if str(target["id"]) == str(source["id"]):
            raise ValueError("room participants cannot send intercom messages to themselves")
        return {
            "roomId": room_id,
            "kind": kind,
            "content": content,
            "clientMessageId": client_message_id,
            "replyTo": reply_to,
            "source": _participant_identity(source),
            "target": _participant_identity(target),
        }

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


class AgentRoomIntercomRouter:
    """Idle-gated delivery worker; Pi remains the owner of each participant transcript."""

    def __init__(
        self,
        store: AgentRoomIntercomStore,
        *,
        generation_provider: Callable[[str], int],
        idle_probe: Callable[[str], bool],
        delivery_handler: Callable[[Mapping[str, object]], Mapping[str, object]],
        audit_publisher: Callable[[Mapping[str, object], str], None],
    ) -> None:
        self.store = store
        self.generation_provider = generation_provider
        self.idle_probe = idle_probe
        self.delivery_handler = delivery_handler
        self.audit_publisher = audit_publisher
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self.store.initialize()
        if self.store.next_queued() is not None:
            self.notify()

    def enqueue(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        route = self.store.resolve_route(source_session_id, payload)
        source = route["source"]
        target = route["target"]
        item, created = self.store.enqueue(
            source_session_id,
            payload,
            source_generation=self.generation_provider(str(source["sessionId"])),
            target_generation=self.generation_provider(str(target["sessionId"])),
            expected_target_participant_id=str(target["id"]),
        )
        if created:
            self._audit(item, "queued")
        if str(item.get("status") or "") == "queued":
            self.notify()
        return item

    def list(
        self,
        session_id: str,
        *,
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        return self.store.list_for_session(session_id, status=status, limit=limit)

    def notify(self) -> None:
        if self._closed.is_set():
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="rag-ime-room-intercom",
                    daemon=True,
                )
                self._thread.start()
        self._wake.set()

    def close(self) -> None:
        self._closed.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._closed.is_set():
            item = self.store.next_queued()
            if item is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            if not self._generation_matches(item):
                stale = self.store.mark_failed(
                    str(item["id"]),
                    error="participant runtime generation changed before delivery",
                    stale=True,
                    expected="queued",
                )
                self._audit(stale, "stale")
                continue
            target_session_id = str(item["targetSessionId"])
            if not self.idle_probe(target_session_id):
                self._wake.wait(timeout=0.25)
                self._wake.clear()
                continue
            claimed = self.store.claim(str(item["id"]))
            if claimed is None:
                continue
            try:
                accepted = self.delivery_handler(claimed)
            except AgentRoomTargetBusy as exc:
                queued = self.store.requeue(str(claimed["id"]), error=str(exc))
                self._audit(queued, "queued")
                self._wake.wait(timeout=0.25)
                self._wake.clear()
            except Exception as exc:
                failed = self.store.mark_failed(
                    str(claimed["id"]),
                    error=str(exc),
                    expected="delivering",
                )
                self._audit(failed, "failed")
            else:
                delivered = self.store.mark_delivered(
                    str(claimed["id"]),
                    accepted_turn_id=str(accepted.get("turnId") or ""),
                )
                self._audit(delivered, "delivered")

    def _generation_matches(self, item: Mapping[str, object]) -> bool:
        try:
            return (
                self.generation_provider(str(item["sourceSessionId"]))
                == int(item["sourceGeneration"])
                and self.generation_provider(str(item["targetSessionId"]))
                == int(item["targetGeneration"])
            )
        except Exception:
            return False

    def _audit(self, item: Mapping[str, object], phase: str) -> None:
        try:
            self.audit_publisher(item, phase)
        except Exception:
            # The intercom row is the durable audit source; Room events are a projection.
            pass


def _participant_identity(row: sqlite3.Row | None) -> dict[str, str]:
    if row is None:
        raise ValueError("room participant is missing")
    return {
        "id": str(row["id"]),
        "roomId": str(row["room_id"]),
        "sessionId": str(row["session_id"]),
        "displayName": str(row["display_name"]),
    }


def _intercom_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-room-intercom.v1",
        "id": str(row["id"]),
        "roomId": str(row["room_id"]),
        "kind": str(row["kind"]),
        "sourceParticipantId": str(row["source_participant_id"]),
        "targetParticipantId": str(row["target_participant_id"]),
        "sourceSessionId": str(row["source_session_id"]),
        "targetSessionId": str(row["target_session_id"]),
        "sourceGeneration": int(row["source_generation"]),
        "targetGeneration": int(row["target_generation"]),
        "clientMessageId": str(row["client_message_id"]),
        "replyTo": str(row["reply_to_message_id"] or ""),
        "status": str(row["status"]),
        "content": str(row["content"]),
        "acceptedTurnId": str(row["accepted_turn_id"] or ""),
        "error": str(row["error"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "deliveredAtMs": (
            int(row["delivered_at_ms"]) if row["delivered_at_ms"] is not None else None
        ),
        "repliedAtMs": (
            int(row["replied_at_ms"]) if row["replied_at_ms"] is not None else None
        ),
    }
    validate_contract(payload, "agent-room-intercom.v1.json")
    return payload


def _content(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("room intercom content must not be empty")
    if len(text) > 4_000:
        raise ValueError("room intercom content exceeds 4000 characters")
    return text


def _client_message_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 200:
        raise ValueError("room intercom clientMessageId is invalid")
    return text


def _bounded_error(value: object) -> str:
    return " ".join(str(value or "").split())[:500]


def _now_ms() -> int:
    return int(time.time() * 1000)
