from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from .deepseek_completion import CompletionCandidateDelta
from .text_utils import compact_whitespace


@dataclass(frozen=True)
class ActiveRagCandidate:
    candidate_id: str
    text: str
    insert_text: str
    source_type: str = "model"
    source_lane: str = "deepseek_v4_flash"
    metadata: dict[str, object] = field(default_factory=dict)


def compile_active_rag_candidates(
    deltas: Iterable[CompletionCandidateDelta],
    *,
    selected_text: str = "",
    max_candidates: int = 5,
) -> tuple[ActiveRagCandidate, ...]:
    selected = compact_whitespace(selected_text)
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for delta in deltas:
        text = compact_whitespace(delta.text)
        if not _active_rag_candidate_allowed(text, selected_text=selected, seen=seen):
            continue
        seen.add(text.lower())
        result.append(
            ActiveRagCandidate(
                candidate_id=f"active-rag:{_short_id(text)}",
                text=text,
                insert_text=compact_whitespace(delta.insert_text or text),
                source_type=delta.source_type,
                source_lane=delta.source_lane,
                metadata={**dict(delta.metadata), "activeRag": True},
            )
        )
        if len(result) >= max(1, int(max_candidates)):
            break
    return tuple(result)


def _active_rag_candidate_allowed(text: str, *, selected_text: str, seen: set[str]) -> bool:
    if not text:
        return False
    if text.lower() in seen:
        return False
    if len(text) > 24:
        return False
    if len(text) > 6 and selected_text and text in selected_text:
        return False
    if any(marker in text for marker in ("下一步", "接下来", "根据上述", "可以进行", "可以继续")):
        return False
    return True


def _short_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
