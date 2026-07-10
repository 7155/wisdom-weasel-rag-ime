from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .deepseek_memory_organizer import MEMORY_BOOK_COMPILE_SCHEMA_VERSION
from .memory_ingest import normalize_text, upsert_memory_item
from .text_utils import compact_whitespace, now_ms, stable_text_hash, truncate_text


MEMORY_BOOK_RUN_SCHEMA_VERSION = "rag-ime.memory-book-run.v1"
MEMORY_BOOK_PREVIEW_SCHEMA_VERSION = "rag-ime.memory-book-preview.v1"
MEMORY_BOOK_VALIDATE_SCHEMA_VERSION = "rag-ime.memory-book-validate.v1"
MEMORY_BOOK_APPLY_SCHEMA_VERSION = "rag-ime.memory-book-apply.v1"
MEMORY_BOOK_ROLLBACK_SCHEMA_VERSION = "rag-ime.memory-book-rollback.v1"

_SECRET_RE = re.compile(r"(password|token|api[_ -]?key|bearer|sk-[A-Za-z0-9]{8,}|secret|验证码|身份证|手机号)", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:(?:/Users|/Volumes)/[^\s\"']+)")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def build_memory_book_source_bundle(
    conn: sqlite3.Connection,
    *,
    project: str,
    since_days: int = 7,
    limit: int = 80,
    after_event_id: int | None = None,
) -> dict[str, object]:
    state = memory_compile_state(conn, project=project)
    cursor = int(state["lastCompiledEventId"]) if after_event_id is None else max(0, int(after_event_id))
    cutoff_ms = now_ms() - max(1, int(since_days)) * 24 * 60 * 60 * 1000
    rows = conn.execute(
        """
        SELECT id, created_at_ms, source, committed_text, recent_context, app, project, tags_json,
               context_group_id, context_group_level
        FROM input_events
        WHERE id > ?
          AND created_at_ms >= ?
          AND (? = '' OR project = ? OR project = '')
        ORDER BY id ASC
        LIMIT ?
        """,
        (cursor, cutoff_ms, project, project, max(1, int(limit))),
    ).fetchall()
    events: list[dict[str, object]] = []
    redaction_stats = {"secret": 0, "path": 0, "email": 0}
    for row in rows:
        text, text_counts = _sanitize_text(str(row["committed_text"] or ""), max_chars=220)
        recent, recent_counts = _sanitize_text(str(row["recent_context"] or ""), max_chars=220)
        _merge_counts(redaction_stats, text_counts)
        _merge_counts(redaction_stats, recent_counts)
        events.append(
            {
                "eventId": int(row["id"]),
                "createdAtMs": int(row["created_at_ms"] or 0),
                "source": str(row["source"] or ""),
                "text": text,
                "recentContext": recent,
                "app": str(row["app"] or ""),
                "project": str(row["project"] or ""),
                "tags": _json_list(row["tags_json"]),
                "contextGroupId": str(row["context_group_id"] or ""),
                "contextGroupLevel": str(row["context_group_level"] or "app"),
            }
        )
    feedback = _source_feedback(conn, event_ids=[int(item["eventId"]) for item in events])
    existing_books = _existing_book_summaries(conn, project=project)
    legal_groups = sorted({str(item.get("contextGroupId") or "") for item in events if item.get("contextGroupId")})
    max_event_id = max((int(item["eventId"]) for item in events), default=cursor)
    pending_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM input_events WHERE id > ? AND (? = '' OR project = ? OR project = '')",
            (cursor, project, project),
        ).fetchone()[0]
    )
    payload = {
        "schemaVersion": "rag-ime.memory-book-source-bundle.v1",
        "project": project,
        "sinceDays": max(1, int(since_days)),
        "exportedAtMs": now_ms(),
        "redactionStats": redaction_stats,
        "recentEvents": events,
        "feedback": feedback,
        "existingMemoryBooks": existing_books,
        "legalContextGroupIds": legal_groups,
        "cursor": {
            "fromEventId": cursor,
            "toEventId": max_event_id,
            "pendingEventCount": pending_count,
        },
    }
    payload["bundleHash"] = stable_text_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload


def memory_compile_state(conn: sqlite3.Connection, *, project: str) -> dict[str, object]:
    _ensure_compile_state_table(conn)
    row = conn.execute(
        "SELECT last_compiled_event_id, last_run_ms, pending_event_count, last_bundle_hash "
        "FROM memory_compile_state WHERE project = ?",
        (project,),
    ).fetchone()
    last_event_id = int(row["last_compiled_event_id"] or 0) if row is not None else 0
    pending = int(
        conn.execute(
            "SELECT COUNT(*) FROM input_events WHERE id > ? AND (? = '' OR project = ? OR project = '')",
            (last_event_id, project, project),
        ).fetchone()[0]
    )
    return {
        "project": project,
        "lastCompiledEventId": last_event_id,
        "lastRunMs": int(row["last_run_ms"] or 0) if row is not None else 0,
        "pendingEventCount": pending,
        "lastBundleHash": str(row["last_bundle_hash"] or "") if row is not None else "",
    }


def memory_compile_due(
    conn: sqlite3.Connection,
    *,
    project: str,
    manual: bool = False,
    idle_ms: int = 0,
    current_ms: int | None = None,
    min_events: int = 50,
    idle_threshold_ms: int = 20 * 60 * 1000,
    daily_interval_ms: int = 24 * 60 * 60 * 1000,
) -> tuple[bool, str, dict[str, object]]:
    state = memory_compile_state(conn, project=project)
    if manual:
        return True, "manual", state
    if int(state["pendingEventCount"]) >= max(1, int(min_events)):
        return True, "pending_events", state
    if int(state["pendingEventCount"]) > 0 and int(idle_ms) >= max(1, int(idle_threshold_ms)):
        return True, "idle", state
    current = now_ms() if current_ms is None else max(0, int(current_ms))
    if int(state["pendingEventCount"]) > 0 and current - int(state["lastRunMs"]) >= max(1, int(daily_interval_ms)):
        return True, "daily", state
    return False, "not_due", state


