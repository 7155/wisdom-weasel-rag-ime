from __future__ import annotations

import json
import re
import sqlite3
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
) -> dict[str, object]:
    cutoff_ms = now_ms() - max(1, int(since_days)) * 24 * 60 * 60 * 1000
    rows = conn.execute(
        """
        SELECT id, created_at_ms, source, committed_text, recent_context, app, project, tags_json
        FROM input_events
        WHERE created_at_ms >= ?
          AND (? = '' OR project = ? OR project = '')
        ORDER BY created_at_ms DESC
        LIMIT ?
        """,
        (cutoff_ms, project, project, max(1, int(limit))),
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
            }
        )
    return {
        "schemaVersion": "rag-ime.memory-book-source-bundle.v1",
        "project": project,
        "sinceDays": max(1, int(since_days)),
        "exportedAtMs": now_ms(),
        "redactionStats": redaction_stats,
        "recentEvents": events,
    }


def memory_book_plan_from_compile_output(
    compile_output: dict[str, object],
    *,
    project: str,
    provider: str,
    model: str,
) -> dict[str, object]:
    diffs: list[dict[str, object]] = []
    for item in _list_of_dicts(compile_output.get("dailyBooks")):
        book_key = compact_whitespace(str(item.get("bookKey") or ""))
        book_id = compact_whitespace(str(item.get("bookId") or "")) or f"book:daily:{book_key}"
        payload = {
            "bookId": book_id,
            "bookType": compact_whitespace(str(item.get("bookType") or "daily")) or "daily",
            "bookKey": book_key,
            "title": compact_whitespace(str(item.get("title") or "")),
            "summary": compact_whitespace(str(item.get("summary") or "")),
            "tags": _strings(item.get("tags")),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
            "memoryAtomIds": _strings(item.get("memoryAtomIds")),
            "project": compact_whitespace(str(item.get("project") or project)),
            "app": compact_whitespace(str(item.get("app") or "")),
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=_bounded_float(item.get("confidence"), default=0.5)),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
        }
        diffs.append({"op": "upsert_memory_book", "targetId": book_id, "payload": payload, "status": "pending"})
    for item in _list_of_dicts(compile_output.get("memoryAtoms")):
        atom_id = compact_whitespace(str(item.get("atomId") or item.get("id") or ""))
        canonical = compact_whitespace(str(item.get("canonicalText") or item.get("text") or ""))
        if not atom_id and canonical:
            atom_id = f"atom:{stable_text_hash(canonical)[:16]}"
        payload = {
            "atomId": atom_id,
            "kind": compact_whitespace(str(item.get("kind") or "project_fact")),
            "canonicalText": canonical,
            "summary": compact_whitespace(str(item.get("summary") or "")),
            "tags": _strings(item.get("tags")),
            "aliases": _strings(item.get("aliases")),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
            "sourceMemoryIds": _strings(item.get("sourceMemoryIds")),
            "directCandidateAllowed": bool(item.get("directCandidateAllowed", False)),
            "project": compact_whitespace(str(item.get("project") or project)),
            "app": compact_whitespace(str(item.get("app") or "")),
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=0.5),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
        }
        diffs.append({"op": "upsert_memory_atom", "targetId": atom_id, "payload": payload, "status": "pending"})
    for item in _list_of_dicts(compile_output.get("tagEdges")):
        src = compact_whitespace(str(item.get("src") or ""))
        dst = compact_whitespace(str(item.get("dst") or ""))
        target = f"tag-edge:{src}->{dst}:{compact_whitespace(str(item.get('edgeType') or 'related'))}"
        diffs.append(
            {
                "op": "upsert_tag_edge",
                "targetId": target,
                "payload": {
                    "src": src,
                    "dst": dst,
                    "edgeType": compact_whitespace(str(item.get("edgeType") or "related")) or "related",
                    "weight": _bounded_float(item.get("weight"), default=0.5),
                    "evidenceEventIds": _positive_ints(item.get("evidenceEventIds")),
                },
                "status": "pending",
            }
        )
    for item in _list_of_dicts(compile_output.get("phraseCandidates")):
        text = compact_whitespace(str(item.get("text") or ""))
        target = f"phrase:{normalize_text(text)}"
        diffs.append(
            {
                "op": "add_phrase_candidate",
                "targetId": target,
                "payload": {
                    "memoryId": target,
                    "text": text,
                    "tags": _strings(item.get("tags")),
                    "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
                    "weight": _bounded_float(item.get("weight"), default=0.6),
                    "project": compact_whitespace(str(item.get("project") or project)),
                },
                "status": "pending",
            }
        )
    run_id = f"memory_book_{now_ms()}"
    return {
        "schemaVersion": MEMORY_BOOK_RUN_SCHEMA_VERSION,
        "runId": run_id,
        "provider": provider,
        "model": model,
        "summary": _memory_book_summary(diffs),
        "metadata": {
            "compileSchemaVersion": str(compile_output.get("schemaVersion") or MEMORY_BOOK_COMPILE_SCHEMA_VERSION),
            "warnings": list(compile_output.get("warnings") or []),
            "elapsedMs": int(compile_output.get("elapsedMs") or 0),
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
            if len(text) < 2 or len(text) > 16:
                errors.append(_issue(index, op, "text", "phrase_text_length_out_of_range", value=len(text), preview=truncate_text(text, 80)))
            _validate_secret_free(errors, index, op, payload, ("text", "tags"))
        else:
            errors.append(_issue(index, op, "op", "unsupported_op"))
        if op and _looks_like_long_history_sentence(payload):
            warnings.append(_issue(index, op, "payload", "looks_like_long_history_sentence"))
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
