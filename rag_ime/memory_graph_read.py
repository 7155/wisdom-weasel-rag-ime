"""Bounded read models for tag relations and semantic-group membership graphs."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Mapping, Sequence

from .management_work_contract import canonical_payload_sha256
from .text_utils import compact_whitespace, truncate_text


GRAPH_SCHEMA_VERSION = "rag-ime.memory-graph.v1"
ENTITY_SCHEMA_VERSION = "rag-ime.memory-entity.v1"

_GRAPH_FIELDS = {
    "plane",
    "project",
    "status",
    "query",
    "focusId",
    "depth",
    "nodeLimit",
    "edgeLimit",
    "minWeight",
}
_ENTITY_FIELDS = {
    "project",
    "connectionsLimit",
    "connectionsCursor",
    "membersLimit",
    "membersCursor",
}
_GRAPH_PLANES = {"tags", "groups"}
_GRAPH_STATUSES = {"active", "merged", "all"}
_GROUP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TAG_ID_PATTERN = re.compile(r"^[1-9][0-9]{0,18}$")
_MEMBER_KINDS = {"atom", "book", "tag", "phrase"}
_COLORS = {"blue", "teal", "green", "orange", "pink", "purple", "gray"}


@dataclass(frozen=True)
class MemoryGraphQuery:
    plane: str
    project: str
    status: str
    query: str
    focus_id: str
    depth: int
    node_limit: int
    edge_limit: int
    min_weight: float

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, object],
        *,
        default_project: str,
    ) -> MemoryGraphQuery:
        _reject_unknown_fields(payload, _GRAPH_FIELDS)
        plane = compact_whitespace(str(payload.get("plane") or ""))
        if plane not in _GRAPH_PLANES:
            raise ValueError("plane must be tags or groups")
        project = _bounded_text(
            payload.get("project") or default_project,
            field="project",
            maximum=128,
        )
        status = compact_whitespace(str(payload.get("status") or "active")).lower()
        if status not in _GRAPH_STATUSES:
            raise ValueError("status must be active, merged, or all")
        query = _bounded_text(payload.get("query"), field="query", maximum=200)
        focus_id = _bounded_text(payload.get("focusId"), field="focusId", maximum=128)
        if focus_id:
            _validate_entity_id("tag" if plane == "tags" else "group", focus_id)
        return cls(
            plane=plane,
            project=project,
            status=status,
            query=query,
            focus_id=focus_id,
            depth=_strict_int(payload.get("depth"), field="depth", default=1, minimum=0, maximum=2),
            node_limit=_strict_int(
                payload.get("nodeLimit"),
                field="nodeLimit",
                default=120,
                minimum=1,
                maximum=200,
            ),
            edge_limit=_strict_int(
                payload.get("edgeLimit"),
                field="edgeLimit",
                default=240,
                minimum=1,
                maximum=500,
            ),
            min_weight=_strict_float(
                payload.get("minWeight"),
                field="minWeight",
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            ),
        )

    def filters(self) -> dict[str, object]:
        return {
            "status": self.status,
            "query": self.query,
            "focusId": self.focus_id,
            "minWeight": self.min_weight,
        }

    def limits(self) -> dict[str, int]:
        return {
            "nodeLimit": self.node_limit,
            "edgeLimit": self.edge_limit,
            "depth": self.depth,
        }


@dataclass(frozen=True)
class MemoryEntityQuery:
    project: str
    connections_limit: int
    connections_offset: int
    members_limit: int
    members_offset: int

    @classmethod
    def parse(
        cls,
        payload: Mapping[str, object],
        *,
        default_project: str,
    ) -> MemoryEntityQuery:
        _reject_unknown_fields(payload, _ENTITY_FIELDS)
        return cls(
            project=_bounded_text(
                payload.get("project") or default_project,
                field="project",
                maximum=128,
            ),
            connections_limit=_strict_int(
                payload.get("connectionsLimit"),
                field="connectionsLimit",
                default=50,
                minimum=1,
                maximum=100,
            ),
            connections_offset=_strict_cursor(payload.get("connectionsCursor"), "connectionsCursor"),
            members_limit=_strict_int(
                payload.get("membersLimit"),
                field="membersLimit",
                default=50,
                minimum=1,
                maximum=100,
            ),
            members_offset=_strict_cursor(payload.get("membersCursor"), "membersCursor"),
        )

    def limits(self) -> dict[str, int]:
        return {
            "connectionsLimit": self.connections_limit,
            "membersLimit": self.members_limit,
        }


def read_memory_graph(
    conn: sqlite3.Connection,
    payload: Mapping[str, object],
    *,
    default_project: str,
) -> dict[str, object]:
    query = MemoryGraphQuery.parse(payload, default_project=default_project)
    graph = _read_tag_graph(conn, query) if query.plane == "tags" else _read_group_graph(conn, query)
    revision_payload = {
        "plane": query.plane,
        "project": query.project,
        "filters": query.filters(),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "truncated": graph["truncated"],
        "limits": query.limits(),
    }
    return {
        "schemaVersion": GRAPH_SCHEMA_VERSION,
        "ok": True,
        "graphRevision": canonical_payload_sha256(revision_payload),
        **revision_payload,
    }


def read_memory_entity(
    conn: sqlite3.Connection,
    kind: str,
    entity_id: str,
    payload: Mapping[str, object],
    *,
    default_project: str,
) -> dict[str, object]:
    normalized_kind = compact_whitespace(kind).lower()
    normalized_id = compact_whitespace(entity_id)
    if normalized_kind not in {"tag", "group", "book"}:
        raise ValueError("memory entity kind must be tag, group, or book")
    _validate_entity_id(normalized_kind, normalized_id)
    query = MemoryEntityQuery.parse(payload, default_project=default_project)

    if normalized_kind == "tag":
        entity = _load_tag_nodes(conn, [normalized_id], project=query.project).get(normalized_id)
        if entity is None:
            raise ValueError("memory tag was not found in the requested project")
        attributes = _tag_attributes(conn, normalized_id)
        connections = _tag_connection_page(conn, normalized_id, query)
        members = _tag_member_page(conn, normalized_id, query)
    elif normalized_kind == "group":
        entity = _load_group_nodes(conn, [normalized_id], project=query.project).get(normalized_id)
        if entity is None:
            raise ValueError("memory group was not found in the requested project")
        attributes = _group_attributes(conn, normalized_id)
        connections = _empty_page(query.connections_limit)
        members = _group_member_page(conn, normalized_id, query)
    else:
        entity = _load_book_nodes(conn, [normalized_id], project=query.project).get(normalized_id)
        if entity is None:
            raise ValueError("memory book was not found in the requested project")
        attributes = _book_attributes(conn, normalized_id)
        connections = _book_group_page(conn, normalized_id, query)
        # A topic book may reference raw atom identifiers. Keep the read model
        # summary-only: expose the bounded count on the node, never the ids or
        # atom text through this endpoint.
        members = _empty_page(query.members_limit)

    return {
        "schemaVersion": ENTITY_SCHEMA_VERSION,
        "ok": True,
        "kind": normalized_kind,
        "entityId": normalized_id,
        "entityRevision": canonical_payload_sha256(
            {"entity": entity, "attributes": attributes}
        ),
        "project": query.project,
        "entity": entity,
        "attributes": attributes,
        "connections": connections,
        "members": members,
        "limits": query.limits(),
    }


def _tag_attributes(conn: sqlite3.Connection, tag_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT mt.tag_type, COALESCE(mtp.aliases_json, '[]') AS aliases_json
        FROM memory_tags mt
        LEFT JOIN memory_tag_profiles mtp ON mtp.tag_id = mt.id
        WHERE CAST(mt.id AS TEXT) = ?
        """,
        (tag_id,),
    ).fetchone()
    if row is None:
        return {"type": "concept", "aliases": [], "tags": []}
    return {
        "type": truncate_text(str(row["tag_type"] or "concept"), 64) or "concept",
        "aliases": _safe_string_list(row["aliases_json"]),
        "tags": [],
    }


