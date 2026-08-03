from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping

from .memory_evidence_admission import admitted_personal_evidence_sql
from .memory_ingest import normalize_text
from .text_utils import compact_whitespace, now_ms, stable_text_hash


PERSONAL_BOOK_PROJECTOR = "personal-memory-book-projector-v1"
_SYSTEM_ARCHIVE_REASONS = frozenset(
    {"membership_below_two", "projection_no_longer_current"}
)
_GENERIC_TAGS = frozenset(
    {
        "memory",
        "personal",
        "preference",
        "habit",
        "fact",
        "principle",
        "记忆",
        "个人",
        "偏好",
        "习惯",
        "事实",
        "原则",
        "codex",
        "external-memory",
    }
)


def project_personal_memory_books(
    conn: sqlite3.Connection,
    *,
    current_ms: int | None = None,
) -> dict[str, object]:
    """Rebuild optional Topic Books from every supported current personal Atom."""

    timestamp = now_ms() if current_ms is None else max(0, int(current_ms))
    atoms = _current_personal_atoms(conn)
    desired = _desired_books(atoms)
    existing_rows = conn.execute(
        """
        SELECT * FROM memory_books
        WHERE json_valid(metadata_json)
          AND json_extract(metadata_json, '$.projectionOwner') = ?
        ORDER BY book_id
        """,
        (PERSONAL_BOOK_PROJECTOR,),
    ).fetchall()
    existing = {str(row["book_id"]): row for row in existing_rows}
    upserted: list[str] = []
    guarded: list[str] = []
    for book_id, book in desired.items():
        previous = existing.get(book_id)
        if (
            previous is not None
            and str(previous["status"] or "") == "archived"
            and str(previous["archive_reason"] or "") not in _SYSTEM_ARCHIVE_REASONS
        ):
            guarded.append(book_id)
            continue
        previous_metadata = (
            _json_object(previous["metadata_json"]) if previous is not None else {}
        )
        for stale_key in (
            "retrievalStale",
            "retrievalStaleReason",
            "retrievalStaleAtMs",
        ):
            previous_metadata.pop(stale_key, None)
        metadata = {
            **previous_metadata,
            "projectionOwner": PERSONAL_BOOK_PROJECTOR,
            "membershipStrategy": "validated_topic_tag",
            "stableAnchor": str(book["tag"]),
            "memberCount": len(book["memberIds"]),
            "projectedAtMs": timestamp,
        }
        conn.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json,
                query_expansions_json, source_event_ids_json,
                memory_atom_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                last_active_at_ms, archive_reason, owner_kind, owner_id,
                knowledge_domain, scope_kind, scope_id, visibility,
                authorization_revision, binding_id, scope_mode
            ) VALUES (?, 'topic', ?, ?, ?, ?, '', '', ?, '[]', '[]', ?, ?,
                      'active', ?, ?, ?, ?, ?, NULL, ?, '', 'user', 'default',
                      'personal_memory', 'user', 'default', 'private',
                      'memory-book-v1', ?, 'authoritative')
            ON CONFLICT(book_id) DO UPDATE SET
                book_type = 'topic',
                book_key = excluded.book_key,
                title = excluded.title,
                summary = excluded.summary,
                normalized_text = excluded.normalized_text,
                project = '',
                app = '',
                tags_json = excluded.tags_json,
                surface_hints_json = '[]',
                query_expansions_json = '[]',
                source_event_ids_json = excluded.source_event_ids_json,
                memory_atom_ids_json = excluded.memory_atom_ids_json,
                status = 'active',
                confidence = excluded.confidence,
                quality_score = excluded.quality_score,
                updated_at_ms = excluded.updated_at_ms,
                metadata_json = excluded.metadata_json,
                archived_at_ms = NULL,
                last_active_at_ms = excluded.last_active_at_ms,
                archive_reason = '',
                owner_kind = 'user',
                owner_id = 'default',
                knowledge_domain = 'personal_memory',
                scope_kind = 'user',
                scope_id = 'default',
                visibility = 'private',
                authorization_revision = 'memory-book-v1',
                binding_id = excluded.binding_id,
                scope_mode = 'authoritative'
            """,
            (
                book_id,
                str(book["bookKey"]),
                str(book["title"]),
                str(book["summary"]),
                normalize_text(f"{book['title']} {book['summary']}"),
                json.dumps([book["tag"]], ensure_ascii=False, separators=(",", ":")),
                json.dumps(book["sourceEventIds"], ensure_ascii=False, separators=(",", ":")),
                json.dumps(book["memberIds"], ensure_ascii=False, separators=(",", ":")),
                float(book["confidence"]),
                float(book["confidence"]),
                int(previous["created_at_ms"] or timestamp) if previous is not None else timestamp,
                timestamp,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                timestamp,
                f"personal-memory-book:{book_id}",
            ),
        )
        upserted.append(book_id)

    archived: list[str] = []
    for book_id, row in existing.items():
        if book_id in desired or str(row["status"] or "") == "archived":
            continue
        conn.execute(
            """
            UPDATE memory_books
            SET status = 'archived', archived_at_ms = ?,
                archive_reason = 'membership_below_two', updated_at_ms = ?
            WHERE book_id = ?
            """,
            (timestamp, timestamp, book_id),
        )
        archived.append(book_id)

    booked_atom_ids = {
        atom_id
        for book_id, book in desired.items()
        if book_id not in guarded
        for atom_id in book["memberIds"]
    }
    return {
        "schemaVersion": "rag-ime.personal-memory-book-projection.v1",
        "ok": True,
        "projectionOwner": PERSONAL_BOOK_PROJECTOR,
        "currentAtomCount": len(atoms),
        "activeBookCount": len(desired) - len(guarded),
        "unbookedAtomCount": len(
            {str(atom["id"]) for atom in atoms} - booked_atom_ids
        ),
        "upsertedBookIds": upserted,
        "archivedBookIds": archived,
        "guardedBookIds": guarded,
    }


def personal_memory_book_projection_status(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Report projection drift without mutating Books or exposing Atom text."""

    atoms = _current_personal_atoms(conn)
    desired = _desired_books(atoms)
    rows = conn.execute(
        """
        SELECT book_id, status, archive_reason, memory_atom_ids_json
        FROM memory_books
        WHERE json_valid(metadata_json)
          AND json_extract(metadata_json, '$.projectionOwner') = ?
        ORDER BY book_id
        """,
        (PERSONAL_BOOK_PROJECTOR,),
    ).fetchall()
    active = {
        str(row["book_id"]): row
        for row in rows
        if str(row["status"] or "") == "active"
    }
    guarded = {
        str(row["book_id"])
        for row in rows
        if str(row["status"] or "") == "archived"
        and str(row["archive_reason"] or "") not in _SYSTEM_ARCHIVE_REASONS
        and str(row["book_id"]) in desired
    }
    effective_desired = set(desired) - guarded
    missing = effective_desired - set(active)
    stale = set(active) - effective_desired
    membership_mismatches = {
        book_id
        for book_id in effective_desired.intersection(active)
        if set(_json_strings(active[book_id]["memory_atom_ids_json"]))
        != set(desired[book_id]["memberIds"])
    }
    booked_atom_ids = {
        atom_id
        for book_id, book in desired.items()
        if book_id not in guarded
        for atom_id in book["memberIds"]
    }
    return {
        "schemaVersion": "rag-ime.personal-memory-book-projection-status.v1",
        "ok": not missing and not stale and not membership_mismatches,
        "projectionOwner": PERSONAL_BOOK_PROJECTOR,
        "currentAtomCount": len(atoms),
        "desiredBookCount": len(effective_desired),
        "activeBookCount": len(active),
        "historicalBookCount": len(rows) - len(active),
        "unbookedAtomCount": len(
            {str(atom["id"]) for atom in atoms} - booked_atom_ids
        ),
        "missingBookCount": len(missing),
        "staleBookCount": len(stale),
        "membershipMismatchCount": len(membership_mismatches),
        "guardedBookCount": len(guarded),
        "inSync": not missing and not stale and not membership_mismatches,
    }


def _desired_books(
    atoms: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    display_by_key: dict[str, str] = {}
    for atom in atoms:
        for tag in atom["tags"]:
            key = normalize_text(str(tag))
            if not key or key in _GENERIC_TAGS or len(key) > 64:
                continue
            groups[key].append(atom)
            display_by_key.setdefault(key, str(tag))

    desired: dict[str, dict[str, object]] = {}
    seen_memberships: set[tuple[str, ...]] = set()
    for key, members in sorted(
        groups.items(),
        key=lambda item: (-len({str(atom["id"]) for atom in item[1]}), item[0]),
    ):
        unique_members = sorted(
            {str(atom["id"]): atom for atom in members}.values(),
            key=lambda atom: (str(atom["claimKey"]), str(atom["id"])),
        )
        member_ids = tuple(str(atom["id"]) for atom in unique_members)
        if len(member_ids) < 2 or member_ids in seen_memberships:
            continue
        seen_memberships.add(member_ids)
        digest = stable_text_hash(key).removeprefix("sha256:")[:20]
        book_id = f"book:personal:topic:{digest}"
        summary = "；".join(
            compact_whitespace(str(atom["canonicalText"]))
            for atom in unique_members
            if compact_whitespace(str(atom["canonicalText"]))
        )[:2400]
        source_event_ids = sorted(
            {
                int(event_id)
                for atom in unique_members
                for event_id in atom["sourceEventIds"]
                if int(event_id) > 0
            }
        )
        desired[book_id] = {
            "bookId": book_id,
            "bookKey": f"personal-topic:{digest}",
            "title": display_by_key[key],
            "summary": summary,
            "tag": display_by_key[key],
            "memberIds": list(member_ids),
            "sourceEventIds": source_event_ids,
            "confidence": min(
                (float(atom["confidence"]) for atom in unique_members),
                default=0.0,
            ),
        }

    return desired


def _current_personal_atoms(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        f"""
        SELECT atom.*
        FROM memory_atoms AS atom
        WHERE atom.owner_kind = 'user' AND atom.owner_id = 'default'
          AND atom.knowledge_domain = 'personal_memory'
          AND atom.scope_kind = 'user' AND atom.scope_id = 'default'
          AND atom.scope_mode = 'authoritative'
          AND COALESCE(atom.scope_project, '') = ''
          AND COALESCE(atom.scope_app, '') = ''
          AND atom.status IN ('active', 'approved')
          AND atom.claim_state = 'current'
          AND EXISTS (
              SELECT 1
              FROM memory_atom_evidence_links AS atom_link
              JOIN agent_memory_evidence AS evidence
                ON evidence.evidence_id = atom_link.evidence_id
              WHERE atom_link.memory_atom_id = atom.id
                AND atom_link.relation IN ('supports', 'corrects')
                AND {admitted_personal_evidence_sql('evidence')}
          )
        ORDER BY atom.claim_key, atom.id
        """
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        atom_id = str(row["id"])
        tags = [
            str(tag["tag"])
            for tag in conn.execute(
                """
                SELECT tag.tag
                FROM memory_atom_tags AS atom_tag
                JOIN memory_tags AS tag
                  ON CAST(tag.id AS TEXT) = atom_tag.tag_id
                WHERE atom_tag.memory_atom_id = ?
                ORDER BY atom_tag.weight DESC, tag.tag
                """,
                (atom_id,),
            ).fetchall()
        ]
        try:
            source_event_ids = [
                int(value)
                for value in json.loads(str(row["source_event_ids_json"] or "[]"))
                if str(value).isdigit() and int(value) > 0
            ]
        except (TypeError, ValueError, json.JSONDecodeError):
            source_event_ids = []
        result.append(
            {
                "id": atom_id,
                "claimKey": str(row["claim_key"] or ""),
                "canonicalText": str(row["canonical_text"] or row["text"] or ""),
                "confidence": float(row["confidence"] or 0.0),
                "sourceEventIds": source_event_ids,
                "tags": tags,
            }
        )
    return result


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_strings(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return (
        [str(item) for item in parsed if isinstance(item, str)]
        if isinstance(parsed, list)
        else []
    )


__all__ = [
    "PERSONAL_BOOK_PROJECTOR",
    "personal_memory_book_projection_status",
    "project_personal_memory_books",
]
