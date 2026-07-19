from __future__ import annotations

import json
import sqlite3
from typing import Any

from .input_quality import MEMORY_CONTEXT_OPT_IN_TAG
from .memory_schema_v2 import ensure_memory_v2_schema
from .text_utils import build_fts_document, compact_whitespace, now_ms, truncate_text


RETRIEVAL_DOCS_REBUILD_SCHEMA_VERSION = "rag-ime.retrieval-docs-rebuild.v1"


def rebuild_retrieval_docs(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    include_books: bool = True,
    include_atoms: bool = True,
    include_phrases: bool = True,
    include_timelines: bool = True,
    include_legacy_items: bool = False,
    include_items: bool | None = None,
) -> dict[str, object]:
    """Rebuild governed retrieval projections and retire legacy item docs.

    ``include_items`` is a compatibility alias for callers of the old API. It
    now controls legacy ``item`` documents only; phrases have their own flag so
    disabling raw legacy projections can never remove IME phrase candidates.
    """

    ensure_memory_v2_schema(conn)
    if include_items is not None:
        include_legacy_items = bool(include_items)
    # Read every projection type owned by this rebuild, not only enabled types.
    # Otherwise a default rebuild would leave old ``item`` rows (and their FTS
    # and vector projections) alive forever.
    managed_doc_types = ("item", "phrase", "atom", "book", "timeline")
    type_placeholders = ", ".join("?" for _ in managed_doc_types)
    existing_rows = conn.execute(
        f"""SELECT rowid, doc_id, doc_type, source_id, raw_text, tags_text,
                   aliases_text, surface_hints_text, query_expansions_text,
                   time_key, project, app, owner_kind, owner_id, metadata_json,
                   updated_at_ms,
                   EXISTS(
                       SELECT 1 FROM memory_retrieval_docs_fts f
                       WHERE f.rowid = memory_retrieval_docs.rowid
                   ) AS fts_present
            FROM memory_retrieval_docs
            WHERE (? = '' OR project = ? OR project = '')
              AND doc_type IN ({type_placeholders})""",
        (project, project, *managed_doc_types),
    ).fetchall()
    existing = {
        str(row["doc_id"]): {
            "signature": tuple(str(row[key] or "") for key in (
                "doc_type", "source_id", "raw_text", "tags_text", "aliases_text",
                "surface_hints_text", "query_expansions_text", "time_key",
                "project", "app", "owner_kind", "owner_id", "metadata_json",
            )),
            "rowid": int(row["rowid"]),
            "updatedAtMs": int(row["updated_at_ms"] or 0),
            "ftsPresent": bool(row["fts_present"]),
        }
        for row in existing_rows
    }
    docs = expected_retrieval_docs(
        conn,
        project=project,
        include_books=include_books,
        include_atoms=include_atoms,
        include_phrases=include_phrases,
        include_timelines=include_timelines,
        include_legacy_items=include_legacy_items,
    )
    timestamp = now_ms()
    counts = {"item": 0, "phrase": 0, "atom": 0, "book": 0, "timeline": 0}
    active_doc_ids: set[str] = set()
    changed_doc_ids: set[str] = set()
    for doc in docs:
        doc_id = str(doc["doc_id"])
        active_doc_ids.add(doc_id)
        doc_type = str(doc["doc_type"])
        counts[doc_type] = counts.get(doc_type, 0) + 1
        metadata_json = json.dumps(doc.get("metadata") or {}, ensure_ascii=False, sort_keys=True)
        signature = tuple(str(doc[key] or "") for key in (
            "doc_type", "source_id", "raw_text", "tags_text", "aliases_text",
            "surface_hints_text", "query_expansions_text", "time_key", "project", "app",
            "owner_kind", "owner_id",
        )) + (metadata_json,)
        previous = existing.get(doc_id)
        if (
            previous is not None
            and previous["signature"] == signature
            and bool(previous["ftsPresent"])
        ):
            continue
        changed_doc_ids.add(doc_id)
        conn.execute(
            "DELETE FROM memory_retrieval_doc_vectors WHERE doc_id = ?",
            (doc["doc_id"],),
        )
        conn.execute(
            """
            INSERT INTO memory_retrieval_docs(
                doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                surface_hints_text, query_expansions_text, time_key, project, app,
                owner_kind, owner_id, status, updated_at_ms, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                doc_type=excluded.doc_type, source_id=excluded.source_id,
                raw_text=excluded.raw_text, tags_text=excluded.tags_text,
                aliases_text=excluded.aliases_text, surface_hints_text=excluded.surface_hints_text,
                query_expansions_text=excluded.query_expansions_text, time_key=excluded.time_key,
                project=excluded.project, app=excluded.app,
                owner_kind=excluded.owner_kind, owner_id=excluded.owner_id, status='active',
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
                doc["owner_kind"],
                doc["owner_id"],
                timestamp,
                metadata_json,
            ),
        )
        rowid = int(conn.execute("SELECT rowid FROM memory_retrieval_docs WHERE doc_id = ?", (doc["doc_id"],)).fetchone()[0])
        conn.execute("DELETE FROM memory_retrieval_docs_fts WHERE rowid = ?", (rowid,))
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
        conn.executemany(
            "DELETE FROM memory_retrieval_docs_fts WHERE rowid = ?",
            ((int(existing[doc_id]["rowid"]),) for doc_id in stale_ids),
        )
        conn.executemany(
            "DELETE FROM memory_retrieval_doc_vectors WHERE doc_id = ?",
            ((doc_id,) for doc_id in stale_ids),
        )
        conn.executemany("DELETE FROM memory_retrieval_docs WHERE doc_id = ?", ((doc_id,) for doc_id in stale_ids))
    return {
        "schemaVersion": RETRIEVAL_DOCS_REBUILD_SCHEMA_VERSION,
        "project": project,
        "docCount": len(docs),
        "counts": counts,
        "includeBooks": bool(include_books),
        "includeAtoms": bool(include_atoms),
        "includePhrases": bool(include_phrases),
        "includeTimelines": bool(include_timelines),
        "includeLegacyItems": bool(include_legacy_items),
        # Retain the old result field while callers migrate to the precise name.
        "includeItems": bool(include_legacy_items),
        "changedDocIds": sorted(changed_doc_ids),
        "removedDocIds": sorted(stale_ids),
        "updatedAtMs": timestamp,
    }


def expected_retrieval_docs(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    include_books: bool = True,
    include_atoms: bool = True,
    include_phrases: bool = True,
    include_timelines: bool = True,
    include_legacy_items: bool = False,
) -> list[dict[str, object]]:
    """Build the exact governed document set without mutating projections."""

    docs: list[dict[str, object]] = []
    tombstones = _active_tombstone_sets(conn)
    if include_phrases or include_legacy_items:
        docs.extend(
            _memory_item_docs(
                conn,
                project=project,
                tombstones=tombstones,
                include_phrases=include_phrases,
                include_legacy_items=include_legacy_items,
            )
        )
    if include_atoms:
        docs.extend(_memory_atom_docs(conn, project=project, tombstones=tombstones))
    if include_books:
        docs.extend(_memory_book_docs(conn, project=project, tombstones=tombstones))
    if include_timelines:
        docs.extend(
            _activity_timeline_docs(
                conn,
                project=project,
                tombstones=tombstones,
            )
        )
    return docs


def _memory_item_docs(
    conn: sqlite3.Connection,
    *,
    project: str,
    tombstones: dict[str, set[str]],
    include_phrases: bool,
    include_legacy_items: bool,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, memory_id, kind, text, normalized_text, summary, source_event_id,
               project, app, owner_kind, owner_id, status, privacy_class,
               metadata_json, updated_at_ms
        FROM memory_items
        WHERE status IN ('active', 'approved')
          AND privacy_class != 'sensitive'
          AND kind != 'raw_event'
          AND NOT EXISTS (
              SELECT 1
              FROM input_events source_event
              WHERE source_event.id = memory_items.source_event_id
                AND source_event.source = 'codex_history'
                AND COALESCE(source_event.tags_json, '[]') NOT LIKE ?
          )
          AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC, id DESC
        """,
        (f'%"{MEMORY_CONTEXT_OPT_IN_TAG}"%', project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        memory_id = str(row["memory_id"])
        text = compact_whitespace(str(row["text"] or ""))
        normalized = compact_whitespace(str(row["normalized_text"] or ""))
        metadata = _json_object(row["metadata_json"])
        metadata_source_event_ids = metadata.get("sourceEventIds")
        source_event_ids = _positive_event_ids(
            [
                row["source_event_id"],
                *(
                    metadata_source_event_ids
                    if isinstance(metadata_source_event_ids, (list, tuple))
                    else []
                ),
            ]
        )
        if not text or _is_tombstoned(
            memory_id=memory_id,
            text=text,
            normalized_text=normalized,
            source_event_ids=source_event_ids,
            tombstones=tombstones,
        ) or (
            source_event_ids
            and not _source_events_retrievable(conn, source_event_ids)
        ):
            continue
        tags = _memory_item_tags(conn, memory_item_pk=int(row["id"]))
        doc_type = "phrase" if str(row["kind"]) == "phrase" else "item"
        if doc_type == "phrase" and not include_phrases:
            continue
        if doc_type == "item" and not include_legacy_items:
            continue
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
                "owner_kind": str(row["owner_kind"] or "user"),
                "owner_id": str(row["owner_id"] or "default"),
                "metadata": {
                    **metadata,
                    "kind": str(row["kind"]),
                    "sourceEventId": int(row["source_event_id"] or 0),
                    "memoryId": memory_id,
                    "source": "memory_items",
                    "contextGroupId": context_group_id,
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                    "ownerKind": str(row["owner_kind"] or "user"),
                    "ownerId": str(row["owner_id"] or "default"),
                },
            }
        )
    return docs


