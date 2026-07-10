from __future__ import annotations

import json
import sqlite3
import time
from typing import Iterable

from .context_group import ContextGroup, context_group_compatibility
from .hybrid_rag_models import HybridRagCandidate, HybridRagHit, HybridRagQuery
from .hybrid_rag_ranker import rank_hybrid_hits
from .memory_ingest import normalize_text
from .query_expansion import build_query_expansion
from .text_utils import compact_whitespace, token_terms


HYBRID_RAG_RETRIEVAL_SCHEMA_VERSION = "rag-ime.hybrid-rag-retrieval.v1"


def retrieve_hybrid_rag_candidates(conn: sqlite3.Connection, query: HybridRagQuery) -> dict[str, object]:
    started = time.perf_counter()
    expansion = build_query_expansion(
        conn,
        query_text=query.query_text,
        raw_input=query.raw_input,
        preedit=query.preedit,
        rime_candidates=query.rime_candidates,
        committed_tail=query.committed_tail,
        project=query.project,
        app=query.app,
    )
    docs = _active_docs(conn, query=query)
    blocked = _blocked_sets(conn)
    lane_hits: dict[str, list[HybridRagHit]] = {
        "bm25_raw": _rank_docs(
            docs,
            lane="bm25_raw",
            terms=(expansion.primary_query, *expansion.lexical_terms),
            fields=("raw_text",),
            blocked=blocked,
            limit=max(8, query.top_k * 4),
        ),
        "bm25_tags": _rank_docs(
            docs,
            lane="bm25_tags",
            terms=(*expansion.matched_aliases, *expansion.activated_tags, *expansion.expansion_terms),
            fields=("tags_text", "aliases_text", "surface_hints_text", "query_expansions_text"),
            blocked=blocked,
            limit=max(8, query.top_k * 4),
        ),
        "vector_raw": [],
        "vector_tag_boost": [],
        "tagmemo": _rank_docs(
            docs,
            lane="tagmemo",
            terms=expansion.activated_tags,
            fields=("tags_text", "aliases_text", "query_expansions_text"),
            blocked=blocked,
            limit=max(8, query.top_k * 4),
        ),
        "time": _rank_time_docs(docs, expansion_terms=(*expansion.expansion_terms, *expansion.activated_tags), blocked=blocked, limit=max(8, query.top_k * 4)),
        "feedback": _feedback_hits(conn, docs=docs, query=query, blocked=blocked, limit=max(8, query.top_k * 4)),
    }
    hits = [hit for lane in lane_hits.values() for hit in lane]
    candidates = rank_hybrid_hits(
        hits,
        query_text=query.query_text,
        committed_tail=query.committed_tail,
        top_k=query.top_k,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "schemaVersion": HYBRID_RAG_RETRIEVAL_SCHEMA_VERSION,
        "query": {
            "primary": expansion.primary_query,
            "lexicalTerms": list(expansion.lexical_terms),
            "matchedAliases": list(expansion.matched_aliases),
            "activatedTags": list(expansion.activated_tags),
            "negativeTags": list(expansion.negative_tags),
            "expansionTerms": list(expansion.expansion_terms),
        },
        "lanes": {
            name: {"count": len(values), "docIds": [hit.doc_id for hit in values[:5]]}
            for name, values in lane_hits.items()
        },
        "elapsedMs": elapsed_ms,
        "overBudget": elapsed_ms > max(1, int(query.latency_budget_ms)),
        "hits": [hit.__dict__ for hit in hits],
        "candidates": [candidate.__dict__ for candidate in candidates],
    }


