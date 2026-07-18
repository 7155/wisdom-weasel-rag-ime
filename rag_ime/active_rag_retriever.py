from __future__ import annotations

import sqlite3

from .active_rag_models import ActiveRagEvidence, ActiveRagFrame
from .embeddings import EmbeddingProvider
from .hybrid_rag_models import HybridRagCandidate, HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidate_objects
from .local_sqlite_core import LocalSqliteCoreClient
from .text_utils import compact_whitespace, token_terms


_GENERIC_CONTEXT_TERMS = {
    "这里", "当前", "前台", "上下文", "测试", "输入", "生成", "内容", "这个", "那个",
    "目前", "应该", "需要", "没有", "可以", "进行", "一个", "一下", "问题", "功能",
}
_TEMPORAL_RECALL_TERMS = {"今天", "昨天", "最近", "本周", "上周", "上午", "下午", "晚上", "回忆"}


def retrieve_active_rag_evidence(
    core: LocalSqliteCoreClient,
    frame: ActiveRagFrame,
    *,
    enabled_lanes: tuple[tuple[str, bool], ...] = (),
    lane_weights: tuple[tuple[str, float], ...] = (),
) -> tuple[ActiveRagEvidence, ...]:
    """Retrieve short evidence objects for explicit selected-text assistance."""
    query = _query_from_frame(
        frame,
        enabled_lanes=enabled_lanes,
        lane_weights=lane_weights,
    )
    with core._connect() as conn:
        # Projection maintenance belongs to the outbox workers. Enforce a
        # read-only connection here so a future retriever change cannot sneak
        # writes back into the latency-sensitive query path.
        conn.execute("PRAGMA query_only = ON")
        candidates = _retrieve_candidates_read_only(
            conn,
            query,
            embedding_provider=core.embedding_provider,
        )
    candidates = _relevant_active_rag_candidates(candidates, frame=frame)
    return tuple(_evidence_from_candidate(candidate) for candidate in candidates)


def _retrieve_candidates_read_only(
    conn: sqlite3.Connection,
    query: HybridRagQuery,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[HybridRagCandidate]:
    return retrieve_hybrid_rag_candidate_objects(conn, query, embedding_provider)


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
    intent_term = intent_terms.get(frame.intent, "")
    query_text = compact_whitespace(" ".join(item for item in (selected, intent_term) if item))
    return HybridRagQuery(
        query_text=query_text or context[-240:],
        raw_input=selected,
        preedit=selected[:80],
        committed_tail=context[-400:],
        rime_candidates=(),
        project=frame.project,
        app=frame.app or frame.front_app_bundle_id,
        input_mode="active_rag_assist",
        # Explicit knowledge generation needs enough evidence to rerank even
        # when only one final text candidate is requested.
        top_k=12,
        latency_budget_ms=2500,
        enabled_lanes=enabled_lanes,
        lane_weights=lane_weights,
    )


def _evidence_from_candidate(candidate: HybridRagCandidate) -> ActiveRagEvidence:
    text = candidate.text
    preview_prefix = compact_whitespace(candidate.evidence_preview).split("：", 1)[0].split(":", 1)[0]
    if candidate.source_type not in {"phrase", "surface_phrase"} and len(compact_whitespace(text)) < 4:
        if 4 <= len(preview_prefix) <= 40:
            text = preview_prefix
    return ActiveRagEvidence(
        evidence_id=candidate.candidate_id,
        text=text,
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


def _relevant_active_rag_candidates(
    candidates: list[HybridRagCandidate],
    *,
    frame: ActiveRagFrame,
) -> list[HybridRagCandidate]:
    """Drop retrieval hits that have rank support but no semantic evidence for this field.

    Project/app/group priors help order relevant documents, but they must never
    manufacture relevance on their own. This gate keeps generic foreground
    text from surfacing a fixed top-k memory count.
    """
    basis = compact_whitespace(
        " ".join(
            value
            for value in (
                frame.selected_text,
                frame.surrounding_before[-600:],
                frame.surrounding_after[:120],
            )
            if value
        )
    )
    terms = [term for term in token_terms(basis, max_terms=64) if len(term) >= 2 and term not in _GENERIC_CONTEXT_TERMS]
    temporal_recall = any(term in basis for term in _TEMPORAL_RECALL_TERMS)
    accepted: list[HybridRagCandidate] = []
    for candidate in candidates:
        metadata = dict(candidate.metadata)
        lanes = {str(value) for value in metadata.get("lanes") or []}
        haystack = compact_whitespace(
            " ".join((candidate.text, candidate.evidence_preview, " ".join(candidate.tags)))
        ).lower()
        overlap = {term for term in terms if term.lower() in haystack}
        raw_scores = metadata.get("rawScores") if isinstance(metadata.get("rawScores"), dict) else {}
        vector_score = max(
            (float(raw_scores.get(lane) or 0.0) for lane in ("vector_raw", "vector_tag_boost")),
            default=0.0,
        )
        lexical_support = bool(overlap) and bool(lanes & {"bm25_raw", "bm25_tags", "tagmemo", "feedback"})
        strong_vector_support = len(terms) >= 2 and vector_score >= 0.72 and candidate.confidence >= 0.65
        temporal_support = temporal_recall and "time" in lanes
        if lexical_support or strong_vector_support or temporal_support:
            accepted.append(candidate)
    return accepted
