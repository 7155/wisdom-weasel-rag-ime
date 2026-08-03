from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Iterable

from .input_event_assembly import assemble_input_rows
from .input_quality import DISABLED_CONTEXT_SOURCES
from .memory_ingest import normalize_text
from .memory_evidence_admission import admitted_personal_evidence_sql
from .memory_tag_graph import recompute_tag_graph
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import compact_whitespace, now_ms


MEMORY_REBUILD_SCHEMA_VERSION = "rag-ime.memory-rebuild.v1"

_RIME_FRAGMENT_SOURCE = "squirrel_rime_commit_burst"
_FINALIZED_SEGMENT_SOURCE = "squirrel_input_segment"
_DISABLED_CONTEXT_SOURCES = tuple(sorted(DISABLED_CONTEXT_SOURCES))
_TRANSPORT_TAGS = {
    "group-buffer",
    "rime-commit",
    "rime-sidecar",
    "sidecar-selected",
    "source:model",
    "squirrel",
}
_PHRASE_TRANSPORT_MARKERS = (
    "group-buffer",
    "rime-commit",
    "sidecar-selected",
    "source:model",
)
_MAX_LEXICON_PHRASE_LENGTH = 18
_KEEP_UNDESCRIBED_TAGS = {
    "agent",
    "arcgis",
    "deepseek",
    "kv cache",
    "llm",
    "mlx",
    "pi",
    "pi集成",
    "rag",
    "rime",
    "ui",
    "候选排序",
    "候选框",
    "插件",
    "架构",
    "记忆",
    "机器学习",
    "模型",
    "模型训练",
    "补全",
    "上下文",
    "数据库",
    "输入法",
    "性能",
    "训练",
    "预测",
    "自然语言处理",
    "深度学习",
    "地理数据",
}
_STABLE_ATOM_MARKERS = (
    "用户要求",
    "用户希望",
    "用户强调",
    "不限制",
    "必须",
    "不能",
    "不要",
    "需要",
    "优先",
    "应当",
    "应 ",
    "需",
)


