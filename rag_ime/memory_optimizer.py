from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from .core_client import CoreClient
from .models import InputSuggestion, RimeContextSnapshot
from .memory_optimizer_models import (
    BlockedCandidate,
    ContextFrame,
    OptimizedMemoryCandidate,
    OptimizerResult,
    QueryPlan,
    RawRetrievalHit,
)
from .pinyin_index import build_pinyin_metadata
from .suggestion_compiler import classify_suggestion, compile_candidate_insert_text, compress_surface_text
from .text_utils import compact_whitespace, now_ms, overlap_terms, split_sentences, token_terms, truncate_text


@dataclass(frozen=True)
class MemoryOptimizerConfig:
    enabled: bool = True
    trace_enabled: bool = False
    max_ms: int = 15
    allow_cold_knowledge: bool = False
    allow_raw_memory_candidates: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MemoryOptimizerConfig":
        source = env or dict(os.environ)
        return cls(
            enabled=_env_flag(source, "RAG_IME_MEMORY_OPTIMIZER", default=True),
            trace_enabled=_env_flag(source, "RAG_IME_MEMORY_OPTIMIZER_TRACE", default=False),
            max_ms=max(1, int(source.get("RAG_IME_MEMORY_OPTIMIZER_MAX_MS", "15"))),
            allow_cold_knowledge=_env_flag(source, "RAG_IME_MEMORY_ALLOW_COLD_KNOWLEDGE", default=False),
            allow_raw_memory_candidates=_env_flag(source, "RAG_IME_ALLOW_RAW_MEMORY_CANDIDATES", default=False),
        )


class RagMemoryOptimizer:
    """Deterministic realtime optimizer over already-local RAG/memory hits."""

    def __init__(self, config: MemoryOptimizerConfig | None = None):
        self.config = config or MemoryOptimizerConfig.from_env()

    def optimize_memory_candidates(
        self,
        context: ContextFrame,
        base_hits: list[RawRetrievalHit],
        *,
        top_k: int,
        latency_budget_ms: int,
        governance: dict[str, Any] | None = None,
    ) -> OptimizerResult:
        started = time.perf_counter()
        blocked: list[BlockedCandidate] = []
        governor = AntiEchoGovernor(self.config)
        prepared_hits: list[tuple[RawRetrievalHit, str, str]] = []
        live_governance = governance or {}
        for hit in base_hits:
            decision = governor.should_block(hit=hit, context=context, governance=live_governance)
            if decision is not None:
                blocked.append(decision)
                continue
            compiled_text = _compile_candidate_text(hit=hit, context=context)
            if not compiled_text:
                blocked.append(BlockedCandidate(id=hit.id, reason="compiler_empty_candidate"))
                continue
            prepared_hits.append((hit, compiled_text, _normalize_candidate_text(compiled_text)))
        duplicate_counts: dict[str, int] = {}
        for _, _, normalized_compiled in prepared_hits:
            if not normalized_compiled:
                continue
            duplicate_counts[normalized_compiled] = duplicate_counts.get(normalized_compiled, 0) + 1
        candidates = [
            _build_optimized_candidate(
                hit=hit,
                compiled_text=compiled_text,
                normalized_compiled=normalized_compiled,
                duplicate_count=duplicate_counts.get(normalized_compiled, 1),
                context=context,
                governance=live_governance,
            )
            for hit, compiled_text, normalized_compiled in prepared_hits
        ]
        candidates = _select_diverse_candidates(candidates, top_k=max(1, top_k))
        trace_id = None
        if self.config.trace_enabled:
            trace_id = _trace_id(context=context, base_hits=base_hits)
        elapsed = (time.perf_counter() - started) * 1000
        return OptimizerResult(
            candidates=candidates,
            blocked=blocked,
            trace_id=trace_id,
            latency_ms=elapsed,
            degraded=elapsed > max(1, latency_budget_ms),
            warnings=[],
        )


class AntiEchoGovernor:
    def __init__(self, config: MemoryOptimizerConfig):
        self.config = config

    def should_block(
        self,
        *,
        hit: RawRetrievalHit,
        context: ContextFrame,
        governance: dict[str, Any],
    ) -> BlockedCandidate | None:
        text = compact_whitespace(hit.text)
        if not text:
            return BlockedCandidate(id=hit.id, reason="empty_text")
        normalized = _normalize_candidate_text(text)
        normalized_committed_tail = _normalize_candidate_text(context.committed_tail)
        raw_history_hit = _looks_like_raw_history_hit(hit)
        allow_recent_echo = _allow_recent_echo_candidate(
            hit=hit,
            context=context,
            normalized_text=normalized,
            normalized_committed_tail=normalized_committed_tail,
            raw_history_hit=raw_history_hit,
        )
        if hit.id in set(governance.get("tombstonedMemoryIds") or []):
            return BlockedCandidate(id=hit.id, reason="tombstone_memory_id")
        if normalized in set(governance.get("tombstonedTexts") or []):
            return BlockedCandidate(id=hit.id, reason="tombstone_text")
        if hit.id in set(governance.get("suppressedMemoryIds") or []):
            return BlockedCandidate(id=hit.id, reason="suppressed_memory_id")
        if normalized in set(governance.get("suppressedTexts") or []):
            return BlockedCandidate(id=hit.id, reason="suppressed_text")
        if _optimized_source_type(hit) == "cold_knowledge" and not self.config.allow_cold_knowledge:
            return BlockedCandidate(id=hit.id, reason="cold_knowledge_disabled")
        if raw_history_hit and not self.config.allow_raw_memory_candidates:
            if len(text) > 12:
                return BlockedCandidate(id=hit.id, reason="raw_history_long_candidate")
        overlap_guard_enabled = context.input_mode == "post_commit_continuation"
        if overlap_guard_enabled and not allow_recent_echo and _overlap_ratio(normalized, normalized_committed_tail) > 0.75:
            return BlockedCandidate(id=hit.id, reason="committed_tail_overlap")
        if _overlap_ratio(normalized, _normalize_candidate_text(context.raw_input)) > 0.95:
            return BlockedCandidate(id=hit.id, reason="raw_input_overlap")
        recent_texts = set(governance.get("recentCommittedTexts") or [])
        if overlap_guard_enabled and not allow_recent_echo and normalized in recent_texts:
            return BlockedCandidate(id=hit.id, reason="recent_committed_echo")
        return None


