from __future__ import annotations

import sqlite3
from collections import defaultdict

from .text_utils import compact_whitespace, token_terms


def recompute_tag_graph(conn: sqlite3.Connection, *, project: str = "") -> dict[str, object]:
    params: list[object] = []
    where = ["mi.status != 'deleted'"]
    if project:
        where.append("(mi.project = ? OR mi.project = '')")
        params.append(project)
    rows = conn.execute(
        f"""
        SELECT mi.id AS memory_item_id, mit.tag_id
        FROM memory_items mi
        JOIN memory_item_tags mit ON mit.memory_item_id = mi.id
        WHERE {' AND '.join(where)}
        ORDER BY mi.id, mit.position
        """,
        params,
    ).fetchall()
    grouped: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        grouped[int(row["memory_item_id"])].append(int(row["tag_id"]))
    conn.execute("DELETE FROM memory_tag_edges WHERE edge_type = 'cooccur'")
    edge_count = 0
    for tag_ids in grouped.values():
        for src in tag_ids:
            for dst in tag_ids:
                if src == dst:
                    continue
                edge_count += 1
                conn.execute(
                    """
                    INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, evidence_count, updated_at_ms, metadata_json)
                    VALUES (?, ?, 'cooccur', 1.0, 0.0, 1, strftime('%s','now') * 1000, '{}')
                    ON CONFLICT(src_tag_id, dst_tag_id, edge_type) DO UPDATE SET
                        weight = memory_tag_edges.weight + 0.2,
                        evidence_count = memory_tag_edges.evidence_count + 1,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (src, dst),
                )
    return {
        "project": project,
        "memoryItems": len(grouped),
        "edgeWrites": edge_count,
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
    if not seeds:
        return {}
    energy = dict(seeds)
    frontier = list(seeds)
    decay = 0.55
    for _hop in range(max(0, min(2, max_hops))):
        next_frontier: list[int] = []
        for tag_id in frontier:
            neighbors = conn.execute(
                """
                SELECT dst_tag_id, weight, direction_bias
                FROM memory_tag_edges
                WHERE src_tag_id = ?
                ORDER BY weight DESC
                LIMIT ?
                """,
                (tag_id, max(1, min(8, max_neighbors))),
            ).fetchall()
            for row in neighbors:
                dst_tag_id = int(row["dst_tag_id"])
                propagated = energy[tag_id] * float(row["weight"]) * decay
                if float(row["direction_bias"]) > 0:
                    propagated *= 1.05
                if propagated <= min_energy:
                    continue
                if propagated > energy.get(dst_tag_id, 0.0):
                    energy[dst_tag_id] = propagated
                    next_frontier.append(dst_tag_id)
        frontier = next_frontier
        if not frontier:
            break
    return energy


def score_memory_items_from_tag_energy(conn: sqlite3.Connection, energy: dict[int, float], *, limit: int = 20) -> dict[int, float]:
    if not energy:
        return {}
    scores: dict[int, float] = {}
    for tag_id, tag_energy in energy.items():
        rows = conn.execute(
            """
            SELECT memory_item_id, weight
            FROM memory_item_tags
            WHERE tag_id = ?
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
            WHERE normalized_tag = ? OR tag = ?
            ORDER BY quality_score DESC, id ASC
            LIMIT 1
            """,
            (term.lower(), term),
        ).fetchone()
        if row is None:
            continue
        seeds[int(row["id"])] = max(0.2, float(row["quality_score"] or 0.5))
    return seeds
