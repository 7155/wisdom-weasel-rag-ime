from __future__ import annotations

import sqlite3

from .active_rag_models import ActiveRagEvidence, ActiveRagFrame
from .embeddings import EmbeddingProvider
from .hybrid_rag_models import HybridRagCandidate, HybridRagQuery, MemoryHit
from .hybrid_rag_retriever import retrieve_hybrid_rag_memory_hit_objects
from .local_sqlite_core import LocalSqliteCoreClient
from .text_utils import compact_whitespace, token_terms


_GENERIC_CONTEXT_TERMS = {
    "这里", "当前", "前台", "上下文", "测试", "输入", "生成", "内容", "这个", "那个",
    "目前", "应该", "需要", "没有", "可以", "进行", "一个", "一下", "问题", "功能",
}
_TEMPORAL_RECALL_TERMS = {"今天", "昨天", "最近", "本周", "上周", "上午", "下午", "晚上", "回忆"}
_ACTIVE_RAG_RETRIEVAL_POOL = 64
_ACTIVE_RAG_EVIDENCE_LIMIT = 12


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
    candidates = _diversify_active_rag_evidence(
        candidates,
        limit=_ACTIVE_RAG_EVIDENCE_LIMIT,
    )
    return tuple(_evidence_from_candidate(candidate) for candidate in candidates)


def _retrieve_candidates_read_only(
    conn: sqlite3.Connection,
    query: HybridRagQuery,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[MemoryHit]:
    return retrieve_hybrid_rag_memory_hit_objects(conn, query, embedding_provider)


def _query_from_frame(
    frame: ActiveRagFrame,
    *,
    enabled_lanes: tuple[tuple[str, bool], ...] = (),
    lane_weights: tuple[tuple[str, float], ...] = (),
) -> HybridRagQuery:
    selected = compact_whitespace(frame.selected_text)
    foreground = compact_whitespace(frame.surrounding_before)
    context = compact_whitespace(
        " ".join(item for item in (foreground, frame.surrounding_after) if item)
    )
    query_text = (
        selected
        if frame.placement == "replace_selection" and selected
        else (foreground or selected)
    )
    return HybridRagQuery(
        # query_text drives both the semantic embedding and primary BM25 lane.
        # Generic intent words and the short caret anchor must not displace the
        # complete foreground document in explicit generation.
        query_text=query_text or context[-4_000:],
        raw_input=selected,
        preedit=selected[:80],
        committed_tail=context[-4_000:],
        rime_candidates=(),
        project=frame.project,
        app=frame.app or frame.front_app_bundle_id,
        input_mode="active_rag_assist",
        # Explicit knowledge generation needs enough evidence to rerank even
        # when only one final text candidate is requested.
        # Retrieve a wider pool before the Active RAG evidence selector keeps
        # the best facts and at least one relevant Topic Book. Asking the
        # hybrid core for only the final 12 let dense Atom rows crowd every
        # Book out even when the Book directly matched the query.
        top_k=_ACTIVE_RAG_RETRIEVAL_POOL,
        latency_budget_ms=2500,
        enabled_lanes=enabled_lanes,
        lane_weights=lane_weights,
    )


def _evidence_from_candidate(candidate: MemoryHit | HybridRagCandidate) -> ActiveRagEvidence:
    text = candidate.text
    preview_prefix = compact_whitespace(candidate.evidence_preview).split("：", 1)[0].split(":", 1)[0]
    if candidate.source_type not in {"phrase", "surface_phrase"} and len(compact_whitespace(text)) < 4:
        if 4 <= len(preview_prefix) <= 40:
            text = preview_prefix
    return ActiveRagEvidence(
        evidence_id=(
            candidate.hit_id
            if isinstance(candidate, MemoryHit)
            else candidate.candidate_id
        ),
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
    candidates: list[MemoryHit | HybridRagCandidate],
    *,
    frame: ActiveRagFrame,
) -> list[MemoryHit | HybridRagCandidate]:
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
    accepted: list[MemoryHit | HybridRagCandidate] = []
    for candidate in candidates:
        if isinstance(candidate, MemoryHit) and compact_whitespace(candidate.doc_type).lower() == "item":
            # ``item`` is the legacy memory_items projection. It has no Atom or
            # Book lifecycle contract and may contain an exact text+summary
            # duplicate, so it must not occupy explicit-generation grounding.
            continue
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


def _diversify_active_rag_evidence(
    candidates: list[MemoryHit | HybridRagCandidate],
    *,
    limit: int,
) -> list[MemoryHit | HybridRagCandidate]:
    """Keep rank quality while preventing one document layer from monopolizing context."""

    bounded_limit = max(0, int(limit))
    if bounded_limit == 0 or not candidates:
        return []
    selected = list(candidates[:bounded_limit])
    for required_kind in ("atom", "book"):
        if any(_active_rag_document_kind(item) == required_kind for item in selected):
            continue
        required = next(
            (
                item
                for item in candidates[bounded_limit:]
                if _active_rag_document_kind(item) == required_kind
            ),
            None,
        )
        if required is None:
            continue
        replacement_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if _active_rag_document_kind(selected[index]) != required_kind
            ),
            -1,
        )
        if replacement_index >= 0:
            selected[replacement_index] = required
    return selected


def _active_rag_document_kind(candidate: MemoryHit | HybridRagCandidate) -> str:
    if isinstance(candidate, MemoryHit):
        return compact_whitespace(candidate.doc_type).lower()
    if candidate.book_ids and not candidate.atom_ids:
        return "book"
    if candidate.atom_ids:
        return "atom"
    return "other"