def memory_book_plan_from_compile_output(
    compile_output: dict[str, object],
    *,
    project: str,
    provider: str,
    model: str,
    source_bundle: dict[str, object] | None = None,
    _allow_fallback: bool = True,
) -> dict[str, object]:
    diffs: list[dict[str, object]] = []
    warnings = list(compile_output.get("warnings") or [])
    for item in _list_of_dicts(compile_output.get("dailyBooks")):
        title = compact_whitespace(str(item.get("title") or ""))
        summary = compact_whitespace(str(item.get("summary") or ""))
        if not title and not summary:
            continue
        book_key = compact_whitespace(str(item.get("bookKey") or "")) or _default_book_key(source_bundle)
        book_id = compact_whitespace(str(item.get("bookId") or "")) or f"book:daily:{book_key}"
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [book_key, title, summary, *_strings(item.get("tags")), *_strings(item.get("surfaceHints"))],
            source_bundle=source_bundle,
        )
        payload = {
            "bookId": book_id,
            "bookType": compact_whitespace(str(item.get("bookType") or "daily")) or "daily",
            "bookKey": book_key,
            "title": title,
            "summary": summary,
            "tags": _strings(item.get("tags")),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": source_ids,
            "memoryAtomIds": _strings(item.get("memoryAtomIds")),
            "project": compact_whitespace(str(item.get("project") or project)),
            "app": compact_whitespace(str(item.get("app") or "")),
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=_bounded_float(item.get("confidence"), default=0.5)),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
            "contextGroupId": compact_whitespace(str(item.get("groupId") or item.get("contextGroupId") or ""))
            or _group_for_source_ids(source_ids, source_bundle=source_bundle),
        }
        diffs.append({"op": "upsert_memory_book", "targetId": book_id, "payload": payload, "status": "pending"})
    for item in _list_of_dicts(compile_output.get("memoryAtoms")):
        atom_id = compact_whitespace(str(item.get("atomId") or item.get("id") or ""))
        canonical = compact_whitespace(str(item.get("canonicalText") or item.get("text") or ""))
        if not canonical:
            continue
        if not atom_id and canonical:
            atom_id = f"atom:{stable_text_hash(canonical)[:16]}"
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [
                canonical,
                compact_whitespace(str(item.get("summary") or "")),
                *_strings(item.get("tags")),
                *_strings(item.get("aliases")),
                *_strings(item.get("surfaceHints")),
                *_strings(item.get("queryExpansions")),
            ],
            source_bundle=source_bundle,
        )
        payload = {
            "atomId": atom_id,
            "kind": compact_whitespace(str(item.get("kind") or "project_fact")),
            "canonicalText": canonical,
            "summary": compact_whitespace(str(item.get("summary") or "")),
            "tags": _strings(item.get("tags")),
            "aliases": _strings(item.get("aliases")),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": source_ids,
            "sourceMemoryIds": _strings(item.get("sourceMemoryIds")),
            "directCandidateAllowed": bool(item.get("directCandidateAllowed", False)),
            "project": compact_whitespace(str(item.get("project") or project)),
            "app": compact_whitespace(str(item.get("app") or "")),
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=0.5),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
            "contextGroupId": compact_whitespace(str(item.get("groupId") or item.get("contextGroupId") or ""))
            or _group_for_source_ids(source_ids, source_bundle=source_bundle),
        }
        diffs.append({"op": "upsert_memory_atom", "targetId": atom_id, "payload": payload, "status": "pending"})
    for item in _list_of_dicts(compile_output.get("tagEdges")):
        src = compact_whitespace(str(item.get("src") or ""))
        dst = compact_whitespace(str(item.get("dst") or ""))
        if not src or not dst:
            continue
        edge_type = compact_whitespace(str(item.get("edgeType") or "related")) or "related"
        evidence_ids = _positive_ints(item.get("evidenceEventIds")) or _infer_source_event_ids(
            [src, dst, edge_type],
            source_bundle=source_bundle,
        )
        target = f"tag-edge:{src}->{dst}:{edge_type}"
        diffs.append(
            {
                "op": "upsert_tag_edge",
                "targetId": target,
                "payload": {
                    "src": src,
                    "dst": dst,
                    "edgeType": edge_type,
                    "weight": _bounded_float(item.get("weight"), default=0.5),
                    "evidenceEventIds": evidence_ids,
                },
                "status": "pending",
            }
        )
    for item in _list_of_dicts(compile_output.get("phraseCandidates")):
        text = compact_whitespace(str(item.get("text") or ""))
        if len(text) < 2 or len(text) > 18:
            continue
        target = f"phrase:{normalize_text(text)}"
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [text, *_strings(item.get("tags"))],
            source_bundle=source_bundle,
        )
        diffs.append(
            {
                "op": "add_phrase_candidate",
                "targetId": target,
                "payload": {
                    "memoryId": target,
                    "text": text,
                    "tags": _strings(item.get("tags")),
                    "sourceEventIds": source_ids,
                    "weight": _bounded_float(item.get("weight"), default=0.6),
                    "project": compact_whitespace(str(item.get("project") or project)),
                    "contextGroupId": compact_whitespace(str(item.get("groupId") or item.get("contextGroupId") or ""))
                    or _group_for_source_ids(source_ids, source_bundle=source_bundle),
                },
                "status": "pending",
            }
        )
    for raw_item in compile_output.get("negativePhrases", []) if isinstance(compile_output.get("negativePhrases"), list) else []:
        item = raw_item if isinstance(raw_item, dict) else {"text": raw_item}
        text = compact_whitespace(str(item.get("text") or ""))
        if not 2 <= len(text) <= 18:
            continue
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [text],
            source_bundle=source_bundle,
        )
        target = f"negative:{stable_text_hash(text)[:16]}"
        diffs.append(
            {
                "op": "add_negative_phrase",
                "targetId": target,
                "payload": {
                    "suppressionId": target,
                    "text": text,
                    "sourceEventIds": source_ids,
                    "reason": compact_whitespace(str(item.get("reason") or "memory_compiler_negative_phrase")),
                },
                "status": "pending",
            }
        )
    for item in _list_of_dicts(compile_output.get("supersedes")):
        old_id = compact_whitespace(str(item.get("oldId") or item.get("supersededId") or ""))
        new_id = compact_whitespace(str(item.get("newId") or item.get("supersedingId") or ""))
        if not old_id or not new_id or old_id == new_id:
            continue
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [old_id, new_id],
            source_bundle=source_bundle,
        )
        diffs.append(
            {
                "op": "supersede_memory",
                "targetId": old_id,
                "payload": {
                    "oldId": old_id,
                    "newId": new_id,
                    "sourceEventIds": source_ids,
                },
                "status": "pending",
            }
        )
    run_id = f"memory_book_{now_ms()}"
    if source_bundle and not any(diff.get("op") == "upsert_memory_book" for diff in diffs):
        daily_book = _synthesize_daily_book_diff_from_diffs(diffs, project=project, source_bundle=source_bundle)
        if daily_book:
            diffs.insert(0, daily_book)
            warnings.append("daily_book_synthesized_from_atoms")
    if _allow_fallback and not diffs and source_bundle:
        fallback_output = _fallback_compile_output_from_source_bundle(source_bundle, project=project)
        if any(fallback_output.get(key) for key in ("dailyBooks", "memoryAtoms", "tagEdges", "phraseCandidates")):
            fallback_warnings = list(fallback_output.get("warnings") or [])
            fallback_output["warnings"] = [*warnings, *fallback_warnings]
            fallback_output["elapsedMs"] = int(compile_output.get("elapsedMs") or 0)
            return memory_book_plan_from_compile_output(
                fallback_output,
                project=project,
                provider=provider,
                model=model,
                source_bundle=source_bundle,
                _allow_fallback=False,
            )
    return {
        "schemaVersion": MEMORY_BOOK_RUN_SCHEMA_VERSION,
        "runId": run_id,
        "provider": provider,
        "model": model,
        "summary": _memory_book_summary(diffs),
        "metadata": {
            "compileSchemaVersion": str(compile_output.get("schemaVersion") or MEMORY_BOOK_COMPILE_SCHEMA_VERSION),
            "warnings": warnings,
            "elapsedMs": int(compile_output.get("elapsedMs") or 0),
            "project": project,
            "bundleHash": str((source_bundle or {}).get("bundleHash") or ""),
            "sourceCursor": dict((source_bundle or {}).get("cursor") or {}),
            "legalContextGroupIds": list((source_bundle or {}).get("legalContextGroupIds") or []),
        },
        "diffs": diffs,
    }


