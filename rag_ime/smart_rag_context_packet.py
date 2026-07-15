from __future__ import annotations

import uuid
from typing import Iterable, Mapping, Sequence

from .active_rag_models import ActiveRagEvidence
from .daily_planner import estimate_tokens
from .input_event_assembly import tail_for_token_budget
from .text_utils import compact_whitespace, now_ms, stable_text_hash, truncate_text


SMART_RAG_CONTEXT_PACKET_SCHEMA_VERSION = "rag-ime.smart-context-packet.v1"


def build_post_commit_context_packet(
    *,
    current_input: str,
    context_group_id: str,
    app: str,
    project: str,
    group_events: Sequence[Mapping[str, object]] = (),
    memory_books: Sequence[Mapping[str, object]] = (),
    tag_hints: Sequence[str] = (),
    surface_hints: Sequence[str] = (),
    negative_signals: Sequence[str] = (),
) -> dict[str, object]:
    """Build the only automatic online task: short post-commit suffix completion."""

    group_id = compact_whitespace(context_group_id)
    safe_group_events: list[dict[str, object]] = []
    for event in reversed(tuple(group_events)):
        event_group = compact_whitespace(str(event.get("contextGroupId") or group_id))
        if group_id and event_group and event_group != group_id:
            continue
        if bool(event.get("deleted")):
            continue
        text = truncate_text(compact_whitespace(str(event.get("text") or "")), 80)
        if not text:
            continue
        safe_group_events.append(
            {
                "text": text,
                "ageMs": max(0, int(event.get("ageMs") or 0)),
                "accepted": bool(event.get("accepted")),
            }
        )
        if len(safe_group_events) >= 2:
            break
    safe_books: list[dict[str, object]] = []
    for book in memory_books:
        safe_books.append(
            {
                "bookId": compact_whitespace(str(book.get("bookId") or book.get("id") or "")),
                "title": truncate_text(compact_whitespace(str(book.get("title") or "")), 60),
                "summary": truncate_text(compact_whitespace(str(book.get("summary") or "")), 140),
                "surfaceHints": _bounded_strings(book.get("surfaceHints"), limit=4, max_chars=18),
                "tags": _bounded_strings(book.get("tags"), limit=8, max_chars=24),
                "sourceEventIds": [
                    int(value)
                    for value in book.get("sourceEventIds", [])
                    if isinstance(value, int) and value > 0
                ][:8],
                "directCandidateAllowed": False,
            }
        )
        if len(safe_books) >= 2:
            break
    return {
        "schemaVersion": "rag-ime.post-commit-context-packet.v1",
        "currentInput": {
            "contextGroupId": group_id,
            "committedTail": truncate_text(compact_whitespace(current_input), 500),
            "app": compact_whitespace(app),
            "project": compact_whitespace(project),
        },
        "groupBuffer": list(reversed(safe_group_events)),
        "memoryBook": safe_books,
        "tagHints": _bounded_strings(tag_hints, limit=8, max_chars=24),
        "surfaceHints": _bounded_strings(surface_hints, limit=4, max_chars=18),
        "negativeSignals": _bounded_strings(negative_signals, limit=8, max_chars=24),
        "outputContract": {
            "task": "post_commit_suffix",
            "suffixOnly": True,
            "maxChars": 18,
            "candidateCount": 3,
            "noExplanation": True,
            "noContextEcho": True,
        },
    }


