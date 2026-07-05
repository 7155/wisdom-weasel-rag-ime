from __future__ import annotations

from collections import Counter

from .memory_models import MemoryCandidateV2
from .text_utils import compact_whitespace


def select_diverse(candidates: list[MemoryCandidateV2], top_k: int) -> list[MemoryCandidateV2]:
    selected: list[MemoryCandidateV2] = []
    seen_text: set[str] = set()
    seen_source: set[int] = set()
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        normalized_text = compact_whitespace(candidate.normalized_text or candidate.text).lower()
        if normalized_text in seen_text:
            continue
        if candidate.source_event_id is not None and candidate.source_event_id in seen_source:
            continue
        if _too_similar_ngram(candidate, selected):
            continue
        selected.append(candidate)
        seen_text.add(normalized_text)
        if candidate.source_event_id is not None:
            seen_source.add(candidate.source_event_id)
        if len(selected) >= max(1, top_k):
            break
    return selected


def _too_similar_ngram(candidate: MemoryCandidateV2, selected: list[MemoryCandidateV2]) -> bool:
    candidate_ngrams = _char_ngrams(candidate.text)
    if not candidate_ngrams:
        return False
    for item in selected:
        overlap = candidate_ngrams & _char_ngrams(item.text)
        if len(overlap) >= max(2, min(len(candidate_ngrams), 3)):
            return True
    return False


def _char_ngrams(text: str) -> set[str]:
    compact = compact_whitespace(text)
    if len(compact) < 2:
        return set()
    grams = Counter(compact[idx : idx + 2] for idx in range(0, len(compact) - 1))
    return set(grams)
