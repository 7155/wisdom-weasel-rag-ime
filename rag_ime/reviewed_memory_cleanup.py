from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping, Sequence

from .memory_ingest import normalize_text
from .memory_projection import RETRIEVAL_DOCS_PROJECTION, enqueue_memory_projection
from .memory_tag_graph import recompute_tag_graph
from .text_utils import compact_whitespace, now_ms


REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION = "rag-ime.reviewed-memory-cleanup-plan.v1"


class ReviewedMemoryCleanupError(RuntimeError):
    pass


def apply_reviewed_memory_cleanup(
    conn: sqlite3.Connection,
    *,
    plan: Mapping[str, object],
    reviewer_id: str,
) -> dict[str, object]:
    """Apply one human-reviewed, append-audited cleanup plan to a candidate DB.

    Raw input events and governed Agent evidence are immutable here. The plan may
    only change derived Atoms, Topic Books, Timeline projections, and source
    dispositions. Callers are responsible for candidate copying and activation.
    """

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _validate_plan(plan)
    project = compact_whitespace(str(plan.get("project") or ""))
    reviewer = compact_whitespace(reviewer_id) or "manual-reviewer"
    timestamp = now_ms()
    plan_sha256 = _json_sha256(plan)
    run_id = f"reviewed-memory-cleanup:{timestamp}:{plan_sha256[7:23]}"
    expected_catalog_sha256 = compact_whitespace(
        str(plan.get("expectedCatalogSha256") or "")
    )
    catalog_sha256 = reviewed_memory_catalog_fingerprint(conn, project=project)
    if not expected_catalog_sha256:
        raise ValueError("cleanup plan must include expectedCatalogSha256")
    if catalog_sha256 != expected_catalog_sha256:
        raise ReviewedMemoryCleanupError(
            "reviewed memory catalog drifted: "
            f"expected {expected_catalog_sha256}, got {catalog_sha256}"
        )
    source_disposition_policy = _source_disposition_policy(plan)
    protected_before = _protected_fingerprints(conn)
    before_counts = _catalog_counts(conn, project=project)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO memory_cleanup_runs(
                   run_id, created_at_ms, provider, model, status, summary,
                   metadata_json, owner_kind, owner_id, run_kind
               ) VALUES (?, ?, 'manual-review', '', 'draft', ?, ?,
                         'user', 'default', 'manual_curation')""",
            (
                run_id,
                timestamp,
                compact_whitespace(str(plan.get("summary") or "")),
                _json(
                    {
                        "schemaVersion": REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION,
                        "planSha256": plan_sha256,
                        "reviewer": reviewer,
                        "project": project,
                    }
                ),
            ),
        )

        retired = _retire_atoms(
            conn,
            plan=_objects(plan.get("retireAtoms")),
            project=project,
            run_id=run_id,
            timestamp=timestamp,
        )
        added = _add_atoms(
            conn,
            plan=_objects(plan.get("addAtoms")),
            project=project,
            run_id=run_id,
            timestamp=timestamp,
        )
        books = _rewrite_books(
            conn,
            plan=_objects(plan.get("books")),
            replacement_map={
                str(item["id"]): str(item.get("replacementId") or "")
                for item in _objects(plan.get("retireAtoms"))
                if compact_whitespace(str(item.get("replacementId") or ""))
            },
            project=project,
            run_id=run_id,
            timestamp=timestamp,
        )
        timelines = _rewrite_timelines(
            conn,
            plan=_objects(plan.get("timelines")),
            project=project,
            reviewer=reviewer,
            run_id=run_id,
            timestamp=timestamp,
        )
        dispositions = _close_source_dispositions(
            conn,
            project=project,
            run_id=run_id,
            reviewer=reviewer,
            timestamp=timestamp,
            policy=source_disposition_policy,
        )
        tag_graph = recompute_tag_graph(conn, project=project)
        outbox_id = enqueue_memory_projection(
            conn,
            projection_kind=RETRIEVAL_DOCS_PROJECTION,
            aggregate_type="project",
            aggregate_id=project or "all",
            operation="reviewed_memory_cleanup",
            project=project,
            payload={"runId": run_id, "planSha256": plan_sha256},
        )
        conn.execute(
            """UPDATE memory_cleanup_runs
               SET status = 'applied', metadata_json = json_set(
                   metadata_json, '$.projectionOutboxId', ?,
                   '$.retiredAtomCount', ?, '$.addedAtomCount', ?,
                   '$.rewrittenBookCount', ?, '$.rewrittenTimelineCount', ?,
                   '$.sourceDispositionChangeCount', ?
               ) WHERE run_id = ?""",
            (
                outbox_id,
                len(retired),
                len(added),
                len(books),
                len(timelines),
                int(dispositions["changed"]),
                run_id,
            ),
        )
        conn.execute(
            """INSERT INTO management_audit_log(
                   created_at_ms, action, target_type, target_id,
                   payload_json, result_json
               ) VALUES (?, 'reviewed_memory_cleanup', 'memory_project', ?, ?, ?)""",
            (
                timestamp,
                project,
                _json({"runId": run_id, "planSha256": plan_sha256, "reviewer": reviewer}),
                _json(
                    {
                        "retiredAtoms": retired,
                        "addedAtoms": added,
                        "books": books,
                        "timelines": timelines,
                        "sourceDispositions": dispositions,
                        "projectionOutboxId": outbox_id,
                    }
                ),
            ),
        )
        protected_after = _protected_fingerprints(conn)
        if protected_after != protected_before:
            raise ReviewedMemoryCleanupError(
                "immutable input, governance evidence, or role-book state changed"
            )
        verification = verify_reviewed_memory_cleanup(conn, plan=plan)
        if not bool(verification["ok"]):
            raise ReviewedMemoryCleanupError(
                "reviewed cleanup verification failed: "
                + "; ".join(str(value) for value in verification["errors"])
            )
        after_counts = _catalog_counts(conn, project=project)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "schemaVersion": REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION,
        "ok": True,
        "runId": run_id,
        "project": project,
        "planSha256": plan_sha256,
        "reviewer": reviewer,
        "beforeCounts": before_counts,
        "afterCounts": after_counts,
        "retiredAtoms": retired,
        "addedAtoms": added,
        "rewrittenBooks": books,
        "rewrittenTimelines": timelines,
        "sourceDispositions": dispositions,
        "tagGraph": tag_graph,
        "projectionOutboxId": outbox_id,
        "protectedFingerprints": protected_after,
        "verification": verification,
    }


def verify_reviewed_memory_cleanup(
    conn: sqlite3.Connection,
    *,
    plan: Mapping[str, object],
) -> dict[str, object]:
    conn.row_factory = sqlite3.Row
    project = compact_whitespace(str(plan.get("project") or ""))
    errors: list[str] = []
    pending = int(
        conn.execute(
            """SELECT COUNT(*)
               FROM agent_memory_sources AS source
               JOIN input_events AS event ON event.id = source.input_event_id
               WHERE source.status = 'active' AND event.project = ?
                 AND source.disposition IN ('pending', 'needs_review')""",
            (project,),
        ).fetchone()[0]
    )
    duplicate_rows = conn.execute(
        """SELECT lower(trim(COALESCE(NULLIF(canonical_text, ''), text))) AS key,
                  COUNT(*) AS count, group_concat(id) AS ids
           FROM memory_atoms
           WHERE status IN ('active', 'approved') AND claim_state = 'current'
             AND (? = '' OR scope_project = ? OR scope_project = '')
           GROUP BY key HAVING COUNT(*) > 1""",
        (project, project),
    ).fetchall()
    broken_books = conn.execute(
        """SELECT book.book_id, value AS atom_id
           FROM memory_books AS book, json_each(book.memory_atom_ids_json)
           LEFT JOIN memory_atoms AS atom ON atom.id = value
           WHERE book.status IN ('active', 'approved')
             AND (? = '' OR book.project = ? OR book.project = '')
             AND (
                 atom.id IS NULL OR atom.status NOT IN ('active', 'approved')
                 OR atom.claim_state != 'current'
             )""",
        (project, project),
    ).fetchall()
    oversized_books = [
        dict(row)
        for row in conn.execute(
            """SELECT book_id, length(summary) AS length
               FROM memory_books
               WHERE status IN ('active', 'approved')
                 AND (? = '' OR project = ? OR project = '')
                 AND length(summary) > 900""",
            (project, project),
        ).fetchall()
    ]
    daily_books = int(
        conn.execute(
            """SELECT COUNT(*) FROM memory_books
               WHERE book_type = 'daily' AND status IN ('active', 'approved')
                 AND (? = '' OR project = ? OR project = '')""",
            (project, project),
        ).fetchone()[0]
    )
    oversized_timelines = [
        dict(row)
        for row in conn.execute(
            """SELECT timeline_id, timeline_date, segment_count
               FROM daily_activity_timelines
               WHERE status = 'approved' AND segment_count > 3
                 AND (? = '' OR project = ? OR project = '')""",
            (project, project),
        ).fetchall()
    ]
    if pending and _source_disposition_policy(plan) != "preserve":
        errors.append(f"unclosed_sources={pending}")
    if duplicate_rows:
        errors.append(f"duplicate_current_atom_texts={len(duplicate_rows)}")
    if broken_books:
        errors.append(f"broken_active_book_refs={len(broken_books)}")
    if oversized_books:
        errors.append(f"oversized_active_book_summaries={len(oversized_books)}")
    if daily_books:
        errors.append(f"active_daily_books={daily_books}")
    if oversized_timelines:
        errors.append(f"oversized_timelines={len(oversized_timelines)}")
    return {
        "schemaVersion": "rag-ime.reviewed-memory-cleanup-verification.v1",
        "ok": not errors,
        "errors": errors,
        "unclosedSourceCount": pending,
        "duplicateCurrentAtoms": [dict(row) for row in duplicate_rows],
        "brokenActiveBookRefs": [dict(row) for row in broken_books],
        "oversizedActiveBookSummaries": oversized_books,
        "activeDailyBookCount": daily_books,
        "oversizedTimelines": oversized_timelines,
        "counts": _catalog_counts(conn, project=project),
    }


def _validate_plan(plan: Mapping[str, object]) -> None:
    if str(plan.get("schemaVersion") or "") != REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION:
        raise ValueError("unsupported reviewed memory cleanup plan schema")
    if not compact_whitespace(str(plan.get("project") or "")):
        raise ValueError("cleanup plan project must not be empty")
    policy = _source_disposition_policy(plan)
    if policy not in {"preserve", "close_unresolved", "reconcile_all_active"}:
        raise ValueError(f"unsupported source disposition policy: {policy}")


def _source_disposition_policy(plan: Mapping[str, object]) -> str:
    return compact_whitespace(
        str(plan.get("sourceDispositionPolicy") or "preserve")
    )


def _retire_atoms(
    conn: sqlite3.Connection,
    *,
    plan: list[dict[str, object]],
    project: str,
    run_id: str,
    timestamp: int,
) -> list[str]:
    retired: list[str] = []
    for item in plan:
        atom_id = compact_whitespace(str(item.get("id") or ""))
        row = conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone()
        if row is None:
            raise ReviewedMemoryCleanupError(f"retired atom is missing: {atom_id}")
        if compact_whitespace(str(row["scope_project"] or "")) not in {"", project}:
            raise ReviewedMemoryCleanupError(
                f"retired atom belongs to another project: {atom_id}"
            )
        expected_text = compact_whitespace(str(item.get("expectedText") or ""))
        if not expected_text:
            raise ValueError(f"retired atom needs expectedText: {atom_id}")
        if compact_whitespace(str(row["text"] or "")) != expected_text:
            raise ReviewedMemoryCleanupError(f"retired atom text drifted: {atom_id}")
        mode = compact_whitespace(str(item.get("mode") or "supersede"))
        if mode not in {"supersede", "retract"}:
            raise ValueError(f"unsupported atom retirement mode: {mode}")
        replacement_id = compact_whitespace(str(item.get("replacementId") or ""))
        if mode == "supersede":
            replacement = conn.execute(
                """SELECT id FROM memory_atoms WHERE id = ?
                   AND status IN ('active', 'approved') AND claim_state = 'current'""",
                (replacement_id,),
            ).fetchone()
            if replacement is None:
                raise ReviewedMemoryCleanupError(
                    f"replacement atom is not current: {replacement_id}"
                )
            replacement_scope = conn.execute(
                "SELECT scope_project FROM memory_atoms WHERE id = ?",
                (replacement_id,),
            ).fetchone()[0]
            if compact_whitespace(str(replacement_scope or "")) not in {"", project}:
                raise ReviewedMemoryCleanupError(
                    f"replacement atom belongs to another project: {replacement_id}"
                )
        _record_cleanup_diff(conn, run_id=run_id, op=f"atom_{mode}", target_id=atom_id, before=dict(row), after={"replacementId": replacement_id}, timestamp=timestamp)
        conn.execute(
            """UPDATE memory_atoms
               SET status = ?, claim_state = ?, valid_to_ms = ?, updated_at_ms = ?
               WHERE id = ?""",
            (
                "superseded" if mode == "supersede" else "hidden",
                "superseded" if mode == "supersede" else "retracted",
                timestamp,
                timestamp,
                atom_id,
            ),
        )
        if replacement_id:
            supersession_id = "supersession:reviewed:" + hashlib.sha256(
                f"{atom_id}\0{replacement_id}".encode("utf-8")
            ).hexdigest()[:24]
            conn.execute(
                """INSERT INTO memory_supersessions(
                       supersession_id, old_memory_id, new_memory_id, reason,
                       source_event_ids_json, status, created_at_ms, metadata_json
                   ) VALUES (?, ?, ?, ?, '[]', 'active', ?, ?)
                   ON CONFLICT(supersession_id) DO NOTHING""",
                (
                    supersession_id,
                    atom_id,
                    replacement_id,
                    compact_whitespace(str(item.get("reason") or "reviewed duplicate")),
                    timestamp,
                    _json({"source": "reviewed_memory_cleanup", "runId": run_id}),
                ),
            )
        retired.append(atom_id)
    return retired


def _add_atoms(
    conn: sqlite3.Connection,
    *,
    plan: list[dict[str, object]],
    project: str,
    run_id: str,
    timestamp: int,
) -> list[str]:
    added: list[str] = []
    for item in plan:
        atom_id = compact_whitespace(str(item.get("id") or ""))
        if conn.execute("SELECT 1 FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone():
            raise ReviewedMemoryCleanupError(f"new atom already exists: {atom_id}")
        text = compact_whitespace(str(item.get("text") or ""))
        claim_key = compact_whitespace(str(item.get("claimKey") or ""))
        event_ids = _positive_ints(item.get("sourceEventIds"))
        source_memory_ids = _strings(item.get("sourceMemoryIds"))
        if not text or not claim_key or not event_ids:
            raise ValueError(f"new atom needs text, claimKey, and evidence: {atom_id}")
        _require_input_events(conn, event_ids, project=project)
        for source_id in source_memory_ids:
            if conn.execute(
                """SELECT 1 FROM agent_memory_sources AS source
                   JOIN input_events AS event ON event.id = source.input_event_id
                   WHERE source.source_id = ? AND event.project = ?""",
                (source_id, project),
            ).fetchone() is None:
                raise ReviewedMemoryCleanupError(f"atom source is missing: {source_id}")
        lineage_id = "lineage:reviewed:" + hashlib.sha256(claim_key.encode("utf-8")).hexdigest()[:24]
        conn.execute(
            """INSERT INTO memory_atoms(
                   id, kind, text, canonical_text, source_event_ids_json,
                   source_memory_ids_json, scope_project, language, confidence,
                   quality_score, echo_risk, privacy_level, status,
                   created_at_ms, updated_at_ms, owner_kind, owner_id,
                   claim_key, lineage_id, claim_state, valid_from_ms
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'zh', ?, ?, 0.0, 'local',
                         'active', ?, ?, 'user', 'default', ?, ?, 'current', ?)""",
            (
                atom_id,
                compact_whitespace(str(item.get("kind") or "project_requirement")),
                text,
                text,
                _json(event_ids),
                _json(source_memory_ids),
                project,
                float(item.get("confidence") or 0.98),
                float(item.get("qualityScore") or 0.95),
                timestamp,
                timestamp,
                claim_key,
                lineage_id,
                timestamp,
            ),
        )
        for tag in _strings(item.get("tags")):
            normalized_tag = normalize_text(tag)
            conn.execute(
                """INSERT INTO memory_tags(
                       tag, normalized_tag, tag_type, quality_score,
                       created_at_ms, updated_at_ms, description, source, status,
                       metadata_json
                   ) VALUES (?, ?, 'concept', 0.9, ?, ?, '', 'user', 'active', '{}')
                   ON CONFLICT(tag) DO UPDATE SET
                       normalized_tag = excluded.normalized_tag,
                       quality_score = MAX(memory_tags.quality_score, excluded.quality_score),
                       updated_at_ms = excluded.updated_at_ms,
                       source = 'user', status = 'active'""",
                (tag, normalized_tag, timestamp, timestamp),
            )
            tag_id = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()[0]
            conn.execute(
                """INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
                   VALUES (?, ?, 1.0, 'manual_review')
                   ON CONFLICT(memory_atom_id, tag_id) DO UPDATE SET
                       weight = excluded.weight, source = excluded.source""",
                (atom_id, tag_id),
            )
        _record_cleanup_diff(conn, run_id=run_id, op="atom_add", target_id=atom_id, before={}, after={"text": text, "claimKey": claim_key, "sourceEventIds": event_ids}, timestamp=timestamp)
        added.append(atom_id)
    return added


def _rewrite_books(
    conn: sqlite3.Connection,
    *,
    plan: list[dict[str, object]],
    replacement_map: Mapping[str, str],
    project: str,
    run_id: str,
    timestamp: int,
) -> list[str]:
    rewritten: list[str] = []
    for item in plan:
        book_id = compact_whitespace(str(item.get("id") or ""))
        row = conn.execute("SELECT * FROM memory_books WHERE book_id = ?", (book_id,)).fetchone()
        if row is None or str(row["status"]) not in {"active", "approved"}:
            raise ReviewedMemoryCleanupError(f"active book is missing: {book_id}")
        if compact_whitespace(str(row["project"] or "")) != project:
            raise ReviewedMemoryCleanupError(
                f"book belongs to another project: {book_id}"
            )
        members = _strings(row["memory_atom_ids_json"])
        members = [replacement_map.get(value, value) for value in members]
        remove_ids = set(_strings(item.get("removeAtomIds")))
        members = [value for value in members if value not in remove_ids]
        members.extend(_strings(item.get("addAtomIds")))
        members = list(dict.fromkeys(value for value in members if value))
        _require_current_atoms(conn, members, project=project)
        source_event_ids = _atom_source_event_ids(conn, members)
        summary = compact_whitespace(str(item.get("summary") or ""))
        if not summary or len(summary) > 900:
            raise ValueError(f"book summary must contain 1-900 characters: {book_id}")
        tags = _strings(item.get("tags")) or _strings(row["tags_json"])
        expansions = _strings(item.get("queryExpansions")) or _strings(row["query_expansions_json"])
        hints = _strings(item.get("surfaceHints")) or _strings(row["surface_hints_json"])
        metadata = _object(row["metadata_json"])
        metadata.update(
            {
                "schemaVersion": REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION,
                "source": "reviewed_memory_cleanup",
                "runId": run_id,
                "summary": summary,
                "tags": tags,
                "queryExpansions": expansions,
                "surfaceHints": hints,
                "memoryAtomIds": members,
                "sourceEventIds": source_event_ids,
                "reviewedAtMs": timestamp,
            }
        )
        _record_cleanup_diff(conn, run_id=run_id, op="book_rewrite", target_id=book_id, before=dict(row), after={"summary": summary, "memoryAtomIds": members, "sourceEventIds": source_event_ids}, timestamp=timestamp)
        conn.execute(
            """UPDATE memory_books
               SET summary = ?, normalized_text = ?, tags_json = ?,
                   surface_hints_json = ?, query_expansions_json = ?,
                   source_event_ids_json = ?, memory_atom_ids_json = ?,
                   confidence = MAX(confidence, 0.9),
                   quality_score = MAX(quality_score, 0.9),
                   updated_at_ms = ?, metadata_json = ?
               WHERE book_id = ?""",
            (
                summary,
                normalize_text(summary),
                _json(tags),
                _json(hints),
                _json(expansions),
                _json(source_event_ids),
                _json(members),
                timestamp,
                _json(metadata),
                book_id,
            ),
        )
        rewritten.append(book_id)
    return rewritten


def _rewrite_timelines(
    conn: sqlite3.Connection,
    *,
    plan: list[dict[str, object]],
    project: str,
    reviewer: str,
    run_id: str,
    timestamp: int,
) -> list[str]:
    rewritten: list[str] = []
    for item in plan:
        timeline_date = compact_whitespace(str(item.get("date") or ""))
        row = conn.execute(
            """SELECT * FROM daily_activity_timelines
               WHERE project = ? AND timeline_date = ? AND status = 'approved'""",
            (project, timeline_date),
        ).fetchone()
        if row is None:
            raise ReviewedMemoryCleanupError(f"approved timeline is missing: {timeline_date}")
        expected_id = compact_whitespace(str(item.get("expectedTimelineId") or ""))
        if expected_id and str(row["timeline_id"]) != expected_id:
            raise ReviewedMemoryCleanupError(f"timeline identity drifted: {timeline_date}")
        segment_plans = _objects(item.get("segments"))
        if not segment_plans or len(segment_plans) > 3:
            raise ValueError(f"timeline needs 1-3 task segments: {timeline_date}")
        segments: list[dict[str, object]] = []
        all_event_ids: list[int] = []
        for position, segment_plan in enumerate(segment_plans):
            event_ids = _positive_ints(segment_plan.get("eventIds"))
            _require_input_events(conn, event_ids, project=project)
            all_event_ids.extend(event_ids)
            segments.append(
                _timeline_segment(
                    conn,
                    timeline_date=timeline_date,
                    plan=segment_plan,
                    position=position,
                    event_ids=event_ids,
                )
            )
        all_event_ids = list(dict.fromkeys(all_event_ids))
        source_hash = hashlib.sha256(_json(all_event_ids).encode("utf-8")).hexdigest()
        summary = compact_whitespace(str(item.get("summary") or ""))
        if not summary:
            summary = "；".join(str(segment["summary"]) for segment in segments)
        metadata = _object(row["metadata_json"])
        metadata.update(
            {
                "schemaVersion": "rag-ime.activity-timeline-index.v1",
                "segmentationMode": "semantic_task_v2",
                "source": "reviewed_memory_cleanup",
                "runId": run_id,
                "reviewer": reviewer,
                "manualReview": True,
                "automaticPromotion": False,
                "longTermFact": False,
                "corroborationOnly": True,
                "maySupportFacts": False,
            }
        )
        _record_cleanup_diff(conn, run_id=run_id, op="timeline_rewrite", target_id=str(row["timeline_id"]), before=dict(row), after={"sourceEventIds": all_event_ids, "segments": segments, "summary": summary}, timestamp=timestamp)
        conn.execute(
            """UPDATE daily_activity_timelines
               SET source_event_ids_json = ?, source_event_hash = ?,
                   segments_json = ?, summary_text = ?, event_count = ?,
                   segment_count = ?, approved_book_id = '', approved_by = ?,
                   approved_at_ms = ?, metadata_json = ?, updated_at_ms = ?
               WHERE timeline_id = ?""",
            (
                _json(all_event_ids),
                source_hash,
                _json(segments),
                summary,
                len(all_event_ids),
                len(segments),
                reviewer,
                timestamp,
                _json(metadata),
                timestamp,
                str(row["timeline_id"]),
            ),
        )
        rewritten.append(str(row["timeline_id"]))
    return rewritten


def _timeline_segment(
    conn: sqlite3.Connection,
    *,
    timeline_date: str,
    plan: Mapping[str, object],
    position: int,
    event_ids: list[int],
) -> dict[str, object]:
    placeholders = ",".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""SELECT id, created_at_ms, source, app, context_group_id
            FROM input_events WHERE id IN ({placeholders}) ORDER BY created_at_ms, id""",
        tuple(event_ids),
    ).fetchall()
    apps = list(dict.fromkeys(compact_whitespace(str(row["app"] or "")) for row in rows if compact_whitespace(str(row["app"] or ""))))
    groups = list(dict.fromkeys(compact_whitespace(str(row["context_group_id"] or "")) for row in rows if compact_whitespace(str(row["context_group_id"] or ""))))
    title = compact_whitespace(str(plan.get("title") or ""))
    actions = compact_whitespace(str(plan.get("actualActions") or ""))
    result = compact_whitespace(str(plan.get("resultOrBlocker") or ""))
    if not title or not actions or not result:
        raise ValueError(f"timeline segment is incomplete: {timeline_date}#{position}")
    source_hash = hashlib.sha256(_json(event_ids).encode("utf-8")).hexdigest()
    return {
        "segmentId": f"activity-segment:reviewed:{source_hash[:24]}",
        "position": position,
        "period": compact_whitespace(str(plan.get("period") or "day")),
        "title": title,
        "goal": compact_whitespace(str(plan.get("goal") or title)),
        "actualActions": actions,
        "resultOrBlocker": result,
        "summary": f"{title}：{actions} {result}",
        "startMs": int(rows[0]["created_at_ms"]),
        "endMs": int(rows[-1]["created_at_ms"]),
        "eventCount": len(event_ids),
        "physicalEventCount": len(event_ids),
        "redactedEventCount": 0,
        "app": apps[0] if len(apps) == 1 else "multiple",
        "apps": apps,
        "contextGroupIds": groups,
        "sourceKinds": list(dict.fromkeys(str(row["source"] or "") for row in rows)),
        "sourceEventIds": event_ids,
        "sourceEventHash": source_hash,
        "source": {"type": "input_event_bundle", "id": f"event-set:{source_hash}"},
        "evidenceRefs": [
            {
                "sourceType": "input_event",
                "sourceId": f"event:{int(row['id'])}",
                "eventId": int(row["id"]),
                "eventIds": [int(row["id"])],
                "sourceKind": str(row["source"] or ""),
                "app": str(row["app"] or ""),
                "occurredAtMs": int(row["created_at_ms"]),
                "preview": "[已整理证据，原文按需展开]",
            }
            for row in rows
        ],
    }


