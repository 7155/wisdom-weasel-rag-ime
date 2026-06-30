from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InputEvent:
    """A committed input event that can become personal-memory evidence."""

    event_id: int | None
    created_at_ms: int
    source: str
    committed_text: str
    recent_context: str = ""
    preedit: str = ""
    schema_id: str = "default"
    app: str = "manual"
    project: str = ""
    candidate_rank: int | None = None
    provider_name: str = "local"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievedMemory:
    """A retrieved memory row plus local ranking and governance metadata."""

    source_event_id: int
    text: str
    recent_context: str
    score: float
    reason: str
    created_at_ms: int
    source: str
    project: str
    tags: tuple[str, ...] = ()
    accepted_count: int = 0
    skipped_count: int = 0
    pinned: bool = False
    downranked: int = 0
    evidence: str = ""


@dataclass(frozen=True)
class InputSuggestion:
    """A user-facing candidate derived from one or more retrieved memories."""

    suggestion_id: str
    surface_text: str
    suggestion_type: str
    source_event_id: int
    evidence_preview: str
    confidence: float
    actions: tuple[str, ...] = ("commit", "expand", "pin", "downrank", "delete")
    expanded_evidence: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelPrediction:
    """A short language-model candidate shown above RAG/memory candidates."""

    text: str
    rank: int
    provider_name: str
    latency_ms: int
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RimeCandidate:
    """A candidate already produced by librime/Squirrel."""

    text: str
    label: str = ""
    comment: str = ""
    index: int = 0


@dataclass(frozen=True)
class RimeContextSnapshot:
    """The structured Rime context a Squirrel integration can send to RAG-IME."""

    session_id: str
    request_seq: int
    raw_input: str = ""
    preedit: str = ""
    commit_text_preview: str = ""
    committed_context: str = ""
    project: str = ""
    candidates: tuple[RimeCandidate, ...] = ()
    highlighted_index: int = 0
    page: int = 0
    is_last_page: bool = True
    latency_budget_ms: int = 150
    max_visible_candidates: int = 8
    max_side_candidates: int = 3
    idle_ms: int = 0
    force_side_candidates: bool = False


@dataclass(frozen=True)
class SideCandidateDisplayItem:
    """A frontend display item after merging Rime and RAG/model side candidates."""

    label: str
    text: str
    insert_text: str
    source_type: str
    selection_action: str
    source_index: int
    comment: str = ""
    evidence_preview: str = ""
    suggestion_id: str = ""
    memory_id: str = ""
    source_event_id: int | None = None
    rime_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryAction:
    """A durable action that changes how a memory is ranked or governed."""

    action_id: int | None
    created_at_ms: int
    memory_id: str
    action_type: str
    query: str = ""
    suggestion_id: str = ""
    source_event_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContextInjection:
    """A local memory block that can be injected into an agent first run."""

    project: str
    generated_at_ms: int
    block: str
    source_event_ids: tuple[int, ...]
    query: str = ""
