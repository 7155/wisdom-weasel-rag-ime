from __future__ import annotations

import json
import sqlite3
from typing import Mapping

from .text_utils import compact_whitespace, now_ms


MEMORY_BOOK_LIFECYCLE_SCHEMA_VERSION = "rag-ime.memory-book-lifecycle.v1"


def archive_inactive_memory_books(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    inactive_days: int = 60,
    current_ms: int | None = None,
    dry_run: bool = True,
    limit: int = 200,
) -> dict[str, object]:
    timestamp = now_ms() if current_ms is None else max(0, int(current_ms))
    days = max(7, min(3650, int(inactive_days)))
    cutoff_ms = timestamp - days * 86_400_000
    rows = conn.execute(
        """
        SELECT book_id, title, summary, book_key, project, status,
               updated_at_ms, last_active_at_ms, metadata_json
        FROM memory_books
        WHERE book_type = 'topic'
          AND status IN ('active', 'approved')
          AND COALESCE(last_active_at_ms, updated_at_ms, created_at_ms) < ?
          AND (? = '' OR project = ? OR project = '')
        ORDER BY COALESCE(last_active_at_ms, updated_at_ms, created_at_ms) ASC
        LIMIT ?
        """,
        (cutoff_ms, compact_whitespace(project), compact_whitespace(project), max(1, int(limit))),
    ).fetchall()
    candidates = [
        {
            "bookId": str(row["book_id"]),
            "title": str(row["title"] or ""),
            "summary": str(row["summary"] or ""),
            "bookKey": str(row["book_key"] or ""),
            "project": str(row["project"] or ""),
            "status": str(row["status"] or "active"),
            "lastActiveAtMs": int(row["last_active_at_ms"] or row["updated_at_ms"] or 0),
            "pinned": bool(_json_object(row["metadata_json"]).get("pinned")),
        }
        for row in rows
        if not bool(_json_object(row["metadata_json"]).get("pinned"))
    ]
    archived_ids: list[str] = []
    if not dry_run:
        reason = f"inactive_for_{days}_days"
        for item in candidates:
            book_id = str(item["bookId"])
            _set_archive_state(
                conn,
                book_id=book_id,
                archived=True,
                timestamp=timestamp,
                reason=reason,
                actor="memory_book_lifecycle",
            )
            archived_ids.append(book_id)
    return {
        "schemaVersion": MEMORY_BOOK_LIFECYCLE_SCHEMA_VERSION,
        "ok": True,
        "dryRun": bool(dry_run),
        "inactiveDays": days,
        "cutoffMs": cutoff_ms,
        "candidateCount": len(candidates),
        "archivedCount": len(archived_ids),
        "archivedBookIds": archived_ids,
        "items": candidates,
    }


def set_memory_book_archive_status(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    archived: bool,
    reason: str = "",
    actor: str = "native-control-center",
    current_ms: int | None = None,
) -> dict[str, object]:
    resolved_id = compact_whitespace(book_id)
    if not resolved_id:
        raise ValueError("bookId is required")
    row = conn.execute(
        "SELECT book_id, book_type, title, status FROM memory_books WHERE book_id = ?",
        (resolved_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"memory book not found: {resolved_id}")
    if str(row["book_type"] or "") != "topic" and archived:
        raise ValueError("only topic books can be archived manually")
    timestamp = now_ms() if current_ms is None else max(0, int(current_ms))
    _set_archive_state(
        conn,
        book_id=resolved_id,
        archived=archived,
        timestamp=timestamp,
        reason=compact_whitespace(reason) or ("user_archive" if archived else "user_restore"),
        actor=compact_whitespace(actor) or "local",
    )
    updated = conn.execute(
        """
        SELECT book_id, book_type, book_key, title, summary, status,
               archived_at_ms, last_active_at_ms, archive_reason, updated_at_ms
        FROM memory_books WHERE book_id = ?
        """,
        (resolved_id,),
    ).fetchone()
    return {
        "schemaVersion": MEMORY_BOOK_LIFECYCLE_SCHEMA_VERSION,
        "ok": True,
        "book": {
            "id": str(updated["book_id"]),
            "type": str(updated["book_type"] or ""),
            "bookKey": str(updated["book_key"] or ""),
            "title": str(updated["title"] or ""),
            "summary": str(updated["summary"] or ""),
            "status": str(updated["status"] or ""),
            "archivedAtMs": int(updated["archived_at_ms"] or 0),
            "lastActiveAtMs": int(updated["last_active_at_ms"] or 0),
            "archiveReason": str(updated["archive_reason"] or ""),
            "updatedAtMs": int(updated["updated_at_ms"] or 0),
        },
    }


def _set_archive_state(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    archived: bool,
    timestamp: int,
    reason: str,
    actor: str,
) -> None:
    row = conn.execute(
        "SELECT metadata_json FROM memory_books WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"memory book not found: {book_id}")
    metadata = _json_object(row["metadata_json"])
    lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), list) else []
    lifecycle = [*lifecycle[-19:], {
        "action": "archive" if archived else "restore",
        "atMs": timestamp,
        "reason": reason,
        "actor": actor,
    }]
    metadata["lifecycle"] = lifecycle
    if archived:
        conn.execute(
            """
            UPDATE memory_books
            SET status = 'archived', archived_at_ms = ?, archive_reason = ?,
                updated_at_ms = ?, metadata_json = ?
            WHERE book_id = ?
            """,
            (timestamp, reason, timestamp, json.dumps(metadata, ensure_ascii=False, sort_keys=True), book_id),
        )
    else:
        conn.execute(
            """
            UPDATE memory_books
            SET status = 'active', archived_at_ms = NULL, archive_reason = '',
                last_active_at_ms = ?, updated_at_ms = ?, metadata_json = ?
            WHERE book_id = ?
            """,
            (timestamp, timestamp, json.dumps(metadata, ensure_ascii=False, sort_keys=True), book_id),
        )


def _json_object(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}