def _close_source_dispositions(
    conn: sqlite3.Connection,
    *,
    project: str,
    run_id: str,
    reviewer: str,
    timestamp: int,
    policy: str,
) -> dict[str, object]:
    if policy == "preserve":
        return {
            "policy": policy,
            "changed": 0,
            "retained": 0,
            "notForMemory": 0,
            "retainedEventCount": len(_retained_event_ids(conn, project=project)),
        }
    retained_event_ids = _retained_event_ids(conn, project=project)
    disposition_filter = (
        " AND source.disposition IN ('pending', 'needs_review')"
        if policy == "close_unresolved"
        else ""
    )
    rows = conn.execute(
        f"""SELECT source.*
           FROM agent_memory_sources AS source
           JOIN input_events AS event ON event.id = source.input_event_id
           WHERE source.status = 'active' AND event.project = ?{disposition_filter}
           ORDER BY source.source_id""",
        (project,),
    ).fetchall()
    changed = 0
    retained_sources = 0
    discarded_sources = 0
    for row in rows:
        desired = "consolidated" if int(row["input_event_id"]) in retained_event_ids else "not_for_memory"
        reason = "reviewed_artifact_evidence" if desired == "consolidated" else "reviewed_non_durable_source"
        if desired == "consolidated":
            retained_sources += 1
        else:
            discarded_sources += 1
        previous = str(row["disposition"])
        if previous == desired and str(row["disposition_reason"] or "") == reason:
            continue
        event_id = "disposition:reviewed:" + hashlib.sha256(
            f"{run_id}\0{row['source_id']}\0{desired}".encode("utf-8")
        ).hexdigest()[:24]
        conn.execute(
            """INSERT INTO memory_source_disposition_events(
                   event_id, source_id, previous_disposition, new_disposition,
                   reason_code, actor_kind, run_id, created_at_ms, metadata_json
               ) VALUES (?, ?, ?, ?, ?, 'system', ?, ?, ?)""",
            (
                event_id,
                str(row["source_id"]),
                previous,
                desired,
                reason,
                run_id,
                timestamp,
                _json({"reviewer": reviewer, "source": "reviewed_memory_cleanup"}),
            ),
        )
        conn.execute(
            """UPDATE agent_memory_sources
               SET disposition = ?, disposition_reason = ?,
                   disposition_updated_at_ms = ?, processed_at_ms = ?,
                   curation_run_id = ?
               WHERE source_id = ?""",
            (desired, reason, timestamp, timestamp, run_id, str(row["source_id"])),
        )
        changed += 1
    return {
        "policy": policy,
        "changed": changed,
        "retained": retained_sources,
        "notForMemory": discarded_sources,
        "retainedEventCount": len(retained_event_ids),
    }


