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
    "MEMORY_SUMMARY",
    "## Memory",
    "# AGENTS.md instructions",
)

_GENERIC_STATUS_PREFIXES = (
    "已完成这一步 git 同步",
    "已完成 git 同步",
    "已经完成 git 同步",
    "已按只读方式调研",
    "已读取",
    "已搜索",
    "已列出",
    "本轮继续推进",
    "继续推进了一轮",
    "导入完成",
    "提交完成",
    "忽略规则已补",
    "现在做 Git",
    "我先",
    "我会先",
    "我接下来",
    "我现在",
    "我已经",
    "接下来我",
    "这个截图说明",
    "**只读结论**",
    "只读结论",
)

_PRODUCT_CANDIDATE_MARKERS = (
    "我的判断是",
    "我的方案是",
    "我建议",
    "建议",
    "目标是",
    "核心是",
    "重点是",
    "亮点是",
    "原则是",
    "最优方案",
    "最终方案",
    "一句话",
)

_INSTRUCTION_FRAGMENT_PREFIXES = (
    "你要",
    "你看",
    "你先",
    "你可以",
    "可以把",
    "如果 macOS",
    "只会在",
)

_LOW_VALUE_SURFACES = {
    "啊",
    "阿",
    "测试",
    "分析",
    "验证",
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
    "当前",
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

_LOW_VALUE_MEMORY_TOKENS = _LOW_VALUE_SURFACES | {
    "问题",
    "流程",
    "输出",
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
            if _skip_memory_by_tags(memory.tags):
                continue
            raw_source_text = memory.text or ""
            source_text = compact_whitespace(raw_source_text)
            if not source_text:
                continue
            if _is_low_value_memory_text(source_text):
                continue
            suggestion_type = classify_suggestion(source_text, memory.tags)
            surface = compress_surface_text(
                raw_source_text,
                tags=memory.tags,
                suggestion_type=suggestion_type,
                max_chars=self.options.max_surface_chars,
            )
            if not surface or not _is_meaningful_suggestion_surface(surface):
                continue
            insert_text = compile_candidate_insert_text(surface)
            insert_norm = _suggestion_insert_norm(insert_text)
            if insert_norm in seen_insert_texts:
                continue
            seen_insert_texts.add(insert_norm)
            state = dict(getattr(memory, "state", {}) or {})
            score_breakdown = state.get("score_breakdown")
            metadata = {
                "memory_id": memory.memory_id,
                "source_ref": memory.source_ref,
                "reason": memory.reason,
                "rank": item.rank,
                "tags": list(memory.tags),
                "source_type": _source_type_from_tags(memory.tags),
                "insert_text": insert_text,
                "preview_text": memory.evidence_preview or source_text,
                "sources": [memory.source_ref],
                "state": state,
                **build_pinyin_metadata(surface),
            }
            if score_breakdown is not None:
                metadata["score_breakdown"] = score_breakdown
            suggestion = InputSuggestion(
                suggestion_id=f"sug-{memory.memory_id}",
                surface_text=surface,
                suggestion_type=suggestion_type,
                source_event_id=_optional_int(memory.source_event_id) or item.rank,
                evidence_preview=truncate_text(memory.evidence_preview or source_text, self.options.max_preview_chars),
                confidence=max(0.0, min(1.0, item.score)),
                actions=("commit", "expand", "pin", "downrank", "delete"),
                expanded_evidence=expanded_evidence(memory, source_text),
                metadata=metadata,
            )
            suggestions.append(suggestion)
            if len(suggestions) >= self.options.max_suggestions:
                break
        return suggestions


def _suggestion_insert_norm(text: str) -> str:
    return compact_whitespace(text).lower()


def compile_candidate_insert_text(surface_text: str) -> str:
    """Return the text committed by number selection in the real IME panel.

    Full RAG evidence stays in `expanded_evidence` / `preview_text`. Selecting a
    candidate must commit the concise candidate span, not an entire retrieved
    history paragraph.
    """

    return compact_whitespace(surface_text)


def _skip_memory_by_tags(tags: tuple[str, ...]) -> bool:
    tag_set = {str(tag).lower() for tag in tags}
    if "role:event_msg" in tag_set or "role:assistant" in tag_set:
        return True
    if "source:rag" in tag_set or "source:model" in tag_set:
        return True
    if "runtime-noise" in tag_set:
        return True
    return False


def _source_type_from_tags(tags: tuple[str, ...]) -> str:
    tag_set = {str(tag).lower() for tag in tags}
    if tag_set.intersection({"rag", "embedding", "retrieval", "suggestion-compiler"}):
        return "rag"
    if tag_set.intersection({"memory", "frequency", "phrase-memory", "user-input", "curated"}):
        return "memory"
    return "rag"


def _is_meaningful_suggestion_surface(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return False
    if _is_low_value_memory_text(surface):
        return False
    if surface in _LOW_VALUE_SURFACES:
        return False
    if re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", surface):
        return False
    if len(surface) == 1 and _CJK_RE.fullmatch(surface):
        return False
    return True


def _is_low_value_memory_text(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return True
    if surface in _LOW_VALUE_SURFACES:
        return True
    if surface.startswith(("请继续做一个窄任务", "请继续做一个任务")):
        return True
    if ("做只读调研" in surface or "只读方式调研" in surface) and any(
        marker in surface for marker in ("不编辑文件", "不修改文件", "不要改文件", "未修改文件")
    ):
        return True
    if re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", surface):
        return True
    parts = [part for part in re.split(r"[\s,，、;；。.!?！？/]+", surface) if part]
    if not parts:
        return True
    if len(parts) <= 4 and all(part in _LOW_VALUE_MEMORY_TOKENS for part in parts):
        return True
    if len(surface) <= 8 and all(part in _LOW_VALUE_MEMORY_TOKENS for part in parts):
        return True
    return False


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
    """Return compact candidate-bar text while preserving full evidence elsewhere."""

    raw = text or ""
    compact = compact_whitespace(raw)
    if not compact:
        return ""
    cleaned_compact = _clean_surface_segment(compact)
    if _looks_like_surface_noise(compact) or _looks_like_surface_noise(cleaned_compact):
        return ""
    if (
        len(cleaned_compact) <= max_chars
        and not _looks_like_surface_noise(cleaned_compact)
        and not _contains_product_candidate_marker(cleaned_compact)
    ):
        return cleaned_compact

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

    for clause in _extract_product_candidate_clauses(raw):
        add_candidate(clause, source_score=2.2)

    for example in _extract_ime_candidate_examples(raw):
        add_candidate(example, source_score=2.8)

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
    text = _remove_cjk_spacing(text)
    text = _TRANSCRIPT_PREFIX_RE.sub("", text)
    text = _TOOL_PREFIX_RE.sub("", text)
    text = _BULLET_PREFIX_RE.sub("", text)
    text = re.sub(r"^\*\*\s*>\s*", "", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = text.replace("**", "")
    text = re.sub(r"^\*\*(只读结论|结论|建议|问题|变化|验证)\*\*\s*[:：]?\s*", "", text)
    text = re.sub(r"^(问题|结论|建议|变化|验证|Changes|Findings|Next|Decision)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    if text.startswith("Chunk ID:") and " Output:" in text:
        text = text.split(" Output:", 1)[1]
    return compact_whitespace(text.strip("` \t"))


def _remove_cjk_spacing(text: str) -> str:
    previous = ""
    current = text
    while current != previous:
        previous = current
        current = re.sub(r"([\u3400-\u9fff])\s+([\u3400-\u9fff])", r"\1\2", current)
    return current


def _extract_product_candidate_clauses(text: str) -> list[str]:
    compact = _remove_cjk_spacing(compact_whitespace(text))
    if not compact:
        return []
    results: list[str] = []
    for marker in _PRODUCT_CANDIDATE_MARKERS:
        start = compact.find(marker)
        if start < 0:
            continue
        tail = compact[start + len(marker) :]
        tail = re.sub(r"^[：:，,\s>*-]+", "", tail)
        for sentence in split_sentences(tail) or [tail]:
            cleaned = _clean_surface_segment(sentence)
            if "，" in cleaned:
                head = cleaned.split("，", 1)[0]
                if len(head) >= 8:
                    cleaned = head
            if cleaned and 4 <= len(cleaned) <= 48 and not _looks_like_surface_noise(cleaned):
                results.append(cleaned)
                break
    for match in re.finditer(r"(?:^|[。！？；;\n])(?:目标|核心|方案|原则|结论|建议|亮点)\s*[:：]\s*([^。！？；;\n]{4,48})", compact):
        cleaned = _clean_surface_segment(match.group(1))
        if cleaned and not _looks_like_surface_noise(cleaned):
            results.append(cleaned)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in results:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:4]


def _extract_ime_candidate_examples(text: str) -> list[str]:
    compact = _remove_cjk_spacing(compact_whitespace(text))
    if not compact or not any(marker in compact for marker in ("候选", "预测", "拼音", "RAG", "记忆")):
        return []
    results: list[str] = []
    prefix_results: list[str] = []
    matches = list(re.finditer(r"(?:^|[\s:：|])(?:[1-9][.)、]?\s+)", compact))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compact)
        window = compact[max(0, match.start() - 96) : match.start()]
        if not any(
            marker in window
            for marker in ("显示预测候选", "候选变成", "预测候选", "拼音匹配", "[RAG]", "[记忆]", "[LLM]")
        ):
            continue
        segment = compact[match.end() : end]
        head = re.split(r"\s*(?:\[[^\]]+\])|[。！？；;\n]", segment, maxsplit=1)[0]
        cleaned = _clean_surface_segment(head)
        cleaned = re.sub(r"\s*\[[^\]]+\]\s*$", "", cleaned)
        cleaned = compact_whitespace(cleaned)
        if not cleaned or not _CJK_RE.search(cleaned):
            continue
        if len(cleaned) < 4 or len(cleaned) > 42:
            continue
        if _looks_like_surface_noise(cleaned):
            continue
        if any(marker in window for marker in ("候选变成", "拼音匹配", "PREFIX_CONSTRAINED", "prefix")):
            prefix_results.append(cleaned)
        else:
            results.append(cleaned)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in [*prefix_results, *results]:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:6]


def _contains_product_candidate_marker(text: str) -> bool:
    compact = _remove_cjk_spacing(compact_whitespace(text))
    return any(marker in compact for marker in _PRODUCT_CANDIDATE_MARKERS)


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
    stripped = _remove_cjk_spacing(text.strip())
    if not stripped:
        return True
    if _is_low_value_memory_text(stripped):
        return True
    if stripped.startswith(_SKIP_SURFACE_PREFIXES):
        return True
    if stripped.startswith(_GENERIC_STATUS_PREFIXES):
        return True
    if stripped.startswith(("请继续做一个窄任务", "请继续做一个任务")):
        return True
    if _looks_like_short_instruction_surface(stripped):
        return True
    if stripped.startswith(_INSTRUCTION_FRAGMENT_PREFIXES) and len(stripped) <= 36:
        return True
    if stripped.startswith(("(eval):", "+-", "-+", "+++", "---")):
        return True
    if _FILE_HIT_PREFIX_RE.match(stripped):
        return True
    if stripped.startswith(("/Volumes/", "/Users/", "~/")) and len(stripped.split()) <= 2:
        return True
    if "验证模型指令" in stripped:
        return True
    lowered = stripped.lower()
    if (
        "memory_summary" in lowered
        or "rollout_summaries" in lowered
        or "<subagent_notification>" in lowered
        or "codex_internal_context" in lowered
        or "index.ts 先改成依赖 core" in lowered
        or "read implementation-goal.md" in lowered
        or "searched for " in lowered
        or "listed files " in lowered
        or "py 通过" in stripped
        or "git diff --check" in stripped
        or "installation.yaml" in lowered
        or "管理员密码" in stripped
        or "未跟踪" in stripped
    ):
        return True
    if "不是目的" in stripped and len(stripped) <= 40:
        return True
    if stripped.startswith(("目前也没想到", "现在也没想到", "还没有想到")) and len(stripped) <= 48:
        return True
    if stripped.startswith(("我目前没有想到", "目前没有想到", "我还没想到")) and len(stripped) <= 48:
        return True
    if re.search(r"(?:0\\.5B|3\\.5B|4B|7B|8B|14B)", stripped) and len(stripped) <= 64:
        return True
    if stripped.startswith(("然后我不是", "就是这个", "这个输入法")) and len(stripped) <= 48:
        return True
    if stripped.startswith(("所以一方面", "另一方面也", "就是用户选择", "就是这个输入法，就首候选")):
        return True
    if stripped.endswith(("?", "？")) and len(stripped) <= 80:
        return True
    if any(marker in stripped for marker in ("打不了字", "没法输入", "没有任何输出", "完全没有任何输出")):
        return True
    if any(marker in stripped for marker in ("你看一下", "你参考", "你先用", "你把")) and len(stripped) <= 80:
        return True
    if "esc to interrupt" in stripped or "yield_time_ms" in stripped or "max_output_tokens" in stripped:
        return True
    if stripped in {"{", "}", "[", "]"}:
        return True
    return False


def _looks_like_short_instruction_surface(text: str) -> bool:
    stripped = _remove_cjk_spacing(compact_whitespace(text)).rstrip("。.!！")
    if not stripped:
        return False
    if stripped.startswith(("要求：", "要求:")) and re.search(r"\d+[).、]", stripped):
        return True
    if stripped.startswith(("不编辑文件", "不修改文件", "只回传路径", "只返回路径")):
        return True
    if len(stripped) > 36:
        return False
    if stripped in {"不要改文件", "不要修改文件", "不要动文件", "不要提交", "不要直接写"}:
        return True
    if stripped.startswith(("不要改", "不要修改", "不要动")) and "文件" in stripped:
        return True
    if stripped.startswith(("请继续做", "请给我文件路径", "请先", "你需要")):
        return True
    if stripped.startswith(("给出推荐排序", "优先官方文档", "关注 TTFT", "明确哪些方案适合")):
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
    parts = [
        memory.source_ref,
        f"reason: {memory.reason}",
        "",
        preview,
    ]
    source = compact_whitespace(source_text)
    if source and source != compact_whitespace(preview):
        parts.extend(["", source])
    return "\n".join(parts).strip()


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
