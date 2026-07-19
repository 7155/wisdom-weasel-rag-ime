from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


_CONTEXT_ENTRY_KINDS = frozenset(
    {
        "room_post",
        "root_state",
        "task_state",
        "dispatch_state",
        "room_commit",
        "control_receipt",
        "evidence_receipt",
        "requirement_anchor",
        "skill_receipt",
        "knowledge_receipt",
        "recovery_packet",
    }
)


class RoomContextConflict(RuntimeError):
    """An immutable Room context or projection identity changed content."""


class ProjectionGenerationMismatch(RuntimeError):
    """A projection operation belongs to a stale Root cancel generation."""


class RoomContextLedgerStore:
    """Durable public Room facts; private Session output never enters implicitly."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def publish_post(
        self,
        post: Mapping[str, object],
    ) -> tuple[dict[str, object], bool]:
        normalized = dict(post)
        source = normalized.get("publicationSource")
        source = dict(source) if isinstance(source, Mapping) else {}
        source_kind = str(source.get("kind") or "").strip()
        source_ref = str(source.get("ref") or "").strip()
        if source_kind not in {"user", "room_commit"}:
            raise ValueError("Room Post requires explicit user or room_commit publication")
        if source_kind == "room_commit" and not source_ref:
            raise ValueError("Room Post from room_commit requires a commit ref")
        validate_contract(normalized, "room-post.v2.json")
        content = _content(normalized.get("content"))
        content_bytes = content.encode("utf-8")
        content_hash = _sha256(content_bytes)
        encoded_post = _canonical_json(normalized)
        post_hash = _sha256(encoded_post.encode("utf-8"))
        post_id = _required_text(normalized.get("postId"), "postId")
        root_id = _required_text(normalized.get("rootId"), "rootId")
        room_id = _required_text(normalized.get("roomId"), "roomId")
        generation = _non_negative_int(normalized.get("generation"), "generation")
        idempotency_key = _required_text(
            normalized.get("idempotencyKey"),
            "idempotencyKey",
        )
        created_at_ms = _non_negative_int(normalized.get("createdAtMs"), "createdAtMs")

        with self._connect(immediate=True) as conn:
            existing_rows = conn.execute(
                """
                SELECT * FROM room_v2_posts
                WHERE post_id = ? OR (root_id = ? AND idempotency_key = ?)
                """,
                (post_id, root_id, idempotency_key),
            ).fetchall()
            if len(existing_rows) > 1:
                raise RoomContextConflict(
                    "Room Post identifiers resolve to different immutable records"
                )
            existing = existing_rows[0] if existing_rows else None
            if existing is not None:
                if str(existing["post_hash"]) != post_hash:
                    raise RoomContextConflict(
                        "Room Post identity was reused with different immutable content"
                    )
                return self._post_payload(conn, existing), False

            entry, _created = self._append_entry_conn(
                conn,
                root_id=root_id,
                room_id=room_id,
                generation=generation,
                entry_kind="room_post",
                source_ref=post_id,
                dedupe_key=f"room-post:{post_id}",
                content=content,
                created_at_ms=created_at_ms,
            )
            conn.execute(
                """
                INSERT INTO room_v2_posts(
                    post_id, room_id, root_id, generation, task_id, dispatch_id,
                    author_actor_ref, post_kind, visibility, idempotency_key,
                    publication_source_kind, publication_source_ref, content_hash,
                    post_hash, content_bytes, payload_json, context_entry_id, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    room_id,
                    root_id,
                    generation,
                    str(normalized.get("taskId") or "").strip(),
                    str(normalized.get("dispatchId") or "").strip(),
                    _required_text(normalized.get("authorActorRef"), "authorActorRef"),
                    _required_text(normalized.get("kind"), "kind"),
                    _required_text(normalized.get("visibility"), "visibility"),
                    idempotency_key,
                    source_kind,
                    source_ref,
                    content_hash,
                    post_hash,
                    content_bytes,
                    encoded_post,
                    str(entry["entryId"]),
                    created_at_ms,
                ),
            )
            row = conn.execute(
                "SELECT * FROM room_v2_posts WHERE post_id = ?",
                (post_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - protected by the transaction
                raise RuntimeError("Room Post write did not persist")
            return self._post_payload(conn, row), True

    def append_entry(
        self,
        *,
        root_id: str,
        room_id: str,
        generation: int,
        entry_kind: str,
        source_ref: str,
        dedupe_key: str,
        content: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        with self._connect(immediate=True) as conn:
            return self._append_entry_conn(
                conn,
                root_id=root_id,
                room_id=room_id,
                generation=generation,
                entry_kind=entry_kind,
                source_ref=source_ref,
                dedupe_key=dedupe_key,
                content=content,
                created_at_ms=created_at_ms,
            )

    def replay_root(self, root_id: str) -> list[dict[str, object]]:
        root_id = _required_text(root_id, "rootId")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_v2_context_entries
                WHERE root_id = ? ORDER BY sequence
                """,
                (root_id,),
            ).fetchall()
        return [_context_entry_payload(row) for row in rows]

    def _append_entry_conn(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        room_id: str,
        generation: int,
        entry_kind: str,
        source_ref: str,
        dedupe_key: str,
        content: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        root_id = _required_text(root_id, "rootId")
        room_id = _required_text(room_id, "roomId")
        generation = _non_negative_int(generation, "generation")
        entry_kind = _required_text(entry_kind, "entryKind")
        if entry_kind not in _CONTEXT_ENTRY_KINDS:
            raise ValueError("unsupported Room context entry kind")
        source_ref = _required_text(source_ref, "sourceRef")
        dedupe_key = _required_text(dedupe_key, "dedupeKey")
        content = _content(content)
        created_at_ms = _non_negative_int(created_at_ms, "createdAtMs")
        content_bytes = content.encode("utf-8")
        content_hash = _sha256(content_bytes)
        identity = {
            "rootId": root_id,
            "roomId": room_id,
            "generation": generation,
            "entryKind": entry_kind,
            "sourceRef": source_ref,
            "dedupeKey": dedupe_key,
            "contentHash": content_hash,
            "createdAtMs": created_at_ms,
        }
        entry_hash = _sha256(_canonical_json(identity).encode("utf-8"))
        entry_id = f"room-context:{_sha256(f'{root_id}:{dedupe_key}'.encode())[:32]}"
        existing = conn.execute(
            """
            SELECT * FROM room_v2_context_entries
            WHERE root_id = ? AND dedupe_key = ?
            """,
            (root_id, dedupe_key),
        ).fetchone()
        if existing is not None:
            if str(existing["entry_hash"]) != entry_hash:
                raise RoomContextConflict(
                    "Room context identity was reused with different immutable content"
                )
            return _context_entry_payload(existing), False
        sequence = int(
            conn.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM room_v2_context_entries WHERE root_id = ?
                """,
                (root_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO room_v2_context_entries(
                entry_id, root_id, room_id, generation, sequence, entry_kind,
                source_ref, dedupe_key, content_hash, entry_hash,
                content_bytes, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                root_id,
                room_id,
                generation,
                sequence,
                entry_kind,
                source_ref,
                dedupe_key,
                content_hash,
                entry_hash,
                content_bytes,
                created_at_ms,
            ),
        )
        row = conn.execute(
            "SELECT * FROM room_v2_context_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("Room context entry write did not persist")
        return _context_entry_payload(row), True

    @staticmethod
    def _post_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
        entry = conn.execute(
            "SELECT * FROM room_v2_context_entries WHERE entry_id = ?",
            (str(row["context_entry_id"]),),
        ).fetchone()
        if entry is None:  # pragma: no cover - foreign key protected
            raise RuntimeError("Room Post context entry is missing")
        payload = json.loads(str(row["payload_json"]))
        return {
            **payload,
            "contentHash": str(row["content_hash"]),
            "contextEntry": _context_entry_payload(entry),
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


class ProviderProjectionJournalStore:
    """Append-only provider projection; reads never consume pending entries."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def open_journal(
        self,
        *,
        journal_id: str,
        root_id: str,
        room_id: str,
        binding_id: str,
        session_id: str,
        session_epoch: int,
        context_epoch: int,
        generation: int,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        identity = {
            "journalId": _required_text(journal_id, "journalId"),
            "rootId": _required_text(root_id, "rootId"),
            "roomId": _required_text(room_id, "roomId"),
            "bindingId": _required_text(binding_id, "bindingId"),
            "sessionId": _required_text(session_id, "sessionId"),
            "sessionEpoch": _positive_int(session_epoch, "sessionEpoch"),
            "contextEpoch": _positive_int(context_epoch, "contextEpoch"),
            "generation": _non_negative_int(generation, "generation"),
        }
        created_at_ms = _non_negative_int(created_at_ms, "createdAtMs")
        identity_hash = _sha256(_canonical_json(identity).encode("utf-8"))
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_provider_projection_journals WHERE journal_id = ?",
                (identity["journalId"],),
            ).fetchone()
            if row is not None:
                if str(row["identity_hash"]) != identity_hash:
                    raise RoomContextConflict(
                        "provider projection journal identity changed after creation"
                    )
                return _journal_payload(row), False
            conn.execute(
                """
                INSERT INTO room_v2_provider_projection_journals(
                    journal_id, root_id, room_id, binding_id, session_id,
                    session_epoch, context_epoch, generation, identity_hash,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity["journalId"],
                    identity["rootId"],
                    identity["roomId"],
                    identity["bindingId"],
                    identity["sessionId"],
                    identity["sessionEpoch"],
                    identity["contextEpoch"],
                    identity["generation"],
                    identity_hash,
                    created_at_ms,
                    created_at_ms,
                ),
            )
            row = self._journal_row(conn, str(identity["journalId"]))
        return _journal_payload(row), True

    def append_entry(
        self,
        journal_id: str,
        context_entry_id: str,
        *,
        dedupe_key: str,
        expected_generation: int,
        appended_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        journal_id = _required_text(journal_id, "journalId")
        context_entry_id = _required_text(context_entry_id, "contextEntryId")
        dedupe_key = _required_text(dedupe_key, "dedupeKey")
        appended_at_ms = _non_negative_int(appended_at_ms, "appendedAtMs")
        with self._connect(immediate=True) as conn:
            journal = self._journal_row(conn, journal_id)
            self._check_generation(journal, expected_generation)
            entry = conn.execute(
                "SELECT * FROM room_v2_context_entries WHERE entry_id = ?",
                (context_entry_id,),
            ).fetchone()
            if entry is None:
                raise KeyError(context_entry_id)
            if str(entry["root_id"]) != str(journal["root_id"]):
                raise RoomContextConflict("context entry belongs to another Root")
            if int(entry["generation"]) != int(journal["generation"]):
                raise ProjectionGenerationMismatch(
                    "context entry belongs to another Root generation"
                )
            existing_rows = conn.execute(
                """
                SELECT * FROM room_v2_provider_projection_items
                WHERE journal_id = ? AND (dedupe_key = ? OR context_entry_id = ?)
                """,
                (journal_id, dedupe_key, context_entry_id),
            ).fetchall()
            if len(existing_rows) > 1:
                raise RoomContextConflict(
                    "projection identifiers resolve to different immutable items"
                )
            existing = existing_rows[0] if existing_rows else None
            if existing is not None:
                if (
                    str(existing["dedupe_key"]) != dedupe_key
                    or str(existing["context_entry_id"]) != context_entry_id
                    or str(existing["content_hash"]) != str(entry["content_hash"])
                ):
                    raise RoomContextConflict(
                        "provider projection item identity was reused with different content"
                    )
                return _projection_item_payload(existing, entry), False
            sequence = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1
                    FROM room_v2_provider_projection_items WHERE journal_id = ?
                    """,
                    (journal_id,),
                ).fetchone()[0]
            )
            conn.execute(
                """
                INSERT INTO room_v2_provider_projection_items(
                    journal_id, sequence, context_entry_id, dedupe_key,
                    content_hash, state, appended_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    journal_id,
                    sequence,
                    context_entry_id,
                    dedupe_key,
                    str(entry["content_hash"]),
                    appended_at_ms,
                ),
            )
            conn.execute(
                """
                UPDATE room_v2_provider_projection_journals
                SET revision = revision + 1, updated_at_ms = ? WHERE journal_id = ?
                """,
                (appended_at_ms, journal_id),
            )
            item = conn.execute(
                """
                SELECT * FROM room_v2_provider_projection_items
                WHERE journal_id = ? AND sequence = ?
                """,
                (journal_id, sequence),
            ).fetchone()
        if item is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("provider projection item write did not persist")
        return _projection_item_payload(item, entry), True

    def projection(
        self,
        journal_id: str,
        *,
        expected_generation: int,
        through_sequence: int | None = None,
    ) -> dict[str, object]:
        journal_id = _required_text(journal_id, "journalId")
        with self._connect() as conn:
            journal = self._journal_row(conn, journal_id)
            self._check_generation(journal, expected_generation)
            maximum = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0)
                    FROM room_v2_provider_projection_items WHERE journal_id = ?
                    """,
                    (journal_id,),
                ).fetchone()[0]
            )
            through = maximum if through_sequence is None else int(through_sequence)
            if through < 0 or through > maximum:
                raise ValueError("projection throughSequence is outside the journal")
            rows = conn.execute(
                """
                SELECT item.*, entry.*
                FROM room_v2_provider_projection_items AS item
                JOIN room_v2_context_entries AS entry
                  ON entry.entry_id = item.context_entry_id
                WHERE item.journal_id = ? AND item.sequence <= ?
                ORDER BY item.sequence
                """,
                (journal_id, through),
            ).fetchall()
        items = [_joined_projection_item_payload(row) for row in rows]
        framed = _framed_projection_bytes(rows)
        projection_bytes = b"".join(bytes(row["content_bytes"]) for row in rows)
        sealed = [item for item in items if item["state"] == "sealed"]
        pending = [item for item in items if item["state"] == "pending"]
        return {
            "schemaVersion": "wisdom-weasel.provider-projection.v1",
            "journalId": journal_id,
            "generation": int(journal["generation"]),
            "sealedThroughSequence": int(journal["sealed_through_sequence"]),
            "throughSequence": through,
            "sealedPrefix": sealed,
            "pendingTail": pending,
            "projectionBytes": projection_bytes,
            "projectionHash": _sha256(framed),
        }

    def record_provider_receipt(
        self,
        journal_id: str,
        *,
        receipt_id: str,
        provider_request_id: str,
        through_sequence: int,
        projection_hash: str,
        expected_generation: int,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        journal_id = _required_text(journal_id, "journalId")
        receipt_id = _required_text(receipt_id, "receiptId")
        provider_request_id = _required_text(provider_request_id, "providerRequestId")
        through_sequence = _positive_int(through_sequence, "throughSequence")
        projection_hash = _required_hash(projection_hash, "projectionHash")
        created_at_ms = _non_negative_int(created_at_ms, "createdAtMs")
        with self._connect(immediate=True) as conn:
            journal = self._journal_row(conn, journal_id)
            self._check_generation(journal, expected_generation)
            existing_rows = conn.execute(
                """
                SELECT * FROM room_v2_provider_projection_receipts
                WHERE receipt_id = ? OR (journal_id = ? AND provider_request_id = ?)
                """,
                (receipt_id, journal_id, provider_request_id),
            ).fetchall()
            if len(existing_rows) > 1:
                raise RoomContextConflict(
                    "provider receipt identifiers resolve to different immutable receipts"
                )
            existing = existing_rows[0] if existing_rows else None
            if existing is not None:
                if (
                    str(existing["receipt_id"]) != receipt_id
                    or str(existing["provider_request_id"]) != provider_request_id
                    or int(existing["sealed_through_sequence"]) != through_sequence
                    or str(existing["projection_hash"]) != projection_hash
                    or int(existing["generation"]) != int(journal["generation"])
                ):
                    raise RoomContextConflict(
                        "provider receipt identity was reused with different content"
                    )
                return _provider_receipt_payload(existing), False
            if through_sequence <= int(journal["sealed_through_sequence"]):
                raise RoomContextConflict("provider receipt does not advance sealed prefix")
            rows = conn.execute(
                """
                SELECT item.sequence, entry.content_bytes
                FROM room_v2_provider_projection_items AS item
                JOIN room_v2_context_entries AS entry
                  ON entry.entry_id = item.context_entry_id
                WHERE item.journal_id = ? AND item.sequence <= ?
                ORDER BY item.sequence
                """,
                (journal_id, through_sequence),
            ).fetchall()
            if len(rows) != through_sequence:
                raise RoomContextConflict("provider receipt projection prefix has a gap")
            if _sha256(_framed_projection_bytes(rows)) != projection_hash:
                raise RoomContextConflict("provider receipt projection hash does not match")
            conn.execute(
                """
                INSERT INTO room_v2_provider_projection_receipts(
                    receipt_id, journal_id, provider_request_id, generation,
                    sealed_through_sequence, projection_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    journal_id,
                    provider_request_id,
                    int(journal["generation"]),
                    through_sequence,
                    projection_hash,
                    created_at_ms,
                ),
            )
            conn.execute(
                """
                UPDATE room_v2_provider_projection_items
                SET state = 'sealed', sealed_by_receipt_id = ?
                WHERE journal_id = ? AND sequence <= ? AND state = 'pending'
                """,
                (receipt_id, journal_id, through_sequence),
            )
            conn.execute(
                """
                UPDATE room_v2_provider_projection_journals
                SET sealed_through_sequence = ?, revision = revision + 1,
                    updated_at_ms = ? WHERE journal_id = ?
                """,
                (through_sequence, created_at_ms, journal_id),
            )
            row = conn.execute(
                """
                SELECT * FROM room_v2_provider_projection_receipts
                WHERE receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - protected by transaction
            raise RuntimeError("provider projection receipt did not persist")
        return _provider_receipt_payload(row), True

    @staticmethod
    def _journal_row(conn: sqlite3.Connection, journal_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM room_v2_provider_projection_journals WHERE journal_id = ?",
            (journal_id,),
        ).fetchone()
        if row is None:
            raise KeyError(journal_id)
        return row

    @staticmethod
    def _check_generation(row: sqlite3.Row, expected_generation: int) -> None:
        expected = _non_negative_int(expected_generation, "expectedGeneration")
        if int(row["generation"]) != expected:
            raise ProjectionGenerationMismatch(
                "provider projection belongs to another Root generation"
            )

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


def _context_entry_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = {
        "schemaVersion": "wisdom-weasel.room-context-entry.v1",
        "entryId": str(row["entry_id"]),
        "rootId": str(row["root_id"]),
        "roomId": str(row["room_id"]),
        "generation": int(row["generation"]),
        "sequence": int(row["sequence"]),
        "entryKind": str(row["entry_kind"]),
        "sourceRef": str(row["source_ref"]),
        "contentHash": str(row["content_hash"]),
        "content": bytes(row["content_bytes"]).decode("utf-8"),
        "createdAtMs": int(row["created_at_ms"]),
    }
    validate_contract(payload, "room-context-entry.v1.json")
    return payload


def _journal_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = {
        "schemaVersion": "wisdom-weasel.provider-projection-journal.v1",
        "journalId": str(row["journal_id"]),
        "rootId": str(row["root_id"]),
        "roomId": str(row["room_id"]),
        "bindingId": str(row["binding_id"]),
        "sessionId": str(row["session_id"]),
        "sessionEpoch": int(row["session_epoch"]),
        "contextEpoch": int(row["context_epoch"]),
        "generation": int(row["generation"]),
        "sealedThroughSequence": int(row["sealed_through_sequence"]),
        "revision": int(row["revision"]),
    }
    validate_contract(payload, "provider-projection-journal.v1.json")
    return payload


def _projection_item_payload(item: sqlite3.Row, entry: sqlite3.Row) -> dict[str, object]:
    return {
        "sequence": int(item["sequence"]),
        "contextEntryId": str(item["context_entry_id"]),
        "contentHash": str(item["content_hash"]),
        "content": bytes(entry["content_bytes"]).decode("utf-8"),
        "state": str(item["state"]),
    }


def _joined_projection_item_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sequence": int(row["sequence"]),
        "contextEntryId": str(row["context_entry_id"]),
        "contentHash": str(row["content_hash"]),
        "content": bytes(row["content_bytes"]).decode("utf-8"),
        "state": str(row["state"]),
    }


def _provider_receipt_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = {
        "schemaVersion": "wisdom-weasel.provider-projection-receipt.v1",
        "receiptId": str(row["receipt_id"]),
        "journalId": str(row["journal_id"]),
        "providerRequestId": str(row["provider_request_id"]),
        "generation": int(row["generation"]),
        "sealedThroughSequence": int(row["sealed_through_sequence"]),
        "projectionHash": str(row["projection_hash"]),
        "createdAtMs": int(row["created_at_ms"]),
    }
    validate_contract(payload, "provider-projection-receipt.v1.json")
    return payload


def _framed_projection_bytes(rows: list[sqlite3.Row]) -> bytes:
    framed = bytearray()
    for row in rows:
        content = bytes(row["content_bytes"])
        framed.extend(len(content).to_bytes(8, byteorder="big", signed=False))
        framed.extend(content)
    return bytes(framed)


def _content(value: object) -> str:
    content = str(value if value is not None else "")
    if not content.strip():
        raise ValueError("Room context content must not be empty")
    return content


def _required_text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _non_negative_int(value: object, field: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _positive_int(value: object, field: str) -> int:
    normalized = _non_negative_int(value, field)
    if normalized < 1:
        raise ValueError(f"{field} must be positive")
    return normalized


def _required_hash(value: object, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a sha256 hex digest")
    return normalized


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Room context value must be JSON serializable") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
