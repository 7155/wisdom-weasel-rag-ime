from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable

from .anti_echo import candidate_has_keyword_echo, candidate_has_self_repetition, repeat_norm
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
    max_chars: int = 24,
) -> tuple[ActiveRagCandidate, ...]:
    selected = compact_whitespace(selected_text)
    char_limit = _candidate_char_limit(max_chars)
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for delta in deltas:
        raw_text = compact_whitespace(delta.text)
        text = _fit_active_rag_candidate_text(raw_text, max_chars=char_limit)
        if not _active_rag_candidate_allowed(text, selected_text=selected, seen=seen, max_chars=char_limit):
            continue
        seen.add(text.lower())
        metadata = dict(delta.metadata)
        if text != raw_text:
            metadata["lengthGoverned"] = True
            metadata["rawTextChars"] = len(raw_text)
            metadata["maxChars"] = char_limit
        result.append(
            ActiveRagCandidate(
                candidate_id=f"active-rag:{_short_id(text)}",
                text=text,
                insert_text=_fit_active_rag_candidate_text(delta.insert_text or text, max_chars=char_limit),
                source_type=delta.source_type,
                source_lane=delta.source_lane,
                metadata={**metadata, "activeRag": True},
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
    max_chars: int = 24,
) -> tuple[ActiveRagCandidate, ...]:
    selected = compact_whitespace(frame.selected_text)
    char_limit = _candidate_char_limit(max_chars)
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for evidence in evidence_items:
        if _context_only_evidence(evidence):
            continue
        for text in _candidate_texts_from_evidence(evidence):
            raw_text = compact_whitespace(text)
            normalized = _fit_active_rag_candidate_text(raw_text, max_chars=char_limit)
            if not _active_rag_candidate_allowed(normalized, selected_text=selected, seen=seen, max_chars=char_limit):
                continue
            seen.add(normalized.lower())
            length_governed = normalized != raw_text
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
                        "lengthGoverned": length_governed,
                        "rawTextChars": len(raw_text),
                        "maxChars": char_limit,
                    },
                )
            )
            if len(result) >= max(1, int(max_candidates)):
                return tuple(result)
    return tuple(result)


def _active_rag_candidate_allowed(text: str, *, selected_text: str, seen: set[str], max_chars: int = 24) -> bool:
    if not text:
        return False
    if text.lower() in seen:
        return False
    if len(text) > _candidate_char_limit(max_chars):
        return False
    if text.isascii() and any(char.isalpha() for char in text) and len(text) <= 12:
        return False
    if not _contains_cjk(text):
        return False
    if candidate_has_self_repetition(text):
        return False
    if candidate_has_keyword_echo(text):
        return False
    if selected_text:
        if repeat_norm(text) == repeat_norm(selected_text):
            return False
        if len(text) >= 8 and text in selected_text:
            return False
    if any(marker in text for marker in ("下一步", "接下来", "根据上述", "可以进行", "可以继续")):
        return False
    if _looks_sensitive(text):
        return False
    return True


def _candidate_texts_from_evidence(evidence: ActiveRagEvidence) -> tuple[str, ...]:
    texts: list[str] = []
    metadata = dict(evidence.metadata or {})
    surface_hints = metadata.get("surfaceHints") or metadata.get("surface_hints")
    if isinstance(surface_hints, (list, tuple)):
        for value in reversed(surface_hints[:4]):
            hint = compact_whitespace(str(value))
            if hint:
                texts.insert(0, hint)
    for key in ("bookTitle", "surfaceHint", "candidateText", "title"):
        value = compact_whitespace(str(metadata.get(key) or ""))
        if value and not _generic_evidence_title(value):
            texts.insert(0, value)
    text = compact_whitespace(evidence.text)
    if text:
        texts.append(text)
    return tuple(_unique_texts(texts))


def _candidate_char_limit(max_chars: int) -> int:
    return max(4, min(48, int(max_chars or 24)))


def _context_only_evidence(evidence: ActiveRagEvidence) -> bool:
    return evidence.source_type == "recent_input_context" or evidence.source_lane == "timeline_recent_input"


def _generic_evidence_title(text: str) -> bool:
    value = compact_whitespace(text)
    return value in {"最近输入上下文", "记忆笔记本", "Memory Book", "Daily Book"}


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _fit_active_rag_candidate_text(text: str, *, max_chars: int) -> str:
    value = compact_whitespace(text)
    if not value:
        return ""
    limit = _candidate_char_limit(max_chars)
    if len(value) <= limit:
        return value
    for segment in _candidate_segments(value):
        if 2 <= len(segment) <= limit:
            return segment
    truncated = value[:limit].rstrip("，。；：、,.!?！？;:")
    return compact_whitespace(truncated)


def _candidate_segments(text: str) -> list[str]:
    raw_segments = []
    for part in re_split_candidate_segments(text):
        segment = compact_whitespace(part).strip("，。；：、,.!?！？;: ")
        if segment:
            raw_segments.append(segment)
    return sorted(_unique_texts(raw_segments), key=lambda item: (abs(len(item) - 10), len(item)))


def re_split_candidate_segments(text: str) -> list[str]:
    return re.split(r"[，。；、,.!?！？;:\n]+", text)


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
