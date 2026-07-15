from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Callable, ContextManager, Mapping

from .memory_ingest import looks_sensitive, normalize_text
from .memory_schema_v2 import ensure_memory_v2_schema
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import build_fts_document, compact_whitespace, now_ms


MEMORY_ACTION_SCHEMA_VERSION = "rag-ime.memory-action-mutation.v1"
_SUPPORTED_ACTIONS = {
    "pin",
    "enable",
    "disable",
    "suppress",
    "tombstone",
    "forget",
    "update_phrase",
    "rebuild_retrieval_doc",
}
_ITEM_TYPE_HINTS = {"", "item", "memory", "phrase", "lexicon", "memory_item"}
_ATOM_TYPE_HINTS = {"atom", "memory_atom"}
_BOOK_TYPE_HINTS = {"book", "memory_book"}

ConnectionFactory = Callable[[], ContextManager[sqlite3.Connection]]
CacheInvalidator = Callable[[], object]
EventPublisher = Callable[[str, Mapping[str, object]], object]


@dataclass(frozen=True)
class _Target:
    target_type: str
    table: str
    id_column: str
    row_id: int | str
    memory_id: str
    kind: str
    text: str
    project: str
    app: str
    status: str
    privacy_class: str
    confidence: float
    quality_score: float
    metadata: dict[str, object]


def execute_memory_action(
    *,
    connection_factory: ConnectionFactory,
    payload: Mapping[str, object],
    cache_invalidator: CacheInvalidator | None = None,
    event_publisher: EventPublisher | None = None,
) -> dict[str, object]:
    """Apply a durable memory mutation, then notify process-local consumers.

    The database transaction is committed by ``connection_factory`` before
    cache invalidation and event publication run. Observer failures are
    reported without rolling back an already durable mutation.
    """

    with connection_factory() as conn:
        result = mutate_memory_action(conn, payload)

    cache_status = _notify_cache(cache_invalidator)
    event_payload = dict(_mapping(result.get("event")).get("payload") or {})
    event_status = _publish_event(event_publisher, event_payload)
    return {
        **result,
        "cacheInvalidation": {
            **_mapping(result.get("cacheInvalidation")),
            **cache_status,
        },
        "event": {
            **_mapping(result.get("event")),
            **event_status,
        },
    }


def mutate_memory_action(
    conn: sqlite3.Connection,
    payload: Mapping[str, object],
    *,
    changed_at_ms: int | None = None,
) -> dict[str, object]:
    """Mutate one real memory record and rebuild its retrieval projection."""

    ensure_memory_v2_schema(conn)
    memory_id = compact_whitespace(
        str(payload.get("memoryId") or payload.get("itemId") or payload.get("id") or "")
    )
    action = compact_whitespace(str(payload.get("action") or payload.get("actionType") or "")).lower().replace("-", "_")
    item_type = compact_whitespace(str(payload.get("itemType") or payload.get("type") or "")).lower()
    if not memory_id:
        raise ValueError("memoryId is required")
    if action not in _SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported memory action: {action}")

    target = _resolve_target(conn, memory_id=memory_id, item_type=item_type)
    if target.privacy_class == "sensitive" and action in {"pin", "enable", "update_phrase"}:
        raise ValueError("sensitive memory cannot be activated or promoted")
    timestamp = int(changed_at_ms if changed_at_ms is not None else now_ms())
    reason = _safe_reason(payload.get("reason"), fallback=f"management_{action}")
    actor = _safe_actor(payload.get("updatedBy") or payload.get("actor"))
    changes: dict[str, object] = {}
    fts_rebuilt = False
    vectors_invalidated = 0

    if action == "pin":
        changes = _pin_target(conn, target=target, changed_at_ms=timestamp, reason=reason, actor=actor)
    elif action == "enable":
        changes = _enable_target(conn, target=target, changed_at_ms=timestamp)
    elif action == "disable":
        changes = _set_target_status(conn, target=target, status="disabled", changed_at_ms=timestamp)
    elif action == "suppress":
        changes = _suppress_target(conn, target=target, changed_at_ms=timestamp, reason=reason)
    elif action in {"tombstone", "forget"}:
        changes = _tombstone_target(conn, target=target, changed_at_ms=timestamp, reason=reason)
    elif action == "update_phrase":
        phrase = compact_whitespace(
            str(payload.get("newPhrase") or payload.get("phrase") or payload.get("text") or payload.get("value") or "")
        )
        changes, vectors_invalidated = _update_phrase(
            conn,
            target=target,
            phrase=phrase,
            changed_at_ms=timestamp,
            reason=reason,
            actor=actor,
        )
        fts_rebuilt = True

    # The rebuild function currently owns a full projection. Rebuild all
    # projects so a mutation in one project cannot accidentally erase another
    # project's documents from the shared table.
    retrieval_report = rebuild_retrieval_docs(conn, project="")
    refreshed = _resolve_target(conn, memory_id=memory_id, item_type=target.target_type)
    event_payload = {
        "schemaVersion": MEMORY_ACTION_SCHEMA_VERSION,
        "memoryId": memory_id,
        "targetType": refreshed.target_type,
        "action": action,
        "status": refreshed.status,
        "changedAtMs": timestamp,
        "retrievalDocCount": int(retrieval_report.get("docCount") or 0),
    }
    return {
        "schemaVersion": MEMORY_ACTION_SCHEMA_VERSION,
        "ok": True,
        "memoryId": memory_id,
        "targetType": refreshed.target_type,
        "action": action,
        "status": refreshed.status,
        "changedAtMs": timestamp,
        "changes": changes,
        "retrievalDocs": {**retrieval_report, "rebuilt": True},
        "indexInvalidation": {
            "memoryItemsFtsRebuilt": fts_rebuilt,
            "memoryItemVectorsInvalidated": vectors_invalidated,
            "retrievalDocsRebuilt": True,
        },
        "cacheInvalidation": {
            "required": True,
            "performed": False,
            "targets": ["suggestion_cache", "rime_export_cache"],
        },
        "event": {
            "name": "memory_changed",
            "published": False,
            "payload": event_payload,
        },
    }