def _bounded_strings(values: object, *, limit: int, max_chars: int) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        text = truncate_text(compact_whitespace(str(value)), max_chars)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def build_active_rag_context_packet(
    *,
    scene: str,
    current_context: str,
    selected_text: str,
    selected_text_hash: str,
    frontend_revision: int,
    selection_epoch: int,
    panel_session_id: str,
    project: str,
    app: str,
    evidence: Iterable[ActiveRagEvidence],
    recent_input_history: Iterable[ActiveRagEvidence] = (),
    intent: str = "complete",
    placement: str = "insert_after_selection",
    max_candidates: int = 1,
    max_chars: int = 120,
    latency_budget_ms: int = 2500,
    remote_model_allowed: bool = True,
    context_token_budget: int = 4096,
    reserved_output_tokens: int = 1024,
    recent_input_baseline: int = 20,
    recent_input_maximum: int = 80,
) -> dict[str, object]:
    raw_context = compact_whitespace(current_context)
    selected = compact_whitespace(selected_text)
    token_budget = max(2048, int(context_token_budget))
    reserved_tokens = max(256, min(token_budget - 256, int(reserved_output_tokens)))
    available_tokens = max(256, token_budget - reserved_tokens)
    context = tail_for_token_budget(raw_context or selected, available_tokens)
    evidence_items = tuple(evidence)
    history_items = tuple(recent_input_history)
    raw_planning_items = [_planning_item(item) for item in evidence_items if _is_planning_evidence(item)]
    raw_notebook_items = [
        _notebook_item(item)
        for item in evidence_items
        if _is_notebook_evidence(item) and not _is_planning_evidence(item)
    ]
    raw_timeline_items = [_timeline_item(item) for item in evidence_items if _is_timeline_evidence(item)]
    raw_recent_items = _recent_input_items(
        (*evidence_items, *history_items),
        current_context=context,
        selected_text=selected,
    )
    remaining_tokens = max(0, available_tokens - estimate_tokens(context))
    planning_items, remaining_tokens = _take_budgeted_items(
        raw_planning_items,
        remaining_tokens=remaining_tokens,
        text_keys=("title", "detail"),
        limit=24,
    )
    recent_items, remaining_tokens = _take_budgeted_recent_items(
        raw_recent_items,
        remaining_tokens=remaining_tokens,
        limit=max(20, min(200, int(recent_input_maximum))),
    )
    rag_hints, remaining_tokens = _take_budgeted_items(
        _rag_evidence_hints(evidence_items),
        remaining_tokens=remaining_tokens,
        text_keys=("text",),
        limit=24,
    )
    selected_rag_ids = {str(item.get("evidenceId") or "") for item in rag_hints}
    notebook_items = [item for item in raw_notebook_items if str(item.get("id") or "") in selected_rag_ids]
    timeline_items = [item for item in raw_timeline_items if str(item.get("id") or "") in selected_rag_ids]
    rag_tokens = sum(estimate_tokens(str(item.get("text") or "")) for item in rag_hints)
    source_tokens = {
        "currentInput": estimate_tokens(context or selected),
        "recentCompleteInputs": sum(
            estimate_tokens(str(item.get("textPreview") or "")) for item in recent_items
        ),
        "plansAndTodos": sum(
            estimate_tokens(str(item.get("title") or item.get("notes") or ""))
            for item in planning_items
        ),
        "timeline": sum(
            estimate_tokens(str(item.get("text") or ""))
            for item in rag_hints
            if str(item.get("category") or "") == "timeline"
        ),
        "notebook": sum(
            estimate_tokens(str(item.get("text") or ""))
            for item in rag_hints
            if str(item.get("category") or "") == "notebook"
        ),
        "ragEvidence": rag_tokens,
    }
    packet_id = _packet_id(
        scene=scene,
        current_context=context,
        selected_text_hash=selected_text_hash,
        frontend_revision=frontend_revision,
        selection_epoch=selection_epoch,
        panel_session_id=panel_session_id,
    )
    return {
        "schemaVersion": SMART_RAG_CONTEXT_PACKET_SCHEMA_VERSION,
        "packetId": packet_id,
        "scene": scene,
        "priority": ["currentInput", "planning", "recentCompleteInputs", "timeline", "notebook"],
        "currentInput": {
            "mode": scene,
            "committedTail": context,
            "selectedText": truncate_text(selected, 600) if scene == "active_rag" else "",
            "selectedTextHash": selected_text_hash,
            "intent": compact_whitespace(intent),
            "placement": compact_whitespace(placement),
            "rawInput": "",
            "preedit": "",
            "app": compact_whitespace(app),
            "project": compact_whitespace(project),
            "frontendRevision": int(frontend_revision),
            "selectionEpoch": int(selection_epoch),
            "panelSessionId": compact_whitespace(panel_session_id),
            "deleteState": {"recentDeletedTextHashes": []},
        },
        "oneRing": {
            "role": "continuity_context",
            "maySupportIntent": True,
            "maySupportFacts": False,
            "baselineEvents": max(10, min(80, int(recent_input_baseline))),
            "maxEvents": max(20, min(200, int(recent_input_maximum))),
            "events": recent_items,
            "negativeSignals": [],
        },
        "planning": {
            "items": planning_items[:24],
            "openTasks": [item for item in planning_items if item.get("kind") == "todo"][:20],
            "longTermGoals": [item for item in planning_items if item.get("kind") == "goal"][:8],
        },
        "notebook": {
            "scope": {"project": compact_whitespace(project), "app": compact_whitespace(app)},
            "items": notebook_items[:12],
        },
        "timeline": {
            "project": compact_whitespace(project),
            "app": compact_whitespace(app),
            "timeWindow": "7d",
            "currentPhase": _current_phase(timeline_items),
            "recentDecisions": timeline_items[:5],
            "openTasks": [item for item in planning_items if item.get("kind") == "todo"][:20],
            "expiresAtMs": now_ms() + 7 * 24 * 60 * 60 * 1000,
        },
        "ragEvidenceHints": rag_hints,
        "outputContract": {
            "maxCandidates": max(1, int(max_candidates)),
            "minCandidateChars": 40 if int(max_chars) == 0 or int(max_chars) >= 80 else 2,
            "maxCandidateChars": max(0, int(max_chars)),
            "outputFormat": "candidate_document" if int(max_chars) == 0 else "candidate_json",
            "intent": compact_whitespace(intent),
            "placement": compact_whitespace(placement),
            "allowedPlacements": ["replace_selection", "insert_after_selection", "append_at_cursor", "show_only"],
            "requireSourceRefs": True,
            "requireConfidence": False,
        },
        "constraints": {
            "forbiddenTerms": ["下一步", "接下来", "根据上述", "可以进行", "可以继续"],
            "forbiddenHashes": [selected_text_hash] if selected_text_hash else [],
            "recentDeletedHashes": [],
            "tombstonedMemoryIds": [],
            "suppressedCandidateIds": [],
            "privacyMode": "redacted",
            "latencyBudgetMs": int(latency_budget_ms),
            "remoteModelAllowed": bool(remote_model_allowed),
        },
        "trace": {
            "packetId": packet_id,
            "evidenceCount": len(evidence_items),
            "notebookCount": len(notebook_items),
            "timelineCount": len(timeline_items),
            "oneRingEventCount": len(recent_items),
            "planningCount": len(planning_items),
            "tokenBudget": token_budget,
            "reservedOutputTokens": reserved_tokens,
            "availableContextTokens": available_tokens,
            "estimatedContextTokens": sum(
                source_tokens[key]
                for key in ("currentInput", "recentCompleteInputs", "plansAndTodos", "ragEvidence")
            ),
            "remainingContextTokens": remaining_tokens,
            "withinSoftBudget": remaining_tokens >= 0,
            "contextSourceCounts": {
                "recentInputs": len(recent_items),
                "plansAndTodos": len(planning_items),
                "timeline": len(timeline_items),
                "notebook": len(notebook_items),
                "ragEvidence": len(rag_hints),
            },
            "contextSourceTokens": source_tokens,
            "trimmedSourceCounts": {
                "recentInputs": max(0, len(raw_recent_items) - len(recent_items)),
                "plansAndTodos": max(0, len(raw_planning_items) - len(planning_items)),
                "ragEvidence": max(0, len(_rag_evidence_hints(evidence_items)) - len(rag_hints)),
            },
        },
    }


