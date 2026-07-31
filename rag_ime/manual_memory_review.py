from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from .owner_memory_curation import _coalesce_owner_inputs
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace, now_ms


MANUAL_MEMORY_EXPORT_SCHEMA_VERSION = "rag-ime.manual-memory-review-export.v1"
MANUAL_MEMORY_PART_SCHEMA_VERSION = "rag-ime.manual-memory-review-part.v1"
MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION = "rag-ime.manual-memory-review-manifest.v1"

_DECISIONS = frozenset({"remember", "not_for_memory"})
# The application path implements a full reviewed replacement.  Keeping or
# rewriting an existing row in place would need different lineage semantics,
# so fail closed instead of silently treating those actions as archive.
_ATOM_ACTIONS = frozenset({"archive", "supersede"})
_BOOK_ACTIONS = frozenset({"archive"})
_PHRASE_ACTIONS = frozenset({"keep", "archive"})
_FORBIDDEN_DERIVED_TEXT_MARKERS = (
    "user_message",
    "assistant_message",
    "[敏感内容已隐藏]",
    "[REDACTED:",
    "请调用 memory",
    "curation_prepare",
    "runId:",
)


class ManualMemoryReviewError(ValueError):
    pass


def export_manual_memory_review(
    conn: sqlite3.Connection,
    *,
    project: str,
    timezone_name: str = "Asia/Shanghai",
) -> dict[str, object]:
    """Build a local-only review export without changing SQLite state."""

    conn.row_factory = sqlite3.Row
    timezone = ZoneInfo(timezone_name)
    normalized_project = compact_whitespace(project)
    rows = conn.execute(
        """
        SELECT s.*, e.committed_text, e.source AS event_source,
               e.recent_context, e.app, e.project AS event_project,
               e.context_group_id, e.context_group_level, e.tags_json
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        WHERE s.status = 'active'
          AND (? = '' OR e.project = ? OR e.project = '')
        ORDER BY s.owner_kind, s.owner_id, s.created_at_ms, s.source_id
        """,
        (normalized_project, normalized_project),
    ).fetchall()
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        created_at_ms = int(row["created_at_ms"] or 0)
        local_date = datetime.fromtimestamp(
            created_at_ms / 1000,
            timezone,
        ).date().isoformat()
        grouped[(str(row["owner_kind"]), str(row["owner_id"]), local_date)].append(
            _raw_source(row)
        )

    inputs: list[dict[str, object]] = []
    for (owner_kind, owner_id, local_date), raw_inputs in grouped.items():
        for item in _coalesce_owner_inputs(raw_inputs):
            text = compact_whitespace(str(item.get("text") or ""))
            source_ids = _unique_strings(item.get("sourceIds"))
            event_ids = _positive_ints(item.get("sourceEventIds"))
            sensitive = contains_sensitive_content(text)
            inputs.append(
                {
                    "inputId": _logical_input_id(
                        source_ids,
                        created_at_ms=int(item.get("createdAtMs") or 0),
                    ),
                    "ownerKind": owner_kind,
                    "ownerId": owner_id,
                    "date": local_date,
                    "createdAtMs": int(item.get("createdAtMs") or 0),
                    "sourceIds": source_ids,
                    "sourceEventIds": event_ids,
                    "sourceKind": str(item.get("sourceKind") or ""),
                    "trustClass": str(item.get("trustClass") or ""),
                    "source": str(item.get("source") or ""),
                    "app": str(item.get("app") or ""),
                    "currentDisposition": str(item.get("disposition") or ""),
                    "sensitive": sensitive,
                    "text": "[REDACTED: sensitive input]" if sensitive else text,
                }
            )

    atoms = [_atom_export(row) for row in conn.execute(
        """
        SELECT * FROM memory_atoms
        WHERE scope_project = ?
        ORDER BY status, owner_kind, owner_id, updated_at_ms DESC, id
        """,
        (normalized_project,),
    ).fetchall()]
    books = [_book_export(row) for row in conn.execute(
        """
        SELECT * FROM memory_books
        WHERE project = ?
        ORDER BY status, owner_kind, owner_id, updated_at_ms DESC, book_id
        """,
        (normalized_project,),
    ).fetchall()]
    phrases = [_phrase_export(row) for row in conn.execute(
        """SELECT * FROM memory_items
           WHERE kind = 'phrase' AND project = ?
           ORDER BY status, updated_at_ms DESC, id""",
        (normalized_project,),
    ).fetchall()]
    fingerprint = memory_review_evidence_fingerprint(
        conn,
        project=normalized_project,
    )
    catalog_fingerprint = memory_review_catalog_fingerprint(
        conn,
        project=normalized_project,
    )
    governance_fingerprint = memory_review_governance_fingerprint(
        conn,
        project=normalized_project,
    )
    return {
        "schemaVersion": MANUAL_MEMORY_EXPORT_SCHEMA_VERSION,
        "project": normalized_project,
        "timezone": timezone_name,
        "exportedAtMs": now_ms(),
        "evidenceFingerprint": fingerprint,
        "memoryCatalogFingerprint": catalog_fingerprint,
        "governanceFingerprint": governance_fingerprint,
        "counts": {
            "physicalSources": len(rows),
            "logicalInputs": len(inputs),
            "sensitiveLogicalInputs": sum(bool(item["sensitive"]) for item in inputs),
            "atoms": len(atoms),
            "books": len(books),
            "phrases": len(phrases),
        },
        "inputs": inputs,
        "existingAtoms": atoms,
        "existingBooks": books,
        "existingPhrases": phrases,
    }


