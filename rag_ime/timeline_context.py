from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from .daily_planner import estimate_tokens, planning_context, planning_evidence_pack
from .input_event_assembly import recent_complete_input_context, resolve_temporal_window
from .text_utils import compact_whitespace, stable_text_hash, truncate_text


TIMELINE_CONTEXT_SCHEMA_VERSION = "rag-ime.timeline-context.v1"


def build_timeline_context_pack(
    core: object,
    *,
    project: str = "",
    app: str = "",
    current_context: str = "",
    selected_text: str = "",
    recent_limit: int = 20,
    recent_max_records: int = 80,
    context_token_budget: int = 4096,
    reserved_tokens: int = 1024,
    book_limit: int = 3,
) -> dict[str, object]:
    """Build a budgeted context pack from complete inputs, plans, and Memory Books."""
    normalized_project = compact_whitespace(project)
    normalized_app = compact_whitespace(app)
    query_text = compact_whitespace(" ".join(item for item in (selected_text, current_context) if item))
    preferences = _timeline_preferences(core)
    recent_limit = int(preferences.get("recentInputBaseline") or recent_limit)
    recent_max_records = int(preferences.get("recentInputMaximum") or recent_max_records)
    context_token_budget = int(preferences.get("tokenBudget") or context_token_budget)
    reserved_tokens = int(preferences.get("reservedOutputTokens") or reserved_tokens)
    temporal_query = query_text if bool(preferences.get("temporalRecall", True)) else ""
    books = _latest_memory_books(
        core,
        project=normalized_project,
        app=normalized_app,
        limit=book_limit,
        query_text=temporal_query,
    )
    planning_enabled = bool(preferences.get("planningEnabled", True))
    planning_injected = bool(preferences.get("planningInjected", True))
    planning = (
        _planning_context(core, project=normalized_project)
        if planning_enabled
        else {"openTasks": [], "longTermGoals": [], "counts": {"taskCount": 0, "goalCount": 0}}
    )
    current_input_tokens = estimate_tokens(query_text)
    planning_tokens = int(planning.get("estimatedTokens") or 0) if planning_enabled and planning_injected else 0
    memory_book_tokens = sum(
        estimate_tokens(
            " ".join(
                item
                for item in (
                    compact_whitespace(str(book.get("title") or "")),
                    compact_whitespace(str(book.get("summary") or "")),
                )
                if item
            )
        )
        for book in books
    )
    # The recent-input selector used to spend the whole context allowance on
    # its own. Reserve higher-priority current/planning/book content first so
    # the combined timeline pack stays near the configured soft budget.
    recent_context = _recent_complete_context(
        core,
        project=normalized_project,
        app=normalized_app,
        query_text=temporal_query,
        baseline_records=recent_limit,
        max_records=recent_max_records,
        token_budget=context_token_budget,
        reserved_tokens=reserved_tokens + current_input_tokens + planning_tokens + memory_book_tokens,
    )
    recent_input = compact_whitespace(str(recent_context.get("rendered") or ""))
    recent_records = recent_context.get("records") if isinstance(recent_context.get("records"), list) else []
    evidence: list[dict[str, object]] = []
    for record in recent_records:
        if isinstance(record, dict):
            evidence.append(_recent_record_evidence(record))
    if planning_enabled and planning_injected:
        evidence.extend(_planning_evidence(core, project=normalized_project))
    for book in books:
        evidence.append(_book_evidence(book))
    recent_observability = (
        dict(recent_context.get("observability"))
        if isinstance(recent_context.get("observability"), dict)
        else {}
    )
    planning_counts = planning.get("counts") if isinstance(planning.get("counts"), dict) else {}
    recent_input_tokens = int(recent_observability.get("estimatedTokens") or estimate_tokens(recent_input))
    evidence_tokens = sum(
        estimate_tokens(
            compact_whitespace(
                str(item.get("evidencePreview") or item.get("summary") or item.get("title") or "")
            )
        )
        for item in evidence
    )
    total_estimated_tokens = current_input_tokens + recent_input_tokens + planning_tokens + memory_book_tokens
    available_context_tokens = max(256, context_token_budget - reserved_tokens)
    context_observability = {
        "tokenBudget": context_token_budget,
        "reservedOutputTokens": reserved_tokens,
        "availableContextTokens": available_context_tokens,
        "currentInput": {"recordCount": 1 if query_text else 0, "estimatedTokens": current_input_tokens},
        "recentCompleteInputs": {
            "recordCount": len(recent_records),
            "estimatedTokens": recent_input_tokens,
            "baselineRecordCount": int(recent_observability.get("baselineRecordCount") or recent_limit),
            "maxRecordCount": int(recent_observability.get("maxRecordCount") or recent_max_records),
        },
        "planning": {
            "taskCount": int(planning_counts.get("taskCount") or 0) if planning_injected else 0,
            "goalCount": int(planning_counts.get("goalCount") or 0) if planning_injected else 0,
            "estimatedTokens": planning_tokens,
        },
        "memoryBooks": {"recordCount": len(books), "estimatedTokens": memory_book_tokens},
        "ragEvidence": {"recordCount": len(evidence), "estimatedTokens": evidence_tokens},
        "temporalWindow": recent_observability.get("temporalWindow"),
        "explicitTemporalQuery": bool(recent_observability.get("explicitTemporalQuery")),
        "totalEstimatedTokens": total_estimated_tokens,
        "withinSoftBudget": total_estimated_tokens <= available_context_tokens,
        "overflowTokens": max(0, total_estimated_tokens - available_context_tokens),
    }
    return {
        "schemaVersion": TIMELINE_CONTEXT_SCHEMA_VERSION,
        "project": normalized_project,
        "app": normalized_app,
        "currentContextHash": stable_text_hash(compact_whitespace(current_context)) if current_context else "",
        "selectedTextHash": stable_text_hash(compact_whitespace(selected_text)) if selected_text else "",
        "recentInput": recent_input,
        "recentRecords": recent_records,
        "recentContextObservability": recent_observability,
        "contextObservability": context_observability,
        "planning": planning,
        "planningInjected": planning_enabled and planning_injected,
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
    max_items: int = 32,
) -> tuple[dict[str, object], ...]:
    pack = build_timeline_context_pack(
        core,
        project=project,
        app=app,
        current_context=current_context,
        selected_text=selected_text,
        book_limit=min(8, max(0, int(max_items) // 4)),
    )
    evidence = pack.get("evidencePack")
    if not isinstance(evidence, list):
        return ()
    return tuple(item for item in evidence[: max(0, int(max_items))] if isinstance(item, dict))


def _recent_complete_context(
    core: object,
    *,
    project: str,
    app: str,
    query_text: str,
    baseline_records: int,
    max_records: int,
    token_budget: int,
    reserved_tokens: int,
) -> dict[str, object]:
    connect = getattr(core, "_connect", None)
    if callable(connect):
        try:
            with connect() as conn:
                return recent_complete_input_context(
                    conn,
                    project=project,
                    app=app,
                    query_text=query_text,
                    baseline_records=baseline_records,
                    max_records=max_records,
                    token_budget=token_budget,
                    reserved_tokens=reserved_tokens,
                )
        except (sqlite3.Error, AttributeError, TypeError, ValueError):
            pass
    method = getattr(core, "recent_input_context", None)
    if not callable(method):
        return {"records": [], "rendered": "", "observability": {}}
    try:
        rendered = compact_whitespace(
            str(method(project=project, limit=max(1, int(baseline_records)), max_chars=max(420, int(token_budget))))
        )
        return {
            "records": ([{"id": "legacy-recent-context", "text": rendered, "sourceEventIds": []}] if rendered else []),
            "rendered": rendered,
            "observability": {
                "selectedRecordCount": 1 if rendered else 0,
                "fallback": "core.recent_input_context",
            },
        }
    except Exception:
        return {"records": [], "rendered": "", "observability": {}}


def _latest_memory_books(
    core: object,
    *,
    project: str,
    app: str,
    limit: int,
    query_text: str = "",
) -> list[dict[str, object]]:
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
                       confidence, quality_score, updated_at_ms,
                       archived_at_ms, last_active_at_ms, archive_reason
                FROM memory_books
                WHERE status IN ('active', 'approved', 'archived')
                  AND (? = '' OR project = ? OR project = '')
                  AND (? = '' OR app = ? OR app = '')
                ORDER BY updated_at_ms DESC
                LIMIT ?
                """,
                (project, project, app, app, max(24, min(120, int(limit) * 12))),
            ).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return []
    temporal = resolve_temporal_window(query_text)
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
                "status": str(row["status"] or "active"),
                "archivedAtMs": int(row["archived_at_ms"] or 0),
                "lastActiveAtMs": int(row["last_active_at_ms"] or row["updated_at_ms"] or 0),
                "archiveReason": str(row["archive_reason"] or ""),
            }
        )
    if temporal is not None:
        matching = [item for item in books if _book_matches_temporal_window(item, temporal.start_ms, temporal.end_ms)]
        if matching:
            return matching[: max(1, int(limit))]
    return [item for item in books if item.get("status") in {"active", "approved"}][: max(1, int(limit))]


def _planning_context(core: object, *, project: str) -> dict[str, object]:
    connect = getattr(core, "_connect", None)
    if not callable(connect):
        return {"openTasks": [], "longTermGoals": [], "counts": {"taskCount": 0, "goalCount": 0}}
    try:
        with connect() as conn:
            return planning_context(conn, project=project)
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        return {"openTasks": [], "longTermGoals": [], "counts": {"taskCount": 0, "goalCount": 0}}


def _planning_evidence(core: object, *, project: str) -> list[dict[str, object]]:
    connect = getattr(core, "_connect", None)
    if not callable(connect):
        return []
    try:
        with connect() as conn:
            return list(planning_evidence_pack(conn, project=project, max_items=12))
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        return []


def timeline_context_preferences(core: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "recentInputBaseline": 20,
        "recentInputMaximum": 80,
        "tokenBudget": 4096,
        "reservedOutputTokens": 1024,
        "temporalRecall": True,
        "planningEnabled": True,
        "planningInjected": True,
    }
    connect = getattr(core, "_connect", None)
    if not callable(connect):
        return defaults
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM management_settings WHERE key IN ('context', 'planning')"
            ).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return defaults
    values: dict[str, dict[str, object]] = {}
    for row in rows:
        try:
            parsed = json.loads(str(row["value_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            values[str(row["key"])] = parsed
    context = values.get("context", {})
    planning = values.get("planning", {})
    return {
        "recentInputBaseline": _bounded_int(context.get("recentInputBaseline"), 20, 10, 80),
        "recentInputMaximum": _bounded_int(context.get("recentInputMaximum"), 80, 20, 200),
        "tokenBudget": _bounded_int(context.get("tokenBudget"), 4096, 2048, 32768),
        "reservedOutputTokens": _bounded_int(context.get("reservedOutputTokens"), 1024, 256, 8192),
        "temporalRecall": bool(context.get("temporalRecall", True)),
        "planningEnabled": bool(planning.get("enabled", True)),
        "planningInjected": bool(planning.get("injectIntoContext", True)),
    }


# Kept as a private alias for older internal callers while the public helper is
# used by the final model-prompt budgeter.
_timeline_preferences = timeline_context_preferences


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _recent_record_evidence(record: dict[str, object]) -> dict[str, object]:
    text = compact_whitespace(str(record.get("text") or ""))
    return {
        "sourceType": "recent_input_context",
        "sourceLane": "timeline_recent_input",
        "title": "最近完整输入",
        "evidencePreview": text,
        "surfaceHints": [],
        "tags": ["recent_input", "timeline"],
        "sourceEventIds": record.get("sourceEventIds") if isinstance(record.get("sourceEventIds"), list) else [],
        "metadata": {
            "source": "recent_complete_input",
            "recordId": record.get("id"),
            "createdAtMs": record.get("createdAtMs"),
            "contextOnly": True,
            "complete": record.get("complete"),
        },
    }


def _book_matches_temporal_window(book: dict[str, object], start_ms: int, end_ms: int) -> bool:
    key = compact_whitespace(str(book.get("bookKey") or ""))
    title = compact_whitespace(str(book.get("title") or ""))
    for match in re.finditer(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)", f"{key} {title}"):
        try:
            timestamp = int(datetime.strptime(match.group(1), "%Y-%m-%d").astimezone().timestamp() * 1000)
        except ValueError:
            continue
        if start_ms <= timestamp < end_ms:
            return True
    updated = int(book.get("lastActiveAtMs") or book.get("updatedAtMs") or 0)
    return start_ms <= updated < end_ms


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
        "metadata": {
            "source": "memory_books",
            "bookType": book_type,
            "status": book.get("status") or "active",
            "archived": book.get("status") == "archived",
            "archiveReason": book.get("archiveReason") or "",
        },
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