def audit_memory_database(conn: sqlite3.Connection) -> dict[str, object]:
    conn.row_factory = sqlite3.Row
    source_counts = {
        str(row["source"]): int(row["count"])
        for row in conn.execute(
            "SELECT source, COUNT(*) AS count FROM input_events GROUP BY source ORDER BY count DESC"
        ).fetchall()
    }
    active_atom_kinds = {
        str(row["kind"]): int(row["count"])
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS count FROM memory_atoms WHERE status = 'active' GROUP BY kind"
        ).fetchall()
    }
    tag_status = {
        f"{row['source']}:{row['status']}": int(row["count"])
        for row in conn.execute(
            "SELECT source, status, COUNT(*) AS count FROM memory_tags GROUP BY source, status"
        ).fetchall()
    }
    admitted = admitted_personal_evidence_sql("evidence")
    evidence_states = {
        str(row["admission_state"]): int(row["count"])
        for row in conn.execute(
            """
            SELECT admission_state, COUNT(*) AS count
            FROM agent_memory_evidence
            WHERE evidence_domain = 'personal_memory'
            GROUP BY admission_state
            """
        ).fetchall()
    }
    return {
        "schemaVersion": MEMORY_REBUILD_SCHEMA_VERSION,
        "inputEvents": _count(conn, "input_events"),
        "inputEventSources": source_counts,
        "legacyRimeFragments": source_counts.get(_RIME_FRAGMENT_SOURCE, 0),
        "finalizedInputSegments": source_counts.get(_FINALIZED_SEGMENT_SOURCE, 0),
        "deletedInputEvents": int(
            conn.execute("SELECT COUNT(*) FROM memory_state WHERE deleted = 1").fetchone()[0]
        ),
        "disabledContextSourceEvents": _disabled_source_event_count(conn),
        "activeDisabledContextSourceEvents": _disabled_source_event_count(
            conn,
            only_active=True,
        ),
        "memoryItems": _count(conn, "memory_items"),
        "approvedPhraseItems": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE kind = 'phrase' AND status = 'approved'"
            ).fetchone()[0]
        ),
        "hiddenPhraseItems": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE kind = 'phrase' AND status = 'hidden'"
            ).fetchone()[0]
        ),
        "memoryAtoms": _count(conn, "memory_atoms"),
        "activeMemoryAtoms": sum(active_atom_kinds.values()),
        "activeAtomKinds": active_atom_kinds,
        "canonicalEvidenceTotal": _count(conn, "agent_memory_evidence"),
        "personalEvidenceStates": evidence_states,
        "admittedPersonalEvidence": int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM agent_memory_evidence AS evidence
                WHERE {admitted}
                """
            ).fetchone()[0]
        ),
        "admittedEvidenceWithoutCurrentAtom": int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM agent_memory_evidence AS evidence
                WHERE {admitted}
                  AND NOT EXISTS (
                      SELECT 1
                      FROM memory_atom_evidence_links AS evidence_link
                      JOIN memory_atoms AS linked_atom
                        ON linked_atom.id = evidence_link.memory_atom_id
                      WHERE evidence_link.evidence_id = evidence.evidence_id
                        AND linked_atom.status IN ('active', 'approved')
                  )
                """
            ).fetchone()[0]
        ),
        "currentAtomsWithoutAdmittedEvidence": int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM memory_atoms AS atom
                WHERE atom.status IN ('active', 'approved')
                  AND atom.kind != 'source_event_archive'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM memory_atom_evidence_links AS evidence_link
                      JOIN agent_memory_evidence AS evidence
                        ON evidence.evidence_id = evidence_link.evidence_id
                      WHERE evidence_link.memory_atom_id = atom.id
                        AND {admitted}
                  )
                """
            ).fetchone()[0]
        ),
        "activeAtomsWithoutApp": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_atoms WHERE status = 'active' AND trim(COALESCE(scope_app, '')) = ''"
            ).fetchone()[0]
        ),
        "memoryBooks": _count(conn, "memory_books"),
        "memoryTags": _count(conn, "memory_tags"),
        "activeMemoryTags": int(
            conn.execute("SELECT COUNT(*) FROM memory_tags WHERE status = 'active'").fetchone()[0]
        ),
        "tagStatus": tag_status,
        "transportTagCount": _tag_name_count(conn, _TRANSPORT_TAGS),
        "tagEdges": _count(conn, "memory_tag_edges"),
        "retrievalDocuments": _count(conn, "memory_retrieval_docs"),
        "pendingMemoryDrafts": int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_cleanup_runs
                WHERE status = 'draft' AND run_id LIKE 'memory_book_%'
                """
            ).fetchone()[0]
        ),
    }


def rebuild_memory_database(conn: sqlite3.Connection) -> dict[str, object]:
    """Rebuild a writable database after its caller has made a backup."""

    conn.row_factory = sqlite3.Row
    before = audit_memory_database(conn)
    started_at_ms = now_ms()
    with conn:
        disabled_source_report = _quarantine_disabled_context_sources(
            conn,
            updated_at_ms=started_at_ms,
        )
        segment_report = _rebuild_legacy_input_segments(conn, updated_at_ms=started_at_ms)
        atom_report = _clean_atoms(conn, updated_at_ms=started_at_ms)
        phrase_report = _clean_phrase_items(conn, updated_at_ms=started_at_ms)
        tag_report = _clean_tags(conn, updated_at_ms=started_at_ms)
        app_report = _backfill_app_provenance(conn, updated_at_ms=started_at_ms)
        repair_report = _repair_orphan_memory_items(conn, updated_at_ms=started_at_ms)
        draft_report = _supersede_pending_memory_drafts(conn)
        graph_report = recompute_tag_graph(conn)
        retrieval_report = rebuild_retrieval_docs(conn)
    after = audit_memory_database(conn)
    return {
        "schemaVersion": MEMORY_REBUILD_SCHEMA_VERSION,
        "startedAtMs": started_at_ms,
        "finishedAtMs": now_ms(),
        "before": before,
        "after": after,
        "changes": {
            "disabledSources": disabled_source_report,
            "inputSegments": segment_report,
            "atoms": atom_report,
            "phrases": phrase_report,
            "tags": tag_report,
            "appProvenance": app_report,
            "integrityRepairs": repair_report,
            "drafts": draft_report,
            "tagGraph": graph_report,
            "retrievalDocuments": retrieval_report,
        },
    }


