from __future__ import annotations

from typing import Any

from .adapter import InputMethodAdapter, SuggestionRequest
from .core_client import CoreClient
from .history_context import build_prediction_context
from .models import (
    InputSuggestion,
    ModelPrediction,
    RimeCandidate,
    RimeContextSnapshot,
    SideCandidateDisplayItem,
)
from .payloads import model_prediction_to_payload, suggestion_to_payload
from .predictor import PredictionProvider
from .text_utils import compact_whitespace


RIME_SIDECAR_SCHEMA_VERSION = "rag-ime.rime-sidecar.v1"


def build_rime_sidecar_response(
    *,
    payload: dict[str, Any],
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    default_project: str = "wisdom-weasel-rag-ime",
) -> dict[str, object]:
    snapshot = parse_rime_context_payload(payload, default_project=default_project)
    semantic_query, query_basis = choose_semantic_query(snapshot)
    prediction_context = build_prediction_context(
        core,
        explicit_recent_context=snapshot.committed_context,
        project=snapshot.project or default_project,
    )
    if snapshot.max_side_candidates > 0:
        model_predictions = predictor.predict(
            current_input=semantic_query,
            recent_context=prediction_context,
            max_candidates=snapshot.max_side_candidates,
        )
        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input=semantic_query,
                recent_context=prediction_context,
                project=snapshot.project or default_project,
                top_k=snapshot.max_side_candidates,
            )
        )
    else:
        model_predictions = []
        suggestions = []
    display_candidates = merge_display_candidates(
        snapshot=snapshot,
        model_predictions=model_predictions,
        suggestions=suggestions,
    )
    return {
        "schemaVersion": RIME_SIDECAR_SCHEMA_VERSION,
        "sessionId": snapshot.session_id,
        "requestSeq": snapshot.request_seq,
        "project": snapshot.project or default_project,
        "rawInput": snapshot.raw_input,
        "preedit": snapshot.preedit,
        "commitTextPreview": snapshot.commit_text_preview,
        "committedContext": snapshot.committed_context,
        "semanticQuery": semantic_query,
        "queryBasis": query_basis,
        "historyContext": prediction_context,
        "latencyBudgetMs": snapshot.latency_budget_ms,
        "rimeContext": rime_context_to_payload(snapshot),
        "modelPredictions": [model_prediction_to_payload(item) for item in model_predictions],
        "ragCandidates": [suggestion_to_payload(item) for item in suggestions],
        "displayCandidates": [display_item_to_payload(item) for item in display_candidates],
        "selectionActions": {
            "rime": "select_rime_candidate",
            "side": "commit_side_candidate",
        },
        "mergePolicy": {
            "rimeFirst": True,
            "maxVisibleCandidates": snapshot.max_visible_candidates,
            "maxSideCandidates": snapshot.max_side_candidates,
            "rawPinyinFallback": query_basis == "rawInputFallback",
        },
    }


def parse_rime_context_payload(payload: dict[str, Any], *, default_project: str) -> RimeContextSnapshot:
    rime_context = payload.get("rimeContext") if isinstance(payload.get("rimeContext"), dict) else {}
    assert isinstance(rime_context, dict)
    candidates_source = rime_context.get("candidates", payload.get("rimeCandidates"))
    candidates = tuple(_parse_rime_candidates(candidates_source))
    select_keys = _string(rime_context.get("selectKeys") or payload.get("selectKeys"))
    if select_keys:
        candidates = tuple(
            RimeCandidate(
                text=item.text,
                label=item.label or (select_keys[index] if index < len(select_keys) else ""),
                comment=item.comment,
                index=item.index,
            )
            for index, item in enumerate(candidates)
        )
    return RimeContextSnapshot(
        session_id=_string(payload.get("sessionId")) or "default",
        request_seq=_bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1),
        raw_input=_string(payload.get("rawInput") or payload.get("currentInput")),
        preedit=_string(payload.get("preedit")),
        commit_text_preview=_string(payload.get("commitTextPreview") or rime_context.get("commitTextPreview")),
        committed_context=_string(payload.get("committedContext") or payload.get("recentContext")),
        project=_string(payload.get("project")) or default_project,
        candidates=candidates,
        highlighted_index=_bounded_int(
            rime_context.get("highlightedIndex", payload.get("highlightedIndex")),
            default=0,
            minimum=0,
            maximum=999,
        ),
        page=_bounded_int(rime_context.get("page", payload.get("page")), default=0, minimum=0, maximum=999),
        is_last_page=_bool(rime_context.get("isLastPage", payload.get("isLastPage")), default=True),
        latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=150, minimum=30, maximum=2000),
        max_visible_candidates=_bounded_int(payload.get("maxVisibleCandidates"), default=8, minimum=1, maximum=10),
        max_side_candidates=_bounded_int(payload.get("maxSideCandidates"), default=3, minimum=0, maximum=6),
    )


