from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Mapping

from .activity_timeline import DailyActivityTimelineStore, TIMELINE_SEGMENTATION_MODE
from .db import apply_database_migrations, migration_status
from .db.migration_runner import DEFAULT_MIGRATIONS_DIR
from .embeddings import EmbeddingProvider
from .memory_ingest import normalize_text
from .memory_projection import (
    RETRIEVAL_DOCS_PROJECTION,
    enqueue_memory_projection,
    memory_projection_freshness,
    process_memory_projection_outbox,
)
from .retrieval_docs import expected_retrieval_docs
from .text_utils import compact_whitespace, now_ms


SEMANTIC_MEMORY_MIGRATION_SCHEMA_VERSION = "rag-ime.semantic-memory-migration.v1"
_SEMANTIC_TIMELINE_MODE = TIMELINE_SEGMENTATION_MODE
_LEGACY_TIMELINE_MODE = "legacy_app_interval_v1"
_MIN_PROMOTABLE_CONFIDENCE = 0.8
_MIN_PROMOTABLE_TEXT_LENGTH = 12


class SemanticMemoryMigrationError(RuntimeError):
    pass


def preview_semantic_memory_migration(
    conn: sqlite3.Connection,
    *,
    project: str = "",
) -> dict[str, object]:
    """Inspect the legacy surface without mutating the database."""

    conn.row_factory = sqlite3.Row
    legacy_items = _legacy_memory_items(conn, project=project)
    decisions = [_legacy_item_decision(conn, row) for row in legacy_items]
    timeline_rows = _legacy_draft_rows(conn, project=project)
    return {
        "schemaVersion": SEMANTIC_MEMORY_MIGRATION_SCHEMA_VERSION,
        "mode": "preview",
        "project": compact_whitespace(project),
        "migrationStatus": migration_status(conn),
        "legacyItems": {
            "active": len(legacy_items),
            "promotable": sum(decision["disposition"] == "promote" for decision in decisions),
            "quarantined": sum(decision["disposition"] == "quarantine" for decision in decisions),
            "items": decisions,
        },
        "legacyTimelineDrafts": {
            "count": len(timeline_rows),
            "items": [
                {
                    "timelineId": str(row["timeline_id"]),
                    "project": str(row["project"] or ""),
                    "date": str(row["timeline_date"]),
                    "eventCount": int(row["event_count"] or 0),
                    "segmentCount": int(row["segment_count"] or 0),
                }
                for row in timeline_rows
            ],
        },
        "missingAtomClaimKeys": _count_missing_atom_lineage(conn),
        "legacyRetrievalDocuments": _count(
            conn,
            "SELECT COUNT(*) FROM memory_retrieval_docs WHERE doc_type = 'item'",
        ),
        "protectedState": _protected_state(conn),
    }


