from __future__ import annotations

import sqlite3

from .text_utils import compact_whitespace, token_terms


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
                FROM memory_tag_edges edge
                JOIN memory_tags dst ON dst.id = edge.dst_tag_id
                WHERE edge.src_tag_id = ?
                  AND dst.status = 'active'
                  AND dst.source IN ('dsv4', 'user')
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
        seeds[int(row["id"])] = max(0.2, float(row["quality_score"] or 0.5))
    return seeds
