from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from .deepseek_completion import CompletionCandidateDelta
from .active_rag_models import ActiveRagEvidence, ActiveRagFrame
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


def compile_active_rag_candidates_from_evidence(
    evidence_items: Iterable[ActiveRagEvidence],
    *,
    frame: ActiveRagFrame,
    max_candidates: int = 5,
) -> tuple[ActiveRagCandidate, ...]:
    selected = compact_whitespace(frame.selected_text)
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for evidence in evidence_items:
        for text in _candidate_texts_from_evidence(evidence):
            normalized = compact_whitespace(text)
            if not _active_rag_candidate_allowed(normalized, selected_text=selected, seen=seen):
                continue
            seen.add(normalized.lower())
            result.append(
                ActiveRagCandidate(
                    candidate_id=f"active-rag:{_short_id(f'{evidence.evidence_id}:{normalized}')}",
                    text=normalized,
                    insert_text=normalized,
                    source_type=evidence.source_type,
                    source_lane=evidence.source_lane,
                    metadata={
                        "activeRag": True,
                        "activeRagLocal": True,
                        "displayLane": _display_lane(evidence),
                        "badge": _badge(evidence),
                        "placement": frame.placement,
                        "intent": frame.intent,
                        "evidenceId": evidence.evidence_id,
                        "evidencePreviewRedacted": bool(evidence.preview),
                        "tags": list(evidence.tags[:6]),
                        "memoryIds": list(evidence.memory_ids[:4]),
                        "atomIds": list(evidence.atom_ids[:4]),
                        "bookIds": list(evidence.book_ids[:4]),
                    },
                )
            )
            if len(result) >= max(1, int(max_candidates)):
                return tuple(result)
    return tuple(result)


def _active_rag_candidate_allowed(text: str, *, selected_text: str, seen: set[str]) -> bool:
    if not text:
        return False
    if text.lower() in seen:
        return False
    if len(text) > 24:
        return False
    if text.isascii() and any(char.isalpha() for char in text) and len(text) <= 12:
        return False
    if len(text) > 6 and selected_text and text in selected_text:
        return False
    if any(marker in text for marker in ("下一步", "接下来", "根据上述", "可以进行", "可以继续")):
        return False
    if _looks_sensitive(text):
        return False
    return True


def _candidate_texts_from_evidence(evidence: ActiveRagEvidence) -> tuple[str, ...]:
    texts: list[str] = []
    text = compact_whitespace(evidence.text)
    if text:
        texts.append(text)
    metadata = dict(evidence.metadata or {})
    for key in ("bookTitle", "surfaceHint", "candidateText"):
        value = compact_whitespace(str(metadata.get(key) or ""))
        if value:
            texts.insert(0, value)
    return tuple(_unique_texts(texts))


def _display_lane(evidence: ActiveRagEvidence) -> str:
    if evidence.source_type == "memory":
        return "memory_book"
    if evidence.source_type == "phrase":
        return "phrase"
    return "rag_evidence"


def _badge(evidence: ActiveRagEvidence) -> str:
    if evidence.source_type == "memory":
        return "Memory"
    if evidence.source_type == "phrase":
        return "Phrase"
    return "RAG"


def _looks_sensitive(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in ("sk-", "api_key", "apikey", "token=", "password", "cookie")):
        return True
    digits = sum(1 for char in text if char.isdigit())
    return digits >= 12


def _unique_texts(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = compact_whitespace(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _short_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
