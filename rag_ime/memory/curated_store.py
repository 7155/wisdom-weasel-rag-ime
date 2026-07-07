from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from rag_ime.models import InputSuggestion
from rag_ime.prediction.quality import (
    reject_context_echo,
    reject_generic_low_value,
    reject_old_history_fragment,
    reject_prompt_leak,
)
from rag_ime.text_utils import compact_whitespace


CURATED_TAGS = {
    "accepted-memory",
    "api-core-optimized",
    "api-lexicon",
    "compiled-memory",
    "compiled-phrase",
    "curated",
    "durable",
    "lexicon-phrase",
    "phrase-memory",
    "project-requirement",
    "stable-memory",
    "structure",
}

CURATED_MEMORY_KINDS = {"stable_memory", "phrase", "memory_alias", "project_requirement", "durable_preference"}


@dataclass(frozen=True)
class RealtimeMemoryDecision:
    allowed: bool
    source_reason: str
    rejected_reason: str = ""


@dataclass(frozen=True)
class RealtimeMemoryContext:
    committed_context: str = ""
    commit_preview: str = ""
    semantic_query: str = ""
    query_basis: str = ""


def decide_realtime_memory_candidate(
    suggestion: InputSuggestion,
    *,
    context: RealtimeMemoryContext,
) -> RealtimeMemoryDecision:
    surface = compact_whitespace(suggestion.surface_text)
    metadata = dict(suggestion.metadata)
    if not surface:
        return RealtimeMemoryDecision(False, "rejected_empty", "empty")
    if _is_tombstoned_or_suppressed(metadata):
        return RealtimeMemoryDecision(False, "rejected_tombstone", "tombstone_or_suppressed")
    if reject_context_echo(surface, context.committed_context, context.commit_preview):
        return RealtimeMemoryDecision(False, "rejected_echo", "context_echo")
    if reject_prompt_leak(surface):
        return RealtimeMemoryDecision(False, "rejected_prompt_leak", "prompt_or_session_leak")

    reason = _positive_source_reason(suggestion)
    if reason:
        return RealtimeMemoryDecision(True, reason)

    if _looks_like_raw_append_only_history(suggestion):
        return RealtimeMemoryDecision(False, "rejected_raw_history", "raw_history_without_compile_or_accept")
    if reject_old_history_fragment(surface):
        return RealtimeMemoryDecision(False, "rejected_old_history_fragment", "old_history_fragment")
    if reject_generic_low_value(surface, context_terms=_context_terms(context)):
        return RealtimeMemoryDecision(False, "rejected_low_signal", "low_signal")
    return RealtimeMemoryDecision(False, "rejected_uncompiled_memory", "missing_curated_signal")


def annotate_realtime_memory_candidate(
    suggestion: InputSuggestion,
    *,
    decision: RealtimeMemoryDecision,
) -> InputSuggestion:
    metadata = dict(suggestion.metadata)
    metadata["sourceReason"] = decision.source_reason
    if decision.rejected_reason:
        metadata["rejectedReason"] = decision.rejected_reason
    return replace(suggestion, metadata=metadata)


def _positive_source_reason(suggestion: InputSuggestion) -> str:
    metadata = dict(suggestion.metadata)
    kind = _memory_kind(metadata)
    if kind == "project_requirement":
        return "project_requirement"
    if kind == "durable_preference":
        return "durable_preference"
    if kind in CURATED_MEMORY_KINDS:
        return "durable_preference" if kind == "stable_memory" else "accepted_memory"

    tags = _tags(metadata)
    if "project-requirement" in tags:
        return "project_requirement"
    if tags.intersection({"curated", "compiled-memory", "compiled-phrase", "phrase-memory", "stable-memory"}):
        return "accepted_memory"
    if tags.intersection({"api-core-optimized", "api-lexicon", "lexicon-phrase", "structure"}):
        return "recent_high_confidence_phrase"
    if bool(metadata.get("durable") or metadata.get("pinned")):
        return "durable_preference"

    state = metadata.get("state") if isinstance(metadata.get("state"), Mapping) else {}
    raw_signals = state.get("rawSignals") if isinstance(state, Mapping) and isinstance(state.get("rawSignals"), Mapping) else {}
    if bool(_mapping_get(state, "pinned") or _mapping_get(raw_signals, "pinned")):
        return "durable_preference"
    accepted = max(
        _as_int(_mapping_get(state, "accepted_count", "event_accepted_count", "acceptedCount")),
        _as_int(_mapping_get(raw_signals, "acceptedCount")),
    )
    if accepted > 0:
        return "accepted_memory"
    frequency = max(
        _as_int(_mapping_get(state, "effective_frequency", "project_input_frequency", "input_frequency")),
        _as_int(_mapping_get(raw_signals, "effectiveFrequency", "projectInputFrequency", "inputFrequency")),
    )
    if frequency >= 3 and not _looks_like_raw_append_only_history(suggestion):
        return "recent_high_confidence_phrase"
    return ""


def _looks_like_raw_append_only_history(suggestion: InputSuggestion) -> bool:
    metadata = dict(suggestion.metadata)
    if _memory_kind(metadata) in CURATED_MEMORY_KINDS:
        return False
    if _tags(metadata).intersection(CURATED_TAGS):
        return False
    source_ref = compact_whitespace(str(metadata.get("source_ref") or metadata.get("memory_id") or "")).lower()
    suggestion_id = compact_whitespace(suggestion.suggestion_id).lower()
    type_name = compact_whitespace(suggestion.suggestion_type).lower()
    return (
        suggestion.source_event_id is not None
        or source_ref.startswith(("input_event:", "event:", "committed:"))
        or suggestion_id.startswith(("sug-event:", "event:", "input_event:", "committed:"))
        or type_name in {"paragraph", "history", "input_event", "raw"}
    )


def _is_tombstoned_or_suppressed(metadata: Mapping[str, object]) -> bool:
    state = metadata.get("state") if isinstance(metadata.get("state"), Mapping) else {}
    status = compact_whitespace(str(metadata.get("status") or _mapping_get(state, "status") or "")).lower()
    if status in {"deleted", "hidden", "suppressed", "tombstoned"}:
        return True
    return bool(
        metadata.get("deleted")
        or metadata.get("tombstoned")
        or metadata.get("suppressed")
        or _mapping_get(state, "deleted", "tombstoned", "suppressed")
    )


def _context_terms(context: RealtimeMemoryContext) -> tuple[str, ...]:
    return tuple(
        part
        for part in (
            compact_whitespace(context.semantic_query),
            compact_whitespace(context.commit_preview),
            compact_whitespace(context.committed_context)[-24:],
        )
        if part
    )


def _memory_kind(metadata: Mapping[str, object]) -> str:
    state = metadata.get("state") if isinstance(metadata.get("state"), Mapping) else {}
    return compact_whitespace(str(metadata.get("memory_kind") or _mapping_get(state, "memory_kind") or "")).lower()


def _tags(metadata: Mapping[str, object]) -> set[str]:
    raw = metadata.get("tags")
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {compact_whitespace(str(tag)).lower() for tag in raw if compact_whitespace(str(tag))}


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
