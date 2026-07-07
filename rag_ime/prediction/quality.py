from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from rag_ime.text_utils import compact_whitespace


LOW_VALUE_GENERIC_TERMS = {
    "机器学习",
    "人工智能",
    "输入法",
    "继续",
    "然后",
    "一下",
    "这个",
    "那个",
    "可以",
    "问题",
}


@dataclass(frozen=True)
class CandidateQualityContext:
    committed_context: str = ""
    commit_preview: str = ""
    existing_candidates: tuple[str, ...] = ()
    strong_terms: tuple[str, ...] = ()


def reject_context_echo(candidate: str, committed_context: str = "", commit_preview: str = "") -> bool:
    surface = _compact(candidate)
    if not surface:
        return True
    return _is_echo(surface, committed_context) or _is_echo(surface, commit_preview)


def reject_prompt_leak(candidate: str) -> bool:
    surface = _compact(candidate)
    if not surface:
        return True
    if re.search(r"(?i)(system prompt|developer message)", surface):
        return True
    if re.search(r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])", surface):
        return True
    if surface.startswith(("{", "[", "```")) and any(marker in surface for marker in ("schemaVersion", "session", "request")):
        return True
    if _looks_like_frontend_trace_leak(surface):
        return True
    return False


def _looks_like_frontend_trace_leak(surface: str) -> bool:
    if re.search(r"(?i)[\"']?(sessionId|requestSeq|frontendRevision)[\"']?\s*[:=]", surface):
        return True
    if re.search(r"(?i)\b(sessionId|frontendRevision)\b", surface):
        return True
    if re.search(r"(?i)\brequestSeq\b", surface):
        concept_markers = ("stale", "guard", "旧候选", "覆盖", "新输入", "异步", "保护")
        return not any(marker in surface for marker in concept_markers)
    return False


def reject_generic_low_value(candidate: str, *, context_terms: Iterable[str] = ()) -> bool:
    surface = _compact(candidate)
    if not surface:
        return True
    terms = {_compact(term).lower() for term in context_terms if _compact(term)}
    if surface in LOW_VALUE_GENERIC_TERMS and surface.lower() not in terms:
        return True
    if surface in {"打一下再", "再打一下", "作为输入法候选"}:
        return True
    return len(surface) <= 1


def reject_old_history_fragment(candidate: str) -> bool:
    surface = _compact(candidate)
    if not surface:
        return True
    if len(surface) > 80:
        return True
    old_fragment_markers = (
        "然后我还有个需求",
        "我输入法切成豆包",
        "你没有记录",
        "不然这个输入法",
        "traceback",
        "exception",
        "报错",
    )
    lowered = surface.lower()
    return any(marker.lower() in lowered for marker in old_fragment_markers)


def score_post_commit_candidate(candidate: str, context: CandidateQualityContext) -> float:
    surface = _compact(candidate)
    if _reject_common(surface, context):
        return 0.0
    score = 0.45
    if 3 <= len(surface) <= 24:
        score += 0.25
    if _has_meaningful_overlap(surface, context.committed_context, context.commit_preview):
        score += 0.15
    if any(term and term in surface for term in context.strong_terms):
        score += 0.15
    return min(score, 1.0)


def score_memory_candidate(candidate: str, context: CandidateQualityContext, metadata: Mapping[str, object] | None = None) -> float:
    surface = _compact(candidate)
    if _reject_common(surface, context):
        return 0.0
    metadata = metadata or {}
    score = 0.35
    state = metadata.get("state") if isinstance(metadata.get("state"), Mapping) else {}
    raw_signals = state.get("rawSignals") if isinstance(state, Mapping) and isinstance(state.get("rawSignals"), Mapping) else {}
    accepted = _as_int(_mapping_get(state, "accepted_count", "acceptedCount"))
    accepted += _as_int(_mapping_get(raw_signals, "acceptedCount"))
    durable = bool(metadata.get("durable") or metadata.get("pinned") or _mapping_get(state, "pinned"))
    if accepted > 0:
        score += 0.35
    if durable:
        score += 0.25
    if _has_meaningful_overlap(surface, context.committed_context, context.commit_preview):
        score += 0.15
    return min(score, 1.0)


def dedupe_candidates(candidates: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        surface = _compact(candidate)
        key = "".join(surface.lower().split())
        if not surface or key in seen:
            continue
        seen.add(key)
        result.append(surface)
    return result


def _reject_common(surface: str, context: CandidateQualityContext) -> bool:
    if reject_context_echo(surface, context.committed_context, context.commit_preview):
        return True
    if reject_prompt_leak(surface):
        return True
    if reject_generic_low_value(surface, context_terms=context.strong_terms):
        return True
    if reject_old_history_fragment(surface):
        return True
    normalized_existing = {"".join(_compact(item).lower().split()) for item in context.existing_candidates}
    return "".join(surface.lower().split()) in normalized_existing


def _is_echo(surface: str, context: str) -> bool:
    context_text = _compact(context)
    if not surface or not context_text:
        return False
    compact_surface = "".join(surface.split())
    compact_context = "".join(context_text.split())
    if compact_surface == compact_context:
        return True
    return len(compact_surface) >= 3 and compact_surface in compact_context


def _has_meaningful_overlap(surface: str, *contexts: str) -> bool:
    for context in contexts:
        context_text = _compact(context)
        if not context_text:
            continue
        for size in (4, 3, 2):
            limit = max(0, len(context_text) - size + 1)
            if any(context_text[index : index + size] in surface for index in range(limit)):
                return True
    return False


def _compact(value: str) -> str:
    return compact_whitespace(str(value or ""))


def _mapping_get(mapping: object, *keys: str) -> object:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
