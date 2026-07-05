from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .memory_ingest import normalize_text, upsert_memory_item
from .memory_models import CleanupDiffEntry, CleanupRunPlan
from .text_utils import compact_whitespace, now_ms, truncate_text


def build_cleanup_plan(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    since_days: int = 90,
    provider: str = "",
    model: str = "",
) -> CleanupRunPlan:
    del since_days
    rows = conn.execute(
        """
        SELECT
            mi.memory_id,
            mi.kind,
            mi.text,
            mi.normalized_text,
            mi.project,
            mi.source_event_id,
            mi.status,
            mi.privacy_class,
            COALESCE(ps.input_frequency, 0) AS input_frequency,
            COALESCE(ms.accepted_count, 0) AS accepted_count
        FROM memory_items mi
        LEFT JOIN phrase_stats ps ON ps.committed_text = mi.text
        LEFT JOIN memory_state ms ON ms.event_id = mi.source_event_id
        WHERE (? = '' OR mi.project = ? OR mi.project = '')
          AND mi.status IN ('active', 'approved', 'hidden')
        ORDER BY mi.updated_at_ms DESC
        """,
        (project, project),
    ).fetchall()
    diffs: list[CleanupDiffEntry] = []
    seen_stable: set[str] = set()
    for row in rows:
        memory_id = str(row["memory_id"])
        kind = str(row["kind"])
        text = compact_whitespace(str(row["text"]))
        normalized = compact_whitespace(str(row["normalized_text"]))
        status = str(row["status"])
        privacy = str(row["privacy_class"])
        input_frequency = int(row["input_frequency"] or 0)
        accepted_count = int(row["accepted_count"] or 0)
        if privacy == "sensitive":
            continue
        if kind == "phrase" and normalized not in seen_stable and (accepted_count >= 1 or input_frequency >= 2):
            seen_stable.add(normalized)
            diffs.append(
                CleanupDiffEntry(
                    op="add_stable_memory",
                    target_memory_id=memory_id,
                    payload={
                        "memoryId": f"stable:{normalized}",
                        "text": text,
                        "project": str(row["project"] or ""),
                        "evidenceEventIds": [int(row["source_event_id"] or 0)],
                        "confidence": min(0.95, 0.55 + accepted_count * 0.1 + min(input_frequency, 4) * 0.05),
                    },
                )
            )
        if kind == "raw_event" and status == "active" and len(text) > 12 and accepted_count <= 0 and input_frequency <= 1:
            diffs.append(
                CleanupDiffEntry(
                    op="tombstone",
                    target_memory_id=memory_id,
                    payload={
                        "targetType": "memory_id",
                        "targetValue": memory_id,
                        "reason": "cleanup:raw-echo-candidate",
                    },
                )
            )
    run_id = f"cleanup_{now_ms()}"
    summary = f"stable={sum(1 for item in diffs if item.op == 'add_stable_memory')} tombstone={sum(1 for item in diffs if item.op == 'tombstone')}"
    return CleanupRunPlan(run_id=run_id, provider=provider, model=model, summary=summary, diffs=tuple(diffs))


def persist_cleanup_plan(conn: sqlite3.Connection, plan: CleanupRunPlan) -> dict[str, object]:
    validate_cleanup_plan(plan)
    created_at = now_ms()
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_cleanup_runs(run_id, created_at_ms, provider, model, status, summary, metadata_json)
        VALUES (?, ?, ?, ?, 'draft', ?, ?)
        """,
        (plan.run_id, created_at, plan.provider, plan.model, plan.summary, json.dumps(plan.metadata, ensure_ascii=False, sort_keys=True)),
    )
    conn.execute("DELETE FROM memory_cleanup_diffs WHERE run_id = ?", (plan.run_id,))
    for diff in plan.diffs:
        conn.execute(
            """
            INSERT INTO memory_cleanup_diffs(run_id, op, target_memory_id, payload_json, status, created_at_ms, rollback_json)
            VALUES (?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                plan.run_id,
                diff.op,
                diff.target_memory_id,
                json.dumps(diff.payload, ensure_ascii=False, sort_keys=True),
                diff.status,
                created_at,
            ),
        )
    _sync_cleanup_run_status(conn, run_id=plan.run_id)
    return cleanup_run_payload(conn, run_id=plan.run_id)


