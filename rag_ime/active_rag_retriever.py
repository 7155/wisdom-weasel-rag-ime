from __future__ import annotations

import sqlite3

from .active_rag_models import ActiveRagEvidence, ActiveRagFrame
from .hybrid_rag_models import HybridRagCandidate, HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidate_objects
from .local_sqlite_core import LocalSqliteCoreClient
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import compact_whitespace


def retrieve_active_rag_evidence(
    core: LocalSqliteCoreClient,
    frame: ActiveRagFrame,
    *,
    enabled_lanes: tuple[tuple[str, bool], ...] = (),
    lane_weights: tuple[tuple[str, float], ...] = (),
) -> tuple[ActiveRagEvidence, ...]:
    """Retrieve short evidence objects for explicit selected-text assistance."""
    core.initialize()
    query = _query_from_frame(
        frame,
        enabled_lanes=enabled_lanes,
        lane_weights=lane_weights,
    )
    with core._connect() as conn:
        candidates = _retrieve_candidates_with_rebuild(conn, query)
    return tuple(_evidence_from_candidate(candidate) for candidate in candidates)


def _retrieve_candidates_with_rebuild(conn: sqlite3.Connection, query: HybridRagQuery) -> list[HybridRagCandidate]:
    try:
        candidates = retrieve_hybrid_rag_candidate_objects(conn, query)
    except sqlite3.OperationalError as exc:
        if "memory_retrieval_docs" not in str(exc):
            raise
        rebuild_retrieval_docs(conn, project=query.project)
        candidates = retrieve_hybrid_rag_candidate_objects(conn, query)
    if candidates:
        return candidates
    try:
        report = rebuild_retrieval_docs(conn, project=query.project)
    except sqlite3.OperationalError:
        return []
    if int(report.get("docCount") or 0) <= 0:
        return []
    return retrieve_hybrid_rag_candidate_objects(conn, query)


def _query_from_frame(
    frame: ActiveRagFrame,
    *,
    enabled_lanes: tuple[tuple[str, bool], ...] = (),
    lane_weights: tuple[tuple[str, float], ...] = (),
) -> HybridRagQuery:
    selected = compact_whitespace(frame.selected_text)
    context = compact_whitespace(" ".join(item for item in (frame.surrounding_before, frame.surrounding_after) if item))
    intent_terms = {
        "rewrite": "改写 优化 表达",
        "continue": "续写 下一步 候选",
        "summarize": "总结 压缩 重点",
        "debug": "排错 原因 修复",
    }
    query_text = compact_whitespace(" ".join(item for item in (selected, intent_terms.get(frame.intent, frame.intent), context) if item))
    return HybridRagQuery(
        query_text=query_text or selected,
        raw_input=selected,
        preedit=selected[:80],
        committed_tail=context,
        rime_candidates=(),
        project=frame.project,
        app=frame.app or frame.front_app_bundle_id,
        input_mode="active_rag_assist",
        top_k=max(1, min(12, int(frame.max_candidates) * 3)),
        latency_budget_ms=2500,
        enabled_lanes=enabled_lanes,
        lane_weights=lane_weights,
    )


def _evidence_from_candidate(candidate: HybridRagCandidate) -> ActiveRagEvidence:
    return ActiveRagEvidence(
        evidence_id=candidate.candidate_id,
        text=candidate.text,
        source_type=candidate.source_type,
        source_lane=candidate.source_lane,
        score=candidate.score,
        confidence=candidate.confidence,
        tags=candidate.tags,
        memory_ids=candidate.memory_ids,
        atom_ids=candidate.atom_ids,
        book_ids=candidate.book_ids,
        evidence_event_ids=candidate.evidence_event_ids,
        preview=candidate.evidence_preview,
        metadata={**dict(candidate.metadata), "activeRagEvidence": True},
    )