def _group_attributes(conn: sqlite3.Connection, group_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT aliases_json, tags_json
        FROM memory_semantic_groups
        WHERE group_id = ?
        """,
        (group_id,),
    ).fetchone()
    if row is None:
        return {"type": "semantic", "aliases": [], "tags": []}
    return {
        "type": "semantic",
        "aliases": _safe_string_list(row["aliases_json"]),
        "tags": _safe_string_list(row["tags_json"]),
    }


def _book_attributes(conn: sqlite3.Connection, book_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT book_type, tags_json
        FROM memory_books
        WHERE book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return {"type": "topic", "aliases": [], "tags": []}
    return {
        "type": truncate_text(str(row["book_type"] or "topic"), 64) or "topic",
        "aliases": [],
        "tags": _safe_string_list(row["tags_json"]),
    }


def _read_tag_graph(conn: sqlite3.Connection, query: MemoryGraphQuery) -> dict[str, object]:
    seed_limit = query.node_limit if query.depth == 0 else min(50, max(1, query.node_limit // 2))
    seed_rows = _select_tag_seeds(conn, query, limit=query.node_limit + 1)
    if query.focus_id and not seed_rows:
        raise ValueError("focus tag was not found in the requested project")

    node_truncated = len(seed_rows) > query.node_limit
    selected = [str(row["id"]) for row in seed_rows[:seed_limit]]
    deferred_seeds = [str(row["id"]) for row in seed_rows[seed_limit:]]
    selected_set = set(selected)
    frontier = list(selected)

    for _hop in range(query.depth):
        if not frontier or len(selected) >= query.node_limit:
            break
        candidate_limit = min(1_000, query.edge_limit + query.node_limit + 1)
        edge_rows = _tag_edges_for_frontier(conn, query, frontier, limit=candidate_limit + 1)
        if len(edge_rows) > candidate_limit:
            node_truncated = True
        next_frontier: list[str] = []
        for row in edge_rows[:candidate_limit]:
            for tag_id in (str(row["src_tag_id"]), str(row["dst_tag_id"])):
                if tag_id in selected_set:
                    continue
                if len(selected) >= query.node_limit:
                    node_truncated = True
                    break
                selected.append(tag_id)
                selected_set.add(tag_id)
                next_frontier.append(tag_id)
        frontier = next_frontier

    for tag_id in deferred_seeds:
        if tag_id in selected_set:
            continue
        if len(selected) >= query.node_limit:
            node_truncated = True
            break
        selected.append(tag_id)
        selected_set.add(tag_id)

    node_map = _load_tag_nodes(conn, selected, project=query.project)
    nodes = [node_map[tag_id] for tag_id in selected if tag_id in node_map]
    edge_rows = _tag_edges_between(conn, query, selected, limit=query.edge_limit + 1)
    edge_truncated = len(edge_rows) > query.edge_limit
    edges = [_tag_edge(row) for row in edge_rows[: query.edge_limit]]
    visible_ids = {str(node["id"]) for node in nodes}
    edges = [
        edge
        for edge in edges
        if str(edge["sourceId"]) in visible_ids and str(edge["targetId"]) in visible_ids
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": {"nodes": node_truncated, "edges": edge_truncated},
    }


def _read_group_graph(conn: sqlite3.Connection, query: MemoryGraphQuery) -> dict[str, object]:
    seed_limit = query.node_limit if query.depth == 0 else min(50, max(1, query.node_limit // 3))
    seed_rows = _select_group_seeds(conn, query, limit=query.node_limit + 1)
    if query.focus_id and not seed_rows:
        raise ValueError("focus group was not found in the requested project")

    node_truncated = len(seed_rows) > query.node_limit
    group_ids = [str(row["group_id"]) for row in seed_rows[:seed_limit]]
    deferred_group_ids = [str(row["group_id"]) for row in seed_rows[seed_limit:]]
    selected_group_ids = list(group_ids)
    selected_group_set = set(group_ids)
    selected_member_refs: list[tuple[str, str]] = []
    selected_member_set: set[tuple[str, str]] = set()
    membership_rows: list[sqlite3.Row] = []
    edge_truncated = False

    if query.depth >= 1 and group_ids:
        candidate_limit = min(2_000, max(query.edge_limit, query.node_limit * 4))
        candidates = _visible_group_memberships(
            conn,
            group_ids,
            project=query.project,
            minimum_weight=query.min_weight,
            limit=candidate_limit + 1,
        )
        if len(candidates) > candidate_limit:
            edge_truncated = True
        for row in candidates[:candidate_limit]:
            ref = (str(row["member_type"]), str(row["member_id"]))
            if ref not in selected_member_set:
                if len(selected_group_ids) + len(selected_member_refs) >= query.node_limit:
                    node_truncated = True
                    continue
                selected_member_refs.append(ref)
                selected_member_set.add(ref)
            membership_rows.append(row)

    # Depth two discovers groups through a shared, already-visible member. It
    # does not invent an unlabeled group-to-group edge.
    if query.depth >= 2 and selected_member_refs:
        capacity = query.node_limit - len(selected_group_ids) - len(selected_member_refs)
        if capacity > 0:
            related_limit = min(1_000, query.edge_limit + capacity + 1)
            related = _related_group_memberships(
                conn,
                selected_member_refs,
                excluded_group_ids=selected_group_ids,
                project=query.project,
                status=query.status,
                minimum_weight=query.min_weight,
                limit=related_limit + 1,
            )
            if len(related) > related_limit:
                edge_truncated = True
            for row in related[:related_limit]:
                group_id = str(row["group_id"])
                if group_id not in selected_group_set:
                    if len(selected_group_ids) + len(selected_member_refs) >= query.node_limit:
                        node_truncated = True
                        continue
                    selected_group_ids.append(group_id)
                    selected_group_set.add(group_id)
                membership_rows.append(row)

    for group_id in deferred_group_ids:
        if group_id in selected_group_set:
            continue
        if len(selected_group_ids) + len(selected_member_refs) >= query.node_limit:
            node_truncated = True
            break
        selected_group_ids.append(group_id)
        selected_group_set.add(group_id)

    group_nodes = _load_group_nodes(conn, selected_group_ids, project=query.project)
    member_nodes = _load_member_nodes(conn, selected_member_refs, project=query.project)
    nodes: list[dict[str, object]] = [
        group_nodes[group_id] for group_id in selected_group_ids if group_id in group_nodes
    ]
    nodes.extend(member_nodes[ref] for ref in selected_member_refs if ref in member_nodes)
    visible_ids = {str(node["id"]) for node in nodes}

    deduplicated_edges: dict[str, dict[str, object]] = {}
    for row in membership_rows:
        edge = _group_member_edge(row)
        if str(edge["sourceId"]) not in visible_ids or str(edge["targetId"]) not in visible_ids:
            continue
        deduplicated_edges[str(edge["id"])] = edge
    edges = sorted(
        deduplicated_edges.values(),
        key=lambda item: (-float(item["weight"]), -int(item["updatedAtMs"]), str(item["id"])),
    )
    if len(edges) > query.edge_limit:
        edge_truncated = True
        edges = edges[: query.edge_limit]
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": {"nodes": node_truncated, "edges": edge_truncated},
    }


def _select_tag_seeds(
    conn: sqlite3.Connection,
    query: MemoryGraphQuery,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    like = f"%{query.query}%"
    return conn.execute(
        f"""
        {_TAG_SCOPE_CTE}
        SELECT mt.id
        FROM memory_tags mt
        LEFT JOIN memory_tag_profiles mtp ON mtp.tag_id = mt.id
        LEFT JOIN tag_scope_summary scope ON scope.tag_id = mt.id
        WHERE mt.source IN ('dsv4', 'user')
          AND (? = 'all' OR mt.status = ?)
          AND {_tag_project_filter('mt', 'scope')}
          AND (? = '' OR CAST(mt.id AS TEXT) = ?)
          AND (
              ? = '' OR mt.tag LIKE ? OR mt.tag_type LIKE ? OR mt.description LIKE ?
              OR COALESCE(mtp.aliases_json, '[]') LIKE ?
          )
        ORDER BY mt.quality_score DESC, mt.updated_at_ms DESC, mt.id ASC
        LIMIT ?
        """,
        (
            query.project,
            query.status,
            query.status,
            query.project,
            query.project,
            query.focus_id,
            query.focus_id,
            query.query,
            like,
            like,
            like,
            like,
            limit,
        ),
    ).fetchall()


def _tag_edges_for_frontier(
    conn: sqlite3.Connection,
    query: MemoryGraphQuery,
    frontier: Sequence[str],
    *,
    limit: int,
) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in frontier)
    return conn.execute(
        f"""
        {_TAG_SCOPE_CTE}
        SELECT e.src_tag_id, e.dst_tag_id, e.edge_type, e.weight,
               e.direction_bias, e.evidence_count, e.updated_at_ms, e.metadata_json
        FROM memory_tag_edges e
        JOIN memory_tags src ON src.id = e.src_tag_id
        JOIN memory_tags dst ON dst.id = e.dst_tag_id
        LEFT JOIN tag_scope_summary src_scope ON src_scope.tag_id = src.id
        LEFT JOIN tag_scope_summary dst_scope ON dst_scope.tag_id = dst.id
        WHERE (e.src_tag_id IN ({placeholders}) OR e.dst_tag_id IN ({placeholders}))
          AND e.weight >= ?
          AND src.source IN ('dsv4', 'user') AND dst.source IN ('dsv4', 'user')
          AND (? = 'all' OR (src.status = ? AND dst.status = ?))
          AND {_tag_project_filter('src', 'src_scope')}
          AND {_tag_project_filter('dst', 'dst_scope')}
        ORDER BY e.weight DESC, e.evidence_count DESC, e.updated_at_ms DESC,
                 e.src_tag_id ASC, e.dst_tag_id ASC, e.edge_type ASC
        LIMIT ?
        """,
        (
            query.project,
            *frontier,
            *frontier,
            query.min_weight,
            query.status,
            query.status,
            query.status,
            query.project,
            query.project,
            query.project,
            query.project,
            limit,
        ),
    ).fetchall()


def _tag_edges_between(
    conn: sqlite3.Connection,
    query: MemoryGraphQuery,
    tag_ids: Sequence[str],
    *,
    limit: int,
) -> list[sqlite3.Row]:
    if not tag_ids:
        return []
    placeholders = ", ".join("?" for _ in tag_ids)
    return conn.execute(
        f"""
        SELECT src_tag_id, dst_tag_id, edge_type, weight, direction_bias,
               evidence_count, updated_at_ms, metadata_json
        FROM memory_tag_edges
        WHERE src_tag_id IN ({placeholders}) AND dst_tag_id IN ({placeholders})
          AND weight >= ?
        ORDER BY weight DESC, evidence_count DESC, updated_at_ms DESC,
                 src_tag_id ASC, dst_tag_id ASC, edge_type ASC
        LIMIT ?
        """,
        (*tag_ids, *tag_ids, query.min_weight, limit),
    ).fetchall()


def _select_group_seeds(
    conn: sqlite3.Connection,
    query: MemoryGraphQuery,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    like = f"%{query.query}%"
    return conn.execute(
        """
        SELECT msg.group_id
        FROM memory_semantic_groups msg
        LEFT JOIN memory_group_overrides mgo ON mgo.context_group_id = msg.group_id
        WHERE (? = 'all' OR msg.status = ?)
          AND length(msg.group_id) BETWEEN 1 AND 128
          AND (? = '' OR msg.project = '' OR msg.project = ?)
          AND (? = '' OR msg.group_id = ?)
          AND (
              ? = '' OR msg.group_id LIKE ? OR msg.title LIKE ? OR msg.description LIKE ?
              OR msg.aliases_json LIKE ? OR msg.tags_json LIKE ?
              OR COALESCE(mgo.title, '') LIKE ? OR COALESCE(mgo.note, '') LIKE ?
          )
        ORDER BY msg.quality_score DESC, msg.updated_at_ms DESC, msg.group_id ASC
        LIMIT ?
        """,
        (
            query.status,
            query.status,
            query.project,
            query.project,
            query.focus_id,
            query.focus_id,
            query.query,
            like,
            like,
            like,
            like,
            like,
            like,
            like,
            limit,
        ),
    ).fetchall()


def _visible_group_memberships(
    conn: sqlite3.Connection,
    group_ids: Sequence[str],
    *,
    project: str,
    minimum_weight: float,
    limit: int,
    offset: int = 0,
) -> list[sqlite3.Row]:
    if not group_ids:
        return []
    placeholders = ", ".join("?" for _ in group_ids)
    return conn.execute(
        f"""
        SELECT msgm.group_id, msgm.member_type, msgm.member_id, msgm.weight,
               msgm.source, msgm.updated_at_ms
        FROM memory_semantic_group_members msgm
        WHERE msgm.group_id IN ({placeholders})
          AND msgm.weight >= ?
          AND {_visible_member_filter('msgm', project=project)}
        ORDER BY msgm.weight DESC, msgm.updated_at_ms DESC,
                 msgm.group_id ASC, msgm.member_type ASC, msgm.member_id ASC
        LIMIT ? OFFSET ?
        """,
        (*group_ids, minimum_weight, *_visible_member_params(project), limit, offset),
    ).fetchall()


def _related_group_memberships(
    conn: sqlite3.Connection,
    member_refs: Sequence[tuple[str, str]],
    *,
    excluded_group_ids: Sequence[str],
    project: str,
    status: str,
    minimum_weight: float,
    limit: int,
) -> list[sqlite3.Row]:
    values = ", ".join("(?, ?)" for _ in member_refs)
    excluded = ", ".join("?" for _ in excluded_group_ids) or "''"
    flat_refs = [value for ref in member_refs for value in ref]
    return conn.execute(
        f"""
        WITH selected(member_type, member_id) AS (VALUES {values})
        SELECT msgm.group_id, msgm.member_type, msgm.member_id, msgm.weight,
               msgm.source, msgm.updated_at_ms
        FROM memory_semantic_group_members msgm
        JOIN selected
          ON selected.member_type = msgm.member_type AND selected.member_id = msgm.member_id
        JOIN memory_semantic_groups msg ON msg.group_id = msgm.group_id
        WHERE msgm.group_id NOT IN ({excluded})
          AND msgm.weight >= ?
          AND (? = 'all' OR msg.status = ?)
          AND (? = '' OR msg.project = '' OR msg.project = ?)
        ORDER BY msgm.weight DESC, msg.quality_score DESC, msgm.updated_at_ms DESC,
                 msgm.group_id ASC, msgm.member_type ASC, msgm.member_id ASC
        LIMIT ?
        """,
        (
            *flat_refs,
            *excluded_group_ids,
            minimum_weight,
            status,
            status,
            project,
            project,
            limit,
        ),
    ).fetchall()


def _load_tag_nodes(
    conn: sqlite3.Connection,
    tag_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not tag_ids:
        return {}
    placeholders = ", ".join("?" for _ in tag_ids)
    rows = conn.execute(
        f"""
        {_TAG_SCOPE_CTE},
        visible_atom_counts AS (
            SELECT CAST(mat.tag_id AS INTEGER) AS tag_id, COUNT(*) AS member_count
            FROM memory_atom_tags mat
            JOIN memory_atoms ma ON ma.id = mat.memory_atom_id
            WHERE ma.privacy_level != 'sensitive'
              AND (? = '' OR COALESCE(ma.scope_project, '') = '' OR ma.scope_project = ?)
            GROUP BY CAST(mat.tag_id AS INTEGER)
        ),
        visible_item_counts AS (
            SELECT mit.tag_id AS tag_id, COUNT(*) AS member_count
            FROM memory_item_tags mit
            JOIN memory_items mi ON mi.id = mit.memory_item_id
            WHERE mi.kind IN ('phrase', 'stable_memory')
              AND mi.privacy_class != 'sensitive'
              AND mi.status NOT IN ('hidden', 'tombstoned')
              AND (? = '' OR mi.project = '' OR mi.project = ?)
            GROUP BY mit.tag_id
        ),
        edge_rows AS (
            SELECT src_tag_id AS tag_id, updated_at_ms FROM memory_tag_edges
            UNION ALL
            SELECT dst_tag_id AS tag_id, updated_at_ms
            FROM memory_tag_edges
            WHERE dst_tag_id != src_tag_id
        ),
        edge_counts AS (
            SELECT tag_id, COUNT(*) AS edge_count, MAX(updated_at_ms) AS updated_at_ms
            FROM edge_rows
            GROUP BY tag_id
        )
        SELECT CAST(mt.id AS TEXT) AS entity_id, mt.tag, mt.tag_type, mt.description,
               mt.source, mt.status, mt.quality_score, mt.updated_at_ms,
               mt.metadata_json, COALESCE(mtp.color_token, 'blue') AS color_token,
               COALESCE(mtp.updated_at_ms, 0) AS profile_updated_at_ms,
               COALESCE(vac.member_count, 0) + COALESCE(vic.member_count, 0) AS member_count,
               COALESCE(ec.edge_count, 0) AS edge_count,
               COALESCE(ec.updated_at_ms, 0) AS edge_updated_at_ms
        FROM memory_tags mt
        LEFT JOIN memory_tag_profiles mtp ON mtp.tag_id = mt.id
        LEFT JOIN tag_scope_summary scope ON scope.tag_id = mt.id
        LEFT JOIN visible_atom_counts vac ON vac.tag_id = mt.id
        LEFT JOIN visible_item_counts vic ON vic.tag_id = mt.id
        LEFT JOIN edge_counts ec ON ec.tag_id = mt.id
        WHERE CAST(mt.id AS TEXT) IN ({placeholders})
          AND mt.source IN ('dsv4', 'user')
          AND {_tag_project_filter('mt', 'scope')}
        """,
        (
            project,
            project,
            project,
            project,
            project,
            *tag_ids,
            project,
            project,
        ),
    ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        entity_id = str(row["entity_id"])
        metadata = _json_object(row["metadata_json"])
        result[entity_id] = _node(
            kind="tag",
            entity_id=entity_id,
            label=str(row["tag"] or entity_id),
            description=str(row["description"] or ""),
            color=str(row["color_token"] or "blue"),
            status=str(row["status"] or "active"),
            source=str(row["source"] or ""),
            project=compact_whitespace(str(metadata.get("project") or "")),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=int(row["member_count"] or 0),
            edge_count=int(row["edge_count"] or 0),
            updated_at_ms=max(
                int(row["updated_at_ms"] or 0),
                int(row["profile_updated_at_ms"] or 0),
                int(row["edge_updated_at_ms"] or 0),
            ),
        )
    return result


def _load_group_nodes(
    conn: sqlite3.Connection,
    group_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not group_ids:
        return {}
    placeholders = ", ".join("?" for _ in group_ids)
    rows = conn.execute(
        f"""
        WITH visible_members AS (
            SELECT member.group_id, member.updated_at_ms
            FROM memory_semantic_group_members member
            WHERE {_visible_member_filter('member', project=project)}
        ),
        member_stats AS (
            SELECT group_id, COUNT(*) AS member_count, MAX(updated_at_ms) AS updated_at_ms
            FROM visible_members
            GROUP BY group_id
        )
        SELECT msg.group_id AS entity_id,
               COALESCE(NULLIF(mgo.title, ''), msg.title) AS title,
               COALESCE(NULLIF(mgo.note, ''), msg.description) AS description,
               COALESCE(mgo.color_token, 'blue') AS color_token,
               msg.project, msg.status, msg.quality_score, msg.updated_at_ms,
               COALESCE(mgo.updated_at_ms, 0) AS override_updated_at_ms,
               COALESCE(ms.member_count, 0) AS member_count,
               COALESCE(ms.updated_at_ms, 0) AS member_updated_at_ms
        FROM memory_semantic_groups msg
        LEFT JOIN memory_group_overrides mgo ON mgo.context_group_id = msg.group_id
        LEFT JOIN member_stats ms ON ms.group_id = msg.group_id
        WHERE msg.group_id IN ({placeholders})
          AND length(msg.group_id) BETWEEN 1 AND 128
          AND (? = '' OR msg.project = '' OR msg.project = ?)
        """,
        (
            *_visible_member_params(project),
            *group_ids,
            project,
            project,
        ),
    ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        entity_id = str(row["entity_id"])
        member_count = int(row["member_count"] or 0)
        result[entity_id] = _node(
            kind="group",
            entity_id=entity_id,
            label=str(row["title"] or entity_id),
            description=str(row["description"] or ""),
            color=str(row["color_token"] or "blue"),
            status=str(row["status"] or "active"),
            source="user" if int(row["override_updated_at_ms"] or 0) > 0 else "dsv4",
            project=str(row["project"] or ""),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=member_count,
            edge_count=member_count,
            updated_at_ms=max(
                int(row["updated_at_ms"] or 0),
                int(row["override_updated_at_ms"] or 0),
                int(row["member_updated_at_ms"] or 0),
            ),
        )
    return result


def _load_member_nodes(
    conn: sqlite3.Connection,
    member_refs: Sequence[tuple[str, str]],
    *,
    project: str,
) -> dict[tuple[str, str], dict[str, object]]:
    grouped: dict[str, list[str]] = {kind: [] for kind in _MEMBER_KINDS}
    for kind, entity_id in member_refs:
        if kind in grouped and entity_id not in grouped[kind]:
            grouped[kind].append(entity_id)

    result: dict[tuple[str, str], dict[str, object]] = {}
    for entity_id, node in _load_atom_nodes(conn, grouped["atom"], project=project).items():
        result[("atom", entity_id)] = node
    for entity_id, node in _load_book_nodes(conn, grouped["book"], project=project).items():
        result[("book", entity_id)] = node
    for entity_id, node in _load_tag_nodes(conn, grouped["tag"], project=project).items():
        result[("tag", entity_id)] = node
    for entity_id, node in _load_phrase_nodes(conn, grouped["phrase"], project=project).items():
        result[("phrase", entity_id)] = node
    return result


def _load_atom_nodes(
    conn: sqlite3.Connection,
    atom_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not atom_ids:
        return {}
    placeholders = ", ".join("?" for _ in atom_ids)
    rows = conn.execute(
        f"""
        WITH group_counts AS (
            SELECT member_id, COUNT(*) AS edge_count
            FROM memory_semantic_group_members
            WHERE member_type = 'atom'
            GROUP BY member_id
        )
        SELECT ma.id AS entity_id, ma.kind,
               COALESCE(NULLIF(ma.canonical_text, ''), ma.text) AS label,
               ma.scope_project AS project, ma.status, ma.quality_score, ma.updated_at_ms,
               COALESCE(gc.edge_count, 0) AS edge_count
        FROM memory_atoms ma
        LEFT JOIN group_counts gc ON gc.member_id = ma.id
        WHERE ma.id IN ({placeholders})
          AND length(ma.id) BETWEEN 1 AND 128
          AND ma.privacy_level != 'sensitive'
          AND (? = '' OR COALESCE(ma.scope_project, '') = '' OR ma.scope_project = ?)
        """,
        (*atom_ids, project, project),
    ).fetchall()
    return {
        str(row["entity_id"]): _node(
            kind="atom",
            entity_id=str(row["entity_id"]),
            label=str(row["label"] or row["entity_id"]),
            description=str(row["kind"] or "memory atom"),
            color="gray",
            status=str(row["status"] or "active"),
            source="memory_atom",
            project=str(row["project"] or ""),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=0,
            edge_count=int(row["edge_count"] or 0),
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )
        for row in rows
    }


def _load_book_nodes(
    conn: sqlite3.Connection,
    book_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not book_ids:
        return {}
    placeholders = ", ".join("?" for _ in book_ids)
    rows = conn.execute(
        f"""
        WITH group_counts AS (
            SELECT member_id, COUNT(*) AS edge_count
            FROM memory_semantic_group_members
            WHERE member_type = 'book'
            GROUP BY member_id
        )
        SELECT mb.book_id AS entity_id, mb.title, mb.summary, mb.project,
               mb.memory_atom_ids_json,
               mb.status, mb.quality_score, mb.updated_at_ms,
               COALESCE(gc.edge_count, 0) AS edge_count
        FROM memory_books mb
        LEFT JOIN group_counts gc ON gc.member_id = mb.book_id
        WHERE mb.book_id IN ({placeholders})
          AND length(mb.book_id) BETWEEN 1 AND 128
          AND (? = '' OR mb.project = '' OR mb.project = ?)
        """,
        (*book_ids, project, project),
    ).fetchall()
    return {
        str(row["entity_id"]): _node(
            kind="book",
            entity_id=str(row["entity_id"]),
            label=str(row["title"] or row["entity_id"]),
            description=str(row["summary"] or ""),
            color="teal",
            status=str(row["status"] or "active"),
            source="memory_book",
            project=str(row["project"] or ""),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=_json_array_count(row["memory_atom_ids_json"]),
            edge_count=int(row["edge_count"] or 0),
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )
        for row in rows
    }


def _load_phrase_nodes(
    conn: sqlite3.Connection,
    memory_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not memory_ids:
        return {}
    placeholders = ", ".join("?" for _ in memory_ids)
    rows = conn.execute(
        f"""
        WITH group_counts AS (
            SELECT member_id, COUNT(*) AS edge_count
            FROM memory_semantic_group_members
            WHERE member_type = 'phrase'
            GROUP BY member_id
        )
        SELECT mi.memory_id AS entity_id, mi.text AS label, mi.summary, mi.project,
               mi.status, mi.quality_score, mi.updated_at_ms,
               COALESCE(gc.edge_count, 0) AS edge_count
        FROM memory_items mi
        LEFT JOIN group_counts gc ON gc.member_id = mi.memory_id
        WHERE mi.memory_id IN ({placeholders})
          AND length(mi.memory_id) BETWEEN 1 AND 128
          AND mi.kind = 'phrase'
          AND mi.privacy_class != 'sensitive'
          AND mi.status NOT IN ('hidden', 'tombstoned')
          AND (? = '' OR mi.project = '' OR mi.project = ?)
        """,
        (*memory_ids, project, project),
    ).fetchall()
    return {
        str(row["entity_id"]): _node(
            kind="phrase",
            entity_id=str(row["entity_id"]),
            label=str(row["label"] or row["entity_id"]),
            description=str(row["summary"] or ""),
            color="purple",
            status=str(row["status"] or "active"),
            source="memory_item",
            project=str(row["project"] or ""),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=0,
            edge_count=int(row["edge_count"] or 0),
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )
        for row in rows
    }


def _tag_connection_page(
    conn: sqlite3.Connection,
    tag_id: str,
    query: MemoryEntityQuery,
) -> dict[str, object]:
    rows = conn.execute(
        f"""
        {_TAG_SCOPE_CTE}
        SELECT e.src_tag_id, e.dst_tag_id, e.edge_type, e.weight,
               e.direction_bias, e.evidence_count, e.updated_at_ms, e.metadata_json,
               CAST(CASE WHEN CAST(e.src_tag_id AS TEXT) = ? THEN e.dst_tag_id ELSE e.src_tag_id END AS TEXT) AS other_id
        FROM memory_tag_edges e
        JOIN memory_tags other
          ON other.id = CASE WHEN CAST(e.src_tag_id AS TEXT) = ? THEN e.dst_tag_id ELSE e.src_tag_id END
        LEFT JOIN tag_scope_summary scope ON scope.tag_id = other.id
        WHERE (CAST(e.src_tag_id AS TEXT) = ? OR CAST(e.dst_tag_id AS TEXT) = ?)
          AND other.source IN ('dsv4', 'user') AND other.status = 'active'
          AND {_tag_project_filter('other', 'scope')}
        ORDER BY e.weight DESC, e.evidence_count DESC, e.updated_at_ms DESC,
                 e.src_tag_id ASC, e.dst_tag_id ASC, e.edge_type ASC
        LIMIT ? OFFSET ?
        """,
        (
            query.project,
            tag_id,
            tag_id,
            tag_id,
            tag_id,
            query.project,
            query.project,
            query.connections_limit + 1,
            query.connections_offset,
        ),
    ).fetchall()
    has_more = len(rows) > query.connections_limit
    rows = rows[: query.connections_limit]
    node_map = _load_tag_nodes(
        conn,
        [str(row["other_id"]) for row in rows],
        project=query.project,
    )
    items = [
        {"node": node_map[str(row["other_id"])], "edge": _tag_edge(row)}
        for row in rows
        if str(row["other_id"]) in node_map
    ]
    return _page(
        items,
        limit=query.connections_limit,
        offset=query.connections_offset,
        has_more=has_more,
    )


def _tag_member_page(
    conn: sqlite3.Connection,
    tag_id: str,
    query: MemoryEntityQuery,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT member_kind, entity_id, weight, source, updated_at_ms
        FROM (
            SELECT 'atom' AS member_kind, ma.id AS entity_id, mat.weight AS weight,
                   mat.source AS source, ma.updated_at_ms AS updated_at_ms
            FROM memory_atom_tags mat
            JOIN memory_atoms ma ON ma.id = mat.memory_atom_id
            WHERE CAST(mat.tag_id AS TEXT) = ?
              AND ma.privacy_level != 'sensitive'
              AND (? = '' OR COALESCE(ma.scope_project, '') = '' OR ma.scope_project = ?)
            UNION ALL
            SELECT CASE WHEN mi.kind = 'phrase' THEN 'phrase' ELSE 'memory' END AS member_kind,
                   mi.memory_id AS entity_id, mit.weight AS weight,
                   'memory_item_tags' AS source, mi.updated_at_ms AS updated_at_ms
            FROM memory_item_tags mit
            JOIN memory_items mi ON mi.id = mit.memory_item_id
            WHERE CAST(mit.tag_id AS TEXT) = ?
              AND mi.kind IN ('phrase', 'stable_memory')
              AND mi.privacy_class != 'sensitive'
              AND mi.status NOT IN ('hidden', 'tombstoned')
              AND (? = '' OR mi.project = '' OR mi.project = ?)
        ) visible_members
        ORDER BY weight DESC, updated_at_ms DESC, member_kind ASC, entity_id ASC
        LIMIT ? OFFSET ?
        """,
        (
            tag_id,
            query.project,
            query.project,
            tag_id,
            query.project,
            query.project,
            query.members_limit + 1,
            query.members_offset,
        ),
    ).fetchall()
    has_more = len(rows) > query.members_limit
    rows = rows[: query.members_limit]
    atom_ids = [
        str(row["entity_id"])
        for row in rows
        if str(row["member_kind"]) == "atom"
    ]
    phrase_ids = [
        str(row["entity_id"])
        for row in rows
        if str(row["member_kind"]) in {"phrase", "memory"}
    ]
    node_map: dict[tuple[str, str], dict[str, object]] = {}
    for entity_id, node in _load_atom_nodes(conn, atom_ids, project=query.project).items():
        node_map[("atom", entity_id)] = node
    for entity_id, node in _load_memory_item_nodes(conn, phrase_ids, project=query.project).items():
        node_map[(str(node["kind"]), entity_id)] = node

    tag_node_id = _node_id("tag", tag_id)
    items: list[dict[str, object]] = []
    for row in rows:
        member_kind = str(row["member_kind"])
        node_kind = "memory" if member_kind == "memory" else member_kind
        entity_id = str(row["entity_id"])
        node = node_map.get((node_kind, entity_id))
        if node is None:
            continue
        edge = {
            "id": f"tag-member::{tag_id}::{node_kind}::{entity_id}",
            "kind": "tagMember",
            "sourceId": tag_node_id,
            "targetId": node["id"],
            "sourceKind": "tag",
            "targetKind": node_kind,
            "relation": "tagged",
            "weight": _bounded_score(row["weight"]),
            "directionBias": 0.0,
            "evidenceCount": 1,
            "source": str(row["source"] or "memory_membership"),
            "updatedAtMs": int(row["updated_at_ms"] or 0),
        }
        items.append({"node": node, "edge": edge})
    return _page(
        items,
        limit=query.members_limit,
        offset=query.members_offset,
        has_more=has_more,
    )


