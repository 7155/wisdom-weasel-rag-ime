from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ContextFrame:
    session_id: str
    request_seq: int
    front_app_bundle_id: str | None
    input_mode: Literal[
        "pinyin_composition",
        "post_commit_continuation",
        "english",
        "code",
        "path",
        "number",
        "punctuation",
        "unknown",
    ]
    raw_input: str
    preedit: str
    committed_tail: str
    selected_rime_candidates: list[str]
    semantic_query: str
    semantic_query_source: Literal[
        "rime_candidate",
        "commit_preview",
        "preedit",
        "raw_input",
        "none",
    ]
    composition_hash: str
    context_hash: str
    active_tags: list[str]
    project_scope: str | None
    timestamp_ms: int


@dataclass(frozen=True)
class QueryPlan:
    query_text: str
    lexical_terms: list[str]
    pinyin_terms: list[str]
    activated_tags: list[str]
    retrievers: list[Literal[
        "phrase",
        "stable_memory",
        "fts",
        "vector",
        "tag_graph",
        "rime_feedback",
        "cold_knowledge",
    ]]
    max_raw_results: int
    max_candidates: int
    allow_long_memory: bool
    allow_cold_knowledge: bool
    echo_risk_level: Literal["low", "medium", "high"]
    latency_budget_ms: int


@dataclass(frozen=True)
class RawRetrievalHit:
    id: str
    text: str
    source: Literal[
        "phrase",
        "memory_alias",
        "stable_memory",
        "fts",
        "vector",
        "tag_graph",
        "rime_feedback",
        "cold_knowledge",
    ]
    score: float
    memory_atom_id: str | None
    evidence: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizedMemoryCandidate:
    id: str
    text: str
    source_type: Literal["memory", "rag", "phrase", "cold_knowledge"]
    lane: Literal["memory", "rag", "lexicon", "evidence"]
    score: float
    confidence: float
    evidence_preview: str | None
    memory_atom_ids: list[str]
    tags: list[str]
    debug_features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockedCandidate:
    id: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizerResult:
    candidates: list[OptimizedMemoryCandidate]
    blocked: list[BlockedCandidate]
    trace_id: str | None
    latency_ms: float
    degraded: bool
    warnings: list[str] = field(default_factory=list)
