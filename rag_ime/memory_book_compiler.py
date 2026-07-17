from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import apply_database_migrations
from .deepseek_memory_organizer import MEMORY_BOOK_COMPILE_SCHEMA_VERSION
from .memory_ingest import normalize_text, upsert_memory_item
from .memory_projection import RETRIEVAL_DOCS_PROJECTION, enqueue_memory_projection
from .text_utils import compact_whitespace, now_ms, stable_text_hash, token_terms, truncate_text


MEMORY_BOOK_RUN_SCHEMA_VERSION = "rag-ime.memory-book-run.v1"
MEMORY_BOOK_PREVIEW_SCHEMA_VERSION = "rag-ime.memory-book-preview.v1"
MEMORY_BOOK_VALIDATE_SCHEMA_VERSION = "rag-ime.memory-book-validate.v1"
MEMORY_BOOK_APPLY_SCHEMA_VERSION = "rag-ime.memory-book-apply.v1"
MEMORY_BOOK_ROLLBACK_SCHEMA_VERSION = "rag-ime.memory-book-rollback.v1"

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URL_SECRET_QUERY_RE = re.compile(
    r"(?P<separator>[?&])"
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|token|api[_-]?key|apikey|secret|password|passwd|credential|auth)"
    r"=[^&#\s]*",
    re.IGNORECASE,
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:password|passwd|token|api[_ -]?key|secret|credential|authorization)\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;，；]+)",
    re.IGNORECASE,
)
_SECRET_RE = re.compile(
    r"(?<!REDACTED_)(password|token|api[_ -]?key|bearer|sk-[A-Za-z0-9_-]{8,}|secret|验证码|身份证|手机号)",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDENTITY_RE = re.compile(r"(?<!\d)[1-9]\d{16}[0-9Xx](?![0-9Xx])")
_PAYMENT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){11,18}\d(?!\d)")
_IPV4_CANDIDATE_RE = re.compile(r"(?<![0-9A-Za-z_.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9A-Za-z_.])")
_IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?=[0-9A-Fa-f:]*:[0-9A-Fa-f:]*:)(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)
_RIME_PINYIN_RE = re.compile(r"^[a-zv]+(?: [a-zv]+)*$")
_PATH_RE = re.compile(
    r"(?:(?:/(?:Users|Volumes|home)/|~/)[^\s\"']+|(?:[A-Za-z]:\\(?:Users\\)?|\\\\[^\\\s]+\\[^\\\s]+\\)[^\s\"']+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RIME_FRAGMENT_SOURCE = "squirrel_rime_commit_burst"
_MODEL_GENERATED_EVENT_SOURCES = {
    "api_core_optimizer",
    "api_lexicon_optimizer",
    "squirrel_rime_sidecar",
    "vcp_memory_generator",
}
_NON_MEMORY_EVENT_SOURCES = {
    "ime_demo_fixture",
}
_RUNTIME_PROBE_MARKERS = (
    "ceshiwendang",
    "press a visible candidate",
    "wait for llm/model",
    "wait for the next prediction",
)


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
    raw_events: list[dict[str, object]] = []
    redaction_stats = _empty_redaction_counts()
    for row in rows:
        text, text_counts = _sanitize_text(str(row["committed_text"] or ""), max_chars=220)
        recent, recent_counts = _sanitize_text(str(row["recent_context"] or ""), max_chars=220)
        app, app_counts = _sanitize_text(str(row["app"] or ""), max_chars=120)
        event_project, project_counts = _sanitize_text(str(row["project"] or ""), max_chars=120)
        tags: list[str] = []
        tag_counts = _empty_redaction_counts()
        for tag in _json_list(row["tags_json"]):
            sanitized_tag, counts = _sanitize_text(tag, max_chars=48)
            _merge_counts(tag_counts, counts)
            if sanitized_tag:
                tags.append(sanitized_tag)
        _merge_counts(redaction_stats, text_counts)
        _merge_counts(redaction_stats, recent_counts)
        _merge_counts(redaction_stats, app_counts)
        _merge_counts(redaction_stats, project_counts)
        _merge_counts(redaction_stats, tag_counts)
        raw_events.append(
            {
                "eventId": int(row["id"]),
                "sourceEventIds": [int(row["id"])],
                "createdAtMs": int(row["created_at_ms"] or 0),
                "source": str(row["source"] or ""),
                "text": text,
                "recentContext": recent,
                "app": app,
                "project": event_project,
                # Source tags are transport metadata, not semantic labels. The
                # organizer may use them as weak hints but must never copy them
                # into the long-term tag graph without semantic evidence.
                "sourceMetadataTags": tags,
                "contextGroupId": str(row["context_group_id"] or ""),
                "contextGroupLevel": str(row["context_group_level"] or "app"),
            }
        )
    events, reconstruction = _reconstruct_memory_source_events(raw_events)
    raw_event_ids = [int(item["eventId"]) for item in raw_events]
    feedback, feedback_redactions = _source_feedback(
        conn,
        event_ids=raw_event_ids,
        project=project,
    )
    rime_rank_feedback, rime_feedback_redactions = _source_rime_rank_feedback(
        conn,
        project=project,
        cutoff_ms=cutoff_ms,
    )
    _merge_counts(redaction_stats, feedback_redactions)
    _merge_counts(redaction_stats, rime_feedback_redactions)
    existing_books = _existing_book_summaries(conn, project=project)
    existing_atoms = _existing_memory_atom_summaries(conn, project=project)
    existing_groups = _existing_semantic_groups(conn, project=project)
    existing_tags = _existing_semantic_tags(conn)
    existing_tag_edges = _existing_semantic_tag_edges(conn)
    legal_groups = sorted({str(item.get("contextGroupId") or "") for item in events if item.get("contextGroupId")})
    max_event_id = max(raw_event_ids, default=cursor)
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
        "rawEventCount": len(raw_events),
        "reconstruction": reconstruction,
        "feedback": feedback,
        "rimeRankFeedback": rime_rank_feedback,
        "existingMemoryBooks": existing_books,
        "existingMemoryAtoms": existing_atoms,
        "existingSemanticGroups": existing_groups,
        "existingSemanticTags": existing_tags,
        "existingTagEdges": existing_tag_edges,
        "legalContextGroupIds": legal_groups,
        "cursor": {
            "fromEventId": cursor,
            "toEventId": max_event_id,
            "pendingEventCount": pending_count,
        },
    }
    hash_payload = dict(payload)
    hash_payload.pop("exportedAtMs", None)
    payload["bundleHash"] = stable_text_hash(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True)
    )
    return payload


