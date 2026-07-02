from __future__ import annotations

from dataclasses import dataclass

from .models import InputSuggestion, ModelPrediction, RimeContextSnapshot, SideCandidateDisplayItem
from .prediction_first import (
    InputMode,
    PredictionFirstMergeResult,
    PredictionSessionState,
    infer_input_mode,
    merge_prediction_first_candidates,
    resolve_prediction_session,
)
from .text_utils import compact_whitespace


@dataclass(frozen=True)
class PredictionManagerResult:
    merge_result: PredictionFirstMergeResult
    session: PredictionSessionState
    display_candidates: tuple[SideCandidateDisplayItem, ...]
    reused_candidate_pool: bool
    candidate_pool_active: bool
    candidate_pool_stale: bool
    context_fingerprint: str


@dataclass(frozen=True)
class _CandidateSourceCache:
    context_fingerprint: str
    model_predictions: tuple[ModelPrediction, ...]
    suggestions: tuple[InputSuggestion, ...]
    updated_at_ms: int


class PredictionManager:
    """Frontend-neutral state manager for Prediction-first candidate sessions.

    It owns only the lifecycle of cached LLM/RAG/memory candidates. Rime/wanxiang
    still owns composition and dictionary fallback. A macOS adapter can call this
    after every commit/composition update without copying patched-Squirrel
    behavior into the frontend.
    """

    def __init__(self, *, candidate_pool_ttl_ms: int = 1200) -> None:
        self.candidate_pool_ttl_ms = max(0, int(candidate_pool_ttl_ms))
        self._cache: _CandidateSourceCache | None = None

    def clear(self) -> None:
        self._cache = None

    def render(
        self,
        *,
        snapshot: RimeContextSnapshot,
        model_predictions: list[ModelPrediction] | tuple[ModelPrediction, ...] | None = None,
        suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...] | None = None,
        raw_commit_text: str = "",
        now_ms: int = 0,
    ) -> PredictionManagerResult:
        context_fingerprint = _context_fingerprint(snapshot.committed_context)
        source_update = model_predictions is not None or suggestions is not None
        mode = (
            InputMode.RAW_INPUT
            if compact_whitespace(raw_commit_text) and not source_update
            else infer_input_mode(snapshot)
        )
        if source_update:
            self._cache = self._updated_cache(
                context_fingerprint=context_fingerprint,
                model_predictions=model_predictions,
                suggestions=suggestions,
                now_ms=now_ms,
            )

        cache = self._cache
        can_reuse = (
            cache is not None
            and context_fingerprint
            and cache.context_fingerprint == context_fingerprint
            and mode in {InputMode.POST_COMMIT_PREDICTING, InputMode.PREFIX_CONSTRAINED_COMPOSING}
        )
        candidate_pool_stale = bool(can_reuse and self._cache_is_stale(cache, now_ms=now_ms))
        if can_reuse and not candidate_pool_stale:
            active_model_predictions = cache.model_predictions
            active_suggestions = cache.suggestions
            reused_candidate_pool = not source_update
        else:
            active_model_predictions = ()
            active_suggestions = ()
            reused_candidate_pool = False

        merge_result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=active_model_predictions,
            suggestions=active_suggestions,
            mode=mode,
            raw_commit_text=raw_commit_text,
        )
        session = resolve_prediction_session(snapshot=snapshot, merge_result=merge_result)
        return PredictionManagerResult(
            merge_result=merge_result,
            session=session,
            display_candidates=merge_result.display_candidates,
            reused_candidate_pool=reused_candidate_pool,
            candidate_pool_active=bool(active_model_predictions or active_suggestions),
            candidate_pool_stale=candidate_pool_stale,
            context_fingerprint=context_fingerprint,
        )

    def _updated_cache(
        self,
        *,
        context_fingerprint: str,
        model_predictions: list[ModelPrediction] | tuple[ModelPrediction, ...] | None,
        suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...] | None,
        now_ms: int,
    ) -> _CandidateSourceCache:
        previous = self._cache if self._cache and self._cache.context_fingerprint == context_fingerprint else None
        return _CandidateSourceCache(
            context_fingerprint=context_fingerprint,
            model_predictions=tuple(model_predictions) if model_predictions is not None else (previous.model_predictions if previous else ()),
            suggestions=tuple(suggestions) if suggestions is not None else (previous.suggestions if previous else ()),
            updated_at_ms=max(0, int(now_ms)),
        )

    def _cache_is_stale(self, cache: _CandidateSourceCache, *, now_ms: int) -> bool:
        if self.candidate_pool_ttl_ms <= 0:
            return False
        return max(0, int(now_ms)) - cache.updated_at_ms > self.candidate_pool_ttl_ms


def _context_fingerprint(committed_context: str) -> str:
    return compact_whitespace(committed_context)[-420:]
