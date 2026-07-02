from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .models import InputSuggestion
from .pinyin_index import build_pinyin_metadata
from .text_utils import compact_whitespace, split_sentences, truncate_text


_ASCII_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{3,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TRANSCRIPT_PREFIX_RE = re.compile(r"^\[\d+\]\s+(?:assistant|user|tool(?:\s+[^:]{0,80})?)\s*:\s*", re.IGNORECASE)
_TOOL_PREFIX_RE = re.compile(r"^tool(?:\s+[^:]{0,80})?\s*:\s*", re.IGNORECASE)
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_FILE_HIT_PREFIX_RE = re.compile(r"^[\w./~ -]+\.(?:md|py|ts|tsx|js|json|swift|m|mm|h|cpp|hpp|yaml|yml):\d+:")

_SKIP_SURFACE_PREFIXES = (
    "*** Begin Patch",
    "*** End Patch",
    "*** Update File:",
    "*** Add File:",
    "diff --git",
    "index ",
    "@@",
    "+++ ",
    "--- ",
    "Chunk ID:",
    "Wall time:",
    "Process exited",
    "Original token count:",
    "Output:",
    "# Files mentioned",
    "<subagent_notification>",
    "<codex_internal_context",
)

_GENERIC_STATUS_PREFIXES = (
    "已完成这一步 git 同步",
    "已完成 git 同步",
    "已经完成 git 同步",
    "本轮继续推进",
    "继续推进了一轮",
    "提交完成",
    "忽略规则已补",
    "**只读结论**",
    "只读结论",
)

_LOW_VALUE_SURFACES = {
    "啊",
    "阿",
    "测试",
    "分析",
    "并且",
    "但是",
    "呃",
    "嗯",
    "额",
    "或者",
    "基于",
    "加油",
    "根据",
    "生成",
    "假设",
    "现在",
    "目前",
    "呐",
    "哦",
    "噢",
    "然后",
    "深度",
    "唔",
    "的",
    "了",
    "和",
    "是",
    "当",
}


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
        seen_insert_texts: set[str] = set()
        for item in ranked_memories:
            memory = item.memory
            raw_source_text = memory.text or ""
            source_text = compact_whitespace(raw_source_text)
            if not source_text:
                continue
            insert_norm = _suggestion_insert_norm(source_text)
            if insert_norm in seen_insert_texts:
                continue
            seen_insert_texts.add(insert_norm)
            suggestion_type = classify_suggestion(source_text, memory.tags)
            surface = compress_surface_text(
                raw_source_text,
                tags=memory.tags,
                suggestion_type=suggestion_type,
                max_chars=self.options.max_surface_chars,
            )
            if not surface or not _is_meaningful_suggestion_surface(surface):
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
                    "state": dict(getattr(memory, "state", {}) or {}),
                    **build_pinyin_metadata(surface),
                },
            )
            suggestions.append(suggestion)
            if len(suggestions) >= self.options.max_suggestions:
                break
        return suggestions


def _suggestion_insert_norm(text: str) -> str:
    return compact_whitespace(text).lower()