def preview_memory_rebuild(conn: sqlite3.Connection) -> dict[str, object]:
    """Return deterministic action counts without mutating the source DB."""

    conn.row_factory = sqlite3.Row
    rows = _active_rime_rows(conn)
    assembled = assemble_input_rows(rows)
    recovery_candidates = [item for item in assembled if _historical_recovery_candidate(item)]
    duplicate_groups = _duplicate_atom_groups(conn)
    phrase_candidates = _phrase_cleanup_candidates(conn)
    disabled_event_ids, disabled_item_ids = _disabled_source_candidates(conn)
    return {
        "schemaVersion": MEMORY_REBUILD_SCHEMA_VERSION,
        "mode": "preview",
        "audit": audit_memory_database(conn),
        "planned": {
            "disabledSourceEventsToQuarantine": len(disabled_event_ids),
            "disabledSourceMemoryItemsToHide": len(disabled_item_ids),
            "legacyFragmentsToArchive": len(rows),
            "historicalSegmentsToCreate": 0,
            "historicalRecoveryCandidatesQuarantined": len(recovery_candidates),
            "sourceArchiveAtomsToHide": int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE status = 'active' AND kind = 'source_event_archive'"
                ).fetchone()[0]
            ),
            # Semantic atoms are reviewable user memory. A deterministic
            # rebuild may flag weak candidates, but must not hide them without
            # an approved curation draft.
            "lowConfidenceTransientAtomsToHide": 0,
            "lowConfidenceProjectFactsForReview": len(_transient_atom_ids(conn)),
            "exactDuplicateAtomGroupsToMerge": len(duplicate_groups),
            "transportPhraseFragmentsToHide": len(phrase_candidates["transport"]),
            "sentenceLikePhrasesToHide": len(phrase_candidates["sentence"]),
            "legacyAutoTagsToDelete": int(
                conn.execute("SELECT COUNT(*) FROM memory_tags WHERE source = 'legacy_auto'").fetchone()[0]
            ),
            "transportTagsToDelete": _tag_name_count(conn, _TRANSPORT_TAGS),
            "genericUndescribedTagsToHide": len(_generic_tag_ids(conn)),
            "orphanMemoryItemsToRepair": int(
                conn.execute(
                    """SELECT COUNT(*) FROM memory_items item
                       LEFT JOIN input_events event ON event.id = item.source_event_id
                    WHERE item.source_event_id IS NOT NULL AND event.id IS NULL"""
                ).fetchone()[0]
            ),
            "staleDraftsToSupersede": int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM memory_cleanup_runs
                    WHERE status = 'draft' AND run_id LIKE 'memory_book_%'
                    """
                ).fetchone()[0]
            ),
        },
        "segmentSamples": [
            {
                "text": str(item.get("text") or "")[:120],
                "app": str(item.get("app") or ""),
                "sourceEventCount": int(item.get("sourceEventCount") or 0),
            }
            for item in recovery_candidates[:20]
        ],
    }


def _quarantine_disabled_context_sources(
    conn: sqlite3.Connection,
    *,
    updated_at_ms: int,
) -> dict[str, object]:
    event_ids, item_ids = _disabled_source_candidates(conn)
    conn.executemany(
        """
        INSERT INTO memory_state(event_id, deleted, updated_at_ms)
        VALUES (?, 1, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            deleted = 1,
            updated_at_ms = excluded.updated_at_ms
        """,
        ((event_id, updated_at_ms) for event_id in event_ids),
    )
    conn.executemany(
        """
        UPDATE memory_items
        SET status = 'hidden', updated_at_ms = ?
        WHERE id = ? AND status IN ('active', 'approved')
        """,
        ((updated_at_ms, item_id) for item_id in item_ids),
    )
    return {
        "sources": list(_DISABLED_CONTEXT_SOURCES),
        "eventsQuarantined": len(event_ids),
        "memoryItemsHidden": len(item_ids),
        "eventIds": event_ids[:120],
        "memoryItemIds": item_ids[:120],
        "policy": "preserved_but_not_indexed_or_injected",
    }


def _disabled_source_candidates(
    conn: sqlite3.Connection,
) -> tuple[list[int], list[int]]:
    if not _DISABLED_CONTEXT_SOURCES:
        return [], []
    placeholders = ",".join("?" for _ in _DISABLED_CONTEXT_SOURCES)
    event_ids = [
        int(row["id"])
        for row in conn.execute(
            f"""
            SELECT e.id
            FROM input_events e
            LEFT JOIN memory_state s ON s.event_id = e.id
            WHERE e.source IN ({placeholders})
              AND COALESCE(s.deleted, 0) = 0
            ORDER BY e.id
            """,
            _DISABLED_CONTEXT_SOURCES,
        ).fetchall()
    ]
    item_ids = [
        int(row["id"])
        for row in conn.execute(
            f"""
            SELECT item.id
            FROM memory_items item
            JOIN input_events event ON event.id = item.source_event_id
            WHERE event.source IN ({placeholders})
              AND item.status IN ('active', 'approved')
            ORDER BY item.id
            """,
            _DISABLED_CONTEXT_SOURCES,
        ).fetchall()
    ]
    return event_ids, item_ids


def _disabled_source_event_count(
    conn: sqlite3.Connection,
    *,
    only_active: bool = False,
) -> int:
    if not _DISABLED_CONTEXT_SOURCES:
        return 0
    placeholders = ",".join("?" for _ in _DISABLED_CONTEXT_SOURCES)
    active_clause = "AND COALESCE(s.deleted, 0) = 0" if only_active else ""
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM input_events e
            LEFT JOIN memory_state s ON s.event_id = e.id
            WHERE e.source IN ({placeholders})
              {active_clause}
            """,
            _DISABLED_CONTEXT_SOURCES,
        ).fetchone()[0]
    )