def build_context_frame(
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
    input_mode: str,
) -> ContextFrame:
    top_candidates = [item.text for item in snapshot.candidates[:3] if compact_whitespace(item.text)]
    active_tags = list(dict.fromkeys(token_terms(f"{semantic_query} {snapshot.committed_context} {snapshot.app}", max_terms=20)))
    return ContextFrame(
        session_id=snapshot.session_id,
        request_seq=snapshot.request_seq,
        front_app_bundle_id=snapshot.frontend_transaction.front_app_bundle_id or snapshot.app or None,
        input_mode=_normalize_input_mode(
            input_mode,
            raw_input=snapshot.raw_input,
            preedit=snapshot.preedit,
        ),
        raw_input=snapshot.raw_input,
        preedit=snapshot.preedit,
        committed_tail=_tail_text(snapshot.committed_context, max_chars=80),
        selected_rime_candidates=top_candidates,
        semantic_query=semantic_query,
        semantic_query_source=_normalize_query_source(query_basis),
        composition_hash=snapshot.frontend_transaction.composition_hash,
        context_hash=snapshot.frontend_transaction.committed_context_hash,
        active_tags=active_tags,
        project_scope=snapshot.project or None,
        timestamp_ms=now_ms(),
    )


def build_query_plan(*, context: ContextFrame, config: MemoryOptimizerConfig, top_k: int, latency_budget_ms: int) -> QueryPlan:
    lexical_terms = token_terms(context.semantic_query, max_terms=16)
    input_mode = context.input_mode
    if input_mode == "post_commit_continuation":
        retrievers = ["phrase", "stable_memory", "tag_graph", "rime_feedback"]
        echo_risk = "medium"
    elif input_mode == "pinyin_composition":
        retrievers = ["phrase", "stable_memory", "fts", "tag_graph"]
        echo_risk = "high" if len(context.preedit) <= 3 else "medium"
    elif input_mode in {"code", "path", "english"}:
        retrievers = ["phrase", "stable_memory"]
        echo_risk = "low"
    elif input_mode in {"number", "punctuation"}:
        retrievers = []
        echo_risk = "low"
    else:
        retrievers = ["phrase", "stable_memory", "fts"]
        echo_risk = "medium"
    return QueryPlan(
        query_text=context.semantic_query,
        lexical_terms=lexical_terms,
        pinyin_terms=[context.preedit] if compact_whitespace(context.preedit) else [],
        activated_tags=list(context.active_tags[:20]),
        retrievers=retrievers,
        max_raw_results=max(8, top_k * 3),
        max_candidates=max(1, top_k),
        allow_long_memory=False,
        allow_cold_knowledge=config.allow_cold_knowledge,
        echo_risk_level=echo_risk,
        latency_budget_ms=max(1, latency_budget_ms),
    )