def migrate_semantic_memory_database(
    db_path: str | Path,
    *,
    project: str = "",
    timezone_name: str = "Asia/Shanghai",
    embedding_provider: EmbeddingProvider | None = None,
    require_vector_freshness: bool = False,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> dict[str, object]:
    """Upgrade one writable candidate DB; callers own backup and activation.

    This function never approves a Timeline, User Memory draft, Topic Book, or
    Role Book. Already-approved legacy memory items may be translated into
    governed Atoms only when their stored evidence, reason, confidence, and
    sentence completeness pass a deterministic compatibility gate.
    """

    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    timestamp = now_ms()
    with _connect(path) as conn:
        protected_before = _protected_state(conn)
        migration_result = apply_database_migrations(
            conn,
            migrations_dir=migrations_dir,
        )
        legacy_report = _migrate_legacy_items(
            conn,
            project=project,
            timestamp=timestamp,
        )
        outbox_id = enqueue_memory_projection(
            conn,
            projection_kind=RETRIEVAL_DOCS_PROJECTION,
            aggregate_type="project",
            aggregate_id=compact_whitespace(project) or "all",
            operation="semantic_memory_v2_migration",
            project=project,
            payload={
                "source": SEMANTIC_MEMORY_MIGRATION_SCHEMA_VERSION,
                "legacyItemsPromoted": int(legacy_report["promoted"]),
                "legacyItemsQuarantined": int(legacy_report["quarantined"]),
            },
        )
        conn.commit()

    timeline_report = _rebuild_legacy_timeline_drafts(
        path,
        project=project,
        timezone_name=timezone_name,
        timestamp=timestamp,
    )

    with _connect(path) as conn:
        projection_report = _drain_projection_outbox(
            conn,
            embedding_provider=embedding_provider,
            migrations_dir=migrations_dir,
        )
        protected_after = _protected_state(conn)
        if protected_after != protected_before:
            raise SemanticMemoryMigrationError(
                "protected evidence, approved artifacts, or role books changed during migration"
            )
        verification = verify_semantic_memory_database(
            conn,
            project=project,
            provider_fingerprint=str(
                getattr(embedding_provider, "fingerprint", "") or ""
            ),
            require_vector_freshness=require_vector_freshness,
        )
        if not bool(verification["ok"]):
            raise SemanticMemoryMigrationError(
                "semantic memory verification failed: "
                + "; ".join(str(value) for value in verification["errors"])
            )

    return {
        "schemaVersion": SEMANTIC_MEMORY_MIGRATION_SCHEMA_VERSION,
        "mode": "migrated_candidate",
        "databasePath": str(path),
        "project": compact_whitespace(project),
        "migration": migration_result.payload(),
        "legacyItems": legacy_report,
        "timelines": timeline_report,
        "projectionOutboxId": outbox_id,
        "projections": projection_report,
        "protectedState": protected_after,
        "verification": verification,
        "startedAtMs": timestamp,
        "finishedAtMs": now_ms(),
        "policy": {
            "inputEventsImmutable": True,
            "approvedArtifactsImmutable": True,
            "roleBooksImmutable": True,
            "autoApproval": False,
            "legacyItemsRetainedForAudit": True,
        },
    }


def verify_semantic_memory_database(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    provider_fingerprint: str = "",
    require_vector_freshness: bool = False,
) -> dict[str, object]:
    conn.row_factory = sqlite3.Row
    errors: list[str] = []
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    missing_lineage = _count_missing_atom_lineage(conn)
    duplicate_claims = _duplicate_current_claims(conn)
    legacy_items = len(_legacy_memory_items(conn, project=project))
    legacy_docs = _count(
        conn,
        "SELECT COUNT(*) FROM memory_retrieval_docs WHERE doc_type = 'item'",
    )
    legacy_drafts = len(_legacy_draft_rows(conn, project=project))
    broken_book_refs = _broken_book_atom_refs(conn)
    artifact_evidence_errors = _active_artifact_evidence_errors(conn)
    timeline_errors = _timeline_conservation_errors(conn, project=project)
    fts_orphans = _fts_orphan_count(conn)
    vector_orphans = _count(
        conn,
        """SELECT COUNT(*) FROM memory_retrieval_doc_vectors v
           LEFT JOIN memory_retrieval_docs d ON d.doc_id = v.doc_id
           WHERE d.doc_id IS NULL""",
    )
    if integrity != "ok":
        errors.append(f"integrity_check={integrity}")
    if foreign_keys:
        errors.append(f"foreign_key_violations={len(foreign_keys)}")
    if missing_lineage:
        errors.append(f"atoms_missing_claim_lineage={missing_lineage}")
    if duplicate_claims:
        errors.append(f"duplicate_current_claims={len(duplicate_claims)}")
    if legacy_items:
        errors.append(f"active_legacy_items={legacy_items}")
    if legacy_docs:
        errors.append(f"legacy_item_docs={legacy_docs}")
    if legacy_drafts:
        errors.append(f"legacy_timeline_drafts={legacy_drafts}")
    if broken_book_refs:
        errors.append(f"broken_book_atom_refs={len(broken_book_refs)}")
    if artifact_evidence_errors:
        errors.append(
            f"active_artifact_evidence_errors={len(artifact_evidence_errors)}"
        )
    if timeline_errors:
        errors.append(f"timeline_conservation_errors={len(timeline_errors)}")
    if fts_orphans:
        errors.append(f"retrieval_fts_orphans={fts_orphans}")
    if vector_orphans:
        errors.append(f"retrieval_vector_orphans={vector_orphans}")

    configured_fingerprint = compact_whitespace(provider_fingerprint)
    provider_enabled = bool(
        configured_fingerprint and configured_fingerprint != "none"
    )
    fingerprint = configured_fingerprint
    if not fingerprint and not require_vector_freshness:
        row = conn.execute(
            """SELECT provider_fingerprint, COUNT(*) AS count
               FROM memory_retrieval_doc_vectors
               GROUP BY provider_fingerprint
               ORDER BY count DESC, provider_fingerprint
               LIMIT 1"""
        ).fetchone()
        fingerprint = str(row["provider_fingerprint"] or "") if row is not None else ""
    vector_freshness = memory_projection_freshness(
        conn,
        provider_fingerprint=fingerprint,
    )
    vector_gate_required = bool(require_vector_freshness or provider_enabled)
    expected_doc_ids = {
        str(doc["doc_id"])
        for doc in expected_retrieval_docs(conn, project="")
    }
    active_doc_ids = {
        str(row[0])
        for row in conn.execute(
            "SELECT doc_id FROM memory_retrieval_docs WHERE status = 'active'"
        ).fetchall()
    }
    missing_projected_doc_ids = sorted(expected_doc_ids - active_doc_ids)
    unexpected_active_doc_ids = sorted(active_doc_ids - expected_doc_ids)
    extra_provider_vectors = 0
    latest_vector_outbox_error = ""
    if provider_enabled:
        extra_provider_vectors = _count(
            conn,
            """SELECT COUNT(*)
               FROM memory_retrieval_doc_vectors AS vector
               LEFT JOIN memory_retrieval_docs AS doc ON doc.doc_id = vector.doc_id
               WHERE vector.provider_fingerprint = ?
                 AND (doc.doc_id IS NULL OR doc.status != 'active')""",
            (configured_fingerprint,),
        )
        latest_vector_row = conn.execute(
            """SELECT state, last_error
               FROM memory_projection_outbox
               WHERE projection_kind = 'retrieval_vectors'
               ORDER BY outbox_id DESC LIMIT 1"""
        ).fetchone()
        if latest_vector_row is not None:
            latest_vector_outbox_error = compact_whitespace(
                str(latest_vector_row["last_error"] or "")
            )

    projection_checkpoints: dict[str, dict[str, object]] = {}
    for projection_kind in ("retrieval_docs", "retrieval_vectors"):
        latest_id = int(
            dict(vector_freshness.get("latestOutboxIds") or {}).get(
                projection_kind, 0
            )
            or 0
        )
        checkpoint_id = int(
            dict(
                dict(vector_freshness.get("checkpoints") or {}).get(
                    projection_kind, {}
                )
                or {}
            ).get("lastOutboxId", 0)
            or 0
        )
        projection_checkpoints[projection_kind] = {
            "latestOutboxId": latest_id,
            "checkpointOutboxId": checkpoint_id,
            "caughtUp": latest_id > 0 and checkpoint_id == latest_id,
        }

    if vector_gate_required:
        if missing_projected_doc_ids:
            errors.append(
                "retrieval_docs_missing_from_projection="
                f"{len(missing_projected_doc_ids)}"
            )
        if unexpected_active_doc_ids:
            errors.append(
                "retrieval_docs_unexpected_active="
                f"{len(unexpected_active_doc_ids)}"
            )
        if not provider_enabled:
            errors.append("embedding_provider_disabled")
        else:
            retrieval_documents = int(
                vector_freshness.get("retrievalDocuments") or 0
            )
            vector_documents = int(vector_freshness.get("vectorDocuments") or 0)
            missing_vectors = int(vector_freshness.get("missingVectors") or 0)
            stale_vectors = int(vector_freshness.get("staleVectors") or 0)
            if retrieval_documents != vector_documents or extra_provider_vectors:
                errors.append(
                    "retrieval_vector_parity="
                    f"docs:{retrieval_documents},vectors:{vector_documents},"
                    f"extra:{extra_provider_vectors}"
                )
            if missing_vectors:
                errors.append(f"retrieval_vectors_missing={missing_vectors}")
            if stale_vectors:
                errors.append(f"retrieval_vectors_stale={stale_vectors}")
            for projection_kind, checkpoint in projection_checkpoints.items():
                if not bool(checkpoint["caughtUp"]):
                    errors.append(
                        f"{projection_kind}_checkpoint_lag="
                        f"latest:{checkpoint['latestOutboxId']},"
                        f"checkpoint:{checkpoint['checkpointOutboxId']}"
                    )
            states = dict(vector_freshness.get("states") or {})
            for state in ("pending", "processing", "failed", "dead"):
                count = int(states.get(state) or 0)
                if count:
                    errors.append(f"projection_outbox_{state}={count}")
            if latest_vector_outbox_error:
                errors.append(
                    "latest_retrieval_vectors_error=" + latest_vector_outbox_error
                )
            if not bool(vector_freshness.get("fresh")):
                errors.append("memory_projection_not_fresh")
    return {
        "schemaVersion": "rag-ime.semantic-memory-verification.v1",
        "ok": not errors,
        "errors": errors,
        "integrityCheck": integrity,
        "foreignKeyViolationCount": len(foreign_keys),
        "atomsMissingClaimLineage": missing_lineage,
        "duplicateCurrentClaims": duplicate_claims,
        "activeLegacyItems": legacy_items,
        "legacyRetrievalDocuments": legacy_docs,
        "legacyTimelineDrafts": legacy_drafts,
        "brokenBookAtomRefs": broken_book_refs,
        "activeArtifactEvidenceErrors": artifact_evidence_errors,
        "timelineConservationErrors": timeline_errors,
        "retrievalFtsOrphans": fts_orphans,
        "retrievalVectorOrphans": vector_orphans,
        "vectorGateRequired": vector_gate_required,
        "embeddingProviderEnabled": provider_enabled,
        "activationEligible": bool(vector_gate_required and not errors),
        "vectorProviderFingerprint": fingerprint,
        "extraProviderVectors": extra_provider_vectors,
        "projectionCheckpoints": projection_checkpoints,
        "latestVectorOutboxError": latest_vector_outbox_error,
        "expectedRetrievalDocuments": len(expected_doc_ids),
        "activeRetrievalDocuments": len(active_doc_ids),
        "missingProjectedDocIds": missing_projected_doc_ids[:50],
        "unexpectedActiveDocIds": unexpected_active_doc_ids[:50],
        "projectionFreshness": vector_freshness,
    }


def _migrate_legacy_items(
    conn: sqlite3.Connection,
    *,
    project: str,
    timestamp: int,
) -> dict[str, object]:
    rows = _legacy_memory_items(conn, project=project)
    existing_atoms = {
        normalize_text(str(row["canonical_text"] or row["text"] or "")): row
        for row in conn.execute(
            """SELECT id, text, canonical_text, source_memory_ids_json
               FROM memory_atoms
               WHERE status IN ('active', 'approved') AND claim_state = 'current'"""
        ).fetchall()
        if normalize_text(str(row["canonical_text"] or row["text"] or ""))
    }
    promoted: list[dict[str, str]] = []
    quarantined: list[dict[str, str]] = []
    for row in rows:
        decision = _legacy_item_decision(conn, row)
        memory_id = str(row["memory_id"])
        metadata = _json_object(row["metadata_json"])
        if decision["disposition"] == "promote":
            normalized = normalize_text(str(row["text"] or ""))
            existing = existing_atoms.get(normalized)
            if existing is not None:
                atom_id = str(existing["id"])
                source_ids = _json_strings(existing["source_memory_ids_json"])
                if memory_id not in source_ids:
                    source_ids.append(memory_id)
                    conn.execute(
                        """UPDATE memory_atoms
                           SET source_memory_ids_json = ?, updated_at_ms = ?
                           WHERE id = ?""",
                        (_json(source_ids), timestamp, atom_id),
                    )
                migration_reason = "linked_to_existing_atom"
            else:
                atom_id = _legacy_atom_id(memory_id)
                event_ids = [
                    value
                    for value in _legacy_evidence_event_ids(row)
                    if _event_is_visible(conn, value)
                ]
                confidence = float(decision["confidence"])
                claim_key = f"legacy-item:{_digest(memory_id)[:32]}"
                lineage_id = f"lineage:{claim_key}"
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, kind, text, canonical_text, source_event_ids_json,
                        source_memory_ids_json, scope_app, scope_project, language,
                        confidence, quality_score, echo_risk, privacy_level, status,
                        created_at_ms, updated_at_ms, last_used_at_ms, owner_kind,
                        owner_id, claim_key, lineage_id, claim_state, valid_from_ms,
                        valid_to_ms, supersedes_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'zh', ?, ?, 0.0, ?,
                              'approved', ?, ?, NULL, ?, ?, ?, ?, 'current', ?, NULL, NULL)
                    """,
                    (
                        atom_id,
                        _legacy_atom_kind(metadata),
                        compact_whitespace(str(row["text"] or "")),
                        normalize_text(str(row["text"] or "")),
                        _json(event_ids),
                        _json([memory_id]),
                        str(row["app"] or "") or None,
                        str(row["project"] or "") or None,
                        confidence,
                        confidence,
                        str(row["privacy_class"] or "local"),
                        int(row["created_at_ms"] or timestamp),
                        timestamp,
                        str(row["owner_kind"] or "user"),
                        str(row["owner_id"] or "default"),
                        claim_key,
                        lineage_id,
                        int(row["created_at_ms"] or timestamp),
                    ),
                )
                existing_atoms[normalized] = {
                    "id": atom_id,
                    "text": row["text"],
                    "canonical_text": normalize_text(str(row["text"] or "")),
                    "source_memory_ids_json": _json([memory_id]),
                }
                migration_reason = "translated_to_governed_atom"
            promoted.append({"memoryId": memory_id, "atomId": atom_id})
            migration_payload = {
                "status": "migrated_to_atom",
                "atomId": atom_id,
                "reason": migration_reason,
            }
        else:
            quarantined.append(
                {"memoryId": memory_id, "reason": str(decision["reason"])}
            )
            migration_payload = {
                "status": "quarantined",
                "reason": str(decision["reason"]),
            }
        metadata["semanticV2Migration"] = {
            "schemaVersion": SEMANTIC_MEMORY_MIGRATION_SCHEMA_VERSION,
            "migratedAtMs": timestamp,
            **migration_payload,
        }
        conn.execute(
            """UPDATE memory_items
               SET status = 'hidden', metadata_json = ?, updated_at_ms = ?
               WHERE id = ?""",
            (_json(metadata), timestamp, int(row["id"])),
        )
    conn.commit()
    return {
        "examined": len(rows),
        "promoted": len(promoted),
        "quarantined": len(quarantined),
        "promotions": promoted,
        "quarantines": quarantined,
        "sourceRowsDeleted": 0,
    }


def _rebuild_legacy_timeline_drafts(
    db_path: Path,
    *,
    project: str,
    timezone_name: str,
    timestamp: int,
) -> dict[str, object]:
    with _connect(db_path) as conn:
        rows = _legacy_draft_rows(conn, project=project)
    rebuilt: list[dict[str, object]] = []
    superseded: list[str] = []
    for row in rows:
        timeline_project = str(row["project"] or "")
        timeline_date = str(row["timeline_date"])
        timeline_id = str(row["timeline_id"])
        with _connect(db_path) as conn:
            canonical = conn.execute(
                """SELECT timeline_id FROM daily_activity_timelines
                   WHERE project = ? AND timeline_date = ?
                     AND status IN ('approved', 'draft')
                     AND timeline_id <> ?
                     AND json_extract(metadata_json, '$.segmentationMode') = ?
                   ORDER BY CASE status WHEN 'approved' THEN 0 ELSE 1 END,
                            updated_at_ms DESC LIMIT 1""",
                (timeline_project, timeline_date, timeline_id, _SEMANTIC_TIMELINE_MODE),
            ).fetchone()
            approved = conn.execute(
                """SELECT timeline_id FROM daily_activity_timelines
                   WHERE project = ? AND timeline_date = ? AND status = 'approved'
                   LIMIT 1""",
                (timeline_project, timeline_date),
            ).fetchone()
            if canonical is not None or approved is not None:
                conn.execute(
                    """UPDATE daily_activity_timelines
                       SET status = 'superseded', updated_at_ms = ?
                       WHERE timeline_id = ? AND status = 'draft'""",
                    (timestamp, timeline_id),
                )
                conn.commit()
                superseded.append(timeline_id)
                continue
        result = DailyActivityTimelineStore(
            db_path,
            project=timeline_project,
            timezone_name=timezone_name,
        ).build_draft(timeline_date, generated_at_ms=timestamp)
        rebuilt.append(
            {
                "legacyTimelineId": timeline_id,
                "timelineId": str(dict(result.get("timeline") or {}).get("timelineId") or ""),
                "project": timeline_project,
                "date": timeline_date,
                "created": bool(result.get("created")),
                "status": str(result.get("status") or ""),
                "segmentCount": int(
                    dict(result.get("timeline") or {}).get("segmentCount") or 0
                ),
            }
        )
    return {
        "legacyDraftsExamined": len(rows),
        "rebuilt": rebuilt,
        "supersededBecauseCanonicalExists": superseded,
        "approved": 0,
    }


def _drain_projection_outbox(
    conn: sqlite3.Connection,
    *,
    embedding_provider: EmbeddingProvider | None,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for _ in range(8):
        report = process_memory_projection_outbox(
            conn,
            embedding_provider=embedding_provider,
            max_events=512,
            migrations_dir=migrations_dir,
        )
        reports.append(report)
        if int(report.get("processed") or 0) == 0:
            break
    return {
        "runs": reports,
        "providerFingerprint": str(
            getattr(embedding_provider, "fingerprint", "") or ""
        ),
    }


def _legacy_memory_items(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """SELECT * FROM memory_items
               WHERE status IN ('active', 'approved')
                 AND kind NOT IN ('phrase', 'raw_event')
                 AND (? = '' OR project = ? OR project = '')
               ORDER BY updated_at_ms DESC, id DESC""",
            (compact_whitespace(project), compact_whitespace(project)),
        ).fetchall()
    )


def _legacy_item_decision(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, object]:
    metadata = _json_object(row["metadata_json"])
    text = compact_whitespace(str(row["text"] or ""))
    confidence = _safe_float(metadata.get("confidence"), default=0.0)
    reason = compact_whitespace(str(metadata.get("reason") or ""))
    evidence_ids = _legacy_evidence_event_ids(row)
    valid_evidence = sum(_event_is_visible(conn, event_id) for event_id in evidence_ids)
    failure = ""
    if len(text) < _MIN_PROMOTABLE_TEXT_LENGTH:
        failure = "text_fragment"
    elif confidence < _MIN_PROMOTABLE_CONFIDENCE:
        failure = "confidence_below_0.8"
    elif not reason:
        failure = "missing_review_reason"
    elif not evidence_ids or valid_evidence != len(evidence_ids):
        failure = "missing_source_evidence"
    return {
        "memoryId": str(row["memory_id"]),
        "textPreview": text[:120],
        "confidence": confidence,
        "evidenceEventIds": evidence_ids,
        "validEvidenceCount": valid_evidence,
        "disposition": "quarantine" if failure else "promote",
        "reason": failure or "approved_evidence_backed_legacy_memory",
    }


def _legacy_evidence_event_ids(row: sqlite3.Row) -> list[int]:
    metadata = _json_object(row["metadata_json"])
    values = metadata.get("evidenceEventIds")
    result = _json_ints(values)
    source_event_id = int(row["source_event_id"] or 0)
    if source_event_id > 0 and source_event_id not in result:
        result.append(source_event_id)
    return result


def _legacy_atom_kind(metadata: Mapping[str, object]) -> str:
    tags = {
        compact_whitespace(str(value)).lower()
        for value in metadata.get("tags", [])
        if compact_whitespace(str(value))
    } if isinstance(metadata.get("tags"), list) else set()
    if "preference" in tags:
        return "durable_preference"
    if "project_requirement" in tags:
        return "project_requirement"
    if tags.intersection({"memory_policy", "workflow"}):
        return "project_decision"
    return "project_fact"


def _event_is_visible(conn: sqlite3.Connection, event_id: int) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM input_events event
            LEFT JOIN memory_state state ON state.event_id = event.id
            WHERE event.id = ? AND COALESCE(state.deleted, 0) = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_tombstones tombstone
                  WHERE tombstone.active = 1
                    AND (
                        (tombstone.target_type = 'source_event_id'
                         AND tombstone.target_value = CAST(event.id AS TEXT))
                        OR
                        (tombstone.target_type = 'memory_id'
                         AND tombstone.target_value = ('event:' || event.id))
                    )
              )
            LIMIT 1
            """,
            (int(event_id),),
        ).fetchone()
        is not None
    )


