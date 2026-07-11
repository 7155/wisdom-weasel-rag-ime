from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .models import InputSuggestion, ModelPrediction, RimeContextSnapshot, SideCandidateDisplayItem
from .pinyin_index import text_initials
from .text_utils import compact_whitespace


_LOW_VALUE_WANXIANG_FALLBACK = {
    "测试",
    "分析",
    "验证",
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
_LOW_VALUE_PREDICTION_TOP1 = _LOW_VALUE_WANXIANG_FALLBACK | {
    "嗯",
    "啊",
    "哦",
    "吧",
    "呢",
    "就是",
    "这个",
    "那个",
}
_COMPOSITION_DISPLAY_LIMITS = {"model": 16, "rag": 18, "memory": 18}
_POST_COMMIT_DISPLAY_LIMITS = {"model": 22, "rag": 20, "memory": 20}


class InputMode(str, Enum):
    RAW_INPUT = "raw_input"
    ANCHOR_COMPOSING = "anchor_composing"
    POST_COMMIT_PREDICTING = "post_commit_predicting"
    PREFIX_CONSTRAINED_COMPOSING = "prefix_constrained_composing"


class PredictionSessionPhase(str, Enum):
    HIDDEN = "hidden"
    RAW_PASSTHROUGH = "raw_passthrough"
    ANCHOR_COMPOSING = "anchor_composing"
    POST_COMMIT = "post_commit"
    PREFIX_CONSTRAINED = "prefix_constrained"


@dataclass(frozen=True)
class PredictionSessionState:
    phase: PredictionSessionPhase
    input_mode: InputMode
    pinyin_prefix: str
    candidate_panel_visible: bool
    prediction_panel_visible: bool
    should_clear_prediction_panel: bool
    clear_reason: str = ""
    selection_scope: str = "none"
    rime_composition_owned_by_rime: bool = False
    side_candidate_count: int = 0
    rime_candidate_count: int = 0
    raw_commit_count: int = 0


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
    expanded_evidence: str = ""
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

    def prediction_order(
        self,
        *,
        side_budget: int | None = None,
        post_commit: bool = False,
    ) -> tuple[PredictionCandidate, ...]:
        groups = {
            "model": list(sorted(self.model, key=lambda item: item.score, reverse=True)),
            "rag": list(sorted(self.rag, key=lambda item: item.score, reverse=True)),
            "memory": list(sorted(self.memory, key=lambda item: item.score, reverse=True)),
        }
        ordered: list[PredictionCandidate] = []
        seen: set[tuple[str, int, str]] = set()
        suggestion_inserted = 0
        model_count = len(groups["model"])
        suggestion_count = len(groups["rag"]) + len(groups["memory"])
        if side_budget is None:
            side_budget = model_count + suggestion_count
        budget = max(0, int(side_budget))
        model_slot_cap = _prediction_max_model_slots(
            budget,
            has_suggestions=suggestion_count > 0,
            post_commit=post_commit,
        )
        if budget <= 1:
            suggestion_reserve = 0 if model_count else min(suggestion_count, 1)
        elif budget == 2:
            suggestion_reserve = min(suggestion_count, 1)
        else:
            minimum_model_slots = min(2, model_count)
            suggestion_reserve = min(
                suggestion_count,
                _prediction_rag_block_reserve(budget),
                max(0, budget - minimum_model_slots),
            )
        model_limit = min(model_slot_cap, max(0, budget - suggestion_reserve))

        def push_one(name: str) -> bool:
            while groups[name]:
                candidate = groups[name].pop(0)
                key = (candidate.source_type, candidate.source_index, candidate.display_text)
                if key in seen:
                    continue
                ordered.append(candidate)
                seen.add(key)
                return True
            return False

        while len([item for item in ordered if item.source_type == "model"]) < model_limit and groups["model"]:
            before = len(ordered)
            push_one("model")
            if len(ordered) == before:
                break
        while suggestion_inserted < suggestion_reserve and (groups["rag"] or groups["memory"]):
            inserted = push_one("rag") or push_one("memory")
            if inserted:
                suggestion_inserted += 1
            else:
                break
        if not suggestion_count:
            while len([item for item in ordered if item.source_type == "model"]) < model_slot_cap and groups["model"]:
                push_one("model")
        return tuple(ordered)


@dataclass(frozen=True)
class PredictionFirstMergeResult:
    mode: InputMode
    pinyin_prefix: str
    display_candidates: tuple[SideCandidateDisplayItem, ...]
    policy: dict[str, object]


def _prediction_rag_block_reserve(side_budget: int) -> int:
    if side_budget <= 1:
        return 0
    return 1


def _prediction_max_model_slots(
    side_budget: int,
    *,
    has_suggestions: bool,
    post_commit: bool = False,
) -> int:
    if side_budget <= 0:
        return 0
    if has_suggestions and not post_commit:
        return min(2, side_budget)
    return min(3, side_budget)


def _allow_semantic_side_candidates_for_prefix(prefix: str) -> bool:
    """Long active pinyin should not hide semantic RAG/LLM candidates."""

    normalized = _pinyin_norm(prefix)
    return len(normalized) >= 6


def prefix_constrained_composing_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL", "0")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def infer_input_mode(snapshot: RimeContextSnapshot) -> InputMode:
    """Infer the prediction-first state from an adapter snapshot.

    This is intentionally conservative. Any active composition is still owned by
    Rime/wanxiang. Prefix-constrained AI remains an explicit experiment behind
    RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL.
    """

    prefix = active_pinyin_prefix(snapshot)
    if _looks_like_raw_ascii_commit_input(prefix):
        return InputMode.RAW_INPUT
    has_context = bool(compact_whitespace(snapshot.committed_context))
    if prefix and has_context and prefix_constrained_composing_enabled():
        return InputMode.PREFIX_CONSTRAINED_COMPOSING
    if prefix:
        return InputMode.ANCHOR_COMPOSING
    if has_context:
        return InputMode.POST_COMMIT_PREDICTING
    return InputMode.RAW_INPUT


def active_pinyin_prefix(snapshot: RimeContextSnapshot) -> str:
    return compact_whitespace(snapshot.preedit or snapshot.raw_input).lower()


def _looks_like_raw_ascii_commit_input(raw: str) -> bool:
    if not raw or not raw.isascii():
        return False
    parts = raw.split()
    command_prefixes = {"git", "npm", "python", "python3", "uv", "node", "cd", "ls", "rg", "docker"}
    if parts and parts[0].lower() in command_prefixes:
        return True
    code_delimiters = set("_./:-+=<>[]{}()$@#\\|")
    return (
        any(char in code_delimiters for char in raw)
        or any(char.isdigit() for char in raw)
        or (any(char.isupper() for char in raw) and any(char.islower() for char in raw))
    )


def build_candidate_pool(
    *,
    model_predictions: list[ModelPrediction] | tuple[ModelPrediction, ...] = (),
    suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...] = (),
) -> CandidatePool:
    rag_items: list[PredictionCandidate] = []
    memory_items: list[PredictionCandidate] = []
    for index, item in enumerate(suggestions):
        candidate = _candidate_from_suggestion(item, index)
        if candidate.source_type == "memory":
            memory_items.append(candidate)
        else:
            rag_items.append(candidate)
    model_candidates = tuple(_candidate_from_model(item, index) for index, item in enumerate(model_predictions))
    return CandidatePool(rag=tuple(rag_items), memory=tuple(memory_items), model=model_candidates)


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
        if raw_inserted:
            return _merge_result(
                mode=InputMode.RAW_INPUT,
                pinyin_prefix=prefix,
                display=display,
                side_inserted=0,
                rime_fallback_count=0,
                reason="raw ascii/code input is directly commit-able; prediction lanes are suspended",
                raw_commit_inserted=raw_inserted,
            )
        before_rime = len(display)
        _append_rime_candidates(display, seen, snapshot, max_visible=max_visible, skip_low_value=True)
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
    if raw_inserted:
        return _merge_result(
            mode=InputMode.RAW_INPUT,
            pinyin_prefix=prefix,
            display=display,
            side_inserted=0,
            rime_fallback_count=0,
            reason="raw ascii/code input is directly commit-able; prediction lanes are suspended",
            raw_commit_inserted=raw_inserted,
        )
    rime_reserve = _rime_reserve_for_mode(snapshot, resolved_mode, max_visible)
    side_budget = min(snapshot.max_side_candidates, max(0, max_visible - rime_reserve))
    side_slot_limit = max(0, max_visible - rime_reserve)
    post_commit = resolved_mode == InputMode.POST_COMMIT_PREDICTING
    max_model_side = _prediction_max_model_slots(
        side_budget,
        has_suggestions=bool(pool.rag or pool.memory),
        post_commit=post_commit,
    )
    rag_reserve = _prediction_rag_block_reserve(side_budget)
    prediction_candidates = pool.prediction_order(side_budget=side_budget, post_commit=post_commit)
    strict_prefix_constraint = (
        resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING
        and not raw_inserted
        and not _allow_semantic_side_candidates_for_prefix(prefix)
    )
    if strict_prefix_constraint:
        prediction_candidates = _prefix_lane_order(prediction_candidates, prefix)
    prediction_candidates, top1_guard = _apply_prediction_top1_guard(prediction_candidates)
    side_inserted = 0
    prefix_matched_side_inserted = 0
    for candidate in prediction_candidates:
        if len(display) >= side_slot_limit or side_inserted >= side_budget:
            break
        normalized = _display_norm(candidate.display_text)
        if not normalized or normalized in seen:
            continue
        if strict_prefix_constraint and not prediction_candidate_matches_prefix(candidate, prefix):
            continue
        seen.add(normalized)
        display.append(_side_display_item(candidate, len(display), resolved_mode, prefix))
        side_inserted += 1
        if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING and prediction_candidate_matches_prefix(candidate, prefix):
            prefix_matched_side_inserted += 1

    before_rime = len(display)
    if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING:
        _append_rime_candidates(display, seen, snapshot, max_visible=max_visible, skip_low_value=True)
    elif side_inserted == 0:
        _append_rime_candidates(display, seen, snapshot, max_visible=max_visible, skip_low_value=True)
    rime_count = len(display) - before_rime

    return _merge_result(
        mode=resolved_mode,
        pinyin_prefix=prefix,
        display=display,
        side_inserted=side_inserted,
        rime_fallback_count=rime_count,
        reason=(
            (
                "long pinyin composition allows semantic LLM/RAG side candidates before wanxiang fallback"
                if not strict_prefix_constraint
                else "prefix-constrained predictions are hard-filtered by user pinyin; wanxiang/rime handles fallback"
            )
            if resolved_mode == InputMode.PREFIX_CONSTRAINED_COMPOSING
            else "post-commit predictions shown before fallback candidates"
        ),
        raw_commit_inserted=raw_inserted,
        prefix_matched_side_inserted=prefix_matched_side_inserted,
        top1_guard=top1_guard,
        rime_reserve=rime_reserve,
        max_model_side_candidates=max_model_side,
        rag_block_reserve=rag_reserve,
    )


