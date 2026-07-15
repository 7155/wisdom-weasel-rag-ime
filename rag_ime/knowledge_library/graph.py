from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .models import KnowledgeConflictError, KnowledgeLibraryError, KnowledgeNotFoundError
from .store import KnowledgeStore, now_ms


GRAPH_SCHEMA_VERSION = "rag-ime.knowledge-graph.v1"
GRAPH_NODE_KINDS = frozenset({"document", "chunk", "topic", "entity", "term"})
_TOKEN_RE = re.compile(r"`([^`\n]{2,80})`|\b([A-Z][A-Za-z0-9_.+-]{1,63})\b")
_ENTITY_RE = re.compile(
    r"\[([^\]\n]{2,80})\]\([^\)\n]+\)|[\"'“‘]([^\"'”’\n]{2,80})[\"'”’]|\b([A-Z]{2,16}(?:[-_][A-Za-z0-9]+)*)\b"
)
_STOP_TERMS = frozenset(
    {
        "this", "that", "with", "from", "into", "using", "used", "the", "and", "for",
        "一个", "一种", "这个", "那个", "可以", "以及", "进行", "通过", "使用", "需要", "如果", "其中",
        "我们", "你们", "他们", "这些", "那些", "相关", "主要", "包括", "用于", "因为", "所以",
    }
)


@dataclass(frozen=True)
class _Node:
    id: str
    kind: str
    label: str
    document_id: str | None
    document_name: str
    chunk_id: str | None
    heading: str
    excerpt: str
    page: int | None
    weight: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _Edge:
    id: str
    source: str
    target: str
    kind: str
    label: str
    weight: float
    document_id: str | None
    chunk_id: str | None


