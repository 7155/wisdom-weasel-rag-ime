from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import InputSuggestion, ModelPrediction, RimeContextSnapshot, SideCandidateDisplayItem
from .text_utils import compact_whitespace


_LOW_VALUE_WANXIANG_FALLBACK = {
    "测试",
    "分析",
    "并且",
    "但是",
    "或者",
    "基于",
    "根据",
    "生成",
    "假设",
    "然后",
    "现在",
    "目前",
    "当前",
    "的",
    "了",
    "和",
    "是",
}


class InputMode(str, Enum):
    RAW_INPUT = "raw_input"
    ANCHOR_COMPOSING = "anchor_composing"
    POST_COMMIT_PREDICTING = "post_commit_predicting"
    PREFIX_CONSTRAINED_COMPOSING = "prefix_constrained_composing"


@dataclass(frozen=True)
class PredictionCandidate:
    display_text: str
    insert_text: str
    source_type: str
    source_index: int
    score: float = 0.0
    confidence: float = 0.0
    comment: str = ""
    evidence_preview: str = ""
    suggestion_id: str = ""
    memory_id: str = ""
    source_event_id: int | None = None
    full_pinyin: tuple[str, ...] = ()
    initials: str = ""
    expandable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidatePool:
    rag: tuple[PredictionCandidate, ...] = ()
    model: tuple[PredictionCandidate, ...] = ()
    memory: tuple[PredictionCandidate, ...] = ()

    def prediction_order(self) -> tuple[PredictionCandidate, ...]:
        return tuple(sorted((*self.rag, *self.memory, *self.model), key=lambda item: item.score, reverse=True))


@dataclass(frozen=True)
class PredictionFirstMergeResult:
    mode: InputMode
    pinyin_prefix: str
    display_candidates: tuple[SideCandidateDisplayItem, ...]
    policy: dict[str, object]


def infer_input_mode(snapshot: RimeContextSnapshot) -> InputMode:
    """Infer the prediction-first state from an adapter snapshot.

    This is intentionally conservative. Any active composition is still owned by
    Rime/wanxiang; Prediction-first logic only changes candidate ordering.
    """

    prefix = active_pinyin_prefix(snapshot)
    has_context = bool(compact_whitespace(snapshot.committed_context))
    if prefix and has_context:
        return InputMode.PREFIX_CONSTRAINED_COMPOSING
    if prefix:
        return InputMode.ANCHOR_COMPOSING
    if has_context:
        return InputMode.POST_COMMIT_PREDICTING
    return InputMode.RAW_INPUT


def active_pinyin_prefix(snapshot: RimeContextSnapshot) -> str:
    return compact_whitespace(snapshot.preedit or snapshot.raw_input).lower()


def build_candidate_pool(
    *,
    model_predictions: list[ModelPrediction] | tuple[ModelPrediction, ...] = (),
    suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...] = (),
) -> CandidatePool:
    rag_candidates = tuple(_candidate_from_suggestion(item, index) for index, item in enumerate(suggestions))
    model_candidates = tuple(_candidate_from_model(item, index) for index, item in enumerate(model_predictions))
    return CandidatePool(rag=rag_candidates, model=model_candidates)


