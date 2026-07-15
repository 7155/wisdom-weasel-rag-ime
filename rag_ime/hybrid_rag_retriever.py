from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Mapping

from .context_group import ContextGroup, context_group_compatibility
from .embeddings import EmbeddingProvider, cosine_similarity, embed_query
from .hybrid_rag_models import HybridRagCandidate, HybridRagHit, HybridRagQuery
from .hybrid_rag_ranker import rank_hybrid_hits
from .memory_book_lifecycle import set_memory_book_archive_status
from .memory_ingest import normalize_text
from .memory_tag_graph import TagActivation
from .query_expansion import build_query_expansion
from .retrieval_vector_index import build_tag_boosted_query_vector, load_retrieval_doc_vectors
from .text_utils import compact_whitespace, token_terms


HYBRID_RAG_RETRIEVAL_SCHEMA_VERSION = "rag-ime.hybrid-rag-retrieval.v1"
_EXPLICIT_HISTORY_RE = re.compile(
    r"(?:之前|以前|最初|初版|旧版|旧项目|归档|历史|当时|过去|去年|上周|上月|"
    r"\d{4}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?)",
    re.IGNORECASE,
)


def retrieve_hybrid_rag_candidates(
    conn: sqlite3.Connection,
    query: HybridRagQuery,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    # ACL is the first retrieval stage: private documents must not seed aliases,
    # Tag activation, expansion terms, vectors, or diagnostics.
    docs = _active_docs(conn, query=query)
    expansion = build_query_expansion(
        conn,
        query_text=query.query_text,
        raw_input=query.raw_input,
        preedit=query.preedit,
        rime_candidates=query.rime_candidates,
        committed_tail=query.committed_tail,
        project=query.project,
        app=query.app,
        visible_doc_ids=tuple(str(doc["doc_id"]) for doc in docs),
        visible_source_ids=tuple(str(doc["source_id"]) for doc in docs),
        visible_atom_ids=tuple(
            str(doc["source_id"]) for doc in docs if str(doc["doc_type"]) == "atom"
        ),
    )
    blocked = _blocked_sets(conn)
    vector_available = bool(embedding_provider and embedding_provider.fingerprint != "none")
    enabled_lanes = _resolved_lane_enabled(query.enabled_lanes, vector_available=vector_available)
    lane_weights = _resolved_lane_weights(query.lane_weights)
    vectors = (
        load_retrieval_doc_vectors(conn, embedding_provider.fingerprint, (str(doc["doc_id"]) for doc in docs))
        if vector_available and embedding_provider is not None else {}
    )
    query_vector = embed_query(embedding_provider, expansion.primary_query) if vectors and embedding_provider else []
    boosted_query_vector, tag_boost_diagnostics = build_tag_boosted_query_vector(
        conn,
        provider_fingerprint=embedding_provider.fingerprint if embedding_provider is not None else "",
        query_vector=query_vector,
        weighted_tags=((item.tag, item.energy) for item in expansion.activated_tag_details),
    )
    # SQLite connections are thread-affine by default. Complete SQL-backed
    # lanes here; CPU-only scoring lanes then run in parallel.
    lexical_lane_meta: dict[str, str] = {}
    bm25_raw_hits = []
    if enabled_lanes["bm25_raw"]:
        bm25_raw_hits, lexical_lane_meta["bm25_raw"] = _rank_fts5_docs(
            conn,
            docs=docs,
            lane="bm25_raw",
            terms=(expansion.primary_query, *expansion.lexical_terms),
            fields=("raw_text",),
            blocked=blocked,
            project=query.project,
            app=query.app,
            limit=max(8, query.top_k * 4),
        )
    bm25_tags_hits = []
    if enabled_lanes["bm25_tags"]:
        bm25_tags_hits, lexical_lane_meta["bm25_tags"] = _rank_fts5_docs(
            conn,
            docs=docs,
            lane="bm25_tags",
            terms=(*expansion.matched_aliases, *expansion.activated_tags, *expansion.expansion_terms),
            fields=("tags_text", "aliases_text", "surface_hints_text", "query_expansions_text"),
            blocked=blocked,
            project=query.project,
            app=query.app,
            limit=max(8, query.top_k * 4),
        )
    tagmemo_hits = []
    if enabled_lanes["tagmemo"]:
        tagmemo_hits, lexical_lane_meta["tagmemo"] = _rank_fts5_docs(
            conn,
            docs=docs,
            lane="tagmemo",
            terms=expansion.activated_tags,
            fields=("tags_text", "aliases_text", "query_expansions_text"),
            blocked=blocked,
            project=query.project,
            app=query.app,
            limit=max(8, query.top_k * 4),
        )
        tagmemo_hits = _rerank_tagmemo_hits(
            tagmemo_hits,
            docs=docs,
            activations=expansion.activated_tag_details,
        )
    feedback_hits = (
        _feedback_hits(
            conn,
            docs=docs,
            query=query,
            terms=(*expansion.lexical_terms, *expansion.matched_aliases, *expansion.activated_tags),
            blocked=blocked,
            limit=max(8, query.top_k * 4),
        )
        if enabled_lanes["feedback"] else []
    )
    tasks = {
        "vector_raw": lambda: _rank_vector_docs(
            docs, vectors=vectors, query_vector=query_vector, lane="vector_raw", vector_index=0,
            blocked=blocked, limit=max(8, query.top_k * 4),
        ) if enabled_lanes["vector_raw"] else [],
        "vector_tag_boost": lambda: _rank_vector_docs(
            docs, vectors=vectors, query_vector=boosted_query_vector, lane="vector_tag_boost", vector_index=1,
            blocked=blocked, limit=max(8, query.top_k * 4), include_group=True,
        ) if enabled_lanes["vector_tag_boost"] else [],
        "time": lambda: (
            _rank_time_docs(
                docs,
                expansion_terms=(*expansion.expansion_terms, *expansion.activated_tags),
                blocked=blocked,
                limit=max(8, query.top_k * 4),
            )
            if enabled_lanes["time"]
            else []
        ),
        "feedback": lambda: feedback_hits,
    }
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="rag-lane") as executor:
        futures = {name: executor.submit(task) for name, task in tasks.items()}
        lane_hits = {name: future.result() for name, future in futures.items()}
    lane_hits.update({
        "bm25_raw": bm25_raw_hits,
        "bm25_tags": bm25_tags_hits,
        "tagmemo": tagmemo_hits,
    })
    hits = [hit for lane in lane_hits.values() for hit in lane]
    candidates = rank_hybrid_hits(
        hits,
        query_text=query.query_text,
        committed_tail=query.committed_tail,
        top_k=query.top_k,
        lane_weights=lane_weights,
        decay_settings=_memory_decay_settings(conn),
    )
    reactivated_book_ids = _reactivate_archived_books_for_explicit_history(
        conn,
        hits=hits,
        candidates=candidates,
        query_text=" ".join(
            item
            for item in (query.query_text, query.raw_input, query.committed_tail)
            if compact_whitespace(item)
        ),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "schemaVersion": HYBRID_RAG_RETRIEVAL_SCHEMA_VERSION,
        "query": {
            "primary": expansion.primary_query,
            "lexicalTerms": list(expansion.lexical_terms),
            "matchedAliases": list(expansion.matched_aliases),
            "activatedTags": list(expansion.activated_tags),
            "activatedTagDetails": [
                {
                    "tag": item.tag,
                    "energy": round(item.energy, 6),
                    "hop": item.hop,
                    "path": list(item.path_tags),
                    "edgeTypes": list(item.edge_types),
                    "evidenceCount": item.evidence_count,
                }
                for item in expansion.activated_tag_details
            ],
            "negativeTags": list(expansion.negative_tags),
            "expansionTerms": list(expansion.expansion_terms),
            "tagBoost": tag_boost_diagnostics,
        },
        "lanes": {
            name: {
                "enabled": enabled_lanes[name],
                "available": vector_available if name in {"vector_raw", "vector_tag_boost"} else True,
                "implementation": _lane_implementation(
                    name,
                    lexical_lane_meta=lexical_lane_meta,
                    vector_available=vector_available,
                ),
                "lexicalFallback": _lane_implementation(
                    name,
                    lexical_lane_meta=lexical_lane_meta,
                    vector_available=vector_available,
                ) == "lexical_substring_fallback",
                "fts5Bm25": _lane_implementation(
                    name,
                    lexical_lane_meta=lexical_lane_meta,
                    vector_available=vector_available,
                ) == "sqlite_fts5_bm25",
                "skippedReason": (
                    ("embedding_provider_not_wired" if not vector_available else "vector_index_empty")
                    if name in {"vector_raw", "vector_tag_boost"} and not values
                    else ("disabled_by_effective_runtime_config" if not enabled_lanes[name] else "")
                ),
                "weight": lane_weights[name],
                "count": len(values),
                "docIds": [hit.doc_id for hit in values[:5]],
            }
            for name, values in lane_hits.items()
        },
        "elapsedMs": elapsed_ms,
        "parallelExecution": True,
        "vectorIndexDocuments": len(vectors),
        "overBudget": elapsed_ms > max(1, int(query.latency_budget_ms)),
        "hits": [hit.__dict__ for hit in hits],
        "candidates": [candidate.__dict__ for candidate in candidates],
        "reactivatedBookIds": reactivated_book_ids,
    }