def _memory_atom_docs(conn: sqlite3.Connection, *, project: str, tombstones: dict[str, set[str]]) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, kind, text, canonical_text, source_event_ids_json, scope_project,
               scope_app, owner_kind, owner_id, status, quality_score, confidence,
               updated_at_ms
        FROM memory_atoms
        WHERE status IN ('active', 'approved')
          AND claim_state = 'current'
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
        source_event_ids = _json_list(row["source_event_ids_json"])
        if not raw_text or _is_tombstoned(
            memory_id=atom_id,
            text=raw_text,
            normalized_text="",
            source_event_ids=source_event_ids,
            tombstones=tombstones,
        ) or (
            source_event_ids
            and not _source_events_retrievable(conn, source_event_ids)
        ):
            continue
        aliases = _atom_aliases(conn, atom_id=atom_id)
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
                "owner_kind": str(row["owner_kind"] or "user"),
                "owner_id": str(row["owner_id"] or "default"),
                "metadata": {
                    "kind": str(row["kind"]),
                    "atomId": atom_id,
                    "sourceEventIds": source_event_ids,
                    "source": "memory_atoms",
                    "contextGroupId": _first_event_context_group(conn, source_event_ids),
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                    "ownerKind": str(row["owner_kind"] or "user"),
                    "ownerId": str(row["owner_id"] or "default"),
                },
            }
        )
    return docs