def resolve_prediction_session(
    *,
    snapshot: RimeContextSnapshot,
    merge_result: PredictionFirstMergeResult,
) -> PredictionSessionState:
    """Resolve the frontend-neutral session lifecycle for prediction candidates.

    Rime/wanxiang candidates and AI prediction candidates can share a visible
    list, but they do not share the same lifecycle. A frontend should hide its
    prediction overlay when this state says `should_clear_prediction_panel`, even
    if Rime still has normal composition candidates to show.
    """

    mode = merge_result.mode
    policy = merge_result.policy
    side_count = _policy_int(policy, "sideInserted")
    rime_count = _policy_int(policy, "wanxiangFallbackCount")
    raw_count = _policy_int(policy, "rawCommitInserted")
    display_visible = bool(merge_result.display_candidates)
    rime_owned = mode in {InputMode.ANCHOR_COMPOSING, InputMode.PREFIX_CONSTRAINED_COMPOSING}

    if mode == InputMode.RAW_INPUT:
        phase = PredictionSessionPhase.RAW_PASSTHROUGH if raw_count else PredictionSessionPhase.HIDDEN
        return PredictionSessionState(
            phase=phase,
            input_mode=mode,
            pinyin_prefix=merge_result.pinyin_prefix,
            candidate_panel_visible=display_visible,
            prediction_panel_visible=False,
            should_clear_prediction_panel=True,
            clear_reason="raw input passthrough" if raw_count else "no active input",
            selection_scope="raw" if raw_count else "none",
            rime_composition_owned_by_rime=False,
            side_candidate_count=side_count,
            rime_candidate_count=rime_count,
            raw_commit_count=raw_count,
        )

    if mode == InputMode.ANCHOR_COMPOSING:
        return PredictionSessionState(
            phase=PredictionSessionPhase.ANCHOR_COMPOSING,
            input_mode=mode,
            pinyin_prefix=merge_result.pinyin_prefix,
            candidate_panel_visible=display_visible,
            prediction_panel_visible=False,
            should_clear_prediction_panel=True,
            clear_reason="wanxiang/rime owns anchor composition",
            selection_scope="rime" if rime_count else "none",
            rime_composition_owned_by_rime=True,
            side_candidate_count=side_count,
            rime_candidate_count=rime_count,
            raw_commit_count=raw_count,
        )

    if mode == InputMode.POST_COMMIT_PREDICTING:
        prediction_visible = side_count > 0 and display_visible
        return PredictionSessionState(
            phase=PredictionSessionPhase.POST_COMMIT if prediction_visible else PredictionSessionPhase.HIDDEN,
            input_mode=mode,
            pinyin_prefix=merge_result.pinyin_prefix,
            candidate_panel_visible=display_visible,
            prediction_panel_visible=prediction_visible,
            should_clear_prediction_panel=not prediction_visible,
            clear_reason="" if prediction_visible else _post_commit_clear_reason(snapshot),
            selection_scope="prediction" if prediction_visible else "none",
            rime_composition_owned_by_rime=False,
            side_candidate_count=side_count,
            rime_candidate_count=rime_count,
            raw_commit_count=raw_count,
        )

    if mode == InputMode.PREFIX_CONSTRAINED_COMPOSING:
        prediction_visible = side_count > 0 and display_visible
        selection_scope = "mixed_prediction_first" if prediction_visible else ("rime" if rime_count else "none")
        return PredictionSessionState(
            phase=PredictionSessionPhase.PREFIX_CONSTRAINED if prediction_visible else PredictionSessionPhase.ANCHOR_COMPOSING,
            input_mode=mode,
            pinyin_prefix=merge_result.pinyin_prefix,
            candidate_panel_visible=display_visible,
            prediction_panel_visible=prediction_visible,
            should_clear_prediction_panel=not prediction_visible,
            clear_reason="" if prediction_visible else "prefix has no matching prediction candidates",
            selection_scope=selection_scope,
            rime_composition_owned_by_rime=rime_owned,
            side_candidate_count=side_count,
            rime_candidate_count=rime_count,
            raw_commit_count=raw_count,
        )

    return PredictionSessionState(
        phase=PredictionSessionPhase.HIDDEN,
        input_mode=mode,
        pinyin_prefix=merge_result.pinyin_prefix,
        candidate_panel_visible=display_visible,
        prediction_panel_visible=False,
        should_clear_prediction_panel=True,
        clear_reason="unknown prediction mode",
        selection_scope="none",
        rime_composition_owned_by_rime=rime_owned,
        side_candidate_count=side_count,
        rime_candidate_count=rime_count,
        raw_commit_count=raw_count,
    )


