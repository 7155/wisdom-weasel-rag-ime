from __future__ import annotations

import json
import sqlite3
from typing import Any

from .text_utils import compact_whitespace, stable_text_hash, truncate_text


TIMELINE_CONTEXT_SCHEMA_VERSION = "rag-ime.timeline-context.v1"


def build_timeline_context_pack(
    core: object,
    *,
    project: str = "",
    app: str = "",
    current_context: str = "",
    selected_text: str = "",
    recent_limit: int = 8,
    recent_max_chars: int = 720,
    book_limit: int = 3,
) -> dict[str, object]:
    """Build a bounded notebook-style context pack from recent input and Memory Books."""
    normalized_project = compact_whitespace(project)
    normalized_app = compact_whitespace(app)
    recent_input = _recent_input_context(
        core,
        project=normalized_project,
        limit=recent_limit,
        max_chars=recent_max_chars,
    )
    books = _latest_memory_books(
        core,
        project=normalized_project,
        app=normalized_app,
        limit=book_limit,
    )
    evidence: list[dict[str, object]] = []
    if recent_input:
        evidence.append(
            {
                "sourceType": "recent_input_context",
                "sourceLane": "timeline_recent_input",
                "title": "最近输入上下文",
                "evidencePreview": truncate_text(recent_input, recent_max_chars),
                "surfaceHints": [],
                "tags": ["recent_input", "timeline"],
                "metadata": {"source": "recent_input_context"},
            }
        )
    for book in books:
        evidence.append(_book_evidence(book))
    return {
        "schemaVersion": TIMELINE_CONTEXT_SCHEMA_VERSION,
        "project": normalized_project,
        "app": normalized_app,
        "currentContextHash": stable_text_hash(compact_whitespace(current_context)) if current_context else "",
        "selectedTextHash": stable_text_hash(compact_whitespace(selected_text)) if selected_text else "",
        "recentInput": recent_input,
        "dailyBooks": books,
        "evidencePack": evidence,
    }


def timeline_evidence_pack_from_core(
    core: object,
    *,
    project: str = "",
    app: str = "",
    current_context: str = "",
    selected_text: str = "",
    max_items: int = 4,
) -> tuple[dict[str, object], ...]:
    pack = build_timeline_context_pack(
        core,
        project=project,
        app=app,
        current_context=current_context,
        selected_text=selected_text,
        book_limit=max(0, int(max_items) - 1),
    )
    evidence = pack.get("evidencePack")
    if not isinstance(evidence, list):
        return ()
    return tuple(item for item in evidence[: max(0, int(max_items))] if isinstance(item, dict))


def _recent_input_context(core: object, *, project: str, limit: int, max_chars: int) -> str:
    method = getattr(core, "recent_input_context", None)
    if not callable(method):
        return ""
    try:
        return truncate_text(
            compact_whitespace(str(method(project=project, limit=max(1, int(limit)), max_chars=max(1, int(max_chars))))),
            max(1, int(max_chars)),
        )
    except Exception:
        return ""


def _latest_memory_books(core: object, *, project: str, app: str, limit: int) -> list[dict[str, object]]:
    connect = getattr(core, "_connect", None)
    if not callable(connect) or limit <= 0:
        return []
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT book_id, book_type, book_key, title, summary, project, app,
                       tags_json, surface_hints_json, query_expansions_json,
                       source_event_ids_json, memory_atom_ids_json, status,
                       confidence, quality_score, updated_at_ms
                FROM memory_books
                WHERE status IN ('active', 'approved')
                  AND (? = '' OR project = ? OR project = '')
                  AND (? = '' OR app = ? OR app = '')
                ORDER BY updated_at_ms DESC
                LIMIT ?
                """,
                (project, project, app, app, max(1, min(8, int(limit)))),
            ).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return []
    books: list[dict[str, object]] = []
    for row in rows:
        title = compact_whitespace(str(row["title"] or ""))
        summary = compact_whitespace(str(row["summary"] or ""))
        if not title and not summary:
            continue
        books.append(
            {
                "bookId": str(row["book_id"] or ""),
                "bookType": str(row["book_type"] or ""),
                "bookKey": str(row["book_key"] or ""),
                "title": title,
                "summary": truncate_text(summary, 220),
                "project": str(row["project"] or ""),
                "app": str(row["app"] or ""),
                "tags": _json_list(row["tags_json"], limit=8),
                "surfaceHints": _json_list(row["surface_hints_json"], limit=8),
                "queryExpansions": _json_list(row["query_expansions_json"], limit=8),
                "sourceEventIds": _json_ints(row["source_event_ids_json"], limit=12),
                "memoryAtomIds": _json_list(row["memory_atom_ids_json"], limit=12),
                "confidence": float(row["confidence"] or 0.0),
                "qualityScore": float(row["quality_score"] or 0.0),
                "updatedAtMs": int(row["updated_at_ms"] or 0),
            }
        )
    return books


def _book_evidence(book: dict[str, object]) -> dict[str, object]:
    book_type = compact_whitespace(str(book.get("bookType") or ""))
    source_type = "daily_book" if book_type == "daily" else "memory_book"
    source_lane = "timeline_daily_book" if book_type == "daily" else "timeline_memory_book"
    hints = [str(item) for item in book.get("surfaceHints", []) if compact_whitespace(str(item))] if isinstance(book.get("surfaceHints"), list) else []
    tags = [str(item) for item in book.get("tags", []) if compact_whitespace(str(item))] if isinstance(book.get("tags"), list) else []
    return {
        "sourceType": source_type,
        "sourceLane": source_lane,
        "title": compact_whitespace(str(book.get("title") or "")),
        "summary": compact_whitespace(str(book.get("summary") or "")),
        "evidencePreview": compact_whitespace(str(book.get("summary") or "")),
        "surfaceHints": hints[:8],
        "tags": tags[:8],
        "bookId": str(book.get("bookId") or ""),
        "bookKey": str(book.get("bookKey") or ""),
        "sourceEventIds": book.get("sourceEventIds") if isinstance(book.get("sourceEventIds"), list) else [],
        "metadata": {"source": "memory_books", "bookType": book_type},
    }


def _json_list(raw: Any, *, limit: int) -> list[str]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "[]")
        except json.JSONDecodeError:
            parsed = []
    else:
        parsed = raw
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    for item in parsed:
        value = compact_whitespace(str(item))
        if value and value not in result:
            result.append(truncate_text(value, 48))
        if len(result) >= limit:
            break
    return result


def _json_ints(raw: Any, *, limit: int) -> list[int]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "[]")
        except json.JSONDecodeError:
            parsed = []
    else:
        parsed = raw
    if not isinstance(parsed, list):
        return []
    result: list[int] = []
    for item in parsed:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result