def _take_budgeted_recent_items(
    items: Sequence[dict[str, object]],
    *,
    remaining_tokens: int,
    limit: int,
) -> tuple[list[dict[str, object]], int]:
    selected_reversed: list[dict[str, object]] = []
    remaining = max(0, int(remaining_tokens))
    for item in reversed(items):
        text = compact_whitespace(str(item.get("textPreview") or ""))
        cost = estimate_tokens(text) + 2
        if not text or cost > remaining:
            continue
        selected_reversed.append(item)
        remaining -= cost
        if len(selected_reversed) >= max(0, int(limit)):
            break
    selected_reversed.reverse()
    return selected_reversed, remaining


def _take_budgeted_items(
    items: Sequence[dict[str, object]],
    *,
    remaining_tokens: int,
    text_keys: Sequence[str],
    limit: int,
) -> tuple[list[dict[str, object]], int]:
    selected: list[dict[str, object]] = []
    remaining = max(0, int(remaining_tokens))
    for item in items:
        text = compact_whitespace(" ".join(str(item.get(key) or "") for key in text_keys))
        cost = estimate_tokens(text) + 2
        if not text or cost > remaining:
            continue
        selected.append(item)
        remaining -= cost
        if len(selected) >= max(0, int(limit)):
            break
    return selected, remaining