def retrieve_hybrid_rag_candidate_objects(conn: sqlite3.Connection, query: HybridRagQuery) -> list[HybridRagCandidate]:
    payload = retrieve_hybrid_rag_candidates(conn, query)
    candidates: list[HybridRagCandidate] = []
    for item in payload.get("candidates", []):
        if isinstance(item, HybridRagCandidate):
            candidates.append(item)
        elif isinstance(item, dict):
            candidates.append(
                HybridRagCandidate(
                    candidate_id=str(item["candidate_id"]),
                    text=str(item["text"]),
                    insert_text=str(item["insert_text"]),
                    source_type=str(item["source_type"]),
                    source_lane=str(item["source_lane"]),
                    score=float(item["score"]),
                    confidence=float(item["confidence"]),
                    tags=tuple(item.get("tags") or ()),
                    memory_ids=tuple(item.get("memory_ids") or ()),
                    atom_ids=tuple(item.get("atom_ids") or ()),
                    book_ids=tuple(item.get("book_ids") or ()),
                    evidence_event_ids=tuple(int(value) for value in item.get("evidence_event_ids") or ()),
                    evidence_preview=str(item.get("evidence_preview") or ""),
                    debug_features=dict(item.get("debug_features") or {}),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
    return candidates


def _active_docs(conn: sqlite3.Connection, *, query: HybridRagQuery) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT doc_id, doc_type, source_id, raw_text, tags_text, aliases_text, surface_hints_text,
               query_expansions_text, time_key, project, app, metadata_json
        FROM memory_retrieval_docs
        WHERE status = 'active'
          AND (? = '' OR project = ? OR project = '')
          AND (? = '' OR app = ? OR app = '')
        """,
        (query.project, query.project, query.app, query.app),
    ).fetchall()
    current_group = ContextGroup(
        context_group_id=compact_whitespace(query.context_group_id),
        context_group_level=query.context_group_level if query.context_group_level in {"document", "project", "app", "global"} else "app",
        confidence=1.0 if query.context_group_id else 0.0,
        parent_group_ids=tuple(query.context_group_parent_ids),
        app_bundle_id=compact_whitespace(query.app),
        project=compact_whitespace(query.project),
    )
    docs: list[dict[str, object]] = []
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        short_term = bool(metadata.get("shortTerm") or metadata.get("short_term"))
        compatibility = context_group_compatibility(
            current_group,
            candidate_group_id=str(metadata.get("contextGroupId") or metadata.get("context_group_id") or ""),
            candidate_project=str(row["project"] or ""),
            candidate_app=str(row["app"] or ""),
            short_term=short_term,
        )
        if compatibility <= 0.0:
            continue
        metadata["groupCompatibility"] = compatibility
        docs.append({
            "doc_id": str(row["doc_id"]),
            "doc_type": str(row["doc_type"]),
            "source_id": str(row["source_id"]),
            "raw_text": str(row["raw_text"] or ""),
            "tags_text": str(row["tags_text"] or ""),
            "aliases_text": str(row["aliases_text"] or ""),
            "surface_hints_text": str(row["surface_hints_text"] or ""),
            "query_expansions_text": str(row["query_expansions_text"] or ""),
            "time_key": str(row["time_key"] or ""),
            "project": str(row["project"] or ""),
            "app": str(row["app"] or ""),
            "metadata": metadata,
        })
    docs.sort(key=lambda item: float(dict(item.get("metadata") or {}).get("groupCompatibility") or 0.0), reverse=True)
    return docs


def _rank_docs(
    docs: list[dict[str, object]],
    *,
    lane: str,
    terms: Iterable[str],
    fields: tuple[str, ...],
    blocked: dict[str, set[str]],
    limit: int,
) -> list[HybridRagHit]:
    weighted: list[tuple[float, dict[str, object]]] = []
    normalized_terms = [normalize_text(term) for term in terms if compact_whitespace(str(term))]
    normalized_terms.extend(token_terms(" ".join(str(term) for term in terms), max_terms=24))
    normalized_terms = _unique(normalized_terms)
    if not normalized_terms:
        return []
    for doc in docs:
        if _doc_blocked(doc, blocked):
            continue
        haystack = normalize_text(" ".join(str(doc.get(field) or "") for field in fields))
        if not haystack:
            continue
        score = sum(1.0 + min(len(term), 8) * 0.02 for term in normalized_terms if term and term in haystack)
        if score <= 0:
            continue
        weighted.append((score, doc))
    weighted.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_doc(doc, lane=lane, rank=index, raw_score=score) for index, (score, doc) in enumerate(weighted[:limit], start=1)]


def _rank_time_docs(
    docs: list[dict[str, object]],
    *,
    expansion_terms: Iterable[str],
    blocked: dict[str, set[str]],
    limit: int,
) -> list[HybridRagHit]:
    terms = [normalize_text(term) for term in expansion_terms if compact_whitespace(str(term))]
    weighted: list[tuple[float, dict[str, object]]] = []
    for doc in docs:
        if _doc_blocked(doc, blocked):
            continue
        time_key = str(doc.get("time_key") or "")
        if not time_key:
            continue
        haystack = normalize_text(" ".join([str(doc.get("raw_text") or ""), str(doc.get("tags_text") or ""), time_key]))
        score = 0.8 + sum(0.5 for term in terms if term and term in haystack)
        weighted.append((score, doc))
    weighted.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_doc(doc, lane="time", rank=index, raw_score=score) for index, (score, doc) in enumerate(weighted[:limit], start=1)]


def _feedback_hits(
    conn: sqlite3.Connection,
    *,
    docs: list[dict[str, object]],
    query: HybridRagQuery,
    blocked: dict[str, set[str]],
    limit: int,
) -> list[HybridRagHit]:
    source_ids = {str(doc["source_id"]): doc for doc in docs if not _doc_blocked(doc, blocked)}
    if not source_ids:
        return []
    rows = conn.execute(
        """
        SELECT memory_id, COUNT(*) AS accepted_count
        FROM candidate_feedback
        WHERE action = 'accepted'
          AND (? = '' OR project = ? OR project = '')
          AND (? = '' OR app = ? OR app = '')
        GROUP BY memory_id
        ORDER BY accepted_count DESC
        LIMIT ?
        """,
        (query.project, query.project, query.app, query.app, max(1, limit)),
    ).fetchall()
    hits: list[HybridRagHit] = []
    for index, row in enumerate(rows, start=1):
        doc = source_ids.get(str(row["memory_id"] or ""))
        if doc is None:
            continue
        metadata = dict(doc.get("metadata") or {})
        metadata["feedbackAccepted"] = True
        metadata["acceptedCount"] = int(row["accepted_count"] or 0)
        hits.append(_hit_from_doc({**doc, "metadata": metadata}, lane="feedback", rank=index, raw_score=float(row["accepted_count"] or 0)))
    return hits


def _hit_from_doc(doc: dict[str, object], *, lane: str, rank: int, raw_score: float) -> HybridRagHit:
    metadata = dict(doc.get("metadata") or {})
    metadata["projectScope"] = bool(doc.get("project"))
    metadata["appScope"] = bool(doc.get("app"))
    if doc.get("doc_type") == "book" and not compact_whitespace(str(metadata.get("bookTitle") or "")):
        metadata["bookTitle"] = _book_title(str(doc.get("raw_text") or ""))
    return HybridRagHit(
        doc_id=str(doc["doc_id"]),
        doc_type=str(doc["doc_type"]),
        source_id=str(doc["source_id"]),
        text=compact_whitespace(str(doc.get("raw_text") or "")),
        surface_hints=tuple(compact_whitespace(str(doc.get("surface_hints_text") or "")).split()),
        tags=tuple(compact_whitespace(str(doc.get("tags_text") or "")).split()),
        source_lane=lane,
        rank=rank,
        raw_score=float(raw_score),
        metadata=metadata,
    )


def _blocked_sets(conn: sqlite3.Connection) -> dict[str, set[str]]:
    blocked = {"memory_id": set(), "normalized_text": set(), "text": set(), "suppressed_memory_id": set(), "suppressed_text": set()}
    for row in conn.execute("SELECT target_type, target_value FROM memory_tombstones WHERE active = 1").fetchall():
        target_type = str(row["target_type"] or "")
        target_value = compact_whitespace(str(row["target_value"] or ""))
        if target_type in blocked and target_value:
            blocked[target_type].update(_memory_id_variants(target_value) if target_type == "memory_id" else {target_value})
    for row in conn.execute("SELECT match_type, match_value FROM memory_candidate_suppressions").fetchall():
        match_type = str(row["match_type"] or "")
        match_value = compact_whitespace(str(row["match_value"] or ""))
        if match_type == "memory_id" and match_value:
            blocked["suppressed_memory_id"].update(_memory_id_variants(match_value))
        elif match_value:
            blocked["suppressed_text"].add(match_value)
    return blocked


def _doc_blocked(doc: dict[str, object], blocked: dict[str, set[str]]) -> bool:
    source_id = str(doc.get("source_id") or "")
    text = compact_whitespace(str(doc.get("raw_text") or ""))
    normalized = normalize_text(text)
    return (
        source_id in blocked["memory_id"]
        or source_id in blocked["suppressed_memory_id"]
        or f"phrase:{normalized}" in blocked["memory_id"]
        or text in blocked["text"]
        or normalized in blocked["normalized_text"]
        or normalized in blocked["suppressed_text"]
    )


def _memory_id_variants(value: str) -> set[str]:
    text = compact_whitespace(value)
    variants = {text}
    if text.startswith("phrase:"):
        variants.add(f"phrase:{normalize_text(text.split(':', 1)[1])}")
    return {item for item in variants if item}


def _metadata(raw: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _book_title(raw_text: str) -> str:
    text = compact_whitespace(raw_text)
    if not text:
        return ""
    return text.split("。", 1)[0].split("，", 1)[0][:24]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = compact_whitespace(str(value))
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