def apply_cleanup_run(conn: sqlite3.Connection, *, run_id: str, only_approved: bool = False) -> dict[str, object]:
    rows = conn.execute(
        f"""
        SELECT id, op, target_memory_id, payload_json, status
        FROM memory_cleanup_diffs
        WHERE run_id = ?
          AND status IN ({'\'approved\', \'pending\'' if not only_approved else '\'approved\''})
        ORDER BY id ASC
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        _validate_cleanup_diff_row_for_apply(row)
    for row in rows:
        _apply_cleanup_diff_row(conn, row=row)
    _sync_cleanup_run_status(conn, run_id=run_id)
    return cleanup_run_payload(conn, run_id=run_id)


def rollback_cleanup_run(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT id, op, rollback_json, status
        FROM memory_cleanup_diffs
        WHERE run_id = ? AND status = 'applied'
        ORDER BY id DESC
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        _rollback_cleanup_diff_row(conn, row=row)
    _sync_cleanup_run_status(conn, run_id=run_id)
    return cleanup_run_payload(conn, run_id=run_id)


def apply_cleanup_diff(conn: sqlite3.Connection, *, diff_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, run_id, op, target_memory_id, payload_json, status
        FROM memory_cleanup_diffs
        WHERE id = ?
        LIMIT 1
        """,
        (diff_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"cleanup diff not found: {diff_id}")
    current_status = str(row["status"])
    if current_status == "applied":
        return cleanup_diff_payload(conn, diff_id=diff_id)
    if current_status not in {"pending", "approved"}:
        raise ValueError(f"cleanup diff {diff_id} cannot be applied from status {current_status}")
    _validate_cleanup_diff_row_for_apply(row)
    _apply_cleanup_diff_row(conn, row=row)
    _sync_cleanup_run_status(conn, run_id=str(row["run_id"]))
    return cleanup_diff_payload(conn, diff_id=diff_id)


def rollback_cleanup_diff(conn: sqlite3.Connection, *, diff_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, run_id, op, rollback_json, status
        FROM memory_cleanup_diffs
        WHERE id = ?
        LIMIT 1
        """,
        (diff_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"cleanup diff not found: {diff_id}")
    current_status = str(row["status"])
    if current_status == "rolled_back":
        return cleanup_diff_payload(conn, diff_id=diff_id)
    if current_status != "applied":
        raise ValueError(f"cleanup diff {diff_id} cannot be rolled back from status {current_status}")
    _rollback_cleanup_diff_row(conn, row=row)
    _sync_cleanup_run_status(conn, run_id=str(row["run_id"]))
    return cleanup_diff_payload(conn, diff_id=diff_id)


def review_cleanup_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    diff_ids: tuple[int, ...] = (),
    diff_indexes: tuple[int, ...] = (),
) -> dict[str, object]:
    normalized_status = compact_whitespace(status).lower()
    if normalized_status not in {"pending", "approved", "rejected"}:
        raise ValueError(f"unsupported cleanup review status: {status}")
    rows = conn.execute(
        """
        SELECT id, status
        FROM memory_cleanup_diffs
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        raise ValueError(f"cleanup run not found: {run_id}")
    available_ids = [int(row["id"]) for row in rows]
    available_statuses = {int(row["id"]): str(row["status"]) for row in rows}
    target_ids: list[int]
    if diff_ids:
        target_ids = []
        known_ids = set(available_ids)
        for diff_id in diff_ids:
            if diff_id not in known_ids:
                raise ValueError(f"cleanup diff id not found in run {run_id}: {diff_id}")
            target_ids.append(diff_id)
    elif diff_indexes:
        target_ids = []
        for diff_index in diff_indexes:
            if diff_index < 0 or diff_index >= len(available_ids):
                raise ValueError(f"cleanup diff index out of range: {diff_index}")
            target_ids.append(available_ids[diff_index])
    else:
        target_ids = list(available_ids)
    for diff_id in target_ids:
        current_status = available_statuses.get(diff_id, "")
        if current_status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"cleanup diff {diff_id} is not reviewable from status {current_status}")
    placeholders = ", ".join("?" for _ in target_ids)
    conn.execute(
        f"""
        UPDATE memory_cleanup_diffs
        SET status = ?
        WHERE run_id = ?
          AND id IN ({placeholders})
        """,
        (normalized_status, run_id, *target_ids),
    )
    _sync_cleanup_run_status(conn, run_id=run_id)
    return cleanup_run_payload(conn, run_id=run_id)


def cleanup_run_payload(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
    run = conn.execute(
        """
        SELECT run_id, created_at_ms, provider, model, status, summary, metadata_json
        FROM memory_cleanup_runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    diffs = conn.execute(
        """
        SELECT id, op, target_memory_id, payload_json, status, created_at_ms, applied_at_ms
        FROM memory_cleanup_diffs
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    ).fetchall()
    return {
        "runId": run_id,
        "status": "" if run is None else str(run["status"]),
        "summary": "" if run is None else str(run["summary"]),
        "provider": "" if run is None else str(run["provider"]),
        "model": "" if run is None else str(run["model"]),
        "diffs": [
            {
                "diffId": int(row["id"]),
                "op": str(row["op"]),
                "targetMemoryId": str(row["target_memory_id"]),
                "payload": json.loads(row["payload_json"] or "{}"),
                "status": str(row["status"]),
                "createdAtMs": int(row["created_at_ms"] or 0),
                "appliedAtMs": int(row["applied_at_ms"] or 0),
            }
            for row in diffs
        ],
    }


def cleanup_diff_payload(conn: sqlite3.Connection, *, diff_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, run_id, op, target_memory_id, payload_json, status, created_at_ms, applied_at_ms, rollback_json
        FROM memory_cleanup_diffs
        WHERE id = ?
        LIMIT 1
        """,
        (diff_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"cleanup diff not found: {diff_id}")
    return {
        "diffId": int(row["id"]),
        "runId": str(row["run_id"]),
        "op": str(row["op"]),
        "targetMemoryId": str(row["target_memory_id"]),
        "payload": json.loads(row["payload_json"] or "{}"),
        "status": str(row["status"]),
        "createdAtMs": int(row["created_at_ms"] or 0),
        "appliedAtMs": int(row["applied_at_ms"] or 0),
        "rollback": json.loads(row["rollback_json"] or "{}"),
    }


def load_cleanup_run_from_file(path: str | Path) -> CleanupRunPlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return cleanup_plan_from_payload(payload)


def cleanup_plan_from_payload(payload: dict[str, object]) -> CleanupRunPlan:
    plan = CleanupRunPlan(
        run_id=str(payload["runId"]),
        provider=str(payload.get("provider", "")),
        model=str(payload.get("model", "")),
        summary=str(payload.get("summary", "")),
        metadata=dict(payload.get("metadata") or {}),
        diffs=tuple(
            CleanupDiffEntry(
                op=str(item["op"]),
                target_memory_id=str(item.get("targetMemoryId", "")),
                payload=dict(item.get("payload") or {}),
                status=str(item.get("status", "pending")),
            )
            for item in payload.get("diffs", [])
        ),
    )
    validate_cleanup_plan(plan)
    return plan


def cleanup_plan_to_payload(plan: CleanupRunPlan) -> dict[str, object]:
    return {
        "runId": plan.run_id,
        "provider": plan.provider,
        "model": plan.model,
        "summary": plan.summary,
        "metadata": plan.metadata,
        "diffs": [
            {
                "op": diff.op,
                "targetMemoryId": diff.target_memory_id,
                "payload": diff.payload,
                "status": diff.status,
            }
            for diff in plan.diffs
        ],
    }


def inspect_cleanup_plan(plan: CleanupRunPlan) -> dict[str, object]:
    counts = {
        "addStableMemory": 0,
        "addPhrase": 0,
        "tombstone": 0,
    }
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for index, diff in enumerate(plan.diffs):
        diff_id = index + 1
        payload = dict(diff.payload or {})
        op = compact_whitespace(diff.op)
        if op == "add_stable_memory":
            counts["addStableMemory"] += 1
            text = compact_whitespace(str(payload.get("text", "")))
            if len(text) > 80:
                errors.append(_cleanup_issue(diff_id=diff_id, op=op, field="text", code="stable_memory_text_too_long", value=len(text)))
            evidence_ids = [int(item) for item in (payload.get("evidenceEventIds") or []) if int(item or 0) > 0]
            if not evidence_ids:
                errors.append(_cleanup_issue(diff_id=diff_id, op=op, field="evidenceEventIds", code="missing_evidence_event_ids"))
            if _looks_like_long_sentence(text):
                warnings.append(_cleanup_issue(diff_id=diff_id, op=op, field="text", code="stable_memory_sentence_like", preview=truncate_text(text, 80)))
        elif op == "add_phrase":
            counts["addPhrase"] += 1
            text = compact_whitespace(str(payload.get("text", "")))
            if len(text) > 32:
                errors.append(_cleanup_issue(diff_id=diff_id, op=op, field="text", code="phrase_text_too_long", value=len(text)))
            if _looks_like_long_sentence(text):
                warnings.append(_cleanup_issue(diff_id=diff_id, op=op, field="text", code="phrase_sentence_like", preview=truncate_text(text, 80)))
        elif op == "tombstone":
            counts["tombstone"] += 1
            target_type = compact_whitespace(str(payload.get("targetType", "")))
            target_value = compact_whitespace(str(payload.get("targetValue", "")))
            if not target_type or not target_value:
                errors.append(_cleanup_issue(diff_id=diff_id, op=op, field="target", code="missing_tombstone_target"))
        else:
            errors.append(_cleanup_issue(diff_id=diff_id, op=op, field="op", code="unsupported_op"))
    return {
        "schemaVersion": "rag-ime.cleanup-validate.v1",
        "ok": not errors,
        "runId": plan.run_id,
        "provider": plan.provider,
        "model": plan.model,
        "summary": plan.summary,
        "diffCount": len(plan.diffs),
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
    }


def validate_cleanup_plan(plan: CleanupRunPlan) -> None:
    if not compact_whitespace(plan.run_id):
        raise ValueError("cleanup run_id is required")
    supported_ops = {"add_stable_memory", "add_phrase", "tombstone"}
    for diff in plan.diffs:
        if diff.op not in supported_ops:
            raise ValueError(f"unsupported cleanup diff op: {diff.op}")
        if diff.op in {"add_stable_memory", "add_phrase"}:
            memory_id = compact_whitespace(str(diff.payload.get("memoryId", "")))
            text = compact_whitespace(str(diff.payload.get("text", "")))
            if not memory_id or not text:
                raise ValueError(f"{diff.op} requires non-empty memoryId and text")
        if diff.op == "tombstone":
            target_type = compact_whitespace(str(diff.payload.get("targetType", "")))
            target_value = compact_whitespace(str(diff.payload.get("targetValue", "")))
            if not target_type or not target_value:
                raise ValueError("tombstone requires targetType and targetValue")


def _validate_cleanup_diff_row_for_apply(row: sqlite3.Row) -> None:
    diff = CleanupDiffEntry(
        op=compact_whitespace(str(row["op"])),
        target_memory_id=compact_whitespace(str(row["target_memory_id"])),
        payload=dict(json.loads(row["payload_json"] or "{}")),
        status=compact_whitespace(str(row["status"])),
    )
    plan = CleanupRunPlan(run_id="stored_cleanup_apply_validation", diffs=(diff,))
    validate_cleanup_plan(plan)
    report = inspect_cleanup_plan(plan)
    if report["ok"]:
        return
    codes = ", ".join(str(item.get("code") or "invalid") for item in report["errors"])
    raise ValueError(f"cleanup diff {int(row['id'])} validation failed: {codes}")


def _cleanup_issue(*, diff_id: int, op: str, field: str, code: str, value: object = None, preview: str = "") -> dict[str, object]:
    payload = {
        "diffIndex": diff_id,
        "op": op,
        "field": field,
        "code": code,
    }
    if value is not None:
        payload["value"] = value
    if preview:
        payload["preview"] = preview
    return payload


def _looks_like_long_sentence(text: str) -> bool:
    compact = compact_whitespace(text)
    if len(compact) >= 20 and any(token in compact for token in ("，", "。", ",", ".", " ", "的", "了", "是")):
        return True
    return False


def _apply_add_stable_memory(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    memory_id = str(payload["memoryId"])
    existing = conn.execute("SELECT 1 FROM memory_items WHERE memory_id = ?", (memory_id,)).fetchone()
    if existing is not None:
        return {"createdMemoryId": "", "existingMemoryId": memory_id}
    text = str(payload["text"])
    tags = tuple(str(item) for item in (payload.get("tags") or []) if compact_whitespace(str(item)))
    timestamp = now_ms()
    upsert_memory_item(
        conn,
        memory_id=memory_id,
        kind="stable_memory",
        text=text,
        normalized_text=normalize_text(text),
        summary=f"cleanup stable memory from {payload.get('evidenceEventIds', [])}",
        source_event_id=int((payload.get("evidenceEventIds") or [0])[0] or 0) or None,
        project=str(payload.get("project", "")),
        app="",
        confidence=float(payload.get("confidence", 0.7)),
        quality_score=max(0.65, float(payload.get("confidence", 0.7))),
        status="approved",
        privacy_class="local",
        created_at_ms=timestamp,
        updated_at_ms=timestamp,
        metadata=dict(payload),
        tags=tags,
        embedding_provider=None,
    )
    return {"createdMemoryId": memory_id}


def _apply_add_phrase(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    memory_id = str(payload["memoryId"])
    existing = conn.execute("SELECT 1 FROM memory_items WHERE memory_id = ?", (memory_id,)).fetchone()
    if existing is not None:
        return {"createdMemoryId": "", "existingMemoryId": memory_id}
    text = str(payload["text"])
    tags = tuple(str(item) for item in (payload.get("tags") or []) if compact_whitespace(str(item)))
    weight = max(0.05, min(1.0, float(payload.get("weight", 0.6))))
    timestamp = now_ms()
    upsert_memory_item(
        conn,
        memory_id=memory_id,
        kind="phrase",
        text=text,
        normalized_text=normalize_text(text),
        summary=f"cleanup phrase | reason: {compact_whitespace(str(payload.get('reason', '')))}",
        source_event_id=None,
        project=str(payload.get("project", "")),
        app="",
        confidence=max(0.55, weight),
        quality_score=max(0.55, weight),
        status="approved",
        privacy_class="local",
        created_at_ms=timestamp,
        updated_at_ms=timestamp,
        metadata={**dict(payload), "direct_candidate_allowed": True},
        tags=tags,
        embedding_provider=None,
    )
    return {"createdMemoryId": memory_id}


def _apply_tombstone(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    cur = conn.execute(
        """
        INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            now_ms(),
            str(payload.get("targetType", "memory_id")),
            str(payload.get("targetValue", "")),
            str(payload.get("reason", "")),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    tombstone_id = int(cur.lastrowid)
    if payload.get("targetType") == "memory_id":
        conn.execute("UPDATE memory_items SET status = 'tombstoned' WHERE memory_id = ?", (str(payload.get("targetValue", "")),))
    return {"tombstoneId": tombstone_id}


def _prune_orphan_item_rows(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM memory_items_fts WHERE rowid NOT IN (SELECT id FROM memory_items)")
    conn.execute("DELETE FROM memory_item_vectors WHERE memory_item_id NOT IN (SELECT id FROM memory_items)")
    conn.execute("DELETE FROM memory_item_tags WHERE memory_item_id NOT IN (SELECT id FROM memory_items)")


def _apply_cleanup_diff_row(conn: sqlite3.Connection, *, row: sqlite3.Row) -> None:
    payload = json.loads(row["payload_json"] or "{}")
    rollback: dict[str, object] = {}
    if str(row["op"]) == "add_stable_memory":
        rollback = _apply_add_stable_memory(conn, payload)
    elif str(row["op"]) == "add_phrase":
        rollback = _apply_add_phrase(conn, payload)
    elif str(row["op"]) == "tombstone":
        rollback = _apply_tombstone(conn, payload)
    else:
        return
    conn.execute(
        """
        UPDATE memory_cleanup_diffs
        SET status = 'applied', applied_at_ms = ?, rollback_json = ?
        WHERE id = ?
        """,
        (now_ms(), json.dumps(rollback, ensure_ascii=False, sort_keys=True), int(row["id"])),
    )


def _rollback_cleanup_diff_row(conn: sqlite3.Connection, *, row: sqlite3.Row) -> None:
    rollback = json.loads(row["rollback_json"] or "{}")
    if str(row["op"]) == "add_stable_memory":
        memory_id = compact_whitespace(str(rollback.get("createdMemoryId", "")))
        if memory_id:
            conn.execute("DELETE FROM memory_items WHERE memory_id = ?", (memory_id,))
            _prune_orphan_item_rows(conn)
    elif str(row["op"]) == "add_phrase":
        memory_id = compact_whitespace(str(rollback.get("createdMemoryId", "")))
        if memory_id:
            conn.execute("DELETE FROM memory_items WHERE memory_id = ?", (memory_id,))
            _prune_orphan_item_rows(conn)
    elif str(row["op"]) == "tombstone":
        tombstone_id = int(rollback.get("tombstoneId") or 0)
        if tombstone_id:
            conn.execute("DELETE FROM memory_tombstones WHERE id = ?", (tombstone_id,))
    conn.execute("UPDATE memory_cleanup_diffs SET status = 'rolled_back' WHERE id = ?", (int(row["id"]),))


def _sync_cleanup_run_status(conn: sqlite3.Connection, *, run_id: str) -> None:
    rows = conn.execute(
        """
        SELECT status
        FROM memory_cleanup_diffs
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    ).fetchall()
    statuses = [str(row["status"]) for row in rows]
    if statuses and all(status == "rolled_back" for status in statuses):
        run_status = "rolled_back"
    elif any(status == "applied" for status in statuses):
        run_status = "applied"
    elif any(status in {"approved", "rejected"} for status in statuses):
        run_status = "reviewed"
    else:
        run_status = "draft"
    conn.execute("UPDATE memory_cleanup_runs SET status = ? WHERE run_id = ?", (run_status, run_id))