def merge_prediction_first_candidates(
    *,
    snapshot: RimeContextSnapshot,
    model_predictions: list[ModelPrediction] | tuple[ModelPrediction, ...] = (),
    suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...] = (),
    mode: InputMode | None = None,
    raw_commit_text: str = "",
) -> PredictionFirstMergeResult:
    resolved_mode = mode or infer_input_mode(snapshot)
    prefix = active_pinyin_prefix(snapshot)
    pool = build_candidate_pool(model_predictions=model_predictions, suggestions=suggestions)
    max_visible = snapshot.max_visible_candidates
    display: list[SideCandidateDisplayItem] = []
    seen: set[str] = set()
    raw_inserted = 0

    if resolved_mode in (InputMode.RAW_INPUT, InputMode.ANCHOR_COMPOSING):
        raw_inserted = _append_raw_commit_candidate(
            display,
            seen,
            raw_commit_text=raw_commit_text,
            mode=resolved_mode,
            prefix=prefix,
            max_visible=max_visible,
        )
        before_rime = len(display)
        _append_rime_candidates(display, seen, snapshot, max_visible=max_visible)
        return _merge_result(
            mode=resolved_mode,
            pinyin_prefix=prefix,
            display=display,
            side_inserted=0,
            rime_fallback_count=len(display) - before_rime,
            reason=(
                "raw ascii/code input is directly commit-able; wanxiang/rime still owns active composition"
                if raw_inserted
                else "wanxiang/rime owns active anchor composition"
            ),
            raw_commit_inserted=raw_inserted,
        )

    raw_inserted = _append_raw_commit_candidate(
        display,
        seen,
        raw_commit_text=raw_commit_text,
        mode=resolved_mode,
        prefix=prefix,
        max_visible=max_visible,
    )
    prediction_candidates = pool.prediction_order()
    if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING:
        prediction_candidates = _prefix_lane_order(prediction_candidates, prefix)

    side_budget = min(snapshot.max_side_candidates, max_visible)
    side_inserted = 0
    prefix_matched_side_inserted = 0
    for candidate in prediction_candidates:
        if len(display) >= max_visible or side_inserted >= side_budget:
            break
        normalized = _display_norm(candidate.display_text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        display.append(_side_display_item(candidate, len(display), resolved_mode, prefix))
        side_inserted += 1
        if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING and prediction_candidate_matches_prefix(candidate, prefix):
            prefix_matched_side_inserted += 1

    before_rime = len(display)
    if side_inserted == 0:
        _append_rime_candidates(display, seen, snapshot, max_visible=max_visible, skip_low_value=True)
    rime_count = len(display) - before_rime

    return _merge_result(
        mode=resolved_mode,
        pinyin_prefix=prefix,
        display=display,
        side_inserted=side_inserted,
        rime_fallback_count=rime_count,
        reason=(
            "prefix-constrained predictions sorted first; remaining LLM/RAG candidates fill before wanxiang/rime fallback"
            if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING
            else "post-commit predictions shown before fallback candidates"
        ),
        raw_commit_inserted=raw_inserted,
        prefix_matched_side_inserted=prefix_matched_side_inserted,
    )


def prediction_candidate_matches_prefix(candidate: PredictionCandidate, prefix: str) -> bool:
    prefix_norm = _pinyin_norm(prefix)
    if not prefix_norm:
        return True
    keys = _candidate_pinyin_keys(candidate)
    if not keys:
        return False
    return any(key.startswith(prefix_norm) for key in keys)


def _prefix_lane_order(candidates: tuple[PredictionCandidate, ...], prefix: str) -> tuple[PredictionCandidate, ...]:
    model_candidates = tuple(item for item in candidates if item.source_type == "model")
    memory_candidates = tuple(item for item in candidates if item.source_type != "model")
    matched_model, unmatched_model = _split_prefix_matches(model_candidates, prefix)
    matched_memory, unmatched_memory = _split_prefix_matches(memory_candidates, prefix)
    if matched_model:
        return matched_model + matched_memory + unmatched_model + unmatched_memory
    visible_unmatched_model = unmatched_model[:1]
    deferred_unmatched_model = unmatched_model[1:]
    return visible_unmatched_model + matched_memory + unmatched_memory + deferred_unmatched_model


def _split_prefix_matches(
    candidates: tuple[PredictionCandidate, ...],
    prefix: str,
) -> tuple[tuple[PredictionCandidate, ...], tuple[PredictionCandidate, ...]]:
    matched = tuple(item for item in candidates if prediction_candidate_matches_prefix(item, prefix))
    unmatched = tuple(item for item in candidates if item not in matched)
    return matched, unmatched


def _candidate_from_suggestion(suggestion: InputSuggestion, index: int) -> PredictionCandidate:
    metadata = dict(suggestion.metadata)
    insert_text = str(metadata.get("insert_text") or suggestion.surface_text)
    source_type = str(metadata.get("source_type") or suggestion.suggestion_type or "rag")
    if source_type not in {"rag", "memory"}:
        source_type = "rag"
    source_weight = 2.0 if source_type == "rag" else 1.8
    if metadata.get("fallback") == "recent_context":
        source_weight = 0.75
    return PredictionCandidate(
        display_text=suggestion.surface_text,
        insert_text=insert_text,
        source_type=source_type,
        source_index=index,
        score=source_weight + suggestion.confidence,
        confidence=suggestion.confidence,
        comment=suggestion.suggestion_type,
        evidence_preview=suggestion.evidence_preview,
        suggestion_id=suggestion.suggestion_id,
        memory_id=str(metadata.get("memory_id") or suggestion.suggestion_id),
        source_event_id=suggestion.source_event_id,
        full_pinyin=_metadata_tuple(metadata, "full_pinyin", "pinyin"),
        initials=_metadata_string(metadata, "initials", "pinyin_initials"),
        expandable=bool(suggestion.expanded_evidence),
        metadata=metadata,
    )


def _candidate_from_model(prediction: ModelPrediction, index: int) -> PredictionCandidate:
    metadata = dict(prediction.metadata)
    return PredictionCandidate(
        display_text=prediction.text,
        insert_text=str(metadata.get("insert_text") or prediction.text),
        source_type="model",
        source_index=prediction.rank - 1 if prediction.rank > 0 else index,
        score=1.0 + prediction.confidence - (index * 0.001),
        confidence=prediction.confidence,
        comment=prediction.provider_name,
        full_pinyin=_metadata_tuple(metadata, "full_pinyin", "pinyin"),
        initials=_metadata_string(metadata, "initials", "pinyin_initials"),
        metadata=metadata,
    )


def _side_display_item(
    candidate: PredictionCandidate,
    zero_based_index: int,
    mode: InputMode,
    prefix: str,
) -> SideCandidateDisplayItem:
    metadata = dict(candidate.metadata)
    metadata.update(
        {
            "candidate_mode": mode.value,
            "pinyin_prefix": prefix,
            "prediction_first": True,
            "score": candidate.score,
            "confidence": candidate.confidence,
        }
    )
    return SideCandidateDisplayItem(
        label=_display_label(zero_based_index),
        text=candidate.display_text,
        insert_text=candidate.insert_text,
        source_type=candidate.source_type,
        selection_action="commit_side_candidate",
        source_index=candidate.source_index,
        comment=candidate.comment,
        evidence_preview=candidate.evidence_preview,
        suggestion_id=candidate.suggestion_id,
        memory_id=candidate.memory_id,
        source_event_id=candidate.source_event_id,
        display_layout="block" if candidate.source_type in {"rag", "memory"} else "inline",
        display_lane="memory" if candidate.source_type in {"rag", "memory"} else "model",
        metadata=metadata,
    )


def _append_rime_candidates(
    display: list[SideCandidateDisplayItem],
    seen: set[str],
    snapshot: RimeContextSnapshot,
    *,
    max_visible: int,
    skip_low_value: bool = False,
) -> None:
    for candidate in snapshot.candidates:
        if len(display) >= max_visible:
            return
        normalized = _display_norm(candidate.text)
        if not normalized or normalized in seen:
            continue
        if skip_low_value and _is_low_value_wanxiang_fallback(candidate.text):
            continue
        seen.add(normalized)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label(len(display)),
                text=candidate.text,
                insert_text=candidate.text,
                source_type="rime",
                selection_action="select_rime_candidate",
                source_index=candidate.index,
                comment=candidate.comment,
                rime_index=candidate.index,
                display_layout="fallback",
                display_lane="wanxiang",
                metadata={"candidate_mode": "wanxiang-fallback"},
            )
        )


