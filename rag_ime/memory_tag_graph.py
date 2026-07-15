from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Mapping

from .text_utils import compact_whitespace, token_terms


@dataclass(frozen=True)
class TagActivation:
    tag_id: int
    tag: str
    energy: float
    hop: int
    path_tag_ids: tuple[int, ...]
    path_tags: tuple[str, ...]
    edge_types: tuple[str, ...] = ()
    evidence_count: int = 0


def recompute_tag_graph(conn: sqlite3.Connection, *, project: str = "") -> dict[str, object]:
    params: list[object] = []
    where = [
        "mi.status IN ('active', 'approved')",
        "mt.status = 'active'",
        "mt.source IN ('dsv4', 'user')",
    ]
    if project:
        where.append("(mi.project = ? OR mi.project = '')")
        params.append(project)
    memory_item_count = int(conn.execute(
        f"""
        SELECT COUNT(DISTINCT mi.id)
        FROM memory_items mi
        JOIN memory_item_tags mit ON mit.memory_item_id = mi.id
        JOIN memory_tags mt ON mt.id = mit.tag_id
        WHERE {' AND '.join(where)}
        ORDER BY mi.id, mit.position
        """,
        params,
    ).fetchone()[0])
    # Co-occurrence edges were a legacy heuristic and made noisy automatic
    # tags look authoritative. The graph is now exclusively maintained by
    # reviewed DSV4 tagEdge operations (or explicit user edits).
    deleted_heuristic_edges = int(
        conn.execute("SELECT COUNT(*) FROM memory_tag_edges WHERE edge_type = 'cooccur'").fetchone()[0]
    )
    conn.execute("DELETE FROM memory_tag_edges WHERE edge_type = 'cooccur'")
    governed_edge_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_tag_edges edge
            JOIN memory_tags src ON src.id = edge.src_tag_id
            JOIN memory_tags dst ON dst.id = edge.dst_tag_id
            WHERE src.status = 'active' AND dst.status = 'active'
              AND src.source IN ('dsv4', 'user')
              AND dst.source IN ('dsv4', 'user')
            """
        ).fetchone()[0]
    )
    return {
        "project": project,
        "mode": "dsv4_governed",
        "memoryItems": memory_item_count,
        "edgeWrites": 0,
        "deletedHeuristicEdges": deleted_heuristic_edges,
        "governedEdges": governed_edge_count,
    }


def propagate_tag_energy(
    conn: sqlite3.Connection,
    *,
    query_text: str,
    max_hops: int = 2,
    max_neighbors: int = 8,
    min_energy: float = 0.05,
) -> dict[int, float]:
    seeds = _seed_tag_ids(conn, query_text)
    activations = activate_tag_graph(
        conn,
        seed_energies=seeds,
        max_hops=max_hops,
        max_neighbors=max_neighbors,
        min_energy=min_energy,
    )
    return {tag_id: activation.energy for tag_id, activation in activations.items()}


def activate_tag_graph(
    conn: sqlite3.Connection,
    *,
    seed_energies: Mapping[int, float],
    max_hops: int = 2,
    max_neighbors: int = 8,
    min_energy: float = 0.05,
    decay: float = 0.55,
) -> dict[int, TagActivation]:
    """Expand governed Tag edges with one bounded, explainable algorithm.

    Callers may use different seed discovery policies, but every retrieval path
    shares the same propagation, cycle protection, limits, and provenance.
    """

    if not seed_energies:
        return {}
    seed_ids = tuple(dict.fromkeys(int(tag_id) for tag_id in seed_energies if int(tag_id) > 0))
    if not seed_ids:
        return {}
    placeholders = ",".join("?" for _ in seed_ids)
    rows = conn.execute(
        f"""
        SELECT id, tag
        FROM memory_tags
        WHERE id IN ({placeholders})
          AND status = 'active'
          AND source IN ('dsv4', 'user')
        """,
        seed_ids,
    ).fetchall()
    tag_names = {int(row["id"]): str(row["tag"]) for row in rows}
    activations: dict[int, TagActivation] = {}
    frontier: dict[int, TagActivation] = {}
    for tag_id in seed_ids:
        tag = tag_names.get(tag_id)
        if not tag:
            continue
        energy = _bounded_energy(seed_energies.get(tag_id, 0.0))
        if energy <= 0.0:
            continue
        activation = TagActivation(
            tag_id=tag_id,
            tag=tag,
            energy=energy,
            hop=0,
            path_tag_ids=(tag_id,),
            path_tags=(tag,),
        )
        activations[tag_id] = activation
        frontier[tag_id] = activation

    safe_hops = max(0, min(2, int(max_hops)))
    safe_neighbors = max(1, min(8, int(max_neighbors)))
    safe_min_energy = max(0.0, min(1.0, float(min_energy)))
    safe_decay = max(0.0, min(1.0, float(decay)))
    for hop in range(1, safe_hops + 1):
        next_frontier: dict[int, TagActivation] = {}
        for source in frontier.values():
            neighbors = conn.execute(
                """
                SELECT edge.dst_tag_id, dst.tag AS dst_tag, edge.edge_type,
                       edge.weight, edge.direction_bias, edge.evidence_count
                FROM memory_tag_edges edge
                JOIN memory_tags dst ON dst.id = edge.dst_tag_id
                WHERE edge.src_tag_id = ?
                  AND dst.status = 'active'
                  AND dst.source IN ('dsv4', 'user')
                ORDER BY edge.weight DESC, edge.evidence_count DESC, edge.dst_tag_id ASC
                LIMIT ?
                """,
                (source.tag_id, safe_neighbors),
            ).fetchall()
            for row in neighbors:
                dst_tag_id = int(row["dst_tag_id"])
                if dst_tag_id in source.path_tag_ids:
                    continue
                edge_weight = _bounded_energy(row["weight"])
                direction_factor = 1.05 if float(row["direction_bias"] or 0.0) > 0.0 else 1.0
                propagated = min(1.0, source.energy * edge_weight * safe_decay * direction_factor)
                if propagated <= safe_min_energy:
                    continue
                candidate = TagActivation(
                    tag_id=dst_tag_id,
                    tag=str(row["dst_tag"]),
                    energy=propagated,
                    hop=hop,
                    path_tag_ids=(*source.path_tag_ids, dst_tag_id),
                    path_tags=(*source.path_tags, str(row["dst_tag"])),
                    edge_types=(*source.edge_types, str(row["edge_type"])),
                    evidence_count=source.evidence_count + max(0, int(row["evidence_count"] or 0)),
                )
                current = activations.get(dst_tag_id)
                if current is not None and current.energy >= candidate.energy:
                    continue
                activations[dst_tag_id] = candidate
                queued = next_frontier.get(dst_tag_id)
                if queued is None or candidate.energy > queued.energy:
                    next_frontier[dst_tag_id] = candidate
        frontier = next_frontier
        if not frontier:
            break
    return activations


def score_memory_items_from_tag_energy(conn: sqlite3.Connection, energy: dict[int, float], *, limit: int = 20) -> dict[int, float]:
    if not energy:
        return {}
    scores: dict[int, float] = {}
    for tag_id, tag_energy in energy.items():
        rows = conn.execute(
            """
            SELECT item_tag.memory_item_id, item_tag.weight
            FROM memory_item_tags item_tag
            JOIN memory_items item ON item.id = item_tag.memory_item_id
            JOIN memory_tags tag ON tag.id = item_tag.tag_id
            WHERE item_tag.tag_id = ?
              AND item.status IN ('active', 'approved')
              AND tag.status = 'active'
              AND tag.source IN ('dsv4', 'user')
            """,
            (tag_id,),
        ).fetchall()
        for row in rows:
            memory_item_id = int(row["memory_item_id"])
            scores[memory_item_id] = scores.get(memory_item_id, 0.0) + float(row["weight"]) * tag_energy
    top = sorted(scores.items(), key=lambda item: item[1], reverse=True)[: max(1, limit)]
    return dict(top)


def _seed_tag_ids(conn: sqlite3.Connection, query_text: str) -> dict[int, float]:
    seeds: dict[int, float] = {}
    for term in token_terms(compact_whitespace(query_text), max_terms=24):
        row = conn.execute(
            """
            SELECT id, quality_score
            FROM memory_tags
            WHERE (normalized_tag = ? OR tag = ?)
              AND status = 'active'
              AND source IN ('dsv4', 'user')
            ORDER BY quality_score DESC, id ASC
            LIMIT 1
            """,
            (term.lower(), term),
        ).fetchone()
        if row is None:
            continue
        seeds[int(row["id"])] = _bounded_energy(max(0.2, float(row["quality_score"] or 0.5)))
    return seeds


def _bounded_energy(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))
