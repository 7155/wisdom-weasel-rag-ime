from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path

from .embeddings import EmbeddingProvider
from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates


class AgentMemoryQueryService:
    """Agent-only iterative memory access over the canonical retrieval path.

    The first step deliberately reuses the IME project's existing hybrid
    retriever. Graph traversal starts only from the canonical sources returned
    by that retriever, so it does not create a second BM25/vector search stack.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        project: str,
        embedding_provider: EmbeddingProvider | None = None,
        graph_store: object | None = None,
    ) -> None:
        normalized_project = " ".join(str(project).split())[:160]
        if not normalized_project:
            raise ValueError("agent memory project must not be empty")
        self.db_path = Path(db_path)
        self.project = normalized_project
        self.embedding_provider = embedding_provider
        if graph_store is None:
            from .memory_graph import MemoryGraphStore

            graph_store = MemoryGraphStore(self.db_path)
        self.graph_store = graph_store
        initialize = getattr(self.graph_store, "initialize", None)
        if callable(initialize):
            initialize()

    def search(
        self,
        session_id: str,
        *,
        query_text: str,
        project: str = "",
        app: str = "",
        limit: int = 8,
    ) -> dict[str, object]:
        principal = self._principal(session_id, requested_project=project)
        query = " ".join(str(query_text).split())[:500]
        if not query:
            raise ValueError("query is required for ime_memory.search")
        bounded_limit = _bounded_int(limit, default=8, minimum=1, maximum=20)
        with closing(self._connect()) as conn:
            retrieval = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text=query,
                    project=self.project,
                    app=" ".join(str(app).split())[:160],
                    top_k=bounded_limit,
                    # Agent retrieval is not the foreground completion hot path.
                    latency_budget_ms=500,
                    reader_session_id=str(getattr(principal, "session_id", "")),
                    reader_agent_id=str(getattr(principal, "agent_id", "")),
                    reader_room_ids=tuple(str(item) for item in getattr(principal, "room_ids", ())),
                ),
                self.embedding_provider,
            )
            raw_hits = retrieval.get("hits") if isinstance(retrieval, Mapping) else []
            visible_hits = _visible_hits(conn, raw_hits, principal=principal)
        raw_lanes = retrieval.get("lanes") if isinstance(retrieval, Mapping) else {}
        lanes = _visible_lane_diagnostics(raw_lanes, visible_hits)
        evidence = _deduplicate_hits(visible_hits, lanes=lanes, limit=bounded_limit)
        source_refs = _source_refs_from_evidence(evidence)
        anchors = _graph_items(
            self.graph_store.find_anchors(  # type: ignore[attr-defined]
                principal,
                source_refs=source_refs,
                query_text=query,
                limit=bounded_limit,
            ),
            preferred_key="anchors",
        )
        return {
            "schemaVersion": "rag-ime.agent-memory-search.v1",
            "summary": f"召回 {len(evidence)} 条去重证据和 {len(anchors)} 个图锚点",
            "query": query,
            "count": len(evidence),
            "items": evidence,
            "anchors": anchors,
            "lanes": dict(lanes) if isinstance(lanes, Mapping) else {},
            "diagnostics": {
                "rawHitCount": len(raw_hits) if isinstance(raw_hits, list) else 0,
                "aclFilteredHitCount": max(0, len(raw_hits) - len(visible_hits))
                if isinstance(raw_hits, list)
                else 0,
                "deduplicatedHitCount": len(evidence),
                "elapsedMs": _safe_int(retrieval.get("elapsedMs")) if isinstance(retrieval, Mapping) else 0,
                "overBudget": retrieval.get("overBudget") is True if isinstance(retrieval, Mapping) else False,
                "parallelExecution": retrieval.get("parallelExecution") is True
                if isinstance(retrieval, Mapping)
                else False,
                "vectorIndexDocuments": _safe_int(retrieval.get("vectorIndexDocuments"))
                if isinstance(retrieval, Mapping)
                else 0,
            },
        }

    def expand(
        self,
        session_id: str,
        *,
        anchor_ids: Sequence[str],
        project: str = "",
        max_depth: int = 2,
        limit: int = 20,
        as_of_ms: int | None = None,
    ) -> dict[str, object]:
        principal = self._principal(session_id, requested_project=project)
        anchors = _bounded_ids(anchor_ids, limit=40)
        if not anchors:
            raise ValueError("anchorIds is required for ime_memory.expand")
        result = self.graph_store.expand(  # type: ignore[attr-defined]
            principal,
            anchor_ids=anchors,
            max_depth=_bounded_int(max_depth, default=2, minimum=1, maximum=3),
            limit=_bounded_int(limit, default=20, minimum=1, maximum=50),
            as_of_ms=_optional_nonnegative_int(as_of_ms),
        )
        payload = _graph_payload(result, preferred_key="items")
        count = _payload_count(payload, ("items", "relations", "paths"))
        payload.setdefault("schemaVersion", "rag-ime.agent-memory-expand.v1")
        payload.setdefault("summary", f"图扩展返回 {count} 条关系证据")
        payload.setdefault("anchorIds", anchors)
        payload.setdefault("count", count)
        return payload

    def get_sources(
        self,
        session_id: str,
        *,
        relation_ids: Sequence[str] = (),
        source_refs: Sequence[Mapping[str, object]] = (),
        project: str = "",
        limit: int = 20,
    ) -> dict[str, object]:
        principal = self._principal(session_id, requested_project=project)
        relations = _bounded_ids(relation_ids, limit=50)
        refs = _bounded_source_refs(source_refs, limit=50)
        if not relations:
            raise ValueError("relationIds is required for ime_memory.get_sources")
        result = self.graph_store.get_sources(  # type: ignore[attr-defined]
            principal,
            relation_ids=relations,
            source_refs=refs,
            limit=_bounded_int(limit, default=20, minimum=1, maximum=50),
        )
        payload = _graph_payload(result, preferred_key="items")
        count = _payload_count(payload, ("items", "sources"))
        payload.setdefault("schemaVersion", "rag-ime.agent-memory-sources.v1")
        payload.setdefault("summary", f"回源读取 {count} 条原始证据")
        payload.setdefault("count", count)
        return payload

    def _principal(self, session_id: str, *, requested_project: str) -> object:
        requested = " ".join(str(requested_project).split())[:160]
        if requested and requested != self.project:
            raise ValueError("cross-project memory access is not allowed")
        normalized_session_id = str(session_id or "").strip()[:240]
        if not normalized_session_id:
            raise ValueError("agent memory session is missing")
        with closing(self._connect()) as conn:
            session = conn.execute(
                "SELECT agent_id, status FROM agent_sessions WHERE id = ?",
                (normalized_session_id,),
            ).fetchone()
            if session is None:
                raise ValueError("agent memory session was not found")
            if str(session["status"] or "") == "archived":
                raise ValueError("archived sessions cannot access memory")
            room_rows = conn.execute(
                """
                SELECT DISTINCT p.room_id
                FROM agent_room_participants AS p
                JOIN agent_rooms AS r ON r.id = p.room_id
                WHERE p.session_id = ?
                  AND p.participant_status = 'active'
                  AND r.status = 'active'
                ORDER BY p.room_id
                """,
                (normalized_session_id,),
            ).fetchall()
        from .memory_graph import MemoryGraphPrincipal

        return MemoryGraphPrincipal(
            project=self.project,
            session_id=normalized_session_id,
            agent_id=str(session["agent_id"] or normalized_session_id),
            room_ids=tuple(str(row["room_id"]) for row in room_rows),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _visible_hits(
    conn: sqlite3.Connection,
    value: object,
    *,
    principal: object,
) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[Mapping[str, object]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        if not _metadata_scope_visible(metadata, principal=principal):
            continue
        event_ids = _hit_event_ids(conn, raw)
        if event_ids and not all(
            _event_visible_to_principal(conn, event_id, principal=principal, metadata=metadata)
            for event_id in event_ids
        ):
            continue
        result.append(raw)
    return result


def _visible_lane_diagnostics(value: object, hits: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    by_lane: dict[str, list[str]] = {}
    for hit in hits:
        lane = str(hit.get("source_lane") or hit.get("sourceLane") or "").strip()
        doc_id = str(hit.get("doc_id") or hit.get("docId") or "").strip()
        if lane and doc_id and doc_id not in by_lane.setdefault(lane, []):
            by_lane[lane].append(doc_id)
    result: dict[str, object] = {}
    for lane, raw in value.items():
        metadata = dict(raw) if isinstance(raw, Mapping) else {}
        visible_ids = by_lane.get(str(lane), [])
        metadata["count"] = len(visible_ids)
        metadata["docIds"] = visible_ids[:5]
        result[str(lane)] = metadata
    return result


def _metadata_scope_visible(value: Mapping[str, object], *, principal: object) -> bool:
    owner_kind = str(value.get("ownerKind") or value.get("owner_kind") or "").strip()
    owner_id = str(value.get("ownerId") or value.get("owner_id") or "").strip()
    if not owner_kind or owner_kind in {"user", "shared"}:
        return True
    if owner_kind == "session":
        return owner_id == str(getattr(principal, "session_id", ""))
    if owner_kind == "agent":
        return owner_id == str(getattr(principal, "agent_id", ""))
    if owner_kind == "room":
        return owner_id in set(getattr(principal, "room_ids", ()))
    return False


def _event_visible_to_principal(
    conn: sqlite3.Connection,
    event_id: int,
    *,
    principal: object,
    metadata: Mapping[str, object],
) -> bool:
    rows = conn.execute(
        """
        SELECT ams.session_id, ams.source_role, ams.status, s.agent_id
        FROM agent_memory_sources AS ams
        JOIN agent_sessions AS s ON s.id = ams.session_id
        WHERE ams.input_event_id = ?
        """,
        (event_id,),
    ).fetchall()
    if not rows:
        event = conn.execute("SELECT source FROM input_events WHERE id = ?", (event_id,)).fetchone()
        return event is not None and str(event["source"] or "") != "pi_agent_tool_receipt"
    if any(str(row["status"]) != "active" for row in rows):
        return False
    session_id = str(getattr(principal, "session_id", ""))
    agent_id = str(getattr(principal, "agent_id", ""))
    owner_kind = str(metadata.get("ownerKind") or metadata.get("owner_kind") or "").strip()
    owner_id = str(metadata.get("ownerId") or metadata.get("owner_id") or "").strip()
    for row in rows:
        if str(row["source_role"]) == "user":
            return True
        source_session = str(row["session_id"])
        if source_session == session_id or str(row["agent_id"]) == agent_id:
            return True
        if owner_kind == "room" and owner_id in set(getattr(principal, "room_ids", ())):
            member = conn.execute(
                """
                SELECT 1
                FROM agent_room_participants AS p
                JOIN agent_rooms AS r ON r.id = p.room_id
                WHERE p.room_id = ? AND p.session_id = ?
                  AND p.participant_status = 'active' AND r.status = 'active'
                LIMIT 1
                """,
                (owner_id, source_session),
            ).fetchone()
            if member is not None:
                return True
    return False


def _hit_event_ids(conn: sqlite3.Connection, raw: Mapping[str, object]) -> list[int]:
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
    values: list[object] = []
    source_event_ids = metadata.get("sourceEventIds") or metadata.get("source_event_ids")
    if isinstance(source_event_ids, (list, tuple)):
        values.extend(source_event_ids)
    source_event_id = metadata.get("sourceEventId") or metadata.get("source_event_id")
    if source_event_id not in (None, "", 0, "0"):
        values.append(source_event_id)
    result = _positive_ids(values)
    if result:
        return result
    source_type = str(raw.get("doc_type") or raw.get("sourceType") or "").strip()
    source_id = str(raw.get("source_id") or raw.get("sourceId") or "").strip()
    if not source_id:
        return []
    if source_type == "atom":
        row = conn.execute("SELECT source_event_ids_json FROM memory_atoms WHERE id = ?", (source_id,)).fetchone()
        return _json_positive_ids(None if row is None else row["source_event_ids_json"])
    if source_type == "book":
        row = conn.execute("SELECT source_event_ids_json FROM memory_books WHERE book_id = ?", (source_id,)).fetchone()
        return _json_positive_ids(None if row is None else row["source_event_ids_json"])
    if source_type in {"item", "phrase"}:
        row = conn.execute("SELECT source_event_id FROM memory_items WHERE memory_id = ?", (source_id,)).fetchone()
        return [] if row is None else _positive_ids([row["source_event_id"]])
    return []


def _source_refs_from_evidence(value: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(source_type: object, source_id: object) -> None:
        kind = str(source_type or "").strip()[:80]
        identifier = str(source_id or "").strip()[:240]
        key = (kind, identifier)
        if not kind or not identifier or key in seen:
            return
        seen.add(key)
        result.append({"sourceType": kind, "sourceId": identifier, "sourceRevision": 1})

    for item in value:
        add(item.get("sourceType"), item.get("sourceId"))
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        source_ids: list[object] = []
        if isinstance(metadata.get("sourceEventIds"), (list, tuple)):
            source_ids.extend(metadata.get("sourceEventIds") or [])
        if metadata.get("sourceEventId") not in (None, "", 0, "0"):
            source_ids.append(metadata.get("sourceEventId"))
        for event_id in _positive_ids(source_ids):
            add("input_event", str(event_id))
    return result[:160]


def _positive_ids(values: Sequence[object]) -> list[int]:
    result: list[int] = []
    for raw in values:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
    return result


def _json_positive_ids(value: object) -> list[int]:
    import json

    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return _positive_ids(parsed if isinstance(parsed, list) else [])


def _deduplicate_hits(
    value: object,
    *,
    lanes: object,
    limit: int,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    lane_weights = _lane_weights(lanes)

    evidence_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for ordinal, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            continue
        rank = _safe_positive_int(raw.get("rank"), default=ordinal + 1)
        doc_id = str(raw.get("doc_id") or raw.get("docId") or "").strip()[:240]
        source_id = str(raw.get("source_id") or raw.get("sourceId") or "").strip()[:240]
        source_type = str(raw.get("doc_type") or raw.get("sourceType") or "").strip()[:80]
        if not doc_id and not source_id:
            continue
        key = (source_type, source_id) if source_id else ("doc", doc_id)
        lane = str(raw.get("source_lane") or raw.get("sourceLane") or "").strip()[:80]
        existing = evidence_by_key.get(key)
        if existing is not None:
            lanes = existing["sourceLanes"]
            if isinstance(lanes, list) and lane and lane not in lanes:
                lanes.append(lane)
            existing["rank"] = min(_safe_positive_int(existing.get("rank"), default=1), rank)
            ranks = existing["laneRanks"]
            if isinstance(ranks, dict) and lane:
                ranks[lane] = min(_safe_positive_int(ranks.get(lane), default=rank), rank)
            raw_scores = existing["rawScores"]
            if isinstance(raw_scores, dict) and lane:
                raw_scores[lane] = _safe_float(raw.get("raw_score") or raw.get("score"))
            continue
        tags = raw.get("tags") if isinstance(raw.get("tags"), (list, tuple)) else ()
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        evidence_by_key[key] = {
            "kind": "source",
            "docId": doc_id,
            "sourceType": source_type,
            "sourceId": source_id,
            "text": str(raw.get("text") or "")[:2000],
            "tags": [str(item)[:120] for item in tags if str(item).strip()][:30],
            "rank": rank,
            "score": 0.0,
            "sourceLanes": [lane] if lane else [],
            "laneRanks": {lane: rank} if lane else {},
            "rawScores": {lane: _safe_float(raw.get("raw_score") or raw.get("score"))}
            if lane
            else {},
            "metadata": dict(metadata),
        }
    evidence = list(evidence_by_key.values())
    for item in evidence:
        ranks = item.get("laneRanks") if isinstance(item.get("laneRanks"), Mapping) else {}
        fused_score = sum(
            lane_weights.get(str(lane), 1.0) / (60.0 + _safe_positive_int(rank, default=1))
            for lane, rank in ranks.items()
        )
        item["score"] = round(fused_score, 8)
        item.pop("laneRanks", None)
    evidence.sort(
        key=lambda item: (
            -_safe_float(item.get("score")),
            _safe_positive_int(item.get("rank"), default=1),
            str(item.get("sourceId") or item.get("docId") or ""),
        )
    )
    return evidence[:limit]


def _lane_weights(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for lane, raw in value.items():
        metadata = raw if isinstance(raw, Mapping) else {}
        weight = metadata.get("weight")
        result[str(lane)] = max(0.0, 1.0 if weight is None else _safe_float(weight))
    return result


def _graph_payload(value: object, *, preferred_key: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return {preferred_key: [dict(item) if isinstance(item, Mapping) else item for item in value]}
    return {preferred_key: []}


def _graph_items(value: object, *, preferred_key: str) -> list[object]:
    payload = _graph_payload(value, preferred_key=preferred_key)
    for key in (preferred_key, "items", "entities"):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    return []


def _payload_count(payload: Mapping[str, object], keys: Sequence[str]) -> int:
    for key in keys:
        items = payload.get(key)
        if isinstance(items, list):
            return len(items)
    return _safe_int(payload.get("count"))


def _bounded_source_refs(
    values: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in list(values)[:limit]:
        if not isinstance(raw, Mapping):
            continue
        source_type = str(raw.get("sourceType") or "").strip()[:80]
        source_id = str(raw.get("sourceId") or "").strip()[:240]
        if not source_type or not source_id or (source_type, source_id) in seen:
            continue
        seen.add((source_type, source_id))
        result.append({"sourceType": source_type, "sourceId": source_id})
    return result


def _bounded_ids(values: Sequence[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for raw in list(values)[:limit]:
        value = str(raw or "").strip()[:240]
        if value and value not in result:
            result.append(value)
    return result


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("asOfMs must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError("asOfMs must be a non-negative integer")
    return parsed


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_positive_int(value: object, *, default: int) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return max(1, default)


def _safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