_DEFAULT_LANE_WEIGHTS = {
    "bm25_raw": 1.00,
    "bm25_tags": 1.15,
    "vector_raw": 0.95,
    "vector_tag_boost": 1.05,
    "tagmemo": 1.10,
    "time": 0.90,
    "feedback": 1.20,
}


def _resolved_lane_enabled(values: tuple[tuple[str, bool], ...], *, vector_available: bool = False) -> dict[str, bool]:
    configured = {str(key): bool(value) for key, value in values}
    resolved = {lane: configured.get(lane, True) for lane in _DEFAULT_LANE_WEIGHTS}
    resolved["vector_raw"] = vector_available and resolved["vector_raw"]
    resolved["vector_tag_boost"] = vector_available and resolved["vector_tag_boost"]
    return resolved


def _resolved_lane_weights(values: tuple[tuple[str, float], ...]) -> dict[str, float]:
    configured = {str(key): max(0.0, float(value)) for key, value in values}
    return {lane: configured.get(lane, default) for lane, default in _DEFAULT_LANE_WEIGHTS.items()}


def _reactivate_archived_books_for_explicit_history(
    conn: sqlite3.Connection,
    *,
    hits: list[HybridRagHit],
    candidates: list[HybridRagCandidate],
    query_text: str,
) -> list[str]:
    """Restore only archived topic books reached by an explicit history query.

    Ordinary background completion keeps archived books down-weighted and read-only.
    A deliberate request such as "最初需求" or "旧项目" is a user action, so a
    strongly retrieved book may become active again. Related new input also
    reactivates a reused book in the offline Memory Book compiler.
    """

    if _EXPLICIT_HISTORY_RE.search(compact_whitespace(query_text)) is None:
        return []
    restored: list[str] = []
    eligible_book_ids: list[str] = []
    for hit in hits:
        if hit.doc_type != "book" or not bool(hit.metadata.get("archived")):
            continue
        # Time-only recall can contain unrelated old books. A lexical, vector,
        # tag, or feedback lane is the evidence that this archived topic is
        # actually related to the user's explicit historical request.
        if hit.source_lane == "time" or hit.source_id in eligible_book_ids:
            continue
        eligible_book_ids.append(hit.source_id)
    for book_id in eligible_book_ids:
        row = conn.execute(
            "SELECT status, book_type FROM memory_books WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if (
            row is None
            or str(row["status"] or "") != "archived"
            or str(row["book_type"] or "") != "topic"
        ):
            continue
        result = set_memory_book_archive_status(
            conn,
            book_id=book_id,
            archived=False,
            reason="explicit_historical_retrieval",
            actor="hybrid_rag_retriever",
        )
        updated = result.get("book") if isinstance(result.get("book"), dict) else {}
        _refresh_retrieval_book_lifecycle_metadata(
            conn,
            book_id=book_id,
            updated_at_ms=int(updated.get("updatedAtMs") or 0),
            last_active_at_ms=int(updated.get("lastActiveAtMs") or 0),
        )
        for candidate in candidates:
            if book_id in candidate.book_ids:
                candidate.metadata["archived"] = False
                candidate.metadata["reactivated"] = True
        restored.append(book_id)
        if len(restored) >= 2:
            return restored
    return restored


