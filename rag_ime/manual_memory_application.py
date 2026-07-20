from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .manual_memory_review import (
    ManualMemoryReviewError,
    memory_review_catalog_fingerprint,
    memory_review_evidence_fingerprint,
    memory_review_governance_fingerprint,
    validate_manual_memory_manifest,
)
from .memory_ingest import normalize_text
from .memory_projection import RETRIEVAL_DOCS_PROJECTION, enqueue_memory_projection
from .memory_tag_graph import recompute_tag_graph
from .text_utils import compact_whitespace, now_ms


MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION = "rag-ime.manual-memory-application.v1"
_TIMEZONE = ZoneInfo("Asia/Shanghai")
_GROUP_BY_BOOK_KEY = {
    "memory-rag-governance": "group:memory-rag",
    "ime-product-runtime": "group:input-method",
    "model-training-evaluation": "group:model-and-data",
    "agent-runtime-tools": "group:agent-interview",
    "learning-engineering": "group:learning-system",
    "voice-input": "group:voice-input",
}


def apply_manual_memory_manifest(
    conn: sqlite3.Connection,
    *,
    candidate_path: Path | str,
    export: Mapping[str, object],
    manifest: Mapping[str, object],
    reviewer_id: str = "codex-root",
    applied_at_ms: int | None = None,
) -> dict[str, object]:
    """Apply one fully reviewed manifest to an isolated SQLite candidate.

    The caller owns the candidate file. This function fails before mutation if
    either immutable evidence or the derived catalog differs from the review.
    """

    bound_candidate = _require_candidate_connection(conn, candidate_path=candidate_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    project = compact_whitespace(str(manifest.get("project") or ""))
    timestamp = now_ms() if applied_at_ms is None else max(1, int(applied_at_ms))
    reviewer = compact_whitespace(reviewer_id) or "codex-root"
    validation = validate_manual_memory_manifest(export, manifest=manifest)
    if not bool(validation["ok"]):
        raise ManualMemoryReviewError(
            "manual memory manifest failed validation: "
            + "; ".join(str(value) for value in validation["errors"][:20])
        )
    evidence_fingerprint = memory_review_evidence_fingerprint(conn, project=project)
    if evidence_fingerprint != str(manifest.get("evidenceFingerprint") or ""):
        raise ManualMemoryReviewError("candidate evidence fingerprint changed after review")
    catalog_fingerprint = memory_review_catalog_fingerprint(conn, project=project)
    if catalog_fingerprint != str(manifest.get("memoryCatalogFingerprint") or ""):
        raise ManualMemoryReviewError("candidate memory catalog changed after review")
    governance_fingerprint = memory_review_governance_fingerprint(
        conn,
        project=project,
    )
    if governance_fingerprint != str(manifest.get("governanceFingerprint") or ""):
        raise ManualMemoryReviewError("candidate memory governance changed after review")

    manifest_sha256 = _payload_sha256(manifest)
    run_id = f"manual-history-review:{manifest_sha256[:24]}"
    input_events_before = _table_fingerprint(conn, "input_events")
    inputs = {
        str(item["inputId"]): dict(item)
        for item in _dicts(export.get("inputs"))
    }
    decisions = {
        str(item["inputId"]): dict(item)
        for item in _dicts(manifest.get("decisions"))
    }
    atoms = _dicts(manifest.get("atoms"))
    books = _dicts(manifest.get("books"))
    timelines = _dicts(manifest.get("timelines"))
    exported_phrases = {
        str(item.get("memoryId") or ""): item
        for item in _dicts(export.get("existingPhrases"))
    }
    phrase_audit = _dicts(manifest.get("existingPhraseAudit"))
    kept_phrase_event_ids = [
        event_id
        for audit in phrase_audit
        if str(audit.get("action") or "") == "keep"
        for event_id in exported_phrases[str(audit.get("memoryId") or "")].get(
            "declaredSourceEventIds", []
        )
    ]
    selected_event_ids = set(
        _ints(
            [
                *(event_id for atom in atoms for event_id in atom.get("sourceEventIds", [])),
                *(event_id for book in books for event_id in book.get("sourceEventIds", [])),
                *(
                    event_id
                    for timeline in timelines
                    for input_id in timeline.get("evidenceLogicalInputIds", [])
                    for event_id in dict(inputs.get(str(input_id)) or {}).get(
                        "sourceEventIds", []
                    )
                ),
                *kept_phrase_event_ids,
            ]
        )
    )
    event_to_sources: dict[int, list[str]] = defaultdict(list)
    source_to_input: dict[str, str] = {}
    for input_id, item in inputs.items():
        source_ids = _strings(item.get("sourceIds"))
        for source_id in source_ids:
            if source_id in source_to_input:
                raise ManualMemoryReviewError(f"source appears in two logical inputs: {source_id}")
            source_to_input[source_id] = input_id
        for event_id in _ints(item.get("sourceEventIds")):
            event_to_sources[event_id].extend(source_ids)

    expected_sources = {
        str(row[0])
        for row in conn.execute(
            """SELECT source.source_id
               FROM agent_memory_sources AS source
               JOIN input_events AS event ON event.id = source.input_event_id
               WHERE source.status = 'active'
                 AND (? = '' OR event.project = ? OR event.project = '')""",
            (project, project),
        ).fetchall()
    }
    if expected_sources != set(source_to_input):
        raise ManualMemoryReviewError(
            "reviewed source coverage changed: "
            f"missing={len(expected_sources - set(source_to_input))},"
            f"unexpected={len(set(source_to_input) - expected_sources)}"
        )

    savepoint = "manual_memory_review_apply"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        disposition_counts = _apply_source_decisions(
            conn,
            inputs=inputs,
            decisions=decisions,
            source_to_input=source_to_input,
            selected_event_ids=selected_event_ids,
            run_id=run_id,
            reviewer=reviewer,
            timestamp=timestamp,
        )
        existing_counts = _retire_existing_catalog(
            conn,
            manifest=manifest,
            atoms=atoms,
            project=project,
            timestamp=timestamp,
            run_id=run_id,
        )
        phrase_counts = _apply_existing_phrase_audit(
            conn,
            audit=phrase_audit,
            exported_phrases=exported_phrases,
            project=project,
            run_id=run_id,
            reviewer=reviewer,
            timestamp=timestamp,
        )
        atom_count = _insert_reviewed_atoms(
            conn,
            atoms=atoms,
            event_to_sources=event_to_sources,
            project=project,
            run_id=run_id,
            timestamp=timestamp,
            superseded_by=_superseded_predecessors(manifest),
        )
        book_count = _insert_reviewed_books(
            conn,
            books=books,
            project=project,
            run_id=run_id,
            timestamp=timestamp,
        )
        timeline_report = _replace_activity_timelines(
            conn,
            timelines=timelines,
            inputs=inputs,
            project=project,
            reviewer=reviewer,
            run_id=run_id,
            timestamp=timestamp,
        )
        group_report = _rebuild_reviewed_groups(
            conn,
            books=books,
            atoms=atoms,
            existing_atom_ids={str(item["atomId"]) for item in _dicts(export.get("existingAtoms"))},
            existing_book_ids={str(item["bookId"]) for item in _dicts(export.get("existingBooks"))},
            project=project,
            run_id=run_id,
            timestamp=timestamp,
        )
        draft_report = _retire_stale_drafts(
            conn,
            project=project,
            inputs=inputs,
            run_id=run_id,
            timestamp=timestamp,
            manifest_sha256=manifest_sha256,
        )
        tag_graph = recompute_tag_graph(conn)
        projection_outbox_id = enqueue_memory_projection(
            conn,
            projection_kind=RETRIEVAL_DOCS_PROJECTION,
            aggregate_type="manual_memory_review",
            aggregate_id=run_id,
            operation="replace_reviewed_catalog",
            project=project,
            revision=timestamp,
            payload={
                "manifestSha256": manifest_sha256,
                "reviewer": reviewer,
                "atomCount": atom_count,
                "bookCount": book_count,
                "timelineCount": timeline_report["timelineCount"],
            },
            available_at_ms=timestamp,
        )
        changes = {
            "sourceDispositions": disposition_counts,
            "existingCatalog": existing_counts,
            "existingPhrases": phrase_counts,
            "insertedAtoms": atom_count,
            "insertedBooks": book_count,
            "timelines": timeline_report,
            "groups": group_report,
            "drafts": draft_report,
            "tagGraph": tag_graph,
            "projectionOutboxId": projection_outbox_id,
        }
        conn.execute(
            """INSERT INTO management_audit_log(
                   created_at_ms, action, target_type, target_id,
                   payload_json, result_json
               ) VALUES (?, 'apply_manual_memory_review', 'memory_database', ?, ?, ?)""",
            (
                timestamp,
                project,
                json.dumps(
                    {
                        "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
                        "reviewer": reviewer,
                        "runId": run_id,
                        "manifestSha256": manifest_sha256,
                        "evidenceFingerprint": evidence_fingerprint,
                        "memoryCatalogFingerprint": catalog_fingerprint,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(changes, ensure_ascii=False, sort_keys=True),
            ),
        )
        input_events_after = _table_fingerprint(conn, "input_events")
        if input_events_after != input_events_before:
            raise RuntimeError("manual review changed immutable input_events")
        verification = verify_manual_memory_application(
            conn,
            manifest=manifest,
            project=project,
        )
        if not bool(verification["ok"]):
            raise RuntimeError(
                "manual memory candidate failed post-apply verification: "
                + "; ".join(str(value) for value in verification["errors"])
            )
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    return {
        "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
        "ok": True,
        "project": project,
        "reviewer": reviewer,
        "runId": run_id,
        "manifestSha256": manifest_sha256,
        "candidatePath": str(bound_candidate),
        "evidenceFingerprint": evidence_fingerprint,
        "memoryCatalogFingerprintBefore": catalog_fingerprint,
        "governanceFingerprintBefore": governance_fingerprint,
        "inputEventsFingerprint": input_events_after,
        "beforeState": {
            "project": project,
            "evidenceFingerprint": evidence_fingerprint,
            "memoryCatalogFingerprint": catalog_fingerprint,
            "governanceFingerprint": governance_fingerprint,
            "inputEventsFingerprint": input_events_before,
        },
        "changes": changes,
        "verification": verification,
    }


def verify_manual_memory_application(
    conn: sqlite3.Connection,
    *,
    manifest: Mapping[str, object],
    project: str,
) -> dict[str, object]:
    errors: list[str] = []
    expected_atoms = {str(item["atomId"]) for item in _dicts(manifest.get("atoms"))}
    actual_atoms = {
        str(row[0])
        for row in conn.execute(
            """SELECT id FROM memory_atoms
               WHERE status IN ('active', 'approved') AND claim_state = 'current'
                 AND scope_project = ?""",
            (project,),
        ).fetchall()
    }
    if actual_atoms != expected_atoms:
        errors.append(
            f"active_atom_set_mismatch:expected={len(expected_atoms)},actual={len(actual_atoms)}"
        )
    pending_sources = int(
        conn.execute(
            """SELECT COUNT(*)
               FROM agent_memory_sources AS source
               JOIN input_events AS event ON event.id = source.input_event_id
               WHERE source.status = 'active'
                 AND source.disposition IN ('pending', 'needs_review')
                 AND (? = '' OR event.project = ? OR event.project = '')""",
            (project, project),
        ).fetchone()[0]
    )
    if pending_sources:
        errors.append(f"unreviewed_sources={pending_sources}")
    artifact_event_ids = _active_artifact_event_ids(conn, project=project)
    remembered_source_event_ids = {
        int(row[0])
        for row in conn.execute(
            """SELECT DISTINCT source.input_event_id
               FROM agent_memory_sources AS source
               JOIN input_events AS event ON event.id = source.input_event_id
               WHERE source.status = 'active' AND source.disposition = 'remember'
                 AND (? = '' OR event.project = ? OR event.project = '')""",
            (project, project),
        ).fetchall()
    }
    if remembered_source_event_ids != artifact_event_ids:
        errors.append(
            "remembered_source_artifact_mismatch:"
            f"extra={sorted(remembered_source_event_ids - artifact_event_ids)},"
            f"missing={sorted(artifact_event_ids - remembered_source_event_ids)}"
        )
    invalid_artifact_sources = _active_artifact_invalid_sources(
        conn,
        project=project,
    )
    if invalid_artifact_sources:
        errors.append(
            "active_artifact_invalid_source="
            + ";".join(invalid_artifact_sources)
        )
    draft_timelines = int(
        conn.execute(
            "SELECT COUNT(*) FROM daily_activity_timelines WHERE project = ? AND status = 'draft'",
            (project,),
        ).fetchone()[0]
    )
    if draft_timelines:
        errors.append(f"draft_timelines={draft_timelines}")
    # Cleanup runs are a shared, legacy review queue with no project column.
    # A project-scoped manual review must neither retire nor reject them.
    draft_runs = 0
    preview_proposals = int(
        conn.execute(
            "SELECT COUNT(*) FROM memory_governance_proposals WHERE project = ? AND status = 'preview'",
            (project,),
        ).fetchone()[0]
    )
    if preview_proposals:
        errors.append(f"preview_memory_proposals={preview_proposals}")
    duplicate_claims = int(
        conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT owner_kind, owner_id, claim_key,
                          COALESCE(scope_app, '') AS app, COUNT(*) AS count
                   FROM memory_atoms
                   WHERE status IN ('active', 'approved') AND claim_state = 'current'
                     AND scope_project = ? AND trim(claim_key) != ''
                   GROUP BY owner_kind, owner_id, claim_key,
                            COALESCE(scope_app, '')
                   HAVING COUNT(*) > 1
               )""",
            (project,),
        ).fetchone()[0]
    )
    if duplicate_claims:
        errors.append(f"duplicate_current_claims={duplicate_claims}")
    active_book_rows = conn.execute(
        """SELECT book_id, memory_atom_ids_json FROM memory_books
           WHERE project = ? AND status IN ('active', 'approved')""",
        (project,),
    ).fetchall()
    invalid_book_members: list[str] = []
    for row in active_book_rows:
        unknown = sorted(set(_stored_strings(row["memory_atom_ids_json"])) - expected_atoms)
        if unknown:
            invalid_book_members.append(f"{row['book_id']}:{','.join(unknown)}")
    if invalid_book_members:
        errors.append("active_book_references_noncurrent_atoms=" + ";".join(invalid_book_members))
    phrase_audit = _dicts(manifest.get("existingPhraseAudit"))
    expected_phrases = {
        compact_whitespace(str(item.get("memoryId") or ""))
        for item in phrase_audit
        if str(item.get("action") or "") == "keep"
    }
    active_phrase_rows = conn.execute(
        """SELECT memory_id, source_event_id, metadata_json FROM memory_items
           WHERE kind = 'phrase' AND project = ?
             AND status IN ('active', 'approved')""",
        (project,),
    ).fetchall()
    actual_phrases = {str(row["memory_id"]) for row in active_phrase_rows}
    if actual_phrases != expected_phrases:
        errors.append(
            f"active_phrase_set_mismatch:expected={len(expected_phrases)},"
            f"actual={len(actual_phrases)}"
        )
    invalid_phrase_sources: list[str] = []
    for row in active_phrase_rows:
        metadata = _json_object(row["metadata_json"])
        declared = set(
            _ints([row["source_event_id"], *_ints(metadata.get("sourceEventIds"))])
        )
        for event_id in sorted(declared):
            dispositions = [
                str(source_row[0])
                for source_row in conn.execute(
                    """SELECT disposition FROM agent_memory_sources
                       WHERE status = 'active' AND input_event_id = ?""",
                    (event_id,),
                ).fetchall()
            ]
            if not dispositions or any(value != "remember" for value in dispositions):
                invalid_phrase_sources.append(f"{row['memory_id']}:{event_id}")
    if invalid_phrase_sources:
        errors.append(
            "active_phrase_invalid_source=" + ",".join(invalid_phrase_sources)
        )
    active_phrase_docs = {
        str(row[0])
        for row in conn.execute(
            """SELECT doc.source_id FROM memory_retrieval_docs AS doc
               JOIN memory_items AS item ON item.memory_id = doc.source_id
               WHERE item.kind = 'phrase' AND item.project = ?
                 AND item.status IN ('active', 'approved')
                 AND doc.status = 'active'""",
            (project,),
        ).fetchall()
    }
    invalid_phrase_docs = sorted(
        memory_id
        for memory_id in active_phrase_docs
        if any(value.startswith(f"{memory_id}:") for value in invalid_phrase_sources)
    )
    if invalid_phrase_docs:
        errors.append("active_phrase_doc_invalid_source=" + ",".join(invalid_phrase_docs))
    discarded_docs = int(
        conn.execute(
            """SELECT COUNT(*)
               FROM memory_retrieval_docs AS doc
               JOIN memory_books AS book ON book.book_id = doc.source_id
               WHERE book.archive_reason = 'discarded_by_manual_review'"""
        ).fetchone()[0]
    )
    # The projection worker runs after this verification. Existing discarded
    # docs are allowed only until that worker replaces the projection.
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok":
        errors.append(f"integrity_check={integrity}")
    if foreign_keys:
        errors.append(f"foreign_key_violations={foreign_keys}")
    return {
        "schemaVersion": "rag-ime.manual-memory-application-verification.v1",
        "ok": not errors,
        "errors": errors,
        "activeAtomCount": len(actual_atoms),
        "pendingOrNeedsReviewSourceCount": pending_sources,
        "rememberedSourceEventCount": len(remembered_source_event_ids),
        "artifactEvidenceEventCount": len(artifact_event_ids),
        "invalidArtifactSources": invalid_artifact_sources,
        "activePhraseCount": len(actual_phrases),
        "activePhraseRetrievalDocCount": len(active_phrase_docs),
        "draftTimelineCount": draft_timelines,
        "draftMemoryRunCount": draft_runs,
        "previewMemoryProposalCount": preview_proposals,
        "duplicateCurrentClaimCount": duplicate_claims,
        "discardedBookProjectionCountBeforeWorker": discarded_docs,
        "integrityCheck": integrity,
        "foreignKeyViolationCount": foreign_keys,
    }


def _apply_source_decisions(
    conn: sqlite3.Connection,
    *,
    inputs: Mapping[str, Mapping[str, object]],
    decisions: Mapping[str, Mapping[str, object]],
    source_to_input: Mapping[str, str],
    selected_event_ids: set[int],
    run_id: str,
    reviewer: str,
    timestamp: int,
) -> dict[str, int]:
    counts = {"remember": 0, "not_for_memory": 0}
    for source_id, input_id in source_to_input.items():
        decision = decisions[input_id]
        logical_decision = str(decision["decision"])
        logical_reason_code = compact_whitespace(str(decision["reasonCode"]))
        row = conn.execute(
            """SELECT disposition, metadata_json, input_event_id
               FROM agent_memory_sources WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        if row is None:
            raise ManualMemoryReviewError(f"reviewed source disappeared: {source_id}")
        previous = str(row["disposition"])
        input_event_id = int(row["input_event_id"])
        disposition = (
            "remember"
            if logical_decision == "remember" and input_event_id in selected_event_ids
            else "not_for_memory"
        )
        reason_code = (
            logical_reason_code
            if disposition == logical_decision
            else "coalesced_source_not_selected"
        )
        metadata = _json_object(row["metadata_json"])
        metadata["manualHistoryReview"] = {
            "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
            "logicalInputId": input_id,
            "reviewer": reviewer,
            "runId": run_id,
            "logicalDecision": logical_decision,
            "effectiveDecision": disposition,
            "logicalReasonCode": logical_reason_code,
            "reasonCode": reason_code,
        }
        conn.execute(
            """UPDATE agent_memory_sources
               SET disposition = ?, disposition_reason = ?,
                   disposition_updated_at_ms = ?, processed_at_ms = ?,
                   curation_run_id = ?, metadata_json = ?
               WHERE source_id = ? AND status = 'active'""",
            (
                disposition,
                reason_code,
                timestamp,
                timestamp,
                run_id,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                source_id,
            ),
        )
        disposition_event_id = (
            "source-disposition:manual:"
            + hashlib.sha256(f"{run_id}\n{source_id}".encode("utf-8")).hexdigest()[:28]
        )
        conn.execute(
            """INSERT INTO memory_source_disposition_events(
                   event_id, source_id, previous_disposition, new_disposition,
                   reason_code, actor_kind, run_id, created_at_ms, metadata_json
               ) VALUES (?, ?, ?, ?, ?, 'system', ?, ?, ?)""",
            (
                disposition_event_id,
                source_id,
                previous,
                disposition,
                reason_code,
                run_id,
                timestamp,
                json.dumps(
                    {
                        "reviewer": reviewer,
                        "logicalInputId": input_id,
                        "logicalDecision": logical_decision,
                        "effectiveDecision": disposition,
                        "sourceTextRetainedOnlyAsEvidence": disposition == "not_for_memory",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        counts[disposition] += 1
    return counts


def _retire_existing_catalog(
    conn: sqlite3.Connection,
    *,
    manifest: Mapping[str, object],
    atoms: list[dict[str, object]],
    project: str,
    timestamp: int,
    run_id: str,
) -> dict[str, int]:
    new_atom_ids = {str(item["atomId"]) for item in atoms}
    audit = dict(manifest.get("existingMemoryAudit") or {})
    counts = {"archivedAtoms": 0, "supersededAtoms": 0, "archivedBooks": 0}
    for item in _dicts(audit.get("atoms")):
        atom_id = str(item["atomId"])
        action = str(item["action"])
        replacement = compact_whitespace(str(item.get("replacementAtomId") or ""))
        if action == "supersede":
            if replacement not in new_atom_ids:
                raise ManualMemoryReviewError(f"unknown replacement atom: {atom_id}->{replacement}")
            conn.execute(
                """UPDATE memory_atoms
                   SET status = 'superseded', claim_state = 'superseded',
                       valid_to_ms = ?, updated_at_ms = ?
                   WHERE id = ? AND scope_project = ?""",
                (timestamp, timestamp, atom_id, project),
            )
            supersession_id = (
                "supersession:manual:"
                + hashlib.sha256(f"{atom_id}->{replacement}".encode("utf-8")).hexdigest()[:24]
            )
            source_ids = _ints(
                conn.execute(
                    "SELECT source_event_ids_json FROM memory_atoms WHERE id = ?",
                    (atom_id,),
                ).fetchone()[0]
            )
            conn.execute(
                """INSERT OR REPLACE INTO memory_supersessions(
                       supersession_id, old_memory_id, new_memory_id, reason,
                       source_event_ids_json, status, created_at_ms,
                       rolled_back_at_ms, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, ?)""",
                (
                    supersession_id,
                    atom_id,
                    replacement,
                    compact_whitespace(str(item.get("reason") or "manual review replacement")),
                    json.dumps(source_ids, separators=(",", ":")),
                    timestamp,
                    json.dumps({"source": "manual_history_review", "runId": run_id}),
                ),
            )
            counts["supersededAtoms"] += 1
        else:
            conn.execute(
                """UPDATE memory_atoms
                   SET status = 'hidden', claim_state = 'retracted',
                       valid_to_ms = COALESCE(valid_to_ms, ?), updated_at_ms = ?
                   WHERE id = ? AND scope_project = ?""",
                (timestamp, timestamp, atom_id, project),
            )
            counts["archivedAtoms"] += 1
    for item in _dicts(audit.get("books")):
        conn.execute(
            """UPDATE memory_books
               SET status = 'archived', archived_at_ms = ?,
                   archive_reason = 'discarded_by_manual_review', updated_at_ms = ?
               WHERE book_id = ? AND project = ?""",
            (timestamp, timestamp, str(item["bookId"]), project),
        )
        counts["archivedBooks"] += 1
    return counts


def _insert_reviewed_atoms(
    conn: sqlite3.Connection,
    *,
    atoms: list[dict[str, object]],
    event_to_sources: Mapping[int, list[str]],
    project: str,
    run_id: str,
    timestamp: int,
    superseded_by: Mapping[str, list[str]],
) -> int:
    for atom in atoms:
        atom_id = str(atom["atomId"])
        claim_key = str(atom["claimKey"])
        text = compact_whitespace(str(atom["canonicalText"]))
        event_ids = _ints(atom.get("sourceEventIds"))
        source_ids = _strings(
            source_id
            for event_id in event_ids
            for source_id in event_to_sources.get(event_id, [])
        )
        lineage = (
            "lineage:manual:"
            + hashlib.sha256(f"{project}\n{claim_key}".encode("utf-8")).hexdigest()[:28]
        )
        predecessors = superseded_by.get(atom_id, [])
        supersedes_id = predecessors[0] if len(predecessors) == 1 else None
        conn.execute(
            """INSERT INTO memory_atoms(
                   id, kind, text, canonical_text, source_event_ids_json,
                   source_memory_ids_json, scope_app, scope_project, language,
                   confidence, quality_score, echo_risk, privacy_level, status,
                   created_at_ms, updated_at_ms, last_used_at_ms,
                   owner_kind, owner_id, claim_key, lineage_id, claim_state,
                   valid_from_ms, valid_to_ms, supersedes_id
               ) VALUES (?, ?, ?, ?, ?, ?, '', ?, 'zh', ?, ?, 0.0, 'local',
                         'active', ?, ?, NULL, 'user', 'default', ?, ?, 'current',
                         ?, NULL, ?)""",
            (
                atom_id,
                str(atom["kind"]),
                text,
                text,
                json.dumps(event_ids, separators=(",", ":")),
                json.dumps(source_ids, ensure_ascii=False, separators=(",", ":")),
                project,
                float(atom["confidence"]),
                float(atom["qualityScore"]),
                min(_event_times(conn, event_ids), default=timestamp),
                timestamp,
                claim_key,
                lineage,
                int(atom.get("validFromMs") or min(_event_times(conn, event_ids), default=timestamp)),
                supersedes_id,
            ),
        )
        for tag in _strings(atom.get("tags")):
            tag_id = _ensure_tag(conn, tag=tag, timestamp=timestamp, run_id=run_id)
            conn.execute(
                """INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
                   VALUES (?, ?, 0.95, 'user')""",
                (atom_id, str(tag_id)),
            )
    return len(atoms)


def _apply_existing_phrase_audit(
    conn: sqlite3.Connection,
    *,
    audit: list[dict[str, object]],
    exported_phrases: Mapping[str, Mapping[str, object]],
    project: str,
    run_id: str,
    reviewer: str,
    timestamp: int,
) -> dict[str, int]:
    counts = {"kept": 0, "archived": 0}
    for item in audit:
        memory_id = compact_whitespace(str(item.get("memoryId") or ""))
        action = compact_whitespace(str(item.get("action") or ""))
        reason = compact_whitespace(str(item.get("reason") or ""))
        if memory_id not in exported_phrases:
            raise ManualMemoryReviewError(f"unknown reviewed phrase: {memory_id}")
        row = conn.execute(
            """SELECT metadata_json FROM memory_items
               WHERE memory_id = ? AND kind = 'phrase' AND project = ?""",
            (memory_id, project),
        ).fetchone()
        if row is None:
            raise ManualMemoryReviewError(f"reviewed phrase disappeared: {memory_id}")
        if action == "keep":
            counts["kept"] += 1
            continue
        metadata = _json_object(row[0])
        metadata["manualHistoryReview"] = {
            "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
            "action": "archive",
            "reason": reason,
            "reviewer": reviewer,
            "runId": run_id,
        }
        updated = conn.execute(
            """UPDATE memory_items
               SET status = 'hidden', updated_at_ms = ?, metadata_json = ?
               WHERE memory_id = ? AND kind = 'phrase' AND project = ?""",
            (
                timestamp,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                memory_id,
                project,
            ),
        ).rowcount
        if int(updated or 0) != 1:
            raise ManualMemoryReviewError(f"failed to archive reviewed phrase: {memory_id}")
        counts["archived"] += 1
    return counts


def _insert_reviewed_books(
    conn: sqlite3.Connection,
    *,
    books: list[dict[str, object]],
    project: str,
    run_id: str,
    timestamp: int,
) -> int:
    for book in books:
        title = compact_whitespace(str(book["title"]))
        summary = compact_whitespace(str(book["summary"]))
        conn.execute(
            """INSERT INTO memory_books(
                   book_id, book_type, book_key, title, summary, normalized_text,
                   project, app, tags_json, surface_hints_json,
                   query_expansions_json, source_event_ids_json,
                   memory_atom_ids_json, status, confidence, quality_score,
                   created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                   last_active_at_ms, archive_reason, owner_kind, owner_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, '[]', ?, ?, ?, 'active',
                         ?, ?, ?, ?, ?, NULL, ?, '', 'user', 'default')""",
            (
                str(book["bookId"]),
                str(book.get("bookType") or "topic"),
                str(book["bookKey"]),
                title,
                summary,
                normalize_text(f"{title} {summary}"),
                project,
                json.dumps(_strings(book.get("tags")), ensure_ascii=False),
                json.dumps(_strings(book.get("queryExpansions")), ensure_ascii=False),
                json.dumps(_ints(book.get("sourceEventIds")), separators=(",", ":")),
                json.dumps(_strings(book.get("memoryAtomIds")), separators=(",", ":")),
                float(book.get("confidence") or 0.95),
                float(book.get("qualityScore") or 0.95),
                timestamp,
                timestamp,
                json.dumps(
                    {
                        "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
                        "source": "manual_history_review",
                        "runId": run_id,
                        "atomCount": len(_strings(book.get("memoryAtomIds"))),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
    return len(books)


def _replace_activity_timelines(
    conn: sqlite3.Connection,
    *,
    timelines: list[dict[str, object]],
    inputs: Mapping[str, Mapping[str, object]],
    project: str,
    reviewer: str,
    run_id: str,
    timestamp: int,
) -> dict[str, int]:
    conn.execute(
        """UPDATE daily_activity_timelines
           SET status = 'superseded', updated_at_ms = ?
           WHERE project = ? AND status IN ('draft', 'approved')""",
        (timestamp, project),
    )
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for segment in timelines:
        by_date[str(segment["date"])].append(segment)
    for timeline_date, source_segments in sorted(by_date.items()):
        segment_payloads: list[dict[str, object]] = []
        all_event_ids: list[int] = []
        for position, source_segment in enumerate(
            sorted(source_segments, key=lambda item: (str(item.get("start") or ""), str(item.get("goal") or "")))
        ):
            logical_ids = _strings(source_segment.get("evidenceLogicalInputIds"))
            event_ids = _ints(
                event_id
                for logical_id in logical_ids
                for event_id in inputs[logical_id].get("sourceEventIds", [])
            )
            all_event_ids.extend(event_ids)
            times = _event_times(conn, event_ids)
            if len(times) != len(event_ids):
                raise ManualMemoryReviewError("timeline evidence event disappeared")
            start_ms = min(times)
            end_ms = max(times)
            apps = _strings(source_segment.get("apps"))
            goal = compact_whitespace(str(source_segment["goal"]))
            actions = compact_whitespace(str(source_segment["actualActions"]))
            result = compact_whitespace(str(source_segment["resultOrBlocker"]))
            segment_hash = _payload_sha256(
                {"eventIds": event_ids, "goal": goal, "actions": actions, "result": result}
            )
            source_kinds = _strings(inputs[input_id].get("source") for input_id in logical_ids)
            evidence_refs = []
            for logical_id in logical_ids:
                source_input = inputs[logical_id]
                source_event_ids = _ints(source_input.get("sourceEventIds"))
                event_id = max(source_event_ids)
                evidence_refs.append(
                    {
                        "sourceType": "input_event",
                        "sourceId": f"event:{event_id}",
                        "eventId": event_id,
                        "eventIds": source_event_ids,
                        "logicalInputId": logical_id,
                        "coalescedSourceEventCount": len(source_event_ids),
                        "app": str(source_input.get("app") or ""),
                        "sourceKind": str(source_input.get("source") or ""),
                        "occurredAtMs": int(source_input.get("createdAtMs") or 0),
                        "preview": "[同义或重复输入已合并，原始证据按需展开]",
                    }
                )
            segment_payloads.append(
                {
                    "segmentId": f"activity-segment:review:{segment_hash[:24]}",
                    "position": position,
                    "app": apps[0] if len(apps) == 1 else "multiple",
                    "sourceKinds": source_kinds,
                    "contextGroupIds": [],
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "period": _period(start_ms, end_ms),
                    "eventCount": len(logical_ids),
                    "physicalEventCount": len(event_ids),
                    "sourceEventIds": event_ids,
                    "sourceEventHash": segment_hash,
                    "summary": f"{goal}：{actions} {result}",
                    "redactedEventCount": 0,
                    "title": goal,
                    "goal": goal,
                    "actualActions": actions,
                    "resultOrBlocker": result,
                    "apps": apps,
                    "evidenceRefs": evidence_refs,
                    "source": {"type": "input_event_bundle", "id": f"event-set:{segment_hash}"},
                }
            )
        event_ids = _ints(all_event_ids)
        timeline_hash = _payload_sha256(
            {"date": timeline_date, "eventIds": event_ids, "segments": segment_payloads}
        )
        timeline_id = f"activity-timeline:review:{timeline_hash[:24]}"
        book_id = f"book:daily:review:{timeline_hash[:24]}"
        summary_parts = [
            f"{segment['title']}：{str(segment['resultOrBlocker']).rstrip('。；; ')}"
            for segment in segment_payloads
        ]
        summary = "；".join(summary_parts) + "。"
        metadata = {
            "schemaVersion": MANUAL_MEMORY_APPLICATION_SCHEMA_VERSION,
            "segmentationMode": "semantic_task_v2",
            "derivedFrom": "reviewed_input_events",
            "manualReview": True,
            "reviewer": reviewer,
            "runId": run_id,
            "longTermFact": False,
            "automaticPromotion": False,
            "explicitApprovalRequired": False,
        }
        conn.execute(
            """INSERT INTO daily_activity_timelines(
                   timeline_id, project, timeline_date, timezone, status,
                   source_event_ids_json, source_event_hash, segments_json,
                   summary_text, event_count, segment_count, approved_book_id,
                   approved_by, approved_at_ms, rejection_reason, metadata_json,
                   created_at_ms, updated_at_ms
               ) VALUES (?, ?, ?, 'Asia/Shanghai', 'approved', ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, '', ?, ?, ?)""",
            (
                timeline_id,
                project,
                timeline_date,
                json.dumps(event_ids, separators=(",", ":")),
                timeline_hash,
                json.dumps(segment_payloads, ensure_ascii=False, sort_keys=True),
                summary,
                sum(int(item["eventCount"]) for item in segment_payloads),
                len(segment_payloads),
                book_id,
                reviewer,
                timestamp,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                timestamp,
                timestamp,
            ),
        )
        title = f"{timeline_date} 活动时间线"
        conn.execute(
            """INSERT INTO memory_books(
                   book_id, book_type, book_key, title, summary, normalized_text,
                   project, app, tags_json, surface_hints_json,
                   query_expansions_json, source_event_ids_json,
                   memory_atom_ids_json, status, confidence, quality_score,
                   created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                   last_active_at_ms, archive_reason, owner_kind, owner_id
               ) VALUES (?, 'daily', ?, ?, ?, ?, ?, 'multiple', ?, '[]', ?, ?,
                         '[]', 'active', 0.95, 0.95, ?, ?, ?, NULL, ?, '',
                         'user', 'default')""",
            (
                book_id,
                f"activity:{timeline_date}",
                title,
                summary,
                normalize_text(f"{title} {summary}"),
                project,
                json.dumps(["daily", "activity-timeline", timeline_date], ensure_ascii=False),
                json.dumps([str(item["title"]) for item in segment_payloads], ensure_ascii=False),
                json.dumps(event_ids, separators=(",", ":")),
                timestamp,
                timestamp,
                json.dumps(
                    {
                        **metadata,
                        "derivedArtifactType": "daily_activity_timeline",
                        "timelineId": timeline_id,
                        "sourceEventHash": timeline_hash,
                        "approvalStatus": "approved",
                        "segmentCount": len(segment_payloads),
                        "timelineDate": timeline_date,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
    return {"timelineCount": len(by_date), "segmentCount": len(timelines)}


def _rebuild_reviewed_groups(
    conn: sqlite3.Connection,
    *,
    books: list[dict[str, object]],
    atoms: list[dict[str, object]],
    existing_atom_ids: set[str],
    existing_book_ids: set[str],
    project: str,
    run_id: str,
    timestamp: int,
) -> dict[str, int]:
    retired_member_ids = sorted(existing_atom_ids | existing_book_ids)
    for member_id in retired_member_ids:
        conn.execute(
            "DELETE FROM memory_semantic_group_members WHERE member_id = ?",
            (member_id,),
        )
    atom_ids = {str(item["atomId"]) for item in atoms}
    membership_count = 0
    for book in books:
        group_id = _GROUP_BY_BOOK_KEY.get(str(book["bookKey"]))
        if not group_id:
            continue
        existing_group = conn.execute(
            "SELECT project FROM memory_semantic_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        if existing_group is not None and str(existing_group[0]) != project:
            raise ManualMemoryReviewError(
                f"semantic group belongs to another project: {group_id}"
            )
        source_event_ids = _ints(book.get("sourceEventIds"))
        conn.execute(
            """INSERT INTO memory_semantic_groups(
                   group_id, title, description, project, aliases_json,
                   tags_json, source_event_ids_json, status, confidence,
                   quality_score, created_at_ms, updated_at_ms, metadata_json
               ) VALUES (?, ?, ?, ?, '[]', ?, ?, 'active', 0.95, 0.95, ?, ?, ?)
               ON CONFLICT(group_id) DO UPDATE SET
                   title = excluded.title,
                   description = excluded.description,
                   project = excluded.project,
                   tags_json = excluded.tags_json,
                   source_event_ids_json = excluded.source_event_ids_json,
                   status = 'active', confidence = excluded.confidence,
                   quality_score = excluded.quality_score,
                   updated_at_ms = excluded.updated_at_ms,
                   metadata_json = excluded.metadata_json""",
            (
                group_id,
                str(book["title"]),
                str(book["summary"]),
                project,
                json.dumps(_strings(book.get("tags")), ensure_ascii=False),
                json.dumps(source_event_ids, separators=(",", ":")),
                timestamp,
                timestamp,
                json.dumps({"source": "manual_history_review", "runId": run_id}),
            ),
        )
        members = [
            atom_id for atom_id in _strings(book.get("memoryAtomIds")) if atom_id in atom_ids
        ]
        for member_type, member_id in [
            *(('atom', atom_id) for atom_id in members),
            ("book", str(book["bookId"])),
        ]:
            conn.execute(
                """INSERT INTO memory_semantic_group_members(
                       group_id, member_type, member_id, weight, source, updated_at_ms
                   ) VALUES (?, ?, ?, 0.95, 'manual_history_review', ?)
                   ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET
                       weight = excluded.weight, source = excluded.source,
                       updated_at_ms = excluded.updated_at_ms""",
                (group_id, member_type, member_id, timestamp),
            )
            membership_count += 1
    return {"groupCount": len(_GROUP_BY_BOOK_KEY), "membershipCount": membership_count}


def _retire_stale_drafts(
    conn: sqlite3.Connection,
    *,
    project: str,
    inputs: Mapping[str, Mapping[str, object]],
    run_id: str,
    timestamp: int,
    manifest_sha256: str,
) -> dict[str, int]:
    # Cleanup drafts are shared legacy state without a project key. This
    # project-scoped review must not retire unrelated runs or diffs.
    run_ids: list[str] = []
    proposal_count = int(
        conn.execute(
            """UPDATE memory_governance_proposals
               SET status = 'expired', updated_at_ms = ?
               WHERE project = ? AND status = 'preview'""",
            (timestamp, project),
        ).rowcount
        or 0
    )
    event_ids = _ints(
        event_id for item in inputs.values() for event_id in item.get("sourceEventIds", [])
    )
    last_event_id = max(event_ids, default=0)
    conn.execute(
        """INSERT INTO memory_compile_state(
               project, last_compiled_event_id, last_run_ms,
               pending_event_count, last_bundle_hash, last_drafted_event_id,
               last_draft_ms, last_draft_bundle_hash, last_draft_run_id
           ) VALUES (?, ?, ?, 0, ?, 0, 0, '', '')
           ON CONFLICT(project) DO UPDATE SET
               last_compiled_event_id = excluded.last_compiled_event_id,
               last_run_ms = excluded.last_run_ms,
               pending_event_count = 0,
               last_bundle_hash = excluded.last_bundle_hash,
               last_drafted_event_id = 0,
               last_draft_ms = 0,
               last_draft_bundle_hash = '',
               last_draft_run_id = ''""",
        (project, last_event_id, timestamp, manifest_sha256),
    )
    owner_sources: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for item in inputs.values():
        owner_sources[(str(item["ownerKind"]), str(item["ownerId"]))].append(item)
    for (owner_kind, owner_id), values in owner_sources.items():
        latest = max(values, key=lambda item: (int(item["createdAtMs"]), str(item["sourceIds"])))
        source_ids = _strings(latest.get("sourceIds"))
        conn.execute(
            """INSERT INTO memory_curation_cursors(
                   owner_kind, owner_id, project, lane,
                   last_source_created_at_ms, last_source_id, last_run_ms,
                   last_run_id, next_due_at_ms, status, consecutive_failures,
                   last_error, updated_at_ms
               ) VALUES (?, ?, ?, 'manual', ?, ?, ?, ?, 0, 'idle', 0, '', ?)
               ON CONFLICT(owner_kind, owner_id, project, lane) DO UPDATE SET
                   last_source_created_at_ms = excluded.last_source_created_at_ms,
                   last_source_id = excluded.last_source_id,
                   last_run_ms = excluded.last_run_ms,
                   last_run_id = excluded.last_run_id,
                   next_due_at_ms = 0, status = 'idle', consecutive_failures = 0,
                   last_error = '', updated_at_ms = excluded.updated_at_ms""",
            (
                owner_kind,
                owner_id,
                project,
                int(latest["createdAtMs"]),
                source_ids[-1] if source_ids else "",
                timestamp,
                run_id,
                timestamp,
            ),
        )
    return {"supersededCleanupRuns": len(run_ids), "expiredGovernanceProposals": proposal_count}


def _ensure_tag(
    conn: sqlite3.Connection,
    *,
    tag: str,
    timestamp: int,
    run_id: str,
) -> int:
    normalized = normalize_text(tag)
    conn.execute(
        """INSERT INTO memory_tags(
               tag, normalized_tag, tag_type, quality_score, created_at_ms,
               updated_at_ms, description, source, status, metadata_json
           ) VALUES (?, ?, 'concept', 0.95, ?, ?, '', 'user', 'active', ?)
           ON CONFLICT(tag) DO UPDATE SET
               normalized_tag = excluded.normalized_tag,
               quality_score = MAX(memory_tags.quality_score, excluded.quality_score),
               updated_at_ms = excluded.updated_at_ms,
               source = 'user', status = 'active', metadata_json = excluded.metadata_json""",
        (
            tag,
            normalized,
            timestamp,
            timestamp,
            json.dumps({"source": "manual_history_review", "runId": run_id}),
        ),
    )
    return int(conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()[0])


def _event_times(conn: sqlite3.Connection, event_ids: list[int]) -> list[int]:
    if not event_ids:
        return []
    placeholders = ",".join("?" for _ in event_ids)
    return [
        int(row[0])
        for row in conn.execute(
            f"SELECT created_at_ms FROM input_events WHERE id IN ({placeholders})",
            event_ids,
        ).fetchall()
    ]


def _active_artifact_event_ids(conn: sqlite3.Connection, *, project: str) -> set[int]:
    event_ids: list[int] = []
    for table, project_column, status_filter, evidence_column in (
        (
            "memory_atoms",
            "scope_project",
            "status IN ('active', 'approved') AND claim_state = 'current'",
            "source_event_ids_json",
        ),
        (
            "memory_books",
            "project",
            "status IN ('active', 'approved')",
            "source_event_ids_json",
        ),
        (
            "daily_activity_timelines",
            "project",
            "status = 'approved'",
            "source_event_ids_json",
        ),
    ):
        rows = conn.execute(
            f"SELECT {evidence_column} FROM {table} "
            f"WHERE {project_column} = ? AND {status_filter}",
            (project,),
        ).fetchall()
        for row in rows:
            event_ids.extend(_ints(row[0]))
    phrase_rows = conn.execute(
        """SELECT source_event_id, metadata_json FROM memory_items
           WHERE kind = 'phrase' AND project = ?
             AND status IN ('active', 'approved')""",
        (project,),
    ).fetchall()
    for row in phrase_rows:
        metadata = _json_object(row["metadata_json"])
        event_ids.extend(
            _ints([row["source_event_id"], *_ints(metadata.get("sourceEventIds"))])
        )
    return set(event_ids)


def _active_artifact_invalid_sources(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> list[str]:
    artifacts: list[tuple[str, str, list[int]]] = []
    for table, identifier, project_column, status_filter in (
        (
            "memory_atoms",
            "id",
            "scope_project",
            "status IN ('active', 'approved') AND claim_state = 'current'",
        ),
        (
            "memory_books",
            "book_id",
            "project",
            "status IN ('active', 'approved')",
        ),
        (
            "daily_activity_timelines",
            "timeline_id",
            "project",
            "status = 'approved'",
        ),
    ):
        for row in conn.execute(
            f"SELECT {identifier}, source_event_ids_json FROM {table} "
            f"WHERE {project_column} = ? AND {status_filter}",
            (project,),
        ).fetchall():
            artifacts.append(
                (table, str(row[identifier]), _ints(row["source_event_ids_json"]))
            )
    for row in conn.execute(
        """SELECT memory_id, source_event_id, metadata_json FROM memory_items
           WHERE kind = 'phrase' AND project = ?
             AND status IN ('active', 'approved')""",
        (project,),
    ).fetchall():
        metadata = _json_object(row["metadata_json"])
        artifacts.append(
            (
                "memory_items:phrase",
                str(row["memory_id"]),
                _ints(
                    [
                        row["source_event_id"],
                        *_ints(metadata.get("sourceEventIds")),
                    ]
                ),
            )
        )

    invalid: list[str] = []
    disposition_cache: dict[int, list[str]] = {}
    for artifact_type, artifact_id, event_ids in artifacts:
        if not event_ids:
            invalid.append(f"{artifact_type}:{artifact_id}:missing_evidence")
            continue
        for event_id in event_ids:
            dispositions = disposition_cache.get(event_id)
            if dispositions is None:
                dispositions = [
                    str(row[0])
                    for row in conn.execute(
                        """SELECT disposition FROM agent_memory_sources
                           WHERE status = 'active' AND input_event_id = ?
                           ORDER BY source_id""",
                        (event_id,),
                    ).fetchall()
                ]
                disposition_cache[event_id] = dispositions
            if not dispositions or any(value != "remember" for value in dispositions):
                invalid.append(
                    f"{artifact_type}:{artifact_id}:event:{event_id}:"
                    + (",".join(dispositions) if dispositions else "missing_source")
                )
    return invalid


def _period(start_ms: int, end_ms: int) -> str:
    start = datetime.fromtimestamp(start_ms / 1000, tz=_TIMEZONE)
    end = datetime.fromtimestamp(end_ms / 1000, tz=_TIMEZONE)
    if start.hour < 12 <= end.hour or start.hour < 18 <= end.hour:
        return "day"
    if start.hour < 12:
        return "morning"
    if start.hour < 18:
        return "afternoon"
    return "evening"


def _require_candidate_connection(
    conn: sqlite3.Connection,
    *,
    candidate_path: Path | str,
) -> Path:
    supplied = Path(candidate_path).expanduser()
    metadata = supplied.lstat()
    if supplied.is_symlink() or not supplied.is_file():
        raise ManualMemoryReviewError("candidate must be a regular non-symlink file")
    if int(metadata.st_nlink) != 1:
        raise ManualMemoryReviewError("candidate must have exactly one hard link")
    expected = supplied.resolve(strict=True)
    database_rows = conn.execute("PRAGMA database_list").fetchall()
    main_paths = [str(row[2]) for row in database_rows if str(row[1]) == "main"]
    if len(main_paths) != 1 or not main_paths[0]:
        raise ManualMemoryReviewError("candidate connection is not file-backed")
    actual = Path(main_paths[0]).expanduser().resolve(strict=True)
    if not actual.samefile(expected):
        raise ManualMemoryReviewError(
            f"candidate connection path mismatch: expected={expected},actual={actual}"
        )
    formal_paths = {
        (Path.home() / "Library/Application Support/RagIme/rag-ime.sqlite").resolve(
            strict=False
        )
    }
    configured = compact_whitespace(os.environ.get("RAG_IME_DB_PATH", ""))
    if configured:
        formal_paths.add(Path(configured).expanduser().resolve(strict=False))
    if any(actual == formal for formal in formal_paths):
        raise ManualMemoryReviewError("refusing to mutate the formal production database")
    return actual


def _superseded_predecessors(
    manifest: Mapping[str, object],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    audit = dict(manifest.get("existingMemoryAudit") or {})
    for item in _dicts(audit.get("atoms")):
        if str(item.get("action") or "") != "supersede":
            continue
        old_id = compact_whitespace(str(item.get("atomId") or ""))
        new_id = compact_whitespace(str(item.get("replacementAtomId") or ""))
        if old_id and new_id and old_id not in result[new_id]:
            result[new_id].append(old_id)
    return dict(result)


def _table_fingerprint(conn: sqlite3.Connection, table: str) -> str:
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
    digest = hashlib.sha256()
    for row in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"):
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


def _payload_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _json_object(raw: object) -> dict[str, object]:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _dicts(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [dict(value) for value in raw if isinstance(value, Mapping)]


def _strings(raw: object) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    else:
        try:
            values = list(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            values = [raw]
    return list(
        dict.fromkeys(
            compact_whitespace(str(value or ""))
            for value in values
            if compact_whitespace(str(value or ""))
        )
    )


def _stored_strings(raw: object) -> list[str]:
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = raw
        return _strings(decoded)
    return _strings(raw)


def _ints(raw: object) -> list[int]:
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = [raw]
        values = decoded if isinstance(decoded, list) else [decoded]
    else:
        try:
            values = list(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            values = [raw]
    result: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result