def memory_review_evidence_fingerprint(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> str:
    """Hash immutable evidence and source ownership, independent of DB layout."""

    normalized_project = compact_whitespace(project)
    digest = hashlib.sha256()
    rows = conn.execute(
        """
        SELECT s.source_id, s.input_event_id, s.owner_kind, s.owner_id,
               s.source_kind, s.trust_class, s.status, s.created_at_ms,
               s.source_revision, s.canonical_text_sha256,
               s.disposition, s.disposition_reason,
               s.disposition_updated_at_ms, s.processed_at_ms,
               s.curation_run_id, s.coverage_start_entry_id,
               s.coverage_end_entry_id, s.expires_at_ms, s.metadata_json,
               e.created_at_ms AS event_created_at_ms, e.source,
               e.committed_text, e.app, e.project, e.tags_json
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        WHERE s.status = 'active'
          AND (? = '' OR e.project = ? OR e.project = '')
        ORDER BY s.owner_kind, s.owner_id, s.created_at_ms, s.source_id
        """,
        (normalized_project, normalized_project),
    ).fetchall()
    for row in rows:
        payload = [
            row["source_id"],
            row["input_event_id"],
            row["owner_kind"],
            row["owner_id"],
            row["source_kind"],
            row["trust_class"],
            row["status"],
            row["created_at_ms"],
            row["source_revision"],
            row["canonical_text_sha256"],
            row["disposition"],
            row["disposition_reason"],
            row["disposition_updated_at_ms"],
            row["processed_at_ms"],
            row["curation_run_id"],
            row["coverage_start_entry_id"],
            row["coverage_end_entry_id"],
            row["expires_at_ms"],
            row["metadata_json"],
            row["event_created_at_ms"],
            row["source"],
            row["committed_text"],
            row["app"],
            row["project"],
            row["tags_json"],
        ]
        digest.update(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def memory_review_catalog_fingerprint(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> str:
    """Hash the derived catalog that the review intends to replace."""

    digest = hashlib.sha256()
    normalized_project = compact_whitespace(project)
    for table, key, project_column in (
        ("memory_atoms", "id", "scope_project"),
        ("memory_books", "book_id", "project"),
    ):
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
        for row in conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} "
            f"WHERE {project_column} = ? ORDER BY {key}",
            (normalized_project,),
        ).fetchall():
            digest.update(table.encode("ascii"))
            digest.update(b"\0")
            digest.update(
                json.dumps(
                    [row[column] for column in columns],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    phrase_columns = [
        str(row[1]) for row in conn.execute("PRAGMA table_info(memory_items)")
    ]
    for row in conn.execute(
        f"SELECT {', '.join(phrase_columns)} FROM memory_items "
        "WHERE kind = 'phrase' AND project = ? ORDER BY id",
        (normalized_project,),
    ).fetchall():
        digest.update(b"memory_items_phrase\0")
        digest.update(
            json.dumps(
                [row[column] for column in phrase_columns],
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def memory_review_governance_fingerprint(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> str:
    """Hash mutable governance state touched by a manual catalog replacement."""

    normalized_project = compact_whitespace(project)
    digest = hashlib.sha256()
    queries = (
        (
            "daily_activity_timelines",
            "SELECT * FROM daily_activity_timelines WHERE project = ? ORDER BY timeline_id",
            (normalized_project,),
        ),
        (
            "memory_semantic_groups",
            "SELECT * FROM memory_semantic_groups WHERE project = ? ORDER BY group_id",
            (normalized_project,),
        ),
        (
            "memory_semantic_group_members",
            """SELECT member.* FROM memory_semantic_group_members AS member
               JOIN memory_semantic_groups AS semantic_group
                 ON semantic_group.group_id = member.group_id
               WHERE semantic_group.project = ?
               ORDER BY member.group_id, member.member_type, member.member_id""",
            (normalized_project,),
        ),
        (
            "memory_governance_proposals",
            "SELECT * FROM memory_governance_proposals WHERE project = ? ORDER BY proposal_id",
            (normalized_project,),
        ),
        (
            "memory_compile_state",
            "SELECT * FROM memory_compile_state WHERE project = ? ORDER BY project",
            (normalized_project,),
        ),
        (
            "memory_curation_cursors",
            """SELECT * FROM memory_curation_cursors
               WHERE project = ? ORDER BY owner_kind, owner_id, lane""",
            (normalized_project,),
        ),
        # Tags and their graph are shared derived state.  The manual apply path
        # can add tags and recompute this graph, so concurrent changes must also
        # invalidate the review.
        ("memory_tags", "SELECT * FROM memory_tags ORDER BY id", ()),
        (
            "memory_tag_edges",
            "SELECT * FROM memory_tag_edges ORDER BY src_tag_id, dst_tag_id, edge_type",
            (),
        ),
    )
    for table, query, params in queries:
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
        for row in conn.execute(query, params).fetchall():
            digest.update(table.encode("ascii"))
            digest.update(b"\0")
            digest.update(
                json.dumps(
                    [row[column] for column in columns],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def assemble_manual_memory_manifest(
    export: Mapping[str, object],
    *,
    parts: Iterable[Mapping[str, object]],
    existing_audit: Mapping[str, object],
    reviewer_id: str = "codex-root",
) -> dict[str, object]:
    if str(export.get("schemaVersion") or "") != MANUAL_MEMORY_EXPORT_SCHEMA_VERSION:
        raise ManualMemoryReviewError("unsupported manual memory export schema")
    decisions: list[dict[str, object]] = []
    atoms: list[dict[str, object]] = []
    books: list[dict[str, object]] = []
    timelines: list[dict[str, object]] = []
    supersedes: list[dict[str, object]] = []
    reviewers: list[dict[str, object]] = []
    for part in parts:
        decisions.extend(_dicts(part.get("decisions")))
        atoms.extend(_normalize_part_atom(item) for item in _dicts(part.get("atoms")))
        books.extend(_dicts(part.get("books")))
        timelines.extend(_dicts(part.get("timelines")))
        supersedes.extend(_dicts(part.get("supersedes")))
        reviewer = part.get("reviewer")
        reviewers.append(
            dict(reviewer)
            if isinstance(reviewer, Mapping)
            else {"id": compact_whitespace(str(reviewer or "unknown"))}
        )
    normalized_audit = dict(existing_audit)
    normalized_audit["atoms"] = _dicts(
        existing_audit.get("atoms") or existing_audit.get("existingAtoms")
    )
    normalized_audit["books"] = _dicts(
        existing_audit.get("books") or existing_audit.get("existingBooks")
    )
    phrase_audit = _dicts(
        existing_audit.get("existingPhraseAudit")
        or existing_audit.get("phrases")
        or existing_audit.get("existingPhrases")
    )
    manifest: dict[str, object] = {
        "schemaVersion": MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION,
        "project": compact_whitespace(str(export.get("project") or "")),
        "timezone": str(export.get("timezone") or "Asia/Shanghai"),
        "evidenceFingerprint": str(export.get("evidenceFingerprint") or ""),
        "memoryCatalogFingerprint": str(
            export.get("memoryCatalogFingerprint") or ""
        ),
        "governanceFingerprint": str(export.get("governanceFingerprint") or ""),
        "exportedAtMs": int(export.get("exportedAtMs") or 0),
        "reviewedAtMs": now_ms(),
        "reviewer": {
            "kind": "codex",
            "id": compact_whitespace(reviewer_id) or "codex-root",
            "parts": reviewers,
        },
        "decisions": decisions,
        "atoms": atoms,
        "books": books,
        "timelines": timelines,
        "supersedes": supersedes,
        "existingMemoryAudit": normalized_audit,
        "existingPhraseAudit": phrase_audit,
    }
    validation = validate_manual_memory_manifest(export, manifest=manifest)
    if not bool(validation["ok"]):
        raise ManualMemoryReviewError(
            "manual memory review is incomplete: "
            + "; ".join(str(value) for value in validation["errors"][:20])
        )
    manifest["validation"] = validation
    return manifest


def validate_manual_memory_manifest(
    export: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    errors: list[str] = []
    if str(manifest.get("schemaVersion") or "") != MANUAL_MEMORY_MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported_manifest_schema")
    if str(manifest.get("evidenceFingerprint") or "") != str(
        export.get("evidenceFingerprint") or ""
    ):
        errors.append("evidence_fingerprint_mismatch")
    if not compact_whitespace(str(export.get("memoryCatalogFingerprint") or "")):
        errors.append("missing_memory_catalog_fingerprint")
    elif str(manifest.get("memoryCatalogFingerprint") or "") != str(
        export.get("memoryCatalogFingerprint") or ""
    ):
        errors.append("memory_catalog_fingerprint_mismatch")
    if not compact_whitespace(str(export.get("governanceFingerprint") or "")):
        errors.append("missing_governance_fingerprint")
    elif str(manifest.get("governanceFingerprint") or "") != str(
        export.get("governanceFingerprint") or ""
    ):
        errors.append("governance_fingerprint_mismatch")

    exported_inputs = {
        str(item.get("inputId") or ""): item
        for item in _dicts(export.get("inputs"))
        if compact_whitespace(str(item.get("inputId") or ""))
    }
    decisions_by_id: dict[str, dict[str, object]] = {}
    duplicate_decisions: set[str] = set()
    unknown_decisions: set[str] = set()
    remembered_inputs: dict[str, set[int]] = {}
    event_input_ids: dict[int, set[str]] = defaultdict(set)
    for input_id, source_input in exported_inputs.items():
        for event_id in _positive_ints(source_input.get("sourceEventIds")):
            event_input_ids[event_id].add(input_id)
    for decision in _dicts(manifest.get("decisions")):
        input_id = compact_whitespace(str(decision.get("inputId") or ""))
        if input_id not in exported_inputs:
            unknown_decisions.add(input_id or "<missing>")
            continue
        if input_id in decisions_by_id:
            duplicate_decisions.add(input_id)
            continue
        disposition = compact_whitespace(str(decision.get("decision") or ""))
        if disposition not in _DECISIONS:
            errors.append(f"invalid_decision:{input_id}:{disposition or '<missing>'}")
        if not compact_whitespace(str(decision.get("reasonCode") or "")):
            errors.append(f"missing_reason:{input_id}")
        if bool(exported_inputs[input_id].get("sensitive")) and disposition != "not_for_memory":
            errors.append(f"sensitive_input_must_not_be_remembered:{input_id}")
        decisions_by_id[input_id] = decision
        if disposition == "remember":
            event_ids = set(_positive_ints(exported_inputs[input_id].get("sourceEventIds")))
            remembered_inputs[input_id] = event_ids
    if unknown_decisions:
        errors.append(f"unknown_decisions:{len(unknown_decisions)}")
    if duplicate_decisions:
        errors.append(f"duplicate_decisions:{len(duplicate_decisions)}")
    missing_decisions = set(exported_inputs) - set(decisions_by_id)
    if missing_decisions:
        errors.append(f"missing_decisions:{len(missing_decisions)}")
    # A physical input event may be represented by more than one logical
    # source.  It is eligible as evidence only when every representation was
    # explicitly reviewed as remember.  A union of remembered event ids would
    # otherwise let one remembered source launder a sibling not_for_memory
    # source into an active Atom, Book, Phrase, or Timeline.
    fully_remembered_event_ids = {
        event_id
        for event_id, input_ids in event_input_ids.items()
        if input_ids
        and all(
            compact_whitespace(
                str(dict(decisions_by_id.get(input_id) or {}).get("decision") or "")
            )
            == "remember"
            for input_id in input_ids
        )
    }

    proposed_atoms: dict[str, dict[str, object]] = {}
    claim_keys: dict[str, str] = {}
    used_event_ids: set[int] = set()
    for index, atom in enumerate(_dicts(manifest.get("atoms")), start=1):
        atom_id = compact_whitespace(str(atom.get("atomId") or ""))
        claim_key = compact_whitespace(str(atom.get("claimKey") or ""))
        canonical = compact_whitespace(str(atom.get("canonicalText") or ""))
        event_ids = set(_positive_ints(atom.get("sourceEventIds")))
        if not atom_id:
            errors.append(f"atom_missing_id:{index}")
        elif atom_id in proposed_atoms:
            errors.append(f"duplicate_atom_id:{atom_id}")
        else:
            proposed_atoms[atom_id] = atom
        if not claim_key or len(claim_key) > 240:
            errors.append(f"atom_invalid_claim_key:{atom_id or index}")
        elif claim_key in claim_keys:
            errors.append(f"duplicate_current_claim_key:{claim_key}")
        else:
            claim_keys[claim_key] = atom_id
        if len(canonical) < 6:
            errors.append(f"atom_text_too_short:{atom_id or index}")
        elif contains_sensitive_content(canonical):
            errors.append(f"atom_contains_sensitive_content:{atom_id or index}")
        elif _contains_derived_text_marker(canonical):
            errors.append(f"atom_contains_raw_protocol_text:{atom_id or index}")
        elif _copies_exported_input(canonical, exported_inputs.values()):
            errors.append(f"atom_copies_source_input:{atom_id or index}")
        if not compact_whitespace(str(atom.get("kind") or "")):
            errors.append(f"atom_missing_kind:{atom_id or index}")
        if not event_ids:
            errors.append(f"atom_missing_evidence:{atom_id or index}")
        elif not event_ids.issubset(fully_remembered_event_ids):
            errors.append(f"atom_uses_unremembered_evidence:{atom_id or index}")
        if _number(atom.get("confidence")) < 0.7:
            errors.append(f"atom_low_confidence:{atom_id or index}")
        if _number(atom.get("qualityScore")) < 0.65:
            errors.append(f"atom_low_quality:{atom_id or index}")
        if bool(atom.get("directCandidateAllowed")):
            errors.append(f"atom_direct_candidate_forbidden:{atom_id or index}")
        used_event_ids.update(event_ids)

    existing_atom_ids = {
        str(item.get("atomId") or "") for item in _dicts(export.get("existingAtoms"))
    }
    for index, book in enumerate(_dicts(manifest.get("books")), start=1):
        book_id = compact_whitespace(str(book.get("bookId") or ""))
        event_ids = set(_positive_ints(book.get("sourceEventIds")))
        atom_ids = set(_unique_strings(book.get("memoryAtomIds")))
        if not book_id:
            errors.append(f"book_missing_id:{index}")
        if not compact_whitespace(str(book.get("title") or "")):
            errors.append(f"book_missing_title:{book_id or index}")
        summary = compact_whitespace(str(book.get("summary") or ""))
        if len(summary) < 12:
            errors.append(f"book_summary_too_short:{book_id or index}")
        elif _contains_derived_text_marker(summary):
            errors.append(f"book_contains_raw_protocol_text:{book_id or index}")
        elif _copies_exported_input(summary, exported_inputs.values()):
            errors.append(f"book_copies_source_input:{book_id or index}")
        if not event_ids:
            errors.append(f"book_missing_evidence:{book_id or index}")
        elif not event_ids.issubset(fully_remembered_event_ids):
            errors.append(f"book_uses_unremembered_evidence:{book_id or index}")
        unknown_atoms = atom_ids - set(proposed_atoms)
        if unknown_atoms:
            errors.append(f"book_unknown_atoms:{book_id or index}:{len(unknown_atoms)}")
        used_event_ids.update(event_ids)

    timeline_evidence_inputs: set[str] = set()
    timeline_dates: dict[str, int] = defaultdict(int)
    try:
        review_timezone = ZoneInfo(str(export.get("timezone") or "Asia/Shanghai"))
    except Exception:
        errors.append("invalid_review_timezone")
        review_timezone = ZoneInfo("Asia/Shanghai")
    for index, timeline in enumerate(_dicts(manifest.get("timelines")), start=1):
        timeline_date = compact_whitespace(str(timeline.get("date") or ""))
        goal = compact_whitespace(str(timeline.get("goal") or ""))
        actions = compact_whitespace(str(timeline.get("actualActions") or ""))
        result = compact_whitespace(str(timeline.get("resultOrBlocker") or ""))
        evidence_input_ids = _unique_strings(timeline.get("evidenceLogicalInputIds"))
        start_minute = _timeline_minute(timeline.get("start"))
        end_minute = _timeline_minute(timeline.get("end"))
        if not timeline_date:
            errors.append(f"timeline_missing_date:{index}")
        if start_minute is None or end_minute is None or start_minute > end_minute:
            errors.append(f"timeline_invalid_time_boundary:{timeline_date or index}")
        timeline_dates[timeline_date] += 1
        if timeline_dates[timeline_date] > 3:
            errors.append(f"timeline_too_many_segments:{timeline_date}")
        for field, value in (("goal", goal), ("actions", actions), ("result", result)):
            if len(value) < 6:
                errors.append(f"timeline_{field}_too_short:{timeline_date or index}")
            elif _contains_derived_text_marker(value):
                errors.append(f"timeline_{field}_contains_raw_protocol_text:{timeline_date or index}")
            elif _copies_exported_input(value, exported_inputs.values()):
                errors.append(f"timeline_{field}_copies_source_input:{timeline_date or index}")
        if not evidence_input_ids:
            errors.append(f"timeline_missing_evidence:{timeline_date or index}")
        for input_id in evidence_input_ids:
            source_input = exported_inputs.get(input_id)
            if source_input is None:
                errors.append(f"timeline_unknown_input:{timeline_date or index}:{input_id}")
                continue
            if bool(source_input.get("sensitive")):
                errors.append(f"timeline_sensitive_input:{timeline_date or index}:{input_id}")
            if input_id not in remembered_inputs:
                errors.append(f"timeline_evidence_not_remembered:{timeline_date or index}:{input_id}")
            source_event_ids = set(
                _positive_ints(source_input.get("sourceEventIds"))
            )
            if not source_event_ids.issubset(fully_remembered_event_ids):
                errors.append(
                    f"timeline_uses_unremembered_evidence:{timeline_date or index}:{input_id}"
                )
            if timeline_date and str(source_input.get("date") or "") != timeline_date:
                errors.append(f"timeline_evidence_date_mismatch:{timeline_date}:{input_id}")
            occurred_at = datetime.fromtimestamp(
                int(source_input.get("createdAtMs") or 0) / 1000,
                tz=review_timezone,
            )
            occurred_minute = occurred_at.hour * 60 + occurred_at.minute
            if (
                start_minute is not None
                and end_minute is not None
                and not start_minute <= occurred_minute <= end_minute
            ):
                errors.append(f"timeline_evidence_time_mismatch:{timeline_date}:{input_id}")
            if input_id in timeline_evidence_inputs:
                errors.append(f"timeline_duplicate_evidence:{input_id}")
            timeline_evidence_inputs.add(input_id)
            used_event_ids.update(
                _positive_ints(source_input.get("sourceEventIds"))
            )

    for input_id, event_ids in remembered_inputs.items():
        if event_ids.isdisjoint(used_event_ids):
            errors.append(f"remembered_input_without_memory_artifact:{input_id}")

    for index, relation in enumerate(_dicts(manifest.get("supersedes")), start=1):
        old_id = compact_whitespace(str(relation.get("oldId") or ""))
        new_id = compact_whitespace(str(relation.get("newId") or ""))
        event_ids = set(_positive_ints(relation.get("sourceEventIds")))
        if old_id not in existing_atom_ids:
            errors.append(f"supersede_unknown_old_atom:{old_id or index}")
        if new_id not in proposed_atoms:
            errors.append(f"supersede_unknown_new_atom:{new_id or index}")
        if not event_ids or not event_ids.issubset(fully_remembered_event_ids):
            errors.append(f"supersede_invalid_evidence:{old_id or index}")

    atom_audit = _dicts(dict(manifest.get("existingMemoryAudit") or {}).get("atoms"))
    atom_audit_ids = [compact_whitespace(str(item.get("atomId") or "")) for item in atom_audit]
    exported_atom_ids = [str(item.get("atomId") or "") for item in _dicts(export.get("existingAtoms"))]
    if set(atom_audit_ids) != set(exported_atom_ids) or len(atom_audit_ids) != len(
        exported_atom_ids
    ):
        errors.append("existing_atom_audit_incomplete")
    for item in atom_audit:
        action = compact_whitespace(str(item.get("action") or ""))
        if action not in _ATOM_ACTIONS:
            errors.append(f"invalid_existing_atom_action:{item.get('atomId')}:{action}")
        if not compact_whitespace(str(item.get("reason") or "")):
            errors.append(f"missing_existing_atom_reason:{item.get('atomId')}")
        if action == "supersede":
            replacement = compact_whitespace(str(item.get("replacementAtomId") or ""))
            if replacement not in proposed_atoms:
                errors.append(f"invalid_existing_atom_replacement:{item.get('atomId')}")
            matching_relations = [
                relation
                for relation in _dicts(manifest.get("supersedes"))
                if compact_whitespace(str(relation.get("oldId") or ""))
                == compact_whitespace(str(item.get("atomId") or ""))
                and compact_whitespace(str(relation.get("newId") or "")) == replacement
            ]
            if len(matching_relations) != 1:
                errors.append(f"existing_atom_supersession_relation_mismatch:{item.get('atomId')}")

    book_audit = _dicts(dict(manifest.get("existingMemoryAudit") or {}).get("books"))
    book_audit_ids = [compact_whitespace(str(item.get("bookId") or "")) for item in book_audit]
    exported_book_ids = [str(item.get("bookId") or "") for item in _dicts(export.get("existingBooks"))]
    if set(book_audit_ids) != set(exported_book_ids) or len(book_audit_ids) != len(
        exported_book_ids
    ):
        errors.append("existing_book_audit_incomplete")
    for item in book_audit:
        action = compact_whitespace(str(item.get("action") or ""))
        if action not in _BOOK_ACTIONS:
            errors.append(f"invalid_existing_book_action:{item.get('bookId')}:{action}")
        if not compact_whitespace(str(item.get("reason") or "")):
            errors.append(f"missing_existing_book_reason:{item.get('bookId')}")

    phrase_audit = _dicts(manifest.get("existingPhraseAudit"))
    phrase_audit_ids = [
        compact_whitespace(str(item.get("memoryId") or "")) for item in phrase_audit
    ]
    exported_phrases = _dicts(export.get("existingPhrases"))
    exported_phrase_by_id = {
        compact_whitespace(str(item.get("memoryId") or "")): item
        for item in exported_phrases
    }
    exported_phrase_ids = list(exported_phrase_by_id)
    if set(phrase_audit_ids) != set(exported_phrase_ids) or len(phrase_audit_ids) != len(
        exported_phrase_ids
    ):
        errors.append("existing_phrase_audit_incomplete")
    physical_event_ids = {
        event_id
        for source_input in exported_inputs.values()
        for event_id in _positive_ints(source_input.get("sourceEventIds"))
    }
    for item in phrase_audit:
        memory_id = compact_whitespace(str(item.get("memoryId") or ""))
        action = compact_whitespace(str(item.get("action") or ""))
        if action not in _PHRASE_ACTIONS:
            errors.append(f"invalid_existing_phrase_action:{memory_id}:{action}")
        if not compact_whitespace(str(item.get("reason") or "")):
            errors.append(f"missing_existing_phrase_reason:{memory_id}")
        phrase = exported_phrase_by_id.get(memory_id)
        if phrase is None or action != "keep":
            continue
        if str(phrase.get("status") or "") not in {"active", "approved"}:
            errors.append(f"kept_phrase_not_active:{memory_id}")
        declared = set(_positive_ints(phrase.get("declaredSourceEventIds")))
        if not declared:
            errors.append(f"kept_phrase_missing_evidence:{memory_id}")
        elif not declared.issubset(physical_event_ids):
            errors.append(f"kept_phrase_unknown_evidence:{memory_id}")
        if not declared.issubset(fully_remembered_event_ids):
            errors.append(f"kept_phrase_uses_unremembered_evidence:{memory_id}")

    return {
        "schemaVersion": "rag-ime.manual-memory-review-validation.v1",
        "ok": not errors,
        "errors": errors,
        "counts": {
            "exportedInputs": len(exported_inputs),
            "decisions": len(decisions_by_id),
            "rememberedInputs": len(remembered_inputs),
            "fullyRememberedPhysicalEvents": len(fully_remembered_event_ids),
            "atoms": len(proposed_atoms),
            "books": len(_dicts(manifest.get("books"))),
            "timelineSegments": len(_dicts(manifest.get("timelines"))),
            "supersedes": len(_dicts(manifest.get("supersedes"))),
            "existingAtomAudits": len(atom_audit),
            "existingBookAudits": len(book_audit),
            "existingPhraseAudits": len(phrase_audit),
        },
    }


def _raw_source(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sourceId": str(row["source_id"]),
        "sourceIds": [str(row["source_id"])],
        "sourceKind": str(row["source_kind"]),
        "trustClass": str(row["trust_class"]),
        "createdAtMs": int(row["created_at_ms"] or 0),
        "sourceEventIds": [int(row["input_event_id"])],
        "text": compact_whitespace(str(row["committed_text"] or ""))[:4000],
        "disposition": str(row["disposition"]),
        "source": str(row["event_source"] or ""),
        "recentContext": compact_whitespace(str(row["recent_context"] or ""))[:4000],
        "app": str(row["app"] or ""),
        "project": str(row["event_project"] or ""),
        "contextGroupId": str(row["context_group_id"] or ""),
        "contextGroupLevel": str(row["context_group_level"] or "app"),
        "sourceMetadataTags": _json_strings(row["tags_json"]),
        "sessionId": str(row["session_id"] or ""),
    }


def _atom_export(row: sqlite3.Row) -> dict[str, object]:
    return {
        "atomId": str(row["id"]),
        "kind": str(row["kind"]),
        "canonicalText": str(row["canonical_text"] or row["text"]),
        "sourceEventIds": _json_ints(row["source_event_ids_json"]),
        "status": str(row["status"]),
        "claimKey": str(row["claim_key"] or ""),
        "claimState": str(row["claim_state"] or ""),
        "validFromMs": int(row["valid_from_ms"] or 0),
        "validToMs": int(row["valid_to_ms"] or 0),
        "supersedesId": str(row["supersedes_id"] or ""),
        "ownerKind": str(row["owner_kind"]),
        "ownerId": str(row["owner_id"]),
    }


def _book_export(row: sqlite3.Row) -> dict[str, object]:
    return {
        "bookId": str(row["book_id"]),
        "bookType": str(row["book_type"]),
        "bookKey": str(row["book_key"]),
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "tags": _json_strings(row["tags_json"]),
        "sourceEventIds": _json_ints(row["source_event_ids_json"]),
        "memoryAtomIds": _json_strings(row["memory_atom_ids_json"]),
        "status": str(row["status"]),
        "ownerKind": str(row["owner_kind"]),
        "ownerId": str(row["owner_id"]),
    }


def _phrase_export(row: sqlite3.Row) -> dict[str, object]:
    metadata = _json_object(row["metadata_json"])
    declared_source_event_ids = _positive_ints(
        [row["source_event_id"], *_positive_ints(metadata.get("sourceEventIds"))]
    )
    return {
        "id": int(row["id"]),
        "memoryId": str(row["memory_id"]),
        "text": str(row["text"] or ""),
        "summary": str(row["summary"] or ""),
        "sourceEventId": int(row["source_event_id"] or 0),
        "declaredSourceEventIds": declared_source_event_ids,
        "status": str(row["status"]),
        "project": str(row["project"]),
        "app": str(row["app"]),
        "ownerKind": str(row["owner_kind"]),
        "ownerId": str(row["owner_id"]),
        "metadata": metadata,
    }


def _logical_input_id(source_ids: list[str], *, created_at_ms: int) -> str:
    digest = hashlib.sha256()
    digest.update("\n".join(source_ids).encode("utf-8"))
    digest.update(f"\n{created_at_ms}".encode("ascii"))
    return f"logical:{digest.hexdigest()[:24]}"


def _normalize_part_atom(item: Mapping[str, object]) -> dict[str, object]:
    atom = dict(item)
    atom_id = compact_whitespace(str(atom.get("atomId") or ""))
    if not atom_id:
        identity = "\n".join(
            (
                compact_whitespace(str(atom.get("claimKey") or "")),
                compact_whitespace(str(atom.get("canonicalText") or "")),
            )
        )
        atom_id = f"atom:review:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    atom["atomId"] = atom_id
    atom["directCandidateAllowed"] = False
    return atom


def _dicts(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _json_strings(raw: object) -> list[str]:
    return _unique_strings(_json_value(raw))


def _json_ints(raw: object) -> list[int]:
    return _positive_ints(_json_value(raw))


def _json_value(raw: object) -> object:
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _json_object(raw: object) -> dict[str, object]:
    value = _json_value(raw)
    return dict(value) if isinstance(value, Mapping) else {}


def _unique_strings(raw: object) -> list[str]:
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    return list(
        dict.fromkeys(
            compact_whitespace(str(value or ""))
            for value in values
            if compact_whitespace(str(value or ""))
        )
    )


def _positive_ints(raw: object) -> list[int]:
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    result: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _number(raw: object) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _timeline_minute(raw: object) -> int | None:
    value = compact_whitespace(str(raw or ""))
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _contains_derived_text_marker(text: str) -> bool:
    folded = compact_whitespace(text).casefold()
    return any(marker.casefold() in folded for marker in _FORBIDDEN_DERIVED_TEXT_MARKERS)


def _copies_exported_input(
    derived_text: str,
    exported_inputs: Iterable[Mapping[str, object]],
) -> bool:
    """Reject raw evidence masquerading as a durable Atom, Book, or Timeline."""

    derived = compact_whitespace(derived_text)
    if len(derived) < 16:
        return False
    for item in exported_inputs:
        source = compact_whitespace(str(item.get("text") or ""))
        if len(source) < 16:
            continue
        if derived == source:
            return True
        shorter, longer = sorted((derived, source), key=len)
        if len(shorter) >= 28 and shorter in longer:
            return True
    return False