class KnowledgeGraph:
    """Deterministic document graph stored only in the isolated knowledge database."""

    def __init__(self, store: KnowledgeStore):
        self.store = store

    def read(
        self,
        base_id: str,
        *,
        document_id: str = "",
        query: str = "",
        kinds: Sequence[str] = (),
        limit: int = 200,
        depth: int = 2,
        exclude_chunks: bool = False,
        focus_id: str = "",
    ) -> dict[str, Any]:
        self.store.get_base(base_id)
        selected_kinds = tuple(dict.fromkeys(item for item in kinds if item in GRAPH_NODE_KINDS))
        node_limit = max(10, min(1_000, int(limit)))
        traversal_depth = max(1, min(5, int(depth)))
        current_fingerprint = self._source_fingerprint(base_id, self._state_document_ids(base_id))
        with self.store.connection() as connection:
            state = connection.execute(
                "SELECT * FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
            status = self._effective_status(
                state,
                current_fingerprint,
                self._has_stale_source(connection, base_id),
            )
            scope_filters = ["base_id=?"]
            scope_params: list[Any] = [base_id]
            if document_id:
                scope_filters.append(
                    "(document_id=? OR id IN ("
                    "SELECT source_id FROM knowledge_graph_edges WHERE base_id=? AND document_id=? "
                    "UNION SELECT target_id FROM knowledge_graph_edges WHERE base_id=? AND document_id=?))"
                )
                scope_params.extend([document_id, base_id, document_id, base_id, document_id])
            seed_filters = list(scope_filters)
            seed_params = list(scope_params)
            if focus_id:
                seed_filters.append("id=?")
                seed_params.append(focus_id)
            elif selected_kinds:
                seed_filters.append(f"kind IN ({', '.join('?' for _ in selected_kinds)})")
                seed_params.extend(selected_kinds)
            if query.strip():
                seed_filters.append("(label LIKE ? ESCAPE '\\' OR heading LIKE ? ESCAPE '\\' OR excerpt LIKE ? ESCAPE '\\')")
                pattern = f"%{_escape_like(query.strip()[:200])}%"
                seed_params.extend([pattern, pattern, pattern])
            if not focus_id and not query.strip() and not selected_kinds:
                seed_filters.append("kind='document'")
            seed_rows = connection.execute(
                f"SELECT * FROM knowledge_graph_nodes WHERE {' AND '.join(seed_filters)} "
                "ORDER BY CASE kind WHEN 'document' THEN 0 WHEN 'topic' THEN 1 WHEN 'chunk' THEN 2 "
                "WHEN 'entity' THEN 3 ELSE 4 END, weight DESC, label COLLATE NOCASE, id LIMIT ?",
                [*seed_params, node_limit],
            ).fetchall()
            if focus_id and not seed_rows:
                raise KnowledgeNotFoundError(f"knowledge graph node {focus_id!r} was not found")
            seed_ids = {str(row["id"]) for row in seed_rows}
            visited: dict[str, sqlite3.Row] = {str(row["id"]): row for row in seed_rows}
            frontier = list(visited)
            candidate_edges: dict[str, sqlite3.Row] = {}
            traversal_limit = node_limit * 3
            for _ in range(traversal_depth):
                if not frontier or len(visited) >= traversal_limit:
                    break
                placeholders = ", ".join("?" for _ in frontier)
                if exclude_chunks:
                    incident = connection.execute(
                        f"SELECT edge.* FROM knowledge_graph_edges edge "
                        "JOIN knowledge_graph_nodes source ON source.id=edge.source_id "
                        "JOIN knowledge_graph_nodes target ON target.id=edge.target_id "
                        f"WHERE edge.base_id=? AND (edge.source_id IN ({placeholders}) "
                        f"OR edge.target_id IN ({placeholders})) "
                        "AND source.kind!='chunk' AND target.kind!='chunk' "
                        "ORDER BY edge.weight DESC, edge.kind, edge.id LIMIT ?",
                        [base_id, *frontier, *frontier, traversal_limit * 6],
                    ).fetchall()
                else:
                    incident = connection.execute(
                        f"SELECT * FROM knowledge_graph_edges WHERE base_id=? AND "
                        f"(source_id IN ({placeholders}) OR target_id IN ({placeholders})) "
                        "ORDER BY weight DESC, kind, id LIMIT ?",
                        [base_id, *frontier, *frontier, traversal_limit * 6],
                    ).fetchall()
                neighbor_ids: list[str] = []
                for edge in incident:
                    candidate_edges[str(edge["id"])] = edge
                    for node_id in (str(edge["source_id"]), str(edge["target_id"])):
                        if node_id not in visited:
                            neighbor_ids.append(node_id)
                neighbor_ids = list(dict.fromkeys(neighbor_ids))
                if not neighbor_ids:
                    break
                neighbor_placeholders = ", ".join("?" for _ in neighbor_ids)
                neighbor_filters = list(scope_filters)
                if exclude_chunks:
                    # Hidden evidence nodes must not consume the traversal budget.
                    # Document and topic mention edges keep the visible graph connected.
                    neighbor_filters.append("kind!='chunk'")
                neighbor_rows = connection.execute(
                    f"SELECT * FROM knowledge_graph_nodes WHERE {' AND '.join(neighbor_filters)} "
                    f"AND id IN ({neighbor_placeholders}) ORDER BY weight DESC, kind, label COLLATE NOCASE, id LIMIT ?",
                    [*scope_params, *neighbor_ids, max(0, traversal_limit - len(visited))],
                ).fetchall()
                frontier = []
                for row in neighbor_rows:
                    node_id = str(row["id"])
                    if node_id not in visited:
                        visited[node_id] = row
                        frontier.append(node_id)
            output_rows = [
                row for row in visited.values()
                if (not selected_kinds or str(row["kind"]) in selected_kinds)
                and (not exclude_chunks or str(row["kind"]) != "chunk")
            ]
            output_rows.sort(
                key=lambda row: (
                    0 if str(row["id"]) in seed_ids else 1,
                    _kind_order(str(row["kind"])),
                    -float(row["weight"]),
                    str(row["label"]).casefold(),
                    str(row["id"]),
                )
            )
            total_nodes = len(output_rows)
            node_rows = output_rows[:node_limit]
            node_ids = {str(row["id"]) for row in node_rows}
            edge_rows = [
                row for row in candidate_edges.values()
                if str(row["source_id"]) in node_ids and str(row["target_id"]) in node_ids
            ]
            edge_rows.sort(key=lambda row: (-float(row["weight"]), str(row["kind"]), str(row["id"])))
            total_edges = len(edge_rows)
            edge_rows = edge_rows[: node_limit * 3]
            stats = self._stats(connection, base_id)
            evidence: dict[str, list[str]] = {}
            if node_ids:
                placeholders = ", ".join("?" for _ in node_ids)
                evidence_rows = connection.execute(
                    f"SELECT source_id, target_id, document_id FROM knowledge_graph_edges "
                    f"WHERE base_id=? AND kind='mentions' AND document_id IS NOT NULL AND "
                    f"(source_id IN ({placeholders}) OR target_id IN ({placeholders})) "
                    "ORDER BY document_id",
                    [base_id, *node_ids, *node_ids],
                ).fetchall()
                for evidence_row in evidence_rows:
                    for node_id in (str(evidence_row["source_id"]), str(evidence_row["target_id"])):
                        if node_id in node_ids:
                            evidence.setdefault(node_id, [])
                            value = str(evidence_row["document_id"])
                            if value not in evidence[node_id]:
                                evidence[node_id].append(value)
        updated_at = int(state["updated_at_ms"]) if state is not None else 0
        revision = int(state["revision"]) if state is not None else 0
        result = {
            "schemaVersion": GRAPH_SCHEMA_VERSION,
            "kbId": base_id,
            "revision": revision,
            "sourceRevision": current_fingerprint,
            "status": status,
            "updatedAtMs": updated_at,
            "nodes": [_node_payload(row, evidence.get(str(row["id"]), [])) for row in node_rows],
            "edges": [_edge_payload(row) for row in edge_rows],
            "stats": stats,
            "truncated": total_nodes > len(node_rows) or total_edges > len(edge_rows),
        }
        if state is not None and state["job_id"]:
            result["jobId"] = str(state["job_id"])
        if state is not None and state["error_message"]:
            result["error"] = str(state["error_message"])
        return result

    def rebuild(
        self,
        base_id: str,
        *,
        expected_revision: int | None,
        document_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        self.store.get_base(base_id)
        requested_ids = tuple(dict.fromkeys(str(item).strip() for item in document_ids if str(item).strip()))
        with self.store.connection() as connection:
            state = connection.execute(
                "SELECT revision FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
            revision = int(state["revision"]) if state is not None else 0
            if expected_revision is not None and int(expected_revision) != revision:
                raise KnowledgeConflictError(
                    f"knowledge graph revision mismatch: expected {expected_revision}, current {revision}"
                )
            all_document_rows = self._ready_documents(connection, base_id, ())
            requested_rows = self._ready_documents(connection, base_id, requested_ids) if requested_ids else all_document_rows
            if requested_ids and len(requested_rows) != len(requested_ids):
                found = {str(row["id"]) for row in requested_rows}
                missing = sorted(set(requested_ids) - found)
                raise KnowledgeNotFoundError(f"ready knowledge documents were not found: {', '.join(missing)}")
            all_document_ids = tuple(str(row["id"]) for row in all_document_rows)
            has_stale_source = self._has_stale_source(connection, base_id)
            partial = bool(requested_ids) and revision > 0
            selected_ids = (
                tuple(str(row["id"]) for row in requested_rows)
                if partial
                else all_document_ids
            )
            fingerprint = self._source_fingerprint_from_connection(connection, base_id, ())
            job_id = f"kg-{uuid.uuid4().hex}"
            timestamp = now_ms()
            connection.execute(
                "INSERT INTO knowledge_graph_state(base_id, revision, status, source_fingerprint, document_ids_json, "
                "job_id, error_message, updated_at_ms) VALUES (?, ?, 'building', ?, ?, ?, '', ?) "
                "ON CONFLICT(base_id) DO UPDATE SET status='building', job_id=excluded.job_id, "
                "error_message='', updated_at_ms=excluded.updated_at_ms",
                (base_id, revision, fingerprint, "[]", job_id, timestamp),
            )
            connection.execute(
                "INSERT INTO knowledge_graph_jobs(id, base_id, revision, status, stage, document_ids_json, "
                "created_at_ms, updated_at_ms) VALUES (?, ?, ?, 'running', 'building', ?, ?, ?)",
                (job_id, base_id, revision + 1, json.dumps(list(selected_ids)), timestamp, timestamp),
            )
        try:
            nodes, edges = self._build(base_id, selected_ids)
            self._replace(
                base_id,
                nodes,
                edges,
                fingerprint,
                job_id,
                revision + 1,
                selected_ids=selected_ids,
                partial=partial,
            )
        except Exception as exc:
            with self.store.connection() as connection:
                connection.execute(
                    "UPDATE knowledge_graph_state SET status='failed', error_message=?, updated_at_ms=? WHERE base_id=?",
                    (str(exc)[:2_000], now_ms(), base_id),
                )
                connection.execute(
                    "UPDATE knowledge_graph_jobs SET status='failed', stage='failed', error_message=?, "
                    "finished_at_ms=?, updated_at_ms=? WHERE id=?",
                    (str(exc)[:2_000], now_ms(), now_ms(), job_id),
                )
            raise
        return {
            "ok": True,
            "jobId": job_id,
            "status": "stale" if has_stale_source else "ready",
            "revision": revision + 1,
        }

    def _build(self, base_id: str, document_ids: Sequence[str]) -> tuple[list[_Node], list[_Edge]]:
        nodes: dict[str, _Node] = {}
        edges: dict[str, _Edge] = {}
        if not document_ids:
            return [], []
        placeholders = ", ".join("?" for _ in document_ids)
        with self.store.connection() as connection:
            documents = connection.execute(
                f"SELECT id, display_name, revision, output_hash FROM knowledge_documents "
                f"WHERE base_id=? AND id IN ({placeholders}) AND status IN ('ready', 'stale') "
                "AND EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.document_id=knowledge_documents.id) "
                "ORDER BY display_name, id",
                [base_id, *document_ids],
            ).fetchall()
            chunks = connection.execute(
                f"SELECT * FROM knowledge_chunks WHERE base_id=? AND document_id IN ({placeholders}) "
                "ORDER BY document_id, ordinal",
                [base_id, *document_ids],
            ).fetchall()
        document_names = {str(row["id"]): str(row["display_name"]) for row in documents}
        previous_chunk: dict[str, str] = {}
        for document in documents:
            document_id = str(document["id"])
            node_id = _stable_id("document", document_id)
            nodes[node_id] = _Node(
                node_id, "document", str(document["display_name"]), document_id,
                str(document["display_name"]), None, "", "", None, 1.0,
                {"revision": int(document["revision"]), "outputHash": str(document["output_hash"] or "")},
            )
        for chunk in chunks:
            document_id = str(chunk["document_id"])
            document_name = document_names[document_id]
            chunk_id = str(chunk["id"])
            heading = str(chunk["heading"] or "").strip()[:500]
            content = str(chunk["content"] or "")
            excerpt = " ".join(content.split())[:240]
            page = int(chunk["page"]) if chunk["page"] is not None else None
            chunk_node_id = _stable_id("chunk", chunk_id)
            nodes[chunk_node_id] = _Node(
                chunk_node_id, "chunk", heading or f"Chunk {int(chunk['ordinal']) + 1}", document_id,
                document_name, chunk_id, heading, excerpt, page, 1.0,
                {"ordinal": int(chunk["ordinal"]), "contentHash": str(chunk["content_hash"])},
            )
            _add_edge(edges, _stable_id("document", document_id), chunk_node_id, "contains", "contains", 1.0, document_id, chunk_id)
            if document_id in previous_chunk:
                _add_edge(
                    edges,
                    previous_chunk[document_id],
                    chunk_node_id,
                    "next",
                    "next chunk",
                    1.0,
                    document_id,
                    chunk_id,
                )
            previous_chunk[document_id] = chunk_node_id
            topic_node_id = ""
            if heading:
                topic_id = _stable_id("topic", document_id, _normalize_label(heading))
                topic_node_id = topic_id
                nodes.setdefault(
                    topic_id,
                    _Node(topic_id, "topic", heading[:160], document_id, document_name, chunk_id, heading,
                          excerpt, page, 1.0, {"extractor": "heading-v1"}),
                )
                _add_edge(edges, _stable_id("document", document_id), topic_id, "contains", "contains topic", 1.0, document_id, chunk_id)
                _add_edge(edges, topic_id, chunk_node_id, "covers", "covers", 1.0, document_id, chunk_id)
            mentions = self._mentions(content)
            mention_ids: list[str] = []
            for kind, label, count in mentions:
                mention_id = _stable_id(kind, base_id, _normalize_label(label))
                mention_ids.append(mention_id)
                weight = min(1.0, 0.45 + 0.1 * count)
                nodes.setdefault(
                    mention_id,
                    _Node(mention_id, kind, label[:160], None, "", None, heading,
                          excerpt, page, weight, {"extractor": "deterministic-v1"}),
                )
                _add_edge(edges, chunk_node_id, mention_id, "mentions", "mentions", weight, document_id, chunk_id)
                _add_edge(
                    edges,
                    _stable_id("document", document_id),
                    mention_id,
                    "mentions",
                    "mentions",
                    weight,
                    document_id,
                    chunk_id,
                )
                if topic_node_id:
                    _add_edge(
                        edges,
                        topic_node_id,
                        mention_id,
                        "mentions",
                        "mentions",
                        weight,
                        document_id,
                        chunk_id,
                    )
            for index, source_id in enumerate(mention_ids[:8]):
                for target_id in mention_ids[index + 1 : 8]:
                    _add_edge(edges, source_id, target_id, "co_occurs", "co-occurs", 0.5, document_id, chunk_id)
        return list(nodes.values()), list(edges.values())

    @staticmethod
    def _mentions(content: str) -> list[tuple[str, str, int]]:
        entities: Counter[str] = Counter()
        terms: Counter[str] = Counter()
        for match in _ENTITY_RE.finditer(content[:100_000]):
            label = next((value for value in match.groups() if value), "").strip()
            if _valid_label(label):
                entities[label] += 1
        for match in _TOKEN_RE.finditer(content[:100_000]):
            label = next((value for value in match.groups() if value), "").strip()
            if not _valid_label(label) or _normalize_label(label) in _STOP_TERMS:
                continue
            if re.fullmatch(r"[A-Z]{2,16}(?:[-_][A-Za-z0-9]+)*", label):
                entities[label] += 1
            else:
                terms[label] += 1
        entity_items = [("entity", label, count) for label, count in entities.most_common(6)]
        entity_keys = {_normalize_label(label) for _, label, _ in entity_items}
        term_items = [
            ("term", label, count)
            for label, count in terms.most_common(10)
            if _normalize_label(label) not in entity_keys
        ][:6]
        return entity_items + term_items

    def _replace(
        self,
        base_id: str,
        nodes: Sequence[_Node],
        edges: Sequence[_Edge],
        fingerprint: str,
        job_id: str,
        revision: int,
        *,
        selected_ids: Sequence[str],
        partial: bool,
    ) -> None:
        timestamp = now_ms()
        with self.store.connection() as connection:
            if partial and selected_ids:
                placeholders = ", ".join("?" for _ in selected_ids)
                connection.execute(
                    f"DELETE FROM knowledge_graph_edges WHERE base_id=? AND document_id IN ({placeholders})",
                    [base_id, *selected_ids],
                )
                connection.execute(
                    f"DELETE FROM knowledge_graph_nodes WHERE base_id=? AND document_id IN ({placeholders})",
                    [base_id, *selected_ids],
                )
                connection.execute(
                    "DELETE FROM knowledge_graph_nodes WHERE base_id=? AND kind IN ('entity', 'term') "
                    "AND NOT EXISTS (SELECT 1 FROM knowledge_graph_edges e "
                    "WHERE e.base_id=knowledge_graph_nodes.base_id AND e.kind='mentions' "
                    "AND (e.source_id=knowledge_graph_nodes.id OR e.target_id=knowledge_graph_nodes.id))",
                    (base_id,),
                )
            else:
                connection.execute("DELETE FROM knowledge_graph_edges WHERE base_id=?", (base_id,))
                connection.execute("DELETE FROM knowledge_graph_nodes WHERE base_id=?", (base_id,))
            connection.executemany(
                "INSERT INTO knowledge_graph_nodes(id, base_id, kind, label, document_id, document_name, chunk_id, "
                "heading, excerpt, page, weight, metadata_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET label=excluded.label, weight=MAX(knowledge_graph_nodes.weight, excluded.weight), "
                "metadata_json=excluded.metadata_json",
                [
                    (node.id, base_id, node.kind, node.label, node.document_id, node.document_name, node.chunk_id,
                     node.heading, node.excerpt, node.page, node.weight,
                     json.dumps(node.metadata, ensure_ascii=False, sort_keys=True), timestamp)
                    for node in nodes
                ],
            )
            connection.executemany(
                "INSERT INTO knowledge_graph_edges(id, base_id, source_id, target_id, kind, label, weight, "
                "document_id, chunk_id, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (edge.id, base_id, edge.source, edge.target, edge.kind, edge.label, edge.weight,
                     edge.document_id, edge.chunk_id, timestamp)
                    for edge in edges
                ],
            )
            connection.execute(
                "UPDATE knowledge_graph_state SET revision=?, status='ready', source_fingerprint=?, "
                "document_ids_json=?, job_id=?, error_message='', updated_at_ms=? WHERE base_id=?",
                (revision, fingerprint, "[]", job_id, timestamp, base_id),
            )
            connection.execute(
                "UPDATE knowledge_graph_jobs SET status='succeeded', stage='completed', finished_at_ms=?, "
                "updated_at_ms=? WHERE id=?",
                (timestamp, timestamp, job_id),
            )

    def _state_document_ids(self, base_id: str) -> tuple[str, ...]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT document_ids_json FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
        if row is None:
            return ()
        try:
            value = json.loads(str(row["document_ids_json"] or "[]"))
        except json.JSONDecodeError:
            return ()
        return tuple(str(item) for item in value if str(item)) if isinstance(value, list) else ()

    def _source_fingerprint(self, base_id: str, document_ids: Sequence[str]) -> str:
        with self.store.connection() as connection:
            return self._source_fingerprint_from_connection(connection, base_id, document_ids)

    @staticmethod
    def _source_fingerprint_from_connection(
        connection: sqlite3.Connection, base_id: str, document_ids: Sequence[str]
    ) -> str:
        filters = ["d.base_id=?", "d.status IN ('ready', 'stale')"]
        params: list[Any] = [base_id]
        if document_ids:
            filters.append(f"d.id IN ({', '.join('?' for _ in document_ids)})")
            params.extend(document_ids)
        rows = connection.execute(
            "SELECT d.id, d.revision, d.status, d.output_hash, d.indexed_config_revision, COUNT(c.id) AS chunk_count, "
            "COALESCE(GROUP_CONCAT(c.content_hash, ','), '') AS chunk_hashes "
            "FROM knowledge_documents d LEFT JOIN knowledge_chunks c ON c.document_id=d.id "
            f"WHERE {' AND '.join(filters)} GROUP BY d.id HAVING COUNT(c.id) > 0 ORDER BY d.id",
            params,
        ).fetchall()
        payload = [
            [str(row["id"]), int(row["revision"]), str(row["status"]), str(row["output_hash"] or ""),
             int(row["indexed_config_revision"]), int(row["chunk_count"]), str(row["chunk_hashes"])]
            for row in rows
        ]
        return "sha256:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _ready_documents(
        connection: sqlite3.Connection, base_id: str, document_ids: Sequence[str]
    ) -> list[sqlite3.Row]:
        params: list[Any] = [base_id]
        condition = ""
        if document_ids:
            condition = f" AND id IN ({', '.join('?' for _ in document_ids)})"
            params.extend(document_ids)
        return connection.execute(
            f"SELECT id, display_name FROM knowledge_documents WHERE base_id=? AND status IN ('ready', 'stale') "
            f"AND EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.document_id=knowledge_documents.id){condition} "
            "ORDER BY display_name, id",
            params,
        ).fetchall()

    @staticmethod
    def _effective_status(state: sqlite3.Row | None, fingerprint: str, has_stale_source: bool) -> str:
        if state is None:
            return "stale"
        status = str(state["status"] or "stale")
        if status in {"building", "failed"}:
            return status
        return (
            "ready"
            if str(state["source_fingerprint"] or "") == fingerprint and not has_stale_source
            else "stale"
        )

    @staticmethod
    def _has_stale_source(connection: sqlite3.Connection, base_id: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM knowledge_documents d WHERE d.base_id=? AND d.status='stale' "
            "AND EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.document_id=d.id) LIMIT 1",
            (base_id,),
        ).fetchone() is not None

    @staticmethod
    def _stats(connection: sqlite3.Connection, base_id: str) -> dict[str, int]:
        node_count = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_graph_nodes WHERE base_id=?", (base_id,)
        ).fetchone()[0])
        edge_count = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_graph_edges WHERE base_id=?", (base_id,)
        ).fetchone()[0])
        document_count = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_graph_nodes WHERE base_id=? AND kind='document'", (base_id,)
        ).fetchone()[0])
        chunk_count = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_graph_nodes WHERE base_id=? AND kind='chunk'", (base_id,)
        ).fetchone()[0])
        pending_document_count = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents d WHERE d.base_id=? "
            "AND d.status IN ('ready', 'stale') "
            "AND EXISTS (SELECT 1 FROM knowledge_chunks c WHERE c.document_id=d.id) "
            "AND (d.status='stale' OR NOT EXISTS (SELECT 1 FROM knowledge_graph_nodes n "
            "WHERE n.base_id=d.base_id AND n.document_id=d.id AND n.kind='document'))",
            (base_id,),
        ).fetchone()[0])
        return {
            "nodeCount": node_count,
            "edgeCount": edge_count,
            "documentCount": document_count,
            "chunkCount": chunk_count,
            "indexedDocumentCount": document_count,
            "pendingDocumentCount": pending_document_count,
        }