def _memory_book_docs(conn: sqlite3.Connection, *, project: str, tombstones: dict[str, set[str]]) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT book_id, book_type, book_key, title, summary, project, app, tags_json,
               surface_hints_json, query_expansions_json, source_event_ids_json, memory_atom_ids_json,
               owner_kind, owner_id, status, confidence, quality_score, metadata_json,
               updated_at_ms,
               archived_at_ms, last_active_at_ms, archive_reason
        FROM memory_books
        WHERE status IN ('active', 'approved', 'archived')
          AND book_type NOT IN ('app_archive', 'daily')
          AND archive_reason NOT IN (
              'complete_input_history',
              'superseded_by_curated_baseline',
              'discarded_by_manual_review'
          )
          AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC
        """,
        (project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        book_id = str(row["book_id"])
        raw_text = compact_whitespace(" ".join(item for item in (str(row["title"] or ""), str(row["summary"] or "")) if item))
        source_event_ids = _json_list(row["source_event_ids_json"])
        if not raw_text or _is_tombstoned(
            memory_id=book_id,
            text=raw_text,
            normalized_text="",
            source_event_ids=source_event_ids,
            tombstones=tombstones,
        ) or (
            source_event_ids
            and not _source_events_retrievable(conn, source_event_ids)
        ):
            continue
        book_type = str(row["book_type"] or "")
        book_key = str(row["book_key"] or "")
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
                "owner_kind": str(row["owner_kind"] or "user"),
                "owner_id": str(row["owner_id"] or "default"),
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
                    "ownerKind": str(row["owner_kind"] or "user"),
                    "ownerId": str(row["owner_id"] or "default"),
                },
            }
        )
    return docs


def _activity_timeline_docs(
    conn: sqlite3.Connection,
    *,
    project: str,
    tombstones: dict[str, set[str]],
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT timeline_id, project, timeline_date, status,
               source_event_ids_json, source_event_hash, segments_json,
               summary_text, event_count, segment_count, metadata_json,
               approved_by, approved_at_ms, updated_at_ms
        FROM daily_activity_timelines
        WHERE status = 'approved'
          AND (? = '' OR project = ? OR project = '')
        ORDER BY timeline_date DESC, updated_at_ms DESC, timeline_id DESC
        """,
        (project, project),
    ).fetchall()
    docs: list[dict[str, object]] = []
    for row in rows:
        timeline_id = compact_whitespace(str(row["timeline_id"] or ""))
        source_event_ids = _positive_event_ids(
            tuple(_json_list(row["source_event_ids_json"]))
        )
        summary = compact_whitespace(str(row["summary_text"] or ""))
        if (
            not timeline_id
            or not summary
            or _is_tombstoned(
                memory_id=timeline_id,
                text=summary,
                normalized_text="",
                source_event_ids=source_event_ids,
                tombstones=tombstones,
            )
            or (
                source_event_ids
                and not _source_events_retrievable(conn, source_event_ids)
            )
        ):
            continue
        segments = _json_objects(row["segments_json"])
        task_titles = _unique_text(
            compact_whitespace(str(segment.get("title") or ""))
            for segment in segments
        )
        task_summaries = _unique_text(
            compact_whitespace(str(segment.get("summary") or ""))
            for segment in segments
        )
        apps = _unique_text(
            value
            for segment in segments
            for value in (
                [
                    compact_whitespace(str(item))
                    for item in segment.get("apps") or []
                ]
                if isinstance(segment.get("apps"), list)
                else [compact_whitespace(str(segment.get("app") or ""))]
            )
        )
        timeline_date = compact_whitespace(str(row["timeline_date"] or ""))
        title = f"{timeline_date} 活动时间线"
        raw_text = truncate_text(
            "。".join(
                item
                for item in (title, summary, *task_titles, *task_summaries)
                if item
            ),
            3_200,
        )
        stored_metadata = _json_object(row["metadata_json"])
        docs.append(
            {
                "doc_id": f"timeline:{timeline_id}",
                "doc_type": "timeline",
                "source_id": timeline_id,
                "raw_text": raw_text,
                "tags_text": " ".join(
                    ["daily", "activity-timeline", timeline_date, *apps]
                ),
                "aliases_text": "",
                "surface_hints_text": " ".join(task_titles),
                "query_expansions_text": " ".join(
                    (
                        "时间线",
                        "最近工作",
                        "当天活动",
                        "做了什么",
                        timeline_date,
                    )
                ),
                "time_key": f"timeline:{timeline_date}",
                "project": str(row["project"] or ""),
                "app": apps[0] if len(apps) == 1 else "multiple" if apps else "",
                "owner_kind": "user",
                "owner_id": "default",
                "metadata": {
                    **stored_metadata,
                    "kind": "activity_timeline",
                    "derivedArtifactType": "daily_activity_timeline",
                    "timelineId": timeline_id,
                    "timelineTitle": title,
                    "timelineDate": timeline_date,
                    "sourceEventHash": str(row["source_event_hash"] or ""),
                    "sourceEventIds": source_event_ids,
                    "taskTitles": task_titles,
                    "eventCount": int(row["event_count"] or 0),
                    "segmentCount": int(row["segment_count"] or 0),
                    "source": "daily_activity_timelines",
                    "sourceUpdatedAtMs": int(row["updated_at_ms"] or 0),
                    "publishedAtMs": int(row["approved_at_ms"] or 0),
                    "publishedBy": str(row["approved_by"] or ""),
                    "ownerKind": "user",
                    "ownerId": "default",
                    "maySupportFacts": False,
                    "corroborationOnly": True,
                    "shortTerm": True,
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


def _json_objects(raw: object) -> list[dict[str, object]]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _unique_text(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = compact_whitespace(str(value or ""))
        if text and text not in result:
            result.append(text)
    return result


def _active_tombstone_sets(conn: sqlite3.Connection) -> dict[str, set[str]]:
    result = {
        "memory_id": set(),
        "source_event_id": set(),
        "normalized_text": set(),
        "text": set(),
        "phrase": set(),
    }
    for row in conn.execute(
        "SELECT target_type, target_value FROM memory_tombstones WHERE active = 1"
    ).fetchall():
        target_type = str(row["target_type"] or "")
        target_value = compact_whitespace(str(row["target_value"] or ""))
        if target_type in result and target_value:
            result[target_type].add(target_value)
    return result


def _is_tombstoned(
    *,
    memory_id: str,
    text: str,
    normalized_text: str,
    source_event_ids: list[object] | tuple[object, ...] = (),
    tombstones: dict[str, set[str]],
) -> bool:
    normalized = normalized_text or compact_whitespace(text)
    return (
        memory_id in tombstones["memory_id"]
        or f"phrase:{normalized}" in tombstones["memory_id"]
        or text in tombstones["text"]
        or text in tombstones["phrase"]
        or normalized in tombstones["normalized_text"]
        or normalized in tombstones["phrase"]
        or _source_event_tombstoned(source_event_ids, tombstones=tombstones)
    )


def _source_event_tombstoned(
    event_ids: list[object] | tuple[object, ...],
    *,
    tombstones: dict[str, set[str]],
) -> bool:
    for value in event_ids:
        try:
            event_id = int(value)
        except (TypeError, ValueError):
            continue
        if event_id <= 0:
            continue
        if (
            str(event_id) in tombstones["source_event_id"]
            or f"event:{event_id}" in tombstones["memory_id"]
        ):
            return True
    return False


def _positive_event_ids(values: list[object] | tuple[object, ...]) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            event_id = int(value)
        except (TypeError, ValueError):
            continue
        if event_id > 0 and event_id not in result:
            result.append(event_id)
    return result


def _source_events_retrievable(
    conn: sqlite3.Connection,
    event_ids: list[object] | tuple[object, ...],
) -> bool:
    normalized = _positive_event_ids(event_ids)
    if not normalized:
        return False
    placeholders = ",".join("?" for _ in normalized)
    visible = int(
        conn.execute(
            f"""SELECT COUNT(*)
                FROM input_events AS event
                WHERE event.id IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM memory_tombstones AS tombstone
                      WHERE tombstone.active = 1
                        AND (
                            (tombstone.target_type = 'source_event_id'
                             AND tombstone.target_value = CAST(event.id AS TEXT))
                            OR
                            (tombstone.target_type = 'memory_id'
                             AND tombstone.target_value = ('event:' || event.id))
                        )
                  )""",
            tuple(normalized),
        ).fetchone()[0]
    )
    if visible != len(normalized):
        return False
    governed_unavailable = int(
        conn.execute(
            f"""SELECT COUNT(*)
                FROM (
                    SELECT input_event_id
                    FROM agent_memory_sources
                    WHERE input_event_id IN ({placeholders})
                    GROUP BY input_event_id
                    HAVING SUM(
                        CASE
                            WHEN status = 'active'
                             AND disposition NOT IN ('not_for_memory', 'expired')
                            THEN 1 ELSE 0
                        END
                    ) = 0
                ) AS unavailable""",
            tuple(normalized),
        ).fetchone()[0]
    )
    return governed_unavailable == 0


def _json_list(raw: Any) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [compact_whitespace(str(item)) for item in parsed if compact_whitespace(str(item))]