def choose_semantic_query(snapshot: RimeContextSnapshot) -> tuple[str, str]:
    commit_preview = compact_whitespace(snapshot.commit_text_preview)
    if commit_preview:
        return commit_preview, "commitTextPreview"
    candidate_text = compact_whitespace(" ".join(item.text for item in snapshot.candidates[:3] if item.text))
    if candidate_text:
        return candidate_text, "rimeCandidates"
    preedit = compact_whitespace(snapshot.preedit)
    raw_input = compact_whitespace(snapshot.raw_input)
    if preedit and preedit != raw_input:
        return preedit, "preedit"
    context = compact_whitespace(snapshot.committed_context)
    if context:
        return context[-240:], "committedContext"
    return raw_input, "rawInputFallback"


def merge_display_candidates(
    *,
    snapshot: RimeContextSnapshot,
    model_predictions: list[ModelPrediction],
    suggestions: list[InputSuggestion],
) -> list[SideCandidateDisplayItem]:
    max_visible = snapshot.max_visible_candidates
    display: list[SideCandidateDisplayItem] = []
    for index, candidate in enumerate(snapshot.candidates[:max_visible]):
        display.append(
            SideCandidateDisplayItem(
                label=_display_label(candidate.label, len(display)),
                text=candidate.text,
                insert_text=candidate.text,
                source_type="rime",
                selection_action="select_rime_candidate",
                source_index=index,
                comment=candidate.comment,
                rime_index=candidate.index,
            )
        )
    side_budget = min(snapshot.max_side_candidates, max(0, max_visible - len(display)))
    side_limit = min(side_budget, max(0, max_visible - len(display)), len(model_predictions))
    for prediction in model_predictions[:side_limit]:
        display.append(
            SideCandidateDisplayItem(
                label=_display_label("", len(display)),
                text=prediction.text,
                insert_text=prediction.text,
                source_type="model",
                selection_action="commit_side_candidate",
                source_index=prediction.rank - 1,
                comment=prediction.provider_name,
                metadata={
                    "providerName": prediction.provider_name,
                    "latencyMs": prediction.latency_ms,
                    "confidence": prediction.confidence,
                    **dict(prediction.metadata),
                },
            )
        )
    remaining_side_budget = max(0, side_budget - side_limit)
    remaining = min(remaining_side_budget, max(0, max_visible - len(display)))
    for index, suggestion in enumerate(suggestions[:remaining]):
        metadata = dict(suggestion.metadata)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label("", len(display)),
                text=suggestion.surface_text,
                insert_text=str(metadata.get("insert_text") or suggestion.surface_text),
                source_type="rag",
                selection_action="commit_side_candidate",
                source_index=index,
                comment=suggestion.suggestion_type,
                evidence_preview=suggestion.evidence_preview,
                suggestion_id=suggestion.suggestion_id,
                memory_id=str(metadata.get("memory_id") or suggestion.suggestion_id),
                source_event_id=suggestion.source_event_id,
                metadata=metadata,
            )
        )
    return display


def rime_context_to_payload(snapshot: RimeContextSnapshot) -> dict[str, object]:
    return {
        "candidates": [
            {
                "index": item.index,
                "label": item.label or _display_label("", index),
                "text": item.text,
                "comment": item.comment,
            }
            for index, item in enumerate(snapshot.candidates)
        ],
        "highlightedIndex": snapshot.highlighted_index,
        "page": snapshot.page,
        "isLastPage": snapshot.is_last_page,
    }


def display_item_to_payload(item: SideCandidateDisplayItem) -> dict[str, object]:
    return {
        "label": item.label,
        "text": item.text,
        "insertText": item.insert_text,
        "sourceType": item.source_type,
        "selectionAction": item.selection_action,
        "sourceIndex": item.source_index,
        "comment": item.comment,
        "evidencePreview": item.evidence_preview,
        "suggestionId": item.suggestion_id,
        "memoryId": item.memory_id,
        "sourceEventId": item.source_event_id,
        "rimeIndex": item.rime_index,
        "metadata": dict(item.metadata),
    }


def _parse_rime_candidates(value: object) -> list[RimeCandidate]:
    if not isinstance(value, list):
        return []
    candidates: list[RimeCandidate] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            text = item
            label = ""
            comment = ""
            rime_index = index
        elif isinstance(item, dict):
            text = _string(item.get("text") or item.get("candidate"))
            label = _string(item.get("label"))
            comment = _string(item.get("comment"))
            rime_index = _bounded_int(item.get("index"), default=index, minimum=0, maximum=999)
        else:
            continue
        text = compact_whitespace(text)
        if text:
            candidates.append(RimeCandidate(text=text, label=label, comment=comment, index=rime_index))
    return candidates


def _display_label(label: str, zero_based_index: int) -> str:
    if label:
        return label
    number = (zero_based_index + 1) % 10
    return "0" if number == 0 else str(number)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return default
    return max(minimum, min(maximum, parsed))


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return default