def _is_low_value_wanxiang_fallback(text: str) -> bool:
    normalized = compact_whitespace(text)
    if normalized in _LOW_VALUE_WANXIANG_FALLBACK:
        return True
    if any(normalized.startswith(prefix) for prefix in ("测试", "分析")) and len(normalized) <= 4:
        return True
    if any(normalized.startswith(prefix) for prefix in ("当前", "目前", "现在")) and len(normalized) <= 5:
        return True
    return False


def _append_raw_commit_candidate(
    display: list[SideCandidateDisplayItem],
    seen: set[str],
    *,
    raw_commit_text: str,
    mode: InputMode,
    prefix: str,
    max_visible: int,
) -> int:
    text = compact_whitespace(raw_commit_text)
    normalized = _display_norm(text)
    if not text or not normalized or normalized in seen or len(display) >= max_visible:
        return 0
    seen.add(normalized)
    display.append(
        SideCandidateDisplayItem(
            label=_display_label(len(display)),
            text=text,
            insert_text=text,
            source_type="raw_english",
            selection_action="commit_side_candidate",
            source_index=0,
            comment="input",
            display_layout="inline",
            display_lane="input",
            metadata={
                "candidate_mode": mode.value,
                "pinyin_prefix": prefix,
                "prediction_first": True,
                "raw_commit": True,
            },
        )
    )
    return 1


