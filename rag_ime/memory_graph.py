from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .db import apply_database_migrations
from .memory_ingest import looks_sensitive, normalize_text
from .text_utils import compact_whitespace


_OWNER_KINDS = frozenset({"user", "shared", "agent", "session", "room"})
_ENTITY_STATUSES = frozenset({"active", "superseded", "archived", "tombstoned"})
_RELATION_STATUSES = frozenset({"active", "superseded", "retracted", "tombstoned"})
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")


@dataclass(frozen=True)
class MemoryGraphPrincipal:
    project: str
    user_id: str = "local-user"
    session_id: str = ""
    agent_id: str = ""
    room_ids: tuple[str, ...] = ()
    local_admin: bool = False

    def can_read(self, *, owner_kind: str, owner_id: str, project: str) -> bool:
        if project and compact_whitespace(project) != compact_whitespace(self.project):
            return False
        if self.local_admin:
            return owner_kind in _OWNER_KINDS
        if owner_kind == "shared":
            return True
        if owner_kind == "user":
            return not owner_id or owner_id == self.user_id
        if owner_kind == "agent":
            return bool(self.agent_id and owner_id == self.agent_id)
        if owner_kind == "session":
            return bool(self.session_id and owner_id == self.session_id)
        if owner_kind == "room":
            return owner_id in set(self.room_ids)
        return False