def _resolve_target(conn: sqlite3.Connection, *, memory_id: str, item_type: str) -> _Target:
    if item_type not in _ITEM_TYPE_HINTS | _ATOM_TYPE_HINTS | _BOOK_TYPE_HINTS:
        raise ValueError(f"unsupported memory item type: {item_type}")
    lookups = []
    if item_type in _ITEM_TYPE_HINTS:
        lookups.append(_memory_item_target)
    if item_type in _ATOM_TYPE_HINTS or not item_type:
        lookups.append(_memory_atom_target)
    if item_type in _BOOK_TYPE_HINTS or not item_type:
        lookups.append(_memory_book_target)
    for lookup in lookups:
        target = lookup(conn, memory_id)
        if target is not None:
            return target
    raise ValueError(f"memory item not found: {memory_id}")


def _memory_item_target(conn: sqlite3.Connection, memory_id: str) -> _Target | None:
    row = conn.execute(
        """
        SELECT id, memory_id, kind, text, project, app, status, privacy_class,
               confidence, quality_score, metadata_json
        FROM memory_items
        WHERE memory_id = ?
        LIMIT 1
        """,
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return _Target(
        target_type="item",
        table="memory_items",
        id_column="id",
        row_id=int(row[0]),
        memory_id=str(row[1]),
        kind=str(row[2]),
        text=str(row[3] or ""),
        project=str(row[4] or ""),
        app=str(row[5] or ""),
        status=str(row[6]),
        privacy_class=str(row[7] or "local"),
        confidence=float(row[8]),
        quality_score=float(row[9]),
        metadata=_json_object(row[10]),
    )


def _memory_atom_target(conn: sqlite3.Connection, memory_id: str) -> _Target | None:
    row = conn.execute(
        """
        SELECT id, kind, COALESCE(canonical_text, text), scope_project,
               scope_app, status, privacy_level, confidence, quality_score
        FROM memory_atoms
        WHERE id = ?
        LIMIT 1
        """,
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return _Target(
        target_type="atom",
        table="memory_atoms",
        id_column="id",
        row_id=str(row[0]),
        memory_id=str(row[0]),
        kind=str(row[1]),
        text=str(row[2] or ""),
        project=str(row[3] or ""),
        app=str(row[4] or ""),
        status=str(row[5]),
        privacy_class=str(row[6] or "local"),
        confidence=float(row[7]),
        quality_score=float(row[8]),
        metadata={},
    )


def _memory_book_target(conn: sqlite3.Connection, memory_id: str) -> _Target | None:
    row = conn.execute(
        """
        SELECT book_id, book_type, title, project, app, status, confidence,
               quality_score, metadata_json
        FROM memory_books
        WHERE book_id = ?
        LIMIT 1
        """,
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return _Target(
        target_type="book",
        table="memory_books",
        id_column="book_id",
        row_id=str(row[0]),
        memory_id=str(row[0]),
        kind=str(row[1]),
        text=str(row[2] or ""),
        project=str(row[3] or ""),
        app=str(row[4] or ""),
        status=str(row[5]),
        privacy_class="local",
        confidence=float(row[6]),
        quality_score=float(row[7]),
        metadata=_json_object(row[8]),
    )


def _pin_target(
    conn: sqlite3.Connection,
    *,
    target: _Target,
    changed_at_ms: int,
    reason: str,
    actor: str,
) -> dict[str, object]:
    rank_weight = 1.25
    metadata = dict(target.metadata)
    was_pinned = bool(metadata.get("pinned"))
    metadata.update(
        {
            "pinned": True,
            "rankWeight": rank_weight,
            "lastManagementAction": "pin",
            "managedAtMs": changed_at_ms,
        }
    )
    if reason:
        metadata["managementReason"] = reason
    if actor:
        metadata["managedBy"] = actor
    if target.target_type in {"item", "book"}:
        conn.execute(
            f"""
            UPDATE {target.table}
            SET status = 'approved', confidence = MAX(confidence, 0.90),
                quality_score = MAX(quality_score, 0.92), updated_at_ms = ?,
                metadata_json = ?
            WHERE {target.id_column} = ?
            """,
            (changed_at_ms, json.dumps(metadata, ensure_ascii=False, sort_keys=True), target.row_id),
        )
    else:
        conn.execute(
            """
            UPDATE memory_atoms
            SET status = 'approved', confidence = MAX(confidence, 0.90),
                quality_score = MAX(quality_score, 0.92), updated_at_ms = ?
            WHERE id = ?
            """,
            (changed_at_ms, target.row_id),
        )
    if target.target_type == "item":
        conn.execute(
            "UPDATE memory_item_tags SET weight = MAX(weight, ?) WHERE memory_item_id = ?",
            (rank_weight, target.row_id),
        )
        if not was_pinned:
            _record_pin_feedback(conn, target=target, changed_at_ms=changed_at_ms)
    elif target.target_type == "atom":
        conn.execute(
            "UPDATE memory_atom_tags SET weight = MAX(weight, ?) WHERE memory_atom_id = ?",
            (rank_weight, target.row_id),
        )
    _clear_governance(conn, memory_id=target.memory_id)
    return {
        "pinned": True,
        "status": "approved",
        "qualityScore": max(target.quality_score, 0.92),
        "confidence": max(target.confidence, 0.90),
        "rankWeight": rank_weight,
        "feedbackRecorded": target.target_type == "item" and not was_pinned,
    }


def _record_pin_feedback(conn: sqlite3.Connection, *, target: _Target, changed_at_ms: int) -> None:
    query_hash = "sha256:" + hashlib.sha256(f"management-pin:{target.memory_id}".encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO candidate_feedback(
            created_at_ms, query_hash, candidate_text, source_type, memory_id,
            action, app, project, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, ?)
        """,
        (
            changed_at_ms,
            query_hash,
            target.text,
            "phrase" if target.kind == "phrase" else "memory",
            target.memory_id,
            target.app,
            target.project,
            json.dumps({"managementAction": "pin"}, sort_keys=True),
        ),
    )


def _enable_target(conn: sqlite3.Connection, *, target: _Target, changed_at_ms: int) -> dict[str, object]:
    changes = _set_target_status(conn, target=target, status="active", changed_at_ms=changed_at_ms)
    cleared = _clear_governance(conn, memory_id=target.memory_id)
    return {**changes, "governanceCleared": cleared}


def _set_target_status(
    conn: sqlite3.Connection,
    *,
    target: _Target,
    status: str,
    changed_at_ms: int,
) -> dict[str, object]:
    conn.execute(
        f"UPDATE {target.table} SET status = ?, updated_at_ms = ? WHERE {target.id_column} = ?",
        (status, changed_at_ms, target.row_id),
    )
    return {"previousStatus": target.status, "status": status}


def _suppress_target(
    conn: sqlite3.Connection,
    *,
    target: _Target,
    changed_at_ms: int,
    reason: str,
) -> dict[str, object]:
    suppression_id = "management:" + hashlib.sha256(target.memory_id.encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        INSERT INTO memory_candidate_suppressions(
            id, match_type, match_value, action, reason, strength,
            expires_at_ms, created_at_ms
        )
        VALUES (?, 'memory_id', ?, 'block', ?, 1.0, NULL, ?)
        ON CONFLICT(id) DO UPDATE SET
            match_type = 'memory_id',
            match_value = excluded.match_value,
            action = 'block',
            reason = excluded.reason,
            strength = 1.0,
            expires_at_ms = NULL,
            created_at_ms = excluded.created_at_ms
        """,
        (suppression_id, target.memory_id, reason, changed_at_ms),
    )
    return {
        "suppressionId": suppression_id,
        "matchType": "memory_id",
        "matchValue": target.memory_id,
        "status": target.status,
    }


def _tombstone_target(
    conn: sqlite3.Connection,
    *,
    target: _Target,
    changed_at_ms: int,
    reason: str,
) -> dict[str, object]:
    metadata_json = json.dumps({"source": "management_memory_action"}, sort_keys=True)
    row = conn.execute(
        """
        SELECT id
        FROM memory_tombstones
        WHERE target_type = 'memory_id' AND target_value = ? AND active = 1
        ORDER BY id ASC
        LIMIT 1
        """,
        (target.memory_id,),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            """
            INSERT INTO memory_tombstones(
                created_at_ms, target_type, target_value, reason, active,
                metadata_json
            )
            VALUES (?, 'memory_id', ?, ?, 1, ?)
            """,
            (changed_at_ms, target.memory_id, reason, metadata_json),
        )
        tombstone_id = int(cur.lastrowid)
    else:
        tombstone_id = int(row[0])
        conn.execute(
            """
            UPDATE memory_tombstones
            SET created_at_ms = ?, reason = ?, active = 1, metadata_json = ?
            WHERE id = ?
            """,
            (changed_at_ms, reason, metadata_json, tombstone_id),
        )
    _set_target_status(conn, target=target, status="tombstoned", changed_at_ms=changed_at_ms)
    return {
        "tombstoneId": tombstone_id,
        "targetType": "memory_id",
        "targetValue": target.memory_id,
        "status": "tombstoned",
    }


def _update_phrase(
    conn: sqlite3.Connection,
    *,
    target: _Target,
    phrase: str,
    changed_at_ms: int,
    reason: str,
    actor: str,
) -> tuple[dict[str, object], int]:
    if target.target_type != "item" or target.kind != "phrase":
        raise ValueError("update_phrase requires a memory_items phrase record")
    if not phrase:
        raise ValueError("newPhrase is required")
    if looks_sensitive(phrase):
        raise ValueError("sensitive phrases cannot be stored")
    normalized = normalize_text(phrase)
    metadata = dict(target.metadata)
    metadata.update(
        {
            "lastManagementAction": "update_phrase",
            "managedAtMs": changed_at_ms,
            "direct_candidate_allowed": True,
        }
    )
    if reason:
        metadata["managementReason"] = reason
    if actor:
        metadata["managedBy"] = actor
    conn.execute(
        """
        UPDATE memory_items
        SET text = ?, normalized_text = ?, status = 'active',
            updated_at_ms = ?, metadata_json = ?
        WHERE id = ?
        """,
        (phrase, normalized, changed_at_ms, json.dumps(metadata, ensure_ascii=False, sort_keys=True), target.row_id),
    )
    tags = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT t.tag
            FROM memory_item_tags it
            JOIN memory_tags t ON t.id = it.tag_id
            WHERE it.memory_item_id = ?
            ORDER BY it.position ASC, it.weight DESC
            """,
            (target.row_id,),
        ).fetchall()
        if compact_whitespace(str(row[0] or ""))
    ]
    row = conn.execute(
        "SELECT summary, project, app FROM memory_items WHERE id = ?",
        (target.row_id,),
    ).fetchone()
    summary, project, app = (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
    conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (target.row_id,))
    conn.execute(
        """
        INSERT INTO memory_items_fts(
            rowid, text, normalized_text, summary, project, app, tags
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target.row_id,
            build_fts_document(phrase),
            normalized,
            build_fts_document(summary),
            project,
            app,
            " ".join(tags),
        ),
    )
    vector_cursor = conn.execute(
        "DELETE FROM memory_item_vectors WHERE memory_item_id = ?",
        (target.row_id,),
    )
    vectors_invalidated = max(0, int(vector_cursor.rowcount))
    phrase_stats = _migrate_phrase_stats(
        conn,
        old_phrase=target.text,
        new_phrase=phrase,
    )
    governance_cleared = _clear_governance(conn, memory_id=target.memory_id)
    return (
        {
            "status": "active",
            "textChanged": phrase != target.text,
            "normalizedTextChanged": normalized != normalize_text(target.text),
            "ftsRebuilt": True,
            "vectorsInvalidated": vectors_invalidated,
            "phraseStats": phrase_stats,
            "governanceCleared": governance_cleared,
        },
        vectors_invalidated,
    )


def _migrate_phrase_stats(
    conn: sqlite3.Connection,
    *,
    old_phrase: str,
    new_phrase: str,
) -> dict[str, int]:
    old_text = compact_whitespace(old_phrase)
    new_text = compact_whitespace(new_phrase)
    if not old_text or not new_text or old_text == new_text:
        return {"global": 0, "project": 0, "app": 0}
    counts = {"global": 0, "project": 0, "app": 0}
    global_row = conn.execute(
        """
        SELECT input_frequency, first_seen_ms, last_seen_ms
        FROM phrase_stats
        WHERE committed_text = ?
        """,
        (old_text,),
    ).fetchone()
    if global_row is not None:
        conn.execute("DELETE FROM phrase_stats WHERE committed_text = ?", (old_text,))
        conn.execute(
            """
            INSERT INTO phrase_stats(
                committed_text, input_frequency, first_seen_ms, last_seen_ms
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(committed_text) DO UPDATE SET
                input_frequency = phrase_stats.input_frequency + excluded.input_frequency,
                first_seen_ms = MIN(phrase_stats.first_seen_ms, excluded.first_seen_ms),
                last_seen_ms = MAX(phrase_stats.last_seen_ms, excluded.last_seen_ms)
            """,
            (new_text, int(global_row[0]), int(global_row[1]), int(global_row[2])),
        )
        counts["global"] = 1
    for table, scope_column, key in (
        ("phrase_project_stats", "project", "project"),
        ("phrase_app_stats", "app", "app"),
    ):
        rows = conn.execute(
            f"""
            SELECT {scope_column}, input_frequency, first_seen_ms, last_seen_ms
            FROM {table}
            WHERE committed_text = ?
            """,
            (old_text,),
        ).fetchall()
        if not rows:
            continue
        conn.execute(f"DELETE FROM {table} WHERE committed_text = ?", (old_text,))
        for row in rows:
            conn.execute(
                f"""
                INSERT INTO {table}(
                    committed_text, {scope_column}, input_frequency,
                    first_seen_ms, last_seen_ms
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(committed_text, {scope_column}) DO UPDATE SET
                    input_frequency = {table}.input_frequency + excluded.input_frequency,
                    first_seen_ms = MIN({table}.first_seen_ms, excluded.first_seen_ms),
                    last_seen_ms = MAX({table}.last_seen_ms, excluded.last_seen_ms)
                """,
                (new_text, str(row[0]), int(row[1]), int(row[2]), int(row[3])),
            )
        counts[key] = len(rows)
    return counts


def _clear_governance(conn: sqlite3.Connection, *, memory_id: str) -> dict[str, int]:
    tombstones = conn.execute(
        """
        UPDATE memory_tombstones
        SET active = 0
        WHERE target_type = 'memory_id' AND target_value = ? AND active = 1
        """,
        (memory_id,),
    ).rowcount
    suppressions = conn.execute(
        "DELETE FROM memory_candidate_suppressions WHERE match_type = 'memory_id' AND match_value = ?",
        (memory_id,),
    ).rowcount
    return {
        "tombstonesDeactivated": max(0, int(tombstones)),
        "suppressionsRemoved": max(0, int(suppressions)),
    }


def _notify_cache(callback: CacheInvalidator | None) -> dict[str, object]:
    if callback is None:
        return {"performed": False}
    try:
        callback()
    except Exception as exc:  # pragma: no cover - defensive observer boundary
        return {"performed": False, "error": _observer_error(exc)}
    return {"performed": True}


def _publish_event(callback: EventPublisher | None, payload: Mapping[str, object]) -> dict[str, object]:
    if callback is None:
        return {"published": False}
    try:
        callback("memory_changed", payload)
    except Exception as exc:  # pragma: no cover - defensive observer boundary
        return {"published": False, "error": _observer_error(exc)}
    return {"published": True}


def _safe_reason(value: object, *, fallback: str) -> str:
    reason = compact_whitespace(str(value or ""))[:160]
    if not reason:
        return fallback
    return "sensitive_reason_redacted" if looks_sensitive(reason) else reason


def _safe_actor(value: object) -> str:
    actor = compact_whitespace(str(value or ""))[:80]
    return "" if looks_sensitive(actor) else actor


def _observer_error(exc: Exception) -> str:
    return compact_whitespace(f"{type(exc).__name__}: {exc}")[:180]


def _json_object(raw: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "MEMORY_ACTION_SCHEMA_VERSION",
    "execute_memory_action",
    "mutate_memory_action",
]