def _reconstruct_memory_source_events(
    raw_events: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Turn Rime's per-commit ledger into coherent model-facing utterances.

    The source rows remain immutable. This projection only removes generated or
    demo rows and collapses cumulative Rime context snapshots before DSV4 sees
    them, so the model receives sentences instead of two-character commits.
    """

    result: list[dict[str, object]] = []
    fragment_run: list[dict[str, object]] = []
    excluded_counts: dict[str, int] = {}

    def flush_fragments() -> None:
        if not fragment_run:
            return
        result.append(_collapse_rime_fragment_run(fragment_run))
        fragment_run.clear()

    for event in raw_events:
        source = compact_whitespace(str(event.get("source") or ""))
        if source in _MODEL_GENERATED_EVENT_SOURCES or source in _NON_MEMORY_EVENT_SOURCES:
            excluded_counts[source] = excluded_counts.get(source, 0) + 1
            continue
        if source == _RIME_FRAGMENT_SOURCE:
            if fragment_run and not _rime_fragments_belong_together(fragment_run[-1], event):
                flush_fragments()
            fragment_run.append(event)
            continue
        flush_fragments()
        result.append(dict(event))
    flush_fragments()

    filtered, filter_stats = _filter_reconstructed_memory_events(result)
    return filtered, {
        "schemaVersion": "rag-ime.memory-source-reconstruction.v1",
        "rawEventCount": len(raw_events),
        "modelEventCount": len(filtered),
        "collapsedEventCount": max(0, len(raw_events) - sum(excluded_counts.values()) - len(result)),
        "excludedGeneratedEventCount": sum(
            count for source, count in excluded_counts.items() if source in _MODEL_GENERATED_EVENT_SOURCES
        ),
        "excludedNonMemoryEventCount": sum(
            count for source, count in excluded_counts.items() if source in _NON_MEMORY_EVENT_SOURCES
        ),
        "excludedSources": excluded_counts,
        **filter_stats,
    }


def _rime_fragments_belong_together(previous: dict[str, object], current: dict[str, object]) -> bool:
    if compact_whitespace(str(previous.get("app") or "")) != compact_whitespace(str(current.get("app") or "")):
        return False
    if compact_whitespace(str(previous.get("contextGroupId") or "")) != compact_whitespace(
        str(current.get("contextGroupId") or "")
    ):
        return False
    previous_ms = _optional_int(previous.get("createdAtMs"))
    current_ms = _optional_int(current.get("createdAtMs"))
    gap_ms = max(0, current_ms - previous_ms)
    if gap_ms > 5 * 60 * 1000:
        return False
    previous_context = compact_whitespace(str(previous.get("recentContext") or ""))
    current_context = compact_whitespace(str(current.get("recentContext") or ""))
    if not previous_context or not current_context:
        return gap_ms <= 8_000
    if previous_context in current_context or current_context in previous_context:
        return True
    overlap_limit = min(len(previous_context), len(current_context), 80)
    for size in range(overlap_limit, 7, -1):
        if previous_context[-size:] == current_context[:size]:
            return True
    return False


def _collapse_rime_fragment_run(events: list[dict[str, object]]) -> dict[str, object]:
    source_event_ids = [
        event_id
        for event in events
        for event_id in _positive_ints(event.get("sourceEventIds") or [event.get("eventId")])
    ]
    source_event_ids = list(dict.fromkeys(source_event_ids))
    committed = compact_whitespace("".join(str(item.get("text") or "") for item in events))
    contexts = [compact_whitespace(str(item.get("recentContext") or "")) for item in events]
    contexts = [item for item in contexts if item]
    reconstructed = max([committed, *contexts], key=len, default=committed)
    last = dict(events[-1])
    tags = _unique_strings(
        [tag for item in events for tag in _strings(item.get("sourceMetadataTags"))],
        limit=24,
    )
    last.update(
        {
            "eventId": source_event_ids[-1] if source_event_ids else _optional_int(last.get("eventId")),
            "sourceEventIds": source_event_ids,
            "source": "reconstructed_user_input",
            "text": reconstructed,
            "recentContext": "",
            "sourceMetadataTags": tags,
            "reconstruction": {
                "method": "rime-cumulative-context",
                "rawEventCount": len(events),
            },
        }
    )
    return last


def _filter_reconstructed_memory_events(
    events: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    filtered: list[dict[str, object]] = []
    dropped_doctor = 0
    dropped_probe = 0
    dropped_fragment = 0
    for event in events:
        text = compact_whitespace(str(event.get("text") or ""))
        group_id = compact_whitespace(str(event.get("contextGroupId") or "")).lower()
        if "doctor-" in group_id or group_id.startswith("doctor:"):
            dropped_doctor += 1
            continue
        lowered = text.lower()
        if sum(marker in lowered for marker in _RUNTIME_PROBE_MARKERS) >= 2:
            dropped_probe += 1
            continue
        if len(text) < 4 or not _evidence_tokens(text):
            dropped_fragment += 1
            continue
        filtered.append(dict(event))

    merged: list[dict[str, object]] = []
    duplicate_count = 0
    for event in filtered:
        normalized = normalize_text(str(event.get("text") or ""))
        app = compact_whitespace(str(event.get("app") or ""))
        group_id = compact_whitespace(str(event.get("contextGroupId") or ""))
        match_index = next(
            (
                index
                for index, previous in enumerate(merged)
                if app == compact_whitespace(str(previous.get("app") or ""))
                and group_id == compact_whitespace(str(previous.get("contextGroupId") or ""))
                and normalize_text(str(previous.get("text") or "")) == normalized
            ),
            None,
        )
        if match_index is None:
            merged.append(event)
            continue
        previous = dict(merged[match_index])
        ids = _positive_ints(previous.get("sourceEventIds"))
        ids.extend(item for item in _positive_ints(event.get("sourceEventIds")) if item not in ids)
        previous["sourceEventIds"] = ids
        previous["eventId"] = ids[-1] if ids else previous.get("eventId")
        reconstruction = dict(previous.get("reconstruction") or {})
        reconstruction["repeatCount"] = int(reconstruction.get("repeatCount") or 1) + 1
        previous["reconstruction"] = reconstruction
        merged[match_index] = previous
        duplicate_count += 1

    return merged, {
        "droppedDoctorEventCount": dropped_doctor,
        "droppedRuntimeProbeCount": dropped_probe,
        "droppedLowSignalEventCount": dropped_fragment,
        "mergedDuplicateEventCount": duplicate_count,
    }


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
) -> dict[str, object]:
    diffs: list[dict[str, object]] = []
    warnings = list(compile_output.get("warnings") or [])
    tag_merges = _planned_tag_merges(compile_output, source_bundle=source_bundle)
    tag_name_map = {
        normalize_text(str(item["source"])): str(item["target"])
        for item in tag_merges
        if normalize_text(str(item.get("source") or ""))
    }
    existing_group_ids = {
        compact_whitespace(str(item.get("groupId") or "")).lower()
        for item in _list_of_dicts((source_bundle or {}).get("existingSemanticGroups"))
        if compact_whitespace(str(item.get("groupId") or ""))
    }
    accepted_group_ids: set[str] = set()
    group_source_ids: dict[str, list[int]] = {}
    new_group_count = 0
    for item in _list_of_dicts(compile_output.get("semanticGroups")):
        title = compact_whitespace(str(item.get("title") or item.get("name") or ""))
        description = compact_whitespace(str(item.get("description") or item.get("summary") or ""))
        if not title or not description:
            continue
        group_id = _semantic_group_id(item.get("groupId"), title=title)
        if group_id in accepted_group_ids:
            warnings.append(f"duplicate_semantic_group_ignored:{group_id}")
            continue
        if len(accepted_group_ids) >= 8:
            warnings.append("semantic_group_total_limit_applied")
            continue
        if group_id not in existing_group_ids:
            if new_group_count >= 3:
                warnings.append("semantic_group_new_limit_applied")
                continue
            new_group_count += 1
        accepted_group_ids.add(group_id)
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [title, description, *_strings(item.get("aliases")), *_strings(item.get("tags"))],
            source_bundle=source_bundle,
        )
        group_source_ids[group_id] = source_ids
        diffs.append(
            {
                "op": "upsert_semantic_group",
                "targetId": group_id,
                "payload": {
                    "groupId": group_id,
                    "title": title,
                    "description": description,
                    "project": compact_whitespace(str(item.get("project") or project)),
                    "aliases": _strings(item.get("aliases")),
                    "tags": _canonical_tag_names(_strings(item.get("tags")), tag_name_map),
                    "sourceEventIds": source_ids,
                    "confidence": _bounded_float(item.get("confidence"), default=0.7),
                    "qualityScore": _bounded_float(item.get("qualityScore"), default=0.7),
                    "status": compact_whitespace(str(item.get("status") or "active")) or "active",
                },
                "status": "pending",
            }
        )
    for item in _list_of_dicts(compile_output.get("semanticTags")):
        name = compact_whitespace(str(item.get("name") or item.get("tag") or ""))
        description = compact_whitespace(str(item.get("description") or ""))
        if not name or not description:
            continue
        canonical_name = _canonical_tag_name(name, tag_name_map)
        if normalize_text(canonical_name) != normalize_text(name):
            warnings.append(f"semantic_tag_merged_into_existing:{name}->{canonical_name}")
            continue
        name = canonical_name
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [name, description, *_strings(item.get("aliases"))],
            source_bundle=source_bundle,
        )
        target = f"semantic-tag:{stable_text_hash(normalize_text(name)).removeprefix('sha256:')[:20]}"
        diffs.append(
            {
                "op": "upsert_semantic_tag",
                "targetId": target,
                "payload": {
                    "name": name,
                    "description": description,
                    "type": compact_whitespace(str(item.get("type") or "concept")) or "concept",
                    "aliases": _canonical_tag_aliases(name, _strings(item.get("aliases")), tag_name_map),
                    "semanticGroupIds": _resolved_semantic_group_ids(
                        item,
                        source_ids=source_ids,
                        group_source_ids=group_source_ids,
                    ),
                    "sourceEventIds": source_ids,
                    "confidence": _bounded_float(item.get("confidence"), default=0.7),
                    "qualityScore": _bounded_float(item.get("qualityScore"), default=0.7),
                    "status": compact_whitespace(str(item.get("status") or "active")) or "active",
                },
                "status": "pending",
            }
        )
    book_items = [
        *(("daily", item) for item in _list_of_dicts(compile_output.get("dailyBooks"))),
        *(("topic", item) for item in _list_of_dicts(compile_output.get("topicBooks"))),
    ]
    for default_book_type, item in book_items:
        title = compact_whitespace(str(item.get("title") or ""))
        summary = compact_whitespace(str(item.get("summary") or ""))
        if not title and not summary:
            continue
        existing_book = (
            _match_existing_topic_book(item, source_bundle=source_bundle)
            if default_book_type == "topic"
            else None
        )
        if default_book_type == "topic":
            default_book_key = f"topic-{stable_text_hash(title or summary).removeprefix('sha256:')[:16]}"
        else:
            default_book_key = _default_book_key(source_bundle)
        # A topic organizer is allowed to invent a fresh id/key, but a strong
        # match against an existing topic must win. Otherwise every maintenance
        # run would create another near-duplicate book even though reuse was
        # detected above.
        book_key = (
            compact_whitespace(str((existing_book or {}).get("bookKey") or ""))
            or compact_whitespace(str(item.get("bookKey") or ""))
            or default_book_key
        )
        book_type = compact_whitespace(str(item.get("bookType") or default_book_type)) or default_book_type
        book_id = (
            compact_whitespace(str((existing_book or {}).get("bookId") or ""))
            or compact_whitespace(str(item.get("bookId") or ""))
            or f"book:{book_type}:{book_key}"
        )
        inferred_source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [book_key, title, summary, *_strings(item.get("tags")), *_strings(item.get("surfaceHints"))],
            source_bundle=source_bundle,
        )
        source_ids = _positive_ints(
            [*_positive_ints((existing_book or {}).get("sourceEventIds")), *inferred_source_ids]
        )
        prior_tags = _strings((existing_book or {}).get("tags"))
        prior_atom_ids = _strings((existing_book or {}).get("memoryAtomIds"))
        payload = {
            "bookId": book_id,
            "bookType": book_type,
            "bookKey": book_key,
            "title": title,
            "summary": summary,
            "tags": _canonical_tag_names([*prior_tags, *_strings(item.get("tags"))], tag_name_map),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": source_ids,
            "memoryAtomIds": _unique_strings([*prior_atom_ids, *_strings(item.get("memoryAtomIds"))], limit=256),
            "semanticGroupIds": _resolved_semantic_group_ids(
                item,
                source_ids=source_ids,
                group_source_ids=group_source_ids,
            ),
            "project": compact_whitespace(str(item.get("project") or project)),
            "app": compact_whitespace(str(item.get("app") or "")),
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=_bounded_float(item.get("confidence"), default=0.5)),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
            "contextGroupId": _group_for_source_ids(source_ids, source_bundle=source_bundle),
            "reusedExistingBookId": compact_whitespace(str((existing_book or {}).get("bookId") or "")),
            "previousStatus": compact_whitespace(str((existing_book or {}).get("status") or "")),
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
        atom_kind = compact_whitespace(str(item.get("kind") or "project_fact"))
        atom_project = compact_whitespace(str(item.get("project") or project))
        atom_app = compact_whitespace(str(item.get("app") or ""))
        claim_key = _normalized_claim_key(
            item.get("claimKey") or item.get("claim") or atom_id
        )
        if not claim_key:
            # Older organizer/eval payloads predate claim lineage. Keep them
            # isolated under a deterministic atom-scoped claim rather than
            # rejecting the whole governed plan or guessing that two
            # differently worded facts are the same claim.
            claim_key = (
                "atom:"
                + stable_text_hash(canonical).removeprefix("sha256:")[:24]
            )
        lineage_id = compact_whitespace(str(item.get("lineageId") or ""))[:200]
        if claim_key and not lineage_id:
            lineage_id = (
                "lineage:"
                + stable_text_hash(
                    f"{atom_kind}\n{atom_project}\n{atom_app}\n{claim_key}"
                ).removeprefix("sha256:")[:24]
            )
        payload = {
            "atomId": atom_id,
            "kind": atom_kind,
            "canonicalText": canonical,
            "summary": compact_whitespace(str(item.get("summary") or "")),
            "tags": _canonical_tag_names(_strings(item.get("tags")), tag_name_map),
            "aliases": _strings(item.get("aliases")),
            "surfaceHints": _strings(item.get("surfaceHints")),
            "queryExpansions": _strings(item.get("queryExpansions")),
            "sourceEventIds": source_ids,
            "sourceMemoryIds": _strings(item.get("sourceMemoryIds")),
            "semanticGroupIds": _resolved_semantic_group_ids(
                item,
                source_ids=source_ids,
                group_source_ids=group_source_ids,
            ),
            "directCandidateAllowed": bool(item.get("directCandidateAllowed", False)),
            "project": atom_project,
            "app": atom_app,
            "claimKey": claim_key,
            "lineageId": lineage_id,
            "claimState": compact_whitespace(
                str(item.get("claimState") or "current")
            ).lower(),
            "validFromMs": (
                _optional_int(item.get("validFromMs"))
                or _latest_source_event_ms(source_ids, source_bundle=source_bundle)
            ),
            "validToMs": _optional_int(item.get("validToMs")) or None,
            "supersedesId": compact_whitespace(
                str(item.get("supersedesId") or "")
            )[:240],
            "confidence": _bounded_float(item.get("confidence"), default=0.5),
            "qualityScore": _bounded_float(item.get("qualityScore"), default=0.5),
            "status": compact_whitespace(str(item.get("status") or "active")) or "active",
            "contextGroupId": _group_for_source_ids(source_ids, source_bundle=source_bundle),
        }
        diffs.append({"op": "upsert_memory_atom", "targetId": atom_id, "payload": payload, "status": "pending"})
    for item in _list_of_dicts(compile_output.get("tagEdges")):
        src = _canonical_tag_name(
            compact_whitespace(str(item.get("src") or item.get("sourceTagName") or item.get("source") or "")),
            tag_name_map,
        )
        dst = _canonical_tag_name(
            compact_whitespace(str(item.get("dst") or item.get("targetTagName") or item.get("target") or "")),
            tag_name_map,
        )
        if not src or not dst:
            continue
        if normalize_text(src) == normalize_text(dst):
            warnings.append(f"self_tag_edge_ignored:{src}")
            continue
        edge_type = compact_whitespace(str(item.get("edgeType") or item.get("relationType") or "related")) or "related"
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
                    "weight": _bounded_float(
                        item.get("weight"),
                        default=_bounded_float(item.get("confidence"), default=0.5),
                    ),
                    "evidenceEventIds": evidence_ids,
                },
                "status": "pending",
            }
        )
    for item in _list_of_dicts(compile_output.get("phraseCandidates")):
        text = compact_whitespace(str(item.get("text") or ""))
        if len(text) < 2 or len(text) > 18:
            continue
        pinyin = _normalized_rime_pinyin(item.get("pinyin"))
        review_source = "dsv4" if compact_whitespace(provider).lower() in {"deepseek", "deepseek-v4", "dsv4"} else "memory"
        target = f"phrase:{normalize_text(text)}"
        source_ids = _positive_ints(item.get("sourceEventIds")) or _infer_source_event_ids(
            [text, *_canonical_tag_names(_strings(item.get("tags")), tag_name_map)],
            source_bundle=source_bundle,
        )
        diffs.append(
            {
                "op": "add_phrase_candidate",
                "targetId": target,
                "payload": {
                    "memoryId": target,
                    "text": text,
                    "pinyin": pinyin,
                    "reviewSource": review_source if pinyin else "memory",
                    "reviewReason": compact_whitespace(str(item.get("reason") or "")),
                    "tags": _strings(item.get("tags")),
                    "semanticGroupIds": _resolved_semantic_group_ids(
                        item,
                        source_ids=source_ids,
                        group_source_ids=group_source_ids,
                    ),
                    "sourceEventIds": source_ids,
                    "weight": _bounded_float(item.get("weight"), default=0.6),
                    "project": compact_whitespace(str(item.get("project") or project)),
                    "contextGroupId": _group_for_source_ids(source_ids, source_bundle=source_bundle),
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
                    "reason": compact_whitespace(str(item.get("reason") or "newer_explicit_information")),
                },
                "status": "pending",
            }
        )
    for item in tag_merges:
        source = compact_whitespace(str(item.get("source") or ""))
        target = compact_whitespace(str(item.get("target") or ""))
        if not source or not target or normalize_text(source) == normalize_text(target):
            continue
        if not bool(item.get("requiresApply", True)):
            warnings.append(f"virtual_tag_merge_canonicalized:{source}->{target}")
            continue
        evidence_ids = _positive_ints(item.get("evidenceEventIds")) or _infer_source_event_ids(
            [source, target, compact_whitespace(str(item.get("reason") or ""))],
            source_bundle=source_bundle,
        )
        diffs.append(
            {
                "op": "merge_semantic_tag",
                "targetId": f"tag-merge:{source}->{target}",
                "payload": {
                    "source": source,
                    "target": target,
                    "reason": compact_whitespace(str(item.get("reason") or "同义标签规范化")),
                    "evidenceEventIds": evidence_ids,
                    "confidence": _bounded_float(item.get("confidence"), default=0.8),
                },
                "status": "pending",
            }
        )
    proposed_tag_names = {
        normalize_text(str(diff.get("payload", {}).get("name") or ""))
        for diff in diffs
        if diff.get("op") == "upsert_semantic_tag" and isinstance(diff.get("payload"), dict)
    }
    connected_tag_names = {
        normalize_text(str(diff.get("payload", {}).get(field) or ""))
        for diff in diffs
        if diff.get("op") == "upsert_tag_edge" and isinstance(diff.get("payload"), dict)
        for field in ("src", "dst")
    }
    isolated_proposed_tags = sorted(name for name in proposed_tag_names if name and name not in connected_tag_names)
    if len(proposed_tag_names) > 1 and isolated_proposed_tags:
        warnings.append(f"isolated_semantic_tags_in_draft:{len(isolated_proposed_tags)}")
    run_id = f"memory_book_{now_ms()}"
    if source_bundle and not any(diff.get("op") == "upsert_memory_book" for diff in diffs):
        daily_book = _synthesize_daily_book_diff_from_diffs(diffs, project=project, source_bundle=source_bundle)
        if daily_book:
            diffs.insert(0, daily_book)
            warnings.append("daily_book_synthesized_from_atoms")
    if not diffs and source_bundle:
        # Never turn raw history into semantic memory when the organizer did
        # not produce a governed result. The cursor stays pending so a later
        # DSV4 run can retry instead of indexing uncleaned ASR/user text.
        warnings.append("organizer_returned_no_governed_memory")
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
            "modelDiagnostics": dict(compile_output.get("modelDiagnostics") or {}),
            "modelBundleStats": dict(compile_output.get("modelBundleStats") or {}),
            "instruction": _sanitize_text(str(compile_output.get("instruction") or ""), max_chars=600)[0],
            "tagGraphDiagnostics": {
                "existingTags": len(_list_of_dicts((source_bundle or {}).get("existingSemanticTags"))),
                "existingEdges": len(_list_of_dicts((source_bundle or {}).get("existingTagEdges"))),
                "proposedTags": len(proposed_tag_names),
                "proposedEdges": sum(1 for diff in diffs if diff.get("op") == "upsert_tag_edge"),
                "proposedMerges": sum(1 for diff in diffs if diff.get("op") == "merge_semantic_tag"),
                "isolatedProposedTags": isolated_proposed_tags,
            },
            "project": project,
            "bundleHash": str((source_bundle or {}).get("bundleHash") or ""),
            "sourceCursor": dict((source_bundle or {}).get("cursor") or {}),
            "legalContextGroupIds": list((source_bundle or {}).get("legalContextGroupIds") or []),
            "legalSourceEventIds": _legal_source_event_ids(source_bundle),
            "existingSemanticGroupIds": [
                str(item.get("groupId") or "")
                for item in _list_of_dicts((source_bundle or {}).get("existingSemanticGroups"))
                if compact_whitespace(str(item.get("groupId") or ""))
            ],
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
        "semanticGroups": 0,
        "semanticTags": 0,
        "tagMerges": 0,
        "memoryBooks": 0,
        "memoryAtoms": 0,
        "tagEdges": 0,
        "phraseCandidates": 0,
        "negativePhrases": 0,
        "supersedes": 0,
    }
    diffs = _list_of_dicts(plan.get("diffs"))
    metadata = dict(plan.get("metadata") or {})
    legal_source_event_ids = set(_positive_ints(metadata.get("legalSourceEventIds")))
    legal_groups = {
        compact_whitespace(str(item))
        for item in metadata.get("legalContextGroupIds", [])
        if compact_whitespace(str(item))
    }
    planned_semantic_groups = {
        compact_whitespace(str(item.get("payload", {}).get("groupId") or ""))
        for item in diffs
        if item.get("op") == "upsert_semantic_group" and isinstance(item.get("payload"), dict)
    }
    existing_semantic_groups = {
        compact_whitespace(str(item))
        for item in metadata.get("existingSemanticGroupIds", [])
        if compact_whitespace(str(item))
    }
    if compact_whitespace(str(plan.get("schemaVersion") or "")) != MEMORY_BOOK_RUN_SCHEMA_VERSION:
        errors.append(_issue(0, "", "schemaVersion", "unsupported_schema_version"))
    source_cursor = dict(metadata.get("sourceCursor") or {})
    if not diffs and int(source_cursor.get("pendingEventCount") or 0) > 0:
        errors.append(_issue(0, "", "diffs", "organizer_returned_no_governed_memory"))
    for index, diff in enumerate(diffs, start=1):
        op = compact_whitespace(str(diff.get("op") or ""))
        payload = diff.get("payload") if isinstance(diff.get("payload"), dict) else {}
        if op == "upsert_semantic_group":
            counts["semanticGroups"] += 1
            _validate_required_text(errors, index, op, payload, "groupId")
            _validate_required_text(errors, index, op, payload, "title")
            _validate_required_text(errors, index, op, payload, "description")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            _validate_secret_free(errors, index, op, payload, ("title", "description", "aliases", "tags"))
        elif op == "upsert_semantic_tag":
            counts["semanticTags"] += 1
            _validate_required_text(errors, index, op, payload, "name")
            _validate_required_text(errors, index, op, payload, "description")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            _validate_secret_free(errors, index, op, payload, ("name", "description", "aliases"))
        elif op == "upsert_memory_book":
            counts["memoryBooks"] += 1
            _validate_required_text(errors, index, op, payload, "bookId")
            _validate_required_text(errors, index, op, payload, "bookKey")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            _validate_short_terms(errors, index, op, "surfaceHints", payload.get("surfaceHints"), max_len=16)
            _validate_secret_free(errors, index, op, payload, ("title", "summary", "tags", "surfaceHints", "queryExpansions"))
        elif op == "upsert_memory_atom":
            counts["memoryAtoms"] += 1
            _validate_required_text(errors, index, op, payload, "atomId")
            _validate_required_text(errors, index, op, payload, "canonicalText")
            _validate_required_text(errors, index, op, payload, "claimKey")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            _validate_short_terms(errors, index, op, "surfaceHints", payload.get("surfaceHints"), max_len=16)
            _validate_secret_free(
                errors,
                index,
                op,
                payload,
                (
                    "canonicalText",
                    "summary",
                    "tags",
                    "aliases",
                    "surfaceHints",
                    "queryExpansions",
                    "claimKey",
                ),
            )
            if payload.get("claimState") not in {"current", "superseded", "retracted"}:
                errors.append(
                    _issue(index, op, "claimState", "unsupported_claim_state")
                )
            if bool(payload.get("directCandidateAllowed")):
                errors.append(_issue(index, op, "directCandidateAllowed", "canonical_text_must_not_be_direct_candidate"))
        elif op == "upsert_tag_edge":
            counts["tagEdges"] += 1
            _validate_required_text(errors, index, op, payload, "src")
            _validate_required_text(errors, index, op, payload, "dst")
            _validate_source_ids(
                errors,
                index,
                op,
                payload.get("evidenceEventIds"),
                field="evidenceEventIds",
                legal_source_event_ids=legal_source_event_ids,
            )
            _validate_secret_free(errors, index, op, payload, ("src", "dst"))
        elif op == "merge_semantic_tag":
            counts["tagMerges"] += 1
            _validate_required_text(errors, index, op, payload, "source")
            _validate_required_text(errors, index, op, payload, "target")
            _validate_required_text(errors, index, op, payload, "reason")
            _validate_source_ids(
                errors,
                index,
                op,
                payload.get("evidenceEventIds"),
                field="evidenceEventIds",
                legal_source_event_ids=legal_source_event_ids,
            )
            if normalize_text(str(payload.get("source") or "")) == normalize_text(str(payload.get("target") or "")):
                errors.append(_issue(index, op, "target", "tag_merge_source_equals_target"))
            _validate_secret_free(errors, index, op, payload, ("source", "target", "reason"))
        elif op == "add_phrase_candidate":
            counts["phraseCandidates"] += 1
            _validate_required_text(errors, index, op, payload, "text")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            text = compact_whitespace(str(payload.get("text") or ""))
            if len(text) < 2 or len(text) > 18:
                errors.append(_issue(index, op, "text", "phrase_text_length_out_of_range", value=len(text), preview=truncate_text(text, 80)))
            pinyin = compact_whitespace(str(payload.get("pinyin") or ""))
            if pinyin and not _RIME_PINYIN_RE.fullmatch(pinyin):
                errors.append(_issue(index, op, "pinyin", "invalid_rime_pinyin", preview=truncate_text(pinyin, 80)))
            _validate_secret_free(errors, index, op, payload, ("text", "tags"))
        elif op == "add_negative_phrase":
            counts["negativePhrases"] += 1
            _validate_required_text(errors, index, op, payload, "suppressionId")
            _validate_required_text(errors, index, op, payload, "text")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
            _validate_secret_free(errors, index, op, payload, ("text", "reason"))
        elif op == "supersede_memory":
            counts["supersedes"] += 1
            _validate_required_text(errors, index, op, payload, "oldId")
            _validate_required_text(errors, index, op, payload, "newId")
            _validate_source_ids(errors, index, op, payload.get("sourceEventIds"), legal_source_event_ids=legal_source_event_ids)
        else:
            errors.append(_issue(index, op, "op", "unsupported_op"))
        if op and _looks_like_long_history_sentence(payload):
            warnings.append(_issue(index, op, "payload", "looks_like_long_history_sentence"))
        group_id = compact_whitespace(str(payload.get("contextGroupId") or ""))
        if group_id and legal_groups and group_id not in legal_groups and group_id != "global":
            errors.append(_issue(index, op, "contextGroupId", "context_group_not_in_source_bundle"))
        for semantic_group_id in _strings(payload.get("semanticGroupIds")):
            if semantic_group_id not in planned_semantic_groups | existing_semantic_groups:
                errors.append(
                    _issue(index, op, "semanticGroupIds", "semantic_group_not_in_plan", preview=semantic_group_id)
                )
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
        if rows:
            _advance_compile_state(conn, plan=plan)
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_book_run",
                aggregate_id=run_id,
                operation="apply",
                project=compact_whitespace(
                    str(dict(plan.get("metadata") or {}).get("project") or "")
                ),
                payload={"runId": run_id, "diffCount": len(rows)},
            )
    return memory_book_run_payload(conn, run_id=run_id)


def find_memory_book_draft_for_bundle(
    conn: sqlite3.Connection,
    *,
    project: str,
    bundle_hash: str,
) -> dict[str, object] | None:
    """Return the newest review draft for one exact source bundle.

    Scheduled maintenance must not spend another model call every hour while
    the same evidence is still waiting for human review.
    """

    normalized_project = compact_whitespace(project)
    normalized_hash = compact_whitespace(bundle_hash)
    if not normalized_hash:
        return None
    rows = conn.execute(
        """
        SELECT run_id, metadata_json
        FROM memory_cleanup_runs
        WHERE status = 'draft' AND run_id LIKE 'memory_book_%'
        ORDER BY created_at_ms DESC, id DESC
        """
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        if compact_whitespace(str(metadata.get("project") or "")) != normalized_project:
            continue
        if compact_whitespace(str(metadata.get("bundleHash") or "")) != normalized_hash:
            continue
        run = memory_book_run_payload(conn, run_id=str(row["run_id"]))
        if memory_book_run_is_stale(conn, run=run):
            continue
        return run
    return None


def memory_book_run_is_stale(conn: sqlite3.Connection, *, run: Mapping[str, object]) -> bool:
    """Return whether a draft's evidence cursor was already consumed by a newer apply."""

    if compact_whitespace(str(run.get("status") or "")) != "draft":
        return False
    metadata = dict(run.get("metadata") or {})
    project = compact_whitespace(str(metadata.get("project") or ""))
    source_cursor = dict(metadata.get("sourceCursor") or {})
    try:
        to_event_id = int(source_cursor.get("toEventId") or 0)
    except (TypeError, ValueError):
        return False
    if not project or to_event_id <= 0:
        return False
    state = memory_compile_state(conn, project=project)
    return int(state.get("lastCompiledEventId") or 0) >= to_event_id


def memory_book_plan_from_stored_run(run: Mapping[str, object]) -> dict[str, object]:
    """Rebuild a validated plan payload from a review draft."""

    run_id = compact_whitespace(str(run.get("runId") or ""))
    if not run_id:
        raise ValueError("stored memory book runId is required")
    return {
        "schemaVersion": MEMORY_BOOK_RUN_SCHEMA_VERSION,
        "runId": run_id,
        "provider": str(run.get("provider") or ""),
        "model": str(run.get("model") or ""),
        "summary": str(run.get("summary") or ""),
        "metadata": dict(run.get("metadata") or {}),
        "diffs": [
            {
                "op": str(item.get("op") or ""),
                "targetId": str(item.get("targetId") or ""),
                "payload": dict(item.get("payload") or {}),
                "status": str(item.get("status") or "pending"),
            }
            for item in _list_of_dicts(run.get("diffs"))
        ],
    }


def store_memory_book_plan(
    conn: sqlite3.Connection,
    plan: dict[str, object],
    *,
    supersede_project_drafts: bool = False,
) -> dict[str, object]:
    """Persist a validated compiler plan as a draft without changing user memory."""
    validation = inspect_memory_book_plan(plan)
    if not validation.get("ok"):
        raise ValueError("memory book plan failed validation")
    run_id = compact_whitespace(str(plan.get("runId") or ""))
    if not run_id:
        raise ValueError("memory book runId is required")
    with conn:
        if supersede_project_drafts:
            _supersede_project_memory_book_drafts(conn, plan=plan)
        _persist_memory_book_run(conn, plan)
    return memory_book_run_payload(conn, run_id=run_id)


def _supersede_project_memory_book_drafts(
    conn: sqlite3.Connection,
    *,
    plan: Mapping[str, object],
) -> None:
    run_id = compact_whitespace(str(plan.get("runId") or ""))
    metadata = dict(plan.get("metadata") or {})
    project = compact_whitespace(str(metadata.get("project") or ""))
    if not project:
        return
    rows = conn.execute(
        """
        SELECT run_id, metadata_json
        FROM memory_cleanup_runs
        WHERE status = 'draft' AND run_id LIKE 'memory_book_%' AND run_id != ?
        """,
        (run_id,),
    ).fetchall()
    superseded: list[str] = []
    for row in rows:
        try:
            previous_metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(previous_metadata, dict):
            continue
        if compact_whitespace(str(previous_metadata.get("project") or "")) == project:
            superseded.append(str(row["run_id"]))
    for previous_run_id in superseded:
        conn.execute(
            "UPDATE memory_cleanup_runs SET status = 'superseded' WHERE run_id = ?",
            (previous_run_id,),
        )
        conn.execute(
            """
            UPDATE memory_cleanup_diffs
            SET status = 'rejected'
            WHERE run_id = ? AND status IN ('pending', 'approved')
            """,
            (previous_run_id,),
        )


def update_stored_memory_book_diff(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    diff_id: int,
    payload: dict[str, object] | None = None,
    selected: bool = True,
) -> dict[str, object]:
    """Edit or include/exclude one draft operation before the atomic apply step."""
    current = memory_book_run_payload(conn, run_id=run_id)
    if not current.get("provider"):
        raise ValueError(f"memory book run not found: {run_id}")
    if str(current.get("status") or "") != "draft":
        raise ValueError("only draft memory book runs can be edited")
    row = conn.execute(
        """
        SELECT id, op, target_memory_id, payload_json, status
        FROM memory_cleanup_diffs
        WHERE run_id = ? AND id = ?
        LIMIT 1
        """,
        (run_id, int(diff_id)),
    ).fetchone()
    if row is None:
        raise ValueError(f"memory book diff not found: {diff_id}")
    if str(row["status"] or "") not in {"pending", "approved", "rejected"}:
        raise ValueError("applied memory book diffs cannot be edited")

    next_payload = dict(payload) if payload is not None else json.loads(row["payload_json"] or "{}")
    next_status = "approved" if selected else "rejected"
    if selected:
        metadata = dict(current.get("metadata") or {})
        selected_diffs: list[dict[str, object]] = []
        for item in current.get("diffs") or []:
            if not isinstance(item, dict):
                continue
            item_id = int(item.get("diffId") or 0)
            item_status = next_status if item_id == int(diff_id) else str(item.get("status") or "pending")
            if item_status == "rejected":
                continue
            selected_diffs.append(
                {
                    "op": str(item.get("op") or ""),
                    "targetId": str(item.get("targetId") or ""),
                    "payload": next_payload if item_id == int(diff_id) else dict(item.get("payload") or {}),
                    "status": item_status,
                }
            )
        validation = inspect_memory_book_plan(
            {
                "schemaVersion": MEMORY_BOOK_RUN_SCHEMA_VERSION,
                "runId": run_id,
                "provider": str(current.get("provider") or ""),
                "model": str(current.get("model") or ""),
                "summary": str(current.get("summary") or ""),
                "metadata": metadata,
                "diffs": selected_diffs,
            }
        )
        if not validation.get("ok"):
            first_error = next(iter(validation.get("errors") or []), {})
            raise ValueError(f"draft edit failed validation: {first_error.get('reason') or 'invalid payload'}")

    with conn:
        conn.execute(
            """
            UPDATE memory_cleanup_diffs
            SET payload_json = ?, status = ?
            WHERE run_id = ? AND id = ?
            """,
            (json.dumps(next_payload, ensure_ascii=False, sort_keys=True), next_status, run_id, int(diff_id)),
        )
    return memory_book_run_payload(conn, run_id=run_id)


def apply_stored_memory_book_run(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
    """Apply a previously reviewed draft run without regenerating it."""
    current = memory_book_run_payload(conn, run_id=run_id)
    if not current.get("provider"):
        raise ValueError(f"memory book run not found: {run_id}")
    status = compact_whitespace(str(current.get("status") or ""))
    if status not in {"draft", "partial"}:
        raise ValueError(f"memory book run is not reviewable: {run_id} ({status or 'unknown'})")
    if memory_book_run_is_stale(conn, run=current):
        raise ValueError(f"memory book draft is stale: {run_id}")
    with conn:
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
        if rows:
            _advance_compile_state(conn, plan={"metadata": dict(current.get("metadata") or {})})
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_book_run",
                aggregate_id=run_id,
                operation="apply",
                project=compact_whitespace(
                    str(dict(current.get("metadata") or {}).get("project") or "")
                ),
                payload={"runId": run_id, "diffCount": len(rows)},
            )
    return memory_book_run_payload(conn, run_id=run_id)


def rollback_memory_book_run(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
    current = memory_book_run_payload(conn, run_id=run_id)
    if not current.get("provider"):
        raise ValueError(f"memory book run not found: {run_id}")
    status = compact_whitespace(str(current.get("status") or ""))
    if status not in {"applied", "partial"}:
        raise ValueError(f"memory book run is not rollbackable: {run_id} ({status or 'unknown'})")
    newer_run = find_newer_applied_memory_book_run(conn, run_id=run_id)
    if newer_run is not None:
        raise ValueError(
            "memory book run is not rollbackable after a newer applied run: "
            f"{run_id} -> {newer_run['runId']}"
        )
    with conn:
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
            conn.execute(
                "UPDATE memory_cleanup_diffs SET status = 'rolled_back' WHERE id = ?",
                (int(row["id"]),),
            )
        _sync_run_status(conn, run_id)
        if rows:
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_book_run",
                aggregate_id=run_id,
                operation="rollback",
                project=compact_whitespace(
                    str(dict(current.get("metadata") or {}).get("project") or "")
                ),
                payload={"runId": run_id, "diffCount": len(rows)},
            )
    return memory_book_run_payload(conn, run_id=run_id)


def memory_book_run_payload(conn: sqlite3.Connection, *, run_id: str) -> dict[str, object]:
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
        "createdAtMs": 0 if run is None else int(run["created_at_ms"] or 0),
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


def find_newer_applied_memory_book_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
) -> dict[str, object] | None:
    """Return a later active apply that makes this run unsafe to roll back.

    Each diff stores the database state that existed immediately before its
    own apply. Replaying an older rollback after a newer apply would therefore
    overwrite the newer memory state. Runs must unwind in reverse apply order.
    """

    current = conn.execute(
        "SELECT id, metadata_json FROM memory_cleanup_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if current is None:
        return None
    try:
        current_metadata = json.loads(current["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        current_metadata = {}
    project = compact_whitespace(
        str(current_metadata.get("project") or "") if isinstance(current_metadata, dict) else ""
    )
    rows = conn.execute(
        """
        SELECT id, run_id, created_at_ms, status, metadata_json
        FROM memory_cleanup_runs
        WHERE id > ? AND status IN ('applied', 'partial') AND run_id LIKE 'memory_book_%'
        ORDER BY id DESC
        """,
        (int(current["id"]),),
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        if compact_whitespace(str(metadata.get("project") or "")) != project:
            continue
        return {
            "runId": str(row["run_id"]),
            "createdAtMs": int(row["created_at_ms"] or 0),
            "status": str(row["status"]),
        }
    return None


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
    if op == "upsert_semantic_group":
        return _apply_semantic_group(conn, payload)
    if op == "upsert_semantic_tag":
        return _apply_semantic_tag(conn, payload)
    if op == "upsert_memory_book":
        return _apply_memory_book(conn, payload)
    if op == "upsert_memory_atom":
        return _apply_memory_atom(conn, payload)
    if op == "upsert_tag_edge":
        return _apply_tag_edge(conn, payload)
    if op == "merge_semantic_tag":
        return _apply_semantic_tag_merge(conn, payload)
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
    if op == "upsert_semantic_group":
        _restore_or_delete_row(conn, table="memory_semantic_groups", pk="group_id", rollback=rollback)
    elif op == "upsert_semantic_tag":
        _restore_or_delete_row(conn, table="memory_tags", pk="id", rollback=rollback)
        _restore_or_delete_row(conn, table="memory_tag_profiles", pk="tag_id", rollback=dict(rollback.get("profile") or {}))
        _restore_semantic_group_members(conn, rollback)
    elif op == "upsert_memory_book":
        _restore_or_delete_row(conn, table="memory_books", pk="book_id", rollback=rollback)
        _restore_semantic_group_members(conn, rollback)
    elif op == "upsert_memory_atom":
        _restore_or_delete_row(conn, table="memory_atoms", pk="id", rollback=rollback)
        for old_row in rollback.get("autoSuperseded", []) or []:
            if isinstance(old_row, dict):
                _insert_or_replace_dict(conn, "memory_atoms", old_row)
        for relation in rollback.get("supersessionRollbacks", []) or []:
            if isinstance(relation, dict):
                _restore_or_delete_row(
                    conn,
                    table="memory_supersessions",
                    pk="supersession_id",
                    rollback=relation,
                )
        _restore_semantic_group_members(conn, rollback)
        for alias_id in rollback.get("createdAliasIds", []) or []:
            conn.execute("DELETE FROM memory_aliases WHERE id = ?", (str(alias_id),))
    elif op == "upsert_tag_edge":
        edge = rollback.get("edge")
        if isinstance(edge, dict):
            previous = rollback.get("previous")
            if isinstance(previous, dict) and previous:
                columns = list(previous.keys())
                conn.execute(
                    f"INSERT OR REPLACE INTO memory_tag_edges({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [previous[column] for column in columns],
                )
            else:
                conn.execute(
                    "DELETE FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
                    (
                        int(edge.get("srcTagId") or 0),
                        int(edge.get("dstTagId") or 0),
                        str(edge.get("edgeType") or ""),
                    ),
                )
    elif op == "merge_semantic_tag":
        _rollback_semantic_tag_merge(conn, rollback)
    elif op == "add_phrase_candidate":
        _restore_or_delete_row(conn, table="memory_items", pk="memory_id", rollback=rollback)
        _restore_semantic_group_members(conn, rollback)
        conn.execute("DELETE FROM memory_items_fts WHERE rowid NOT IN (SELECT id FROM memory_items)")
        conn.execute("DELETE FROM memory_item_tags WHERE memory_item_id NOT IN (SELECT id FROM memory_items)")
    elif op == "add_negative_phrase":
        _restore_or_delete_row(conn, table="memory_candidate_suppressions", pk="id", rollback=rollback)
    elif op == "supersede_memory":
        table = compact_whitespace(str(rollback.get("table") or ""))
        pk = "id" if table == "memory_atoms" else "memory_id"
        if table in {"memory_atoms", "memory_items"}:
            _restore_or_delete_row(conn, table=table, pk=pk, rollback=rollback)
        relation = rollback.get("supersession")
        if isinstance(relation, dict):
            _restore_or_delete_row(
                conn,
                table="memory_supersessions",
                pk="supersession_id",
                rollback=relation,
            )


def _apply_semantic_group(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    group_id = str(payload["groupId"])
    previous = _row_dict(
        conn.execute("SELECT * FROM memory_semantic_groups WHERE group_id = ?", (group_id,)).fetchone()
    )
    timestamp = now_ms()
    conn.execute(
        """
        INSERT INTO memory_semantic_groups(
            group_id, title, description, project, aliases_json, tags_json,
            source_event_ids_json, status, confidence, quality_score,
            created_at_ms, updated_at_ms, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            project = excluded.project,
            aliases_json = excluded.aliases_json,
            tags_json = excluded.tags_json,
            source_event_ids_json = excluded.source_event_ids_json,
            status = excluded.status,
            confidence = excluded.confidence,
            quality_score = excluded.quality_score,
            updated_at_ms = excluded.updated_at_ms,
            metadata_json = excluded.metadata_json
        """,
        (
            group_id,
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            str(payload.get("project") or ""),
            json.dumps(_strings(payload.get("aliases")), ensure_ascii=False),
            json.dumps(_strings(payload.get("tags")), ensure_ascii=False),
            json.dumps(_positive_ints(payload.get("sourceEventIds")), ensure_ascii=False),
            str(payload.get("status") or "active"),
            _bounded_float(payload.get("confidence"), default=0.7),
            _bounded_float(payload.get("qualityScore"), default=0.7),
            int(previous.get("created_at_ms") or timestamp),
            timestamp,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {"table": "memory_semantic_groups", "pk": "group_id", "pkValue": group_id, "previous": previous}


def _apply_semantic_tag(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    name = str(payload["name"])
    row = conn.execute(
        "SELECT id FROM memory_tags WHERE tag = ? OR normalized_tag = ? "
        "ORDER BY CASE WHEN tag = ? THEN 0 ELSE 1 END, quality_score DESC LIMIT 1",
        (name, normalize_text(name), name),
    ).fetchone()
    timestamp = now_ms()
    if row is None:
        cursor = conn.execute(
            """
            INSERT INTO memory_tags(
                tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms,
                description, source, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'dsv4', ?, ?)
            """,
            (
                name,
                normalize_text(name),
                str(payload.get("type") or "concept"),
                _bounded_float(payload.get("qualityScore"), default=0.7),
                timestamp,
                timestamp,
                str(payload.get("description") or ""),
                str(payload.get("status") or "active"),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        tag_id = int(cursor.lastrowid)
        previous: dict[str, object] = {}
    else:
        tag_id = int(row["id"])
        previous = _row_dict(conn.execute("SELECT * FROM memory_tags WHERE id = ?", (tag_id,)).fetchone())
        conn.execute(
            """
            UPDATE memory_tags
            SET normalized_tag = ?, tag_type = ?, quality_score = ?, updated_at_ms = ?,
                description = ?,
                source = CASE WHEN source = 'user' THEN 'user' ELSE 'dsv4' END,
                status = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                normalize_text(name),
                str(payload.get("type") or "concept"),
                _bounded_float(payload.get("qualityScore"), default=0.7),
                timestamp,
                str(payload.get("description") or ""),
                str(payload.get("status") or "active"),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                tag_id,
            ),
        )
    profile_previous = _row_dict(
        conn.execute("SELECT * FROM memory_tag_profiles WHERE tag_id = ?", (tag_id,)).fetchone()
    )
    conn.execute(
        """
        INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms)
        VALUES (?, 'blue', ?, ?)
        ON CONFLICT(tag_id) DO UPDATE SET aliases_json = excluded.aliases_json, updated_at_ms = excluded.updated_at_ms
        """,
        (tag_id, json.dumps(_strings(payload.get("aliases")), ensure_ascii=False), timestamp),
    )
    memberships = _sync_semantic_group_members(
        conn,
        member_type="tag",
        member_id=str(tag_id),
        group_ids=_strings(payload.get("semanticGroupIds")),
    )
    return {
        "table": "memory_tags",
        "pk": "id",
        "pkValue": str(tag_id),
        "previous": previous,
        "profile": {
            "table": "memory_tag_profiles",
            "pk": "tag_id",
            "pkValue": str(tag_id),
            "previous": profile_previous,
        },
        **memberships,
    }


def _apply_memory_book(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    book_id = str(payload["bookId"])
    previous = _row_dict(conn.execute("SELECT * FROM memory_books WHERE book_id = ?", (book_id,)).fetchone())
    timestamp = now_ms()
    conn.execute(
        """
        INSERT INTO memory_books(
            book_id, book_type, book_key, title, summary, normalized_text, project, app,
            tags_json, surface_hints_json, query_expansions_json, source_event_ids_json,
            memory_atom_ids_json, status, confidence, quality_score, created_at_ms, updated_at_ms,
            metadata_json, archived_at_ms, last_active_at_ms, archive_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT created_at_ms FROM memory_books WHERE book_id = ?), ?),
                ?, ?, NULL, ?, '')
        ON CONFLICT(book_id) DO UPDATE SET
            book_type = excluded.book_type,
            book_key = excluded.book_key,
            title = excluded.title,
            summary = excluded.summary,
            normalized_text = excluded.normalized_text,
            project = excluded.project,
            app = excluded.app,
            tags_json = excluded.tags_json,
            surface_hints_json = excluded.surface_hints_json,
            query_expansions_json = excluded.query_expansions_json,
            source_event_ids_json = excluded.source_event_ids_json,
            memory_atom_ids_json = excluded.memory_atom_ids_json,
            status = excluded.status,
            confidence = excluded.confidence,
            quality_score = excluded.quality_score,
            updated_at_ms = excluded.updated_at_ms,
            metadata_json = excluded.metadata_json,
            archived_at_ms = NULL,
            last_active_at_ms = excluded.last_active_at_ms,
            archive_reason = ''
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
            timestamp,
        ),
    )
    memberships = _sync_semantic_group_members(
        conn,
        member_type="book",
        member_id=book_id,
        group_ids=_strings(payload.get("semanticGroupIds")),
    )
    return {"table": "memory_books", "pk": "book_id", "pkValue": book_id, "previous": previous, **memberships}


def _apply_memory_atom(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    atom_id = str(payload["atomId"])
    previous = _row_dict(conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone())
    timestamp = now_ms()
    canonical = str(payload.get("canonicalText") or "")
    kind = str(payload.get("kind") or "project_fact")
    app = str(payload.get("app") or "")
    project = str(payload.get("project") or "")
    claim_key = _normalized_claim_key(payload.get("claimKey"))
    if not claim_key:
        raise ValueError("memory atom claimKey is required")
    lineage_id = compact_whitespace(str(payload.get("lineageId") or ""))
    if not lineage_id:
        lineage_id = (
            "lineage:"
            + stable_text_hash(
                f"{kind}\n{project}\n{app}\n{claim_key}"
            ).removeprefix("sha256:")[:24]
        )
    claim_state = compact_whitespace(str(payload.get("claimState") or "current")).lower()
    if claim_state not in {"current", "superseded", "retracted"}:
        raise ValueError(f"unsupported memory atom claimState: {claim_state}")
    valid_from_ms = _optional_int(payload.get("validFromMs")) or timestamp
    valid_to_ms = _optional_int(payload.get("validToMs")) or None
    requested_status = str(payload.get("status") or "active")
    stored_status = requested_status
    auto_superseded: list[dict[str, object]] = []
    supersession_rollbacks: list[dict[str, object]] = []
    supersedes_id = compact_whitespace(str(payload.get("supersedesId") or ""))

    current_rows = conn.execute(
        """
        SELECT *
        FROM memory_atoms
        WHERE claim_key = ?
          AND COALESCE(scope_project, '') = ?
          AND COALESCE(scope_app, '') = ?
          AND kind = ?
          AND id <> ?
          AND claim_state = 'current'
          AND status IN ('active', 'approved')
        ORDER BY valid_from_ms DESC, updated_at_ms DESC
        """,
        (claim_key, project, app, kind, atom_id),
    ).fetchall()
    if claim_state == "current" and requested_status in {"active", "approved"}:
        newer_current = next(
            (
                row
                for row in current_rows
                if int(row["valid_from_ms"] or 0) > valid_from_ms
            ),
            None,
        )
        if newer_current is not None:
            # Replayed or delayed evidence is history, not the current truth.
            claim_state = "superseded"
            stored_status = "superseded"
            valid_to_ms = int(newer_current["valid_from_ms"] or timestamp)
            supersedes_id = ""
        else:
            for row in current_rows:
                old = _row_dict(row)
                auto_superseded.append(old)
                old_id = str(row["id"])
                conn.execute(
                    """
                    UPDATE memory_atoms
                    SET status = 'superseded',
                        claim_state = 'superseded',
                        valid_to_ms = ?,
                        updated_at_ms = ?
                    WHERE id = ?
                    """,
                    (max(valid_from_ms, 1), timestamp, old_id),
                )
                supersedes_id = supersedes_id or old_id
                supersession_rollbacks.append(
                    _record_memory_supersession(
                        conn,
                        old_id=old_id,
                        new_id=atom_id,
                        source_event_ids=_positive_ints(payload.get("sourceEventIds")),
                        reason="same_claim_key_newer_value",
                    )
                )
    elif claim_state != "current" and stored_status in {"active", "approved"}:
        stored_status = "superseded"
        valid_to_ms = valid_to_ms or timestamp

    conn.execute(
        """
        INSERT INTO memory_atoms(
            id, kind, text, canonical_text, source_event_ids_json, source_memory_ids_json,
            scope_app, scope_project, language, confidence, quality_score, echo_risk,
            privacy_level, status, created_at_ms, updated_at_ms, last_used_at_ms,
            claim_key, lineage_id, claim_state, valid_from_ms, valid_to_ms, supersedes_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'zh', ?, ?, 0.0, 'local', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            kind = excluded.kind,
            text = excluded.text,
            canonical_text = excluded.canonical_text,
            source_event_ids_json = excluded.source_event_ids_json,
            source_memory_ids_json = excluded.source_memory_ids_json,
            scope_app = excluded.scope_app,
            scope_project = excluded.scope_project,
            confidence = excluded.confidence,
            quality_score = excluded.quality_score,
            status = excluded.status,
            updated_at_ms = excluded.updated_at_ms,
            claim_key = excluded.claim_key,
            lineage_id = excluded.lineage_id,
            claim_state = excluded.claim_state,
            valid_from_ms = excluded.valid_from_ms,
            valid_to_ms = excluded.valid_to_ms,
            supersedes_id = excluded.supersedes_id
        """,
        (
            atom_id,
            kind,
            canonical,
            canonical,
            json.dumps(_positive_ints(payload.get("sourceEventIds")), ensure_ascii=False),
            json.dumps(_strings(payload.get("sourceMemoryIds")), ensure_ascii=False),
            app,
            project,
            _bounded_float(payload.get("confidence"), default=0.5),
            _bounded_float(payload.get("qualityScore"), default=0.5),
            stored_status,
            timestamp,
            timestamp,
            claim_key,
            lineage_id,
            claim_state,
            valid_from_ms,
            valid_to_ms,
            supersedes_id or None,
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
        tag_id = _ensure_tag(conn, tag, source="dsv4")
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
            VALUES (?, ?, 0.8, 'memory_book_compile')
            """,
            (atom_id, str(tag_id)),
        )
    memberships = _sync_semantic_group_members(
        conn,
        member_type="atom",
        member_id=atom_id,
        group_ids=_strings(payload.get("semanticGroupIds")),
    )
    return {
        "table": "memory_atoms",
        "pk": "id",
        "pkValue": atom_id,
        "previous": previous,
        "createdAliasIds": created_alias_ids,
        "autoSuperseded": auto_superseded,
        "supersessionRollbacks": supersession_rollbacks,
        **memberships,
    }


def _apply_tag_edge(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    src_id = _ensure_tag(conn, str(payload.get("src") or ""), source="dsv4")
    dst_id = _ensure_tag(conn, str(payload.get("dst") or ""), source="dsv4")
    edge_type = str(payload.get("edgeType") or "related")
    previous = _row_dict(
        conn.execute(
            "SELECT * FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
            (src_id, dst_id, edge_type),
        ).fetchone()
    )
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
    return {
        "edge": {"srcTagId": src_id, "dstTagId": dst_id, "edgeType": edge_type},
        "previous": previous,
    }


def _apply_semantic_tag_merge(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    source_name = compact_whitespace(str(payload.get("source") or ""))
    target_name = compact_whitespace(str(payload.get("target") or ""))
    source = conn.execute(
        "SELECT * FROM memory_tags WHERE tag = ? OR normalized_tag = ? "
        "ORDER BY CASE WHEN tag = ? THEN 0 ELSE 1 END, quality_score DESC LIMIT 1",
        (source_name, normalize_text(source_name), source_name),
    ).fetchone()
    target = conn.execute(
        "SELECT * FROM memory_tags WHERE tag = ? OR normalized_tag = ? "
        "ORDER BY CASE WHEN tag = ? THEN 0 ELSE 1 END, quality_score DESC LIMIT 1",
        (target_name, normalize_text(target_name), target_name),
    ).fetchone()
    if source is None or target is None:
        # Older stored drafts could contain a model-proposed merge whose
        # source only existed in the same compile output. The compiler already
        # canonicalized that virtual tag into the target, so there is no row
        # left to move. Treat this as an observable no-op instead of aborting
        # every other reviewed diff in the transaction.
        missing = "source" if source is None else "target"
        return {
            "noOp": True,
            "reason": f"missing_{missing}",
            "source": source_name,
            "target": target_name,
        }
    source_id = int(source["id"])
    target_id = int(target["id"])
    if source_id == target_id:
        return {"noOp": True, "sourceTagId": source_id, "targetTagId": target_id}

    snapshot = {
        "sourceTagId": source_id,
        "targetTagId": target_id,
        "tags": [dict(source), dict(target)],
        "profiles": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memory_tag_profiles WHERE tag_id IN (?, ?)",
                (source_id, target_id),
            ).fetchall()
        ],
        "itemTags": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memory_item_tags WHERE tag_id IN (?, ?)",
                (source_id, target_id),
            ).fetchall()
        ],
        "atomTags": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memory_atom_tags WHERE CAST(tag_id AS INTEGER) IN (?, ?)",
                (source_id, target_id),
            ).fetchall()
        ],
        "edges": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memory_tag_edges WHERE src_tag_id IN (?, ?) OR dst_tag_id IN (?, ?)",
                (source_id, target_id, source_id, target_id),
            ).fetchall()
        ],
        "groupMembers": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM memory_semantic_group_members "
                "WHERE member_type = 'tag' AND member_id IN (?, ?)",
                (str(source_id), str(target_id)),
            ).fetchall()
        ],
        "bookTags": [
            {"book_id": str(row["book_id"]), "tags_json": str(row["tags_json"] or "[]")}
            for row in conn.execute("SELECT book_id, tags_json FROM memory_books").fetchall()
            if source_name in _json_list(row["tags_json"])
        ],
    }
    timestamp = now_ms()

    for row in conn.execute(
        "SELECT memory_item_id, weight, position, evidence FROM memory_item_tags WHERE tag_id = ?",
        (source_id,),
    ).fetchall():
        existing = conn.execute(
            "SELECT weight, position, evidence FROM memory_item_tags WHERE memory_item_id = ? AND tag_id = ?",
            (row["memory_item_id"], target_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence) VALUES (?, ?, ?, ?, ?)",
                (row["memory_item_id"], target_id, row["weight"], row["position"], row["evidence"]),
            )
        else:
            conn.execute(
                "UPDATE memory_item_tags SET weight = MAX(weight, ?), position = MIN(position, ?), evidence = ? "
                "WHERE memory_item_id = ? AND tag_id = ?",
                (
                    row["weight"],
                    row["position"],
                    str(existing["evidence"] or row["evidence"] or ""),
                    row["memory_item_id"],
                    target_id,
                ),
            )
    conn.execute("DELETE FROM memory_item_tags WHERE tag_id = ?", (source_id,))

    for row in conn.execute(
        "SELECT memory_atom_id, weight, source FROM memory_atom_tags WHERE CAST(tag_id AS INTEGER) = ?",
        (source_id,),
    ).fetchall():
        existing = conn.execute(
            "SELECT weight FROM memory_atom_tags WHERE memory_atom_id = ? AND CAST(tag_id AS INTEGER) = ?",
            (row["memory_atom_id"], target_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES (?, ?, ?, ?)",
                (row["memory_atom_id"], str(target_id), row["weight"], row["source"]),
            )
        else:
            conn.execute(
                "UPDATE memory_atom_tags SET weight = MAX(weight, ?), source = 'dsv4_merge' "
                "WHERE memory_atom_id = ? AND CAST(tag_id AS INTEGER) = ?",
                (row["weight"], row["memory_atom_id"], target_id),
            )
    conn.execute("DELETE FROM memory_atom_tags WHERE CAST(tag_id AS INTEGER) = ?", (source_id,))

    source_edges = conn.execute(
        "SELECT * FROM memory_tag_edges WHERE src_tag_id = ? OR dst_tag_id = ?",
        (source_id, source_id),
    ).fetchall()
    conn.execute("DELETE FROM memory_tag_edges WHERE src_tag_id = ? OR dst_tag_id = ?", (source_id, source_id))
    for row in source_edges:
        src_id = target_id if int(row["src_tag_id"]) == source_id else int(row["src_tag_id"])
        dst_id = target_id if int(row["dst_tag_id"]) == source_id else int(row["dst_tag_id"])
        if src_id == dst_id:
            continue
        existing = conn.execute(
            "SELECT weight, evidence_count FROM memory_tag_edges "
            "WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
            (src_id, dst_id, row["edge_type"]),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, "
                "evidence_count, updated_at_ms, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    src_id,
                    dst_id,
                    row["edge_type"],
                    row["weight"],
                    row["direction_bias"],
                    row["evidence_count"],
                    timestamp,
                    row["metadata_json"],
                ),
            )
        else:
            conn.execute(
                "UPDATE memory_tag_edges SET weight = MAX(weight, ?), evidence_count = evidence_count + ?, "
                "updated_at_ms = ? WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
                (
                    row["weight"],
                    row["evidence_count"],
                    timestamp,
                    src_id,
                    dst_id,
                    row["edge_type"],
                ),
            )

    for row in conn.execute(
        "SELECT group_id, weight, source FROM memory_semantic_group_members "
        "WHERE member_type = 'tag' AND member_id = ?",
        (str(source_id),),
    ).fetchall():
        conn.execute(
            "INSERT INTO memory_semantic_group_members(group_id, member_type, member_id, weight, source, updated_at_ms) "
            "VALUES (?, 'tag', ?, ?, ?, ?) ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET "
            "weight = MAX(weight, excluded.weight), source = 'dsv4_merge', updated_at_ms = excluded.updated_at_ms",
            (row["group_id"], str(target_id), row["weight"], row["source"], timestamp),
        )
    conn.execute(
        "DELETE FROM memory_semantic_group_members WHERE member_type = 'tag' AND member_id = ?",
        (str(source_id),),
    )

    source_profile = next((row for row in snapshot["profiles"] if int(row["tag_id"]) == source_id), {})
    target_profile = next((row for row in snapshot["profiles"] if int(row["tag_id"]) == target_id), {})
    aliases = _unique_strings(
        [
            *_json_list(target_profile.get("aliases_json")),
            source_name,
            *_json_list(source_profile.get("aliases_json")),
        ],
        limit=48,
    )
    conn.execute(
        "INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(tag_id) DO UPDATE SET aliases_json = excluded.aliases_json, updated_at_ms = excluded.updated_at_ms",
        (
            target_id,
            str(target_profile.get("color_token") or source_profile.get("color_token") or "blue"),
            json.dumps(aliases, ensure_ascii=False),
            timestamp,
        ),
    )
    conn.execute("DELETE FROM memory_tag_profiles WHERE tag_id = ?", (source_id,))
    for row in snapshot["bookTags"]:
        tags = [target_name if tag == source_name else tag for tag in _json_list(row["tags_json"])]
        conn.execute(
            "UPDATE memory_books SET tags_json = ?, updated_at_ms = ? WHERE book_id = ?",
            (json.dumps(_unique_strings(tags, limit=48), ensure_ascii=False), timestamp, row["book_id"]),
        )
    conn.execute("DELETE FROM memory_tags WHERE id = ?", (source_id,))
    return snapshot


def _rollback_semantic_tag_merge(conn: sqlite3.Connection, rollback: dict[str, object]) -> None:
    if rollback.get("noOp"):
        return
    source_id = int(rollback.get("sourceTagId") or 0)
    target_id = int(rollback.get("targetTagId") or 0)
    if not source_id or not target_id:
        return
    for row in _list_of_dicts(rollback.get("tags")):
        _insert_or_replace_dict(conn, "memory_tags", row)
    conn.execute("DELETE FROM memory_tag_profiles WHERE tag_id IN (?, ?)", (source_id, target_id))
    for row in _list_of_dicts(rollback.get("profiles")):
        _insert_or_replace_dict(conn, "memory_tag_profiles", row)
    conn.execute("DELETE FROM memory_item_tags WHERE tag_id IN (?, ?)", (source_id, target_id))
    for row in _list_of_dicts(rollback.get("itemTags")):
        _insert_or_replace_dict(conn, "memory_item_tags", row)
    conn.execute("DELETE FROM memory_atom_tags WHERE CAST(tag_id AS INTEGER) IN (?, ?)", (source_id, target_id))
    for row in _list_of_dicts(rollback.get("atomTags")):
        _insert_or_replace_dict(conn, "memory_atom_tags", row)
    conn.execute(
        "DELETE FROM memory_tag_edges WHERE src_tag_id IN (?, ?) OR dst_tag_id IN (?, ?)",
        (source_id, target_id, source_id, target_id),
    )
    for row in _list_of_dicts(rollback.get("edges")):
        _insert_or_replace_dict(conn, "memory_tag_edges", row)
    conn.execute(
        "DELETE FROM memory_semantic_group_members WHERE member_type = 'tag' AND member_id IN (?, ?)",
        (str(source_id), str(target_id)),
    )
    for row in _list_of_dicts(rollback.get("groupMembers")):
        _insert_or_replace_dict(conn, "memory_semantic_group_members", row)
    for row in _list_of_dicts(rollback.get("bookTags")):
        conn.execute(
            "UPDATE memory_books SET tags_json = ? WHERE book_id = ?",
            (str(row.get("tags_json") or "[]"), str(row.get("book_id") or "")),
        )


def _insert_or_replace_dict(conn: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    if not row:
        return
    columns = list(row.keys())
    conn.execute(
        f"INSERT OR REPLACE INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [row[column] for column in columns],
    )


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
        tag_source="dsv4",
    )
    memberships = _sync_semantic_group_members(
        conn,
        member_type="phrase",
        member_id=memory_id,
        group_ids=_strings(payload.get("semanticGroupIds")),
    )
    return {"table": "memory_items", "pk": "memory_id", "pkValue": memory_id, "previous": previous, **memberships}


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


def _record_memory_supersession(
    conn: sqlite3.Connection,
    *,
    old_id: str,
    new_id: str,
    source_event_ids: list[int],
    reason: str,
) -> dict[str, object]:
    supersession_id = f"supersession:{stable_text_hash(f'{old_id}->{new_id}').removeprefix('sha256:')[:24]}"
    previous_relation = _row_dict(
        conn.execute(
            "SELECT * FROM memory_supersessions WHERE supersession_id = ?",
            (supersession_id,),
        ).fetchone()
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_supersessions(
            supersession_id, old_memory_id, new_memory_id, reason,
            source_event_ids_json, status, created_at_ms, rolled_back_at_ms,
            metadata_json
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, ?)
        """,
        (
            supersession_id,
            old_id,
            new_id,
            compact_whitespace(reason) or "newer_explicit_information",
            json.dumps(source_event_ids, ensure_ascii=False),
            now_ms(),
            json.dumps({"source": "memory_book_compile"}, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {
        "table": "memory_supersessions",
        "pk": "supersession_id",
        "pkValue": supersession_id,
        "previous": previous_relation,
    }


def _apply_supersede_memory(conn: sqlite3.Connection, payload: dict[str, object]) -> dict[str, object]:
    old_id = str(payload["oldId"])
    new_id = str(payload["newId"])
    relation_rollback = _record_memory_supersession(
        conn,
        old_id=old_id,
        new_id=new_id,
        source_event_ids=_positive_ints(payload.get("sourceEventIds")),
        reason=compact_whitespace(
            str(payload.get("reason") or "newer_explicit_information")
        ),
    )
    atom = conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (old_id,)).fetchone()
    if atom is not None:
        previous = _row_dict(atom)
        conn.execute(
            """
            UPDATE memory_atoms
            SET status = 'superseded',
                claim_state = 'superseded',
                valid_to_ms = COALESCE(valid_to_ms, ?),
                updated_at_ms = ?
            WHERE id = ?
            """,
            (now_ms(), now_ms(), old_id),
        )
        return {
            "table": "memory_atoms",
            "pk": "id",
            "pkValue": old_id,
            "previous": previous,
            "supersession": relation_rollback,
        }
    item = conn.execute("SELECT * FROM memory_items WHERE memory_id = ?", (old_id,)).fetchone()
    if item is not None:
        previous = _row_dict(item)
        conn.execute("UPDATE memory_items SET status = 'hidden', updated_at_ms = ? WHERE memory_id = ?", (now_ms(), old_id))
        return {
            "table": "memory_items",
            "pk": "memory_id",
            "pkValue": old_id,
            "previous": previous,
            "supersession": relation_rollback,
        }
    conn.execute(
        "DELETE FROM memory_supersessions WHERE supersession_id = ?",
        (str(relation_rollback["pkValue"]),),
    )
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


def _sync_semantic_group_members(
    conn: sqlite3.Connection,
    *,
    member_type: str,
    member_id: str,
    group_ids: list[str],
) -> dict[str, object]:
    previous = [
        dict(row)
        for row in conn.execute(
            """
            SELECT group_id, member_type, member_id, weight, source, updated_at_ms
            FROM memory_semantic_group_members
            WHERE member_type = ? AND member_id = ?
            """,
            (member_type, member_id),
        ).fetchall()
    ]
    conn.execute(
        "DELETE FROM memory_semantic_group_members WHERE member_type = ? AND member_id = ?",
        (member_type, member_id),
    )
    timestamp = now_ms()
    for group_id in dict.fromkeys(_strings(group_ids)):
        if conn.execute(
            "SELECT 1 FROM memory_semantic_groups WHERE group_id = ? AND status = 'active'",
            (group_id,),
        ).fetchone() is None:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_semantic_group_members(
                group_id, member_type, member_id, weight, source, updated_at_ms
            ) VALUES (?, ?, ?, 0.8, 'dsv4', ?)
            """,
            (group_id, member_type, member_id, timestamp),
        )
    return {
        "semanticMemberType": member_type,
        "semanticMemberId": member_id,
        "previousSemanticGroupMembers": previous,
    }


def _restore_semantic_group_members(conn: sqlite3.Connection, rollback: dict[str, object]) -> None:
    member_type = compact_whitespace(str(rollback.get("semanticMemberType") or ""))
    member_id = compact_whitespace(str(rollback.get("semanticMemberId") or ""))
    if not member_type or not member_id:
        return
    conn.execute(
        "DELETE FROM memory_semantic_group_members WHERE member_type = ? AND member_id = ?",
        (member_type, member_id),
    )
    for row in _list_of_dicts(rollback.get("previousSemanticGroupMembers")):
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_semantic_group_members(
                group_id, member_type, member_id, weight, source, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(row.get("group_id") or ""),
                str(row.get("member_type") or member_type),
                str(row.get("member_id") or member_id),
                _bounded_float(row.get("weight"), default=0.8),
                str(row.get("source") or "dsv4"),
                int(row.get("updated_at_ms") or now_ms()),
            ),
        )


def _ensure_tag(conn: sqlite3.Connection, tag: str, *, source: str = "dsv4") -> int:
    value = compact_whitespace(tag)
    row = conn.execute(
        "SELECT id FROM memory_tags WHERE tag = ? OR normalized_tag = ? "
        "ORDER BY CASE WHEN tag = ? THEN 0 ELSE 1 END, quality_score DESC LIMIT 1",
        (value, normalize_text(value), value),
    ).fetchone()
    if row is not None:
        tag_id = int(row["id"])
        if source == "dsv4":
            conn.execute(
                """
                UPDATE memory_tags
                SET source = CASE WHEN source = 'user' THEN 'user' ELSE 'dsv4' END,
                    status = 'active', updated_at_ms = ?
                WHERE id = ?
                """,
                (now_ms(), tag_id),
            )
        return tag_id
    cur = conn.execute(
        """
        INSERT INTO memory_tags(
            tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms,
            description, source, status, metadata_json
        )
        VALUES (?, ?, 'concept', 0.6, ?, ?, '', ?, 'active', '{}')
        """,
        (value, normalize_text(value), now_ms(), now_ms(), source),
    )
    return int(cur.lastrowid)


def _sync_run_status(conn: sqlite3.Connection, run_id: str) -> None:
    rows = conn.execute("SELECT status FROM memory_cleanup_diffs WHERE run_id = ?", (run_id,)).fetchall()
    statuses = {str(row["status"]) for row in rows}
    effective_statuses = statuses - {"rejected"}
    if not statuses:
        status = "empty"
    elif not effective_statuses:
        status = "draft"
    elif effective_statuses == {"applied"}:
        status = "applied"
    elif effective_statuses == {"rolled_back"}:
        status = "rolled_back"
    elif "applied" in effective_statuses:
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
    semantic_group_ids: list[str] = []
    for payload in atom_payloads:
        if not isinstance(payload, dict):
            continue
        for event_id in _positive_ints(payload.get("sourceEventIds")):
            if event_id not in source_ids:
                source_ids.append(event_id)
        tags.extend(_strings(payload.get("tags")))
        hints.extend(_strings(payload.get("surfaceHints")))
        semantic_group_ids.extend(_strings(payload.get("semanticGroupIds")))
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
        "title": f"本地记忆归档 {book_key}",
        "summary": (
            f"按来源事件归档 {len(source_ids)} 条记录，保留 {len(atom_payloads)} 个去重记忆项。"
        ),
        "tags": _unique_strings(tags, limit=8),
        "surfaceHints": unique_hints[:3],
        "queryExpansions": [],
        "sourceEventIds": source_ids[:10],
        "memoryAtomIds": atom_ids,
        "semanticGroupIds": _unique_strings(semantic_group_ids, limit=4),
        "project": project,
        "app": "",
        "confidence": 0.6,
        "qualityScore": 0.6,
        "status": "active",
    }
    return {"op": "upsert_memory_book", "targetId": book_id, "payload": payload, "status": "pending"}


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
        event_ids = _positive_ints(item.get("sourceEventIds") or [item.get("eventId")])
        if not event_ids:
            continue
        committed_text = compact_whitespace(str(item.get("text") or ""))
        recent_context = compact_whitespace(str(item.get("recentContext") or ""))
        tags = _strings(item.get("tags"))
        text = compact_whitespace(
            " ".join(
                [
                    committed_text,
                    recent_context,
                    " ".join(tags),
                    str(item.get("app") or ""),
                    str(item.get("project") or ""),
                    str(item.get("source") or ""),
                ]
            )
        )
        events.append(
            {
                "eventId": event_ids[0],
                "sourceEventIds": event_ids,
                "createdAtMs": _optional_int(item.get("createdAtMs")),
                "text": text,
                "committedText": committed_text,
                "recentContext": recent_context,
                "tags": tags,
                "contextGroupId": compact_whitespace(str(item.get("contextGroupId") or "")),
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
    counts = {
        "分组": sum(1 for item in diffs if item.get("op") == "upsert_semantic_group"),
        "标签": sum(1 for item in diffs if item.get("op") == "upsert_semantic_tag"),
        "主题": sum(1 for item in diffs if item.get("op") == "upsert_memory_book"),
        "记忆": sum(1 for item in diffs if item.get("op") == "upsert_memory_atom"),
        "标签关系": sum(1 for item in diffs if item.get("op") == "upsert_tag_edge"),
        "标签合并": sum(1 for item in diffs if item.get("op") == "merge_semantic_tag"),
        "词表提案": sum(1 for item in diffs if item.get("op") == "add_phrase_candidate"),
    }
    visible = [f"{label} {count}" for label, count in counts.items() if count]
    return "；".join(visible) if visible else "没有生成可入库的高置信变更"


def _sanitize_text(text: str, *, max_chars: int) -> tuple[str, dict[str, int]]:
    counts = _empty_redaction_counts()
    value = text or ""
    value, private_key_count = _PRIVATE_KEY_RE.subn("[REDACTED_SECRET]", value)
    counts["secret"] += private_key_count
    value, url_secret_count = _URL_SECRET_QUERY_RE.subn(
        lambda match: f"{match.group('separator')}[REDACTED_SECRET]",
        value,
    )
    counts["secret"] += url_secret_count
    value, assignment_count = _CREDENTIAL_ASSIGNMENT_RE.subn("[REDACTED_SECRET]", value)
    counts["secret"] += assignment_count
    value = compact_whitespace(value)
    value, counts["identity"] = _IDENTITY_RE.subn("[REDACTED_IDENTITY]", value)
    value, counts["phone"] = _PHONE_RE.subn("[REDACTED_PHONE]", value)
    value, counts["paymentCard"] = _PAYMENT_CARD_RE.subn("[REDACTED_PAYMENT_CARD]", value)
    value, counts["path"] = _PATH_RE.subn("[REDACTED_PATH]", value)
    value, counts["email"] = _EMAIL_RE.subn("[REDACTED_EMAIL]", value)
    value, ip_count = _redact_ip_addresses(value)
    counts["ipAddress"] += ip_count
    value, bare_secret_count = _SECRET_RE.subn("[REDACTED_SECRET]", value)
    counts["secret"] += bare_secret_count
    return truncate_text(value, max_chars), counts


def _empty_redaction_counts() -> dict[str, int]:
    return {
        "secret": 0,
        "path": 0,
        "email": 0,
        "phone": 0,
        "identity": 0,
        "paymentCard": 0,
        "ipAddress": 0,
    }


def _redact_ip_addresses(text: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        candidate = match.group(0)
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        count += 1
        return "[REDACTED_IP]"

    value = _IPV4_CANDIDATE_RE.sub(replace, text)
    value = _IPV6_CANDIDATE_RE.sub(replace, value)
    return value, count


def _contains_sensitive_text(text: str) -> bool:
    value = text or ""
    if any(
        pattern.search(value)
        for pattern in (
            _PRIVATE_KEY_RE,
            _URL_SECRET_QUERY_RE,
            _CREDENTIAL_ASSIGNMENT_RE,
            _SECRET_RE,
            _PHONE_RE,
            _IDENTITY_RE,
            _PAYMENT_CARD_RE,
            _PATH_RE,
            _EMAIL_RE,
        )
    ):
        return True
    _, count = _redact_ip_addresses(value)
    return count > 0


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value)


def _json_list(raw: object) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return _strings(parsed)


def _json_object(raw: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in value or [] if isinstance(item, dict)]


def _planned_tag_merges(
    compile_output: dict[str, object],
    *,
    source_bundle: dict[str, object] | None,
) -> list[dict[str, object]]:
    existing = _list_of_dicts((source_bundle or {}).get("existingSemanticTags"))
    canonical_by_name: dict[str, str] = {}
    aliases_by_name: dict[str, list[str]] = {}
    for item in existing:
        name = compact_whitespace(str(item.get("name") or ""))
        normalized = normalize_text(name)
        if not normalized:
            continue
        canonical_by_name.setdefault(normalized, name)
        aliases_by_name[name] = _strings(item.get("aliases"))
    proposed_names = {
        normalize_text(str(item.get("name") or item.get("tag") or ""))
        for item in _list_of_dicts(compile_output.get("semanticTags"))
        if normalize_text(str(item.get("name") or item.get("tag") or ""))
    }

    merges: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    merge_target_by_source: dict[str, str] = {}

    def add_merge(
        source: object,
        target: object,
        *,
        reason: object,
        evidence_event_ids: object = None,
        confidence: object = 0.8,
    ) -> None:
        source_name = compact_whitespace(str(source or ""))
        target_name = compact_whitespace(str(target or ""))
        source_norm = normalize_text(source_name)
        target_norm = normalize_text(target_name)
        if not source_norm or not target_norm:
            return
        target_name = canonical_by_name.get(target_norm, target_name)
        target_norm = normalize_text(target_name)
        if source_norm == target_norm or source_norm in seen_sources:
            return
        if target_norm not in canonical_by_name and target_norm not in proposed_names:
            return
        cursor = target_norm
        visited: set[str] = set()
        while cursor and cursor not in visited:
            if cursor == source_norm:
                return
            visited.add(cursor)
            cursor = merge_target_by_source.get(cursor, "")
        seen_sources.add(source_norm)
        merge_target_by_source[source_norm] = target_norm
        merges.append(
            {
                "source": source_name,
                "target": target_name,
                "reason": compact_whitespace(str(reason or "同义标签规范化")),
                "evidenceEventIds": _positive_ints(evidence_event_ids),
                "confidence": _bounded_float(confidence, default=0.8),
                "requiresApply": source_norm in canonical_by_name,
            }
        )

    for item in _list_of_dicts(compile_output.get("tagMerges")):
        add_merge(
            item.get("source") or item.get("from"),
            item.get("target") or item.get("into"),
            reason=item.get("reason"),
            evidence_event_ids=item.get("evidenceEventIds"),
            confidence=item.get("confidence"),
        )

    # Exact normalized-name and declared-alias overlap is deterministic enough
    # to propose a reviewable merge. It never mutates the formal graph here.
    for item in existing:
        name = compact_whitespace(str(item.get("name") or ""))
        canonical = canonical_by_name.get(normalize_text(name), name)
        if canonical and canonical != name:
            add_merge(name, canonical, reason="规范化名称重复", confidence=0.98)
    for target_name, aliases in aliases_by_name.items():
        for alias in aliases:
            existing_alias = canonical_by_name.get(normalize_text(alias))
            if existing_alias and normalize_text(existing_alias) != normalize_text(target_name):
                add_merge(existing_alias, target_name, reason="已有标签别名重合", confidence=0.95)
    for item in _list_of_dicts(compile_output.get("semanticTags")):
        name = compact_whitespace(str(item.get("name") or item.get("tag") or ""))
        for candidate in [name, *_strings(item.get("aliases"))]:
            existing_name = canonical_by_name.get(normalize_text(candidate))
            if existing_name and normalize_text(name) != normalize_text(existing_name):
                add_merge(
                    name,
                    existing_name,
                    reason="本批标签与已有规范标签或别名重合",
                    evidence_event_ids=item.get("sourceEventIds"),
                    confidence=item.get("confidence"),
                )
                break
    return merges


def _canonical_tag_name(value: str, mapping: dict[str, str]) -> str:
    current = compact_whitespace(value)
    visited: set[str] = set()
    while current:
        normalized = normalize_text(current)
        if not normalized or normalized in visited:
            break
        visited.add(normalized)
        target = compact_whitespace(mapping.get(normalized, ""))
        if not target or normalize_text(target) == normalized:
            break
        current = target
    return current


def _canonical_tag_names(values: list[str], mapping: dict[str, str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        canonical = _canonical_tag_name(value, mapping)
        normalized = normalize_text(canonical)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(canonical)
    return result


def _canonical_tag_aliases(name: str, aliases: list[str], mapping: dict[str, str]) -> list[str]:
    name_normalized = normalize_text(name)
    return _unique_strings(
        [alias for alias in aliases if normalize_text(alias) and normalize_text(alias) != name_normalized],
        limit=24,
    )


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


def _optional_positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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
    apply_database_migrations(conn)


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


def _source_feedback(
    conn: sqlite3.Connection,
    *,
    event_ids: list[int],
    project: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    if not event_ids:
        return [], _empty_redaction_counts()
    rows = conn.execute(
        """
        SELECT action, candidate_id, candidate_text, candidate_source, raw_input,
               preedit, committed_tail, created_at_ms, metadata_json
        FROM memory_feedback_events
        ORDER BY created_at_ms DESC
        LIMIT 80
        """
    ).fetchall()
    wanted_event_ids = set(event_ids)
    result: list[dict[str, object]] = []
    redaction_stats = _empty_redaction_counts()
    for row in rows:
        metadata = _json_object(row["metadata_json"])
        metadata_project = compact_whitespace(str(metadata.get("project") or ""))
        if project and metadata_project and metadata_project != project:
            continue
        source_event_id = _optional_positive_int(metadata.get("sourceEventId"))
        if source_event_id and source_event_id not in wanted_event_ids:
            continue
        text, text_counts = _sanitize_text(str(row["candidate_text"] or ""), max_chars=100)
        raw_input, raw_counts = _sanitize_text(str(row["raw_input"] or ""), max_chars=80)
        preedit, preedit_counts = _sanitize_text(str(row["preedit"] or ""), max_chars=80)
        committed_tail, tail_counts = _sanitize_text(str(row["committed_tail"] or ""), max_chars=180)
        selected_text, selected_counts = _sanitize_text(str(metadata.get("selectedText") or ""), max_chars=100)
        for counts in (text_counts, raw_counts, preedit_counts, tail_counts, selected_counts):
            _merge_counts(redaction_stats, counts)
        result.append(
            {
                "action": str(row["action"] or ""),
                "candidateId": _sanitize_text(str(row["candidate_id"] or ""), max_chars=120)[0],
                "text": text,
                "source": str(row["candidate_source"] or ""),
                "rawInput": raw_input,
                "preedit": preedit,
                "committedTail": committed_tail,
                "selectedText": selected_text,
                "selectedRank": _optional_positive_int(metadata.get("selectedRank")) or 0,
                "deleteCount": _optional_positive_int(metadata.get("deleteCount")) or 0,
                "sourceEventId": source_event_id,
                "createdAtMs": int(row["created_at_ms"] or 0),
            }
        )
    return result, redaction_stats


def _source_rime_rank_feedback(
    conn: sqlite3.Connection,
    *,
    project: str,
    cutoff_ms: int,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    rows = conn.execute(
        """
        SELECT preedit, rejected_text, accepted_text, action, app, project,
               candidate_rank, created_at_ms, metadata_json
        FROM rime_rank_feedback
        WHERE created_at_ms >= ?
          AND (? = '' OR project = ? OR project = '')
        ORDER BY created_at_ms DESC, id DESC
        LIMIT 80
        """,
        (cutoff_ms, project, project),
    ).fetchall()
    result: list[dict[str, object]] = []
    redaction_stats = _empty_redaction_counts()
    for row in rows:
        preedit, preedit_counts = _sanitize_text(str(row["preedit"] or ""), max_chars=80)
        rejected, rejected_counts = _sanitize_text(str(row["rejected_text"] or ""), max_chars=100)
        accepted, accepted_counts = _sanitize_text(str(row["accepted_text"] or ""), max_chars=100)
        app, app_counts = _sanitize_text(str(row["app"] or ""), max_chars=120)
        for counts in (preedit_counts, rejected_counts, accepted_counts, app_counts):
            _merge_counts(redaction_stats, counts)
        result.append(
            {
                "action": str(row["action"] or ""),
                "preedit": preedit,
                "rejectedText": rejected,
                "acceptedText": accepted,
                "candidateRank": int(row["candidate_rank"] or 0),
                "app": app,
                "createdAtMs": int(row["created_at_ms"] or 0),
            }
        )
    return result, redaction_stats


def _existing_book_summaries(conn: sqlite3.Connection, *, project: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT book_id, book_type, book_key, title, summary, tags_json,
               source_event_ids_json, memory_atom_ids_json, status,
               updated_at_ms, archived_at_ms, metadata_json
        FROM memory_books
        WHERE status IN ('active', 'approved', 'archived')
          AND (? = '' OR project = ? OR project = '')
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                 updated_at_ms DESC
        LIMIT 48
        """,
        (project, project),
    ).fetchall()
    return [
        {
            "bookId": str(row["book_id"] or ""),
            "bookType": str(row["book_type"] or ""),
            "bookKey": str(row["book_key"] or ""),
            "title": _sanitize_text(str(row["title"] or ""), max_chars=80)[0],
            "summary": _sanitize_text(str(row["summary"] or ""), max_chars=180)[0],
            "tags": [_sanitize_text(tag, max_chars=48)[0] for tag in _json_list(row["tags_json"])],
            "sourceEventIds": _json_list(row["source_event_ids_json"]),
            "memoryAtomIds": _json_list(row["memory_atom_ids_json"]),
            "status": str(row["status"] or "active"),
            "updatedAtMs": int(row["updated_at_ms"] or 0),
            "archivedAtMs": int(row["archived_at_ms"] or 0),
        }
        for row in rows
    ]


def _existing_memory_atom_summaries(
    conn: sqlite3.Connection,
    *,
    project: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, kind, canonical_text, scope_project, scope_app, claim_key,
               lineage_id, claim_state, valid_from_ms, valid_to_ms,
               source_event_ids_json, status, updated_at_ms
        FROM memory_atoms
        WHERE status IN ('active', 'approved')
          AND claim_state = 'current'
          AND privacy_level != 'sensitive'
          AND (? = '' OR scope_project = ? OR scope_project = '')
        ORDER BY updated_at_ms DESC
        LIMIT 96
        """,
        (project, project),
    ).fetchall()
    return [
        {
            "atomId": str(row["id"] or ""),
            "kind": str(row["kind"] or ""),
            "canonicalText": _sanitize_text(
                str(row["canonical_text"] or ""),
                max_chars=220,
            )[0],
            "project": str(row["scope_project"] or ""),
            "app": str(row["scope_app"] or ""),
            "claimKey": str(row["claim_key"] or ""),
            "lineageId": str(row["lineage_id"] or ""),
            "claimState": str(row["claim_state"] or "current"),
            "validFromMs": int(row["valid_from_ms"] or 0),
            "validToMs": int(row["valid_to_ms"]) if row["valid_to_ms"] is not None else None,
            "sourceEventIds": _json_list(row["source_event_ids_json"]),
            "status": str(row["status"] or "active"),
            "updatedAtMs": int(row["updated_at_ms"] or 0),
        }
        for row in rows
    ]


def _match_existing_topic_book(
    item: dict[str, object],
    *,
    source_bundle: dict[str, object] | None,
) -> dict[str, object] | None:
    existing = _list_of_dicts((source_bundle or {}).get("existingMemoryBooks"))
    if not existing:
        return None
    requested_id = compact_whitespace(str(item.get("bookId") or ""))
    requested_key = compact_whitespace(str(item.get("bookKey") or ""))
    for candidate in existing:
        if requested_id and requested_id == compact_whitespace(str(candidate.get("bookId") or "")):
            return candidate
        if requested_key and requested_key == compact_whitespace(str(candidate.get("bookKey") or "")):
            return candidate

    title = compact_whitespace(str(item.get("title") or ""))
    summary = compact_whitespace(str(item.get("summary") or ""))
    tags = _strings(item.get("tags"))
    ranked = sorted(
        ((_topic_book_similarity(title, summary, tags, candidate), candidate) for candidate in existing),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.52:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08 and ranked[0][0] < 0.82:
        return None
    return ranked[0][1]


def _topic_book_similarity(
    title: str,
    summary: str,
    tags: list[str],
    candidate: dict[str, object],
) -> float:
    current_title = normalize_text(title)
    previous_title = normalize_text(str(candidate.get("title") or ""))
    if current_title and current_title == previous_title:
        return 1.0
    if current_title and previous_title and (
        current_title in previous_title or previous_title in current_title
    ):
        title_score = 0.82
    else:
        current_terms = _topic_terms(" ".join([title, summary, *tags]))
        previous_terms = _topic_terms(
            " ".join(
                [
                    str(candidate.get("title") or ""),
                    str(candidate.get("summary") or ""),
                    *_strings(candidate.get("tags")),
                ]
            )
        )
        title_terms = _topic_terms(title)
        previous_title_terms = _topic_terms(str(candidate.get("title") or ""))
        title_score = _jaccard(title_terms, previous_title_terms)
        content_score = _jaccard(current_terms, previous_terms)
        current_tags = {normalize_text(value) for value in tags if normalize_text(value)}
        previous_tags = {
            normalize_text(value)
            for value in _strings(candidate.get("tags"))
            if normalize_text(value)
        }
        tag_score = _jaccard(current_tags, previous_tags)
        return 0.50 * title_score + 0.35 * content_score + 0.15 * tag_score
    current_tags = {normalize_text(value) for value in tags if normalize_text(value)}
    previous_tags = {
        normalize_text(value)
        for value in _strings(candidate.get("tags"))
        if normalize_text(value)
    }
    return min(1.0, title_score + 0.10 * _jaccard(current_tags, previous_tags))


def _topic_terms(text: str) -> set[str]:
    value = normalize_text(text)
    terms = {normalize_text(term) for term in token_terms(text, max_terms=80) if normalize_text(term)}
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", value))
    if len(cjk) == 1:
        terms.add(cjk)
    elif len(cjk) >= 2:
        terms.update(cjk[index : index + 2] for index in range(len(cjk) - 1))
    return terms


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def _existing_semantic_groups(conn: sqlite3.Connection, *, project: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT group_id, title, description, aliases_json, tags_json, source_event_ids_json
        FROM memory_semantic_groups
        WHERE status = 'active' AND (? = '' OR project = ? OR project = '')
        ORDER BY quality_score DESC, updated_at_ms DESC
        LIMIT 24
        """,
        (project, project),
    ).fetchall()
    return [
        {
            "groupId": str(row["group_id"] or ""),
            "title": _sanitize_text(str(row["title"] or ""), max_chars=48)[0],
            "description": _sanitize_text(str(row["description"] or ""), max_chars=160)[0],
            "aliases": [_sanitize_text(item, max_chars=32)[0] for item in _json_list(row["aliases_json"])],
            "tags": [_sanitize_text(item, max_chars=32)[0] for item in _json_list(row["tags_json"])],
            "sourceEventIds": _json_list(row["source_event_ids_json"]),
        }
        for row in rows
    ]


def _existing_semantic_tags(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT mt.id, mt.tag, mt.description, mt.tag_type, mt.quality_score, mt.metadata_json,
               COALESCE(mtp.aliases_json, '[]') AS aliases_json,
               (SELECT COUNT(*) FROM memory_tag_edges edge
                WHERE edge.src_tag_id = mt.id OR edge.dst_tag_id = mt.id) AS degree
        FROM memory_tags mt
        LEFT JOIN memory_tag_profiles mtp ON mtp.tag_id = mt.id
        WHERE mt.status = 'active' AND mt.source IN ('dsv4', 'user')
        ORDER BY mt.quality_score DESC, mt.updated_at_ms DESC
        LIMIT 160
        """
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        metadata = _json_object(row["metadata_json"])
        result.append(
            {
                "tagId": int(row["id"]),
                "name": _sanitize_text(str(row["tag"] or ""), max_chars=32)[0],
                "description": _sanitize_text(str(row["description"] or ""), max_chars=120)[0],
                "type": str(row["tag_type"] or "concept"),
                "aliases": [_sanitize_text(item, max_chars=32)[0] for item in _json_list(row["aliases_json"])],
                "semanticGroupIds": [
                    str(member[0])
                    for member in conn.execute(
                        "SELECT group_id FROM memory_semantic_group_members "
                        "WHERE member_type = 'tag' AND member_id = ? ORDER BY weight DESC LIMIT 4",
                        (str(row["id"]),),
                    ).fetchall()
                ],
                "degree": int(row["degree"] or 0),
                "qualityScore": float(row["quality_score"] or 0.0),
                "sourceEventIds": _positive_ints(metadata.get("sourceEventIds")),
            }
        )
    return result


def _existing_semantic_tag_edges(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT src.tag AS src, dst.tag AS dst, edge.edge_type, edge.weight, edge.evidence_count
        FROM memory_tag_edges edge
        JOIN memory_tags src ON src.id = edge.src_tag_id
        JOIN memory_tags dst ON dst.id = edge.dst_tag_id
        WHERE src.status = 'active' AND dst.status = 'active'
          AND src.source IN ('dsv4', 'user')
          AND dst.source IN ('dsv4', 'user')
        ORDER BY edge.weight DESC, edge.evidence_count DESC, edge.updated_at_ms DESC
        LIMIT 240
        """
    ).fetchall()
    return [
        {
            "src": _sanitize_text(str(row["src"] or ""), max_chars=32)[0],
            "dst": _sanitize_text(str(row["dst"] or ""), max_chars=32)[0],
            "edgeType": str(row["edge_type"] or "related_to"),
            "weight": float(row["weight"] or 0.0),
            "evidenceCount": int(row["evidence_count"] or 0),
        }
        for row in rows
    ]


def _group_for_source_ids(source_ids: list[int], *, source_bundle: dict[str, object] | None) -> str:
    if not source_bundle:
        return ""
    wanted = set(source_ids)
    for event in _list_of_dicts(source_bundle.get("recentEvents")):
        event_ids = set(_positive_ints(event.get("sourceEventIds") or [event.get("eventId")]))
        group_id = compact_whitespace(str(event.get("contextGroupId") or ""))
        if wanted.intersection(event_ids) and group_id:
            return group_id
    return ""


def _legal_source_event_ids(source_bundle: dict[str, object] | None) -> list[int]:
    if not source_bundle:
        return []
    result: list[int] = []
    for event in _list_of_dicts(source_bundle.get("recentEvents")):
        for event_id in _positive_ints(event.get("sourceEventIds") or [event.get("eventId")]):
            if event_id not in result:
                result.append(event_id)
    for collection_name in (
        "existingMemoryBooks",
        "existingMemoryAtoms",
        "existingSemanticGroups",
        "existingSemanticTags",
    ):
        for item in _list_of_dicts(source_bundle.get(collection_name)):
            for event_id in _positive_ints(item.get("sourceEventIds")):
                if event_id not in result:
                    result.append(event_id)
    return result


def _semantic_group_id(value: object, *, title: str) -> str:
    raw = compact_whitespace(str(value or "")).lower()
    if raw.startswith("group:") and re.fullmatch(r"group:[a-z0-9][a-z0-9._-]{1,63}", raw):
        return raw
    digest = stable_text_hash(normalize_text(title)).removeprefix("sha256:")[:16]
    return f"group:topic-{digest}"


def _normalized_claim_key(value: object) -> str:
    raw = compact_whitespace(str(value or "")).lower()
    if not raw:
        return ""
    raw = re.sub(r"\s+", "-", raw)
    if len(raw) > 160:
        return ""
    if not re.fullmatch(r"[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff._:/-]*", raw):
        return ""
    return raw


def _latest_source_event_ms(
    source_ids: list[int],
    *,
    source_bundle: dict[str, object] | None,
) -> int:
    if not source_bundle:
        return 0
    wanted = set(source_ids)
    values = [
        _optional_int(event.get("createdAtMs"))
        for event in _list_of_dicts(source_bundle.get("recentEvents"))
        if wanted.intersection(
            _positive_ints(event.get("sourceEventIds") or [event.get("eventId")])
        )
    ]
    return max(values, default=0)


def _semantic_group_ids(item: dict[str, object]) -> list[str]:
    values = item.get("semanticGroupIds")
    if values is None:
        values = item.get("groupIds")
    return [
        value.lower()
        for value in _strings(values)
        if re.fullmatch(r"group:[a-z0-9][a-z0-9._-]{1,63}", value.lower())
    ][:4]


def _resolved_semantic_group_ids(
    item: dict[str, object],
    *,
    source_ids: list[int],
    group_source_ids: dict[str, list[int]],
) -> list[str]:
    explicit = _semantic_group_ids(item)
    if explicit or not source_ids or not group_source_ids:
        return explicit

    wanted = set(source_ids)
    scored = [
        (len(wanted.intersection(event_ids)), group_id)
        for group_id, event_ids in group_source_ids.items()
    ]
    overlap, group_id = max(scored, default=(0, ""))
    return [group_id] if overlap > 0 and group_id else []


def _normalized_rime_pinyin(value: object) -> str:
    pinyin = " ".join(compact_whitespace(str(value or "")).lower().split())
    return pinyin if _RIME_PINYIN_RE.fullmatch(pinyin) else ""


def _validate_required_text(errors: list[dict[str, object]], index: int, op: str, payload: dict[str, object], field: str) -> None:
    if not compact_whitespace(str(payload.get(field) or "")):
        errors.append(_issue(index, op, field, "required"))


def _validate_source_ids(
    errors: list[dict[str, object]],
    index: int,
    op: str,
    value: object,
    *,
    field: str = "sourceEventIds",
    legal_source_event_ids: set[int] | None = None,
) -> None:
    source_ids = _positive_ints(value)
    if not source_ids:
        errors.append(_issue(index, op, field, "missing_source_event_ids"))
        return
    legal_ids = legal_source_event_ids or set()
    unknown_ids = [source_id for source_id in source_ids if legal_ids and source_id not in legal_ids]
    if unknown_ids:
        errors.append(
            _issue(
                index,
                op,
                field,
                "source_event_not_in_bundle",
                preview=",".join(str(source_id) for source_id in unknown_ids[:8]),
            )
        )


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
            if _contains_sensitive_text(value):
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