def _node_payload(row: sqlite3.Row, evidence_document_ids: Sequence[str] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(row["id"]),
        "label": str(row["label"]),
        "kind": str(row["kind"]),
        "weight": float(row["weight"]),
    }
    optional = {
        "documentId": row["document_id"],
        "documentName": row["document_name"],
        "chunkId": row["chunk_id"],
        "heading": row["heading"],
        "excerpt": row["excerpt"],
        "page": int(row["page"]) if row["page"] is not None else None,
    }
    result.update({key: value for key, value in optional.items() if value not in (None, "")})
    if evidence_document_ids:
        result["documentIds"] = list(evidence_document_ids)
    return result


def _edge_payload(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(row["id"]),
        "source": str(row["source_id"]),
        "target": str(row["target_id"]),
        "kind": str(row["kind"]),
        "weight": float(row["weight"]),
    }
    if row["label"]:
        result["label"] = str(row["label"])
    return result


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join((kind, *parts)).encode("utf-8")).hexdigest()[:24]
    return f"kg:{kind}:{digest}"


def _add_edge(
    edges: dict[str, _Edge], source: str, target: str, kind: str, label: str, weight: float,
    document_id: str | None, chunk_id: str | None,
) -> None:
    edge_id = _stable_id("edge", source, target, kind, chunk_id or "")
    edges[edge_id] = _Edge(edge_id, source, target, kind, label, weight, document_id, chunk_id)


def _normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())[:160]


def _valid_label(value: str) -> bool:
    normalized = _normalize_label(value)
    return 2 <= len(normalized) <= 80 and normalized not in _STOP_TERMS and not normalized.isdigit()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _kind_order(kind: str) -> int:
    return {"document": 0, "topic": 1, "chunk": 2, "entity": 3, "term": 4}.get(kind, 5)