def _retained_event_ids(conn: sqlite3.Connection, *, project: str) -> set[int]:
    result: set[int] = set()
    for row in conn.execute(
        """SELECT source_event_ids_json FROM memory_atoms
           WHERE status IN ('active', 'approved') AND claim_state = 'current'
             AND (? = '' OR scope_project = ? OR scope_project = '')""",
        (project, project),
    ):
        result.update(_positive_ints(row[0]))
    for row in conn.execute(
        """SELECT source_event_ids_json FROM memory_books
           WHERE status IN ('active', 'approved')
             AND (? = '' OR project = ? OR project = '')""",
        (project, project),
    ):
        result.update(_positive_ints(row[0]))
    for row in conn.execute(
        """SELECT source_event_ids_json FROM daily_activity_timelines
           WHERE status = 'approved'
             AND (? = '' OR project = ? OR project = '')""",
        (project, project),
    ):
        result.update(_positive_ints(row[0]))
    for row in conn.execute(
        """SELECT source_event_id FROM memory_items
           WHERE kind = 'phrase' AND status IN ('active', 'approved')
             AND (? = '' OR project = ? OR project = '')""",
        (project, project),
    ):
        if int(row[0] or 0) > 0:
            result.add(int(row[0]))
    return result


def _record_cleanup_diff(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    op: str,
    target_id: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    timestamp: int,
) -> None:
    conn.execute(
        """INSERT INTO memory_cleanup_diffs(
               run_id, op, target_memory_id, payload_json, status,
               created_at_ms, applied_at_ms, rollback_json
           ) VALUES (?, ?, ?, ?, 'applied', ?, ?, ?)""",
        (
            run_id,
            op,
            target_id,
            _json(dict(after)),
            timestamp,
            timestamp,
            _json(dict(before)),
        ),
    )