def _event_is_available_as_evidence(
    conn: sqlite3.Connection,
    event_id: int,
) -> bool:
    """Return whether an immutable source event can still support an artifact.

    ``memory_state.deleted`` only hides a raw input row from direct recall. The
    manual curation pipeline deliberately hides those raw rows after deriving
    reviewed Atoms, Books, Timelines, and Phrases from them. An explicit
    tombstone, in contrast, is the user's forget boundary and invalidates the
    evidence transitively.
    """
    return (
        conn.execute(
            """
            SELECT 1
            FROM input_events event
            WHERE event.id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_tombstones tombstone
                  WHERE tombstone.active = 1
                    AND (
                        (tombstone.target_type = 'source_event_id'
                         AND tombstone.target_value = CAST(event.id AS TEXT))
                        OR
                        (tombstone.target_type = 'memory_id'
                         AND tombstone.target_value = ('event:' || event.id))
                    )
              )
            LIMIT 1
            """,
            (int(event_id),),
        ).fetchone()
        is not None
    )


def _legacy_draft_rows(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """SELECT * FROM daily_activity_timelines
               WHERE status = 'draft'
                 AND (? = '' OR project = ?)
                 AND COALESCE(json_extract(metadata_json, '$.segmentationMode'), '') <> ?
               ORDER BY timeline_date, project, updated_at_ms""",
            (compact_whitespace(project), compact_whitespace(project), _SEMANTIC_TIMELINE_MODE),
        ).fetchall()
    )