def load_memory_book_plan(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("memory book run file must contain a JSON object")
    return payload


def inspect_memory_book_plan(plan: dict[str, object]) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    counts: dict[str, int] = {
        "memoryBooks": 0,
        "memoryAtoms": 0,
        "tagEdges": 0,
        "phraseCandidates": 0,
        "negativePhrases": 0,
        "supersedes": 0,
    }
    diffs = _list_of_dicts(plan.get("diffs"))
    if compact_whitespace(str(plan.get("schemaVersion") or "")) != MEMORY_BOOK_RUN_SCHEMA_VERSION:
        errors.append(_issue(0, "", "schemaVersion", "unsupported_schema_version"))
    for index, diff in enumerate(diffs, start=1):
        op = compact_whitespace(str(diff.get("op") or ""))
        payload = diff.get("payload") if isinstance(diff.get("payload"), dict) else {}
        if op == "upsert_memory_book":
            counts["memoryBooks"] += 1
            _validate_required_text(errors, index, op, payload, "bookId")
            _validate_required_text(errors, index, op, payload, "bookKey")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"))
            _validate_short_terms(errors, index, op, "surfaceHints", payload.get("surfaceHints"), max_len=16)
            _validate_secret_free(errors, index, op, payload, ("title", "summary", "surfaceHints", "queryExpansions"))
        elif op == "upsert_memory_atom":
            counts["memoryAtoms"] += 1
            _validate_required_text(errors, index, op, payload, "atomId")
            _validate_required_text(errors, index, op, payload, "canonicalText")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"))
            _validate_short_terms(errors, index, op, "surfaceHints", payload.get("surfaceHints"), max_len=16)
            _validate_secret_free(errors, index, op, payload, ("canonicalText", "summary", "aliases", "surfaceHints", "queryExpansions"))
            if bool(payload.get("directCandidateAllowed")):
                errors.append(_issue(index, op, "directCandidateAllowed", "canonical_text_must_not_be_direct_candidate"))
        elif op == "upsert_tag_edge":
            counts["tagEdges"] += 1
            _validate_required_text(errors, index, op, payload, "src")
            _validate_required_text(errors, index, op, payload, "dst")
            _validate_source_ids(errors, index, op, payload.get("evidenceEventIds"))
            _validate_secret_free(errors, index, op, payload, ("src", "dst"))
        elif op == "add_phrase_candidate":
            counts["phraseCandidates"] += 1
            _validate_required_text(errors, index, op, payload, "text")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"))
            text = compact_whitespace(str(payload.get("text") or ""))
            if len(text) < 2 or len(text) > 18:
                errors.append(_issue(index, op, "text", "phrase_text_length_out_of_range", value=len(text), preview=truncate_text(text, 80)))
            _validate_secret_free(errors, index, op, payload, ("text", "tags"))
        elif op == "add_negative_phrase":
            counts["negativePhrases"] += 1
            _validate_required_text(errors, index, op, payload, "suppressionId")
            _validate_required_text(errors, index, op, payload, "text")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"))
            _validate_secret_free(errors, index, op, payload, ("text", "reason"))
        elif op == "supersede_memory":
            counts["supersedes"] += 1
            _validate_required_text(errors, index, op, payload, "oldId")
            _validate_required_text(errors, index, op, payload, "newId")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"))
        else:
            errors.append(_issue(index, op, "op", "unsupported_op"))
        if op and _looks_like_long_history_sentence(payload):
            warnings.append(_issue(index, op, "payload", "looks_like_long_history_sentence"))
        legal_groups = {
            compact_whitespace(str(item))
            for item in dict(plan.get("metadata") or {}).get("legalContextGroupIds", [])
            if compact_whitespace(str(item))
        }
        group_id = compact_whitespace(str(payload.get("contextGroupId") or ""))
        if group_id and legal_groups and group_id not in legal_groups and group_id != "global":
            errors.append(_issue(index, op, "contextGroupId", "context_group_not_in_source_bundle"))
    return {
        "schemaVersion": MEMORY_BOOK_VALIDATE_SCHEMA_VERSION,
        "ok": not errors,
        "runId": str(plan.get("runId") or ""),
        "provider": str(plan.get("provider") or ""),
        "model": str(plan.get("model") or ""),
        "summary": str(plan.get("summary") or ""),
        "diffCount": len(diffs),
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
    }


def apply_memory_book_plan(conn: sqlite3.Connection, plan: dict[str, object]) -> dict[str, object]:
    validation = inspect_memory_book_plan(plan)
    if not validation.get("ok"):
        raise ValueError("memory book plan failed validation")
    run_id = compact_whitespace(str(plan.get("runId") or ""))
    if not run_id:
        raise ValueError("memory book runId is required")
    with conn:
        _persist_memory_book_run(conn, plan)
        rows = conn.execute(
            """
            SELECT id, op, target_memory_id, payload_json
            FROM memory_cleanup_diffs
            WHERE run_id = ? AND status IN ('pending', 'approved')
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        for row in rows:
            rollback = _apply_memory_book_diff(conn, row=row)
            conn.execute(
                """
                UPDATE memory_cleanup_diffs
                SET status = 'applied', applied_at_ms = ?, rollback_json = ?
                WHERE id = ?
                """,
                (now_ms(), json.dumps(rollback, ensure_ascii=False, sort_keys=True), int(row["id"])),
            )
        _sync_run_status(conn, run_id)
        _advance_compile_state(conn, plan=plan)
    return memory_book_run_payload(conn, run_id=run_id)


def rollback_memory_book_run(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
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
        _rollback_memory_book_diff(conn, row=row)
        conn.execute("UPDATE memory_cleanup_diffs SET status = 'rolled_back' WHERE id = ?", (int(row["id"]),))
    _sync_run_status(conn, run_id)
    return memory_book_run_payload(conn, run_id=run_id)


def memory_book_run_payload(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
    run = conn.execute(
        """
        SELECT run_id, provider, model, status, summary, metadata_json
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
        "provider": "" if run is None else str(run["provider"]),
        "model": "" if run is None else str(run["model"]),
        "summary": "" if run is None else str(run["summary"]),
        "metadata": {} if run is None else json.loads(run["metadata_json"] or "{}"),
        "diffs": [
            {
                "diffId": int(row["id"]),
                "op": str(row["op"]),
                "targetId": str(row["target_memory_id"]),
                "payload": json.loads(row["payload_json"] or "{}"),
                "status": str(row["status"]),
                "createdAtMs": int(row["created_at_ms"] or 0),
                "appliedAtMs": int(row["applied_at_ms"] or 0),
            }
            for row in diffs
        ],
    }


def _persist_memory_book_run(conn: sqlite3.Connection, plan: dict[str, object]) -> None:
    run_id = compact_whitespace(str(plan.get("runId") or ""))
    created_at = now_ms()
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_cleanup_runs(run_id, created_at_ms, provider, model, status, summary, metadata_json)
        VALUES (?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            run_id,
            created_at,
            str(plan.get("provider") or ""),
            str(plan.get("model") or ""),
            str(plan.get("summary") or ""),
            json.dumps(dict(plan.get("metadata") or {}), ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.execute("DELETE FROM memory_cleanup_diffs WHERE run_id = ?", (run_id,))
    for diff in _list_of_dicts(plan.get("diffs")):
        conn.execute(
            """
            INSERT INTO memory_cleanup_diffs(run_id, op, target_memory_id, payload_json, status, created_at_ms, rollback_json)
            VALUES (?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                run_id,
                str(diff.get("op") or ""),
                str(diff.get("targetId") or diff.get("targetMemoryId") or ""),
                json.dumps(dict(diff.get("payload") or {}), ensure_ascii=False, sort_keys=True),
                str(diff.get("status") or "pending"),
                created_at,
            ),
        )


def _apply_memory_book_diff(conn: sqlite3.Connection, *, row: sqlite3.Row) -> dict[str, object]:
    op = str(row["op"])
    payload = json.loads(row["payload_json"] or "{}")
    if op == "upsert_memory_book":
        return _apply_memory_book(conn, payload)
    if op == "upsert_memory_atom":
        return _apply_memory_atom(conn, payload)
    if op == "upsert_tag_edge":
        return _apply_tag_edge(conn, payload)
    if op == "add_phrase_candidate":
        return _apply_phrase_candidate(conn, payload)
    if op == "add_negative_phrase":
        return _apply_negative_phrase(conn, payload)
    if op == "supersede_memory":
        return _apply_supersede_memory(conn, payload)
    raise ValueError(f"unsupported memory book op: {op}")


def _rollback_memory_book_diff(conn: sqlite3.Connection, *, row: sqlite3.Row) -> None:
    op = str(row["op"])
    rollback = json.loads(row["rollback_json"] or "{}")
    if op == "upsert_memory_book":
        _restore_or_delete_row(conn, table="memory_books", pk="book_id", rollback=rollback)
    elif op == "upsert_memory_atom":
        _restore_or_delete_row(conn, table="memory_atoms", pk="id", rollback=rollback)
        for alias_id in rollback.get("createdAliasIds", []) or []:
            conn.execute("DELETE FROM memory_aliases WHERE id = ?", (str(alias_id),))
    elif op == "upsert_tag_edge":
        edge = rollback.get("edge")
        if isinstance(edge, dict):
            conn.execute(
                "DELETE FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
                (int(edge.get("srcTagId") or 0), int(edge.get("dstTagId") or 0), str(edge.get("edgeType") or "")),
            )
    elif op == "add_phrase_candidate":
        _restore_or_delete_row(conn, table="memory_items", pk="memory_id", rollback=rollback)
        conn.execute("DELETE FROM memory_items_fts WHERE rowid NOT IN (SELECT id FROM memory_items)")
        conn.execute("DELETE FROM memory_item_tags WHERE memory_item_id NOT IN (SELECT id FROM memory_items)")
    elif op == "add_negative_phrase":
        _restore_or_delete_row(conn, table="memory_candidate_suppressions", pk="id", rollback=rollback)
    elif op == "supersede_memory":
        table = compact_whitespace(str(rollback.get("table") or ""))
        pk = "id" if table == "memory_atoms" else "memory_id"
        if table in {"memory_atoms", "memory_items"}:
            _restore_or_delete_row(conn, table=table, pk=pk, rollback=rollback)


def _apply_memory_book(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    book_id = str(payload["bookId"])
    previous = _row_dict(conn.execute("SELECT * FROM memory_books WHERE book_id = ?", (book_id,)).fetchone())
    timestamp = now_ms()
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_books(
            book_id, book_type, book_key, title, summary, normalized_text, project, app,
            tags_json, surface_hints_json, query_expansions_json, source_event_ids_json,
            memory_atom_ids_json, status, confidence, quality_score, created_at_ms, updated_at_ms, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at_ms FROM memory_books WHERE book_id = ?), ?), ?, ?)
        """,
        (
            book_id,
            str(payload.get("bookType") or "daily"),
            str(payload.get("bookKey") or ""),
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            normalize_text(f"{payload.get('title', '')} {payload.get('summary', '')}"),
            str(payload.get("project") or ""),
            str(payload.get("app") or ""),
            json.dumps(_strings(payload.get("tags")), ensure_ascii=False),
            json.dumps(_strings(payload.get("surfaceHints")), ensure_ascii=False),
            json.dumps(_strings(payload.get("queryExpansions")), ensure_ascii=False),
            json.dumps(_positive_ints(payload.get("sourceEventIds")), ensure_ascii=False),
            json.dumps(_strings(payload.get("memoryAtomIds")), ensure_ascii=False),
            str(payload.get("status") or "active"),
            _bounded_float(payload.get("confidence"), default=0.5),
            _bounded_float(payload.get("qualityScore"), default=0.5),
            book_id,
            timestamp,
            timestamp,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {"table": "memory_books", "pk": "book_id", "pkValue": book_id, "previous": previous}


def _apply_memory_atom(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    atom_id = str(payload["atomId"])
    previous = _row_dict(conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone())
    timestamp = now_ms()
    canonical = str(payload.get("canonicalText") or "")
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_atoms(
            id, kind, text, canonical_text, source_event_ids_json, source_memory_ids_json,
            scope_app, scope_project, language, confidence, quality_score, echo_risk,
            privacy_level, status, created_at_ms, updated_at_ms, last_used_at_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'zh', ?, ?, 0.0, 'local', ?, COALESCE((SELECT created_at_ms FROM memory_atoms WHERE id = ?), ?), ?, NULL)
        """,
        (
            atom_id,
            str(payload.get("kind") or "project_fact"),
            canonical,
            canonical,
            json.dumps(_positive_ints(payload.get("sourceEventIds")), ensure_ascii=False),
            json.dumps(_strings(payload.get("sourceMemoryIds")), ensure_ascii=False),
            str(payload.get("app") or ""),
            str(payload.get("project") or ""),
            _bounded_float(payload.get("confidence"), default=0.5),
            _bounded_float(payload.get("qualityScore"), default=0.5),
            str(payload.get("status") or "active"),
            atom_id,
            timestamp,
            timestamp,
        ),
    )
    created_alias_ids: list[str] = []
    for alias_type, values in (
        ("alias", _strings(payload.get("aliases"))),
        ("surface_hint", _strings(payload.get("surfaceHints"))),
        ("query_expansion", _strings(payload.get("queryExpansions"))),
    ):
        for value in values:
            alias_id = f"alias:{stable_text_hash(f'{atom_id}:{alias_type}:{value}')[:20]}"
            existed = conn.execute("SELECT 1 FROM memory_aliases WHERE id = ?", (alias_id,)).fetchone() is not None
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_aliases(id, memory_atom_id, alias, alias_type, pinyin, weight, created_at_ms)
                VALUES (?, ?, ?, ?, '', ?, ?)
                """,
                (alias_id, atom_id, value, alias_type, 0.8 if alias_type != "alias" else 0.6, timestamp),
            )
            if not existed:
                created_alias_ids.append(alias_id)
    conn.execute("DELETE FROM memory_atom_tags WHERE memory_atom_id = ?", (atom_id,))
    for tag in _strings(payload.get("tags")):
        tag_id = _ensure_tag(conn, tag)
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
            VALUES (?, ?, 0.8, 'memory_book_compile')
            """,
            (atom_id, str(tag_id)),
        )
    return {"table": "memory_atoms", "pk": "id", "pkValue": atom_id, "previous": previous, "createdAliasIds": created_alias_ids}


def _apply_tag_edge(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    src_id = _ensure_tag(conn, str(payload.get("src") or ""))
    dst_id = _ensure_tag(conn, str(payload.get("dst") or ""))
    edge_type = str(payload.get("edgeType") or "related")
    conn.execute(
        """
        INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, evidence_count, updated_at_ms, metadata_json)
        VALUES (?, ?, ?, ?, 0.0, ?, ?, ?)
        ON CONFLICT(src_tag_id, dst_tag_id, edge_type) DO UPDATE SET
            weight = excluded.weight,
            evidence_count = excluded.evidence_count,
            updated_at_ms = excluded.updated_at_ms,
            metadata_json = excluded.metadata_json
        """,
        (
            src_id,
            dst_id,
            edge_type,
            _bounded_float(payload.get("weight"), default=0.5),
            max(1, len(_positive_ints(payload.get("evidenceEventIds")))),
            now_ms(),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {"edge": {"srcTagId": src_id, "dstTagId": dst_id, "edgeType": edge_type}}


def _apply_phrase_candidate(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    memory_id = str(payload["memoryId"])
    previous = _row_dict(conn.execute("SELECT * FROM memory_items WHERE memory_id = ?", (memory_id,)).fetchone())
    text = str(payload.get("text") or "")
    evidence_ids = _positive_ints(payload.get("sourceEventIds"))
    timestamp = now_ms()
    upsert_memory_item(
        conn,
        memory_id=memory_id,
        kind="phrase",
        text=text,
        normalized_text=normalize_text(text),
        summary="memory-book phrase candidate",
        source_event_id=evidence_ids[0] if evidence_ids else None,
        project=str(payload.get("project") or ""),
        app="",
        confidence=max(0.55, _bounded_float(payload.get("weight"), default=0.6)),
        quality_score=max(0.55, _bounded_float(payload.get("weight"), default=0.6)),
        status="approved",
        privacy_class="local",
        created_at_ms=timestamp,
        updated_at_ms=timestamp,
        metadata={**payload, "direct_candidate_allowed": True, "source": "memory_book_compile"},
        tags=tuple(_strings(payload.get("tags"))),
        embedding_provider=None,
    )
    return {"table": "memory_items", "pk": "memory_id", "pkValue": memory_id, "previous": previous}


def _apply_negative_phrase(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    suppression_id = str(payload["suppressionId"])
    previous = _row_dict(
        conn.execute("SELECT * FROM memory_candidate_suppressions WHERE id = ?", (suppression_id,)).fetchone()
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_candidate_suppressions(
            id, match_type, match_value, action, reason, strength, expires_at_ms, created_at_ms
        ) VALUES (?, 'text', ?, 'block', ?, 1.0, NULL, ?)
        """,
        (suppression_id, str(payload.get("text") or ""), str(payload.get("reason") or ""), now_ms()),
    )
    return {
        "table": "memory_candidate_suppressions",
        "pk": "id",
        "pkValue": suppression_id,
        "previous": previous,
    }


def _apply_supersede_memory(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    old_id = str(payload["oldId"])
    atom = conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (old_id,)).fetchone()
    if atom is not None:
        previous = _row_dict(atom)
        conn.execute("UPDATE memory_atoms SET status = 'superseded', updated_at_ms = ? WHERE id = ?", (now_ms(), old_id))
        return {"table": "memory_atoms", "pk": "id", "pkValue": old_id, "previous": previous}
    item = conn.execute("SELECT * FROM memory_items WHERE memory_id = ?", (old_id,)).fetchone()
    if item is not None:
        previous = _row_dict(item)
        conn.execute("UPDATE memory_items SET status = 'hidden', updated_at_ms = ? WHERE memory_id = ?", (now_ms(), old_id))
        return {"table": "memory_items", "pk": "memory_id", "pkValue": old_id, "previous": previous}
    raise ValueError(f"superseded memory does not exist: {old_id}")


def _restore_or_delete_row(conn: sqlite3.Connection, *, table: str, pk: str, rollback: dict[str, object]) -> None:
    pk_value = str(rollback.get("pkValue") or "")
    previous = rollback.get("previous")
    if isinstance(previous, dict) and previous:
        columns = list(previous.keys())
        assignments = ", ".join(f"{col} = ?" for col in columns)
        values = [previous[col] for col in columns]
        conn.execute(f"INSERT OR REPLACE INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", values)
        return
    if pk_value:
        conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (pk_value,))


def _ensure_tag(conn: sqlite3.Connection, tag: str) -> int:
    value = compact_whitespace(tag)
    row = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (value,)).fetchone()
    if row is not None:
        return int(row["id"])
    cur = conn.execute(
        """
        INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms)
        VALUES (?, ?, 'concept', 0.6, ?, ?)
        """,
        (value, normalize_text(value), now_ms(), now_ms()),
    )
    return int(cur.lastrowid)


def _sync_run_status(conn: sqlite3.Connection, run_id: str) -> None:
    rows = conn.execute("SELECT status FROM memory_cleanup_diffs WHERE run_id = ?", (run_id,)).fetchall()
    statuses = {str(row["status"]) for row in rows}
    if not statuses:
        status = "empty"
    elif statuses == {"applied"}:
        status = "applied"
    elif statuses == {"rolled_back"}:
        status = "rolled_back"
    elif "applied" in statuses:
        status = "partial"
    else:
        status = "draft"
    conn.execute("UPDATE memory_cleanup_runs SET status = ? WHERE run_id = ?", (status, run_id))


def _synthesize_daily_book_diff_from_diffs(
    diffs: list[dict[str, object]],
    *,
    project: str,
    source_bundle: dict[str, object],
) -> dict[str, object] | None:
    atom_payloads = [
        diff.get("payload")
        for diff in diffs
        if diff.get("op") == "upsert_memory_atom" and isinstance(diff.get("payload"), dict)
    ]
    if not atom_payloads:
        return None
    source_ids: list[int] = []
    tags: list[str] = []
    hints: list[str] = []
    atom_ids: list[str] = []
    for payload in atom_payloads:
        if not isinstance(payload, dict):
            continue
        for event_id in _positive_ints(payload.get("sourceEventIds")):
            if event_id not in source_ids:
                source_ids.append(event_id)
        tags.extend(_strings(payload.get("tags")))
        hints.extend(_strings(payload.get("surfaceHints")))
        atom_id = compact_whitespace(str(payload.get("atomId") or ""))
        if atom_id and atom_id not in atom_ids:
            atom_ids.append(atom_id)
    for diff in diffs:
        if diff.get("op") != "add_phrase_candidate" or not isinstance(diff.get("payload"), dict):
            continue
        text = compact_whitespace(str(diff["payload"].get("text") or ""))
        if 2 <= len(text) <= 16:
            hints.append(text)
        for event_id in _positive_ints(diff["payload"].get("sourceEventIds")):
            if event_id not in source_ids:
                source_ids.append(event_id)
    if not source_ids:
        source_ids = _infer_source_event_ids(hints, source_bundle=source_bundle, limit=6)
    if not source_ids:
        return None
    book_key = _default_book_key(source_bundle)
    book_id = f"book:daily:{book_key}"
    unique_hints = [item for item in _unique_strings(hints, limit=6) if 2 <= len(item) <= 16]
    payload = {
        "bookId": book_id,
        "bookType": "daily",
        "bookKey": book_key,
        "title": "RAG 输入法真实历史整理摘要",
        "summary": f"本轮从真实 Codex 历史整理出 {len(atom_payloads)} 个记忆原子和若干短候选，用于输入法 RAG 展示和评测。",
        "tags": _unique_strings(tags or ["RAG", "输入法", "Memory Book"], limit=8),
        "surfaceHints": unique_hints[:3] or ["历史整理", "流式候选", "真实链路"],
        "queryExpansions": ["RAG 输入法", "DeepSeek 整理", "Memory Book"],
        "sourceEventIds": source_ids[:10],
        "memoryAtomIds": atom_ids,
        "project": project,
        "app": "",
        "confidence": 0.6,
        "qualityScore": 0.6,
        "status": "active",
    }
    return {"op": "upsert_memory_book", "targetId": book_id, "payload": payload, "status": "pending"}


def _fallback_compile_output_from_source_bundle(source_bundle: dict[str, object], *, project: str) -> dict[str, object]:
    events = [event for event in _source_event_records(source_bundle) if _fallback_event_is_safe(str(event.get("text") or ""))]
    atoms: dict[str, dict[str, object]] = {}
    phrases: dict[str, dict[str, object]] = {}
    edges: dict[str, dict[str, object]] = {}

    def add_atom(
        atom_id: str,
        *,
        canonical: str,
        summary: str,
        tags: list[str],
        aliases: list[str],
        hints: list[str],
        phrase_terms: list[str],
        source_event_id: int,
    ) -> None:
        payload = atoms.setdefault(
            atom_id,
            {
                "atomId": atom_id,
                "kind": "project_fact",
                "canonicalText": canonical,
                "summary": summary,
                "tags": tags,
                "aliases": aliases,
                "surfaceHints": hints,
                "queryExpansions": aliases,
                "sourceEventIds": [],
                "directCandidateAllowed": False,
                "project": project,
                "confidence": 0.62,
                "qualityScore": 0.62,
            },
        )
        source_ids = _positive_ints(payload.get("sourceEventIds"))
        if source_event_id not in source_ids:
            source_ids.append(source_event_id)
            payload["sourceEventIds"] = source_ids[:6]
        for term in phrase_terms:
            if 2 <= len(term) <= 16:
                phrase = phrases.setdefault(
                    term,
                    {
                        "text": term,
                        "tags": tags[:3],
                        "sourceEventIds": [],
                        "weight": 0.62,
                        "project": project,
                    },
                )
                phrase_ids = _positive_ints(phrase.get("sourceEventIds"))
                if source_event_id not in phrase_ids:
                    phrase_ids.append(source_event_id)
                    phrase["sourceEventIds"] = phrase_ids[:6]

    def add_edge(src: str, dst: str, edge_type: str, source_event_id: int) -> None:
        key = f"{src}->{dst}:{edge_type}"
        payload = edges.setdefault(
            key,
            {
                "src": src,
                "dst": dst,
                "edgeType": edge_type,
                "weight": 0.58,
                "evidenceEventIds": [],
            },
        )
        evidence_ids = _positive_ints(payload.get("evidenceEventIds"))
        if source_event_id not in evidence_ids:
            evidence_ids.append(source_event_id)
            payload["evidenceEventIds"] = evidence_ids[:6]

    for event in events[:80]:
        event_id = int(event["eventId"])
        text = str(event.get("text") or "")
        haystack = text.lower()
        if "deepseek" in haystack and ("历史" in text or "整理" in text or "rag" in haystack):
            add_atom(
                "atom:deepseek-history-rag-cleanup",
                canonical="用户希望使用 DeepSeek 离线整理 Codex 历史并写入 RAG DB。",
                summary="DeepSeek 用于离线清理、整理和追加历史记忆，不走实时按键预测。",
                tags=["DeepSeek", "RAG DB", "Codex历史"],
                aliases=["DeepSeek整理历史", "历史库清理"],
                hints=["DeepSeek整理", "历史库清理"],
                phrase_terms=["DeepSeek整理", "历史库清理"],
                source_event_id=event_id,
            )
            add_edge("DeepSeek", "RAG DB", "offline_cleanup", event_id)
        if "流式" in text or "首帧" in text or "没有流" in text or "stream" in haystack:
            add_atom(
                "atom:ime-visible-streaming-candidate",
                canonical="用户要求输入法 LLM 候选具备可见首帧和连续流式更新。",
                summary="post-commit 预测必须先显示首帧候选，再用同一槽位持续替换更新。",
                tags=["输入法", "流式候选", "LLM"],
                aliases=["首帧流式", "post-commit流式"],
                hints=["流式候选", "首帧候选"],
                phrase_terms=["流式候选", "首帧候选"],
                source_event_id=event_id,
            )
            add_edge("输入法", "流式候选", "requires", event_id)
        if "squirrel" in haystack or "rime" in haystack or ("真实" in text and "输入法" in text):
            add_atom(
                "atom:real-squirrel-rime-chain",
                canonical="RAG-IME 的功能必须挂回真实 Squirrel/Rime 输入法候选链路。",
                summary="整理不是删功能，而是把 RAG、LLM 和 Active Assist 接回真实输入法链路。",
                tags=["Squirrel", "Rime", "真实链路"],
                aliases=["真实输入法链路", "Squirrel候选"],
                hints=["真实链路", "Squirrel链路"],
                phrase_terms=["真实链路", "Squirrel链路"],
                source_event_id=event_id,
            )
            add_edge("RAG-IME", "Squirrel", "frontend_chain", event_id)
        if "快捷键" in text or "框选" in text or "选区" in text or "active rag" in haystack:
            add_atom(
                "atom:active-rag-assist-shortcut-selection",
                canonical="Active RAG Assist 应通过快捷键触发选区预测，不塞进每次按键。",
                summary="普通 rime-suggest 保持轻量，选区/框选预测走独立助手入口。",
                tags=["Active RAG Assist", "快捷键", "选区预测"],
                aliases=["框选预测", "快捷键触发"],
                hints=["选区预测", "框选预测"],
                phrase_terms=["选区预测", "框选预测"],
                source_event_id=event_id,
            )
            add_edge("Active RAG Assist", "快捷键", "triggered_by", event_id)
        if "面试" in text or "展示" in text or "demo" in haystack:
            add_atom(
                "atom:interview-demo-quality-priority",
                canonical="项目当前优先保证面试演示可见、可解释、可评测。",
                summary="候选质量、真实链路和 eval gate 比堆功能更适合面试展示。",
                tags=["面试展示", "质量闸门", "项目目标"],
                aliases=["面试演示", "demo质量"],
                hints=["面试演示", "展示质量"],
                phrase_terms=["面试演示", "展示质量"],
                source_event_id=event_id,
            )
            add_edge("面试展示", "eval gate", "validated_by", event_id)
        if "memory-book" in haystack or ("preview" in haystack and "validate" in haystack and "apply" in haystack):
            add_atom(
                "atom:memory-book-preview-validate-apply-eval",
                canonical="RAG DB 整理流程应走 memory-book-preview、validate、apply、eval gate。",
                summary="真实历史先 dry-run 预览，再校验、应用、重建检索文档并用评测闸门把关。",
                tags=["Memory Book", "eval gate", "RAG DB"],
                aliases=["Memory Book闭环", "评测闸门"],
                hints=["整理闭环", "评测闸门"],
                phrase_terms=["整理闭环", "评测闸门"],
                source_event_id=event_id,
            )
            add_edge("Memory Book", "eval gate", "guarded_by", event_id)

    daily_books: list[dict[str, object]] = []
    if atoms:
        source_ids: list[int] = []
        for atom in atoms.values():
            for event_id in _positive_ints(atom.get("sourceEventIds")):
                if event_id not in source_ids:
                    source_ids.append(event_id)
        tags = _unique_strings(
            [tag for atom in atoms.values() for tag in _strings(atom.get("tags"))],
            limit=8,
        )
        daily_books.append(
            {
                "bookKey": _default_book_key(source_bundle),
                "title": "RAG 输入法真实历史整理摘要",
                "summary": "近期历史重点集中在 DeepSeek 离线整理、流式候选、真实 Squirrel/Rime 链路和面试展示质量。",
                "tags": tags,
                "surfaceHints": ["历史整理", "流式候选", "真实链路"],
                "queryExpansions": ["RAG 输入法", "DeepSeek 整理", "Memory Book"],
                "sourceEventIds": source_ids[:10],
                "memoryAtomIds": list(atoms.keys()),
                "project": project,
                "confidence": 0.62,
                "qualityScore": 0.62,
            }
        )
    return {
        "schemaVersion": MEMORY_BOOK_COMPILE_SCHEMA_VERSION,
        "dailyBooks": daily_books,
        "memoryAtoms": list(atoms.values())[:8],
        "tagEdges": list(edges.values())[:12],
        "phraseCandidates": list(phrases.values())[:12],
        "warnings": ["local_source_bundle_fallback_used"],
    }


def _fallback_event_is_safe(text: str) -> bool:
    if not text:
        return False
    return not any(marker in text for marker in ("[REDACTED_SECRET]", "[REDACTED_PATH]", "[REDACTED_EMAIL]"))


def _unique_strings(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = compact_whitespace(value)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _default_book_key(source_bundle: dict[str, object] | None) -> str:
    events = _source_event_records(source_bundle)
    for event in events:
        created_at_ms = event.get("createdAtMs")
        if isinstance(created_at_ms, int) and created_at_ms > 0:
            return datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return datetime.fromtimestamp(now_ms() / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _infer_source_event_ids(
    texts: list[str],
    *,
    source_bundle: dict[str, object] | None,
    limit: int = 3,
) -> list[int]:
    events = _source_event_records(source_bundle)
    if not events:
        return []
    tokens: set[str] = set()
    for text in texts:
        tokens.update(_evidence_tokens(text))
    if not tokens:
        return [int(event["eventId"]) for event in events[:limit]]
    scored: list[tuple[int, int, int]] = []
    for index, event in enumerate(events):
        event_tokens = _evidence_tokens(str(event.get("text") or ""))
        overlap = len(tokens.intersection(event_tokens))
        if overlap > 0:
            scored.append((-overlap, index, int(event["eventId"])))
    if scored:
        return [event_id for _, _, event_id in sorted(scored)[:limit]]
    return [int(event["eventId"]) for event in events[:limit]]


def _source_event_records(source_bundle: dict[str, object] | None) -> list[dict[str, object]]:
    if not isinstance(source_bundle, dict):
        return []
    raw_events = source_bundle.get("recentEvents")
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, object]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        event_ids = _positive_ints([item.get("eventId")])
        if not event_ids:
            continue
        tags = " ".join(_strings(item.get("tags")))
        text = compact_whitespace(
            " ".join(
                [
                    str(item.get("text") or ""),
                    str(item.get("recentContext") or ""),
                    tags,
                    str(item.get("app") or ""),
                    str(item.get("project") or ""),
                    str(item.get("source") or ""),
                ]
            )
        )
        events.append(
            {
                "eventId": event_ids[0],
                "createdAtMs": _optional_int(item.get("createdAtMs")),
                "text": text,
            }
        )
    return events


def _evidence_tokens(text: str) -> set[str]:
    value = compact_whitespace(text).lower()
    if not value:
        return set()
    tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9_+.-]{1,}|[0-9]+(?:\.[0-9]+)?", normalize_text(value))
        if len(token) >= 2
    }
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", value):
        for size in (2, 3):
            if len(segment) < size:
                continue
            tokens.update(segment[index : index + size] for index in range(0, len(segment) - size + 1))
    for stop in ("用户", "要求", "需要", "这个", "那个", "当前", "目前", "项目", "可以", "应该", "使用", "进行"):
        tokens.discard(stop)
    return tokens


