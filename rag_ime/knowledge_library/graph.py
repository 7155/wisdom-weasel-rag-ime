from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .graph_extractors import (
    DeterministicGraphExtractor,
    GraphExtraction,
    GraphExtractionInput,
    GraphExtractor,
    extraction_from_dict,
    graph_extractor_from_config,
)
from .models import KnowledgeConflictError, KnowledgeNotFoundError
from .store import KnowledgeStore, now_ms


GRAPH_SCHEMA_VERSION = "rag-ime.knowledge-graph.v1"
GRAPH_NODE_KINDS = frozenset({"document", "chunk", "topic", "entity", "term"})


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


_RELATION_RANK_MAX_HOPS = 3
_RELATION_RANK_MAX_NODES = 160
_RELATION_RANK_RESTART = 0.35
_RELATION_RANK_ITERATIONS = 6


def _expand_relation_concepts(
    connection: sqlite3.Connection,
    base_id: str,
    concepts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Bounded personalized propagation over evidence-grounded relations."""

    initial_ids = tuple(concepts)
    if not initial_ids:
        return {
            "algorithm": "bounded-personalized-rank-v1",
            "maxHops": _RELATION_RANK_MAX_HOPS,
            "expandedNodeCount": 0,
        }
    adjacency: dict[str, dict[str, float]] = {node_id: {} for node_id in initial_ids}
    hops = {node_id: 0 for node_id in initial_ids}
    frontier = list(initial_ids)
    for hop in range(1, _RELATION_RANK_MAX_HOPS + 1):
        if not frontier or len(hops) >= _RELATION_RANK_MAX_NODES:
            break
        placeholders = ", ".join("?" for _ in frontier)
        rows = connection.execute(
            "SELECT source_id, target_id, weight FROM knowledge_graph_edges "
            "WHERE base_id=? AND kind='relation' "
            f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders})) "
            "ORDER BY weight DESC, id LIMIT 3000",
            [base_id, *frontier, *frontier],
        ).fetchall()
        discovered: list[str] = []
        for row in rows:
            source_id = str(row["source_id"])
            target_id = str(row["target_id"])
            if source_id == target_id:
                continue
            for node_id in (source_id, target_id):
                if node_id not in hops:
                    if len(hops) >= _RELATION_RANK_MAX_NODES:
                        break
                    hops[node_id] = hop
                    discovered.append(node_id)
                    adjacency[node_id] = {}
            if source_id not in hops or target_id not in hops:
                continue
            weight = max(0.05, min(1.0, float(row["weight"])))
            adjacency[source_id][target_id] = max(
                adjacency[source_id].get(target_id, 0.0),
                weight,
            )
            adjacency[target_id][source_id] = max(
                adjacency[target_id].get(source_id, 0.0),
                weight,
            )
        frontier = list(dict.fromkeys(discovered))

    missing_ids = [node_id for node_id in hops if node_id not in concepts]
    if missing_ids:
        placeholders = ", ".join("?" for _ in missing_ids)
        rows = connection.execute(
            "SELECT id, label, kind, weight FROM knowledge_graph_nodes "
            f"WHERE base_id=? AND kind IN ('entity', 'term', 'topic') AND id IN ({placeholders})",
            [base_id, *missing_ids],
        ).fetchall()
        found = {str(row["id"]) for row in rows}
        for node_id in missing_ids:
            if node_id not in found:
                adjacency.pop(node_id, None)
                hops.pop(node_id, None)
        for row in rows:
            node_id = str(row["id"])
            concepts[node_id] = {
                "label": " ".join(str(row["label"] or "").split()),
                "kind": str(row["kind"]),
                "source": "relation",
                "seedRank": None,
                "weight": float(row["weight"]),
                "hop": hops[node_id],
            }
    valid_ids = set(concepts)
    adjacency = {
        source_id: {
            target_id: weight
            for target_id, weight in neighbors.items()
            if target_id in valid_ids
        }
        for source_id, neighbors in adjacency.items()
        if source_id in valid_ids
    }

    personalization: dict[str, float] = {}
    for node_id in initial_ids:
        concept = concepts[node_id]
        if concept["source"] == "query":
            source_weight = 1.0
        else:
            source_weight = 0.8 / (1.0 + 0.08 * int(concept.get("seedRank") or 1))
        personalization[node_id] = source_weight * max(
            0.05,
            min(1.0, float(concept.get("weight") or 0.0)),
        )
    total_personalization = sum(personalization.values()) or 1.0
    personalization = {
        node_id: score / total_personalization
        for node_id, score in personalization.items()
    }
    scores = {node_id: personalization.get(node_id, 0.0) for node_id in valid_ids}
    for _ in range(_RELATION_RANK_ITERATIONS):
        next_scores = {
            node_id: _RELATION_RANK_RESTART * personalization.get(node_id, 0.0)
            for node_id in valid_ids
        }
        dangling = 0.0
        for source_id, score in scores.items():
            neighbors = adjacency.get(source_id, {})
            total_weight = sum(neighbors.values())
            if total_weight <= 0:
                dangling += (1.0 - _RELATION_RANK_RESTART) * score
                continue
            for target_id, weight in neighbors.items():
                next_scores[target_id] += (
                    (1.0 - _RELATION_RANK_RESTART)
                    * score
                    * weight
                    / total_weight
                )
        if dangling:
            for node_id, weight in personalization.items():
                next_scores[node_id] += dangling * weight
        scores = next_scores
    maximum_score = max(scores.values(), default=1.0) or 1.0
    for node_id, concept in concepts.items():
        concept.setdefault("hop", hops.get(node_id, 0))
        concept["graphScore"] = max(0.0, min(1.0, scores.get(node_id, 0.0) / maximum_score))
    return {
        "algorithm": "bounded-personalized-rank-v1",
        "maxHops": _RELATION_RANK_MAX_HOPS,
        "maxNodes": _RELATION_RANK_MAX_NODES,
        "restartProbability": _RELATION_RANK_RESTART,
        "iterations": _RELATION_RANK_ITERATIONS,
        "seedNodeCount": len(initial_ids),
        "expandedNodeCount": max(0, len(concepts) - len(initial_ids)),
    }


class KnowledgeGraph:
    """Deterministic document graph stored only in the isolated knowledge database."""

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        extractor_factory: Callable[..., GraphExtractor] | None = None,
    ):
        self.store = store
        self.extractor_factory = extractor_factory or graph_extractor_from_config

    def current_revision(self, base_id: str) -> int:
        self.store.get_base(base_id)
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT revision FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
        return int(row["revision"]) if row is not None else 0

    def retrieval_candidates(
        self,
        base_id: str,
        query: str,
        *,
        seed_chunk_ids: Sequence[str] = (),
        limit: int = 40,
    ) -> dict[str, Any]:
        """Expand text/vector seeds through ready semantic graph concepts."""
        self.store.get_base(base_id)
        candidate_limit = max(1, min(100, int(limit)))
        normalized_query = " ".join(str(query or "").split()).casefold()[:500]
        unique_seed_ids = tuple(dict.fromkeys(str(item) for item in seed_chunk_ids if str(item)))[:20]
        with self.store.connection() as connection:
            state = connection.execute(
                "SELECT * FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
            fingerprint = self._source_fingerprint_from_connection(connection, base_id, ())
            status = self._effective_status(
                state,
                fingerprint,
                self._has_stale_source(connection, base_id),
            )
            if status != "ready":
                return {"status": status, "items": [], "matchedNodes": []}

            concept_rows = connection.execute(
                "SELECT id, label, kind, weight FROM knowledge_graph_nodes "
                "WHERE base_id=? AND kind IN ('entity', 'term', 'topic') "
                "ORDER BY weight DESC, label COLLATE NOCASE, id LIMIT 3000",
                (base_id,),
            ).fetchall()
            ascii_terms = {
                token.casefold()
                for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._+:-]*", normalized_query)
                if len(token) >= 2
            }
            concepts: dict[str, dict[str, Any]] = {}
            for row in concept_rows:
                label = " ".join(str(row["label"] or "").split())
                normalized_label = label.casefold()
                direct = bool(
                    normalized_label
                    and (
                        normalized_query in normalized_label
                        or (len(normalized_label) >= 2 and normalized_label in normalized_query)
                        or any(term in normalized_label for term in ascii_terms)
                    )
                )
                if direct:
                    concepts[str(row["id"])] = {
                        "label": label,
                        "kind": str(row["kind"]),
                        "source": "query",
                        "seedRank": None,
                        "weight": float(row["weight"]),
                    }
                if len(concepts) >= 40:
                    break

            if not concepts:
                return {
                    "status": status,
                    "items": [],
                    "matchedNodes": [],
                    "relationRanking": {
                        "algorithm": "bounded-personalized-rank-v1",
                        "activation": "query-concept-required-v1",
                        "activated": False,
                        "reason": "no-query-concept-match",
                        "querySeedNodeCount": 0,
                        "firstStageChunkCount": len(unique_seed_ids),
                        "firstStageSupportedSeedCount": 0,
                        "expandedNodeCount": 0,
                    },
                }
            first_stage_supported: set[str] = set()
            if unique_seed_ids:
                chunk_placeholders = ", ".join("?" for _ in unique_seed_ids)
                concept_placeholders = ", ".join("?" for _ in concepts)
                support_rows = connection.execute(
                    "SELECT source_id, target_id FROM knowledge_graph_edges WHERE base_id=? "
                    "AND kind IN ('mentions', 'covers') AND chunk_id IN ("
                    f"{chunk_placeholders}) AND (source_id IN ({concept_placeholders}) "
                    f"OR target_id IN ({concept_placeholders}))",
                    [base_id, *unique_seed_ids, *concepts, *concepts],
                ).fetchall()
                for edge in support_rows:
                    for node_id in (str(edge["source_id"]), str(edge["target_id"])):
                        if node_id in concepts:
                            first_stage_supported.add(node_id)
            relation_ranking = _expand_relation_concepts(
                connection,
                base_id,
                concepts,
            )
            relation_ranking.update(
                {
                    "activation": "query-concept-required-v1",
                    "activated": True,
                    "querySeedNodeCount": sum(
                        item.get("source") == "query" for item in concepts.values()
                    ),
                    "firstStageChunkCount": len(unique_seed_ids),
                    "firstStageSupportedSeedCount": len(first_stage_supported),
                }
            )
            concept_ids = tuple(concepts)
            placeholders = ", ".join("?" for _ in concept_ids)
            evidence_edges = connection.execute(
                "SELECT source_id, target_id, kind, label, weight, chunk_id FROM knowledge_graph_edges "
                "WHERE base_id=? AND chunk_id IS NOT NULL AND kind IN ('mentions', 'covers', 'relation') "
                f"AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))",
                [base_id, *concept_ids, *concept_ids],
            ).fetchall()

        candidates: dict[str, dict[str, Any]] = {}
        for edge in evidence_edges:
            chunk_id = str(edge["chunk_id"] or "")
            if not chunk_id:
                continue
            linked_ids = [
                node_id for node_id in (str(edge["source_id"]), str(edge["target_id"]))
                if node_id in concepts
            ]
            if not linked_ids:
                continue
            best_concept_id = max(
                linked_ids,
                key=lambda node_id: (
                    float(concepts[node_id].get("graphScore") or 0.0),
                    {"query": 2, "seed": 1}.get(str(concepts[node_id]["source"]), 0),
                    -int(concepts[node_id].get("hop") or 0),
                    float(concepts[node_id]["weight"]),
                ),
            )
            concept = concepts[best_concept_id]
            source_score = max(0.05, float(concept.get("graphScore") or 0.0))
            score = source_score * (0.7 + 0.3 * max(0.0, min(1.0, float(edge["weight"]))))
            candidate = candidates.setdefault(
                chunk_id,
                {"chunkId": chunk_id, "score": 0.0, "matchedNodes": [], "paths": []},
            )
            candidate["score"] = max(float(candidate["score"]), score)
            label = str(concept["label"])
            if label and label not in candidate["matchedNodes"] and len(candidate["matchedNodes"]) < 4:
                candidate["matchedNodes"].append(label)
            path = f"{label} → {str(edge['label'] or edge['kind'])} → 文档片段"
            if path not in candidate["paths"] and len(candidate["paths"]) < 3:
                candidate["paths"].append(path)
        ranked = sorted(candidates.values(), key=lambda item: (-float(item["score"]), str(item["chunkId"])))
        matched_nodes = [
            {
                "id": node_id,
                "label": item["label"],
                "kind": item["kind"],
                "source": item["source"],
                "hop": int(item.get("hop") or 0),
                "score": round(float(item.get("graphScore") or 0.0), 8),
            }
            for node_id, item in concepts.items()
        ][:40]
        return {
            "status": status,
            "items": ranked[:candidate_limit],
            "matchedNodes": matched_nodes,
            "relationRanking": relation_ranking,
        }

    def reserve_rebuild(
        self,
        base_id: str,
        *,
        expected_revision: int | None,
        job_id: str,
        document_ids: Sequence[str],
        extractor_mode: str,
        extractor_model: str,
    ) -> int:
        self.store.get_base(base_id)
        timestamp = now_ms()
        fingerprint = self._source_fingerprint(base_id, ())
        with self.store.connection() as connection:
            # Serialize the status check and reservation so two rebuild POSTs cannot claim one revision.
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT revision, status FROM knowledge_graph_state WHERE base_id=?", (base_id,)
            ).fetchone()
            current_revision = int(active["revision"]) if active is not None else 0
            if active is not None and str(active["status"]) == "building":
                raise KnowledgeConflictError("a knowledge graph rebuild is already running")
            if expected_revision is not None and int(expected_revision) != current_revision:
                raise KnowledgeConflictError(
                    f"knowledge graph revision mismatch: expected {expected_revision}, current {current_revision}"
                )
            connection.execute(
                "INSERT INTO knowledge_graph_state(base_id, revision, status, source_fingerprint, document_ids_json, "
                "job_id, error_message, updated_at_ms, extractor_mode, extractor_model, extraction_stats_json) "
                "VALUES (?, ?, 'building', ?, '[]', ?, '', ?, ?, ?, '{}') "
                "ON CONFLICT(base_id) DO UPDATE SET status='building', job_id=excluded.job_id, "
                "error_message='', updated_at_ms=excluded.updated_at_ms, extractor_mode=excluded.extractor_mode, "
                "extractor_model=excluded.extractor_model, extraction_stats_json='{}'",
                (base_id, current_revision, fingerprint, job_id, timestamp, extractor_mode, extractor_model),
            )
            connection.execute(
                "INSERT INTO knowledge_graph_jobs(id, base_id, revision, status, stage, document_ids_json, "
                "created_at_ms, updated_at_ms, extractor_mode, stats_json) "
                "VALUES (?, ?, ?, 'queued', 'queued', ?, ?, ?, ?, '{}')",
                (
                    job_id,
                    base_id,
                    current_revision + 1,
                    json.dumps(list(document_ids)),
                    timestamp,
                    timestamp,
                    extractor_mode,
                ),
            )
        return current_revision

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
                relation_filters = ["base_id=?", "kind='relation'"]
                relation_params: list[Any] = [base_id]
                if document_id:
                    relation_filters.append("document_id=?")
                    relation_params.append(document_id)
                has_semantic_relations = exclude_chunks and connection.execute(
                    f"SELECT 1 FROM knowledge_graph_edges WHERE {' AND '.join(relation_filters)} LIMIT 1",
                    relation_params,
                ).fetchone() is not None
                if has_semantic_relations:
                    # Start the overview from complete high-confidence relation
                    # pairs. Seeding from documents alone makes a small visible
                    # budget fill with alphabetic topics before any semantic
                    # edge reaches the client.
                    relation_limit = max(1, node_limit // 2)
                    relation_where = " AND ".join(relation_filters)
                    seed_filters.append(
                        "(id IN (SELECT source_id FROM knowledge_graph_edges "
                        f"WHERE {relation_where} ORDER BY weight DESC, id LIMIT ?) OR "
                        "id IN (SELECT target_id FROM knowledge_graph_edges "
                        f"WHERE {relation_where} ORDER BY weight DESC, id LIMIT ?))"
                    )
                    seed_params.extend([*relation_params, relation_limit, *relation_params, relation_limit])
                else:
                    seed_filters.append("kind='document'")
            seed_kind_order = (
                "CASE kind WHEN 'entity' THEN 0 WHEN 'term' THEN 1 WHEN 'topic' THEN 2 "
                "WHEN 'document' THEN 3 ELSE 4 END"
                if exclude_chunks
                else "CASE kind WHEN 'document' THEN 0 WHEN 'topic' THEN 1 WHEN 'chunk' THEN 2 "
                "WHEN 'entity' THEN 3 ELSE 4 END"
            )
            seed_rows = connection.execute(
                f"SELECT * FROM knowledge_graph_nodes WHERE {' AND '.join(seed_filters)} "
                f"ORDER BY {seed_kind_order}, weight DESC, label COLLATE NOCASE, id LIMIT ?",
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
                    _semantic_kind_order(str(row["kind"])) if exclude_chunks else _kind_order(str(row["kind"])),
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
        if state is not None:
            extractor_stats = _json_dict(state["extraction_stats_json"])
            mode = str(state["extractor_mode"] or "deterministic")
            result["extractor"] = {
                "mode": mode,
                "model": str(state["extractor_model"] or ""),
                "configured": bool(extractor_stats.get("configured", mode != "model")),
                "degraded": int(extractor_stats.get("fallbackChunkCount") or 0) > 0,
                **extractor_stats,
            }
        return result

    def rebuild(
        self,
        base_id: str,
        *,
        expected_revision: int | None,
        document_ids: Sequence[str] = (),
        extractor_mode: str = "deterministic",
        model_id: str = "",
        batch_size: int = 4,
        extraction_concurrency: int = 2,
        max_entities: int = 5,
        max_relations: int = 4,
        max_topics: int = 2,
        job_id: str = "",
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
            job_id = job_id or f"kg-{uuid.uuid4().hex}"
            timestamp = now_ms()
            connection.execute(
                "INSERT INTO knowledge_graph_state(base_id, revision, status, source_fingerprint, document_ids_json, "
                "job_id, error_message, updated_at_ms, extractor_mode, extractor_model, extraction_stats_json) "
                "VALUES (?, ?, 'building', ?, ?, ?, '', ?, ?, ?, '{}') "
                "ON CONFLICT(base_id) DO UPDATE SET status='building', job_id=excluded.job_id, "
                "error_message='', updated_at_ms=excluded.updated_at_ms, extractor_mode=excluded.extractor_mode, "
                "extractor_model=excluded.extractor_model, extraction_stats_json='{}'",
                (base_id, revision, fingerprint, "[]", job_id, timestamp, extractor_mode, model_id),
            )
            connection.execute(
                "INSERT INTO knowledge_graph_jobs(id, base_id, revision, status, stage, document_ids_json, "
                "created_at_ms, updated_at_ms, extractor_mode, stats_json) "
                "VALUES (?, ?, ?, 'running', 'extracting', ?, ?, ?, ?, '{}') "
                "ON CONFLICT(id) DO UPDATE SET status='running', stage='extracting', "
                "document_ids_json=excluded.document_ids_json, updated_at_ms=excluded.updated_at_ms, "
                "extractor_mode=excluded.extractor_mode, stats_json='{}'",
                (job_id, base_id, revision + 1, json.dumps(list(selected_ids)), timestamp, timestamp, extractor_mode),
            )
        try:
            extractor = self.extractor_factory(
                extractor_mode,
                model_id=model_id,
                extraction_concurrency=extraction_concurrency,
                max_entities=max_entities,
                max_relations=max_relations,
                max_topics=max_topics,
            )
            nodes, edges, extraction_stats = self._build(
                base_id,
                selected_ids,
                extractor=extractor,
                batch_size=max(1, min(8, int(batch_size))),
                extraction_concurrency=max(1, min(4, int(extraction_concurrency))),
            )
            self._replace(
                base_id,
                nodes,
                edges,
                fingerprint,
                job_id,
                revision + 1,
                selected_ids=selected_ids,
                partial=partial,
                extractor_mode=extractor_mode,
                extractor_model=(
                    str(extraction_stats.get("model") or model_id)[:160]
                    if extractor_mode == "model"
                    else ""
                ),
                extraction_stats=extraction_stats,
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
            "extractor": extraction_stats,
        }

    def _build(
        self,
        base_id: str,
        document_ids: Sequence[str],
        *,
        extractor: GraphExtractor,
        batch_size: int,
        extraction_concurrency: int,
    ) -> tuple[list[_Node], list[_Edge], dict[str, Any]]:
        nodes: dict[str, _Node] = {}
        edges: dict[str, _Edge] = {}
        if not document_ids:
            return [], [], {"mode": extractor.mode, "processedChunkCount": 0}
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
        extractions, extraction_stats = self._extract_chunks(
            chunks,
            extractor=extractor,
            batch_size=batch_size,
            extraction_concurrency=extraction_concurrency,
        )
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
            topic_node_ids: list[str] = []
            if heading:
                topic_id = _stable_id("topic", document_id, _normalize_label(heading))
                topic_node_ids.append(topic_id)
                nodes.setdefault(
                    topic_id,
                    _Node(topic_id, "topic", heading[:160], document_id, document_name, chunk_id, heading,
                          excerpt, page, 1.0, {"extractor": "heading-v1"}),
                )
                _add_edge(edges, _stable_id("document", document_id), topic_id, "contains", "contains topic", 1.0, document_id, chunk_id, dedupe_across_chunks=True)
                _add_edge(edges, topic_id, chunk_node_id, "covers", "covers", 1.0, document_id, chunk_id)
            extraction = extractions.get(chunk_id, GraphExtraction(chunk_id))
            for topic in extraction.topics:
                topic_id = _stable_id("topic", base_id, _normalize_label(topic))
                if topic_id not in topic_node_ids:
                    topic_node_ids.append(topic_id)
                nodes.setdefault(
                    topic_id,
                    _Node(topic_id, "topic", topic[:160], None, "", None, heading, excerpt, page, 0.9,
                          {"extractor": extractor.mode}),
                )
                _add_edge(edges, _stable_id("document", document_id), topic_id, "contains", "contains topic", 0.9, document_id, chunk_id, dedupe_across_chunks=True)
                _add_edge(edges, topic_id, chunk_node_id, "covers", "covers", 0.9, document_id, chunk_id)
            mention_ids: dict[str, str] = {}
            extracted_mentions = [
                ("entity", item.name, item.entity_type, item.evidence)
                for item in extraction.entities
            ] + [("term", term, "Term", term) for term in extraction.terms]
            for kind, label, semantic_type, evidence_text in extracted_mentions:
                mention_id = _stable_id(kind, base_id, _normalize_label(label))
                mention_ids[_normalize_label(label)] = mention_id
                weight = 0.85 if extractor.mode == "model" else 0.7
                nodes.setdefault(
                    mention_id,
                    _Node(mention_id, kind, label[:160], None, "", None, heading,
                          excerpt, page, weight, {
                              "extractor": extractor.mode,
                              "semanticType": semantic_type,
                              "evidence": evidence_text[:240],
                          }),
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
                    dedupe_across_chunks=True,
                )
                for topic_node_id in topic_node_ids:
                    _add_edge(
                        edges,
                        topic_node_id,
                        mention_id,
                        "mentions",
                        "mentions",
                        weight,
                        document_id,
                        chunk_id,
                        dedupe_across_chunks=True,
                    )
            for relation in extraction.relations:
                source_id = mention_ids.get(_normalize_label(relation.source))
                target_id = mention_ids.get(_normalize_label(relation.target))
                if not source_id or not target_id:
                    continue
                _add_edge(
                    edges,
                    source_id,
                    target_id,
                    "relation",
                    relation.relation_type[:120],
                    relation.confidence,
                    document_id,
                    chunk_id,
                )
        extraction_stats["entityCount"] = sum(node.kind == "entity" for node in nodes.values())
        extraction_stats["termCount"] = sum(node.kind == "term" for node in nodes.values())
        extraction_stats["topicCount"] = sum(node.kind == "topic" for node in nodes.values())
        extraction_stats["relationCount"] = sum(edge.kind == "relation" for edge in edges.values())
        return list(nodes.values()), list(edges.values()), extraction_stats

    def _extract_chunks(
        self,
        chunks: Sequence[sqlite3.Row],
        *,
        extractor: GraphExtractor,
        batch_size: int,
        extraction_concurrency: int,
    ) -> tuple[dict[str, GraphExtraction], dict[str, Any]]:
        inputs = {
            str(row["id"]): GraphExtractionInput(
                chunk_id=str(row["id"]),
                document_id=str(row["document_id"]),
                content_hash=str(row["content_hash"]),
                heading=str(row["heading"] or "")[:500],
                content=str(row["content"] or ""),
            )
            for row in chunks
        }
        results: dict[str, GraphExtraction] = {}
        cached_count = 0
        fallback_count = 0
        model_count = 0
        errors: list[str] = []
        missing: list[GraphExtractionInput] = []
        with self.store.connection() as connection:
            for item in inputs.values():
                row = connection.execute(
                    "SELECT content_hash, result_json, status FROM knowledge_graph_extractions "
                    "WHERE chunk_id=? AND extractor_fingerprint=?",
                    (item.chunk_id, extractor.fingerprint),
                ).fetchone()
                if row is None or str(row["content_hash"]) != item.content_hash or str(row["status"]) != "succeeded":
                    missing.append(item)
                    continue
                try:
                    raw = json.loads(str(row["result_json"]))
                    results[item.chunk_id] = extraction_from_dict(raw, item)
                    cached_count += 1
                except (json.JSONDecodeError, TypeError, ValueError):
                    missing.append(item)
        fallback = DeterministicGraphExtractor()
        batches = [missing[offset : offset + batch_size] for offset in range(0, len(missing), batch_size)]
        effective_concurrency = (
            max(1, min(4, int(extraction_concurrency), len(batches)))
            if extractor.mode == "model" and batches
            else 1
        )

        def extract_batch(
            batch: list[GraphExtractionInput],
        ) -> tuple[list[GraphExtractionInput], dict[str, GraphExtraction], str]:
            error_message = ""
            try:
                extracted = extractor.extract(batch)
            except Exception as exc:
                extracted = {}
                error_message = str(exc)[:500]
            return batch, extracted, error_message

        if effective_concurrency > 1:
            with ThreadPoolExecutor(
                max_workers=effective_concurrency,
                thread_name_prefix="knowledge-graph-extract",
            ) as executor:
                extracted_batches = executor.map(extract_batch, batches)
                batch_results = list(extracted_batches)
        else:
            batch_results = [extract_batch(batch) for batch in batches]

        for batch, extracted, error_message in batch_results:
            if extractor.mode == "model":
                model_count += len(extracted)
            if error_message:
                errors.append(error_message)
            model_result_ids = set(extracted)
            absent = [item for item in batch if item.chunk_id not in extracted]
            if absent:
                fallback_count += len(absent)
                extracted.update(fallback.extract(absent))
            with self.store.connection() as connection:
                for item in batch:
                    result = extracted[item.chunk_id]
                    results[item.chunk_id] = result
                    item_status = (
                        "succeeded"
                        if extractor.mode != "model" or item.chunk_id in model_result_ids
                        else "fallback"
                    )
                    connection.execute(
                        "INSERT INTO knowledge_graph_extractions(chunk_id, content_hash, extractor_fingerprint, "
                        "result_json, status, error_message, updated_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(chunk_id, extractor_fingerprint) DO UPDATE SET "
                        "content_hash=excluded.content_hash, result_json=excluded.result_json, status=excluded.status, "
                        "error_message=excluded.error_message, updated_at_ms=excluded.updated_at_ms",
                        (
                            item.chunk_id,
                            item.content_hash,
                            extractor.fingerprint,
                            json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True),
                            item_status,
                            "" if item_status == "succeeded" else error_message,
                            now_ms(),
                        ),
                    )
        stats: dict[str, Any] = {
            "mode": extractor.mode,
            "fingerprint": extractor.fingerprint,
            "processedChunkCount": len(inputs),
            "cachedChunkCount": cached_count,
            "modelChunkCount": model_count,
            "fallbackChunkCount": fallback_count,
            "errorCount": len(errors),
            "batchSize": batch_size,
            "batchCount": len(batches),
            "extractionConcurrency": (
                max(1, min(4, int(extraction_concurrency))) if extractor.mode == "model" else 1
            ),
            "effectiveExtractionConcurrency": effective_concurrency if batches else 0,
            "configured": bool(getattr(extractor, "configured", extractor.mode != "model")),
        }
        extractor_config = getattr(extractor, "config", None)
        if extractor_config is not None:
            stats["model"] = str(getattr(extractor_config, "model", ""))[:160]
        if errors:
            stats["lastError"] = errors[-1]
        return results, stats

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
        extractor_mode: str,
        extractor_model: str,
        extraction_stats: dict[str, Any],
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
                "document_ids_json=?, job_id=?, error_message='', updated_at_ms=?, extractor_mode=?, "
                "extractor_model=?, extraction_stats_json=? WHERE base_id=?",
                (
                    revision,
                    fingerprint,
                    "[]",
                    job_id,
                    timestamp,
                    extractor_mode,
                    extractor_model or str(extraction_stats.get("model") or ""),
                    json.dumps(extraction_stats, ensure_ascii=False, sort_keys=True),
                    base_id,
                ),
            )
            connection.execute(
                "UPDATE knowledge_graph_jobs SET status='succeeded', stage='completed', finished_at_ms=?, "
                "updated_at_ms=?, stats_json=? WHERE id=?",
                (timestamp, timestamp, json.dumps(extraction_stats, ensure_ascii=False, sort_keys=True), job_id),
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
            "SELECT d.id, d.revision, d.status, d.output_hash, COUNT(c.id) AS chunk_count, "
            "COALESCE(GROUP_CONCAT(c.content_hash, ','), '') AS chunk_hashes "
            "FROM knowledge_documents d LEFT JOIN knowledge_chunks c ON c.document_id=d.id "
            f"WHERE {' AND '.join(filters)} GROUP BY d.id HAVING COUNT(c.id) > 0 ORDER BY d.id",
            params,
        ).fetchall()
        payload = [
            [str(row["id"]), int(row["revision"]), str(row["status"]), str(row["output_hash"] or ""),
             int(row["chunk_count"]), str(row["chunk_hashes"])]
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
    *,
    dedupe_across_chunks: bool = False,
) -> None:
    edge_id = _stable_id("edge", source, target, kind, "" if dedupe_across_chunks else (chunk_id or ""))
    edges[edge_id] = _Edge(edge_id, source, target, kind, label, weight, document_id, chunk_id)


def _normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())[:160]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _kind_order(kind: str) -> int:
    return {"document": 0, "topic": 1, "chunk": 2, "entity": 3, "term": 4}.get(kind, 5)


def _semantic_kind_order(kind: str) -> int:
    return {"entity": 0, "term": 1, "topic": 2, "document": 3, "chunk": 4}.get(kind, 5)


def _json_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}
