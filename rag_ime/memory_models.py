from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImeQueryContext:
    current_input: str
    recent_context: str = ""
    committed_context: str = ""
    preedit: str = ""
    rime_candidates: tuple[str, ...] = ()
    app: str = ""
    project: str = ""
    schema_id: str = ""
    top_k: int = 5
    source_budget_ms: int = 80
    allow_cold_knowledge: bool = False
    allow_raw_event_candidates: bool = False


@dataclass(frozen=True)
class MemoryCandidateV2:
    text: str
    source_type: str
    memory_kind: str
    score: float
    memory_ids: tuple[str, ...]
    evidence_preview: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    source_event_id: int | None = None
    normalized_text: str = ""
    tags: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class CandidateFeedbackV2:
    query_hash: str
    candidate_text: str
    source_type: str
    memory_ids: tuple[str, ...] = ()
    action: str = "shown"
    app: str = ""
    project: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanupDiffEntry:
    op: str
    target_memory_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


@dataclass(frozen=True)
class CleanupRunPlan:
    run_id: str
    provider: str = ""
    model: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    diffs: tuple[CleanupDiffEntry, ...] = ()
