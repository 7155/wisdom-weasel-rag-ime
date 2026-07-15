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
    context_group_id: str = ""
    context_group_level: str = "app"
    context_group_parent_ids: tuple[str, ...] = ()
    enabled_lanes: tuple[tuple[str, bool], ...] = ()
    lane_weights: tuple[tuple[str, float], ...] = ()
    reader_session_id: str = ""
    reader_agent_id: str = ""
    reader_room_ids: tuple[str, ...] = ()


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
