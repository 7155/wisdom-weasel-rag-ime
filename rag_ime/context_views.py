from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .context_frame import CurrentInputFrame
from .models import SideCandidateDisplayItem
from .text_utils import compact_whitespace, truncate_text


@dataclass(frozen=True)
class RimeView:
    raw_input: str
    preedit: str
    candidates: tuple[str, ...]
    highlighted_index: int


@dataclass(frozen=True)
class ModelPromptView:
    request_type: str
    query: str
    recent_context_tail: str
    rime_candidates: tuple[str, ...]
    max_candidates: int
    forbidden_phrases: tuple[str, ...]
    latency_budget_ms: int


@dataclass(frozen=True)
class RagRetrievalView:
    semantic_query: str
    query_basis: str
    committed_tail: str
    project: str
    app: str
    active_tags: tuple[str, ...]
    negative_signals: tuple[str, ...]
    top_k: int
    latency_budget_ms: int


@dataclass(frozen=True)
class RagEvidenceItem:
    evidence_id: str
    source_type: str
    text: str
    summary: str
    tags: tuple[str, ...]
    memory_ids: tuple[str, ...]
    evidence_event_ids: tuple[int, ...]
    score: float
    blocked_reason: str = ""


@dataclass(frozen=True)
class RagPredictionView:
    selected_or_committed_query: str
    evidence_pack: tuple[RagEvidenceItem, ...]
    candidate_style: Literal["short_ime_candidate"]
    placement: Literal["replace_selection", "insert_after_selection", "append_at_cursor", "show_only"]
    max_candidates: int


@dataclass(frozen=True)
class DisplayView:
    ui_mode: str
    key_policy: dict[str, str]
    display_anchor: str
    visible_candidates: tuple[SideCandidateDisplayItem, ...]
    status_rows: tuple[SideCandidateDisplayItem, ...]


def build_rime_view(frame: CurrentInputFrame) -> RimeView:
    return RimeView(
        raw_input=frame.composition.raw_input,
        preedit=frame.composition.preedit,
        candidates=tuple(item.text for item in frame.composition.rime_candidates),
        highlighted_index=frame.composition.highlighted_index,
    )


def build_model_prompt_view(frame: CurrentInputFrame) -> ModelPromptView:
    is_post_commit = frame.ui.ui_mode.startswith("post_commit")
    query = frame.committed.commit_text_preview if is_post_commit else frame.composition.preedit or frame.composition.raw_input
    tail = frame.committed.committed_tail[-160:]
    forbidden = tuple(
        item
        for item in (
            frame.committed.commit_text_preview,
            frame.composition.raw_input,
            frame.composition.preedit,
            "下一步",
            "接下来",
            "根据上述",
            "可以进行",
        )
        if compact_whitespace(item)
    )
    return ModelPromptView(
        request_type="post_commit_prediction" if is_post_commit else "composition_warmup",
        query=compact_whitespace(query),
        recent_context_tail=tail,
        rime_candidates=tuple(item.text for item in frame.composition.rime_candidates[:5]),
        max_candidates=3 if is_post_commit else 0,
        forbidden_phrases=forbidden,
        latency_budget_ms=1500 if is_post_commit else 0,
    )


def build_rag_retrieval_view(
    frame: CurrentInputFrame,
    *,
    semantic_query: str = "",
    query_basis: str = "",
) -> RagRetrievalView:
    query = compact_whitespace(semantic_query) or compact_whitespace(
        frame.committed.commit_text_preview or frame.composition.preedit or frame.composition.raw_input
    )
    return RagRetrievalView(
        semantic_query=query,
        query_basis=compact_whitespace(query_basis) or "contextFrame",
        committed_tail=frame.committed.committed_tail[-240:],
        project=frame.ui.project,
        app=frame.ui.app,
        active_tags=(),
        negative_signals=("raw_echo", "long_evidence_surface"),
        top_k=8,
        latency_budget_ms=120,
    )


def build_rag_prediction_view(
    frame: CurrentInputFrame,
    evidence_pack: tuple[RagEvidenceItem, ...],
) -> RagPredictionView:
    selected_hash = frame.foreground_text.selected_text_hash
    placement: Literal["replace_selection", "insert_after_selection", "append_at_cursor", "show_only"]
    placement = "replace_selection" if frame.foreground_text.can_replace_selection and selected_hash else "append_at_cursor"
    query = frame.foreground_text.selected_text_preview or frame.committed.commit_text_preview or frame.committed.committed_tail
    return RagPredictionView(
        selected_or_committed_query=truncate_text(query, 120),
        evidence_pack=evidence_pack,
        candidate_style="short_ime_candidate",
        placement=placement,
        max_candidates=3,
    )


def build_display_view(
    frame: CurrentInputFrame,
    *,
    candidates: tuple[SideCandidateDisplayItem, ...],
    key_policy: dict[str, str],
) -> DisplayView:
    return DisplayView(
        ui_mode=frame.ui.ui_mode,
        key_policy=dict(key_policy),
        display_anchor=frame.anchors.display_anchor,
        visible_candidates=tuple(item for item in candidates if item.source_type != "status"),
        status_rows=tuple(item for item in candidates if item.source_type == "status" or item.display_layout == "status_row"),
    )


def context_views_trace_payload(
    *,
    rime_view: RimeView,
    model_view: ModelPromptView,
    rag_view: RagRetrievalView,
    display_view: DisplayView,
) -> dict[str, object]:
    return {
        "rime": {
            "rawInputChars": len(rime_view.raw_input),
            "preeditChars": len(rime_view.preedit),
            "candidateCount": len(rime_view.candidates),
            "highlightedIndex": rime_view.highlighted_index,
        },
        "model": {
            "requestType": model_view.request_type,
            "queryChars": len(model_view.query),
            "recentContextTailChars": len(model_view.recent_context_tail),
            "rimeCandidateCount": len(model_view.rime_candidates),
            "maxCandidates": model_view.max_candidates,
            "latencyBudgetMs": model_view.latency_budget_ms,
        },
        "rag": {
            "semanticQueryChars": len(rag_view.semantic_query),
            "queryBasis": rag_view.query_basis,
            "committedTailChars": len(rag_view.committed_tail),
            "project": rag_view.project,
            "app": rag_view.app,
            "topK": rag_view.top_k,
        },
        "display": {
            "uiMode": display_view.ui_mode,
            "displayAnchor": display_view.display_anchor,
            "visibleCandidateCount": len(display_view.visible_candidates),
            "statusRowCount": len(display_view.status_rows),
            "keyPolicy": dict(display_view.key_policy),
        },
    }

