from __future__ import annotations

import sqlite3

from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidate_objects
from .memory_ingest import normalize_text
from .memory_models import MemoryCandidateV2
from .models import InputSuggestion
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import compact_whitespace, truncate_text


RAG_CORE_V3_SCHEMA_VERSION = "rag-ime.rag-core-v3.v1"


def retrieve_candidates_v3(
    conn: sqlite3.Connection,
    *,
    current_input: str,
    recent_context: str = "",
    committed_context: str = "",
    preedit: str = "",
    rime_candidates: tuple[str, ...] = (),
    project: str = "",
    app: str = "",
    top_k: int = 5,
    source_budget_ms: int = 25,
    context_group_id: str = "",
    context_group_level: str = "app",
    context_group_parent_ids: tuple[str, ...] = (),
) -> list[MemoryCandidateV2]:
    rebuild_retrieval_docs(conn, project=project)
    query_text = compact_whitespace(current_input or preedit or recent_context or committed_context)
    query = HybridRagQuery(
        query_text=query_text,
        raw_input=current_input,
        preedit=preedit,
        committed_tail=committed_context or recent_context,
        rime_candidates=tuple(rime_candidates),
        project=project,
        app=app,
        top_k=max(1, int(top_k)),
        latency_budget_ms=max(1, int(source_budget_ms)),
        context_group_id=context_group_id,
        context_group_level=context_group_level,
        context_group_parent_ids=context_group_parent_ids,
    )
    return [_memory_candidate_from_hybrid(item) for item in retrieve_hybrid_rag_candidate_objects(conn, query)]


def memory_candidates_v2_to_input_suggestions(candidates: list[MemoryCandidateV2]) -> list[InputSuggestion]:
    suggestions: list[InputSuggestion] = []
    for index, candidate in enumerate(candidates, start=1):
        primary_id = candidate.memory_ids[0] if candidate.memory_ids else f"rag-core-v3:{index}"
        suggestions.append(
            InputSuggestion(
                suggestion_id=f"v3:{primary_id}",
                surface_text=candidate.text,
                suggestion_type=candidate.source_type,
                source_event_id=int(candidate.source_event_id or 0),
                evidence_preview=candidate.evidence_preview,
                confidence=max(0.0, min(1.0, float(candidate.score))),
                expanded_evidence=candidate.evidence_preview,
                metadata={
                    "memory_id": primary_id,
                    "memory_ids": list(candidate.memory_ids),
                    "source_type": candidate.source_type,
                    "memory_kind": candidate.memory_kind,
                    "insert_text": candidate.text,
                    "tags": list(candidate.tags),
                    "reason": candidate.reason,
                    "rag_core": "v3",
                    "diagnostics": dict(candidate.diagnostics),
                },
            )
        )
    return suggestions


def _memory_candidate_from_hybrid(candidate) -> MemoryCandidateV2:
    memory_ids = tuple(
        item
        for item in (*candidate.memory_ids, *candidate.atom_ids, *candidate.book_ids)
        if compact_whitespace(str(item))
    )
    event_id = candidate.evidence_event_ids[0] if candidate.evidence_event_ids else None
    return MemoryCandidateV2(
        text=candidate.text,
        source_type=candidate.source_type,
        memory_kind=str(candidate.metadata.get("docType") or candidate.source_type),
        score=candidate.confidence,
        memory_ids=memory_ids,
        evidence_preview=truncate_text(candidate.evidence_preview, 180),
        diagnostics={
            "schemaVersion": RAG_CORE_V3_SCHEMA_VERSION,
            "scoreBreakdown": dict(candidate.debug_features),
            "hybridCandidate": {
                "candidateId": candidate.candidate_id,
                "sourceLane": candidate.source_lane,
                "score": candidate.score,
                "metadata": dict(candidate.metadata),
            },
        },
        source_event_id=event_id,
        normalized_text=normalize_text(candidate.text),
        tags=tuple(candidate.tags),
        reason=_reason(candidate),
    )


def _reason(candidate) -> str:
    lanes = candidate.metadata.get("lanes") if isinstance(candidate.metadata, dict) else None
    lane_text = ",".join(str(item) for item in lanes) if isinstance(lanes, list) else candidate.source_lane
    return f"hybrid-rag:{lane_text};score:{round(float(candidate.score), 4)}"