def prediction_session_to_payload(state: PredictionSessionState) -> dict[str, object]:
    return {
        "phase": state.phase.value,
        "inputMode": state.input_mode.value,
        "pinyinPrefix": state.pinyin_prefix,
        "candidatePanelVisible": state.candidate_panel_visible,
        "predictionPanelVisible": state.prediction_panel_visible,
        "shouldClearPredictionPanel": state.should_clear_prediction_panel,
        "clearReason": state.clear_reason,
        "selectionScope": state.selection_scope,
        "rimeCompositionOwnedByRime": state.rime_composition_owned_by_rime,
        "sideCandidateCount": state.side_candidate_count,
        "rimeCandidateCount": state.rime_candidate_count,
        "rawCommitCount": state.raw_commit_count,
    }


def prediction_candidate_matches_prefix(candidate: PredictionCandidate, prefix: str) -> bool:
    prefix_norm = _pinyin_norm(prefix)
    if not prefix_norm:
        return True
    keys = _candidate_primary_pinyin_keys(candidate)
    if not keys:
        return False
    return any(key.startswith(prefix_norm) for key in keys)


def _prefix_lane_order(candidates: tuple[PredictionCandidate, ...], prefix: str) -> tuple[PredictionCandidate, ...]:
    model_candidates = tuple(item for item in candidates if item.source_type == "model")
    memory_candidates = tuple(item for item in candidates if item.source_type != "model")
    matched_model, _ = _split_prefix_matches(model_candidates, prefix)
    matched_memory, _ = _split_prefix_matches(memory_candidates, prefix)
    return matched_model + matched_memory