def _protected_state(conn: sqlite3.Connection) -> dict[str, object]:
    return {
        "inputEvents": _table_snapshot(conn, "input_events"),
        "agentEvidence": _table_snapshot(conn, "agent_memory_evidence"),
        "approvedTimelines": _table_snapshot(
            conn,
            "daily_activity_timelines",
            where="status = 'approved'",
        ),
        "memoryBooks": _table_snapshot(conn, "memory_books"),
        "roleBookRevisions": _table_snapshot(conn, "agent_role_book_revisions"),
    }


def _table_snapshot(
    conn: sqlite3.Connection,
    table: str,
    *,
    where: str = "",
) -> dict[str, object]:
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
    if not columns:
        return {"rows": 0, "sha256": _digest("")}
    order = ", ".join(columns)
    query = f"SELECT {order} FROM {table}"
    if where:
        query += f" WHERE {where}"
    query += f" ORDER BY {order}"
    digest = hashlib.sha256()
    count = 0
    for row in conn.execute(query):
        payload = [row[column] for column in columns]
        digest.update(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
        count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def _count_missing_atom_lineage(conn: sqlite3.Connection) -> int:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory_atoms)")}
    if not {"claim_key", "lineage_id"}.issubset(columns):
        return _count(conn, "SELECT COUNT(*) FROM memory_atoms")
    return _count(
        conn,
        """SELECT COUNT(*) FROM memory_atoms
           WHERE trim(COALESCE(claim_key, '')) = ''
              OR trim(COALESCE(lineage_id, '')) = ''""",
    )


