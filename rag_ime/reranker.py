from __future__ import annotations

from typing import Any, Mapping

from .text_utils import compact_whitespace


SOURCE_PRIORS = {
    "rime": 0.35,
    "lexicon": 0.35,
    "model": 0.28,
    "rag": 0.18,
    "memory": 0.24,
    "raw_english": 0.08,
}


def rerank_candidate_dicts(
    candidates: list[Mapping[str, Any]],
    *,
    query: str = "",
    recent_context: str = "",
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """Rank mixed Rime/model/RAG/memory candidates while preserving Rime fallback."""

    scored: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    query_norm = _norm(query)
    context_norm = _norm(recent_context)
    for original_rank, candidate in enumerate(candidates, start=1):
        text = compact_whitespace(str(candidate.get("text") or candidate.get("surface") or ""))
        if not text:
            continue
        source = _source_type(candidate)
        duplicate = _norm(text) in seen_texts
        if not duplicate:
            seen_texts.add(_norm(text))
        old_input_echo = _is_old_input_echo(text, query_norm=query_norm, context_norm=context_norm)
        score, breakdown = _score_candidate(
            candidate,
            text=text,
            source=source,
            original_rank=original_rank,
            duplicate=duplicate,
            old_input_echo=old_input_echo,
        )
        scored.append(
            {
                "text": text,
                "source": source,
                "originalRank": original_rank,
                "score": round(score, 4),
                "duplicate": duplicate,
                "oldInputEcho": old_input_echo,
                "scoreBreakdown": breakdown,
                "metadata": dict(candidate.get("metadata") or {}) if isinstance(candidate.get("metadata"), dict) else {},
            }
        )

    ranked = sorted(scored, key=lambda item: (-float(item["score"]), int(item["originalRank"])))
    limited = ranked[: max(1, max_candidates)]
    _ensure_rime_fallback(scored=scored, limited=limited, max_candidates=max(1, max_candidates))
    for rank, item in enumerate(limited, start=1):
        item["rank"] = rank
    return limited


def _score_candidate(
    candidate: Mapping[str, Any],
    *,
    text: str,
    source: str,
    original_rank: int,
    duplicate: bool,
    old_input_echo: bool,
) -> tuple[float, dict[str, float]]:
    rank_prior = max(0.0, 0.22 - (original_rank - 1) * 0.025)
    source_prior = SOURCE_PRIORS.get(source, 0.0)
    confidence = _float(candidate.get("confidence")) * 0.18
    accepted_bonus = min(0.22, _float(candidate.get("acceptedCount") or candidate.get("accepted_count")) * 0.035)
    skipped_penalty = min(0.2, _float(candidate.get("skippedCount") or candidate.get("skipped_count")) * 0.04)
    pinned_bonus = 0.18 if bool(candidate.get("pinned")) else 0.0
    length_penalty = 0.08 if len(text) > 24 else 0.0
    duplicate_penalty = 0.32 if duplicate else 0.0
    echo_penalty = 0.38 if old_input_echo else 0.0
    forbidden_penalty = 1.0 if bool(candidate.get("forbidden") or candidate.get("tombstoned")) else 0.0
    score = (
        source_prior
        + rank_prior
        + confidence
        + accepted_bonus
        + pinned_bonus
        - skipped_penalty
        - length_penalty
        - duplicate_penalty
        - echo_penalty
        - forbidden_penalty
    )
    breakdown = {
        "sourcePrior": round(source_prior, 4),
        "rankPrior": round(rank_prior, 4),
        "confidence": round(confidence, 4),
        "acceptedBonus": round(accepted_bonus, 4),
        "pinnedBonus": pinned_bonus,
        "skippedPenalty": round(-skipped_penalty, 4),
        "lengthPenalty": round(-length_penalty, 4),
        "duplicatePenalty": round(-duplicate_penalty, 4),
        "oldInputEchoPenalty": round(-echo_penalty, 4),
        "forbiddenPenalty": round(-forbidden_penalty, 4),
    }
    return score, breakdown


def _ensure_rime_fallback(*, scored: list[dict[str, Any]], limited: list[dict[str, Any]], max_candidates: int) -> None:
    if any(item.get("source") == "rime" for item in limited):
        return
    fallback = next((item for item in scored if item.get("source") == "rime"), None)
    if fallback is None:
        return
    if len(limited) < max_candidates:
        limited.append(fallback)
    else:
        limited[-1] = fallback


def _source_type(candidate: Mapping[str, Any]) -> str:
    raw = compact_whitespace(str(candidate.get("source") or candidate.get("sourceType") or candidate.get("type") or ""))
    source = raw.lower().replace("-", "_")
    if source in {"word", "dict", "dictionary"}:
        return "lexicon"
    if source in {"llm", "prediction", "model_prediction"}:
        return "model"
    return source or "unknown"


def _is_old_input_echo(text: str, *, query_norm: str, context_norm: str) -> bool:
    text_norm = _norm(text)
    if not text_norm:
        return False
    if query_norm and text_norm == query_norm:
        return True
    return bool(context_norm and len(text_norm) >= 4 and text_norm in context_norm[-120:])


def _norm(text: str) -> str:
    return compact_whitespace(text).casefold()


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