def _catalog_counts(conn: sqlite3.Connection, *, project: str) -> dict[str, int]:
    return {
        "currentAtoms": _count(conn, "SELECT COUNT(*) FROM memory_atoms WHERE status IN ('active','approved') AND claim_state='current' AND (?='' OR scope_project=? OR scope_project='')", (project, project)),
        "activeBooks": _count(conn, "SELECT COUNT(*) FROM memory_books WHERE status IN ('active','approved') AND (?='' OR project=? OR project='')", (project, project)),
        "approvedTimelines": _count(conn, "SELECT COUNT(*) FROM daily_activity_timelines WHERE status='approved' AND (?='' OR project=? OR project='')", (project, project)),
        "approvedPhrases": _count(conn, "SELECT COUNT(*) FROM memory_items WHERE kind='phrase' AND status IN ('active','approved') AND (?='' OR project=? OR project='')", (project, project)),
        "pendingSources": _count(conn, "SELECT COUNT(*) FROM agent_memory_sources s JOIN input_events e ON e.id=s.input_event_id WHERE s.status='active' AND e.project=? AND s.disposition='pending'", (project,)),
        "needsReviewSources": _count(conn, "SELECT COUNT(*) FROM agent_memory_sources s JOIN input_events e ON e.id=s.input_event_id WHERE s.status='active' AND e.project=? AND s.disposition='needs_review'", (project,)),
    }