def _merge_result(
    *,
    mode: InputMode,
    pinyin_prefix: str,
    display: list[SideCandidateDisplayItem],
    side_inserted: int,
    rime_fallback_count: int,
    reason: str,
    raw_commit_inserted: int = 0,
    prefix_matched_side_inserted: int = 0,
) -> PredictionFirstMergeResult:
    return PredictionFirstMergeResult(
        mode=mode,
        pinyin_prefix=pinyin_prefix,
        display_candidates=tuple(display),
        policy={
            "engine": "prediction-first",
            "mode": mode.value,
            "reason": reason,
            "sideInserted": side_inserted,
            "prefixMatchedSideInserted": prefix_matched_side_inserted,
            "rawCommitInserted": raw_commit_inserted,
            "wanxiangFallbackCount": rime_fallback_count,
            "rimeCompositionOwnedByRime": mode in {InputMode.ANCHOR_COMPOSING, InputMode.PREFIX_CONSTRAINED_COMPOSING},
        },
    )


def _candidate_pinyin_keys(candidate: PredictionCandidate) -> tuple[str, ...]:
    keys: list[str] = []
    if candidate.initials:
        keys.append(_pinyin_norm(candidate.initials))
    if candidate.full_pinyin:
        joined = "".join(candidate.full_pinyin)
        keys.append(_pinyin_norm(joined))
        keys.extend(_pinyin_norm(item) for item in candidate.full_pinyin)
    extra = candidate.metadata.get("pinyin_prefixes")
    if isinstance(extra, (list, tuple)):
        keys.extend(_pinyin_norm(str(item)) for item in extra)
    elif isinstance(extra, str):
        keys.append(_pinyin_norm(extra))
    return tuple(item for item in dict.fromkeys(keys) if item)


def _metadata_tuple(metadata: dict[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return tuple(part for part in (_pinyin_norm(part) for part in value.replace("'", " ").split()) if part)
        if isinstance(value, (list, tuple)):
            return tuple(part for part in (_pinyin_norm(str(item)) for item in value) if part)
    return ()


def _metadata_string(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            return _pinyin_norm(value)
    return ""


def _pinyin_norm(value: str) -> str:
    return "".join(char.lower() for char in compact_whitespace(value) if char.isascii() and char.isalnum())


def _display_norm(value: str) -> str:
    return compact_whitespace(value).lower()


def _display_label(zero_based_index: int) -> str:
    number = (zero_based_index + 1) % 10
    return "0" if number == 0 else str(number)
