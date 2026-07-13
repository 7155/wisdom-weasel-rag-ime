from __future__ import annotations

import json
import sqlite3
from typing import Any

from .memory_schema_v2 import ensure_memory_v2_schema
from .text_utils import build_fts_document, compact_whitespace, now_ms


RETRIEVAL_DOCS_REBUILD_SCHEMA_VERSION = "rag-ime.retrieval-docs-rebuild.v1"


def rebuild_retrieval_docs(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    include_books: bool = True,
    include_atoms: bool = True,
    include_items: bool = True,
) -> dict[str, object]:
    ensure_memory_v2_schema(conn)
    existing = {
        str(row["doc_id"]): tuple(str(row[key] or "") for key in (
            "raw_text", "tags_text", "aliases_text", "surface_hints_text",
            "query_expansions_text", "project", "app", "metadata_json",
        ))
        for row in conn.execute(
            """SELECT doc_id, raw_text, tags_text, aliases_text, surface_hints_text,
                      query_expansions_text, project, app, metadata_json
               FROM memory_retrieval_docs"""
        ).fetchall()
    }
    conn.execute("DELETE FROM memory_retrieval_docs_fts")
    docs: list[dict[str, object]] = []
    tombstones = _active_tombstone_sets(conn)
    if include_items:
        docs.extend(_memory_item_docs(conn, project=project, tombstones=tombstones))
    if include_atoms:
        docs.extend(_memory_atom_docs(conn, project=project, tombstones=tombstones))
    if include_books:
        docs.extend(_memory_book_docs(conn, project=project, tombstones=tombstones))
    timestamp = now_ms()
    counts = {"item": 0, "phrase": 0, "atom": 0, "book": 0}
    active_doc_ids: set[str] = set()
    for doc in docs:
        active_doc_ids.add(str(doc["doc_id"]))
        doc_type = str(doc["doc_type"])
        counts[doc_type] = counts.get(doc_type, 0) + 1
        metadata_json = json.dumps(doc.get("metadata") or {}, ensure_ascii=False, sort_keys=True)
        signature = tuple(str(doc[key] or "") for key in (
            "raw_text", "tags_text", "aliases_text", "surface_hints_text",
            "query_expansions_text", "project", "app",
        )) + (metadata_json,)
        if existing.get(str(doc["doc_id"])) not in {None, signature}:
            conn.execute("DELETE FROM memory_retrieval_doc_vectors WHERE doc_id = ?", (doc["doc_id"],))
        cur = conn.execute(
            """
            INSERT INTO memory_retrieval_docs(
                doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                surface_hints_text, query_expansions_text, time_key, project, app,
                status, updated_at_ms, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                doc_type=excluded.doc_type, source_id=excluded.source_id,
                raw_text=excluded.raw_text, tags_text=excluded.tags_text,
                aliases_text=excluded.aliases_text, surface_hints_text=excluded.surface_hints_text,
                query_expansions_text=excluded.query_expansions_text, time_key=excluded.time_key,
                project=excluded.project, app=excluded.app, status='active',
                updated_at_ms=excluded.updated_at_ms, metadata_json=excluded.metadata_json
            """,
            (
                doc["doc_id"],
                doc_type,
                doc["source_id"],
                doc["raw_text"],
                doc["tags_text"],
                doc["aliases_text"],
                doc["surface_hints_text"],
                doc["query_expansions_text"],
                doc["time_key"],
                doc["project"],
                doc["app"],
                timestamp,
                metadata_json,
            ),
        )
        rowid = int(conn.execute("SELECT rowid FROM memory_retrieval_docs WHERE doc_id = ?", (doc["doc_id"],)).fetchone()[0])
        conn.execute(
            """
            INSERT INTO memory_retrieval_docs_fts(
                rowid,
                raw_text, tags_text, aliases_text, surface_hints_text,
                query_expansions_text, time_key, project, app
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rowid,
                build_fts_document(str(doc["raw_text"])),
                build_fts_document(str(doc["tags_text"])),
                build_fts_document(str(doc["aliases_text"])),
                build_fts_document(str(doc["surface_hints_text"])),
                build_fts_document(str(doc["query_expansions_text"])),
                str(doc["time_key"]),
                str(doc["project"]),
                str(doc["app"]),
            ),
        )
    stale_ids = set(existing) - active_doc_ids
    if stale_ids:
        conn.executemany("DELETE FROM memory_retrieval_docs WHERE doc_id = ?", ((doc_id,) for doc_id in stale_ids))
    return {
        "schemaVersion": RETRIEVAL_DOCS_REBUILD_SCHEMA_VERSION,
        "project": project,
        "docCount": len(docs),
        "counts": counts,
        "includeBooks": bool(include_books),
        "includeAtoms": bool(include_atoms),
        "includeItems": bool(include_items),
        "updatedAtMs": timestamp,
    }


def _memory_item_docs(conn: sqlite3.Connection, *, project: str, tombstones: dict[str, set[str]]) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, memory_id, kind, text, normalized_text, summary, source_event_id,
               project, app, status, privacy_class, metadata_json, updated_at_ms
        FROM memory_items
        WHERE status IN ('active', 'approved')
          AND privacy_class != 'sensitive'
          AND NOT (kind = 'raw_event' AND status = 'hidden')
          AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC, id DESC
        """,
        (project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        memory_id = str(row["memory_id"])
        text = compact_whitespace(str(row["text"] or ""))
        normalized = compact_whitespace(str(row["normalized_text"] or ""))
        if not text or _is_tombstoned(memory_id=memory_id, text=text, normalized_text=normalized, tombstones=tombstones):
            continue
        tags = _memory_item_tags(conn, memory_item_pk=int(row["id"]))
        doc_type = "phrase" if str(row["kind"]) == "phrase" else "item"
        metadata = _json_object(row["metadata_json"])
        context_group_id = compact_whitespace(str(metadata.get("contextGroupId") or ""))
        if not context_group_id and int(row["source_event_id"] or 0) > 0:
            context_group_id = _event_context_group(conn, int(row["source_event_id"]))
        docs.append(
            {
                "doc_id": f"{doc_type}:{memory_id}",
                "doc_type": doc_type,
                "source_id": memory_id,
                "raw_text": " ".join(item for item in (text, compact_whitespace(str(row["summary"] or ""))) if item),
                "tags_text": " ".join(tags),
                "aliases_text": "",
                "surface_hints_text": text if doc_type == "phrase" else "",
                "query_expansions_text": "",
                "time_key": "",
                "project": str(row["project"] or ""),
                "app": str(row["app"] or ""),
                "metadata": {
                    **metadata,
                    "kind": str(row["kind"]),
                    "sourceEventId": int(row["source_event_id"] or 0),
                    "memoryId": memory_id,
                    "source": "memory_items",
                    "contextGroupId": context_group_id,
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                },
            }
        )
    return docs


def _memory_atom_docs(conn: sqlite3.Connection, *, project: str, tombstones: dict[str, set[str]]) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, kind, text, canonical_text, source_event_ids_json, scope_project,
               scope_app, status, quality_score, confidence, updated_at_ms
        FROM memory_atoms
        WHERE status IN ('active', 'approved')
          AND privacy_level != 'sensitive'
          AND (? = '' OR scope_project = ? OR scope_project = '')
        ORDER BY updated_at_ms DESC
        """,
        (project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        atom_id = str(row["id"])
        raw_text = compact_whitespace(str(row["canonical_text"] or row["text"] or ""))
        if not raw_text or _is_tombstoned(memory_id=atom_id, text=raw_text, normalized_text="", tombstones=tombstones):
            continue
        aliases = _atom_aliases(conn, atom_id=atom_id)
        source_event_ids = _json_list(row["source_event_ids_json"])
        docs.append(
            {
                "doc_id": f"atom:{atom_id}",
                "doc_type": "atom",
                "source_id": atom_id,
                "raw_text": raw_text,
                "tags_text": " ".join(_memory_atom_tags(conn, atom_id=atom_id)),
                "aliases_text": " ".join(aliases["alias"]),
                "surface_hints_text": " ".join(aliases["surface_hint"]),
                "query_expansions_text": " ".join(aliases["query_expansion"]),
                "time_key": "",
                "project": str(row["scope_project"] or ""),
                "app": str(row["scope_app"] or ""),
                "metadata": {
                    "kind": str(row["kind"]),
                    "atomId": atom_id,
                    "sourceEventIds": source_event_ids,
                    "source": "memory_atoms",
                    "contextGroupId": _first_event_context_group(conn, source_event_ids),
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                },
            }
        )
    return docs


def _memory_book_docs(conn: sqlite3.Connection, *, project: str, tombstones: dict[str, set[str]]) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT book_id, book_type, book_key, title, summary, project, app, tags_json,
               surface_hints_json, query_expansions_json, source_event_ids_json, memory_atom_ids_json,
               status, confidence, quality_score, metadata_json, updated_at_ms,
               archived_at_ms, last_active_at_ms, archive_reason
        FROM memory_books
        WHERE status IN ('active', 'approved', 'archived')
          AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC
        """,
        (project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        book_id = str(row["book_id"])
        raw_text = compact_whitespace(" ".join(item for item in (str(row["title"] or ""), str(row["summary"] or "")) if item))
        if not raw_text or _is_tombstoned(memory_id=book_id, text=raw_text, normalized_text="", tombstones=tombstones):
            continue
        book_type = str(row["book_type"] or "")
        book_key = str(row["book_key"] or "")
        source_event_ids = _json_list(row["source_event_ids_json"])
        stored_metadata = _json_object(row["metadata_json"])
        docs.append(
            {
                "doc_id": f"book:{book_id}",
                "doc_type": "book",
                "source_id": book_id,
                "raw_text": raw_text,
                "tags_text": " ".join(_json_list(row["tags_json"])),
                "aliases_text": "",
                "surface_hints_text": " ".join(_json_list(row["surface_hints_json"])),
                "query_expansions_text": " ".join(_json_list(row["query_expansions_json"])),
                "time_key": f"{book_type}:{book_key}" if book_type and book_key else book_key,
                "project": str(row["project"] or ""),
                "app": str(row["app"] or ""),
                "metadata": {
                    **stored_metadata,
                    "bookType": book_type,
                    "bookKey": book_key,
                    "bookTitle": compact_whitespace(str(row["title"] or "")),
                    "sourceEventIds": source_event_ids,
                    "memoryAtomIds": _json_list(row["memory_atom_ids_json"]),
                    "source": "memory_books",
                    "bookStatus": str(row["status"] or "active"),
                    "archived": str(row["status"] or "") == "archived",
                    "archivedAtMs": int(row["archived_at_ms"] or 0),
                    "lastActiveAtMs": int(row["last_active_at_ms"] or 0),
                    "archiveReason": str(row["archive_reason"] or ""),
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                    "contextGroupId": compact_whitespace(str(stored_metadata.get("contextGroupId") or ""))
                    or _first_event_context_group(conn, source_event_ids),
                },
            }
        )
    return docs


def _memory_item_tags(conn: sqlite3.Connection, *, memory_item_pk: int) -> list[str]:
    return [
        str(row["tag"])
        for row in conn.execute(
            """
            SELECT t.tag
            FROM memory_item_tags it
            JOIN memory_tags t ON t.id = it.tag_id
            WHERE it.memory_item_id = ?
              AND t.status = 'active'
              AND t.source IN ('curated_import', 'dsv4', 'user')
            ORDER BY it.position ASC, it.weight DESC
            """,
            (memory_item_pk,),
        ).fetchall()
        if compact_whitespace(str(row["tag"]))
    ]


def _memory_atom_tags(conn: sqlite3.Connection, *, atom_id: str) -> list[str]:
    return [
        str(row["tag"])
        for row in conn.execute(
            """
            SELECT t.tag
            FROM memory_atom_tags at
            JOIN memory_tags t ON CAST(t.id AS TEXT) = CAST(at.tag_id AS TEXT)
            WHERE at.memory_atom_id = ?
              AND t.status = 'active'
              AND t.source IN ('curated_import', 'dsv4', 'user')
            ORDER BY at.weight DESC, t.tag ASC
            """,
            (atom_id,),
        ).fetchall()
        if compact_whitespace(str(row["tag"]))
    ]


def _atom_aliases(conn: sqlite3.Connection, *, atom_id: str) -> dict[str, list[str]]:
    result = {"alias": [], "surface_hint": [], "query_expansion": []}
    for row in conn.execute(
        """
        SELECT alias, alias_type
        FROM memory_aliases
        WHERE memory_atom_id = ?
        ORDER BY weight DESC, created_at_ms ASC
        """,
        (atom_id,),
    ).fetchall():
        alias = compact_whitespace(str(row["alias"] or ""))
        alias_type = str(row["alias_type"] or "alias")
        if alias and alias_type in result:
            result[alias_type].append(alias)
    return result


def _event_context_group(conn: sqlite3.Connection, event_id: int) -> str:
    row = conn.execute(
        "SELECT context_group_id FROM input_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    return "" if row is None else compact_whitespace(str(row["context_group_id"] or ""))


def _first_event_context_group(conn: sqlite3.Connection, event_ids: list[object]) -> str:
    for value in event_ids:
        try:
            event_id = int(value)
        except (TypeError, ValueError):
            continue
        group_id = _event_context_group(conn, event_id)
        if group_id:
            return group_id
    return ""


def _json_object(raw: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _active_tombstone_sets(conn: sqlite3.Connection) -> dict[str, set[str]]:
    result = {"memory_id": set(), "normalized_text": set(), "text": set(), "phrase": set()}
    for row in conn.execute(
        "SELECT target_type, target_value FROM memory_tombstones WHERE active = 1"
    ).fetchall():
        target_type = str(row["target_type"] or "")
        target_value = compact_whitespace(str(row["target_value"] or ""))
        if target_type in result and target_value:
            result[target_type].add(target_value)
    return result


def _is_tombstoned(*, memory_id: str, text: str, normalized_text: str, tombstones: dict[str, set[str]]) -> bool:
    normalized = normalized_text or compact_whitespace(text)
    return (
        memory_id in tombstones["memory_id"]
        or f"phrase:{normalized}" in tombstones["memory_id"]
        or text in tombstones["text"]
        or text in tombstones["phrase"]
        or normalized in tombstones["normalized_text"]
        or normalized in tombstones["phrase"]
    )


def _json_list(raw: Any) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [compact_whitespace(str(item)) for item in parsed if compact_whitespace(str(item))]
