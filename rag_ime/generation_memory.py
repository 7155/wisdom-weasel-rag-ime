from __future__ import annotations

import sqlite3

from .hybrid_rag_models import HybridRagQuery, MemoryHit
from .hybrid_rag_retriever import retrieve_hybrid_rag_memory_hit_objects
from .text_utils import compact_whitespace, truncate_text


def retrieve_generation_memory_hits(
    core: object,
    *,
    current_context: str,
    project: str = "",
    app: str = "",
    context_group_id: str = "",
    top_k: int = 6,
) -> tuple[MemoryHit, ...]:
    """Read current governed Atom/Book evidence for generation.

    The IME projector deliberately drops Atom/Book bodies that are unsafe to
    insert verbatim. Generation needs the opposite contract: bounded evidence
    with provenance, never a ready-to-commit candidate. Legacy ``item``
    projections are deliberately rejected because they have no governed fact
    lifecycle and can contradict current Atoms or Books.
    """

    connect = getattr(core, "_connect", None)
    if not callable(connect):
        return ()
    context = compact_whitespace(current_context)
    if not context:
        return ()
    requested_top_k = max(1, min(12, int(top_k)))
    query = HybridRagQuery(
        query_text=context[-720:],
        committed_tail=context[-720:],
        project=compact_whitespace(project),
        app=compact_whitespace(app),
        input_mode="generation_context",
        # Over-fetch before applying the generation-specific type budget. The
        # global hybrid rank can otherwise fill a small top-k with raw history
        # before a current Atom or Book reaches this consumer.
        top_k=min(48, max(12, requested_top_k * 4)),
        latency_budget_ms=180,
        context_group_id=compact_whitespace(context_group_id),
        context_group_level="document" if context_group_id.startswith("doc:") else "app",
    )
    try:
        with connect() as conn:
            conn.execute("PRAGMA query_only = ON")
            hits = retrieve_hybrid_rag_memory_hit_objects(
                conn,
                query,
                getattr(core, "embedding_provider", None),
            )
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        return ()
    eligible = [
        hit
        for hit in hits
        if hit.doc_type in {"atom", "book"}
        and compact_whitespace(hit.text)
    ]
    return _diversify_generation_hits(eligible, top_k=requested_top_k)


def _diversify_generation_hits(
    hits: list[MemoryHit],
    *,
    top_k: int,
) -> tuple[MemoryHit, ...]:
    limit = max(1, min(12, int(top_k)))
    type_caps = {"atom": 3, "book": 2}
    selected_indexes: set[int] = set()
    counts = {doc_type: 0 for doc_type in type_caps}

    # Current facts and Books are the primary generation contract. Keep one of
    # each when retrieval found them, then fill the remaining governed budget.
    for doc_type in ("atom", "book"):
        if len(selected_indexes) >= limit:
            break
        for index, hit in enumerate(hits):
            if hit.doc_type == doc_type:
                selected_indexes.add(index)
                counts[doc_type] += 1
                break

    for index, hit in enumerate(hits):
        if len(selected_indexes) >= limit:
            break
        if index in selected_indexes:
            continue
        cap = type_caps.get(hit.doc_type, 0)
        if counts.get(hit.doc_type, 0) >= cap:
            continue
        selected_indexes.add(index)
        counts[hit.doc_type] = counts.get(hit.doc_type, 0) + 1

    return tuple(hits[index] for index in sorted(selected_indexes))


def generation_memory_evidence_pack(
    hits: tuple[MemoryHit, ...] | list[MemoryHit],
    *,
    max_items: int = 6,
    max_text_chars: int = 360,
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for hit in hits[: max(0, int(max_items))]:
        text = truncate_text(compact_whitespace(hit.text), max(80, int(max_text_chars)))
        if not text:
            continue
        metadata = dict(hit.metadata or {})
        timeline_id = compact_whitespace(str(metadata.get("timelineId") or ""))
        is_timeline = (
            hit.doc_type == "book"
            and str(metadata.get("derivedArtifactType") or "")
            == "daily_activity_timeline"
            and bool(timeline_id)
        )
        source = {
            "type": f"memory_{hit.doc_type}",
            "id": hit.source_id or hit.hit_id,
        }
        ref = (
            {
                "type": "timeline",
                "id": timeline_id,
                "bookId": hit.source_id,
            }
            if is_timeline
            else dict(source)
        )
        result.append(
            {
                "evidenceId": hit.hit_id,
                "sourceType": f"memory_{hit.doc_type}",
                "sourceLane": hit.source_lane,
                "text": text,
                # DeepSeek's evidence boundary deliberately exposes only the
                # bounded preview field, so put the current fact body here.
                "evidencePreview": truncate_text(text, 220),
                "surfaceHints": list(hit.surface_hints[:8]),
                "tags": list(hit.tags[:8]),
                "memoryIds": list(hit.memory_ids[:8]),
                "atomIds": list(hit.atom_ids[:8]),
                "bookIds": list(hit.book_ids[:8]),
                "sourceEventIds": list(hit.evidence_event_ids[:12]),
                "source": source,
                "ref": ref,
                "score": round(float(hit.score), 6),
                "confidence": round(float(hit.confidence), 6),
                "maySupportFacts": not is_timeline,
                "corroborationOnly": is_timeline,
                "instructional": False,
            }
        )
    return tuple(result)