def optimize_suggestions_if_enabled(
    *,
    core: CoreClient | None,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
    input_mode: str,
    suggestions: list[InputSuggestion],
    top_k: int,
    latency_budget_ms: int,
    env: dict[str, str] | None = None,
) -> tuple[list[InputSuggestion], dict[str, object]]:
    config = MemoryOptimizerConfig.from_env(env)
    context = build_context_frame(
        snapshot=snapshot,
        semantic_query=semantic_query,
        query_basis=query_basis,
        input_mode=input_mode,
    )
    plan = build_query_plan(
        context=context,
        config=config,
        top_k=top_k,
        latency_budget_ms=min(latency_budget_ms, config.max_ms),
    )
    if not config.enabled:
        return suggestions, {
            "enabled": False,
            "traceEnabled": config.trace_enabled,
            "maxMs": config.max_ms,
            "contextFrame": asdict(context) if config.trace_enabled else {},
            "queryPlan": asdict(plan) if config.trace_enabled else {},
        }
    raw_hits = _raw_hits_from_suggestions(suggestions)
    optimizer_callable = getattr(core, "optimize_memory_candidates", None) if core is not None else None
    try:
        if callable(optimizer_callable):
            result = optimizer_callable(
                context,
                raw_hits,
                top_k=top_k,
                latency_budget_ms=min(latency_budget_ms, config.max_ms),
            )
        else:
            optimizer = RagMemoryOptimizer(config=config)
            governance = _load_governance_snapshot(
                core=core,
                context=context,
                base_hits=raw_hits,
            )
            result = optimizer.optimize_memory_candidates(
                context,
                raw_hits,
                top_k=top_k,
                latency_budget_ms=min(latency_budget_ms, config.max_ms),
                governance=governance,
            )
    except Exception as exc:
        return [], {
            "enabled": True,
            "traceEnabled": config.trace_enabled,
            "maxMs": config.max_ms,
            "traceId": None,
            "latencyMs": 0.0,
            "degraded": True,
            "failClosed": True,
            "warnings": [f"optimizer_exception:{type(exc).__name__}"],
            "blocked": [],
            "contextFrame": asdict(context) if config.trace_enabled else {},
            "queryPlan": asdict(plan) if config.trace_enabled else {},
        }
    _store_optimizer_trace(
        core=core,
        context=context,
        plan=plan,
        raw_hits=raw_hits,
        result=result,
    )
    if result.degraded:
        warnings = list(result.warnings)
        if "optimizer_degraded_timeout" not in warnings:
            warnings.append("optimizer_degraded_timeout")
        return [], {
            "enabled": True,
            "traceEnabled": config.trace_enabled,
            "maxMs": config.max_ms,
            "traceId": result.trace_id,
            "latencyMs": round(result.latency_ms, 3),
            "degraded": True,
            "failClosed": True,
            "warnings": warnings,
            "blocked": [asdict(item) for item in result.blocked],
            "contextFrame": asdict(context) if config.trace_enabled else {},
            "queryPlan": asdict(plan) if config.trace_enabled else {},
        }
    suggestion_lookup = {
        str(item.metadata.get("memory_id") or item.suggestion_id): item
        for item in suggestions
    }
    optimized_suggestions = [
        _apply_optimized_candidate(suggestion_lookup[candidate.id], candidate)
        for candidate in result.candidates
        if candidate.id in suggestion_lookup
    ]
    optimized_suggestions = _merge_protected_retrieval_hits(
        raw_suggestions=suggestions,
        optimized_suggestions=optimized_suggestions,
        top_k=max(1, top_k),
        blocked_ids={item.id for item in result.blocked},
    )
    return optimized_suggestions[: max(1, top_k)], {
        "enabled": True,
        "traceEnabled": config.trace_enabled,
        "maxMs": config.max_ms,
        "traceId": result.trace_id,
        "latencyMs": round(result.latency_ms, 3),
        "degraded": result.degraded,
        "warnings": list(result.warnings),
        "blocked": [asdict(item) for item in result.blocked],
        "contextFrame": asdict(context) if config.trace_enabled else {},
        "queryPlan": asdict(plan) if config.trace_enabled else {},
    }


def _merge_protected_retrieval_hits(
    *,
    raw_suggestions: list[InputSuggestion],
    optimized_suggestions: list[InputSuggestion],
    top_k: int,
    blocked_ids: set[str] | None = None,
) -> list[InputSuggestion]:
    protected: list[InputSuggestion] = []
    blocked = set(blocked_ids or set())
    for suggestion in raw_suggestions[: min(3, max(1, top_k))]:
        candidate_id = str(suggestion.metadata.get("memory_id") or suggestion.suggestion_id)
        if candidate_id in blocked:
            continue
        if _is_protected_retrieval_hit(suggestion):
            protected.append(suggestion)
    if not protected:
        return optimized_suggestions
    merged: list[InputSuggestion] = []
    seen: set[str] = set()
    for suggestion in [*protected, *optimized_suggestions]:
        key = _normalize_candidate_text(suggestion.surface_text)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(suggestion)
        if len(merged) >= max(1, top_k):
            break
    return merged


def _is_protected_retrieval_hit(suggestion: InputSuggestion) -> bool:
    metadata = dict(suggestion.metadata)
    try:
        rank = int(metadata.get("rank") or 0)
    except (TypeError, ValueError):
        rank = 0
    if rank <= 0 or rank > 3:
        return False
    if suggestion.confidence < 0.55:
        return False
    tags = {
        compact_whitespace(str(tag)).lower()
        for tag in metadata.get("tags", [])
        if compact_whitespace(str(tag))
    } if isinstance(metadata.get("tags"), list) else set()
    if tags.intersection({"curated", "generated-memory", "api-core-optimized", "api-lexicon", "phrase-memory"}):
        return True
    source_type = compact_whitespace(str(metadata.get("source_type") or "")).lower()
    return source_type in {"memory", "phrase"}


def _raw_hits_from_suggestions(suggestions: list[InputSuggestion]) -> list[RawRetrievalHit]:
    hits: list[RawRetrievalHit] = []
    for item in suggestions:
        metadata = dict(item.metadata)
        source_type = str(metadata.get("source_type") or "rag")
        metadata.setdefault("tags", list(metadata.get("tags") or []))
        metadata.setdefault("source_type", source_type)
        metadata.setdefault("source_event_id", item.source_event_id)
        metadata.setdefault("preview_text", metadata.get("preview_text") or item.evidence_preview)
        metadata.setdefault("expanded_evidence", item.expanded_evidence)
        metadata.setdefault("suggestion_type", item.suggestion_type)
        hits.append(
            RawRetrievalHit(
                id=str(metadata.get("memory_id") or item.suggestion_id),
                text=item.surface_text,
                source=_raw_hit_source(source_type),
                score=float(item.confidence),
                memory_atom_id=str(metadata.get("memory_id") or ""),
                evidence=item.evidence_preview,
                metadata=metadata,
            )
        )
    return hits


