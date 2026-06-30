from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import InputSuggestion
from .text_utils import compact_whitespace, split_sentences, truncate_text


class MemoryLike(Protocol):
    memory_id: str
    text: str
    source_ref: str
    score: float
    reason: str
    evidence_preview: str
    tags: tuple[str, ...]
    source_event_id: str | None


@dataclass(frozen=True)
class CompilerOptions:
    max_suggestions: int = 5
    max_surface_chars: int = 42
    max_preview_chars: int = 180
    include_writing_panel_candidates: bool = False


@dataclass(frozen=True)
class RankedMemory:
    memory: MemoryLike
    score: float
    rank: int


class SuggestionCompiler:
    """Turn retrieved memories into input-method suggestions.

    RAG chunks are not input candidates. This compiler is the adapter-owned
    boundary that compresses evidence into short, inspectable, directly usable
    input suggestions.
    """

    def __init__(self, options: CompilerOptions | None = None):
        self.options = options or CompilerOptions()

    def compile(self, ranked_memories: list[RankedMemory]) -> list[InputSuggestion]:
        suggestions: list[InputSuggestion] = []
        for item in ranked_memories:
            memory = item.memory
            source_text = compact_whitespace(memory.text)
            if not source_text:
                continue
            suggestion_type = classify_suggestion(source_text, memory.tags)
            if suggestion_type == "paragraph" and not self.options.include_writing_panel_candidates:
                surface = first_sentence(source_text)
            else:
                surface = source_text
            surface = truncate_text(surface, self.options.max_surface_chars)
            if not surface:
                continue
            suggestion = InputSuggestion(
                suggestion_id=f"sug-{memory.memory_id}",
                surface_text=surface,
                suggestion_type=suggestion_type,
                source_event_id=_optional_int(memory.source_event_id) or item.rank,
                evidence_preview=truncate_text(memory.evidence_preview or source_text, self.options.max_preview_chars),
                confidence=max(0.0, min(1.0, item.score)),
                actions=("commit", "expand", "pin", "downrank", "delete"),
                expanded_evidence=expanded_evidence(memory, source_text),
                metadata={
                    "memory_id": memory.memory_id,
                    "source_ref": memory.source_ref,
                    "reason": memory.reason,
                    "rank": item.rank,
                    "tags": list(memory.tags),
                    "insert_text": source_text,
                    "preview_text": memory.evidence_preview or source_text,
                    "sources": [memory.source_ref],
                },
            )
            suggestions.append(suggestion)
            if len(suggestions) >= self.options.max_suggestions:
                break
        return suggestions


def classify_suggestion(text: str, tags: tuple[str, ...] = ()) -> str:
    tag_set = set(tags)
    if "template" in tag_set:
        return "template"
    if "quote" in tag_set:
        return "quote"
    if "rewrite" in tag_set:
        return "rewrite"
    if "continue" in tag_set or text.endswith(("，", ",")):
        return "continue"
    if "style" in tag_set or "preference" in tag_set:
        return "style_hint"
    if "structure" in tag_set or any(marker in text for marker in ("第一", "第二", "第三", "步骤", "路线")):
        return "structure"
    if len(text) > 120 or len(split_sentences(text)) >= 2:
        return "paragraph"
    if len(text) > 24:
        return "sentence"
    return "phrase"


def first_sentence(text: str) -> str:
    sentences = split_sentences(text)
    return sentences[0] if sentences else text


def expanded_evidence(memory: MemoryLike, source_text: str) -> str:
    preview = memory.evidence_preview or source_text
    return "\n".join(
        [
            memory.source_ref,
            f"reason: {memory.reason}",
            "",
            preview,
        ]
    ).strip()


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