def _protected_fingerprints(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        table: _table_fingerprint(conn, table)
        for table in (
            "input_events",
            "agent_memory_evidence",
            "memory_governance_proposals",
            "memory_atom_evidence_links",
            "agent_role_books",
            "agent_role_book_revisions",
        )
    }


def _table_fingerprint(conn: sqlite3.Connection, table: str) -> str:
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
    digest = hashlib.sha256()
    if not columns:
        return "missing"
    for row in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"):
        digest.update(_json([row[column] for column in columns]).encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _require_input_events(
    conn: sqlite3.Connection,
    event_ids: Sequence[int],
    *,
    project: str,
) -> None:
    if not event_ids:
        raise ValueError("evidence event list must not be empty")
    placeholders = ",".join("?" for _ in event_ids)
    count = int(
        conn.execute(
            f"""SELECT COUNT(*) FROM input_events
                WHERE id IN ({placeholders}) AND project = ?""",
            (*event_ids, project),
        ).fetchone()[0]
    )
    if count != len(set(event_ids)):
        raise ReviewedMemoryCleanupError("one or more evidence input events are missing")


def _require_current_atoms(
    conn: sqlite3.Connection,
    atom_ids: Sequence[str],
    *,
    project: str,
) -> None:
    for atom_id in atom_ids:
        row = conn.execute(
            """SELECT 1 FROM memory_atoms WHERE id = ?
               AND status IN ('active', 'approved') AND claim_state = 'current'
               AND (scope_project = ? OR scope_project = '')""",
            (atom_id, project),
        ).fetchone()
        if row is None:
            raise ReviewedMemoryCleanupError(f"book member is not a current atom: {atom_id}")


def _atom_source_event_ids(conn: sqlite3.Connection, atom_ids: Sequence[str]) -> list[int]:
    result: list[int] = []
    for atom_id in atom_ids:
        row = conn.execute("SELECT source_event_ids_json FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone()
        if row is not None:
            result.extend(_positive_ints(row[0]))
    return list(dict.fromkeys(result))


def _count(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
        value = parsed
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(compact_whitespace(str(item)) for item in value if compact_whitespace(str(item))))


def _positive_ints(value: object) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, (list, tuple)):
        return []
    result: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _object(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _json_sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def reviewed_memory_catalog_fingerprint(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> str:
    """Fingerprint every mutable catalog row targeted by a reviewed plan."""

    queries = (
        (
            "sources",
            """SELECT source.* FROM agent_memory_sources AS source
               JOIN input_events AS event ON event.id = source.input_event_id
               WHERE source.status = 'active' AND event.project = ?
               ORDER BY source.source_id""",
            (project,),
        ),
        (
            "atoms",
            """SELECT * FROM memory_atoms
               WHERE status IN ('active', 'approved') AND claim_state = 'current'
                 AND (scope_project = ? OR scope_project = '') ORDER BY id""",
            (project,),
        ),
        (
            "books",
            """SELECT * FROM memory_books
               WHERE status IN ('active', 'approved') AND project = ?
               ORDER BY book_id""",
            (project,),
        ),
        (
            "timelines",
            """SELECT * FROM daily_activity_timelines
               WHERE status = 'approved' AND project = ? ORDER BY timeline_id""",
            (project,),
        ),
        (
            "phrases",
            """SELECT * FROM memory_items
               WHERE kind = 'phrase' AND status IN ('active', 'approved')
                 AND project = ? ORDER BY id""",
            (project,),
        ),
    )
    digest = hashlib.sha256()
    for label, sql, params in queries:
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        for row in conn.execute(sql, params):
            digest.update(_json(list(row)).encode("utf-8"))
            digest.update(b"\n")
    return "sha256:" + digest.hexdigest()