def _refresh_retrieval_book_lifecycle_metadata(
    conn: sqlite3.Connection,
    *,
    book_id: str,
    updated_at_ms: int,
    last_active_at_ms: int,
) -> None:
    rows = conn.execute(
        "SELECT doc_id, metadata_json FROM memory_retrieval_docs WHERE doc_type = 'book' AND source_id = ?",
        (book_id,),
    ).fetchall()
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        metadata.update(
            {
                "bookStatus": "active",
                "archived": False,
                "archivedAtMs": 0,
                "archiveReason": "",
                "lastActiveAtMs": last_active_at_ms,
                "sourceUpdatedAtMs": updated_at_ms,
            }
        )
        conn.execute(
            "UPDATE memory_retrieval_docs SET metadata_json = ?, updated_at_ms = ? WHERE doc_id = ?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), updated_at_ms, str(row["doc_id"])),
        )


def _lane_implementation(
    lane: str,
    *,
    lexical_lane_meta: dict[str, str],
    vector_available: bool,
) -> str:
    if lane in {"bm25_raw", "bm25_tags", "tagmemo"}:
        return lexical_lane_meta.get(lane, "disabled")
    if lane in {"vector_raw", "vector_tag_boost"}:
        return "precomputed_cosine" if vector_available else "not_wired"
    if lane == "time":
        return "recency_term_scoring"
    if lane == "feedback":
        return "accepted_feedback_relevance"
    return "native"