def _duplicate_current_claims(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return [
        {
            "ownerKind": str(row["owner_kind"]),
            "ownerId": str(row["owner_id"]),
            "project": str(row["scope_project"] or ""),
            "app": str(row["scope_app"] or ""),
            "claimKey": str(row["claim_key"]),
            "count": int(row["count"]),
        }
        for row in conn.execute(
            """SELECT owner_kind, owner_id, scope_project, scope_app,
                      claim_key, COUNT(*) AS count
               FROM memory_atoms
               WHERE status IN ('active', 'approved') AND claim_state = 'current'
                 AND trim(COALESCE(claim_key, '')) <> ''
               GROUP BY owner_kind, owner_id, COALESCE(scope_project, ''),
                        COALESCE(scope_app, ''), claim_key
               HAVING COUNT(*) > 1"""
        ).fetchall()
    ]


def _broken_book_atom_refs(conn: sqlite3.Connection) -> list[dict[str, str]]:
    atom_ids = {str(row[0]) for row in conn.execute("SELECT id FROM memory_atoms")}
    broken: list[dict[str, str]] = []
    for row in conn.execute("SELECT book_id, memory_atom_ids_json FROM memory_books"):
        for atom_id in _json_strings(row["memory_atom_ids_json"]):
            if atom_id not in atom_ids:
                broken.append({"bookId": str(row["book_id"]), "atomId": atom_id})
    return broken


def _active_artifact_evidence_errors(
    conn: sqlite3.Connection,
) -> list[dict[str, object]]:
    artifacts: list[tuple[str, str, list[int]]] = []
    for table, artifact_type, identifier, status_filter in (
        (
            "memory_atoms",
            "atom",
            "id",
            "status IN ('active', 'approved') AND claim_state = 'current'",
        ),
        (
            "memory_books",
            "book",
            "book_id",
            "status IN ('active', 'approved')",
        ),
        (
            "daily_activity_timelines",
            "timeline",
            "timeline_id",
            "status = 'approved'",
        ),
    ):
        for row in conn.execute(
            f"SELECT {identifier}, source_event_ids_json FROM {table} "
            f"WHERE {status_filter}"
        ).fetchall():
            artifacts.append(
                (
                    artifact_type,
                    str(row[identifier]),
                    _json_ints(row["source_event_ids_json"]),
                )
            )
    for row in conn.execute(
        """SELECT memory_id, source_event_id, metadata_json
           FROM memory_items
           WHERE kind = 'phrase' AND status IN ('active', 'approved')"""
    ).fetchall():
        metadata = _json_object(row["metadata_json"])
        event_ids = _json_ints(metadata.get("sourceEventIds"))
        source_event_id = int(row["source_event_id"] or 0)
        if source_event_id > 0 and source_event_id not in event_ids:
            event_ids.append(source_event_id)
        artifacts.append(("phrase", str(row["memory_id"]), event_ids))

    errors: list[dict[str, object]] = []
    visibility_cache: dict[int, bool] = {}
    disposition_cache: dict[int, list[str]] = {}
    for artifact_type, artifact_id, event_ids in artifacts:
        if not event_ids:
            if artifact_type == "atom" and _atom_has_governed_evidence(
                conn,
                atom_id=artifact_id,
            ):
                continue
            errors.append(
                {
                    "artifactType": artifact_type,
                    "artifactId": artifact_id,
                    "reason": "missing_source_evidence",
                    "eventIds": [],
                }
            )
            continue
        invisible: list[int] = []
        governed_not_remembered: list[int] = []
        for event_id in event_ids:
            visible = visibility_cache.get(event_id)
            if visible is None:
                visible = _event_is_available_as_evidence(conn, event_id)
                visibility_cache[event_id] = visible
            if not visible:
                invisible.append(event_id)
                continue
            # Phrase and Timeline are non-personal projections over observable
            # input history. A pending/rejected personal-Memory disposition
            # cannot erase their separate UI/retrieval purpose. They still
            # fail closed above when the input event is missing or forgotten.
            if artifact_type in {"phrase", "timeline"}:
                continue
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
            # Older evidence may predate agent_memory_sources. Once an event is
            # governed by that table, every active source must agree to remember
            # it; a mixed decision is a fail-closed activation error.
            if dispositions and any(
                value not in {"remember", "consolidated"}
                for value in dispositions
            ):
                governed_not_remembered.append(event_id)
        if invisible:
            errors.append(
                {
                    "artifactType": artifact_type,
                    "artifactId": artifact_id,
                    "reason": "missing_or_forgotten_source_evidence",
                    "eventIds": invisible,
                }
            )
        if governed_not_remembered:
            errors.append(
                {
                    "artifactType": artifact_type,
                    "artifactId": artifact_id,
                    "reason": "source_disposition_not_fully_remembered",
                    "eventIds": governed_not_remembered,
                }
            )
    return errors


def _atom_has_governed_evidence(
    conn: sqlite3.Connection,
    *,
    atom_id: str,
) -> bool:
    """Accept evidence-led Agent memories that intentionally have no input event.

    Explicitly governed memories use immutable ``agent_memory_evidence`` rows
    and an applied proposal rather than ``input_events``. The link digest is
    checked so a dangling or stale evidence reference cannot satisfy the gate.
    """

    return (
        conn.execute(
            """
            SELECT 1
            FROM memory_atom_evidence_links AS link
            JOIN agent_memory_evidence AS evidence
              ON evidence.evidence_id = link.evidence_id
            JOIN memory_governance_proposals AS proposal
              ON proposal.proposal_id = link.proposal_id
            WHERE link.memory_atom_id = ?
              AND link.relation IN ('supports', 'corrects')
              AND evidence.status = 'active'
              AND proposal.status = 'applied'
              AND proposal.applied_memory_id = link.memory_atom_id
              AND link.content_sha256 = evidence.content_sha256
            LIMIT 1
            """,
            (atom_id,),
        ).fetchone()
        is not None
    )


def _timeline_conservation_errors(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    rows = conn.execute(
        """SELECT timeline_id, source_event_ids_json, segments_json, event_count
           FROM daily_activity_timelines
           WHERE status IN ('draft', 'approved') AND (? = '' OR project = ?)
             AND json_extract(metadata_json, '$.segmentationMode') = ?""",
        (
            compact_whitespace(project),
            compact_whitespace(project),
            _SEMANTIC_TIMELINE_MODE,
        ),
    ).fetchall()
    for row in rows:
        source_ids = _json_ints(row["source_event_ids_json"])
        segment_ids: list[int] = []
        declared_segment_events = 0
        declared_physical_events = 0
        has_physical_counts = False
        for segment in _json_objects(row["segments_json"]):
            logical_count = int(segment.get("eventCount") or 0)
            declared_segment_events += logical_count
            if "physicalEventCount" in segment:
                has_physical_counts = True
                declared_physical_events += int(
                    segment.get("physicalEventCount") or 0
                )
            else:
                declared_physical_events += logical_count
            for event_id in _json_ints(segment.get("sourceEventIds")):
                segment_ids.append(event_id)
        # Reviewed timelines collapse repeated/coalesced physical events into
        # one logical evidence item for the UI. Conservation still checks the
        # complete physical union, while event_count intentionally reports the
        # smaller logical count.
        stored_event_count = int(row["event_count"] or 0)
        count_mismatch = (
            declared_segment_events != stored_event_count
            or (
                has_physical_counts
                and declared_physical_events != len(source_ids)
            )
            or (
                not has_physical_counts
                and len(source_ids) != stored_event_count
            )
        )
        if (
            sorted(source_ids) != sorted(set(segment_ids))
            or len(segment_ids) != len(set(segment_ids))
            or count_mismatch
        ):
            errors.append(
                {
                    "timelineId": str(row["timeline_id"]),
                    "reason": "source_event_ids_do_not_match_segment_union",
                }
            )
    return errors


def _fts_orphan_count(conn: sqlite3.Connection) -> int:
    return _count(
        conn,
        """SELECT COUNT(*) FROM memory_retrieval_docs_fts f
           LEFT JOIN memory_retrieval_docs d ON d.rowid = f.rowid
           WHERE d.rowid IS NULL""",
    ) + _count(
        conn,
        """SELECT COUNT(*) FROM memory_retrieval_docs d
           LEFT JOIN memory_retrieval_docs_fts f ON f.rowid = d.rowid
           WHERE f.rowid IS NULL""",
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _count(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...] = (),
) -> int:
    return int(conn.execute(query, params).fetchone()[0])


def _legacy_atom_id(memory_id: str) -> str:
    return f"atom:legacy-item:{_digest(memory_id)[:24]}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_object(raw: object) -> dict[str, object]:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _json_objects(raw: object) -> list[dict[str, object]]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _json_ints(raw: object) -> list[int]:
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(str(raw or "[]"))
        except (TypeError, json.JSONDecodeError):
            values = []
    result: list[int] = []
    for value in values if isinstance(values, list) else []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _json_strings(raw: object) -> list[str]:
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(str(raw or "[]"))
        except (TypeError, json.JSONDecodeError):
            values = []
    return list(
        dict.fromkeys(
            compact_whitespace(str(value))
            for value in values if isinstance(values, list)
            if compact_whitespace(str(value))
        )
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