def _raw_hit_source(source_type: str) -> str:
    if source_type == "memory":
        return "stable_memory"
    if source_type == "phrase":
        return "phrase"
    if source_type == "cold_knowledge":
        return "cold_knowledge"
    return "fts"


def _optimized_source_type(hit: RawRetrievalHit) -> str:
    if hit.source == "phrase":
        return "phrase"
    if hit.source == "cold_knowledge":
        return "cold_knowledge"
    return str(hit.metadata.get("source_type") or "rag")


def _optimized_lane(hit: RawRetrievalHit) -> str:
    if hit.source == "phrase":
        return "lexicon"
    if hit.source == "cold_knowledge":
        return "evidence"
    if str(hit.metadata.get("source_type") or "rag") == "memory":
        return "memory"
    return "rag"


def _normalize_query_source(query_basis: str) -> str:
    mapping = {
        "rimeCandidate": "rime_candidate",
        "rimeCandidates": "rime_candidate",
        "commitPreview": "commit_preview",
        "commitTextPreview": "commit_preview",
        "committedContext": "commit_preview",
        "preedit": "preedit",
        "rawInput": "raw_input",
        "rawInputFallback": "raw_input",
    }
    return mapping.get(query_basis, "none")


def _normalize_input_mode(input_mode: str, *, raw_input: str = "", preedit: str = "") -> str:
    raw_mode = getattr(input_mode, "value", input_mode)
    aliases = {
        "prefix_constrained_composing": "pinyin_composition",
        "anchor_composing": "pinyin_composition",
        "post_commit_predicting": "post_commit_continuation",
        "raw_input": _classify_raw_input_mode(raw_input or preedit),
    }
    input_mode = aliases.get(str(raw_mode), str(raw_mode))
    known = {
        "pinyin_composition",
        "post_commit_continuation",
        "english",
        "code",
        "path",
        "number",
        "punctuation",
        "unknown",
    }
    return input_mode if input_mode in known else "unknown"


def _classify_raw_input_mode(text: str) -> str:
    raw = compact_whitespace(text)
    if not raw:
        return "unknown"
    if raw.isdigit():
        return "number"
    if all(not char.isalnum() for char in raw):
        return "punctuation"
    if _looks_like_path_input(raw):
        return "path"
    if _looks_like_code_input(raw):
        return "code"
    if raw.isascii() and any(char.isalpha() for char in raw):
        return "english"
    return "unknown"


def _looks_like_path_input(raw: str) -> bool:
    lowered = raw.lower()
    return (
        "/" in raw
        or "\\" in raw
        or lowered.startswith(("./", "../", "~/"))
        or lowered.endswith((".py", ".ts", ".tsx", ".js", ".json", ".md", ".yaml", ".yml"))
    )


def _looks_like_code_input(raw: str) -> bool:
    code_delimiters = set("_:+=<>[]{}()$@#|")
    command_prefixes = {"git", "npm", "python", "python3", "uv", "node", "cd", "ls", "rg", "docker"}
    parts = raw.split()
    return (
        any(char in code_delimiters for char in raw)
        or (parts and parts[0].lower() in command_prefixes)
        or any(char.isdigit() for char in raw)
    )


def _tail_text(text: str, *, max_chars: int) -> str:
    compact = compact_whitespace(text)
    if len(compact) <= max_chars:
        return compact
    return compact[-max_chars:]


def _trace_id(*, context: ContextFrame, base_hits: list[RawRetrievalHit]) -> str:
    seed = f"{context.session_id}:{context.request_seq}:{context.context_hash}:{len(base_hits)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _store_optimizer_trace(
    *,
    core: CoreClient | None,
    context: ContextFrame,
    plan: QueryPlan,
    raw_hits: list[RawRetrievalHit],
    result: OptimizerResult,
) -> None:
    if core is None or not result.trace_id:
        return
    recorder = getattr(core, "store_memory_optimizer_trace", None)
    if not callable(recorder):
        return
    try:
        recorder(
            {
                "traceId": result.trace_id,
                "requestSeq": context.request_seq,
                "contextHash": context.context_hash,
                "contextFrame": asdict(context),
                "queryPlan": asdict(plan),
                "rawResults": [asdict(item) for item in raw_hits],
                "optimizedCandidates": [asdict(item) for item in result.candidates],
                "blocked": [asdict(item) for item in result.blocked],
                "latencyMs": result.latency_ms,
                "warnings": list(result.warnings),
                "degraded": result.degraded,
                "createdAtMs": context.timestamp_ms,
            }
        )
    except Exception:
        return


