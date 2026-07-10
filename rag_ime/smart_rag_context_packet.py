from __future__ import annotations

import uuid
from typing import Iterable, Mapping, Sequence

from .active_rag_models import ActiveRagEvidence
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
    intent: str = "complete",
    placement: str = "insert_after_selection",
    max_candidates: int = 1,
    max_chars: int = 120,
    latency_budget_ms: int = 2500,
    remote_model_allowed: bool = True,
) -> dict[str, object]:
    context = compact_whitespace(current_context)
    selected = compact_whitespace(selected_text)
    evidence_items = tuple(evidence)
    notebook_items = [_notebook_item(item) for item in evidence_items if _is_notebook_evidence(item)]
    timeline_items = [_timeline_item(item) for item in evidence_items if _is_timeline_evidence(item)]
    recent_items = [_one_ring_like_event(item) for item in evidence_items if _is_recent_input_evidence(item)]
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
        "priority": ["currentInput", "oneRing", "timeline", "notebook"],
        "currentInput": {
            "mode": scene,
            "committedTail": truncate_text(context or selected, 180),
            "selectedText": truncate_text(selected, 160) if scene == "active_rag" else "",
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
            "maxEvents": 20,
            "events": recent_items[:20],
            "negativeSignals": [],
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
            "openTasks": [],
            "expiresAtMs": now_ms() + 7 * 24 * 60 * 60 * 1000,
        },
        "outputContract": {
            "maxCandidates": max(1, int(max_candidates)),
            "minCandidateChars": 40 if int(max_chars) >= 80 else 2,
            "maxCandidateChars": max(4, int(max_chars)),
            "outputFormat": "candidate_json",
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
        },
    }


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


def _is_timeline_evidence(item: ActiveRagEvidence) -> bool:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    return bool(metadata.get("timelineContext")) or item.source_lane.startswith("timeline_")


def _is_recent_input_evidence(item: ActiveRagEvidence) -> bool:
    return item.source_type == "recent_input_context" or item.source_lane == "timeline_recent_input"


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


def _one_ring_like_event(item: ActiveRagEvidence) -> dict[str, object]:
    return {
        "type": "recent_input_context",
        "textHash": stable_text_hash(item.text),
        "textPreview": truncate_text(compact_whitespace(item.text), 80),
        "source": item.source_lane or item.source_type,
        "atMs": now_ms(),
    }


def _current_phase(items: list[dict[str, object]]) -> str:
    for item in items:
        text = compact_whitespace(str(item.get("text") or ""))
        if text:
            return truncate_text(text, 80)
    return ""