def retrieve_hybrid_rag_candidate_objects(
    conn: sqlite3.Connection,
    query: HybridRagQuery,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[HybridRagCandidate]:
    payload = retrieve_hybrid_rag_candidates(conn, query, embedding_provider)
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
               query_expansions_text, time_key, project, app, updated_at_ms, metadata_json
        FROM memory_retrieval_docs
        WHERE status = 'active'
          AND (? = '' OR project = ? OR project = '')
          AND (? = '' OR app = ? OR app = '')
        """,
        (query.project, query.project, query.app, query.app),
    ).fetchall()
    prepared = [
        {
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
            "updated_at_ms": int(row["updated_at_ms"] or 0),
            "metadata": _metadata(row["metadata_json"]),
        }
        for row in rows
    ]
    event_ids_by_doc = _retrieval_doc_event_map(conn, prepared)
    all_event_ids = sorted({event_id for values in event_ids_by_doc.values() for event_id in values})
    agent_links = _agent_event_links(conn, all_event_ids)
    deleted_event_ids = _deleted_event_ids(conn, all_event_ids)
    room_owner_ids: set[str] = set()
    for doc in prepared:
        metadata = dict(doc.get("metadata") or {})
        if str(metadata.get("ownerKind") or metadata.get("owner_kind") or "") == "room":
            room_id = str(metadata.get("ownerId") or metadata.get("owner_id") or "")
            if room_id and room_id in query.reader_room_ids:
                room_owner_ids.add(room_id)
    room_members = _active_room_members(conn, room_owner_ids)
    current_group = ContextGroup(
        context_group_id=compact_whitespace(query.context_group_id),
        context_group_level=query.context_group_level if query.context_group_level in {"document", "project", "app", "global"} else "app",
        confidence=1.0 if query.context_group_id else 0.0,
        parent_group_ids=tuple(query.context_group_parent_ids),
        app_bundle_id=compact_whitespace(query.app),
        project=compact_whitespace(query.project),
    )
    docs: list[dict[str, object]] = []
    for doc in prepared:
        metadata = dict(doc.get("metadata") or {})
        if not _retrieval_doc_visible_to_reader(
            event_ids=event_ids_by_doc.get(str(doc["doc_id"]), ()),
            agent_links=agent_links,
            deleted_event_ids=deleted_event_ids,
            room_members=room_members,
            metadata=metadata,
            query=query,
        ):
            continue
        short_term = bool(metadata.get("shortTerm") or metadata.get("short_term"))
        compatibility = context_group_compatibility(
            current_group,
            candidate_group_id=str(metadata.get("contextGroupId") or metadata.get("context_group_id") or ""),
            candidate_project=str(doc["project"] or ""),
            candidate_app=str(doc["app"] or ""),
            short_term=short_term,
        )
        if compatibility <= 0.0:
            continue
        metadata["groupCompatibility"] = compatibility
        docs.append({**doc, "metadata": metadata})
    docs.sort(key=lambda item: float(dict(item.get("metadata") or {}).get("groupCompatibility") or 0.0), reverse=True)
    return docs


def _retrieval_doc_visible_to_reader(
    *,
    event_ids: Iterable[int],
    agent_links: Mapping[int, tuple[Mapping[str, object], ...]],
    deleted_event_ids: set[int],
    room_members: Mapping[str, set[str]],
    metadata: dict[str, object],
    query: HybridRagQuery,
) -> bool:
    owner_kind = compact_whitespace(str(metadata.get("ownerKind") or metadata.get("owner_kind") or ""))
    owner_id = compact_whitespace(str(metadata.get("ownerId") or metadata.get("owner_id") or ""))
    if owner_kind == "session" and owner_id != query.reader_session_id:
        return False
    if owner_kind == "agent" and owner_id != query.reader_agent_id:
        return False
    if owner_kind == "room" and owner_id not in query.reader_room_ids:
        return False
    if owner_kind not in {"", "user", "shared", "session", "agent", "room"}:
        return False

    for event_id in event_ids:
        if event_id in deleted_event_ids:
            return False
        rows = agent_links.get(event_id, ())
        if not rows:
            continue
        if any(str(row.get("status") or "") != "active" for row in rows):
            return False
        visible = False
        for row in rows:
            if str(row.get("source_role") or "") == "user":
                visible = True
                break
            if query.reader_session_id and query.reader_session_id == str(row.get("session_id") or ""):
                visible = True
                break
            if query.reader_agent_id and query.reader_agent_id == str(row.get("agent_id") or ""):
                visible = True
                break
            if owner_kind == "room" and owner_id in query.reader_room_ids:
                if str(row.get("session_id") or "") in room_members.get(owner_id, set()):
                    visible = True
                    break
        if not visible:
            return False
    return True


def _retrieval_doc_event_map(
    conn: sqlite3.Connection,
    docs: Iterable[Mapping[str, object]],
) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    fallback: dict[str, set[str]] = {"atom": set(), "book": set(), "item": set()}
    pending_docs: list[tuple[str, str, str]] = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "")
        doc_type = str(doc.get("doc_type") or "")
        source_id = str(doc.get("source_id") or "")
        metadata = dict(doc.get("metadata") or {})
        values: list[object] = []
        source_ids = metadata.get("sourceEventIds") or metadata.get("source_event_ids")
        if isinstance(source_ids, (list, tuple)):
            values.extend(source_ids)
        source_event_id = metadata.get("sourceEventId") or metadata.get("source_event_id")
        if source_event_id not in (None, "", 0, "0"):
            values.append(source_event_id)
        event_ids = _positive_event_ids(values)
        if event_ids:
            result[doc_id] = tuple(event_ids)
            continue
        family = "item" if doc_type in {"item", "phrase"} else doc_type
        if family in fallback and source_id:
            fallback[family].add(source_id)
            pending_docs.append((doc_id, family, source_id))
        else:
            result[doc_id] = ()

    source_events: dict[tuple[str, str], tuple[int, ...]] = {}
    if fallback["atom"]:
        rows = conn.execute(
            """SELECT a.id, a.source_event_ids_json FROM memory_atoms AS a
               JOIN json_each(?) AS wanted ON CAST(wanted.value AS TEXT) = a.id""",
            (json.dumps(sorted(fallback["atom"])),),
        ).fetchall()
        source_events.update({("atom", str(row["id"])): tuple(_json_event_ids(row["source_event_ids_json"])) for row in rows})
    if fallback["book"]:
        rows = conn.execute(
            """SELECT b.book_id, b.source_event_ids_json FROM memory_books AS b
               JOIN json_each(?) AS wanted ON CAST(wanted.value AS TEXT) = b.book_id""",
            (json.dumps(sorted(fallback["book"])),),
        ).fetchall()
        source_events.update({("book", str(row["book_id"])): tuple(_json_event_ids(row["source_event_ids_json"])) for row in rows})
    if fallback["item"]:
        rows = conn.execute(
            """SELECT i.memory_id, i.source_event_id FROM memory_items AS i
               JOIN json_each(?) AS wanted ON CAST(wanted.value AS TEXT) = i.memory_id""",
            (json.dumps(sorted(fallback["item"])),),
        ).fetchall()
        source_events.update({("item", str(row["memory_id"])): tuple(_positive_event_ids([row["source_event_id"]])) for row in rows})
    for doc_id, family, source_id in pending_docs:
        result[doc_id] = source_events.get((family, source_id), ())
    return result


def _agent_event_links(
    conn: sqlite3.Connection,
    event_ids: Iterable[int],
) -> dict[int, tuple[Mapping[str, object], ...]]:
    ids = tuple(dict.fromkeys(int(value) for value in event_ids if int(value) > 0))
    if not ids:
        return {}
    rows = conn.execute(
        """
        SELECT ams.input_event_id, ams.session_id, ams.source_role, ams.status, s.agent_id
        FROM agent_memory_sources AS ams
        JOIN agent_sessions AS s ON s.id = ams.session_id
        JOIN json_each(?) AS wanted ON CAST(wanted.value AS INTEGER) = ams.input_event_id
        """,
        (json.dumps(ids),),
    ).fetchall()
    grouped: dict[int, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(int(row["input_event_id"]), []).append(
            {
                "session_id": str(row["session_id"]),
                "source_role": str(row["source_role"]),
                "status": str(row["status"]),
                "agent_id": str(row["agent_id"]),
            }
        )
    source_rows = conn.execute(
        """
        SELECT e.id, e.source
        FROM input_events AS e
        JOIN json_each(?) AS wanted ON CAST(wanted.value AS INTEGER) = e.id
        WHERE e.source IN ('pi_agent_tool_receipt', 'pi_agent_user')
        """,
        (json.dumps(ids),),
    ).fetchall()
    for row in source_rows:
        event_id = int(row["id"])
        if event_id in grouped:
            continue
        source = str(row["source"] or "")
        grouped[event_id] = [
            {
                "session_id": "",
                "source_role": "user" if source == "pi_agent_user" else "tool_receipt",
                "status": "active" if source == "pi_agent_user" else "orphaned",
                "agent_id": "",
            }
        ]
    return {event_id: tuple(values) for event_id, values in grouped.items()}


def _deleted_event_ids(conn: sqlite3.Connection, event_ids: Iterable[int]) -> set[int]:
    ids = tuple(dict.fromkeys(int(value) for value in event_ids if int(value) > 0))
    if not ids:
        return set()
    return {
        int(row["event_id"])
        for row in conn.execute(
            """SELECT ms.event_id FROM memory_state AS ms
               JOIN json_each(?) AS wanted ON CAST(wanted.value AS INTEGER) = ms.event_id
               WHERE ms.deleted = 1""",
            (json.dumps(ids),),
        ).fetchall()
    }


def _active_room_members(conn: sqlite3.Connection, room_ids: Iterable[str]) -> dict[str, set[str]]:
    ids = tuple(dict.fromkeys(str(value) for value in room_ids if str(value)))
    if not ids:
        return {}
    rows = conn.execute(
        """
        SELECT p.room_id, p.session_id
        FROM agent_room_participants AS p
        JOIN agent_rooms AS r ON r.id = p.room_id
        JOIN json_each(?) AS wanted ON CAST(wanted.value AS TEXT) = p.room_id
        WHERE p.participant_status = 'active' AND r.status = 'active'
        """,
        (json.dumps(ids),),
    ).fetchall()
    result: dict[str, set[str]] = {}
    for row in rows:
        result.setdefault(str(row["room_id"]), set()).add(str(row["session_id"]))
    return result


def _json_event_ids(value: object) -> list[int]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return _positive_event_ids(parsed if isinstance(parsed, list) else [])


def _positive_event_ids(values: Iterable[object]) -> list[int]:
    result: list[int] = []
    for raw in values:
        try:
            event_id = int(raw)
        except (TypeError, ValueError):
            continue
        if event_id > 0 and event_id not in result:
            result.append(event_id)
    return result


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


def _rank_fts5_docs(
    conn: sqlite3.Connection,
    *,
    docs: list[dict[str, object]],
    lane: str,
    terms: Iterable[str],
    fields: tuple[str, ...],
    blocked: dict[str, set[str]],
    project: str,
    app: str,
    limit: int,
) -> tuple[list[HybridRagHit], str]:
    """Run a column-scoped FTS5 BM25 query, with an explicit safe fallback.

    The retrieval-doc builder maintains ``memory_retrieval_docs_fts`` with the
    same rowids as the normalized document table.  Keeping the fallback local
    makes a partially migrated database usable, but diagnostics must report it
    as such rather than calling it BM25.
    """

    match_query = _fts5_match_query(terms, fields=fields)
    if not match_query:
        return [], "sqlite_fts5_bm25"
    docs_by_id = {str(doc["doc_id"]): doc for doc in docs}
    if not docs_by_id:
        return [], "sqlite_fts5_bm25"
    try:
        rows = conn.execute(
            """
            SELECT d.doc_id, bm25(memory_retrieval_docs_fts) AS bm25_score
            FROM memory_retrieval_docs_fts
            JOIN memory_retrieval_docs AS d
              ON d.rowid = memory_retrieval_docs_fts.rowid
            JOIN json_each(?) AS visible_docs
              ON CAST(visible_docs.value AS TEXT) = d.doc_id
            WHERE memory_retrieval_docs_fts MATCH ?
              AND d.status = 'active'
              AND (? = '' OR d.project = ? OR d.project = '')
              AND (? = '' OR d.app = ? OR d.app = '')
            ORDER BY bm25(memory_retrieval_docs_fts) ASC, d.updated_at_ms DESC
            LIMIT ?
            """,
            (
                json.dumps(sorted(docs_by_id), ensure_ascii=False),
                match_query,
                project,
                project,
                app,
                app,
                max(1, limit * 8),
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return (
            _rank_docs(docs, lane=lane, terms=terms, fields=fields, blocked=blocked, limit=limit),
            "lexical_substring_fallback",
        )
    hits: list[HybridRagHit] = []
    for row in rows:
        doc = docs_by_id.get(str(row["doc_id"]))
        if doc is None or _doc_blocked(doc, blocked):
            continue
        hits.append(
            _hit_from_doc(
                doc,
                lane=lane,
                rank=len(hits) + 1,
                raw_score=float(row["bm25_score"]),
            )
        )
        if len(hits) >= limit:
            break
    if not hits:
        fallback_hits = _rank_docs(
            docs,
            lane=lane,
            terms=terms,
            fields=fields,
            blocked=blocked,
            limit=limit,
        )
        if fallback_hits:
            return fallback_hits, "lexical_substring_fallback"
    return hits, "sqlite_fts5_bm25"


def _rerank_tagmemo_hits(
    hits: list[HybridRagHit],
    *,
    docs: list[dict[str, object]],
    activations: tuple[TagActivation, ...],
) -> list[HybridRagHit]:
    if not hits or not activations:
        return hits
    docs_by_id = {str(doc["doc_id"]): doc for doc in docs}
    normalized_activations = [
        (normalize_text(activation.tag), activation)
        for activation in activations
        if normalize_text(activation.tag)
    ]
    weighted: list[tuple[float, int, HybridRagHit]] = []
    for hit in hits:
        doc = docs_by_id.get(hit.doc_id)
        if doc is None:
            weighted.append((0.0, hit.rank, hit))
            continue
        haystack = normalize_text(" ".join(
            str(doc.get(field) or "")
            for field in ("tags_text", "aliases_text", "query_expansions_text")
        ))
        matched = [
            activation
            for normalized_tag, activation in normalized_activations
            if normalized_tag in haystack
        ]
        best = max(matched, key=lambda activation: activation.energy) if matched else None
        metadata = dict(hit.metadata)
        if best is not None:
            metadata.update({
                "tagActivationEnergy": round(best.energy, 6),
                "tagActivationHop": best.hop,
                "tagActivationPath": list(best.path_tags),
                "tagActivationEvidenceCount": best.evidence_count,
            })
        updated = replace(hit, metadata=metadata)
        weighted.append((best.energy if best is not None else 0.0, hit.rank, updated))
    weighted.sort(key=lambda item: (-item[0], item[1]))
    return [replace(hit, rank=index) for index, (_energy, _old_rank, hit) in enumerate(weighted, start=1)]


def _fts5_match_query(terms: Iterable[str], *, fields: tuple[str, ...]) -> str:
    normalized: list[str] = []
    for value in terms:
        normalized.extend(token_terms(str(value), max_terms=24))
    unique_terms = _unique(normalized)
    if not unique_terms or not fields:
        return ""
    escaped = [f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in unique_terms]
    return f"{{{' '.join(fields)}}} : ({' OR '.join(escaped)})"


def _rank_vector_docs(
    docs: list[dict[str, object]],
    *,
    vectors: dict[str, tuple[list[float], list[float], list[float]]],
    query_vector: list[float],
    lane: str,
    vector_index: int,
    blocked: dict[str, set[str]],
    limit: int,
    include_group: bool = False,
) -> list[HybridRagHit]:
    if not query_vector:
        return []
    eligible: list[tuple[dict[str, object], list[float], list[float]]] = []
    for doc in docs:
        if _doc_blocked(doc, blocked):
            continue
        doc_vectors = vectors.get(str(doc["doc_id"]))
        if doc_vectors and doc_vectors[vector_index]:
            eligible.append((doc, doc_vectors[vector_index], doc_vectors[2]))
    try:
        import numpy as np

        if eligible:
            query_array = np.asarray(query_vector, dtype=np.float32)
            matrix = np.asarray([item[1] for item in eligible], dtype=np.float32)
            scores = matrix @ query_array
            if include_group:
                group_matrix = np.asarray(
                    [item[2] if item[2] else [0.0] * len(query_vector) for item in eligible],
                    dtype=np.float32,
                )
                group_scores = np.maximum(0.0, group_matrix @ query_array)
                compatibility = np.asarray([
                    float(dict(item[0].get("metadata") or {}).get("groupCompatibility") or 0.0)
                    for item in eligible
                ], dtype=np.float32)
                scores = scores * 0.75 + group_scores * 0.15 + compatibility * 0.10
            weighted = [
                (float(score), eligible[index][0])
                for index, score in enumerate(scores)
                if float(score) > 0.0
            ]
            weighted.sort(key=lambda item: item[0], reverse=True)
            return [
                _hit_from_doc(doc, lane=lane, rank=index, raw_score=score)
                for index, (score, doc) in enumerate(weighted[:limit], start=1)
            ]
    except (ImportError, ValueError):
        pass
    weighted: list[tuple[float, dict[str, object]]] = []
    for doc, doc_vector, group_vector in eligible:
        score = cosine_similarity(query_vector, doc_vector)
        if include_group and group_vector:
            group_score = max(0.0, cosine_similarity(query_vector, group_vector))
            compatibility = float(dict(doc.get("metadata") or {}).get("groupCompatibility") or 0.0)
            score = score * 0.75 + group_score * 0.15 + compatibility * 0.10
        if score > 0.0:
            weighted.append((score, doc))
    weighted.sort(key=lambda item: item[0], reverse=True)
    return [
        _hit_from_doc(doc, lane=lane, rank=index, raw_score=score)
        for index, (score, doc) in enumerate(weighted[:limit], start=1)
    ]


def _rank_time_docs(
    docs: list[dict[str, object]],
    *,
    expansion_terms: Iterable[str],
    blocked: dict[str, set[str]],
    limit: int,
) -> list[HybridRagHit]:
    terms = [normalize_text(term) for term in expansion_terms if compact_whitespace(str(term))]
    weighted: list[tuple[float, dict[str, object]]] = []
    now_ms = int(time.time() * 1000)
    for doc in docs:
        if _doc_blocked(doc, blocked):
            continue
        time_key = str(doc.get("time_key") or "")
        if not time_key:
            continue
        haystack = normalize_text(" ".join([str(doc.get("raw_text") or ""), str(doc.get("tags_text") or ""), time_key]))
        matched_terms = {term for term in terms if term and term in haystack}
        lexical_ratio = len(matched_terms) / max(1, len(set(terms)))
        recency = _time_recency_score(time_key, updated_at_ms=int(doc.get("updated_at_ms") or 0), now_ms=now_ms)
        # The Time lane is deliberately an explicit temporal prior, not an
        # unbounded "all Daily Books" fallback. Query overlap keeps an old but
        # relevant book competitive while the half-life prevents it from
        # permanently outranking recent evidence.
        score = 0.20 + 0.55 * recency + 0.65 * lexical_ratio
        weighted.append((score, doc))
    weighted.sort(key=lambda item: item[0], reverse=True)
    return [_hit_from_doc(doc, lane="time", rank=index, raw_score=score) for index, (score, doc) in enumerate(weighted[:limit], start=1)]


def _feedback_hits(
    conn: sqlite3.Connection,
    *,
    docs: list[dict[str, object]],
    query: HybridRagQuery,
    terms: Iterable[str],
    blocked: dict[str, set[str]],
    limit: int,
) -> list[HybridRagHit]:
    source_ids = {str(doc["source_id"]): doc for doc in docs if not _doc_blocked(doc, blocked)}
    if not source_ids:
        return []
    rows = conn.execute(
        """
        SELECT feedback.memory_id, COUNT(*) AS accepted_count
        FROM candidate_feedback AS feedback
        JOIN json_each(?) AS visible_sources
          ON CAST(visible_sources.value AS TEXT) = feedback.memory_id
        WHERE feedback.action = 'accepted'
          AND (? = '' OR feedback.project = ? OR feedback.project = '')
          AND (? = '' OR feedback.app = ? OR feedback.app = '')
        GROUP BY feedback.memory_id
        ORDER BY accepted_count DESC
        LIMIT ?
        """,
        (
            json.dumps(sorted(source_ids), ensure_ascii=False),
            query.project,
            query.project,
            query.app,
            query.app,
            max(1, limit),
        ),
    ).fetchall()
    hits: list[HybridRagHit] = []
    normalized_terms = _unique(token_terms(" ".join(str(item) for item in terms), max_terms=32))
    for index, row in enumerate(rows, start=1):
        doc = source_ids.get(str(row["memory_id"] or ""))
        if doc is None:
            continue
        relevance = _feedback_relevance(doc, normalized_terms)
        if relevance <= 0.0:
            continue
        metadata = dict(doc.get("metadata") or {})
        metadata["feedbackAccepted"] = True
        metadata["acceptedCount"] = int(row["accepted_count"] or 0)
        metadata["feedbackRelevance"] = relevance
        hits.append(
            _hit_from_doc(
                {**doc, "metadata": metadata},
                lane="feedback",
                rank=len(hits) + 1,
                raw_score=float(row["accepted_count"] or 0) * (1.0 + relevance),
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _feedback_relevance(doc: dict[str, object], terms: list[str]) -> float:
    if not terms:
        return 0.0
    haystack = normalize_text(
        " ".join(
            str(doc.get(field) or "")
            for field in ("raw_text", "tags_text", "aliases_text", "surface_hints_text", "query_expansions_text")
        )
    )
    if not haystack:
        return 0.0
    matched = {term for term in terms if term and term in haystack}
    return len(matched) / max(1, len(terms))


_TIME_KEY_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{8})(?!\d)")


def _time_recency_score(time_key: str, *, updated_at_ms: int, now_ms: int) -> float:
    reference_ms = _time_key_ms(time_key) or max(0, int(updated_at_ms))
    if reference_ms <= 0:
        return 0.0
    age_days = max(0.0, (max(0, now_ms - reference_ms)) / 86_400_000.0)
    return math.exp(-math.log(2.0) * age_days / 30.0)


def _time_key_ms(time_key: str) -> int:
    match = _TIME_KEY_DATE_RE.search(str(time_key or ""))
    if match is None:
        return 0
    value = match.group(1)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d" if "-" in value else "%Y%m%d")
    except ValueError:
        return 0
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


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


def _memory_decay_settings(conn: sqlite3.Connection) -> dict[str, object]:
    try:
        row = conn.execute(
            "SELECT value_json FROM management_settings WHERE key = 'memory' LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    payload = _metadata(row[0])
    value = payload.get("timeDecay")
    return dict(value) if isinstance(value, dict) else {}


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