def _split_prefix_matches(
    candidates: tuple[PredictionCandidate, ...],
    prefix: str,
) -> tuple[tuple[PredictionCandidate, ...], tuple[PredictionCandidate, ...]]:
    matched = tuple(item for item in candidates if prediction_candidate_matches_prefix(item, prefix))
    unmatched = tuple(item for item in candidates if item not in matched)
    return matched, unmatched


def _apply_prediction_top1_guard(
    candidates: tuple[PredictionCandidate, ...],
) -> tuple[tuple[PredictionCandidate, ...], dict[str, object] | None]:
    if len(candidates) < 2:
        return candidates, None
    first = candidates[0]
    if not _is_low_value_prediction_top1(first):
        return candidates, None

    for index, candidate in enumerate(candidates[1:], start=1):
        if not _can_promote_over_low_value_top1(candidate):
            continue
        promoted = replace(
            candidate,
            metadata={
                **candidate.metadata,
                "top1_guard": "promoted_over_low_value",
                "guarded_from_rank": index + 1,
                "original_top1": first.display_text,
            },
        )
        demoted = replace(
            first,
            metadata={
                **first.metadata,
                "top1_guard": "demoted_low_value",
                "guarded_by": candidate.display_text,
            },
        )
        reordered = list(candidates)
        reordered[0] = demoted
        reordered[index] = promoted
        promoted_candidate = reordered.pop(index)
        reordered.insert(0, promoted_candidate)
        guard = {
            "triggered": True,
            "reason": "low_value_prediction_top1",
            "originalTop1": first.display_text,
            "promotedText": candidate.display_text,
            "promotedSourceType": candidate.source_type,
            "promotedOriginalRank": index + 1,
        }
        return tuple(reordered), guard
    return candidates, {
        "triggered": False,
        "reason": "low_value_prediction_top1_without_challenger",
        "originalTop1": first.display_text,
    }


