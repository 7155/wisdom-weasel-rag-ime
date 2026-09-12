"""Hash-bound source forgetting through the existing governance authorities.

This is LOGICAL Memory erasure, not forensic deletion of immutable audit,
backups, previously exported files, or external provider logs.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from .common import (LifecycleError, digest, identifier, instance_namespace, load_json,
                     now_ms, require_schema, row_dicts, transaction)


def preview_source_forget(conn: sqlite3.Connection, *, project: str, source_id: str) -> dict[str, Any]:
    identifier(project, field="project", allow_empty=True)
    identifier(source_id, field="source_id")
    require_schema(conn)
    with transaction(conn, write=False):
        return _plan(conn, project=project, source_id=source_id)


def _plan(conn: sqlite3.Connection, *, project: str, source_id: str) -> dict[str, Any]:
    roots = row_dicts(conn.execute("""SELECT DISTINCT s.input_event_id FROM agent_memory_sources s
        JOIN input_events event ON event.id=s.input_event_id
        WHERE s.owner_kind='user' AND s.owner_id='default' AND event.project=?
          AND (s.source_id=? OR 'event:'||s.input_event_id=?)""", (project, source_id, source_id)))
    if not roots:
        raise LifecycleError("source_not_found_in_project")
    events = {int(row["input_event_id"]) for row in roots}
    # Only the selected source's events are roots. An Evidence statement may
    # also cite independent source B; forgetting A must NOT erase B itself.
    initial = [row for event in sorted(events) for row in row_dicts(conn.execute("""SELECT e.*
        FROM agent_memory_evidence e JOIN memory_evidence_input_event_links l ON l.evidence_id=e.evidence_id
        WHERE l.input_event_id=? AND l.relation='source' AND e.owner_kind='user' AND e.owner_id='default'""", (event,)))]
    evidence = {e["evidence_id"]: e for e in initial}
    # Shared supporting inputs can feed several canonical Evidence records.
    for event in events:
        for e in row_dicts(conn.execute("""SELECT e.* FROM agent_memory_evidence e
            JOIN memory_evidence_input_event_links l ON l.evidence_id=e.evidence_id AND l.relation='source'
            WHERE l.input_event_id=? AND e.owner_kind='user' AND e.owner_id='default'""", (event,))):
            evidence[e["evidence_id"]] = e
    all_atoms = row_dicts(conn.execute("SELECT * FROM memory_atoms WHERE owner_kind='user' AND owner_id='default'"))
    atoms: dict[str, Any] = {}
    direct = {r[0] for eid in evidence for r in conn.execute("SELECT atom_id FROM memory_lifecycle_atom_evidence_links WHERE evidence_id=?", (eid,))}
    changed = True
    while changed:
        changed = False
        inherited = set(atoms) | {f"atom:{a}" for a in atoms} | {f"event:{e}" for e in events} | {f"raw:event:{e}" for e in events}
        for atom in all_atoms:
            if atom["id"] in atoms:
                continue
            if (atom["id"] in direct or events.intersection(load_json(atom["source_event_ids_json"], list))
                    or inherited.intersection(load_json(atom["source_memory_ids_json"], list))):
                atoms[atom["id"]] = atom
                changed = True
    items = [r for r in row_dicts(conn.execute("SELECT memory_id,source_event_id,updated_at_ms,status FROM memory_items WHERE owner_kind='user' AND owner_id='default'")) if r["source_event_id"] in events]
    books = [r for r in row_dicts(conn.execute("SELECT * FROM memory_books WHERE owner_kind='user' AND owner_id='default'"))
             if events.intersection(load_json(r["source_event_ids_json"], list)) or set(atoms).intersection(load_json(r["memory_atom_ids_json"], list))]
    sources = [r for e in events for r in row_dicts(conn.execute("SELECT source_id,source_revision,canonical_text_sha256 FROM agent_memory_sources WHERE input_event_id=? AND owner_kind='user' AND owner_id='default'", (e,)))]
    relation_ids = set()
    for r in row_dicts(conn.execute("""SELECT rs.relation_id,rs.source_type,rs.source_id FROM memory_relation_sources rs
        JOIN memory_relations r ON r.relation_id=rs.relation_id WHERE r.owner_kind='user' AND r.owner_id='default'""")):
        if (r["source_id"] in set(evidence) | set(atoms) | {s["source_id"] for s in sources}
            or r["source_type"] in {"input_event", "source_event", "source_event_id"} and r["source_id"] in {str(e) for e in events}):
            relation_ids.add(r["relation_id"])
    if len(evidence) + len(atoms) + len(items) + len(books) > 2000:
        raise LifecycleError("forget_plan_too_large")
    plan = {"project": project, "sourceId": source_id, "eventIds": sorted(events),
        "evidenceIds": sorted(evidence), "atomIds": sorted(atoms), "itemIds": sorted(r["memory_id"] for r in items),
        "bookIds": sorted(r["book_id"] for r in books), "relationIds": sorted(relation_ids),
        "sourceIds": sorted(s["source_id"] for s in sources),
        "revisions": {"evidence": [[e["evidence_id"], e["content_sha256"], e["admission_revision"], e["status"]] for e in sorted(evidence.values(), key=lambda x:x["evidence_id"])],
            "atoms": [[a["id"], a["updated_at_ms"], a["status"]] for a in sorted(atoms.values(), key=lambda x:x["id"])],
            "sources": [[s["source_id"], s["source_revision"], s["canonical_text_sha256"]] for s in sorted(sources, key=lambda x:x["source_id"])]},
        "logicalErasureOnly": True, "retainsImmutableAudit": True}
    plan["planDigest"] = digest(plan)
    return plan


def _admission(conn: sqlite3.Connection, evidence_id: str, at: int) -> None:
    from ..memory_evidence_admission import transition_evidence_admission
    transition_evidence_admission(conn, evidence_id, new_state="forgotten", reason_code="source_forgotten",
                                 actor_kind="user", created_at_ms=at)


def _mutation(conn: sqlite3.Connection, kind: str, target: str, at: int) -> None:
    from ..memory_actions import mutate_memory_action
    mutate_memory_action(conn, {"memoryId": target, "itemType": kind, "action": "forget",
                               "reason": "source_forgotten", "updatedBy": "user"}, changed_at_ms=at)


def _rebuild(conn: sqlite3.Connection) -> None:
    from ..retrieval_docs import rebuild_retrieval_docs
    rebuild_retrieval_docs(conn, project="")


def forget_source(conn: sqlite3.Connection, *, project: str, source_id: str, expected_plan_digest: str,
                  cache_invalidator: Callable[[], object] | None = None,
                  admission: Callable[..., None] = _admission, mutation: Callable[..., None] = _mutation,
                  rebuild: Callable[[sqlite3.Connection], None] = _rebuild) -> dict[str, Any]:
    """Preview digest is rechecked under the write lock before any mutation.

    Callback seams are trusted server dependencies, never deserialized input.
    The owning admission API refuses to mutate a source being curated.
    """
    if conn.in_transaction:
        raise LifecycleError("forget_requires_owned_transaction")
    require_schema(conn)
    at = now_ms()
    with transaction(conn):
        plan = _plan(conn, project=project, source_id=source_id)
        if plan["planDigest"] != expected_plan_digest:
            raise LifecycleError("forget_preview_is_stale")
        namespace = instance_namespace(conn)
        for evidence_id in plan["evidenceIds"]:
            admission(conn, evidence_id, at)
            conn.execute("UPDATE agent_memory_evidence SET status='tombstoned' WHERE evidence_id=?", (evidence_id,))
        for event in plan["eventIds"]:
            conn.execute("UPDATE memory_state SET deleted=1,updated_at_ms=? WHERE event_id=?", (at, event))
            if not conn.execute("SELECT 1 FROM memory_tombstones WHERE active=1 AND target_type='source_event_id' AND target_value=?", (str(event),)).fetchone():
                conn.execute("INSERT INTO memory_tombstones(created_at_ms,target_type,target_value,reason,active,metadata_json) VALUES (?,'source_event_id',?,'source_forgotten',1,'{}')", (at, str(event)))
        for kind, key in (("atom", "atomIds"), ("item", "itemIds"), ("book", "bookIds")):
            for target in plan[key]:
                mutation(conn, kind, target, at)
        for sid in plan["sourceIds"]:
            conn.execute("UPDATE agent_memory_sources SET status='tombstoned',disposition='not_for_memory',disposition_reason='source_forgotten',disposition_updated_at_ms=? WHERE source_id=?", (at, sid))
        for rid in plan["relationIds"]:
            conn.execute("UPDATE memory_relations SET status='tombstoned',revision=revision+1,updated_at_ms=? WHERE relation_id=? AND status!='tombstoned'", (at, rid))
        for kind, ids in (("source", plan["eventIds"]), ("evidence", plan["evidenceIds"]), ("atom", plan["atomIds"])):
            for local_id in ids:
                origins = [(namespace, str(local_id))]
                origins.extend((r[0], r[1]) for r in conn.execute("SELECT namespace,external_id FROM memory_portable_imports WHERE object_kind=? AND local_id=?", (kind, str(local_id))))
                for ns, external in origins:
                    conn.execute("INSERT OR IGNORE INTO memory_portable_revocations(namespace,object_kind,external_id,revoked_at_ms) VALUES (?,?,?,?)", (ns, kind, external, at))
        # Uses the owning full-project projection rebuild, never deletes other
        # projects' documents via a partial global rebuild.
        rebuild(conn)
    invalidated = False
    if cache_invalidator:
        try:
            cache_invalidator()
            invalidated = True
        except Exception:
            # An observer failure must not pretend the committed erasure failed.
            invalidated = False
    return {"ok": True, "forgotten": True, "plan": plan, "logicalErasureOnly": True,
            "processCacheInvalidationRequired": not invalidated, "cacheInvalidated": invalidated}
