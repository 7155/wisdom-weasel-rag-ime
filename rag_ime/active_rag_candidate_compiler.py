from __future__ import annotations

import hashlib
import re
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
    max_chars: int = 0,
) -> tuple[ActiveRagCandidate, ...]:
    selected = compact_whitespace(selected_text)
    char_limit = _candidate_char_limit(max_chars)
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for delta in deltas:
        raw_text = _preserve_paragraph_layout(delta.text)
        text = _fit_active_rag_candidate_text(raw_text, max_chars=char_limit)
        if not _active_rag_candidate_allowed(text, selected_text=selected, seen=seen, max_chars=char_limit):
            continue
        seen.add(compact_whitespace(text).lower())
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
    compact = compact_whitespace(text)
    if not compact:
        return False
    if compact.lower() in seen:
        return False
    char_limit = _candidate_char_limit(max_chars)
    if char_limit > 0 and len(text) > char_limit:
        return False

    # Explicit Active RAG output is a user-requested document. Do not reuse the
    # passive IME candidate blacklist here: it rejected valid technical prose,
    # numbers and English identifiers after the remote model had already
    # returned successfully. The provider layer owns protocol parsing; this
    # compiler only enforces structural identity and the optional UI length.
    if selected_text:
        selected = compact_whitespace(selected_text)
        if compact == selected:
            return False
        # A model occasionally returns only the first clause of the selected
        # request. Treat that as input echo, while still allowing normal term
        # overlap in a genuinely new answer.
        if len(compact) >= 8 and selected.startswith(compact):
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
    requested = int(max_chars or 0)
    if requested <= 0:
        return 0
    return max(4, min(12000, requested))


def _context_only_evidence(evidence: ActiveRagEvidence) -> bool:
    return evidence.source_type == "recent_input_context" or evidence.source_lane == "timeline_recent_input"


def _generic_evidence_title(text: str) -> bool:
    value = compact_whitespace(text)
    return value in {"最近输入上下文", "记忆笔记本", "Memory Book", "Daily Book"}


def _fit_active_rag_candidate_text(text: str, *, max_chars: int) -> str:
    value = _preserve_paragraph_layout(text)
    if not value:
        return ""
    limit = _candidate_char_limit(max_chars)
    if limit <= 0:
        return value
    if len(value) <= limit:
        return value
    if limit > 48:
        paragraph = _fit_active_rag_paragraph_text(value, max_chars=limit)
        if paragraph:
            return paragraph
    for segment in _candidate_segments(value):
        if 2 <= len(segment) <= limit:
            return segment
    truncated = value[:limit].rstrip("，。；：、,.!?！？;:")
    return compact_whitespace(truncated)


def _fit_active_rag_paragraph_text(text: str, *, max_chars: int) -> str:
    limit = _candidate_char_limit(max_chars)
    if limit <= 0:
        return _preserve_paragraph_layout(text)
    value = compact_whitespace(text)
    if len(value) <= limit:
        return value
    for paragraph in re.split(r"[\r\n]+", value):
        normalized = compact_whitespace(paragraph)
        if 24 <= len(normalized) <= limit:
            return normalized
    parts = [compact_whitespace(part) for part in re.split(r"(?<=[。！？!?；;])", value)]
    assembled = ""
    for part in parts:
        if not part:
            continue
        if len(assembled + part) > limit:
            break
        assembled += part
    if len(assembled) >= 24:
        return assembled.rstrip("，；：、,.!?！？;:")
    return value[:limit].rstrip("，。；：、,.!?！？;:")


def _candidate_segments(text: str) -> list[str]:
    raw_segments = []
    for part in re_split_candidate_segments(text):
        segment = compact_whitespace(part).strip("，。；：、,.!?！？;: ")
        if segment:
            raw_segments.append(segment)
    return sorted(_unique_texts(raw_segments), key=lambda item: (abs(len(item) - 10), len(item)))


def re_split_candidate_segments(text: str) -> list[str]:
    return re.split(r"[，。；、,.!?！？;:\n]+", text)


def _preserve_paragraph_layout(text: str) -> str:
    value = str(text or "").replace("\\n", "\n").replace("\\r", "\r").replace("\r\n", "\n").replace("\r", "\n")
    lines = [compact_whitespace(line) for line in value.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    result: list[str] = []
    for line in lines:
        if not line and result and not result[-1]:
            continue
        result.append(line)
    return "\n".join(result).strip()


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