def _is_low_value_prediction_top1(candidate: PredictionCandidate) -> bool:
    text = compact_whitespace(candidate.display_text)
    if not text:
        return True
    if text in _LOW_VALUE_PREDICTION_TOP1:
        return True
    if len(text) <= 1 and text not in {"✓", "✅"}:
        return True
    return _is_low_value_wanxiang_fallback(text)


def _can_promote_over_low_value_top1(candidate: PredictionCandidate) -> bool:
    text = compact_whitespace(candidate.display_text)
    if len(text) < 2:
        return False
    if _is_low_value_prediction_top1(candidate):
        return False
    if candidate.source_type in {"rag", "memory"}:
        return True
    return candidate.source_type == "model" and len(text) >= 2


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
        expanded_evidence=suggestion.expanded_evidence,
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
    insert_text = str(metadata.get("insert_text") or prediction.text)
    display_text = compact_whitespace(prediction.text).lstrip(",，。！？；;、 ")
    return PredictionCandidate(
        display_text=display_text,
        insert_text=insert_text,
        source_type="model",
        source_index=prediction.rank - 1 if prediction.rank > 0 else index,
        score=1.0 + prediction.confidence - (index * 0.001),
        confidence=prediction.confidence,
        comment=prediction.provider_name,
        expanded_evidence="",
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
    display_text, truncated = _bounded_side_display_text(
        candidate.display_text,
        source_type=candidate.source_type,
        mode=mode,
    )
    metadata.update(
        {
            "candidate_mode": mode.value,
            "pinyin_prefix": prefix,
            "prediction_first": True,
            "score": candidate.score,
            "confidence": candidate.confidence,
            "display_text_truncated": truncated,
        }
    )
    if truncated:
        metadata["full_display_text"] = candidate.display_text
        metadata["display_text_limit"] = _side_display_text_limit(candidate.source_type, mode)
    return SideCandidateDisplayItem(
        label=_display_label(zero_based_index),
        text=display_text,
        insert_text=candidate.insert_text,
        source_type=candidate.source_type,
        selection_action="commit_side_candidate",
        source_index=candidate.source_index,
        comment=candidate.comment,
        evidence_preview=candidate.evidence_preview,
        expanded_evidence=candidate.expanded_evidence,
        suggestion_id=candidate.suggestion_id,
        memory_id=candidate.memory_id,
        source_event_id=candidate.source_event_id,
        display_layout="block" if candidate.source_type in {"model", "rag", "memory"} else "inline",
        display_lane="memory" if candidate.source_type in {"rag", "memory"} else "model",
        metadata=metadata,
    )


def _bounded_side_display_text(text: str, *, source_type: str, mode: InputMode) -> tuple[str, bool]:
    normalized = compact_whitespace(text)
    limit = _side_display_text_limit(source_type, mode)
    if limit <= 0 or len(normalized) <= limit:
        return normalized, False
    return normalized[:limit].rstrip() + "...", True


def _side_display_text_limit(source_type: str, mode: InputMode) -> int:
    if mode == InputMode.POST_COMMIT_PREDICTING:
        return _POST_COMMIT_DISPLAY_LIMITS.get(source_type, 0)
    if mode == InputMode.PREFIX_CONSTRAINED_COMPOSING:
        return _COMPOSITION_DISPLAY_LIMITS.get(source_type, 0)
    return 0


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


def _rime_reserve_for_mode(snapshot: RimeContextSnapshot, mode: InputMode, max_visible: int) -> int:
    if mode not in {InputMode.ANCHOR_COMPOSING, InputMode.PREFIX_CONSTRAINED_COMPOSING}:
        return 0
    rime_count = sum(1 for candidate in snapshot.candidates if compact_whitespace(candidate.text))
    if rime_count <= 0:
        return 0
    if max_visible >= 8:
        return min(3, rime_count)
    if max_visible >= 5:
        return min(2, rime_count)
    return min(1, rime_count)


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
    top1_guard: dict[str, object] | None = None,
    rime_reserve: int = 0,
    max_model_side_candidates: int = 0,
    rag_block_reserve: int = 0,
) -> PredictionFirstMergeResult:
    return PredictionFirstMergeResult(
        mode=mode,
        pinyin_prefix=pinyin_prefix,
        display_candidates=tuple(display),
        policy={
            "engine": "prediction-first",
            "mode": mode.value,
            "reason": reason,
            "panelVisible": bool(display),
            "predictionPanelVisible": side_inserted > 0 and mode
            in {InputMode.POST_COMMIT_PREDICTING, InputMode.PREFIX_CONSTRAINED_COMPOSING},
            "shouldClearPredictionPanel": not (
                side_inserted > 0 and mode in {InputMode.POST_COMMIT_PREDICTING, InputMode.PREFIX_CONSTRAINED_COMPOSING}
            ),
            "hideWhenEmpty": True,
            "sessionBound": True,
            "sideInserted": side_inserted,
            "prefixMatchedSideInserted": prefix_matched_side_inserted,
            "rawCommitInserted": raw_commit_inserted,
            "wanxiangFallbackCount": rime_fallback_count,
            "wanxiangReserve": rime_reserve,
            "maxModelSideCandidates": max_model_side_candidates,
            "ragBlockReserve": rag_block_reserve,
            "rimeCompositionOwnedByRime": mode in {InputMode.ANCHOR_COMPOSING, InputMode.PREFIX_CONSTRAINED_COMPOSING},
            "top1Guard": top1_guard or {"triggered": False},
        },
    )


def _candidate_primary_pinyin_keys(candidate: PredictionCandidate) -> tuple[str, ...]:
    keys: list[str] = []
    if candidate.initials:
        keys.append(_pinyin_norm(candidate.initials))
    if candidate.full_pinyin:
        joined = "".join(candidate.full_pinyin)
        keys.append(_pinyin_norm(joined))
        keys.extend(_pinyin_norm(item) for item in candidate.full_pinyin)
    for text in (candidate.display_text, candidate.insert_text):
        if text:
            keys.append(_pinyin_norm(text_initials(text)))
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


def _policy_int(policy: dict[str, object], key: str) -> int:
    try:
        return int(policy.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _post_commit_clear_reason(snapshot: RimeContextSnapshot) -> str:
    if snapshot.idle_ms > 0:
        return "post-commit prediction session stale or empty"
    return "post-commit prediction has no live candidates"


def _display_label(zero_based_index: int) -> str:
    number = (zero_based_index + 1) % 10
    return "0" if number == 0 else str(number)
