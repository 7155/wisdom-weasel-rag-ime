from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


class RoomContextEpochConflict(RuntimeError):
    """A Session context epoch transition is stale or was rebound."""


class RoomSessionContextEpochStore:
    """Own monotonic Provider context epochs across Dispatches and compaction."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def prepare_dispatch(
        self,
        *,
        session_id: str,
        root_id: str,
        generation: int,
        dispatch_id: str,
        now_ms: int,
    ) -> dict[str, object]:
        source_ref = f"dispatch:{_required(dispatch_id, 'dispatch_id')}"
        with self._connect(immediate=True) as conn:
            existing = self._transition(conn, session_id, source_ref)
            if existing is not None:
                return existing
            current = self._current_row(conn, session_id)
            if current is None:
                from_epoch = 0
                to_epoch = 1
                reason = "session_open"
                changed = True
            elif (
                str(current["root_id"]) == root_id
                and int(current["generation"]) == generation
            ):
                from_epoch = int(current["context_epoch"])
                to_epoch = from_epoch
                reason = str(current["epoch_reason"])
                changed = False
            else:
                from_epoch = int(current["context_epoch"])
                to_epoch = from_epoch + 1
                reason = "task_switch"
                changed = True
            transition = self._insert_transition(
                conn,
                session_id=session_id,
                source_ref=source_ref,
                root_id=root_id,
                generation=generation,
                from_epoch=from_epoch,
                to_epoch=to_epoch,
                reason=reason,
                changed=changed,
                evidence={},
                now_ms=now_ms,
            )
            if current is None or changed:
                self._upsert_current(conn, transition, now_ms=now_ms)
            return transition

    def advance_compaction(
        self,
        *,
        session_id: str,
        compaction_entry_id: str,
        expected_epoch: int,
        room_recovery_context: str,
        session_context: str,
        now_ms: int,
    ) -> dict[str, object]:
        source_ref = f"compaction:{_required(compaction_entry_id, 'compaction_entry_id')}"
        evidence = _compaction_evidence(room_recovery_context, session_context)
        with self._connect(immediate=True) as conn:
            existing = self._transition(conn, session_id, source_ref)
            if existing is not None:
                if existing["evidence"] != evidence:
                    raise RoomContextEpochConflict(
                        "compaction epoch identity was reused with different context"
                    )
                return existing
            current = self._current_row(conn, session_id)
            if current is None:
                raise RoomContextEpochConflict(
                    "managed Room compaction has no active context epoch"
                )
            current_epoch = int(current["context_epoch"])
            if int(expected_epoch) != current_epoch:
                raise RoomContextEpochConflict(
                    "managed Room compaction context epoch is stale"
                )
            transition = self._insert_transition(
                conn,
                session_id=session_id,
                source_ref=source_ref,
                root_id=str(current["root_id"]),
                generation=int(current["generation"]),
                from_epoch=current_epoch,
                to_epoch=current_epoch + 1,
                reason="compaction",
                changed=True,
                evidence=evidence,
                now_ms=now_ms,
            )
            self._upsert_current(conn, transition, now_ms=now_ms)
            return transition

    def current(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = self._current_row(conn, session_id)
        return _current_payload(row) if row is not None else None

    def history(self, session_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM room_v2_session_context_epoch_transitions
                   WHERE session_id = ? ORDER BY created_at_ms, transition_id""",
                (_required(session_id, "session_id"),),
            ).fetchall()
        return [_transition_payload(row) for row in rows]

    def _insert_transition(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        source_ref: str,
        root_id: str,
        generation: int,
        from_epoch: int,
        to_epoch: int,
        reason: str,
        changed: bool,
        evidence: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        identity = {
            "sessionId": _required(session_id, "session_id"),
            "sourceRef": source_ref,
            "rootId": _required(root_id, "root_id"),
            "generation": _non_negative(generation, "generation"),
            "fromEpoch": _non_negative(from_epoch, "from_epoch"),
            "toEpoch": _positive(to_epoch, "to_epoch"),
            "epochReason": _required(reason, "reason"),
            "epochChanged": bool(changed),
            "evidence": dict(evidence),
        }
        transition_hash = _sha256_json(identity)
        transition_id = f"context-epoch:{transition_hash[:32]}"
        conn.execute(
            """INSERT INTO room_v2_session_context_epoch_transitions(
                   transition_id,session_id,source_ref,root_id,generation,
                   from_epoch,to_epoch,epoch_reason,epoch_changed,evidence_json,
                   transition_hash,created_at_ms
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                transition_id,
                identity["sessionId"],
                source_ref,
                identity["rootId"],
                identity["generation"],
                identity["fromEpoch"],
                identity["toEpoch"],
                identity["epochReason"],
                1 if changed else 0,
                _json(identity["evidence"]),
                transition_hash,
                _non_negative(now_ms, "now_ms"),
            ),
        )
        row = conn.execute(
            "SELECT * FROM room_v2_session_context_epoch_transitions WHERE transition_id = ?",
            (transition_id,),
        ).fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("context epoch transition did not persist")
        return _transition_payload(row)

    @staticmethod
    def _upsert_current(
        conn: sqlite3.Connection,
        transition: Mapping[str, object],
        *,
        now_ms: int,
    ) -> None:
        conn.execute(
            """INSERT INTO room_v2_session_context_epochs(
                   session_id,context_epoch,root_id,generation,epoch_reason,
                   last_transition_id,created_at_ms,updated_at_ms
               ) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                   context_epoch=excluded.context_epoch,
                   root_id=excluded.root_id,
                   generation=excluded.generation,
                   epoch_reason=excluded.epoch_reason,
                   last_transition_id=excluded.last_transition_id,
                   updated_at_ms=excluded.updated_at_ms""",
            (
                transition["sessionId"],
                transition["toEpoch"],
                transition["rootId"],
                transition["generation"],
                transition["epochReason"],
                transition["transitionId"],
                now_ms,
                now_ms,
            ),
        )

    @staticmethod
    def _current_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM room_v2_session_context_epochs WHERE session_id = ?",
            (_required(session_id, "session_id"),),
        ).fetchone()

    @staticmethod
    def _transition(
        conn: sqlite3.Connection,
        session_id: str,
        source_ref: str,
    ) -> dict[str, object] | None:
        row = conn.execute(
            """SELECT * FROM room_v2_session_context_epoch_transitions
               WHERE session_id = ? AND source_ref = ?""",
            (_required(session_id, "session_id"), source_ref),
        ).fetchone()
        return _transition_payload(row) if row is not None else None

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


def _compaction_evidence(room_context: str, session_context: str) -> dict[str, object]:
    room = str(room_context or "").strip()
    session = str(session_context or "").strip()
    try:
        packet = json.loads(room) if room else {}
    except json.JSONDecodeError as exc:
        raise RoomContextEpochConflict(
            "Room compaction recovery context is not canonical JSON"
        ) from exc
    if not isinstance(packet, Mapping):
        raise RoomContextEpochConflict("Room compaction recovery context must be an object")
    skill = packet.get("skillReceipt") if isinstance(packet.get("skillReceipt"), Mapping) else {}
    tools = packet.get("toolReceipt") if isinstance(packet.get("toolReceipt"), Mapping) else {}
    tool_items = tools.get("items") if isinstance(tools.get("items"), list) else []
    return {
        "roomContextSha256": _sha256(room),
        "roomProviderEntryHash": _sha256(f"room_context\0{room}"),
        "sessionContextSha256": _sha256(session),
        "sessionProviderEntryHash": _sha256(f"session_memory\0{session}"),
        "recoverySchemaVersion": str(packet.get("schemaVersion") or ""),
        "originalRequirementCount": len(packet.get("originalRequirements") or []),
        "currentTaskPresent": bool(packet.get("currentTask")),
        "acceptanceCount": len(packet.get("acceptance") or []),
        "blockerCount": len(packet.get("blockers") or []),
        "handoffPresent": bool(packet.get("handoff")),
        "skillReceiptId": str(skill.get("restoredFromReceiptId") or ""),
        "toolReceiptIds": [
            str(item.get("receiptId") or "")
            for item in tool_items
            if isinstance(item, Mapping) and str(item.get("receiptId") or "").strip()
        ],
    }


def _current_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sessionId": str(row["session_id"]),
        "contextEpoch": int(row["context_epoch"]),
        "rootId": str(row["root_id"]),
        "generation": int(row["generation"]),
        "epochReason": str(row["epoch_reason"]),
        "lastTransitionId": str(row["last_transition_id"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
    }


def _transition_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": "wisdom-weasel.room-context-epoch-transition.v1",
        "transitionId": str(row["transition_id"]),
        "sessionId": str(row["session_id"]),
        "sourceRef": str(row["source_ref"]),
        "rootId": str(row["root_id"]),
        "generation": int(row["generation"]),
        "fromEpoch": int(row["from_epoch"]),
        "toEpoch": int(row["to_epoch"]),
        "epochReason": str(row["epoch_reason"]),
        "epochChanged": bool(row["epoch_changed"]),
        "evidence": json.loads(str(row["evidence_json"])),
        "transitionHash": str(row["transition_hash"]),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return _sha256(_json(value))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive(value: object, name: str) -> int:
    result = _non_negative(value, name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result
