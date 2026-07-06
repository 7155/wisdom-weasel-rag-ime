from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HybridRagQuery:
    query_text: str
    raw_input: str = ""
    preedit: str = ""
    committed_tail: str = ""
    rime_candidates: tuple[str, ...] = ()
    project: str = ""
    app: str = ""
    input_mode: str = "unknown"
    top_k: int = 5
    latency_budget_ms: int = 25


@dataclass(frozen=True)
class HybridRagHit:
    doc_id: str
    doc_type: str
    source_id: str
    text: str
    surface_hints: tuple[str, ...]
    tags: tuple[str, ...]
    source_lane: str
    rank: int
    raw_score: float
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridRagCandidate:
    candidate_id: str
    text: str
    insert_text: str
    source_type: str
    source_lane: str
    score: float
    confidence: float
    tags: tuple[str, ...]
    memory_ids: tuple[str, ...]
    atom_ids: tuple[str, ...]
    book_ids: tuple[str, ...]
    evidence_event_ids: tuple[int, ...]
    evidence_preview: str
    debug_features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