def _optional_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _memory_book_summary(diffs: list[dict[str, object]]) -> str:
    return (
        f"books={sum(1 for item in diffs if item.get('op') == 'upsert_memory_book')} "
        f"atoms={sum(1 for item in diffs if item.get('op') == 'upsert_memory_atom')} "
        f"edges={sum(1 for item in diffs if item.get('op') == 'upsert_tag_edge')} "
        f"phrases={sum(1 for item in diffs if item.get('op') == 'add_phrase_candidate')}"
    )


def _sanitize_text(text: str, *, max_chars: int) -> tuple[str, dict[str, int]]:
    counts = {"secret": 0, "path": 0, "email": 0}
    value = compact_whitespace(text)
    value, counts["secret"] = _SECRET_RE.subn("[REDACTED_SECRET]", value)
    value, counts["path"] = _PATH_RE.subn("[REDACTED_PATH]", value)
    value, counts["email"] = _EMAIL_RE.subn("[REDACTED_EMAIL]", value)
    return truncate_text(value, max_chars), counts


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value)


def _json_list(raw: object) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return _strings(parsed)


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _strings(value: object) -> list[str]:
    return [compact_whitespace(str(item)) for item in value or [] if compact_whitespace(str(item))]


def _positive_ints(value: object) -> list[int]:
    result: list[int] = []
    for item in value or []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _bounded_float(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _row_dict(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _ensure_compile_state_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_compile_state (
            project TEXT PRIMARY KEY,
            last_compiled_event_id INTEGER NOT NULL DEFAULT 0,
            last_run_ms INTEGER NOT NULL DEFAULT 0,
            pending_event_count INTEGER NOT NULL DEFAULT 0,
            last_bundle_hash TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _advance_compile_state(conn: sqlite3.Connection, *, plan: dict[str, object]) -> None:
    metadata = dict(plan.get("metadata") or {})
    project = compact_whitespace(str(metadata.get("project") or ""))
    cursor = dict(metadata.get("sourceCursor") or {})
    to_event_id = max(0, int(cursor.get("toEventId") or 0))
    if not project or to_event_id <= 0:
        return
    _ensure_compile_state_table(conn)
    pending = int(
        conn.execute(
            "SELECT COUNT(*) FROM input_events WHERE id > ? AND (? = '' OR project = ? OR project = '')",
            (to_event_id, project, project),
        ).fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO memory_compile_state(project, last_compiled_event_id, last_run_ms, pending_event_count, last_bundle_hash)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project) DO UPDATE SET
            last_compiled_event_id = MAX(memory_compile_state.last_compiled_event_id, excluded.last_compiled_event_id),
            last_run_ms = excluded.last_run_ms,
            pending_event_count = excluded.pending_event_count,
            last_bundle_hash = excluded.last_bundle_hash
        """,
        (project, to_event_id, now_ms(), pending, compact_whitespace(str(metadata.get("bundleHash") or ""))),
    )


def _source_feedback(conn: sqlite3.Connection, *, event_ids: list[int]) -> list[dict[str, object]]:
    if not event_ids:
        return []
    rows = conn.execute(
        """
        SELECT action, candidate_text, candidate_source, created_at_ms, metadata_json
        FROM memory_feedback_events
        ORDER BY created_at_ms DESC
        LIMIT 80
        """
    ).fetchall()
    return [
        {
            "action": str(row["action"] or ""),
            "text": _sanitize_text(str(row["candidate_text"] or ""), max_chars=80)[0],
            "source": str(row["candidate_source"] or ""),
            "createdAtMs": int(row["created_at_ms"] or 0),
        }
        for row in rows
    ]


def _existing_book_summaries(conn: sqlite3.Connection, *, project: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT book_id, title, summary, tags_json, source_event_ids_json, metadata_json
        FROM memory_books
        WHERE status IN ('active', 'approved') AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC
        LIMIT 8
        """,
        (project, project),
    ).fetchall()
    return [
        {
            "bookId": str(row["book_id"] or ""),
            "title": _sanitize_text(str(row["title"] or ""), max_chars=80)[0],
            "summary": _sanitize_text(str(row["summary"] or ""), max_chars=180)[0],
            "tags": _json_list(row["tags_json"]),
            "sourceEventIds": _json_list(row["source_event_ids_json"]),
        }
        for row in rows
    ]


def _group_for_source_ids(source_ids: list[int], *, source_bundle: dict[str, object] | None) -> str:
    if not source_bundle:
        return ""
    wanted = set(source_ids)
    for event in _list_of_dicts(source_bundle.get("recentEvents")):
        try:
            event_id = int(event.get("eventId") or 0)
        except (TypeError, ValueError):
            continue
        group_id = compact_whitespace(str(event.get("contextGroupId") or ""))
        if event_id in wanted and group_id:
            return group_id
    return ""


def _validate_required_text(errors: list[dict[str, object]], index: int, op: str, payload: dict[str, object], field: str) -> None:
    if not compact_whitespace(str(payload.get(field) or "")):
        errors.append(_issue(index, op, field, "required"))


def _validate_source_ids(errors: list[dict[str, object]], index: int, op: str, value: object) -> None:
    if not _positive_ints(value):
        errors.append(_issue(index, op, "sourceEventIds", "missing_source_event_ids"))


def _validate_short_terms(
    errors: list[dict[str, object]],
    index: int,
    op: str,
    field: str,
    value: object,
    *,
    max_len: int,
) -> None:
    for item in _strings(value):
        if len(item) < 2 or len(item) > max_len:
            errors.append(_issue(index, op, field, "term_length_out_of_range", value=len(item), preview=truncate_text(item, 80)))


def _validate_secret_free(
    errors: list[dict[str, object]],
    index: int,
    op: str,
    payload: dict[str, object],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        values = _strings(payload.get(field)) if isinstance(payload.get(field), list) else [compact_whitespace(str(payload.get(field) or ""))]
        for value in values:
            if _SECRET_RE.search(value) or _PATH_RE.search(value) or _EMAIL_RE.search(value):
                errors.append(_issue(index, op, field, "sensitive_text_detected", preview=truncate_text(value, 80)))


def _looks_like_long_history_sentence(payload: dict[str, object]) -> bool:
    candidates = _strings(payload.get("surfaceHints")) + [compact_whitespace(str(payload.get("text") or ""))]
    return any(len(item) >= 24 and any(mark in item for mark in ("，", "。", ",", ".", " ")) for item in candidates)


def _issue(
    diff_index: int,
    op: str,
    field: str,
    code: str,
    *,
    value: object = None,
    preview: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {"diffIndex": diff_index, "op": op, "field": field, "code": code}
    if value is not None:
        payload["value"] = value
    if preview:
        payload["preview"] = preview
    return payload