def _load_governance_snapshot(
    *,
    core: CoreClient | None,
    context: ContextFrame,
    base_hits: list[RawRetrievalHit],
) -> dict[str, Any]:
    if core is None:
        return {
            "recentCommittedTexts": [],
            "tombstonedMemoryIds": [],
            "tombstonedTexts": [],
            "suppressedMemoryIds": [],
            "suppressedTexts": [],
        }
    loader = getattr(core, "optimizer_governance_snapshot", None)
    if not callable(loader):
        return {
            "recentCommittedTexts": [],
            "tombstonedMemoryIds": [],
            "tombstonedTexts": [],
            "suppressedMemoryIds": [],
            "suppressedTexts": [],
        }
    return dict(
        loader(
            memory_ids=[hit.id for hit in base_hits],
            texts=[hit.text for hit in base_hits],
            source_event_ids=[int(hit.metadata.get("source_event_id") or 0) or None for hit in base_hits],
            context_hash=context.context_hash,
            project=context.project_scope or "",
            app=context.front_app_bundle_id or "",
        )
        or {}
    )


def _build_optimized_candidate(
    *,
    hit: RawRetrievalHit,
    compiled_text: str,
    normalized_compiled: str,
    duplicate_count: int,
    context: ContextFrame,
    governance: dict[str, Any],
) -> OptimizedMemoryCandidate:
    debug_features = _score_debug_features(
        hit=hit,
        compiled_text=compiled_text,
        normalized_compiled=normalized_compiled,
        duplicate_count=duplicate_count,
        context=context,
        governance=governance,
    )
    total_score = _optimizer_total_score(debug_features)
    metadata = dict(hit.metadata)
    metadata["display_lane"] = _optimized_lane(hit)
    metadata["compiled_text"] = compiled_text
    metadata["memory_optimizer_score"] = round(total_score, 4)
    metadata["memory_optimizer_features"] = {key: round(value, 4) for key, value in debug_features.items()}
    evidence_preview = _candidate_evidence_preview(hit=hit, compiled_text=compiled_text)
    metadata["expanded_evidence"] = _candidate_expanded_evidence(
        hit=hit,
        compiled_text=compiled_text,
        evidence_preview=evidence_preview,
    )
    return OptimizedMemoryCandidate(
        id=hit.id,
        text=compiled_text,
        source_type=_optimized_source_type(hit),
        lane=_optimized_lane(hit),
        score=round(total_score, 4),
        confidence=_optimizer_confidence(total_score=total_score, base_score=hit.score),
        evidence_preview=evidence_preview,
        memory_atom_ids=[hit.memory_atom_id] if hit.memory_atom_id else [],
        tags=_candidate_tags(hit),
        debug_features={key: round(value, 4) for key, value in debug_features.items()},
        metadata=metadata,
    )


def _score_debug_features(
    *,
    hit: RawRetrievalHit,
    compiled_text: str,
    normalized_compiled: str,
    duplicate_count: int,
    context: ContextFrame,
    governance: dict[str, Any],
) -> dict[str, float]:
    metadata = dict(hit.metadata)
    source_text = _candidate_source_text(hit)
    breakdown = _score_breakdown_metadata(metadata)
    components = dict(breakdown.get("components") or {}) if isinstance(breakdown.get("components"), dict) else {}
    raw_signals = dict(breakdown.get("rawSignals") or {}) if isinstance(breakdown.get("rawSignals"), dict) else {}
    accepted_count = int(raw_signals.get("acceptedCount") or 0)
    stale_penalty_component = float(components.get("stalePenalty") or 0.0)
    source_type = str(metadata.get("source_type") or "")
    return {
        "prefixMatch": _prefix_match_score(context.semantic_query, compiled_text),
        "pinyinMatch": _pinyin_match_score(context=context, metadata=metadata, compiled_text=compiled_text),
        "semanticScore": _semantic_score(hit=hit, source_text=source_text, breakdown=breakdown, context=context),
        "tagActivation": _tag_activation_score(context=context, hit=hit, source_text=source_text, compiled_text=compiled_text),
        "appScopeMatch": _scope_match_score(context.front_app_bundle_id, _metadata_scope_value(metadata, "app")),
        "projectScopeMatch": _scope_match_score(context.project_scope, _metadata_scope_value(metadata, "project")),
        "acceptedBonus": _accepted_bonus_score(accepted_count=accepted_count, breakdown=breakdown),
        "phraseFrequency": _phrase_frequency_score(hit=hit),
        "memoryQuality": _memory_quality_score(hit=hit),
        "freshness": _freshness_score(stale_penalty_component=stale_penalty_component, hit=hit),
        "evidenceStrength": _evidence_strength_score(hit=hit, source_text=source_text),
        "rawEchoPenalty": _raw_echo_penalty_score(context=context, normalized_compiled=normalized_compiled),
        "staleContextPenalty": _stale_context_penalty_score(context=context, hit=hit, source_type=source_type),
        "repeatedIgnorePenalty": 1.0 if hit.id in set(governance.get("suppressedMemoryIds") or []) else 0.0,
        "duplicatePenalty": 1.0 if duplicate_count > 1 else 0.0,
        "deletedOrDownrankedPenalty": _downrank_penalty(metadata),
        "compiledCandidate": 1.0 if compact_whitespace(compiled_text) != compact_whitespace(hit.text) else 0.0,
        "baseScore": _clamp01(hit.score),
        "compiledLength": min(1.0, len(compiled_text) / 16.0),
    }


def _optimizer_total_score(features: dict[str, float]) -> float:
    return (
        0.20 * features.get("prefixMatch", 0.0)
        + 0.15 * features.get("pinyinMatch", 0.0)
        + 0.15 * features.get("semanticScore", 0.0)
        + 0.12 * features.get("tagActivation", 0.0)
        + 0.10 * features.get("appScopeMatch", 0.0)
        + 0.08 * features.get("projectScopeMatch", 0.0)
        + 0.08 * features.get("acceptedBonus", 0.0)
        + 0.06 * features.get("phraseFrequency", 0.0)
        + 0.05 * features.get("memoryQuality", 0.0)
        + 0.04 * features.get("freshness", 0.0)
        + 0.03 * features.get("evidenceStrength", 0.0)
        - 0.35 * features.get("rawEchoPenalty", 0.0)
        - 0.30 * features.get("staleContextPenalty", 0.0)
        - 0.25 * features.get("repeatedIgnorePenalty", 0.0)
        - 0.25 * features.get("duplicatePenalty", 0.0)
        - 0.50 * features.get("deletedOrDownrankedPenalty", 0.0)
    )


def _optimizer_confidence(*, total_score: float, base_score: float) -> float:
    return _clamp01(0.35 * _clamp01(base_score) + 0.65 * _clamp01(total_score + 0.2))


def _apply_optimized_candidate(base: InputSuggestion, candidate: OptimizedMemoryCandidate) -> InputSuggestion:
    metadata = dict(base.metadata)
    metadata.update(dict(candidate.metadata))
    tags = list(dict.fromkeys(candidate.tags or list(metadata.get("tags") or [])))
    metadata["tags"] = tags
    if candidate.source_type in {"rag", "memory"}:
        metadata["source_type"] = candidate.source_type
    metadata["insert_text"] = compile_candidate_insert_text(candidate.text)
    metadata["preview_text"] = candidate.evidence_preview or metadata.get("preview_text") or base.evidence_preview
    metadata["memory_optimizer"] = {
        "score": round(candidate.score, 4),
        "lane": candidate.lane,
        "sourceType": candidate.source_type,
        "features": {key: round(value, 4) for key, value in candidate.debug_features.items()},
    }
    metadata.update(build_pinyin_metadata(candidate.text))
    return InputSuggestion(
        suggestion_id=base.suggestion_id,
        surface_text=candidate.text,
        suggestion_type=classify_suggestion(candidate.text, tuple(tags)) or base.suggestion_type,
        source_event_id=base.source_event_id,
        evidence_preview=candidate.evidence_preview or base.evidence_preview,
        confidence=max(0.0, min(1.0, candidate.confidence)),
        actions=base.actions,
        expanded_evidence=compact_whitespace(str(metadata.get("expanded_evidence") or "")) or base.expanded_evidence,
        metadata=metadata,
    )


def _candidate_source_text(hit: RawRetrievalHit) -> str:
    metadata = dict(hit.metadata)
    for value in (
        metadata.get("raw_text"),
        hit.text,
        metadata.get("preview_text"),
        metadata.get("expanded_evidence"),
        hit.evidence,
    ):
        text = compact_whitespace(str(value or ""))
        if text:
            return text
    return ""


def _candidate_tags(hit: RawRetrievalHit) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for item in hit.metadata.get("tags") or []:
        text = compact_whitespace(str(item))
        if not text or text in seen:
            continue
        seen.add(text)
        tags.append(text)
    return tags


def _compile_candidate_text(*, hit: RawRetrievalHit, context: ContextFrame) -> str:
    source_text = _candidate_source_text(hit)
    tags = tuple(_candidate_tags(hit))
    max_chars = _compiled_text_limit(context=context, source_text=source_text or hit.text)
    surface_text = compact_whitespace(str(hit.text or ""))
    if surface_text and len(surface_text) <= max_chars:
        return surface_text
    focused = _best_query_focused_segment(source_text or surface_text, context=context, max_chars=max_chars)
    if focused:
        return focused
    compiled = compress_surface_text(
        source_text or surface_text,
        tags=tags,
        suggestion_type=classify_suggestion(source_text or surface_text, tags=tags),
        max_chars=max_chars,
    )
    if compiled:
        return compiled
    fallback = surface_text or compact_whitespace(str(hit.metadata.get("insert_text") or ""))
    return truncate_text(fallback, max_chars)


def _compiled_text_limit(*, context: ContextFrame, source_text: str) -> int:
    if context.input_mode in {"code", "path", "english"} or _looks_ascii_heavy(source_text):
        return 32
    return 32


def _looks_like_raw_history_hit(hit: RawRetrievalHit) -> bool:
    tags = {str(tag).lower() for tag in hit.metadata.get("tags") or []}
    source_type = str(hit.metadata.get("source_type") or "")
    if tags.intersection({"memory", "curated", "phrase-memory", "generated-memory", "structure", "outline"}):
        return False
    if tags.intersection({"user-input", "raw", "history", "codex-history"}):
        return True
    if tags:
        return False
    if source_type == "rag" and hit.source == "fts" and hit.id.startswith(("event:", "sug-event:")):
        return True
    return False