def _rebuild_legacy_input_segments(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    rows = _active_rime_rows(conn)
    assembled = assemble_input_rows(rows)
    recovery_candidates = [item for item in assembled if _historical_recovery_candidate(item)]

    event_ids = [int(row["id"]) for row in rows]
    conn.executemany(
        """
        INSERT INTO memory_state(event_id, deleted, updated_at_ms)
        VALUES (?, 1, ?)
        ON CONFLICT(event_id) DO UPDATE SET deleted = 1, updated_at_ms = excluded.updated_at_ms
        """,
        ((event_id, updated_at_ms) for event_id in event_ids),
    )
    return {
        "rawFragmentCount": len(rows),
        "assembledRecordCount": len(assembled),
        "historicalRecoveryCandidateCount": len(recovery_candidates),
        "insertedSegmentCount": 0,
        "recoveryPolicy": "quarantined_without_enter_boundary",
        "archivedFragmentCount": len(event_ids),
        "droppedNoiseRecordCount": len(assembled) - len(recovery_candidates),
    }


def _clean_atoms(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    source_archive = [
        str(row["id"])
        for row in conn.execute(
            "SELECT id FROM memory_atoms WHERE status = 'active' AND kind = 'source_event_archive'"
        ).fetchall()
    ]
    review_candidates = _transient_atom_ids(conn)
    hidden_ids = list(dict.fromkeys(source_archive))
    conn.executemany(
        "UPDATE memory_atoms SET status = 'hidden', updated_at_ms = ? WHERE id = ?",
        ((updated_at_ms, atom_id) for atom_id in hidden_ids),
    )
    merge_report = _merge_exact_duplicate_atoms(conn, updated_at_ms=updated_at_ms)
    return {
        "sourceArchiveAtomsHidden": len(source_archive),
        "lowConfidenceTransientAtomsHidden": 0,
        "lowConfidenceProjectFactsForReview": len(review_candidates),
        "reviewCandidateAtomIds": review_candidates[:80],
        "hiddenAtomIds": hidden_ids[:80],
        **merge_report,
    }


def _transient_atom_ids(conn: sqlite3.Connection) -> list[str]:
    result: list[str] = []
    rows = conn.execute(
        """
        SELECT id, COALESCE(NULLIF(canonical_text, ''), text) AS value
        FROM memory_atoms
        WHERE status = 'active' AND kind = 'project_fact' AND quality_score <= 0.65
        """
    ).fetchall()
    for row in rows:
        value = compact_whitespace(str(row["value"] or ""))
        if not any(marker in value for marker in _STABLE_ATOM_MARKERS):
            result.append(str(row["id"]))
    return result


def _merge_exact_duplicate_atoms(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    merged: list[dict[str, object]] = []
    for group in _duplicate_atom_groups(conn):
        rows = sorted(
            group,
            key=lambda row: (
                -float(row["quality_score"] or 0),
                -float(row["confidence"] or 0),
                int(row["created_at_ms"] or 0),
                str(row["id"]),
            ),
        )
        keeper = rows[0]
        keeper_id = str(keeper["id"])
        merged_ids: list[str] = []
        source_event_ids = _json_ints(keeper["source_event_ids_json"])
        source_memory_ids = _json_strings(keeper["source_memory_ids_json"])
        for duplicate in rows[1:]:
            duplicate_id = str(duplicate["id"])
            merged_ids.append(duplicate_id)
            source_event_ids.extend(
                value for value in _json_ints(duplicate["source_event_ids_json"]) if value not in source_event_ids
            )
            source_memory_ids.extend(
                value for value in _json_strings(duplicate["source_memory_ids_json"]) if value not in source_memory_ids
            )
            _move_atom_references(conn, source_id=duplicate_id, target_id=keeper_id)
            conn.execute("DELETE FROM memory_atoms WHERE id = ?", (duplicate_id,))
        conn.execute(
            """
            UPDATE memory_atoms
            SET source_event_ids_json = ?, source_memory_ids_json = ?,
                confidence = ?, quality_score = ?, updated_at_ms = ?
            WHERE id = ?
            """,
            (
                json.dumps(source_event_ids),
                json.dumps(source_memory_ids, ensure_ascii=False),
                max(float(row["confidence"] or 0) for row in rows),
                max(float(row["quality_score"] or 0) for row in rows),
                updated_at_ms,
                keeper_id,
            ),
        )
        merged.append({"keeperId": keeper_id, "mergedIds": merged_ids})
    return {"exactDuplicateGroupsMerged": len(merged), "exactDuplicateAtomsRemoved": sum(len(item["mergedIds"]) for item in merged), "merges": merged}


def _move_atom_references(conn: sqlite3.Connection, *, source_id: str, target_id: str) -> None:
    conn.execute(
        """
        INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
        SELECT ?, tag_id, weight, source FROM memory_atom_tags WHERE memory_atom_id = ?
        ON CONFLICT(memory_atom_id, tag_id) DO UPDATE SET weight = MAX(weight, excluded.weight)
        """,
        (target_id, source_id),
    )
    conn.execute("DELETE FROM memory_atom_tags WHERE memory_atom_id = ?", (source_id,))
    conn.execute("UPDATE memory_aliases SET memory_atom_id = ? WHERE memory_atom_id = ?", (target_id, source_id))
    conn.execute(
        """
        INSERT INTO memory_semantic_group_members(group_id, member_type, member_id, weight, source, updated_at_ms)
        SELECT group_id, member_type, ?, weight, source, updated_at_ms
        FROM memory_semantic_group_members WHERE member_type = 'atom' AND member_id = ?
        ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET weight = MAX(weight, excluded.weight)
        """,
        (target_id, source_id),
    )
    conn.execute(
        "DELETE FROM memory_semantic_group_members WHERE member_type = 'atom' AND member_id = ?",
        (source_id,),
    )
    conn.execute("UPDATE memory_supersessions SET old_memory_id = ? WHERE old_memory_id = ?", (target_id, source_id))
    conn.execute("UPDATE memory_supersessions SET new_memory_id = ? WHERE new_memory_id = ?", (target_id, source_id))
    for row in conn.execute("SELECT book_id, memory_atom_ids_json FROM memory_books").fetchall():
        atom_ids = _json_strings(row["memory_atom_ids_json"])
        if source_id not in atom_ids:
            continue
        updated = list(dict.fromkeys(target_id if value == source_id else value for value in atom_ids))
        conn.execute(
            "UPDATE memory_books SET memory_atom_ids_json = ? WHERE book_id = ?",
            (json.dumps(updated, ensure_ascii=False), str(row["book_id"])),
        )


def _duplicate_atom_groups(conn: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    groups: dict[tuple[str, str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute(
        """
        SELECT id, kind, text, canonical_text, source_event_ids_json, source_memory_ids_json,
               scope_app, scope_project, confidence, quality_score, created_at_ms
        FROM memory_atoms WHERE status = 'active'
        """
    ).fetchall():
        value = normalize_text(str(row["canonical_text"] or row["text"] or ""))
        if not value:
            continue
        key = (
            str(row["kind"] or ""),
            value,
            compact_whitespace(str(row["scope_project"] or "")),
            compact_whitespace(str(row["scope_app"] or "")),
        )
        groups[key].append(row)
    return [rows for rows in groups.values() if len(rows) > 1]


def _clean_phrase_items(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    candidates = _phrase_cleanup_candidates(conn)
    hidden_ids = list(dict.fromkeys([*candidates["transport"], *candidates["sentence"]]))
    conn.executemany(
        "UPDATE memory_items SET status = 'hidden', updated_at_ms = ? WHERE id = ?",
        ((updated_at_ms, item_id) for item_id in hidden_ids),
    )
    return {
        "transportFragmentsHidden": len(candidates["transport"]),
        "sentenceLikePhrasesHidden": len(candidates["sentence"]),
        "hiddenPhraseItemIds": hidden_ids[:120],
    }


def _phrase_cleanup_candidates(conn: sqlite3.Connection) -> dict[str, list[int]]:
    transport: list[int] = []
    sentence: list[int] = []
    rows = conn.execute(
        """
        SELECT id, text, metadata_json
        FROM memory_items
        WHERE kind = 'phrase' AND status = 'approved'
        """
    ).fetchall()
    for row in rows:
        item_id = int(row["id"])
        text = compact_whitespace(str(row["text"] or ""))
        metadata = str(row["metadata_json"] or "")
        if any(marker in metadata for marker in _PHRASE_TRANSPORT_MARKERS):
            transport.append(item_id)
        elif len(text) > _MAX_LEXICON_PHRASE_LENGTH:
            sentence.append(item_id)
    return {"transport": transport, "sentence": sentence}


def _clean_tags(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    legacy_ids = [
        int(row["id"])
        for row in conn.execute("SELECT id FROM memory_tags WHERE source = 'legacy_auto'").fetchall()
    ]
    transport_ids = [
        int(row["id"])
        for row in conn.execute("SELECT id, tag FROM memory_tags").fetchall()
        if compact_whitespace(str(row["tag"] or "")).casefold() in _TRANSPORT_TAGS
    ]
    delete_ids = list(dict.fromkeys([*legacy_ids, *transport_ids]))
    _delete_tags(conn, delete_ids)

    generic_ids = _generic_tag_ids(conn)
    conn.executemany(
        "UPDATE memory_tags SET status = 'hidden', updated_at_ms = ? WHERE id = ?",
        ((updated_at_ms, tag_id) for tag_id in generic_ids),
    )
    if generic_ids:
        placeholders = ",".join("?" for _ in generic_ids)
        conn.execute(
            f"DELETE FROM memory_tag_edges WHERE src_tag_id IN ({placeholders}) OR dst_tag_id IN ({placeholders})",
            (*generic_ids, *generic_ids),
        )
    return {
        "legacyAutoTagsDeleted": len(legacy_ids),
        "transportTagsDeleted": len(set(transport_ids) - set(legacy_ids)),
        "genericUndescribedTagsHidden": len(generic_ids),
        "hiddenGenericTagIds": generic_ids[:120],
    }


def _generic_tag_ids(conn: sqlite3.Connection) -> list[int]:
    result: list[int] = []
    for row in conn.execute(
        """
        SELECT id, tag, quality_score FROM memory_tags
        WHERE source = 'dsv4' AND status = 'active' AND trim(description) = ''
        """
    ).fetchall():
        tag = compact_whitespace(str(row["tag"] or ""))
        if tag.casefold() in _TRANSPORT_TAGS:
            continue
        if tag.casefold() in _KEEP_UNDESCRIBED_TAGS:
            continue
        result.append(int(row["id"]))
    return result


def _delete_tags(conn: sqlite3.Connection, tag_ids: list[int]) -> None:
    if not tag_ids:
        return
    placeholders = ",".join("?" for _ in tag_ids)
    conn.execute(
        f"DELETE FROM memory_tag_edges WHERE src_tag_id IN ({placeholders}) OR dst_tag_id IN ({placeholders})",
        (*tag_ids, *tag_ids),
    )
    conn.execute(f"DELETE FROM memory_item_tags WHERE tag_id IN ({placeholders})", tag_ids)
    conn.execute(f"DELETE FROM memory_atom_tags WHERE CAST(tag_id AS INTEGER) IN ({placeholders})", tag_ids)
    conn.execute(f"DELETE FROM memory_tag_profiles WHERE tag_id IN ({placeholders})", tag_ids)
    conn.execute(
        f"DELETE FROM memory_semantic_group_members WHERE member_type = 'tag' AND CAST(member_id AS INTEGER) IN ({placeholders})",
        tag_ids,
    )
    conn.execute(f"DELETE FROM memory_tags WHERE id IN ({placeholders})", tag_ids)


def _backfill_app_provenance(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    atom_updates = 0
    for row in conn.execute(
        "SELECT id, scope_app, source_event_ids_json FROM memory_atoms"
    ).fetchall():
        current = _normalize_app(str(row["scope_app"] or ""))
        derived = _single_source_app(conn, _json_ints(row["source_event_ids_json"]))
        app = derived if current in {"", "squirrel"} and derived not in {"", "squirrel"} else current
        if not app or app == compact_whitespace(str(row["scope_app"] or "")):
            continue
        conn.execute(
            "UPDATE memory_atoms SET scope_app = ?, updated_at_ms = ? WHERE id = ?",
            (app, updated_at_ms, str(row["id"])),
        )
        atom_updates += 1

    book_updates = 0
    for row in conn.execute(
        "SELECT book_id, app, source_event_ids_json FROM memory_books"
    ).fetchall():
        current = _normalize_app(str(row["app"] or ""))
        derived = _single_source_app(conn, _json_ints(row["source_event_ids_json"]))
        app = derived if current in {"", "squirrel"} and derived not in {"", "squirrel"} else current
        if not app or app == compact_whitespace(str(row["app"] or "")):
            continue
        conn.execute(
            "UPDATE memory_books SET app = ?, updated_at_ms = ? WHERE book_id = ?",
            (app, updated_at_ms, str(row["book_id"])),
        )
        book_updates += 1
    return {"atomsBackfilled": atom_updates, "booksBackfilled": book_updates}


def _repair_orphan_memory_items(conn: sqlite3.Connection, *, updated_at_ms: int) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT item.id, item.memory_id, item.kind, item.status
        FROM memory_items item
        LEFT JOIN input_events event ON event.id = item.source_event_id
        WHERE item.source_event_id IS NOT NULL AND event.id IS NULL
        """
    ).fetchall()
    deleted_ids: list[int] = []
    detached_ids: list[int] = []
    for row in rows:
        item_id = int(row["id"])
        if str(row["status"] or "") == "hidden" or str(row["kind"] or "") == "raw_event":
            conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            deleted_ids.append(item_id)
        else:
            conn.execute(
                "UPDATE memory_items SET source_event_id = NULL, updated_at_ms = ? WHERE id = ?",
                (updated_at_ms, item_id),
            )
            detached_ids.append(item_id)
    return {
        "orphanMemoryItemsDeleted": len(deleted_ids),
        "orphanMemoryItemsDetached": len(detached_ids),
        "deletedItemIds": deleted_ids,
        "detachedItemIds": detached_ids,
    }


def _supersede_pending_memory_drafts(conn: sqlite3.Connection) -> dict[str, object]:
    """Invalidate review snapshots made against the pre-rebuild catalog."""

    run_ids = [
        str(row["run_id"])
        for row in conn.execute(
            """
            SELECT run_id
            FROM memory_cleanup_runs
            WHERE status = 'draft' AND run_id LIKE 'memory_book_%'
            ORDER BY created_at_ms ASC, run_id ASC
            """
        ).fetchall()
    ]
    if not run_ids:
        return {"supersededDraftCount": 0, "supersededRunIds": []}
    placeholders = ",".join("?" for _ in run_ids)
    conn.execute(
        f"""
        UPDATE memory_cleanup_diffs
        SET status = 'rejected'
        WHERE run_id IN ({placeholders})
          AND status IN ('pending', 'approved')
        """,
        run_ids,
    )
    conn.execute(
        f"""
        UPDATE memory_cleanup_runs
        SET status = 'superseded'
        WHERE run_id IN ({placeholders})
        """,
        run_ids,
    )
    conn.execute(
        """
        UPDATE memory_compile_state
        SET last_drafted_event_id = 0,
            last_draft_ms = 0,
            last_draft_bundle_hash = '',
            last_draft_run_id = ''
        WHERE last_draft_run_id != ''
        """
    )
    return {
        "supersededDraftCount": len(run_ids),
        "supersededRunIds": run_ids,
    }


def _single_source_app(conn: sqlite3.Connection, event_ids: list[int]) -> str:
    if not event_ids:
        return ""
    placeholders = ",".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT app, COUNT(*) AS count FROM input_events
        WHERE id IN ({placeholders}) AND trim(app) != ''
        GROUP BY app ORDER BY count DESC, app ASC
        """,
        event_ids,
    ).fetchall()
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if app := _normalize_app(str(row["app"] or "")):
            counts[app] += int(row["count"] or 0)
    return next(iter(counts)) if len(counts) == 1 else ""


def _normalize_app(value: str) -> str:
    app = compact_whitespace(value)
    return "com.openai.codex" if app.casefold() == "codex" else app


def _active_rime_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.id, e.created_at_ms, e.source, e.committed_text, e.recent_context,
               e.preedit, e.app, e.project, e.context_group_id, e.context_group_level,
               e.tags_json
        FROM input_events e
        LEFT JOIN memory_state s ON s.event_id = e.id
        WHERE e.source = ? AND COALESCE(s.deleted, 0) = 0
        ORDER BY e.id ASC
        """,
        (_RIME_FRAGMENT_SOURCE,),
    ).fetchall()


def _historical_recovery_candidate(item: dict[str, object]) -> bool:
    text = compact_whitespace(str(item.get("text") or ""))
    return len(text) >= 20 and text.endswith(("。", "！", "？", ".", "!", "?"))


def _tag_name_count(conn: sqlite3.Connection, names: Iterable[str]) -> int:
    normalized = {compact_whitespace(name).casefold() for name in names}
    return sum(
        1
        for row in conn.execute("SELECT tag FROM memory_tags").fetchall()
        if compact_whitespace(str(row["tag"] or "")).casefold() in normalized
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _json_ints(raw: object) -> list[int]:
    values = _json_values(raw)
    result: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _json_strings(raw: object) -> list[str]:
    return list(
        dict.fromkeys(
            compact_whitespace(str(value))
            for value in _json_values(raw)
            if compact_whitespace(str(value))
        )
    )


def _json_values(raw: object) -> list[object]:
    try:
        payload = json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []
