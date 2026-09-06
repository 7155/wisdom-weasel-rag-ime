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


def _projector_metadata_strings(value: object) -> list[str]:
    values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    return [
        compact_whitespace(str(item))
        for item in values
        if item is not None and compact_whitespace(str(item))
    ]


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
    effective_desired, redirected_source_ids, redirected_target_ids = (
        _effective_projector_books(desired, existing, atoms)
    )
    upserted: list[str] = []
    guarded: list[str] = []
    for book_id, book in effective_desired.items():
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
        topic_aliases = [
            *_projector_metadata_strings(previous_metadata.get("topicAliases")),
            *_projector_metadata_strings(previous_metadata.get("aliases")),
            *(book.get("aliases") or []),
        ]
        merged_source_book_ids = [
            *_projector_metadata_strings(previous_metadata.get("mergedSourceBookIds")),
            *(book.get("mergedSourceBookIds") or []),
        ]
        metadata = {
            **previous_metadata,
            "projectionOwner": PERSONAL_BOOK_PROJECTOR,
            "membershipStrategy": "validated_topic_tag",
            "stableAnchor": str(book["tag"]),
            "memberCount": len(book["memberIds"]),
            "projectedAtMs": timestamp,
        }
        if topic_aliases:
            metadata["topicAliases"] = list(dict.fromkeys(topic_aliases))[:64]
        if merged_source_book_ids:
            metadata["mergedSourceBookIds"] = list(
                dict.fromkeys(merged_source_book_ids)
            )
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
                json.dumps(
                    book.get("tags") or [book["tag"]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
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
        if (
            book_id in effective_desired
            or book_id in redirected_source_ids
            or str(row["status"] or "") == "archived"
        ):
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
        for book_id, book in effective_desired.items()
        if book_id not in guarded
        for atom_id in book["memberIds"]
    }
    for target_id in redirected_target_ids:
        target_row = existing.get(target_id)
        if target_row is None or str(target_row["status"] or "") not in {"active", "approved"}:
            continue
        booked_atom_ids.update(_json_strings(target_row["memory_atom_ids_json"]))
    return {
        "schemaVersion": "rag-ime.personal-memory-book-projection.v1",
        "ok": True,
        "projectionOwner": PERSONAL_BOOK_PROJECTOR,
        "currentAtomCount": len(atoms),
        "activeBookCount": len(effective_desired) - len(guarded),
        "unbookedAtomCount": len(
            {str(atom["id"]) for atom in atoms} - booked_atom_ids
        ),
        "upsertedBookIds": upserted,
        "archivedBookIds": archived,
        "guardedBookIds": guarded,
    }


def _effective_projector_books(
    desired: dict[str, dict[str, object]],
    existing: dict[str, sqlite3.Row],
    atoms: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], set[str], set[str]]:
    """Fold redirected projector groups into their live target Book.

    A superseded source is a redirect, not an exclusion rule: its current
    desired members and any members persisted before the merge both belong to
    the target.  Rebuilding the summary from the current Atom set prevents a
    retracted or superseded fact from returning through an old Book snapshot.
    """

    def unique(values: list[object]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = compact_whitespace(str(value or ""))
            key = normalize_text(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def resolve(book_id: str) -> str:
        current = compact_whitespace(book_id)
        visited: set[str] = set()
        while current in existing:
            if current in visited:
                return ""
            visited.add(current)
            row = existing[current]
            if str(row["status"] or "") != "superseded":
                return current
            target = compact_whitespace(
                str(_json_object(row["metadata_json"]).get("supersededByBookId") or "")
            )
            if not target or target not in existing:
                return ""
            current = target
        return ""

    redirects: dict[str, str] = {}
    for book_id in existing:
        if str(existing[book_id]["status"] or "") != "superseded":
            continue
        target = resolve(book_id)
        if target and target != book_id:
            redirects[book_id] = target
    redirected_source_ids = set(redirects)
    redirected_target_ids = set(redirects.values())
    current_by_id = {
        str(atom["id"]): atom
        for atom in atoms
        if compact_whitespace(str(atom.get("id") or ""))
    }

    def row_book(row: sqlite3.Row) -> dict[str, object]:
        metadata = _json_object(row["metadata_json"])
        member_ids = [
            atom_id
            for atom_id in _json_strings(row["memory_atom_ids_json"])
            if atom_id in current_by_id
        ]
        tags = _json_strings(row["tags_json"])
        aliases = [
            *_projector_metadata_strings(metadata.get("topicAliases")),
            *_projector_metadata_strings(metadata.get("aliases")),
            str(row["title"] or ""),
            str(row["book_key"] or ""),
        ]
        return {
            "bookId": str(row["book_id"] or ""),
            "bookKey": str(row["book_key"] or ""),
            "title": str(row["title"] or ""),
            "tag": tags[0] if tags else compact_whitespace(str(metadata.get("stableAnchor") or row["title"] or "")),
            "tags": tags,
            "aliases": unique(aliases),
            "memberIds": member_ids,
            "sourceEventIds": [],
            "confidence": float(row["confidence"] or 0.0),
            "mergedSourceBookIds": _projector_metadata_strings(metadata.get("mergedSourceBookIds")),
        }

    def merge_book(target: dict[str, object], incoming: Mapping[str, object]) -> None:
        target["memberIds"] = list(
            dict.fromkeys(
                [
                    *[str(value) for value in target.get("memberIds") or []],
                    *[str(value) for value in incoming.get("memberIds") or []],
                ]
            )
        )
        target["tags"] = unique(
            [*(target.get("tags") or []), *(incoming.get("tags") or []), incoming.get("tag")]
        )
        target["aliases"] = unique(
            [*(target.get("aliases") or []), *(incoming.get("aliases") or []), incoming.get("title"), incoming.get("bookKey")]
        )
        target["mergedSourceBookIds"] = unique(
            [
                *(target.get("mergedSourceBookIds") or []),
                *(incoming.get("mergedSourceBookIds") or []),
            ]
        )

    effective: dict[str, dict[str, object]] = {}
    # Seed redirected targets first so their stable title/key/anchor always win
    # over a source group's display label.
    for target_id in sorted(redirected_target_ids):
        row = existing.get(target_id)
        if row is not None:
            effective[target_id] = row_book(row)

    for book_id, book in desired.items():
        target_id = redirects.get(book_id, book_id)
        if target_id in redirected_source_ids or target_id not in existing and book_id in redirects:
            target_id = book_id
        incoming = dict(book)
        incoming["tags"] = [book.get("tag")]
        incoming["aliases"] = [book.get("tag"), book.get("title"), book.get("bookKey")]
        incoming["mergedSourceBookIds"] = []
        if target_id not in effective:
            effective[target_id] = incoming
        else:
            merge_book(effective[target_id], incoming)

    # Source rows may contain members that the desired tag projection no longer
    # exposes.  They remain valid merge members until their Atom leaves the
    # current governed catalog.
    for source_id, target_id in redirects.items():
        source = existing.get(source_id)
        if source is None:
            continue
        source_book = row_book(source)
        target_book = effective.setdefault(target_id, row_book(existing[target_id]))
        merge_book(target_book, source_book)
        target_book["mergedSourceBookIds"] = unique(
            [*(target_book.get("mergedSourceBookIds") or []), source_id]
        )

    rebuilt: dict[str, dict[str, object]] = {}
    for book_id, book in effective.items():
        member_ids = [
            atom_id
            for atom_id in dict.fromkeys(str(value) for value in book.get("memberIds") or [])
            if atom_id in current_by_id
        ]
        if len(member_ids) < 2:
            continue
        member_atoms = [current_by_id[atom_id] for atom_id in member_ids]
        book["memberIds"] = member_ids
        book["summary"] = "；".join(
            compact_whitespace(str(atom.get("canonicalText") or ""))
            for atom in member_atoms
            if compact_whitespace(str(atom.get("canonicalText") or ""))
        )[:2400]
        book["sourceEventIds"] = sorted(
            {
                int(event_id)
                for atom in member_atoms
                for event_id in atom.get("sourceEventIds") or []
                if str(event_id).isdigit() and int(event_id) > 0
            }
        )
        book["confidence"] = min(
            (float(atom.get("confidence") or 0.0) for atom in member_atoms),
            default=0.0,
        )
        book["tags"] = unique([*(book.get("tags") or []), book.get("tag")])
        book["aliases"] = unique(
            [*(book.get("aliases") or []), book.get("title"), book.get("bookKey")]
        )
        rebuilt[book_id] = book
    return rebuilt, redirected_source_ids, redirected_target_ids


def personal_memory_book_projection_status(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Report projection drift without mutating Books or exposing Atom text."""

    atoms = _current_personal_atoms(conn)
    desired = _desired_books(atoms)
    rows = conn.execute(
        """
        SELECT book_id, book_key, title, tags_json, confidence,
               status, archive_reason, memory_atom_ids_json, metadata_json
        FROM memory_books
        WHERE json_valid(metadata_json)
          AND json_extract(metadata_json, '$.projectionOwner') = ?
        ORDER BY book_id
        """,
        (PERSONAL_BOOK_PROJECTOR,),
    ).fetchall()
    rows_by_id = {str(row["book_id"]): row for row in rows}
    effective_books, redirected_source_ids, redirected_target_ids = (
        _effective_projector_books(desired, rows_by_id, atoms)
    )
    active = {
        str(row["book_id"]): row
        for row in rows
        if str(row["status"] or "") in {"active", "approved"}
    }
    guarded = {
        str(row["book_id"])
        for row in rows
        if str(row["status"] or "") == "archived"
        and str(row["archive_reason"] or "") not in _SYSTEM_ARCHIVE_REASONS
        and str(row["book_id"]) in effective_books
    }
    effective_desired = {
        book_id: book
        for book_id, book in effective_books.items()
        if book_id not in guarded
    }
    protected_targets = redirected_target_ids.intersection(rows_by_id)
    missing = set(effective_desired) - set(active)
    stale = set(active) - set(effective_desired) - protected_targets
    membership_mismatches = {
        book_id
        for book_id in set(effective_desired).intersection(active)
        if set(_json_strings(active[book_id]["memory_atom_ids_json"]))
        != set(effective_desired[book_id]["memberIds"])
    }
    booked_atom_ids = {
        atom_id
        for book_id, book in effective_desired.items()
        if book_id not in guarded
        for atom_id in book["memberIds"]
    }
    for target_id in protected_targets:
        target_row = rows_by_id.get(target_id)
        if target_row is not None and str(target_row["status"] or "") in {"active", "approved"}:
            booked_atom_ids.update(_json_strings(target_row["memory_atom_ids_json"]))
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