def _is_meaningful_suggestion_surface(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return False
    if surface in _LOW_VALUE_SURFACES:
        return False
    if re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", surface):
        return False
    if len(surface) == 1 and _CJK_RE.fullmatch(surface):
        return False
    return True


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


def compress_surface_text(
    text: str,
    *,
    tags: tuple[str, ...] = (),
    suggestion_type: str = "",
    max_chars: int = 42,
) -> str:
    """Return compact candidate-bar text while preserving full insert text elsewhere."""

    raw = text or ""
    compact = compact_whitespace(raw)
    if not compact:
        return ""
    if _looks_like_surface_noise(compact) or _looks_like_surface_noise(_clean_surface_segment(compact)):
        return ""
    if len(compact) <= max_chars and not _looks_like_surface_noise(compact):
        return compact

    candidates: list[tuple[float, int, str]] = []
    index = 0

    def add_candidate(segment: str, *, source_score: float = 0.0) -> None:
        nonlocal index
        cleaned = _clean_surface_segment(segment)
        if not cleaned or _looks_like_surface_noise(cleaned):
            return
        candidates.append((_surface_candidate_score(cleaned, tags, suggestion_type) + source_score, -index, cleaned))
        index += 1

    for line in raw.splitlines():
        if _BULLET_PREFIX_RE.match(line):
            add_candidate(line, source_score=1.1)
        else:
            add_candidate(line)

    for sentence in split_sentences(raw):
        add_candidate(sentence)

    inferred_summary = _inferred_surface_identifier_summary(compact)
    if inferred_summary:
        add_candidate(inferred_summary, source_score=3.0)

    identifier_summary = _surface_identifier_summary(compact, max_chars=max_chars)
    if identifier_summary:
        add_candidate(identifier_summary, source_score=1.45)

    add_candidate(compact, source_score=-0.4)

    if not candidates:
        fallback = _clean_surface_segment(compact) or compact
        if _looks_like_surface_noise(fallback):
            return ""
        return truncate_text(fallback, max_chars)

    _, _, best = max(candidates)
    return truncate_text(best, max_chars)


def _clean_surface_segment(segment: str) -> str:
    text = compact_whitespace(segment)
    if not text:
        return ""
    text = _TRANSCRIPT_PREFIX_RE.sub("", text)
    text = _TOOL_PREFIX_RE.sub("", text)
    text = _BULLET_PREFIX_RE.sub("", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"^\*\*(只读结论|结论|建议|问题|变化|验证)\*\*\s*[:：]?\s*", "", text)
    text = re.sub(r"^(问题|结论|建议|变化|验证|Changes|Findings|Next|Decision)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    if text.startswith("Chunk ID:") and " Output:" in text:
        text = text.split(" Output:", 1)[1]
    return compact_whitespace(text.strip("` \t"))


def _surface_identifier_summary(text: str, *, max_chars: int) -> str:
    identifiers: list[str] = []
    seen: set[str] = set()
    for match in _ASCII_IDENTIFIER_RE.finditer(text or ""):
        token = match.group(0).strip("`.,;:()[]{}")
        lowered = token.lower()
        if lowered in seen or not _is_surface_identifier(token):
            continue
        seen.add(lowered)
        identifiers.append(token)
        if len(" / ".join(identifiers)) >= max_chars:
            break
    if not identifiers:
        return ""
    if len(identifiers) == 1 and _CJK_RE.search(text) and not identifiers[0].startswith("RAG_IME_"):
        return ""
    return " / ".join(identifiers)


def _inferred_surface_identifier_summary(text: str) -> str:
    compact = compact_whitespace(text)
    lowered = compact.lower()
    identifiers: list[str] = []

    def add(*tokens: str) -> None:
        for token in tokens:
            if token and token not in identifiers:
                identifiers.append(token)

    if "embedding endpoint" in lowered and (
        "wsl" in lowered or "openai-compatible" in lowered or "rag_ime_embedding_provider" in lowered
    ):
        add("RAG_IME_EMBEDDING_BASE_URL", "RAG_IME_EMBEDDING_MODEL")
    if (
        "maxmodelsidecandidates" in lowered
        or "模型候选挤掉" in compact
        or ("最多 1 个模型" in compact and "side" in lowered)
        or ("model" in lowered and "side slots" in lowered and "占满" in compact)
    ):
        add("maxModelSideCandidates")
    if identifiers and ("剩余" in compact or "remaining" in lowered) and ("rag" in lowered or "记忆" in compact):
        add("ragKeepsRemainingSideSlots")
    return " / ".join(identifiers)


def _is_surface_identifier(token: str) -> bool:
    if len(token) < 3:
        return False
    lowered = token.lower()
    if lowered in {
        "add",
        "and",
        "apply_patch",
        "assistant",
        "codex",
        "commit",
        "debug",
        "docs",
        "expectedterms",
        "file",
        "from",
        "git",
        "json",
        "local",
        "memory",
        "model",
        "output",
        "python3",
        "rag",
        "source",
        "tests",
        "tool",
        "with",
    }:
        return False
    if re.fullmatch(r"[a-f0-9]{6,40}", lowered):
        return False
    if "_" in token or "+" in token or "#" in token:
        return True
    if token.isupper() and len(token) >= 3:
        return True
    if any(char.isupper() for char in token[1:]):
        return True
    if "-" in token and any(part for part in token.split("-") if part and not part.islower()):
        return True
    return False


def _looks_like_surface_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith(_SKIP_SURFACE_PREFIXES):
        return True
    if stripped.startswith(("(eval):", "+-", "-+", "+++", "---")):
        return True
    if _FILE_HIT_PREFIX_RE.match(stripped):
        return True
    if stripped.startswith(("/Volumes/", "/Users/", "~/")) and len(stripped.split()) <= 2:
        return True
    if stripped in {"{", "}", "[", "]"}:
        return True
    return False


def _surface_candidate_score(text: str, tags: tuple[str, ...], suggestion_type: str) -> float:
    length = len(text)
    score = 0.0
    if 8 <= length <= 32:
        score += 3.0
    elif 4 <= length <= 48:
        score += 2.0
    elif length > 48:
        score += 0.8
    else:
        score -= 1.0

    if _CJK_RE.search(text):
        score += 0.7
    if _ASCII_IDENTIFIER_RE.search(text):
        score += 0.35
    if suggestion_type in {"structure", "template", "style_hint"}:
        score += 0.25

    lowered = text.lower()
    for tag in tags:
        if tag and str(tag).lower() in lowered:
            score += 0.2

    if text.startswith(_GENERIC_STATUS_PREFIXES):
        score -= 2.5
    if _TRANSCRIPT_PREFIX_RE.match(text) or _TOOL_PREFIX_RE.match(text):
        score -= 1.0
    return score


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