def _load_memory_item_nodes(
    conn: sqlite3.Connection,
    memory_ids: Sequence[str],
    *,
    project: str,
) -> dict[str, dict[str, object]]:
    if not memory_ids:
        return {}
    placeholders = ", ".join("?" for _ in memory_ids)
    rows = conn.execute(
        f"""
        SELECT mi.memory_id AS entity_id, mi.kind, mi.text AS label, mi.summary,
               mi.project, mi.status, mi.quality_score, mi.updated_at_ms
        FROM memory_items mi
        WHERE mi.memory_id IN ({placeholders})
          AND length(mi.memory_id) BETWEEN 1 AND 128
          AND mi.kind IN ('phrase', 'stable_memory')
          AND mi.privacy_class != 'sensitive'
          AND mi.status NOT IN ('hidden', 'tombstoned')
          AND (? = '' OR mi.project = '' OR mi.project = ?)
        """,
        (*memory_ids, project, project),
    ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        entity_id = str(row["entity_id"])
        kind = "phrase" if str(row["kind"]) == "phrase" else "memory"
        result[entity_id] = _node(
            kind=kind,
            entity_id=entity_id,
            label=str(row["label"] or entity_id),
            description=str(row["summary"] or ""),
            color="purple" if kind == "phrase" else "green",
            status=str(row["status"] or "active"),
            source="memory_item",
            project=str(row["project"] or ""),
            quality_score=float(row["quality_score"] or 0.0),
            member_count=0,
            edge_count=0,
            updated_at_ms=int(row["updated_at_ms"] or 0),
        )
    return result


def _group_member_page(
    conn: sqlite3.Connection,
    group_id: str,
    query: MemoryEntityQuery,
) -> dict[str, object]:
    rows = _visible_group_memberships(
        conn,
        [group_id],
        project=query.project,
        minimum_weight=0.0,
        limit=query.members_limit + 1,
        offset=query.members_offset,
    )
    has_more = len(rows) > query.members_limit
    rows = rows[: query.members_limit]
    refs = [(str(row["member_type"]), str(row["member_id"])) for row in rows]
    node_map = _load_member_nodes(conn, refs, project=query.project)
    items = [
        {"node": node_map[ref], "edge": _group_member_edge(row)}
        for row, ref in zip(rows, refs, strict=True)
        if ref in node_map
    ]
    return _page(
        items,
        limit=query.members_limit,
        offset=query.members_offset,
        has_more=has_more,
    )


def _book_group_page(
    conn: sqlite3.Connection,
    book_id: str,
    query: MemoryEntityQuery,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT member.group_id, member.member_type, member.member_id, member.weight,
               member.source, member.updated_at_ms
        FROM memory_semantic_group_members member
        JOIN memory_semantic_groups group_record ON group_record.group_id = member.group_id
        WHERE member.member_type = 'book' AND member.member_id = ?
          AND group_record.status = 'active'
          AND (? = '' OR group_record.project = '' OR group_record.project = ?)
        ORDER BY member.weight DESC, member.updated_at_ms DESC, member.group_id ASC
        LIMIT ? OFFSET ?
        """,
        (
            book_id,
            query.project,
            query.project,
            query.connections_limit + 1,
            query.connections_offset,
        ),
    ).fetchall()
    has_more = len(rows) > query.connections_limit
    rows = rows[: query.connections_limit]
    node_map = _load_group_nodes(
        conn,
        [str(row["group_id"]) for row in rows],
        project=query.project,
    )
    items = [
        {"node": node_map[str(row["group_id"])], "edge": _group_member_edge(row)}
        for row in rows
        if str(row["group_id"]) in node_map
    ]
    return _page(
        items,
        limit=query.connections_limit,
        offset=query.connections_offset,
        has_more=has_more,
    )


def _node(
    *,
    kind: str,
    entity_id: str,
    label: str,
    description: str,
    color: str,
    status: str,
    source: str,
    project: str,
    quality_score: float,
    member_count: int,
    edge_count: int,
    updated_at_ms: int,
) -> dict[str, object]:
    return {
        "id": _node_id(kind, entity_id),
        "entityId": entity_id,
        "kind": kind,
        "label": truncate_text(label, 120) or entity_id,
        "description": truncate_text(description, 240),
        "color": _color_token(color),
        "status": truncate_text(status, 32) or "active",
        "source": truncate_text(source, 64),
        "project": truncate_text(project, 128),
        "qualityScore": _bounded_score(quality_score),
        "memberCount": max(0, int(member_count)),
        "edgeCount": max(0, int(edge_count)),
        "updatedAtMs": max(0, int(updated_at_ms)),
    }


def _tag_edge(row: Mapping[str, object]) -> dict[str, object]:
    src_id = str(row["src_tag_id"])
    dst_id = str(row["dst_tag_id"])
    relation = truncate_text(str(row["edge_type"] or "related"), 64) or "related"
    metadata = _json_object(row["metadata_json"])
    return {
        "id": f"tag-relation::{src_id}::{dst_id}::{relation}",
        "kind": "tagRelation",
        "sourceId": _node_id("tag", src_id),
        "targetId": _node_id("tag", dst_id),
        "sourceKind": "tag",
        "targetKind": "tag",
        "relation": relation,
        "weight": _bounded_score(row["weight"]),
        "directionBias": _bounded_direction(row["direction_bias"]),
        "evidenceCount": max(0, int(row["evidence_count"] or 0)),
        "source": truncate_text(str(metadata.get("source") or "dsv4"), 64),
        "updatedAtMs": max(0, int(row["updated_at_ms"] or 0)),
    }


def _group_member_edge(row: Mapping[str, object]) -> dict[str, object]:
    group_id = str(row["group_id"])
    member_kind = str(row["member_type"])
    member_id = str(row["member_id"])
    return {
        "id": f"group-member::{group_id}::{member_kind}::{member_id}",
        "kind": "groupMember",
        "sourceId": _node_id("group", group_id),
        "targetId": _node_id(member_kind, member_id),
        "sourceKind": "group",
        "targetKind": member_kind,
        "relation": "contains",
        "weight": _bounded_score(row["weight"]),
        "directionBias": 1.0,
        "evidenceCount": 1,
        "source": truncate_text(str(row["source"] or "dsv4"), 64),
        "updatedAtMs": max(0, int(row["updated_at_ms"] or 0)),
    }


def _node_id(kind: str, entity_id: str) -> str:
    return f"{kind}::{entity_id}"


def _page(
    items: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
    has_more: bool,
) -> dict[str, object]:
    return {
        "items": items,
        "nextCursor": str(offset + limit) if has_more else "",
        "limit": limit,
        "hasMore": has_more,
    }


def _empty_page(limit: int) -> dict[str, object]:
    return {"items": [], "nextCursor": "", "limit": limit, "hasMore": False}


# Tags are global records. Project scope is derived in one bulk CTE from their
# persisted item, atom, and semantic-group memberships.
_TAG_SCOPE_CTE = """
WITH tag_scope AS (
    SELECT mit.tag_id AS tag_id, mi.project AS project
    FROM memory_item_tags mit
    JOIN memory_items mi ON mi.id = mit.memory_item_id
    UNION ALL
    SELECT CAST(mat.tag_id AS INTEGER) AS tag_id, COALESCE(ma.scope_project, '') AS project
    FROM memory_atom_tags mat
    JOIN memory_atoms ma ON ma.id = mat.memory_atom_id
    UNION ALL
    SELECT CAST(msgm.member_id AS INTEGER) AS tag_id, msg.project AS project
    FROM memory_semantic_group_members msgm
    JOIN memory_semantic_groups msg ON msg.group_id = msgm.group_id
    WHERE msgm.member_type = 'tag'
),
tag_scope_summary AS (
    SELECT tag_id, COUNT(*) AS scope_count,
           MAX(CASE WHEN COALESCE(project, '') IN ('', ?) THEN 1 ELSE 0 END) AS matches_project
    FROM tag_scope
    GROUP BY tag_id
)
"""


def _tag_project_filter(tag_alias: str, scope_alias: str) -> str:
    metadata_project = (
        f"COALESCE(CASE WHEN json_valid({tag_alias}.metadata_json) "
        f"THEN json_extract({tag_alias}.metadata_json, '$.project') ELSE '' END, '')"
    )
    return (
        f"(? = '' OR {metadata_project} = ? OR COALESCE({scope_alias}.matches_project, 0) = 1 "
        f"OR ({metadata_project} = '' AND COALESCE({scope_alias}.scope_count, 0) = 0))"
    )


def _visible_member_filter(alias: str, *, project: str) -> str:
    _ = project
    return f"""(
        length({alias}.member_id) BETWEEN 1 AND 128 AND (
        ({alias}.member_type = 'atom' AND EXISTS (
            SELECT 1 FROM memory_atoms ma
            WHERE ma.id = {alias}.member_id AND ma.privacy_level != 'sensitive'
              AND (? = '' OR COALESCE(ma.scope_project, '') = '' OR ma.scope_project = ?)
        ))
        OR ({alias}.member_type = 'book' AND EXISTS (
            SELECT 1 FROM memory_books mb
            WHERE mb.book_id = {alias}.member_id
              AND (? = '' OR mb.project = '' OR mb.project = ?)
        ))
        OR ({alias}.member_type = 'tag' AND EXISTS (
            SELECT 1 FROM memory_tags mt
            WHERE CAST(mt.id AS TEXT) = {alias}.member_id
              AND mt.status = 'active' AND mt.source IN ('dsv4', 'user')
        ))
        OR ({alias}.member_type = 'phrase' AND EXISTS (
            SELECT 1 FROM memory_items mi
            WHERE mi.memory_id = {alias}.member_id AND mi.kind = 'phrase'
              AND mi.privacy_class != 'sensitive'
              AND mi.status NOT IN ('hidden', 'tombstoned')
              AND (? = '' OR mi.project = '' OR mi.project = ?)
        ))
        )
    )"""


def _visible_member_params(project: str) -> tuple[str, ...]:
    return (project, project, project, project, project, project)


def _reject_unknown_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(str(key) for key in payload if key not in allowed)
    if unknown:
        raise ValueError(f"unsupported query field: {unknown[0]}")


def _validate_entity_id(kind: str, entity_id: str) -> None:
    pattern = _TAG_ID_PATTERN if kind == "tag" else _GROUP_ID_PATTERN
    if not pattern.fullmatch(entity_id):
        raise ValueError(f"invalid memory {kind} id")


def _bounded_text(value: object, *, field: str, maximum: int) -> str:
    raw = str(value or "")
    if any(ord(char) < 32 for char in raw):
        raise ValueError(f"{field} contains control characters")
    text = compact_whitespace(raw)
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return text


def _strict_int(
    value: object,
    *,
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    raw = str(value)
    if not re.fullmatch(r"0|[1-9][0-9]*", raw):
        raise ValueError(f"{field} must be an integer")
    parsed = int(raw)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _strict_float(
    value: object,
    *,
    field: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _strict_cursor(value: object, field: str) -> int:
    if value in (None, ""):
        return 0
    raw = str(value)
    if not re.fullmatch(r"0|[1-9][0-9]{0,6}", raw):
        raise ValueError(f"{field} is invalid")
    return int(raw)


def _color_token(value: object) -> str:
    color = compact_whitespace(str(value or "")).lower()
    return color if color in _COLORS else "gray"


def _bounded_score(value: object) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _bounded_direction(value: object) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(-1.0, min(1.0, parsed))


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _safe_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        raw = parsed if isinstance(parsed, list) else []
    result: list[str] = []
    for item in raw:
        text = truncate_text(str(item or ""), 64)
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= 64:
            break
    return result


def _json_array_count(value: object) -> int:
    if isinstance(value, list):
        return min(len(value), 1_000_000)
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0
    return min(len(parsed), 1_000_000) if isinstance(parsed, list) else 0