class MemoryGraphStore:
    """Canonical, ACL-aware temporal graph over the existing SQLite ledger."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            apply_database_migrations(conn)

    def upsert_entity(
        self,
        *,
        entity_type: str,
        name: str,
        aliases: Sequence[str] = (),
        sources: Sequence[Mapping[str, object]] = (),
        entity_id: str = "",
        description: str = "",
        owner_kind: str = "user",
        owner_id: str = "local-user",
        project: str = "",
        status: str = "active",
        confidence: float = 0.5,
        metadata: Mapping[str, object] | None = None,
        expected_revision: int | None = None,
        updated_at_ms: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        entity_type = _graph_type(entity_type, field="entity_type")
        canonical_name = _required(name, field="name", maximum=240)
        normalized_name = normalize_text(canonical_name)
        owner_kind, owner_id, project = _scope(owner_kind, owner_id, project)
        if status not in _ENTITY_STATUSES:
            raise ValueError("unsupported memory entity status")
        confidence = _confidence(confidence)
        timestamp = _timestamp(updated_at_ms)
        desired_id = compact_whitespace(entity_id)[:240] or _stable_id(
            "entity", owner_kind, owner_id, project, entity_type, normalized_name
        )
        normalized_aliases = _aliases(aliases, canonical_name=canonical_name)
        source_refs = _source_refs(sources, timestamp=timestamp, allow_empty=True)
        metadata_json = _json_object(metadata)
        with self._maybe_connection(conn) as active:
            for source_ref in source_refs:
                self._assert_source_writable(
                    active,
                    source_ref,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    project=project,
                )
            source_refs = self._bind_source_generations(active, source_refs)
            row = active.execute(
                "SELECT * FROM memory_entities WHERE entity_id = ?",
                (desired_id,),
            ).fetchone()
            if row is None:
                row = active.execute(
                    """
                    SELECT * FROM memory_entities
                    WHERE owner_kind = ? AND owner_id = ? AND project = ?
                      AND entity_type = ? AND normalized_name = ?
                    """,
                    (owner_kind, owner_id, project, entity_type, normalized_name),
                ).fetchone()
            if row is not None and (
                str(row["owner_kind"]) != owner_kind
                or str(row["owner_id"]) != owner_id
                or str(row["project"]) != project
            ):
                raise PermissionError("entity id belongs to another memory owner")
            previous = self._entity_snapshot(active, row) if row is not None else None
            if row is not None and expected_revision is not None and int(row["revision"]) != int(expected_revision):
                raise ValueError("memory entity revision conflict")
            if row is None and expected_revision not in (None, 0):
                raise ValueError("memory entity revision conflict")
            effective_id = str(row["entity_id"]) if row is not None else desired_id
            current_aliases = {
                str(item["normalized_alias"]): str(item["alias"])
                for item in active.execute(
                    "SELECT alias, normalized_alias FROM memory_entity_aliases WHERE entity_id = ?",
                    (effective_id,),
                ).fetchall()
            }
            all_aliases = {**current_aliases, **{normalize_text(item): item for item in normalized_aliases}}
            current_sources = {
                _source_ref_key(item): item
                for item in self._entity_source_rows(active, effective_id)
            }
            incoming_sources = {_source_ref_key(item): item for item in source_refs}
            for key, item in incoming_sources.items():
                if key in current_sources:
                    item["createdAtMs"] = current_sources[key]["createdAtMs"]
            desired_sources = {**current_sources, **incoming_sources}
            changed = row is None or any(
                (
                    str(row["entity_type"]) != entity_type,
                    str(row["canonical_name"]) != canonical_name,
                    str(row["normalized_name"]) != normalized_name,
                    str(row["description"]) != compact_whitespace(description)[:1000],
                    str(row["status"]) != status,
                    abs(float(row["confidence"]) - confidence) > 1e-9,
                    str(row["metadata_json"] or "{}") != metadata_json,
                    set(current_aliases) != set(all_aliases),
                    {
                        key: _source_ref_signature(item) for key, item in current_sources.items()
                    }
                    != {
                        key: _source_ref_signature(item) for key, item in desired_sources.items()
                    },
                )
            )
            if not changed:
                entity = self._entity_payload(active, row)
                return {
                    "operation": "unchanged",
                    "entity": entity,
                    "previous": previous,
                    "outboxEventId": None,
                    "outboxOperation": "",
                }
            revision = 1 if row is None else int(row["revision"]) + 1
            created_at = timestamp if row is None else int(row["created_at_ms"])
            if row is None:
                try:
                    active.execute(
                        """
                        INSERT INTO memory_entities(
                    entity_id, entity_type, canonical_name, normalized_name, description,
                    owner_kind, owner_id, project, status, revision, confidence,
                    created_at_ms, updated_at_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            effective_id,
                            entity_type,
                            canonical_name,
                            normalized_name,
                            compact_whitespace(description)[:1000],
                            owner_kind,
                            owner_id,
                            project,
                            status,
                            revision,
                            confidence,
                            created_at,
                            timestamp,
                            metadata_json,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("memory entity revision conflict") from exc
            else:
                cursor = active.execute(
                    """
                    UPDATE memory_entities SET
                    entity_type = ?,
                    canonical_name = ?,
                    normalized_name = ?,
                    description = ?,
                    status = ?,
                    revision = ?,
                    confidence = ?,
                    updated_at_ms = ?,
                    metadata_json = ?
                    WHERE entity_id = ? AND revision = ?
                    """,
                    (
                        entity_type,
                        canonical_name,
                        normalized_name,
                        compact_whitespace(description)[:1000],
                        status,
                        revision,
                        confidence,
                        timestamp,
                        metadata_json,
                        effective_id,
                        int(row["revision"]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("memory entity revision conflict")
            for normalized_alias, alias in all_aliases.items():
                active.execute(
                    """
                    INSERT INTO memory_entity_aliases(
                        entity_id, alias, normalized_alias, alias_type, weight, created_at_ms
                    ) VALUES (?, ?, ?, 'synonym', 0.8, ?)
                    ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET alias = excluded.alias
                    """,
                    (effective_id, alias, normalized_alias, timestamp),
                )
            for item in desired_sources.values():
                active.execute(
                    """
                    INSERT INTO memory_entity_sources(
                        entity_id, source_type, source_id, source_revision,
                        evidence_text, evidence_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entity_id, source_type, source_id, source_revision) DO UPDATE SET
                        evidence_text = excluded.evidence_text,
                        evidence_json = excluded.evidence_json
                    """,
                    (
                        effective_id,
                        item["sourceType"],
                        item["sourceId"],
                        item["sourceRevision"],
                        item["evidenceText"],
                        json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
                        item["createdAtMs"],
                    ),
                )
            entity_row = active.execute(
                "SELECT * FROM memory_entities WHERE entity_id = ?", (effective_id,)
            ).fetchone()
            entity = self._entity_payload(active, entity_row)
            outbox_id = self.enqueue_projection(
                aggregate_type="entity",
                aggregate_id=effective_id,
                operation="upsert",
                revision=revision,
                payload=entity,
                conn=active,
                updated_at_ms=timestamp,
            )
            return {
                "operation": "created" if row is None else "updated",
                "entity": entity,
                "previous": previous,
                "outboxEventId": outbox_id,
                "outboxOperation": "upsert",
            }

    def upsert_relation(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        fact: str,
        idempotency_key: str,
        sources: Sequence[Mapping[str, object]],
        relation_id: str = "",
        owner_kind: str = "user",
        owner_id: str = "local-user",
        project: str = "",
        valid_from_ms: int | None = None,
        valid_to_ms: int | None = None,
        status: str = "active",
        confidence: float = 0.5,
        metadata: Mapping[str, object] | None = None,
        expected_revision: int | None = None,
        updated_at_ms: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        source_entity_id = _required(source_entity_id, field="source_entity_id", maximum=240)
        target_entity_id = _required(target_entity_id, field="target_entity_id", maximum=240)
        if source_entity_id == target_entity_id:
            raise ValueError("self relation is not allowed")
        relation_type = _graph_type(relation_type, field="relation_type")
        fact = _required(fact, field="fact", maximum=1000)
        idempotency_key = _required(idempotency_key, field="idempotency_key", maximum=240)
        owner_kind, owner_id, project = _scope(owner_kind, owner_id, project)
        if status not in _RELATION_STATUSES:
            raise ValueError("unsupported memory relation status")
        confidence = _confidence(confidence)
        timestamp = _timestamp(updated_at_ms)
        requested_valid_from = None if valid_from_ms is None else max(0, int(valid_from_ms))
        valid_to = None if valid_to_ms in (None, "") else max(0, int(valid_to_ms))
        source_refs = _source_refs(sources, timestamp=timestamp)
        desired_id = compact_whitespace(relation_id)[:240] or _stable_id(
            "relation", owner_kind, owner_id, project, idempotency_key
        )
        metadata_json = _json_object(metadata)
        with self._maybe_connection(conn) as active:
            for source_ref in source_refs:
                self._assert_source_writable(
                    active,
                    source_ref,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    project=project,
                )
            source_refs = self._bind_source_generations(active, source_refs)
            endpoints = {
                str(row["entity_id"]): row
                for row in active.execute(
                    "SELECT * FROM memory_entities WHERE entity_id IN (?, ?)",
                    (source_entity_id, target_entity_id),
                ).fetchall()
            }
            if set(endpoints) != {source_entity_id, target_entity_id}:
                raise ValueError("relation endpoints must reference existing entities")
            for endpoint in endpoints.values():
                if str(endpoint["status"]) != "active":
                    raise ValueError("relation endpoints must be active entities")
                if str(endpoint["project"] or "") not in {"", project}:
                    raise PermissionError("relation endpoint belongs to another project")
                endpoint_owner = (str(endpoint["owner_kind"]), str(endpoint["owner_id"]))
                if endpoint_owner not in {
                    ("shared", ""),
                    (owner_kind, owner_id),
                    ("user", "local-user"),
                } and endpoint_owner[0] != "shared":
                    raise PermissionError("relation endpoint belongs to another memory owner")
            row = active.execute(
                "SELECT * FROM memory_relations WHERE relation_id = ?", (desired_id,)
            ).fetchone()
            if row is not None and str(row["idempotency_key"]) != idempotency_key:
                raise ValueError("relation id is already bound to another idempotency key")
            if row is None:
                row = active.execute(
                    """
                    SELECT * FROM memory_relations
                    WHERE owner_kind = ? AND owner_id = ? AND project = ? AND idempotency_key = ?
                    """,
                    (owner_kind, owner_id, project, idempotency_key),
                ).fetchone()
            valid_from = (
                int(row["valid_from_ms"])
                if row is not None and requested_valid_from is None
                else timestamp if requested_valid_from is None else requested_valid_from
            )
            if valid_to is not None and valid_to <= valid_from:
                raise ValueError("relation valid_to_ms must be greater than valid_from_ms")
            if row is not None and (
                str(row["owner_kind"]) != owner_kind
                or str(row["owner_id"]) != owner_id
                or str(row["project"]) != project
            ):
                raise PermissionError("relation id belongs to another memory owner")
            previous = self._relation_snapshot(active, row) if row is not None else None
            if row is not None and expected_revision is not None and int(row["revision"]) != int(expected_revision):
                raise ValueError("memory relation revision conflict")
            if row is None and expected_revision not in (None, 0):
                raise ValueError("memory relation revision conflict")
            effective_id = str(row["relation_id"]) if row is not None else desired_id
            current_sources = {
                _source_ref_key(item): item
                for item in self._relation_source_rows(active, effective_id)
            }
            incoming_sources = {_source_ref_key(item): item for item in source_refs}
            for key, item in incoming_sources.items():
                if key in current_sources:
                    item["createdAtMs"] = current_sources[key]["createdAtMs"]
            desired_sources = {**current_sources, **incoming_sources}
            changed = row is None or any(
                (
                    str(row["source_entity_id"]) != source_entity_id,
                    str(row["target_entity_id"]) != target_entity_id,
                    str(row["relation_type"]) != relation_type,
                    str(row["fact"]) != fact,
                    int(row["valid_from_ms"]) != valid_from,
                    (int(row["valid_to_ms"]) if row["valid_to_ms"] is not None else None) != valid_to,
                    str(row["status"]) != status,
                    abs(float(row["confidence"]) - confidence) > 1e-9,
                    str(row["metadata_json"] or "{}") != metadata_json,
                    {
                        key: _source_ref_signature(item) for key, item in current_sources.items()
                    }
                    != {
                        key: _source_ref_signature(item) for key, item in desired_sources.items()
                    },
                )
            )
            if not changed:
                relation = self._relation_payload(active, row)
                return {
                    "operation": "unchanged",
                    "relation": relation,
                    "previous": previous,
                    "outboxEventId": None,
                    "outboxOperation": "",
                }
            revision = 1 if row is None else int(row["revision"]) + 1
            created_at = timestamp if row is None else int(row["created_at_ms"])
            if row is None:
                try:
                    active.execute(
                        """
                        INSERT INTO memory_relations(
                            relation_id, source_entity_id, target_entity_id, relation_type,
                            fact, normalized_fact, owner_kind, owner_id, project,
                            valid_from_ms, valid_to_ms, status, revision, idempotency_key,
                            confidence, created_at_ms, updated_at_ms, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            effective_id,
                            source_entity_id,
                            target_entity_id,
                            relation_type,
                            fact,
                            normalize_text(fact),
                            owner_kind,
                            owner_id,
                            project,
                            valid_from,
                            valid_to,
                            status,
                            revision,
                            idempotency_key,
                            confidence,
                            created_at,
                            timestamp,
                            metadata_json,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("memory relation revision conflict") from exc
            else:
                cursor = active.execute(
                    """
                    UPDATE memory_relations SET
                        source_entity_id = ?,
                        target_entity_id = ?,
                        relation_type = ?,
                        fact = ?,
                        normalized_fact = ?,
                        valid_from_ms = ?,
                        valid_to_ms = ?,
                        status = ?,
                        revision = ?,
                        confidence = ?,
                        updated_at_ms = ?,
                        metadata_json = ?
                    WHERE relation_id = ? AND revision = ?
                    """,
                    (
                        source_entity_id,
                        target_entity_id,
                        relation_type,
                        fact,
                        normalize_text(fact),
                        valid_from,
                        valid_to,
                        status,
                        revision,
                        confidence,
                        timestamp,
                        metadata_json,
                        effective_id,
                        int(row["revision"]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("memory relation revision conflict")
            for item in desired_sources.values():
                active.execute(
                    """
                    INSERT INTO memory_relation_sources(
                        relation_id, source_type, source_id, source_revision,
                        evidence_text, evidence_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(relation_id, source_type, source_id, source_revision) DO UPDATE SET
                        evidence_text = excluded.evidence_text,
                        evidence_json = excluded.evidence_json
                    """,
                    (
                        effective_id,
                        item["sourceType"],
                        item["sourceId"],
                        item["sourceRevision"],
                        item["evidenceText"],
                        json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
                        item["createdAtMs"],
                    ),
                )
            relation_row = active.execute(
                "SELECT * FROM memory_relations WHERE relation_id = ?", (effective_id,)
            ).fetchone()
            relation = self._relation_payload(active, relation_row)
            outbox_id = self.enqueue_projection(
                aggregate_type="relation",
                aggregate_id=effective_id,
                operation="upsert",
                revision=revision,
                payload=relation,
                conn=active,
                updated_at_ms=timestamp,
            )
            return {
                "operation": "created" if row is None else "updated",
                "relation": relation,
                "previous": previous,
                "outboxEventId": outbox_id,
                "outboxOperation": "upsert",
            }

    def enqueue_projection(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        operation: str,
        revision: int,
        payload: Mapping[str, object],
        projection_kind: str = "graphiti",
        updated_at_ms: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        timestamp = _timestamp(updated_at_ms)
        with self._maybe_connection(conn) as active:
            active.execute(
                """
                INSERT INTO memory_projection_outbox(
                    projection_kind, aggregate_type, aggregate_id, operation, revision,
                    payload_json, state, attempts, available_at_ms, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                ON CONFLICT(projection_kind, aggregate_type, aggregate_id, operation, revision)
                DO NOTHING
                """,
                (
                    _required(projection_kind, field="projection_kind", maximum=80),
                    _required(aggregate_type, field="aggregate_type", maximum=80),
                    _required(aggregate_id, field="aggregate_id", maximum=240),
                    _required(operation, field="operation", maximum=40),
                    max(1, int(revision)),
                    json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = active.execute(
                """
                SELECT outbox_id FROM memory_projection_outbox
                WHERE projection_kind = ? AND aggregate_type = ? AND aggregate_id = ?
                  AND operation = ? AND revision = ?
                """,
                (projection_kind, aggregate_type, aggregate_id, operation, max(1, int(revision))),
            ).fetchone()
            return int(row["outbox_id"])

    def find_anchors(
        self,
        principal: MemoryGraphPrincipal,
        *,
        source_refs: Sequence[Mapping[str, object]] = (),
        query_text: str = "",
        limit: int = 8,
    ) -> dict[str, object]:
        bounded_limit = min(40, max(1, int(limit)))
        refs = _query_source_refs(source_refs, limit=bounded_limit * 8)
        query = normalize_text(compact_whitespace(query_text)[:500])
        scores: dict[str, float] = {}
        matched_by: dict[str, set[str]] = {}
        relation_ids: dict[str, set[str]] = {}
        with self._maybe_connection(None) as conn:
            self._drain_dirty_sources(conn)
            if refs:
                clauses: list[str] = []
                entity_clauses: list[str] = []
                params: list[object] = []
                for ref in refs:
                    clauses.append("(rs.source_type = ? AND rs.source_id = ?)")
                    entity_clauses.append("(es.source_type = ? AND es.source_id = ?)")
                    params.extend((ref["sourceType"], ref["sourceId"]))
                visibility_sql, visibility_params = _visibility_sql(principal, alias="r")
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT r.*
                    FROM memory_relation_sources AS rs
                    JOIN memory_relations AS r ON r.relation_id = rs.relation_id
                    WHERE ({' OR '.join(clauses)})
                      AND r.status = 'active'
                      AND {visibility_sql}
                    ORDER BY r.confidence DESC, r.updated_at_ms DESC
                    LIMIT ?
                    """,
                    (*params, *visibility_params, bounded_limit * 8),
                ).fetchall()
                for relation in rows:
                    if relation is None or not self._relation_visible(conn, principal, relation):
                        continue
                    for entity_id in (str(relation["source_entity_id"]), str(relation["target_entity_id"])):
                        entity = conn.execute(
                            "SELECT * FROM memory_entities WHERE entity_id = ?", (entity_id,)
                        ).fetchone()
                        if entity is None or not self._entity_visible(conn, principal, entity):
                            continue
                        scores[entity_id] = scores.get(entity_id, 0.0) + 2.0
                        matched_by.setdefault(entity_id, set()).add("source")
                        relation_ids.setdefault(entity_id, set()).add(str(relation["relation_id"]))

                entity_visibility_sql, entity_visibility_params = _visibility_sql(
                    principal,
                    alias="e",
                )
                direct_entities = conn.execute(
                    f"""
                    SELECT DISTINCT e.*
                    FROM memory_entity_sources AS es
                    JOIN memory_entities AS e ON e.entity_id = es.entity_id
                    WHERE ({' OR '.join(entity_clauses)})
                      AND e.status = 'active'
                      AND {entity_visibility_sql}
                    ORDER BY e.confidence DESC, e.updated_at_ms DESC
                    LIMIT ?
                    """,
                    (*params, *entity_visibility_params, bounded_limit * 8),
                ).fetchall()
                for entity in direct_entities:
                    if not self._entity_visible(conn, principal, entity):
                        continue
                    entity_id = str(entity["entity_id"])
                    scores[entity_id] = scores.get(entity_id, 0.0) + 2.0
                    matched_by.setdefault(entity_id, set()).add("source")

            # Name matching is only a bounded fallback when canonical retrieval
            # sources have no graph edge. It is not a second global RAG lane.
            if query and not scores:
                visibility_sql, visibility_params = _visibility_sql(principal, alias="e")
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT e.*
                    FROM memory_entities AS e
                    LEFT JOIN memory_entity_aliases AS a ON a.entity_id = e.entity_id
                    WHERE e.status = 'active'
                      AND {visibility_sql}
                      AND (
                          instr(?, e.normalized_name) > 0
                          OR instr(e.normalized_name, ?) > 0
                          OR instr(?, a.normalized_alias) > 0
                          OR instr(a.normalized_alias, ?) > 0
                      )
                    ORDER BY e.updated_at_ms DESC
                    LIMIT 500
                    """,
                    (*visibility_params, query, query, query, query),
                ).fetchall()
                for entity in rows:
                    if not self._entity_visible(conn, principal, entity):
                        continue
                    entity_id = str(entity["entity_id"])
                    aliases = [
                        str(item["normalized_alias"])
                        for item in conn.execute(
                            "SELECT normalized_alias FROM memory_entity_aliases WHERE entity_id = ?",
                            (entity_id,),
                        ).fetchall()
                    ]
                    names = [str(entity["normalized_name"]), *aliases]
                    name_score = max((_text_anchor_score(query, name) for name in names), default=0.0)
                    if name_score <= 0.0:
                        continue
                    scores[entity_id] = scores.get(entity_id, 0.0) + name_score
                    matched_by.setdefault(entity_id, set()).add("name")

            ranked = sorted(scores, key=lambda item: (-scores[item], item))[:bounded_limit]
            anchors: list[dict[str, object]] = []
            for entity_id in ranked:
                row = conn.execute(
                    "SELECT * FROM memory_entities WHERE entity_id = ?", (entity_id,)
                ).fetchone()
                if row is None:
                    continue
                payload = self._entity_payload(conn, row)
                payload.update(
                    {
                        "score": round(scores[entity_id], 6),
                        "matchedBy": sorted(matched_by.get(entity_id, set())),
                        "relationIds": sorted(relation_ids.get(entity_id, set())),
                    }
                )
                anchors.append(payload)
        return {"schemaVersion": "rag-ime.memory-graph-anchors.v1", "anchors": anchors, "count": len(anchors)}

    def expand(
        self,
        principal: MemoryGraphPrincipal,
        *,
        anchor_ids: Sequence[str],
        max_depth: int = 2,
        limit: int = 20,
        as_of_ms: int | None = None,
    ) -> dict[str, object]:
        depth_limit = min(3, max(1, int(max_depth)))
        relation_limit = min(50, max(1, int(limit)))
        as_of = _timestamp(as_of_ms)
        requested = _ids(anchor_ids, limit=40)
        entity_payloads: dict[str, dict[str, object]] = {}
        relation_payloads: list[dict[str, object]] = []
        visited_relations: set[str] = set()
        with self._maybe_connection(None) as conn:
            self._drain_dirty_sources(conn)
            frontier: set[str] = set()
            for entity_id in requested:
                row = conn.execute(
                    "SELECT * FROM memory_entities WHERE entity_id = ?", (entity_id,)
                ).fetchone()
                if row is not None and self._entity_visible(conn, principal, row):
                    frontier.add(entity_id)
                    entity_payloads[entity_id] = self._entity_payload(conn, row)
            visited_entities = set(frontier)
            for depth in range(1, depth_limit + 1):
                if not frontier or len(relation_payloads) >= relation_limit:
                    break
                placeholders = ", ".join("?" for _ in frontier)
                visibility_sql, visibility_params = _visibility_sql(principal, alias="memory_relations")
                rows = conn.execute(
                    f"""
                    SELECT * FROM memory_relations
                    WHERE status = 'active'
                      AND valid_from_ms <= ?
                      AND (valid_to_ms IS NULL OR valid_to_ms > ?)
                      AND {visibility_sql}
                      AND (source_entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders}))
                    ORDER BY confidence DESC, updated_at_ms DESC
                    LIMIT ?
                    """,
                    (as_of, as_of, *visibility_params, *frontier, *frontier, relation_limit * 8),
                ).fetchall()
                next_frontier: set[str] = set()
                for relation in rows:
                    relation_id = str(relation["relation_id"])
                    if relation_id in visited_relations or not self._relation_visible(
                        conn, principal, relation, as_of_ms=as_of
                    ):
                        continue
                    source_id = str(relation["source_entity_id"])
                    target_id = str(relation["target_entity_id"])
                    source = conn.execute(
                        "SELECT * FROM memory_entities WHERE entity_id = ?", (source_id,)
                    ).fetchone()
                    target = conn.execute(
                        "SELECT * FROM memory_entities WHERE entity_id = ?", (target_id,)
                    ).fetchone()
                    if (
                        source is None
                        or target is None
                        or not self._entity_visible(conn, principal, source)
                        or not self._entity_visible(conn, principal, target)
                    ):
                        continue
                    visited_relations.add(relation_id)
                    payload = self._relation_payload(conn, relation)
                    payload["depth"] = depth
                    payload["traversalDirection"] = (
                        "forward" if source_id in frontier else "reverse"
                    )
                    relation_payloads.append(payload)
                    entity_payloads.setdefault(source_id, self._entity_payload(conn, source))
                    entity_payloads.setdefault(target_id, self._entity_payload(conn, target))
                    for entity_id in (source_id, target_id):
                        if entity_id not in visited_entities:
                            visited_entities.add(entity_id)
                            next_frontier.add(entity_id)
                    if len(relation_payloads) >= relation_limit:
                        break
                frontier = next_frontier
        return {
            "schemaVersion": "rag-ime.memory-graph-expand.v1",
            "anchorIds": [item for item in requested if item in entity_payloads],
            "asOfMs": as_of,
            "entities": list(entity_payloads.values()),
            "relations": relation_payloads,
            "items": relation_payloads,
            "count": len(relation_payloads),
        }

    def browse(
        self,
        principal: MemoryGraphPrincipal,
        *,
        query: str = "",
        owner_kinds: Sequence[str] = (),
        entity_types: Sequence[str] = (),
        as_of_ms: int | None = None,
        node_limit: int = 60,
        relation_limit: int = 100,
    ) -> dict[str, object]:
        """Return a bounded control-plane snapshot without creating another RAG lane."""

        normalized_query = normalize_text(query)
        selected_owners = tuple(
            sorted({_required(item, field="owner_kind", maximum=24) for item in owner_kinds})
        )
        if any(item not in _OWNER_KINDS for item in selected_owners):
            raise ValueError("unsupported memory graph owner kind")
        selected_types = tuple(
            sorted({_graph_type(item, field="entity_type") for item in entity_types})
        )
        max_nodes = min(100, max(1, int(node_limit)))
        max_relations = min(200, max(1, int(relation_limit)))
        as_of = _timestamp(as_of_ms)

        entities: dict[str, sqlite3.Row] = {}
        relation_payloads: list[dict[str, object]] = []
        seen_relations: set[str] = set()

        with self._maybe_connection(None) as conn:
            self._drain_dirty_sources(conn)
            entity_visibility_sql, entity_visibility_params = _visibility_sql(principal, alias="e")
            relation_visibility_sql, relation_visibility_params = _visibility_sql(
                principal, alias="r"
            )

            owner_sql = ""
            owner_params: list[object] = []
            if selected_owners:
                owner_sql = f" AND r.owner_kind IN ({', '.join('?' for _ in selected_owners)})"
                owner_params.extend(selected_owners)
            relation_entity_type_sql = ""
            relation_entity_type_params: list[object] = []
            if selected_types:
                placeholders = ", ".join("?" for _ in selected_types)
                relation_entity_type_sql = (
                    f" AND source.entity_type IN ({placeholders})"
                    f" AND target.entity_type IN ({placeholders})"
                )
                relation_entity_type_params.extend(selected_types)
                relation_entity_type_params.extend(selected_types)
            relation_query_sql = ""
            relation_query_params: list[object] = []
            if normalized_query:
                like = f"%{normalized_query}%"
                relation_query_sql = """
                    AND (
                        r.normalized_fact LIKE ? OR r.relation_type LIKE ?
                        OR source.normalized_name LIKE ? OR target.normalized_name LIKE ?
                        OR EXISTS (
                            SELECT 1 FROM memory_entity_aliases a
                            WHERE (a.entity_id = source.entity_id OR a.entity_id = target.entity_id)
                              AND a.normalized_alias LIKE ?
                        )
                    )
                """
                relation_query_params.extend([like, like, like, like, like])
            relation_rows = conn.execute(
                f"""
                SELECT r.*
                FROM memory_relations r
                JOIN memory_entities source ON source.entity_id = r.source_entity_id
                JOIN memory_entities target ON target.entity_id = r.target_entity_id
                WHERE r.status = 'active'
                  AND r.valid_from_ms <= ?
                  AND (r.valid_to_ms IS NULL OR r.valid_to_ms > ?)
                  AND {relation_visibility_sql}
                  {owner_sql}
                  {relation_entity_type_sql}
                  {relation_query_sql}
                ORDER BY r.confidence DESC, r.updated_at_ms DESC, r.relation_id ASC
                LIMIT ?
                """,
                (
                    as_of,
                    as_of,
                    *relation_visibility_params,
                    *owner_params,
                    *relation_entity_type_params,
                    *relation_query_params,
                    max_relations * 4,
                ),
            ).fetchall()

            def append_relation(row: sqlite3.Row) -> None:
                relation_id = str(row["relation_id"])
                if relation_id in seen_relations or len(relation_payloads) >= max_relations:
                    return
                if not self._relation_visible(conn, principal, row, as_of_ms=as_of):
                    return
                source = conn.execute(
                    "SELECT * FROM memory_entities WHERE entity_id = ?",
                    (str(row["source_entity_id"]),),
                ).fetchone()
                target = conn.execute(
                    "SELECT * FROM memory_entities WHERE entity_id = ?",
                    (str(row["target_entity_id"]),),
                ).fetchone()
                if (
                    source is None
                    or target is None
                    or not self._entity_visible(conn, principal, source)
                    or not self._entity_visible(conn, principal, target)
                ):
                    return
                missing = {
                    str(source["entity_id"]),
                    str(target["entity_id"]),
                } - set(entities)
                if len(entities) + len(missing) > max_nodes:
                    return
                entities[str(source["entity_id"])] = source
                entities[str(target["entity_id"])] = target
                payload = self._relation_payload(conn, row)
                payload.update(
                    {
                        "sourceName": str(source["canonical_name"]),
                        "targetName": str(target["canonical_name"]),
                        "sourceType": str(source["entity_type"]),
                        "targetType": str(target["entity_type"]),
                        "sourceCount": len(payload.get("sources") or []),
                    }
                )
                relation_payloads.append(payload)
                seen_relations.add(relation_id)

            for row in relation_rows:
                append_relation(row)

            entity_owner_sql = ""
            entity_owner_params: list[object] = []
            if selected_owners:
                entity_owner_sql = f" AND e.owner_kind IN ({', '.join('?' for _ in selected_owners)})"
                entity_owner_params.extend(selected_owners)
            entity_type_sql = ""
            entity_type_params: list[object] = []
            if selected_types:
                entity_type_sql = f" AND e.entity_type IN ({', '.join('?' for _ in selected_types)})"
                entity_type_params.extend(selected_types)
            entity_query_sql = ""
            entity_query_params: list[object] = []
            if normalized_query:
                like = f"%{normalized_query}%"
                entity_query_sql = """
                    AND (
                        e.normalized_name LIKE ? OR e.description LIKE ?
                        OR EXISTS (
                            SELECT 1 FROM memory_entity_aliases a
                            WHERE a.entity_id = e.entity_id AND a.normalized_alias LIKE ?
                        )
                    )
                """
                entity_query_params.extend([like, like, like])
            entity_rows = conn.execute(
                f"""
                SELECT e.*
                FROM memory_entities e
                WHERE e.status = 'active'
                  AND {entity_visibility_sql}
                  {entity_owner_sql}
                  {entity_type_sql}
                  {entity_query_sql}
                ORDER BY e.confidence DESC, e.updated_at_ms DESC, e.entity_id ASC
                LIMIT ?
                """,
                (
                    *entity_visibility_params,
                    *entity_owner_params,
                    *entity_type_params,
                    *entity_query_params,
                    max_nodes * 4,
                ),
            ).fetchall()
            for row in entity_rows:
                if len(entities) >= max_nodes:
                    break
                if self._entity_visible(conn, principal, row):
                    entities.setdefault(str(row["entity_id"]), row)

            if entities and len(relation_payloads) < max_relations:
                entity_ids = tuple(entities)
                placeholders = ", ".join("?" for _ in entity_ids)
                connected_rows = conn.execute(
                    f"""
                    SELECT r.*
                    FROM memory_relations r
                    JOIN memory_entities source ON source.entity_id = r.source_entity_id
                    JOIN memory_entities target ON target.entity_id = r.target_entity_id
                    WHERE r.status = 'active'
                      AND r.valid_from_ms <= ?
                      AND (r.valid_to_ms IS NULL OR r.valid_to_ms > ?)
                      AND {relation_visibility_sql}
                      {owner_sql}
                      {relation_entity_type_sql}
                      AND (r.source_entity_id IN ({placeholders}) OR r.target_entity_id IN ({placeholders}))
                    ORDER BY r.confidence DESC, r.updated_at_ms DESC, r.relation_id ASC
                    LIMIT ?
                    """,
                    (
                        as_of,
                        as_of,
                        *relation_visibility_params,
                        *owner_params,
                        *relation_entity_type_params,
                        *entity_ids,
                        *entity_ids,
                        max_relations * 4,
                    ),
                ).fetchall()
                for row in connected_rows:
                    append_relation(row)

            entity_payloads = [self._entity_payload(conn, row) for row in entities.values()]
            degree: dict[str, int] = {str(item["entityId"]): 0 for item in entity_payloads}
            for relation in relation_payloads:
                for key in ("sourceEntityId", "targetEntityId"):
                    entity_id = str(relation[key])
                    degree[entity_id] = degree.get(entity_id, 0) + 1
            for item in entity_payloads:
                item["relationCount"] = degree.get(str(item["entityId"]), 0)

            projection_pending = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_projection_outbox WHERE state IN ('pending', 'processing', 'failed')"
                ).fetchone()[0]
            )
            entity_types_available = [
                {"value": str(row["entity_type"]), "count": int(row["count"])}
                for row in conn.execute(
                    f"""
                    SELECT e.entity_type, COUNT(*) AS count
                    FROM memory_entities e
                    WHERE e.status = 'active' AND {entity_visibility_sql}
                    GROUP BY e.entity_type ORDER BY count DESC, e.entity_type ASC
                    """,
                    entity_visibility_params,
                ).fetchall()
            ]

        return {
            "schemaVersion": "rag-ime.memory-graph-browser.v1",
            "asOfMs": as_of,
            "query": query,
            "entities": entity_payloads,
            "relations": relation_payloads,
            "summary": {
                "visibleEntityCount": len(entity_payloads),
                "visibleRelationCount": len(relation_payloads),
                "evidenceCount": sum(int(item.get("sourceCount") or 0) for item in relation_payloads),
                "projectionPendingCount": projection_pending,
            },
            "filters": {
                "entityTypes": entity_types_available,
                "ownerKinds": sorted(_OWNER_KINDS),
            },
        }

    def get_sources(
        self,
        principal: MemoryGraphPrincipal,
        *,
        relation_ids: Sequence[str] = (),
        source_refs: Sequence[Mapping[str, object]] = (),
        limit: int = 20,
    ) -> dict[str, object]:
        bounded_limit = min(50, max(1, int(limit)))
        requested_relations = _ids(relation_ids, limit=50)
        if not requested_relations:
            raise ValueError("relation_ids is required before source rehydration")
        requested_refs = _query_source_refs(source_refs, limit=50)
        refs: dict[tuple[str, str, int], dict[str, object]] = {}
        with self._maybe_connection(None) as conn:
            self._drain_dirty_sources(conn)
            for relation_id in requested_relations:
                relation = conn.execute(
                    "SELECT * FROM memory_relations WHERE relation_id = ?", (relation_id,)
                ).fetchone()
                if relation is None or not self._relation_visible(conn, principal, relation):
                    continue
                for item in self._relation_source_rows(conn, relation_id):
                    key = _source_ref_key(item)
                    stored = refs.setdefault(key, {**item, "relationIds": [], "ownerScopes": []})
                    relation_list = stored["relationIds"]
                    if isinstance(relation_list, list) and relation_id not in relation_list:
                        relation_list.append(relation_id)
                    scopes = stored["ownerScopes"]
                    scope = {
                        "ownerKind": str(relation["owner_kind"]),
                        "ownerId": str(relation["owner_id"]),
                    }
                    if isinstance(scopes, list) and scope not in scopes:
                        scopes.append(scope)
            if requested_refs:
                allowed = {_source_ref_key(item) for item in requested_refs}
                refs = {key: item for key, item in refs.items() if key in allowed}

            sources: list[dict[str, object]] = []
            for item in refs.values():
                payload = self._rehydrate_source(conn, principal, item)
                if payload is None:
                    continue
                payload["relationIds"] = list(item.get("relationIds") or [])
                sources.append(payload)
                if len(sources) >= bounded_limit:
                    break
        return {"schemaVersion": "rag-ime.memory-graph-sources.v1", "sources": sources, "items": sources, "count": len(sources)}

    def restore_entity(
        self,
        *,
        entity_id: str,
        snapshot: Mapping[str, object] | None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        entity_id = _required(entity_id, field="entity_id", maximum=240)
        with self._maybe_connection(conn) as active:
            current = active.execute(
                "SELECT * FROM memory_entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if current is None:
                return {"operation": "unchanged", "entity": None, "outboxEventId": None}
            if snapshot:
                active.execute("DELETE FROM memory_entity_aliases WHERE entity_id = ?", (entity_id,))
                active.execute("DELETE FROM memory_entity_sources WHERE entity_id = ?", (entity_id,))
                return self.upsert_entity(
                    entity_id=entity_id,
                    entity_type=str(snapshot.get("entityType") or "concept"),
                    name=str(snapshot.get("canonicalName") or ""),
                    aliases=[str(item) for item in snapshot.get("aliases") or []],
                    sources=[dict(item) for item in snapshot.get("sources") or [] if isinstance(item, Mapping)],
                    description=str(snapshot.get("description") or ""),
                    owner_kind=str(snapshot.get("ownerKind") or "user"),
                    owner_id=str(snapshot.get("ownerId") or "local-user"),
                    project=str(snapshot.get("project") or ""),
                    status=str(snapshot.get("status") or "active"),
                    confidence=float(snapshot.get("confidence") or 0.5),
                    metadata=_mapping(snapshot.get("metadata")),
                    expected_revision=int(current["revision"]),
                    conn=active,
                )
            if str(current["status"]) == "tombstoned":
                return {"operation": "unchanged", "entity": self._entity_payload(active, current), "outboxEventId": None}
            revision = int(current["revision"]) + 1
            timestamp = _timestamp(None)
            cursor = active.execute(
                """
                UPDATE memory_entities
                SET status = 'tombstoned', revision = ?, updated_at_ms = ?
                WHERE entity_id = ? AND revision = ?
                """,
                (revision, timestamp, entity_id, int(current["revision"])),
            )
            if cursor.rowcount != 1:
                raise ValueError("memory entity revision conflict")
            row = active.execute("SELECT * FROM memory_entities WHERE entity_id = ?", (entity_id,)).fetchone()
            payload = self._entity_payload(active, row)
            outbox_id = self.enqueue_projection(
                aggregate_type="entity", aggregate_id=entity_id, operation="delete",
                revision=revision, payload=payload, updated_at_ms=timestamp, conn=active,
            )
            return {"operation": "tombstoned", "entity": payload, "outboxEventId": outbox_id, "outboxOperation": "delete"}

    def restore_relation(
        self,
        *,
        relation_id: str,
        snapshot: Mapping[str, object] | None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        relation_id = _required(relation_id, field="relation_id", maximum=240)
        with self._maybe_connection(conn) as active:
            current = active.execute(
                "SELECT * FROM memory_relations WHERE relation_id = ?", (relation_id,)
            ).fetchone()
            if current is None:
                return {"operation": "unchanged", "relation": None, "outboxEventId": None}
            if snapshot:
                active.execute("DELETE FROM memory_relation_sources WHERE relation_id = ?", (relation_id,))
                return self.upsert_relation(
                    relation_id=relation_id,
                    source_entity_id=str(snapshot.get("sourceEntityId") or ""),
                    target_entity_id=str(snapshot.get("targetEntityId") or ""),
                    relation_type=str(snapshot.get("relationType") or "related_to"),
                    fact=str(snapshot.get("fact") or ""),
                    idempotency_key=str(snapshot.get("idempotencyKey") or relation_id),
                    sources=[dict(item) for item in snapshot.get("sources") or [] if isinstance(item, Mapping)],
                    owner_kind=str(snapshot.get("ownerKind") or "user"),
                    owner_id=str(snapshot.get("ownerId") or "local-user"),
                    project=str(snapshot.get("project") or ""),
                    valid_from_ms=int(snapshot.get("validFromMs") or 0),
                    valid_to_ms=_optional_int(snapshot.get("validToMs")),
                    status=str(snapshot.get("status") or "active"),
                    confidence=float(snapshot.get("confidence") or 0.5),
                    metadata=_mapping(snapshot.get("metadata")),
                    expected_revision=int(current["revision"]),
                    conn=active,
                )
            if str(current["status"]) == "tombstoned":
                return {"operation": "unchanged", "relation": self._relation_payload(active, current), "outboxEventId": None}
            revision = int(current["revision"]) + 1
            timestamp = _timestamp(None)
            cursor = active.execute(
                """
                UPDATE memory_relations
                SET status = 'tombstoned', revision = ?, updated_at_ms = ?
                WHERE relation_id = ? AND revision = ?
                """,
                (revision, timestamp, relation_id, int(current["revision"])),
            )
            if cursor.rowcount != 1:
                raise ValueError("memory relation revision conflict")
            row = active.execute("SELECT * FROM memory_relations WHERE relation_id = ?", (relation_id,)).fetchone()
            payload = self._relation_payload(active, row)
            outbox_id = self.enqueue_projection(
                aggregate_type="relation", aggregate_id=relation_id, operation="delete",
                revision=revision, payload=payload, updated_at_ms=timestamp, conn=active,
            )
            return {"operation": "tombstoned", "relation": payload, "outboxEventId": outbox_id, "outboxOperation": "delete"}

    def _assert_source_writable(
        self,
        conn: sqlite3.Connection,
        source_ref: Mapping[str, object],
        *,
        owner_kind: str,
        owner_id: str,
        project: str,
    ) -> None:
        source_type = _canonical_source_type(source_ref.get("sourceType"))
        source_id = _required(source_ref.get("sourceId"), field="source_id", maximum=240)
        event_ids: list[int] = []
        source_project = ""
        if source_type == "input_event":
            event_id = _positive_int(source_id, field="input_event source_id")
            row = conn.execute(
                """
                SELECT e.project, e.source, e.committed_text, e.recent_context,
                       COALESCE(ms.deleted, 0) AS deleted
                FROM input_events AS e
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                raise ValueError("memory relation source input_event does not exist")
            if int(row["deleted"] or 0):
                raise PermissionError("deleted input_event cannot become graph provenance")
            if looks_sensitive(f"{row['committed_text']} {row['recent_context']}"):
                raise PermissionError("sensitive input_event cannot become graph provenance")
            source_project = str(row["project"] or "")
            event_ids = [event_id]
        elif source_type == "agent_memory_source":
            row = conn.execute(
                """
                SELECT ams.input_event_id, ams.session_id, e.project,
                       e.committed_text, e.recent_context, COALESCE(ms.deleted, 0) AS deleted
                FROM agent_memory_sources AS ams
                JOIN input_events AS e ON e.id = ams.input_event_id
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE ams.source_id = ? AND ams.status = 'active'
                """,
                (source_id,),
            ).fetchone()
            if row is None:
                raise ValueError("agent memory relation source does not exist")
            if int(row["deleted"] or 0):
                raise PermissionError("deleted Agent source cannot become graph provenance")
            if looks_sensitive(f"{row['committed_text']} {row['recent_context']}"):
                raise PermissionError("sensitive Agent source cannot become graph provenance")
            source_project = str(row["project"] or "")
            event_ids = [int(row["input_event_id"])]
        elif source_type == "atom":
            row = conn.execute(
                "SELECT source_event_ids_json, scope_project, privacy_level FROM memory_atoms WHERE id = ? AND status IN ('active', 'approved')",
                (source_id,),
            ).fetchone()
            if row is None or str(row["privacy_level"] or "") == "sensitive":
                raise ValueError("memory atom relation source is unavailable")
            source_project = str(row["scope_project"] or "")
            event_ids = _json_ints(row["source_event_ids_json"])
        elif source_type in {"item", "phrase"}:
            row = conn.execute(
                "SELECT source_event_id, project, privacy_class FROM memory_items WHERE memory_id = ? AND status IN ('active', 'approved')",
                (source_id,),
            ).fetchone()
            if row is None or str(row["privacy_class"] or "") == "sensitive":
                raise ValueError("memory item relation source is unavailable")
            source_project = str(row["project"] or "")
            if int(row["source_event_id"] or 0) > 0:
                event_ids = [int(row["source_event_id"])]
        elif source_type == "book":
            row = conn.execute(
                "SELECT source_event_ids_json, project FROM memory_books WHERE book_id = ? AND status IN ('active', 'approved', 'archived')",
                (source_id,),
            ).fetchone()
            if row is None:
                raise ValueError("memory book relation source is unavailable")
            source_project = str(row["project"] or "")
            event_ids = _json_ints(row["source_event_ids_json"])
        else:
            raise ValueError(f"unsupported memory relation source type: {source_type}")
        if source_project and source_project != project:
            raise PermissionError("memory relation source belongs to another project")
        for event_id in event_ids:
            event = conn.execute(
                """
                SELECT e.source, e.committed_text, e.recent_context,
                       COALESCE(ms.deleted, 0) AS deleted
                FROM input_events AS e
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if event is None or int(event["deleted"] or 0):
                raise PermissionError("deleted graph provenance is unavailable")
            if looks_sensitive(f"{event['committed_text']} {event['recent_context']}"):
                raise PermissionError("sensitive graph provenance is unavailable")
            links = conn.execute(
                """
                SELECT ams.session_id, ams.source_role, ams.status, s.agent_id
                FROM agent_memory_sources AS ams
                JOIN agent_sessions AS s ON s.id = ams.session_id
                WHERE ams.input_event_id = ?
                """,
                (event_id,),
            ).fetchall()
            if not links and str(event["source"] or "") == "pi_agent_tool_receipt":
                raise PermissionError("orphaned Agent tool source cannot become graph provenance")
            if any(str(link["status"]) != "active" for link in links):
                raise PermissionError("inactive Agent source cannot become graph provenance")
            for link in links:
                if str(link["source_role"]) == "user" and owner_kind == "user" and owner_id == "local-user":
                    continue
                if not self._owner_can_use_agent_source(
                    conn,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    session_id=str(link["session_id"]),
                    agent_id=str(link["agent_id"]),
                ):
                    raise PermissionError("private Agent source cannot be attached to this relation")

    @staticmethod
    def _bind_source_generations(
        conn: sqlite3.Connection,
        source_refs: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        """Bind provenance to the source generation visible in this transaction."""

        timestamp = _timestamp(None)
        result: list[dict[str, object]] = []
        seen: set[tuple[str, str, int]] = set()
        for source_ref in source_refs:
            source_type = _canonical_source_type(source_ref.get("sourceType"))
            source_id = _required(source_ref.get("sourceId"), field="source_id", maximum=240)
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_source_generations(
                    source_type, source_id, generation, updated_at_ms
                ) VALUES (?, ?, 1, ?)
                """,
                (source_type, source_id, timestamp),
            )
            generation = int(
                conn.execute(
                    """
                    SELECT generation FROM memory_source_generations
                    WHERE source_type = ? AND source_id = ?
                    """,
                    (source_type, source_id),
                ).fetchone()["generation"]
            )
            key = (source_type, source_id, generation)
            if key in seen:
                continue
            seen.add(key)
            bound = dict(source_ref)
            bound["sourceType"] = source_type
            bound["sourceId"] = source_id
            bound["sourceRevision"] = generation
            result.append(bound)
        return result

    @staticmethod
    def _owner_can_use_agent_source(
        conn: sqlite3.Connection,
        *,
        owner_kind: str,
        owner_id: str,
        session_id: str,
        agent_id: str,
    ) -> bool:
        if owner_kind == "session":
            return owner_id == session_id
        if owner_kind == "agent":
            return owner_id == agent_id
        if owner_kind == "room":
            row = conn.execute(
                """
                SELECT 1 FROM agent_room_participants
                WHERE room_id = ? AND session_id = ? AND participant_status = 'active'
                """,
                (owner_id, session_id),
            ).fetchone()
            return row is not None
        return False

    def reconcile_invalid_provenance(
        self,
        principal: MemoryGraphPrincipal | None = None,
    ) -> dict[str, int]:
        """Tombstone graph rows whose canonical evidence is no longer live."""

        with self._maybe_connection(None) as conn:
            return self._reconcile_invalid_provenance_on_conn(conn, principal=principal)

    def drain_dirty_sources(self, *, limit: int = 256) -> dict[str, int]:
        """Apply a bounded batch of source-driven graph invalidations.

        Normal Agent queries call the same incremental path before reading. The
        public entry point lets background projection workers keep delete events
        moving even when no Agent happens to query the affected memory.
        """

        with self._maybe_connection(None) as conn:
            return self._drain_dirty_sources(conn, limit=limit)

    def _drain_dirty_sources(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 256,
    ) -> dict[str, int]:
        """Incrementally invalidate only graph rows touched by changed sources."""

        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        dirty_rows = conn.execute(
            """
            SELECT source_type, source_id, dirty_revision
            FROM memory_graph_source_dirty
            ORDER BY updated_at_ms ASC, source_type ASC, source_id ASC
            LIMIT ?
            """,
            (min(1000, max(1, int(limit))),),
        ).fetchall()
        if not dirty_rows:
            return {"sources": 0, "relations": 0, "entities": 0}

        source_keys = {
            (_canonical_source_type(row["source_type"]), str(row["source_id"]))
            for row in dirty_rows
        }
        input_event_ids = [
            int(source_id)
            for source_type, source_id in source_keys
            if source_type == "input_event" and source_id.isdigit() and int(source_id) > 0
        ]
        if input_event_ids:
            event_ids_json = json.dumps(sorted(set(input_event_ids)))
            source_keys.update(
                (
                    _canonical_source_type(row["source_type"]),
                    str(row["source_id"]),
                )
                for row in conn.execute(
                    """
                    SELECT DISTINCT links.source_type, links.source_id
                    FROM memory_source_event_links AS links
                    JOIN json_each(?) AS wanted
                      ON CAST(wanted.value AS INTEGER) = links.event_id
                    """,
                    (event_ids_json,),
                ).fetchall()
            )

        source_key_payload = json.dumps(
            [{"type": source_type, "id": source_id} for source_type, source_id in sorted(source_keys)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        generation_rows = conn.execute(
            """
            SELECT json_extract(source.value, '$.type') AS source_type,
                   json_extract(source.value, '$.id') AS source_id,
                   COALESCE(g.generation, 1) AS generation
            FROM json_each(?) AS source
            LEFT JOIN memory_source_generations AS g
              ON g.source_type = json_extract(source.value, '$.type')
             AND g.source_id = json_extract(source.value, '$.id')
            """,
            (source_key_payload,),
        ).fetchall()
        key_payload = json.dumps(
            [
                {
                    "type": str(row["source_type"]),
                    "id": str(row["source_id"]),
                    "generation": int(row["generation"]),
                }
                for row in generation_rows
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        relation_rows = conn.execute(
            """
            WITH dirty AS (
                SELECT json_extract(value, '$.type') AS source_type,
                       json_extract(value, '$.id') AS source_id,
                       CAST(json_extract(value, '$.generation') AS INTEGER) AS generation
                FROM json_each(?)
            )
            SELECT DISTINCT r.*
            FROM memory_relation_sources AS rs
            JOIN dirty AS d
              ON d.source_type = rs.source_type AND d.source_id = rs.source_id
             AND rs.source_revision < d.generation
            JOIN memory_relations AS r ON r.relation_id = rs.relation_id
            WHERE r.status = 'active'
            """,
            (key_payload,),
        ).fetchall()
        entity_rows = conn.execute(
            """
            WITH dirty AS (
                SELECT json_extract(value, '$.type') AS source_type,
                       json_extract(value, '$.id') AS source_id,
                       CAST(json_extract(value, '$.generation') AS INTEGER) AS generation
                FROM json_each(?)
            )
            SELECT DISTINCT e.*
            FROM memory_entity_sources AS es
            JOIN dirty AS d
              ON d.source_type = es.source_type AND d.source_id = es.source_id
             AND es.source_revision < d.generation
            JOIN memory_entities AS e ON e.entity_id = es.entity_id
            WHERE e.status = 'active'
            """,
            (key_payload,),
        ).fetchall()

        # A dirty source is no longer valid evidence for the graph revision it
        # originally produced, even when the underlying row still exists. Drop
        # only those provenance links; a later compiler pass may re-derive and
        # attach the corrected source again.
        conn.execute(
            """
            DELETE FROM memory_relation_sources
            WHERE EXISTS (
                SELECT 1
                FROM json_each(?) AS dirty
                WHERE json_extract(dirty.value, '$.type') = memory_relation_sources.source_type
                  AND json_extract(dirty.value, '$.id') = memory_relation_sources.source_id
                  AND memory_relation_sources.source_revision
                      < CAST(json_extract(dirty.value, '$.generation') AS INTEGER)
            )
            """,
            (key_payload,),
        )
        conn.execute(
            """
            DELETE FROM memory_entity_sources
            WHERE EXISTS (
                SELECT 1
                FROM json_each(?) AS dirty
                WHERE json_extract(dirty.value, '$.type') = memory_entity_sources.source_type
                  AND json_extract(dirty.value, '$.id') = memory_entity_sources.source_id
                  AND memory_entity_sources.source_revision
                      < CAST(json_extract(dirty.value, '$.generation') AS INTEGER)
            )
            """,
            (key_payload,),
        )

        affected_entity_ids: set[str] = set()
        revised_relations = 0
        for relation in relation_rows:
            affected_entity_ids.update(
                (str(relation["source_entity_id"]), str(relation["target_entity_id"]))
            )
            if self._relation_has_live_source(conn, relation):
                revised_relations += int(
                    self._refresh_active_relation_projection(conn, relation)
                )
            else:
                revised_relations += int(
                    self._tombstone_unprovenanced_relation(conn, relation)
                )

        directly_affected_entity_ids = {str(row["entity_id"]) for row in entity_rows}
        affected_entity_ids.update(directly_affected_entity_ids)
        revised_entities = 0
        for entity_id in sorted(affected_entity_ids):
            entity = conn.execute(
                "SELECT * FROM memory_entities WHERE entity_id = ? AND status = 'active'",
                (entity_id,),
            ).fetchone()
            if entity is None:
                continue
            if self._entity_has_live_provenance(conn, entity):
                if entity_id in directly_affected_entity_ids:
                    revised_entities += int(
                        self._refresh_active_entity_projection(conn, entity)
                    )
            else:
                revised_entities += int(
                    self._tombstone_unprovenanced_entity(conn, entity)
                )

        conn.executemany(
            """
            DELETE FROM memory_graph_source_dirty
            WHERE source_type = ? AND source_id = ? AND dirty_revision = ?
            """,
            (
                (str(row["source_type"]), str(row["source_id"]), int(row["dirty_revision"]))
                for row in dirty_rows
            ),
        )
        return {
            "sources": len(dirty_rows),
            "relations": revised_relations,
            "entities": revised_entities,
        }

    def _reconcile_invalid_provenance_on_conn(
        self,
        conn: sqlite3.Connection,
        *,
        principal: MemoryGraphPrincipal | None,
    ) -> dict[str, int]:
        relation_sql = "SELECT * FROM memory_relations WHERE status = 'active'"
        entity_sql = "SELECT * FROM memory_entities WHERE status = 'active'"
        relation_params: tuple[object, ...] = ()
        entity_params: tuple[object, ...] = ()
        if principal is not None:
            relation_visibility, relation_params = _visibility_sql(
                principal,
                alias="memory_relations",
            )
            entity_visibility, entity_params = _visibility_sql(
                principal,
                alias="memory_entities",
            )
            relation_sql += f" AND {relation_visibility}"
            entity_sql += f" AND {entity_visibility}"

        tombstoned_relations = 0
        for row in conn.execute(relation_sql, relation_params).fetchall():
            if self._relation_has_live_source(conn, row):
                continue
            tombstoned_relations += int(self._tombstone_unprovenanced_relation(conn, row))

        tombstoned_entities = 0
        for row in conn.execute(entity_sql, entity_params).fetchall():
            if self._entity_has_live_provenance(conn, row):
                continue
            tombstoned_entities += int(self._tombstone_unprovenanced_entity(conn, row))
        return {"relations": tombstoned_relations, "entities": tombstoned_entities}

    def _source_ref_is_live(
        self,
        conn: sqlite3.Connection,
        source_ref: Mapping[str, object],
        *,
        owner_kind: str,
        owner_id: str,
        project: str,
    ) -> bool:
        source_type = _canonical_source_type(source_ref.get("sourceType"))
        source_id = compact_whitespace(str(source_ref.get("sourceId") or ""))[:240]
        generation = conn.execute(
            """
            SELECT generation FROM memory_source_generations
            WHERE source_type = ? AND source_id = ?
            """,
            (source_type, source_id),
        ).fetchone()
        if generation is not None and int(source_ref.get("sourceRevision") or 1) != int(
            generation["generation"]
        ):
            return False
        try:
            self._assert_source_writable(
                conn,
                source_ref,
                owner_kind=owner_kind,
                owner_id=owner_id,
                project=project,
            )
        except (PermissionError, TypeError, ValueError):
            return False
        return True

    def _relation_has_live_source(self, conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
        return any(
            self._source_ref_is_live(
                conn,
                source_ref,
                owner_kind=str(row["owner_kind"]),
                owner_id=str(row["owner_id"]),
                project=str(row["project"]),
            )
            for source_ref in self._relation_source_rows(conn, str(row["relation_id"]))
        )

    def _entity_has_live_provenance(self, conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
        owner_kind = str(row["owner_kind"])
        owner_id = str(row["owner_id"])
        project = str(row["project"])
        if any(
            self._source_ref_is_live(
                conn,
                source_ref,
                owner_kind=owner_kind,
                owner_id=owner_id,
                project=project,
            )
            for source_ref in self._entity_source_rows(conn, str(row["entity_id"]))
        ):
            return True
        relation_rows = conn.execute(
            """
            SELECT * FROM memory_relations
            WHERE status = 'active'
              AND owner_kind = ? AND owner_id = ? AND project = ?
              AND (source_entity_id = ? OR target_entity_id = ?)
            """,
            (owner_kind, owner_id, project, str(row["entity_id"]), str(row["entity_id"])),
        ).fetchall()
        return any(self._relation_has_live_source(conn, relation) for relation in relation_rows)

    def _tombstone_unprovenanced_relation(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        revision = int(row["revision"]) + 1
        timestamp = _timestamp(None)
        cursor = conn.execute(
            """
            UPDATE memory_relations
            SET status = 'tombstoned', revision = ?, updated_at_ms = ?
            WHERE relation_id = ? AND status = 'active' AND revision = ?
            """,
            (revision, timestamp, str(row["relation_id"]), int(row["revision"])),
        )
        if cursor.rowcount != 1:
            return False
        current = conn.execute(
            "SELECT * FROM memory_relations WHERE relation_id = ?",
            (str(row["relation_id"]),),
        ).fetchone()
        payload = self._relation_payload(conn, current)
        self.enqueue_projection(
            aggregate_type="relation",
            aggregate_id=str(row["relation_id"]),
            operation="delete",
            revision=revision,
            payload=payload,
            updated_at_ms=timestamp,
            conn=conn,
        )
        return True

    def _refresh_active_relation_projection(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        """Publish a new revision after one of several provenance links changed."""

        revision = int(row["revision"]) + 1
        timestamp = _timestamp(None)
        cursor = conn.execute(
            """
            UPDATE memory_relations
            SET revision = ?, updated_at_ms = ?
            WHERE relation_id = ? AND status = 'active' AND revision = ?
            """,
            (revision, timestamp, str(row["relation_id"]), int(row["revision"])),
        )
        if cursor.rowcount != 1:
            return False
        current = conn.execute(
            "SELECT * FROM memory_relations WHERE relation_id = ?",
            (str(row["relation_id"]),),
        ).fetchone()
        self.enqueue_projection(
            aggregate_type="relation",
            aggregate_id=str(row["relation_id"]),
            operation="upsert",
            revision=revision,
            payload=self._relation_payload(conn, current),
            updated_at_ms=timestamp,
            conn=conn,
        )
        return True

    def _tombstone_unprovenanced_entity(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        revision = int(row["revision"]) + 1
        timestamp = _timestamp(None)
        cursor = conn.execute(
            """
            UPDATE memory_entities
            SET status = 'tombstoned', revision = ?, updated_at_ms = ?
            WHERE entity_id = ? AND status = 'active' AND revision = ?
            """,
            (revision, timestamp, str(row["entity_id"]), int(row["revision"])),
        )
        if cursor.rowcount != 1:
            return False
        current = conn.execute(
            "SELECT * FROM memory_entities WHERE entity_id = ?",
            (str(row["entity_id"]),),
        ).fetchone()
        payload = self._entity_payload(conn, current)
        self.enqueue_projection(
            aggregate_type="entity",
            aggregate_id=str(row["entity_id"]),
            operation="delete",
            revision=revision,
            payload=payload,
            updated_at_ms=timestamp,
            conn=conn,
        )
        return True

    def _refresh_active_entity_projection(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        revision = int(row["revision"]) + 1
        timestamp = _timestamp(None)
        cursor = conn.execute(
            """
            UPDATE memory_entities
            SET revision = ?, updated_at_ms = ?
            WHERE entity_id = ? AND status = 'active' AND revision = ?
            """,
            (revision, timestamp, str(row["entity_id"]), int(row["revision"])),
        )
        if cursor.rowcount != 1:
            return False
        current = conn.execute(
            "SELECT * FROM memory_entities WHERE entity_id = ?",
            (str(row["entity_id"]),),
        ).fetchone()
        self.enqueue_projection(
            aggregate_type="entity",
            aggregate_id=str(row["entity_id"]),
            operation="upsert",
            revision=revision,
            payload=self._entity_payload(conn, current),
            updated_at_ms=timestamp,
            conn=conn,
        )
        return True

    def _entity_visible(
        self,
        conn: sqlite3.Connection,
        principal: MemoryGraphPrincipal,
        row: sqlite3.Row,
    ) -> bool:
        if str(row["status"]) != "active" or not principal.can_read(
            owner_kind=str(row["owner_kind"]),
            owner_id=str(row["owner_id"]),
            project=str(row["project"]),
        ):
            return False
        if self._entity_has_live_provenance(conn, row):
            return True
        self._tombstone_unprovenanced_entity(conn, row)
        return False

    def _relation_visible(
        self,
        conn: sqlite3.Connection,
        principal: MemoryGraphPrincipal,
        row: sqlite3.Row,
        *,
        as_of_ms: int | None = None,
    ) -> bool:
        if str(row["status"]) != "active" or not principal.can_read(
            owner_kind=str(row["owner_kind"]),
            owner_id=str(row["owner_id"]),
            project=str(row["project"]),
        ):
            return False
        if not self._relation_has_live_source(conn, row):
            self._tombstone_unprovenanced_relation(conn, row)
            return False
        if as_of_ms is None:
            return True
        return int(row["valid_from_ms"]) <= as_of_ms and (
            row["valid_to_ms"] is None or int(row["valid_to_ms"]) > as_of_ms
        )

    def _entity_payload(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
        aliases = [
            str(item["alias"])
            for item in conn.execute(
                "SELECT alias FROM memory_entity_aliases WHERE entity_id = ? ORDER BY weight DESC, alias ASC",
                (str(row["entity_id"]),),
            ).fetchall()
        ]
        return {
            "entityId": str(row["entity_id"]),
            "entityType": str(row["entity_type"]),
            "canonicalName": str(row["canonical_name"]),
            "description": str(row["description"] or ""),
            "aliases": aliases,
            "ownerKind": str(row["owner_kind"]),
            "ownerId": str(row["owner_id"]),
            "project": str(row["project"]),
            "status": str(row["status"]),
            "revision": int(row["revision"]),
            "confidence": float(row["confidence"]),
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
            "metadata": _json_mapping(row["metadata_json"]),
            "sources": [
                {
                    "sourceType": item["sourceType"],
                    "sourceId": item["sourceId"],
                    "sourceRevision": item["sourceRevision"],
                }
                for item in self._entity_source_rows(conn, str(row["entity_id"]))
                if self._source_ref_is_live(
                    conn,
                    item,
                    owner_kind=str(row["owner_kind"]),
                    owner_id=str(row["owner_id"]),
                    project=str(row["project"]),
                )
            ],
        }

    def _entity_snapshot(self, conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        payload = self._entity_payload(conn, row)
        payload["sources"] = self._entity_source_rows(conn, str(row["entity_id"]))
        return payload

    def _relation_payload(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
        return {
            "relationId": str(row["relation_id"]),
            "sourceEntityId": str(row["source_entity_id"]),
            "targetEntityId": str(row["target_entity_id"]),
            "relationType": str(row["relation_type"]),
            "fact": str(row["fact"]),
            "ownerKind": str(row["owner_kind"]),
            "ownerId": str(row["owner_id"]),
            "project": str(row["project"]),
            "validFromMs": int(row["valid_from_ms"]),
            "validToMs": None if row["valid_to_ms"] is None else int(row["valid_to_ms"]),
            "status": str(row["status"]),
            "revision": int(row["revision"]),
            "idempotencyKey": str(row["idempotency_key"]),
            "confidence": float(row["confidence"]),
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
            "metadata": _json_mapping(row["metadata_json"]),
            "sources": [
                {
                    "sourceType": item["sourceType"],
                    "sourceId": item["sourceId"],
                    "sourceRevision": item["sourceRevision"],
                }
                for item in self._relation_source_rows(conn, str(row["relation_id"]))
                if self._source_ref_is_live(
                    conn,
                    item,
                    owner_kind=str(row["owner_kind"]),
                    owner_id=str(row["owner_id"]),
                    project=str(row["project"]),
                )
            ],
        }

    def _relation_snapshot(self, conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        payload = self._relation_payload(conn, row)
        payload["sources"] = self._relation_source_rows(conn, str(row["relation_id"]))
        return payload

    @staticmethod
    def _entity_source_rows(conn: sqlite3.Connection, entity_id: str) -> list[dict[str, object]]:
        return [
            {
                "sourceType": str(row["source_type"]),
                "sourceId": str(row["source_id"]),
                "sourceRevision": int(row["source_revision"]),
                "evidenceText": str(row["evidence_text"] or ""),
                "evidence": _json_mapping(row["evidence_json"]),
                "createdAtMs": int(row["created_at_ms"]),
            }
            for row in conn.execute(
                """
                SELECT source_type, source_id, source_revision, evidence_text, evidence_json, created_at_ms
                FROM memory_entity_sources WHERE entity_id = ?
                ORDER BY created_at_ms ASC, source_type ASC, source_id ASC
                """,
                (entity_id,),
            ).fetchall()
        ]

    @staticmethod
    def _relation_source_rows(conn: sqlite3.Connection, relation_id: str) -> list[dict[str, object]]:
        return [
            {
                "sourceType": str(row["source_type"]),
                "sourceId": str(row["source_id"]),
                "sourceRevision": int(row["source_revision"]),
                "evidenceText": str(row["evidence_text"] or ""),
                "evidence": _json_mapping(row["evidence_json"]),
                "createdAtMs": int(row["created_at_ms"]),
            }
            for row in conn.execute(
                """
                SELECT source_type, source_id, source_revision, evidence_text, evidence_json, created_at_ms
                FROM memory_relation_sources WHERE relation_id = ?
                ORDER BY created_at_ms ASC, source_type ASC, source_id ASC
                """,
                (relation_id,),
            ).fetchall()
        ]

    def _rehydrate_source(
        self,
        conn: sqlite3.Connection,
        principal: MemoryGraphPrincipal,
        source_ref: Mapping[str, object],
    ) -> dict[str, object] | None:
        source_type = _canonical_source_type(source_ref.get("sourceType"))
        source_id = compact_whitespace(str(source_ref.get("sourceId") or ""))[:240]
        revision = max(1, int(source_ref.get("sourceRevision") or 1))
        if not source_id:
            return None
        if source_type == "input_event":
            try:
                event_id = int(source_id)
            except ValueError:
                return None
            row = conn.execute(
                """
                SELECT e.id, e.committed_text, e.recent_context, e.project, e.app, e.source,
                       e.context_group_id, e.created_at_ms, COALESCE(ms.deleted, 0) AS deleted
                FROM input_events AS e
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if (
                row is None
                or int(row["deleted"] or 0)
                or looks_sensitive(f"{row['committed_text']} {row['recent_context']}")
                or not self._source_project_visible(principal, str(row["project"] or ""))
            ):
                return None
            if not self._agent_event_visible(
                conn, principal, event_id, owner_scopes=source_ref.get("ownerScopes")
            ):
                return None
            return _source_payload(
                source_type, source_id, revision, text=str(row["committed_text"] or ""),
                created_at_ms=int(row["created_at_ms"]), project=str(row["project"] or ""),
                app=str(row["app"] or ""), metadata={"source": str(row["source"] or ""), "contextGroupId": str(row["context_group_id"] or "")},
            )
        if source_type == "agent_memory_source":
            row = conn.execute(
                """
                SELECT ams.input_event_id, ams.session_id, ams.source_role, ams.created_at_ms,
                       e.committed_text, e.recent_context, e.project, e.app,
                       COALESCE(ms.deleted, 0) AS deleted
                FROM agent_memory_sources AS ams
                JOIN input_events AS e ON e.id = ams.input_event_id
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE ams.source_id = ? AND ams.status = 'active'
                """,
                (source_id,),
            ).fetchone()
            if (
                row is None
                or int(row["deleted"] or 0)
                or looks_sensitive(f"{row['committed_text']} {row['recent_context']}")
                or not self._source_project_visible(principal, str(row["project"] or ""))
            ):
                return None
            if not self._agent_event_visible(
                conn, principal, int(row["input_event_id"]), owner_scopes=source_ref.get("ownerScopes")
            ):
                return None
            return _source_payload(
                source_type, source_id, revision, text=str(row["committed_text"] or ""),
                created_at_ms=int(row["created_at_ms"]), project=str(row["project"] or ""),
                app=str(row["app"] or ""), metadata={"sourceRole": str(row["source_role"] or "")},
            )
        if source_type == "atom":
            row = conn.execute(
                """
                SELECT id, text, canonical_text, source_event_ids_json, scope_project, scope_app,
                       created_at_ms, kind, privacy_level
                FROM memory_atoms WHERE id = ? AND status IN ('active', 'approved')
                """,
                (source_id,),
            ).fetchone()
            if row is None or str(row["privacy_level"] or "") == "sensitive" or not self._source_project_visible(principal, str(row["scope_project"] or "")):
                return None
            if not self._events_visible(
                conn, principal, _json_ints(row["source_event_ids_json"]), owner_scopes=source_ref.get("ownerScopes")
            ):
                return None
            return _source_payload(
                source_type, source_id, revision, text=str(row["canonical_text"] or row["text"] or ""),
                created_at_ms=int(row["created_at_ms"]), project=str(row["scope_project"] or ""),
                app=str(row["scope_app"] or ""), metadata={"kind": str(row["kind"] or "")},
            )
        if source_type in {"item", "phrase"}:
            row = conn.execute(
                """
                SELECT memory_id, text, summary, source_event_id, project, app, created_at_ms, kind, privacy_class
                FROM memory_items WHERE memory_id = ? AND status IN ('active', 'approved')
                """,
                (source_id,),
            ).fetchone()
            event_ids = [] if row is None or int(row["source_event_id"] or 0) <= 0 else [int(row["source_event_id"])]
            if row is None or str(row["privacy_class"] or "") == "sensitive" or not self._source_project_visible(principal, str(row["project"] or "")) or not self._events_visible(conn, principal, event_ids, owner_scopes=source_ref.get("ownerScopes")):
                return None
            return _source_payload(
                source_type, source_id, revision, text=str(row["text"] or ""),
                created_at_ms=int(row["created_at_ms"]), project=str(row["project"] or ""),
                app=str(row["app"] or ""), metadata={"kind": str(row["kind"] or ""), "summary": str(row["summary"] or "")[:500]},
            )
        if source_type == "book":
            row = conn.execute(
                """
                SELECT book_id, title, summary, source_event_ids_json, project, app,
                       created_at_ms, book_type, book_key
                FROM memory_books WHERE book_id = ? AND status IN ('active', 'approved', 'archived')
                """,
                (source_id,),
            ).fetchone()
            if row is None or not self._source_project_visible(principal, str(row["project"] or "")) or not self._events_visible(conn, principal, _json_ints(row["source_event_ids_json"]), owner_scopes=source_ref.get("ownerScopes")):
                return None
            return _source_payload(
                source_type, source_id, revision, text=compact_whitespace(f"{row['title']} {row['summary']}"),
                created_at_ms=int(row["created_at_ms"]), project=str(row["project"] or ""),
                app=str(row["app"] or ""), metadata={"bookType": str(row["book_type"] or ""), "bookKey": str(row["book_key"] or "")},
            )
        return None

    @staticmethod
    def _source_project_visible(principal: MemoryGraphPrincipal, project: str) -> bool:
        return not project or project == principal.project

    def _events_visible(
        self,
        conn: sqlite3.Connection,
        principal: MemoryGraphPrincipal,
        event_ids: Sequence[int],
        *,
        owner_scopes: object = None,
    ) -> bool:
        for event_id in event_ids:
            row = conn.execute(
                """
                SELECT e.committed_text, e.recent_context, e.project,
                       COALESCE(ms.deleted, 0) AS deleted
                FROM input_events AS e
                LEFT JOIN memory_state AS ms ON ms.event_id = e.id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if (
                row is None
                or int(row["deleted"] or 0)
                or looks_sensitive(f"{row['committed_text']} {row['recent_context']}")
                or not self._source_project_visible(principal, str(row["project"] or ""))
                or not self._agent_event_visible(conn, principal, event_id, owner_scopes=owner_scopes)
            ):
                return False
        return True

    @staticmethod
    def _agent_event_visible(
        conn: sqlite3.Connection,
        principal: MemoryGraphPrincipal,
        event_id: int,
        *,
        owner_scopes: object = None,
    ) -> bool:
        links = conn.execute(
            """
            SELECT ams.session_id, ams.source_role, ams.status, s.agent_id
            FROM agent_memory_sources AS ams
            JOIN agent_sessions AS s ON s.id = ams.session_id
            WHERE ams.input_event_id = ?
            """,
            (event_id,),
        ).fetchall()
        if not links:
            event = conn.execute(
                "SELECT source FROM input_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            return event is not None and str(event["source"] or "") != "pi_agent_tool_receipt"
        if any(str(row["status"]) != "active" for row in links):
            return False
        for row in links:
            if str(row["source_role"]) == "user":
                return True
            if principal.session_id and principal.session_id == str(row["session_id"]):
                return True
            if principal.agent_id and principal.agent_id == str(row["agent_id"]):
                return True
            for scope in owner_scopes if isinstance(owner_scopes, list) else []:
                if not isinstance(scope, Mapping) or str(scope.get("ownerKind")) != "room":
                    continue
                room_id = str(scope.get("ownerId") or "")
                if room_id not in principal.room_ids:
                    continue
                member = conn.execute(
                    """
                    SELECT 1 FROM agent_room_participants
                    WHERE session_id = ? AND room_id = ? AND participant_status = 'active'
                    LIMIT 1
                    """,
                    (str(row["session_id"]), room_id),
                ).fetchone()
                if member is not None:
                    return True
        return False

    @contextmanager
    def _maybe_connection(self, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        if conn is not None:
            yield conn
            return
        owned = self._connect()
        try:
            with owned:
                yield owned
        finally:
            owned.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _required(value: object, *, field: str, maximum: int) -> str:
    normalized = compact_whitespace(str(value or ""))[:maximum]
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _graph_type(value: object, *, field: str) -> str:
    normalized = compact_whitespace(str(value or "")).lower()
    if not _TYPE_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a lowercase graph type")
    return normalized


def _scope(owner_kind: object, owner_id: object, project: object) -> tuple[str, str, str]:
    kind = compact_whitespace(str(owner_kind or ""))
    if kind not in _OWNER_KINDS:
        raise ValueError("unsupported memory owner kind")
    identifier = compact_whitespace(str(owner_id or ""))[:240]
    if kind == "user" and not identifier:
        identifier = "local-user"
    if kind in {"agent", "session", "room"} and not identifier:
        raise ValueError(f"{kind} memory owner id is required")
    return kind, identifier, compact_whitespace(str(project or ""))[:160]


def _visibility_sql(
    principal: MemoryGraphPrincipal,
    *,
    alias: str,
) -> tuple[str, tuple[object, ...]]:
    owner_terms = [
        f"{alias}.owner_kind = 'shared'",
        f"({alias}.owner_kind = 'user' AND ({alias}.owner_id = '' OR {alias}.owner_id = ?))",
    ]
    params: list[object] = [principal.project, principal.user_id]
    if principal.agent_id:
        owner_terms.append(f"({alias}.owner_kind = 'agent' AND {alias}.owner_id = ?)")
        params.append(principal.agent_id)
    if principal.session_id:
        owner_terms.append(f"({alias}.owner_kind = 'session' AND {alias}.owner_id = ?)")
        params.append(principal.session_id)
    if principal.room_ids:
        placeholders = ", ".join("?" for _ in principal.room_ids)
        owner_terms.append(f"({alias}.owner_kind = 'room' AND {alias}.owner_id IN ({placeholders}))")
        params.extend(principal.room_ids)
    return (
        f"({alias}.project = '' OR {alias}.project = ?) AND ({' OR '.join(owner_terms)})",
        tuple(params),
    )


def _confidence(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    return min(1.0, max(0.0, parsed))


def _timestamp(value: int | None) -> int:
    if value is None:
        return int(time.time() * 1000)
    return max(0, int(value))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _aliases(values: Sequence[str], *, canonical_name: str) -> list[str]:
    canonical = normalize_text(canonical_name)
    result: list[str] = []
    seen: set[str] = set()
    for raw in list(values)[:40]:
        alias = compact_whitespace(str(raw or ""))[:240]
        normalized = normalize_text(alias)
        if not alias or not normalized or normalized == canonical or normalized in seen:
            continue
        seen.add(normalized)
        result.append(alias)
    return result


def _json_object(value: Mapping[str, object] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_mapping(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _source_evidence(value: object) -> dict[str, object]:
    raw = _mapping(value)
    result: dict[str, object] = {}
    for key in ("observedAtMs", "spanStart", "spanEnd"):
        if key not in raw:
            continue
        try:
            result[key] = max(0, int(raw[key]))
        except (TypeError, ValueError):
            continue
    return result


def _canonical_source_type(value: object) -> str:
    source_type = compact_whitespace(str(value or "")).lower().replace("-", "_")
    aliases = {
        "event": "input_event",
        "inputevent": "input_event",
        "memory_atom": "atom",
        "memory_item": "item",
        "memory_book": "book",
        "agent_source": "agent_memory_source",
    }
    return aliases.get(source_type, source_type)


def _source_refs(
    values: Sequence[Mapping[str, object]],
    *,
    timestamp: int,
    allow_empty: bool = False,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for raw in list(values)[:100]:
        if not isinstance(raw, Mapping):
            continue
        source_type = _required(_canonical_source_type(raw.get("sourceType")), field="source_type", maximum=80)
        source_id = _required(raw.get("sourceId"), field="source_id", maximum=240)
        revision = max(1, int(raw.get("sourceRevision") or 1))
        key = (source_type, source_id, revision)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "sourceType": source_type,
                "sourceId": source_id,
                "sourceRevision": revision,
                # Free-form evidence belongs in the canonical source row, not
                # in a relation payload that is injected or projected.
                "evidenceText": "",
                "evidence": _source_evidence(raw.get("evidence")),
                "createdAtMs": _timestamp(_optional_int(raw.get("createdAtMs"))) if raw.get("createdAtMs") is not None else timestamp,
            }
        )
    if not result and not allow_empty:
        raise ValueError("memory relation requires at least one source")
    return result


def _query_source_refs(values: Sequence[Mapping[str, object]], *, limit: int) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for raw in list(values)[:limit]:
        if not isinstance(raw, Mapping):
            continue
        source_type = _canonical_source_type(raw.get("sourceType"))[:80]
        source_id = compact_whitespace(str(raw.get("sourceId") or ""))[:240]
        try:
            revision = max(1, int(raw.get("sourceRevision") or 1))
        except (TypeError, ValueError):
            revision = 1
        key = (source_type, source_id, revision)
        if not source_type or not source_id or key in seen:
            continue
        seen.add(key)
        result.append({"sourceType": source_type, "sourceId": source_id, "sourceRevision": revision})
    return result


def _source_ref_key(value: Mapping[str, object]) -> tuple[str, str, int]:
    return (
        _canonical_source_type(value.get("sourceType")),
        compact_whitespace(str(value.get("sourceId") or "")),
        max(1, int(value.get("sourceRevision") or 1)),
    )


def _source_ref_signature(value: Mapping[str, object]) -> tuple[str, str]:
    return (
        compact_whitespace(str(value.get("evidenceText") or "")),
        json.dumps(_mapping(value.get("evidence")), ensure_ascii=False, sort_keys=True),
    )


def _ids(values: Sequence[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for raw in list(values)[:limit]:
        value = compact_whitespace(str(raw or ""))[:240]
        if value and value not in result:
            result.append(value)
    return result


def _text_anchor_score(query: str, name: str) -> float:
    if not query or not name:
        return 0.0
    if query == name:
        return 1.5
    if name in query:
        return 1.25
    if query in name:
        return 1.0
    query_terms = {item for item in query.split() if len(item) > 1}
    name_terms = {item for item in name.split() if len(item) > 1}
    overlap = len(query_terms & name_terms)
    return min(0.9, overlap * 0.3)


def _json_ints(value: object) -> list[int]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    result: list[int] = []
    if not isinstance(parsed, list):
        return result
    for raw in parsed[:200]:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _positive_int(value: object, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_payload(
    source_type: str,
    source_id: str,
    source_revision: int,
    *,
    text: str,
    created_at_ms: int,
    project: str,
    app: str,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    return {
        "sourceType": source_type,
        "sourceId": source_id,
        "sourceRevision": source_revision,
        "text": compact_whitespace(text)[:4000],
        "createdAtMs": created_at_ms,
        "project": project,
        "app": app,
        "metadata": dict(metadata),
    }
