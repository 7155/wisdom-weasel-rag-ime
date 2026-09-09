from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from rag_ime.db import apply_database_migrations


class AgentRoomStartGateStore:
    """Durable, Room-scoped confirmation fence for the first executable task."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def get(self, room_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                (str(room_id),),
            ).fetchone()
        return _payload(row) if row is not None else None

    def confirmed_room_ids(self) -> list[str]:
        """Return durable Room ids whose one-time start gate was confirmed.

        The Room execution overlay lives on participant Sessions, so a Host
        restart must be able to restore it from the Room-owned confirmation
        authority instead of asking for every Tool action again.
        """

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT room_id
                FROM agent_room_start_gates
                WHERE status = 'confirmed'
                ORDER BY confirmed_at_ms ASC, room_id ASC
                """
            ).fetchall()
        return [str(row["room_id"]) for row in rows]

    def retire_pending(self) -> int:
        """Delete every obsolete Room start prompt in one durable operation.

        Room dispatch is now the user authorization boundary.  This storage-
        level cleanup deliberately has no Room list/page dependency: an older
        installation may have left more pending rows than one directory page
        can project during Host startup.
        """

        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "DELETE FROM agent_room_start_gates WHERE status = 'pending'"
            )
            return max(0, int(cursor.rowcount))

    def claim(
        self,
        *,
        room_id: str,
        objective_text: str,
        client_message_id: str,
        target_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str] = (),
        retry_of_root_id: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        room_id = str(room_id).strip()
        objective = str(objective_text).strip()
        client_id = str(client_message_id).strip()
        targets = _ids(target_participant_ids)
        attachments = _ids(attachment_ids)
        work_id = str(work_item_id).strip()
        retry_root_id = str(retry_of_root_id).strip()
        if not room_id or not objective or not client_id or not work_id:
            raise ValueError("Room start gate requires room, objective, client and WorkItem")
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        digest = _sha256_json(
            {
                "objective": objective,
                "clientMessageId": client_id,
                "targetParticipantIds": targets,
                "workItemId": work_id,
                "attachmentIds": attachments,
                "retryOfRootId": retry_root_id,
            }
        )
        with self._connect(immediate=True) as conn:
            existing = False
            row = conn.execute(
                "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_room_start_gates(
                        room_id, status, objective_text, objective_sha256,
                        target_participant_ids_json, work_item_id, root_id,
                        confirmation_text, client_message_id, created_at_ms,
                        updated_at_ms, confirmed_at_ms, attachment_ids_json,
                        retry_of_root_id
                    ) VALUES (?, 'pending', ?, ?, ?, ?, '', '', ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        room_id,
                        objective,
                        digest,
                        json.dumps(targets, ensure_ascii=False, separators=(",", ":")),
                        work_id,
                        client_id,
                        timestamp,
                        timestamp,
                        json.dumps(attachments, ensure_ascii=False, separators=(",", ":")),
                        retry_root_id,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
            else:
                existing = True
                if str(row["objective_sha256"] or "") != digest:
                    raise ValueError("Room already has a different start confirmation draft")
            if row is None:  # pragma: no cover - defensive sqlite invariant
                raise RuntimeError("Room start gate insert was not readable")
            return _payload(row, idempotent_replay=existing)

    def confirm(self, room_id: str, *, now_ms: int | None = None) -> dict[str, object]:
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                (str(room_id),),
            ).fetchone()
            if row is None:
                raise KeyError(room_id)
            if str(row["status"]) == "pending":
                conn.execute(
                    "UPDATE agent_room_start_gates SET status = 'confirmed', confirmed_at_ms = ?, updated_at_ms = ? WHERE room_id = ?",
                    (timestamp, timestamp, str(room_id)),
                )
            row = conn.execute(
                "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                (str(room_id),),
            ).fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("Room start gate disappeared during confirmation")
        return _payload(row)

    def reject(self, room_id: str) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM agent_room_start_gates WHERE room_id = ?",
                (str(room_id),),
            ).fetchone()
            if row is None:
                raise KeyError(room_id)
            payload = _payload(row)
            conn.execute(
                "DELETE FROM agent_room_start_gates WHERE room_id = ? AND status = 'pending'",
                (str(room_id),),
            )
        return payload

    def complete(
        self,
        room_id: str,
        *,
        root_id: str,
        response: Mapping[str, object],
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._connect(immediate=True) as conn:
            conn.execute(
                "UPDATE agent_room_start_gates SET root_id = ?, confirmation_text = ?, updated_at_ms = ? WHERE room_id = ? AND status = 'confirmed'",
                (
                    str(root_id),
                    json.dumps(dict(response), ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    str(room_id),
                ),
            )
        result = self.get(room_id)
        if result is None:  # pragma: no cover
            raise KeyError(room_id)
        return result

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            with conn:
                yield conn
        finally:
            conn.close()


def _payload(row: sqlite3.Row, *, idempotent_replay: bool = False) -> dict[str, object]:
    try:
        targets = json.loads(str(row["target_participant_ids_json"] or "[]"))
    except json.JSONDecodeError:
        targets = []
    try:
        attachments = json.loads(str(row["attachment_ids_json"] or "[]"))
    except json.JSONDecodeError:
        attachments = []
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-room-start-gate.v1",
        "ok": True,
        "gateId": f"room-start:{row['room_id']}",
        "roomId": str(row["room_id"]),
        "status": str(row["status"]),
        "objective": str(row["objective_text"]),
        "workItemId": str(row["work_item_id"]),
        "targetParticipantIds": [str(value) for value in targets if str(value).strip()],
        "attachmentIds": [str(value) for value in attachments if str(value).strip()],
        "retryOfRootId": str(row["retry_of_root_id"] or ""),
        "clientMessageId": str(row["client_message_id"] or ""),
        "rootId": str(row["root_id"] or ""),
        "confirmedAtMs": int(row["confirmed_at_ms"] or 0),
        "idempotentReplay": idempotent_replay,
    }
    if row["confirmation_text"]:
        try:
            payload["response"] = json.loads(str(row["confirmation_text"]))
        except json.JSONDecodeError:
            pass
    return payload


def _ids(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