def _allow_recent_echo_candidate(
    *,
    hit: RawRetrievalHit,
    context: ContextFrame,
    normalized_text: str,
    normalized_committed_tail: str,
    raw_history_hit: bool,
) -> bool:
    if not normalized_text:
        return False
    if context.input_mode == "pinyin_composition" and not raw_history_hit:
        return True
    if context.input_mode != "post_commit_continuation":
        return False
    if raw_history_hit:
        return False
    if str(hit.metadata.get("source_type") or "") != "rag":
        return False
    if len(normalized_text) < 4 or not normalized_committed_tail:
        return False
    return normalized_text in normalized_committed_tail


def _looks_ascii_heavy(text: str) -> bool:
    compact = compact_whitespace(text)
    if not compact:
        return False
    ascii_chars = sum(1 for char in compact if char.isascii() and not char.isspace())
    return ascii_chars >= max(4, len(compact) // 2)


def _best_query_focused_segment(text: str, *, context: ContextFrame, max_chars: int) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return ""
    query = compact_whitespace(context.semantic_query)
    active_terms = token_terms(" ".join(context.active_tags[:12]), max_terms=24)
    segments: list[str] = []
    for sentence in split_sentences(compact) or [compact]:
        for segment in re.split(r"[，、；;|/]", sentence):
            cleaned = compact_whitespace(segment.strip("：:·- ，。！？!?；;,."))
            if cleaned:
                segments.append(cleaned)
    best_text = ""
    best_score = 0.0
    for segment in segments:
        if len(segment) > max_chars:
            continue
        overlap = len(overlap_terms(query, segment))
        active_hits = sum(1 for term in active_terms if term and term.lower() in segment.lower())
        exact = 1.0 if query and compact_whitespace(query) in segment else 0.0
        score = exact * 2.0 + overlap * 1.2 + min(2.0, active_hits * 0.8)
        if 2 <= len(segment) <= max_chars:
            score += 0.5
        if score > best_score:
            best_score = score
            best_text = segment
    return best_text if best_score >= 1.5 else ""


def _score_breakdown_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = metadata.get("score_breakdown")
    return dict(payload) if isinstance(payload, dict) else {}


def _prefix_match_score(query: str, candidate_text: str) -> float:
    normalized_query = _normalize_candidate_text(query)
    normalized_candidate = _normalize_candidate_text(candidate_text)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    if normalized_candidate.startswith(normalized_query) or normalized_query in normalized_candidate:
        return min(1.0, 0.55 + len(normalized_query) / max(len(normalized_candidate), 1))
    query_terms = token_terms(query, max_terms=12)
    if not query_terms:
        return 0.0
    matches = sum(1 for term in query_terms if term and term.lower() in normalized_candidate)
    return _clamp01(matches / max(1, len(query_terms)))


def _pinyin_match_score(*, context: ContextFrame, metadata: dict[str, Any], compiled_text: str) -> float:
    query = compact_whitespace(context.preedit or context.raw_input).lower()
    if not query or not re.fullmatch(r"[a-z0-9_+#.\-]+", query):
        return 0.0
    pinyin_payload = dict(metadata) if metadata else {}
    if not pinyin_payload.get("pinyin_prefixes") and not pinyin_payload.get("pinyin_initials"):
        pinyin_payload.update(build_pinyin_metadata(compiled_text))
    prefixes = [compact_whitespace(str(item)).lower() for item in pinyin_payload.get("pinyin_prefixes") or []]
    initials = compact_whitespace(str(pinyin_payload.get("pinyin_initials") or pinyin_payload.get("initials") or "")).lower()
    full_pinyin = [compact_whitespace(str(item)).lower() for item in pinyin_payload.get("full_pinyin") or []]
    if any(prefix.startswith(query) for prefix in prefixes):
        return 1.0
    if initials.startswith(query):
        return 0.95
    if any(part.startswith(query) for part in full_pinyin):
        return 0.8
    if any(query in prefix for prefix in prefixes):
        return 0.6
    return 0.0


def _semantic_score(
    *,
    hit: RawRetrievalHit,
    source_text: str,
    breakdown: dict[str, Any],
    context: ContextFrame,
) -> float:
    total = float(breakdown.get("total") or 0.0)
    overlap_bonus = min(0.2, len(overlap_terms(context.semantic_query, source_text or hit.text)) * 0.08)
    return _clamp01(max(hit.score, total) + overlap_bonus)


def _tag_activation_score(*, context: ContextFrame, hit: RawRetrievalHit, source_text: str, compiled_text: str) -> float:
    active = {compact_whitespace(item).lower() for item in context.active_tags if compact_whitespace(item)}
    if not active:
        return 0.0
    tag_hits = sum(1 for item in _candidate_tags(hit) if compact_whitespace(item).lower() in active)
    text_haystack = f"{source_text} {compiled_text}".lower()
    text_hits = sum(1 for item in active if item and item in text_haystack)
    return _clamp01(0.5 * (tag_hits / max(1, len(active))) + 0.5 * min(1.0, text_hits / 3))


def _metadata_scope_value(metadata: dict[str, Any], key: str) -> str:
    for value in (
        metadata.get(key),
        (metadata.get("state") or {}).get(key) if isinstance(metadata.get("state"), dict) else "",
    ):
        text = compact_whitespace(str(value or ""))
        if text:
            return text
    return ""


def _scope_match_score(expected: str | None, actual: str) -> float:
    left = compact_whitespace(expected or "")
    right = compact_whitespace(actual)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left.endswith(right) or right.endswith(left):
        return 0.75
    return 0.0


def _accepted_bonus_score(*, accepted_count: int, breakdown: dict[str, Any]) -> float:
    components = dict(breakdown.get("components") or {}) if isinstance(breakdown.get("components"), dict) else {}
    accepted_component = float(components.get("accepted") or 0.0)
    return _clamp01(max(min(1.0, accepted_count / 3.0), accepted_component))


def _phrase_frequency_score(*, hit: RawRetrievalHit) -> float:
    if hit.source == "phrase":
        return 1.0
    if hit.source in {"stable_memory", "memory_alias"}:
        return 0.55
    return 0.2


def _memory_quality_score(*, hit: RawRetrievalHit) -> float:
    if hit.source == "phrase":
        return 0.82
    if hit.source in {"stable_memory", "memory_alias"}:
        return 0.74
    if hit.source == "cold_knowledge":
        return 0.38
    return 0.56


def _freshness_score(*, stale_penalty_component: float, hit: RawRetrievalHit) -> float:
    base = 0.72 if hit.source == "phrase" else 0.58
    if stale_penalty_component < 0:
        base += stale_penalty_component
    return _clamp01(base)


def _evidence_strength_score(*, hit: RawRetrievalHit, source_text: str) -> float:
    if compact_whitespace(hit.evidence or "") and compact_whitespace(source_text):
        return 1.0
    if compact_whitespace(source_text):
        return 0.7
    return 0.3


def _raw_echo_penalty_score(*, context: ContextFrame, normalized_compiled: str) -> float:
    committed_overlap = _overlap_ratio(normalized_compiled, _normalize_candidate_text(context.committed_tail))
    raw_overlap = _overlap_ratio(normalized_compiled, _normalize_candidate_text(context.raw_input))
    return max(committed_overlap, raw_overlap)


def _stale_context_penalty_score(*, context: ContextFrame, hit: RawRetrievalHit, source_type: str) -> float:
    if context.input_mode in {"number", "punctuation"}:
        return 1.0
    if context.input_mode in {"code", "path", "english"} and hit.source not in {"phrase", "stable_memory"}:
        return 0.75
    if source_type == "cold_knowledge":
        return 0.65
    return 0.0


def _downrank_penalty(metadata: dict[str, Any]) -> float:
    state = dict(metadata.get("state") or {}) if isinstance(metadata.get("state"), dict) else {}
    downranked = int(state.get("downranked") or 0)
    deleted = float(state.get("deleted") or 0.0) if isinstance(state.get("deleted"), (int, float, bool)) else 0.0
    return _clamp01(max(downranked * 0.25, deleted))


def _candidate_evidence_preview(*, hit: RawRetrievalHit, compiled_text: str) -> str:
    preview = compact_whitespace(str(hit.metadata.get("preview_text") or hit.evidence or hit.text or ""))
    if _evidence_preview_leaks_long_source(preview=preview, hit=hit, compiled_text=compiled_text):
        return truncate_text(f"压缩自稳定记忆：{compiled_text}", 180)
    if preview:
        return truncate_text(preview, 180)
    return truncate_text(compiled_text, 180)


def _candidate_expanded_evidence(*, hit: RawRetrievalHit, compiled_text: str, evidence_preview: str) -> str:
    expanded = compact_whitespace(str(hit.metadata.get("expanded_evidence") or ""))
    if _evidence_preview_leaks_long_source(preview=expanded, hit=hit, compiled_text=compiled_text):
        return evidence_preview
    return expanded or evidence_preview


def _evidence_preview_leaks_long_source(*, preview: str, hit: RawRetrievalHit, compiled_text: str) -> bool:
    preview_norm = _normalize_candidate_text(preview)
    source_norm = _normalize_candidate_text(_candidate_source_text(hit) or hit.text)
    compiled_norm = _normalize_candidate_text(compiled_text)
    if not preview_norm or not source_norm or not compiled_norm:
        return False
    if preview_norm == compiled_norm:
        return False
    if len(source_norm) <= max(12, len(compiled_norm) + 4):
        return False
    if source_norm in preview_norm or preview_norm in source_norm:
        return True
    return _overlap_ratio(preview_norm, source_norm) >= 0.85


def _select_diverse_candidates(
    candidates: list[OptimizedMemoryCandidate],
    *,
    top_k: int,
) -> list[OptimizedMemoryCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (-item.score, -item.confidence, item.text, item.id),
    )
    selected: list[OptimizedMemoryCandidate] = []
    seen_texts: set[str] = set()
    for candidate in ordered:
        normalized = _normalize_candidate_text(candidate.text)
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        selected.append(candidate)
        if len(selected) >= max(1, top_k):
            break
    return selected


def _normalize_candidate_text(text: str) -> str:
    compact = compact_whitespace(text).lower()
    compact = compact.replace("，", ",").replace("。", ".").replace("！", "!").replace("？", "?")
    return compact


def _overlap_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    overlap = sum(1 for gram in _char_ngrams(left) if gram in _char_ngrams(right))
    total = max(len(_char_ngrams(left)), len(_char_ngrams(right)), 1)
    return overlap / total


def _char_ngrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(0, len(text) - 1)}


def _env_flag(env: dict[str, str], key: str, *, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