def _rag_evidence_hints(evidence: Sequence[ActiveRagEvidence]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in evidence:
        if _is_recent_input_evidence(item) or _is_planning_evidence(item):
            continue
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        surface_hints = metadata.get("surfaceHints") if isinstance(metadata.get("surfaceHints"), list) else []
        text = compact_whitespace(
            " ".join(
                str(value)
                for value in (
                    *(surface_hints[:3]),
                    metadata.get("title"),
                    metadata.get("summary"),
                    item.preview,
                    item.text,
                )
                if compact_whitespace(str(value or ""))
            )
        )
        normalized = text.lower()
        if not text or normalized in seen:
            continue
        seen.add(normalized)
        category = "timeline" if _is_timeline_evidence(item) else ("notebook" if _is_notebook_evidence(item) else "rag")
        result.append(
            {
                "evidenceId": item.evidence_id,
                "sourceType": item.source_type,
                "sourceLane": item.source_lane,
                "category": category,
                "text": text,
            }
        )
    return result


def _packet_id(
    *,
    scene: str,
    current_context: str,
    selected_text_hash: str,
    frontend_revision: int,
    selection_epoch: int,
    panel_session_id: str,
) -> str:
    base = "|".join(
        (
            compact_whitespace(scene),
            stable_text_hash(current_context),
            selected_text_hash,
            str(int(frontend_revision)),
            str(int(selection_epoch)),
            compact_whitespace(panel_session_id),
        )
    )
    return f"pkt_{stable_text_hash(base).split(':', 1)[-1][:16]}_{uuid.uuid4().hex[:6]}"


def _is_notebook_evidence(item: ActiveRagEvidence) -> bool:
    return item.source_type in {"memory", "phrase"} or item.source_lane in {
        "bm25_tags",
        "tag_memo",
        "timeline_daily_book",
        "timeline_memory_book",
    }


def _is_planning_evidence(item: ActiveRagEvidence) -> bool:
    return item.source_type in {"daily_plan", "todo", "goal"} or item.source_lane.startswith("planning_")


def _is_timeline_evidence(item: ActiveRagEvidence) -> bool:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    return bool(metadata.get("timelineContext")) or item.source_lane.startswith("timeline_")


def _is_recent_input_evidence(item: ActiveRagEvidence) -> bool:
    return item.source_type == "recent_input_context" or item.source_lane == "timeline_recent_input"


def _recent_input_items(
    evidence: Sequence[ActiveRagEvidence],
    *,
    current_context: str,
    selected_text: str,
) -> list[dict[str, object]]:
    """Keep recent complete inputs separate from grounding evidence.

    The editable field remains the primary request. Recent inputs only restore
    continuity when IMK exposes a short cursor tail; they never increase the
    RAG evidence count or authorize factual claims.
    """

    current_values = {
        compact_whitespace(value).lower()
        for value in (current_context, selected_text)
        if compact_whitespace(value)
    }
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in evidence:
        if not _is_recent_input_evidence(item):
            continue
        text = truncate_text(compact_whitespace(item.text), 480)
        normalized = text.lower()
        if not text or normalized in current_values or normalized in seen:
            continue
        seen.add(normalized)
        result.append(_one_ring_like_event(item, text=text))
    return result[-80:]


def _notebook_item(item: ActiveRagEvidence) -> dict[str, object]:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    title = compact_whitespace(str(metadata.get("title") or metadata.get("bookTitle") or item.text))
    summary = compact_whitespace(str(metadata.get("summary") or item.preview or item.text))
    surface_hints = metadata.get("surfaceHints") if isinstance(metadata.get("surfaceHints"), list) else []
    return {
        "id": item.evidence_id,
        "kind": item.source_lane or item.source_type,
        "title": truncate_text(title, 80),
        "summary": truncate_text(summary, 100),
        "tags": list(item.tags[:8]),
        "surfaceHints": [truncate_text(compact_whitespace(str(value)), 32) for value in surface_hints[:6]],
        "sourceEventIds": list(item.evidence_event_ids[:8]),
        "confidence": item.confidence,
        "directCandidateAllowed": False,
    }


def _timeline_item(item: ActiveRagEvidence) -> dict[str, object]:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    text = compact_whitespace(str(metadata.get("summary") or metadata.get("title") or item.preview or item.text))
    return {
        "id": item.evidence_id,
        "text": truncate_text(text, 100),
        "source": item.source_lane or item.source_type,
        "tags": list(item.tags[:6]),
        "sourceEventIds": list(item.evidence_event_ids[:8]),
    }


def _one_ring_like_event(item: ActiveRagEvidence, *, text: str | None = None) -> dict[str, object]:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    preview = truncate_text(compact_whitespace(text if text is not None else item.text), 480)
    return {
        "type": "recent_input_context",
        "textHash": stable_text_hash(preview),
        "textPreview": preview,
        "source": item.source_lane or item.source_type,
        "sourceEventIds": list(item.evidence_event_ids[:32]),
        "atMs": int(metadata.get("createdAtMs") or now_ms()),
    }


def _planning_item(item: ActiveRagEvidence) -> dict[str, object]:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    title = compact_whitespace(str(metadata.get("title") or item.text or item.preview))
    return {
        "id": item.evidence_id,
        "kind": "todo" if item.source_type == "todo" else ("goal" if item.source_type == "goal" else "daily_plan"),
        "title": truncate_text(title, 240),
        "detail": truncate_text(compact_whitespace(str(metadata.get("summary") or item.preview)), 600),
        "status": compact_whitespace(str(metadata.get("status") or "")),
        "priority": int(metadata.get("priority") or 0),
        "source": item.source_lane or item.source_type,
    }


def _current_phase(items: list[dict[str, object]]) -> str:
    for item in items:
        text = compact_whitespace(str(item.get("text") or ""))
        if text:
            return truncate_text(text, 80)
    return ""
