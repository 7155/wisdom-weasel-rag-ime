"""Project-scoped, provenance-preserving interchange of canonical Memory.

Imports are explicit user review requests, not trusted database backups.
Incoming approvals, owners, SQL, paths, sessions and authorization bindings
are never replayed. Every imported Atom is a draft and Evidence needs review.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from .common import (MAX_BUNDLE_BYTES, MAX_OBJECTS, LifecycleError, bounded_rows,
                     canonical_json, digest, identifier, insert_row, instance_namespace,
                     load_json, now_ms, require_schema, row_dicts, text_digest,
                     timestamp, transaction)
from .privacy import CapturePolicy, assess_capture, redact_text, sanitize_json

SCHEMA = "paw.memory-bundle.v1"
_LISTS = ("sources", "evidence", "atoms")
_TYPES = {"sources": "source", "evidence": "evidence", "atoms": "atom"}


def _origin(conn: sqlite3.Connection, namespace: str, kind: str, local_id: str, project: str) -> dict[str, str]:
    row = conn.execute("""SELECT namespace, external_id FROM memory_portable_imports
        WHERE object_kind=? AND local_id=? AND project=?""", (kind, local_id, project)).fetchone()
    return {"namespace": str(row[0]), "id": str(row[1])} if row else {"namespace": namespace, "id": local_id}


def object_id(kind: str, origin: Mapping[str, str]) -> str:
    return f"{kind}:{digest([origin['namespace'], origin['id']])}"


def _object(object_kind: str, origin: dict[str, str], **data: Any) -> dict[str, Any]:
    if any(redact_text(value) != value for value in origin.values()):
        raise LifecycleError("sensitive_identifier_requires_opaque_id")
    return {"id": object_id(object_kind, origin), "origin": origin, **data}


def _sealed(packet: dict[str, Any]) -> dict[str, Any]:
    packet["sha256"] = digest(packet)
    if len(canonical_json(packet).encode()) > MAX_BUNDLE_BYTES:
        raise LifecycleError("bundle_too_large")
    return packet


def export_project(conn: sqlite3.Connection, *, project: str,
                   policy: CapturePolicy | None = None) -> dict[str, Any]:
    """Export one user's exact project; no global/project/owner widening.

    Unsupported or hidden dependencies omit the WHOLE dependent Atom instead
    of exporting a misleading partial proof. Counts make omissions explicit.
    """
    project = identifier(project, field="project", allow_empty=True)
    require_schema(conn)
    with transaction(conn):
        namespace = instance_namespace(conn)
        return _export_snapshot(conn, project=project, namespace=namespace, policy=policy)


def _export_snapshot(conn: sqlite3.Connection, *, project: str, namespace: str,
                     policy: CapturePolicy | None) -> dict[str, Any]:
    evidence_rows = bounded_rows(conn.execute("""SELECT e.* FROM agent_memory_evidence e
        WHERE e.project=? AND e.owner_kind='user' AND e.owner_id='default'
          AND e.evidence_domain='personal_memory' AND e.knowledge_domain='personal_memory'
          AND e.scope_mode='authoritative' AND e.status='active'
          AND e.admission_state IN ('candidate','needs_review','admitted')
          AND NOT EXISTS (SELECT 1 FROM memory_tombstones t WHERE t.active=1
              AND t.target_type='memory_id' AND t.target_value=e.evidence_id)
        ORDER BY e.occurred_at_ms,e.evidence_id""", (project,)))
    event_cache: dict[int, dict[str, Any] | None] = {}
    evidence_out: dict[str, dict[str, Any]] = {}
    evidence_events: dict[str, set[int]] = {}
    omitted_evidence = 0
    references: list[dict[str, str]] = []
    for row in evidence_rows:
        source_links = row_dicts(conn.execute("""SELECT l.* FROM memory_evidence_input_event_links l
            WHERE l.evidence_id=? ORDER BY l.ordinal,l.input_event_id,l.relation""", (row["evidence_id"],)))
        sources = [link for link in source_links if link["relation"] == "source"]
        if not sources:
            omitted_evidence += 1
            continue
        safe = assess_capture(source=row["source_kind"], text=row["content_text"],
                              metadata={"metadata": load_json(row["metadata_json"]),
                                        "provenance": load_json(row["provenance_json"])}, policy=policy)
        if not safe.allowed:
            omitted_evidence += 1
            continue
        for link in source_links:
            event_id = int(link["input_event_id"])
            if event_id in event_cache:
                continue
            events = row_dicts(conn.execute("""SELECT e.* FROM input_events e
                LEFT JOIN memory_state s ON s.event_id=e.id
                WHERE e.id=? AND e.project=? AND COALESCE(s.deleted,0)=0
                AND NOT EXISTS (SELECT 1 FROM memory_tombstones t WHERE t.active=1 AND (
                    (t.target_type='source_event_id' AND t.target_value=CAST(e.id AS TEXT)) OR
                    (t.target_type='memory_id' AND t.target_value='event:'||e.id)))""", (event_id, project)))
            event_cache[event_id] = None
            if not events:
                continue
            event = events[0]
            metadata = load_json(event.get("capture_metadata_json") or "{}")
            decision = assess_capture(source=event["source"], text=event["committed_text"],
                                      metadata=metadata, tags=tuple(load_json(event["tags_json"], list)), policy=policy)
            if not decision.allowed:
                continue
            origin = _origin(conn, namespace, "source", str(event_id), project)
            original_transport = metadata.get("portableOriginalSource", event["source"])
            event_cache[event_id] = _object("source", origin, source=str(original_transport),
                text=decision.text, contentSha256=text_digest(decision.text), occurredAtMs=int(event["created_at_ms"]),
                revision=int(conn.execute("SELECT COALESCE(MAX(source_revision),1) FROM agent_memory_sources WHERE input_event_id=?", (event_id,)).fetchone()[0]))
        if any(event_cache[int(link["input_event_id"])] is None for link in sources):
            omitted_evidence += 1
            continue
        origin = _origin(conn, namespace, "evidence", row["evidence_id"], project)
        # Preserve the original source descriptor through repeated migrations.
        provenance = load_json(row["provenance_json"])
        source_descriptor = provenance.get("portableOriginalSource") or {
            "kind": row["source_kind"], "id": row["source_id"],
            "occurredAtMs": int(row["occurred_at_ms"]), "recordedAtMs": int(row["recorded_at_ms"])}
        item = _object("evidence", origin, text=safe.text, contentSha256=text_digest(safe.text),
            occurredAtMs=int(row["occurred_at_ms"]), recordedAtMs=int(row["recorded_at_ms"]),
            source=sanitize_json(source_descriptor), admissionState=row["admission_state"],
            provenance=sanitize_json(provenance.get("portableOriginalProvenance", provenance)),
            redacted=safe.redacted)
        evidence_out[row["evidence_id"]] = item
        evidence_events[row["evidence_id"]] = {int(link["input_event_id"]) for link in sources}
        for link in source_links:
            source_item = event_cache[int(link["input_event_id"])]
            if source_item:
                references.append({"from": item["id"], "to": source_item["id"], "relation": link["relation"]})
    atoms_out: list[dict[str, Any]] = []
    omitted_atoms = 0
    for row in bounded_rows(conn.execute("""SELECT a.* FROM memory_atoms a
        WHERE COALESCE(a.scope_project,'')=? AND a.owner_kind='user' AND a.owner_id='default'
          AND a.status IN ('active','approved','draft') AND a.privacy_level!='sensitive'
          AND NOT EXISTS (SELECT 1 FROM memory_tombstones t WHERE t.active=1
             AND t.target_type='memory_id' AND t.target_value=a.id)
        ORDER BY a.created_at_ms,a.id""", (project,))):
        event_ids = set(load_json(row["source_event_ids_json"], list))
        linked = {r[0] for r in conn.execute("SELECT evidence_id FROM memory_lifecycle_atom_evidence_links WHERE atom_id=? AND relation='source'", (row["id"],))}
        linked.update(key for key, ids in evidence_events.items() if event_ids.intersection(ids))
        covered = set().union(*(evidence_events.get(key, set()) for key in linked)) if linked else set()
        decision = assess_capture(source="memory_atom", text=row["canonical_text"] or row["text"], policy=policy)
        if not decision.allowed or not linked or not linked <= evidence_out.keys() or not event_ids <= covered:
            omitted_atoms += 1
            continue
        # A mixed proof involving another Memory item cannot be flattened into
        # only the Evidence we happened to find. Preserve safety by omitting it.
        memory_ids = load_json(row["source_memory_ids_json"], list)
        if any(str(value) not in {f"event:{eid}" for eid in event_ids} | {f"raw:event:{eid}" for eid in event_ids} for value in memory_ids):
            omitted_atoms += 1
            continue
        origin = _origin(conn, namespace, "atom", row["id"], project)
        item = _object("atom", origin, kind=row["kind"], text=decision.text,
            contentSha256=text_digest(decision.text), status=row["status"],
            createdAtMs=int(row["created_at_ms"]), updatedAtMs=int(row["updated_at_ms"]),
            validFromMs=int(row.get("valid_from_ms") or 0), validToMs=row.get("valid_to_ms"),
            claimState=row.get("claim_state", "current"), redacted=decision.redacted,
            displayText=redact_text(row["text"]), properties=sanitize_json({"confidence": float(row["confidence"]),
                "qualityScore": float(row["quality_score"]), "echoRisk": float(row["echo_risk"]),
                "language": row["language"], "scopeApp": row["scope_app"] or ""}))
        atoms_out.append(item)
        references.extend({"from": item["id"], "to": evidence_out[key]["id"], "relation": "source"} for key in sorted(linked))
    used_sources = {ref["to"] for ref in references}
    packet = {"schemaVersion": SCHEMA, "namespace": namespace, "project": project,
        "owner": {"kind": "user", "id": "default"}, "exportedAtMs": now_ms(),
        "sources": sorted((item for item in event_cache.values() if item and item["id"] in used_sources), key=lambda x: x["id"]),
        "evidence": sorted(evidence_out.values(), key=lambda x: x["id"]),
        "atoms": sorted(atoms_out, key=lambda x: x["id"]),
        "references": sorted(references, key=lambda r: (r["from"], r["to"], r["relation"])),
        "omitted": {"evidence": omitted_evidence, "atoms": omitted_atoms}}
    return _sealed(packet)


def validate_bundle(packet: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(packet, Mapping) or packet.get("schemaVersion") != SCHEMA:
        raise LifecycleError("unsupported_bundle_schema")
    if len(canonical_json(packet).encode()) > MAX_BUNDLE_BYTES:
        raise LifecycleError("bundle_too_large")
    body = {k: v for k, v in packet.items() if k != "sha256"}
    if packet.get("sha256") != digest(body):
        raise LifecycleError("bundle_integrity_mismatch")
    identifier(packet.get("namespace"), field="namespace")
    identifier(packet.get("project"), field="project", allow_empty=True)
    timestamp(packet.get("exportedAtMs"))
    if packet.get("owner") != {"kind": "user", "id": "default"}:
        raise LifecycleError("unsupported_bundle_owner")
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    origins: set[tuple[str, str, str]] = set()
    for group in _LISTS:
        items = packet.get(group)
        if not isinstance(items, list) or len(items) > MAX_OBJECTS:
            raise LifecycleError("invalid_bundle_collection")
        kind = _TYPES[group]
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("origin"), dict):
                raise LifecycleError("invalid_bundle_object")
            origin = item["origin"]
            identifier(origin.get("namespace"), field="namespace")
            identifier(origin.get("id"))
            if any(redact_text(value) != value for value in origin.values()):
                raise LifecycleError("sensitive_identifier_requires_opaque_id")
            object_key = identifier(item.get("id"))
            identity = (kind, origin["namespace"], origin["id"])
            if object_key != object_id(kind, origin) or object_key in index or identity in origins:
                raise LifecycleError("duplicate_or_invalid_object_identity")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 32_000:
                raise LifecycleError("invalid_bundle_text")
            if item.get("contentSha256") != text_digest(text):
                raise LifecycleError("object_content_digest_mismatch")
            if kind == "atom":
                identifier(item.get("kind"), field="atom_kind")
                if not isinstance(item.get("displayText", text), str) or len(item.get("displayText", text)) > 32_000:
                    raise LifecycleError("invalid_atom_display_text")
                _atom_properties(item)
                timestamp(item.get("createdAtMs"))
                timestamp(item.get("updatedAtMs"))
                timestamp(item.get("validFromMs", 0))
                if item.get("validToMs") is not None:
                    timestamp(item["validToMs"])
                    if item["validToMs"] <= item.get("validFromMs", 0):
                        raise LifecycleError("invalid_validity_interval")
                if item.get("claimState") not in {"current", "superseded", "retracted"}:
                    raise LifecycleError("invalid_claim_state")
            else:
                timestamp(item.get("occurredAtMs"))
                if kind == "source":
                    identifier(item.get("source"), field="source_type")
                    if type(item.get("revision", 1)) is not int or not 1 <= item.get("revision", 1) <= 2**31 - 1:
                        raise LifecycleError("invalid_source_revision")
                else:
                    timestamp(item.get("recordedAtMs"))
                    if not isinstance(item.get("source"), dict) or not isinstance(item.get("provenance", {}), dict):
                        raise LifecycleError("invalid_evidence_provenance")
                    identifier(item["source"].get("kind"), field="evidence_source_kind")
                    identifier(item["source"].get("id"), field="evidence_source_id")
            index[object_key] = (kind, item)
            origins.add(identity)
    refs = packet.get("references")
    if not isinstance(refs, list) or len(refs) > MAX_OBJECTS * 10:
        raise LifecycleError("invalid_references")
    seen: set[tuple[str, str, str]] = set()
    supported: set[str] = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"from", "to", "relation"}:
            raise LifecycleError("invalid_reference")
        left = identifier(ref["from"])
        right = identifier(ref["to"])
        if left not in index or right not in index:
            raise LifecycleError("dangling_reference")
        if ref["relation"] not in {"source", "context"}:
            raise LifecycleError("invalid_reference_relation")
        pair = (index[left][0], index[right][0])
        if pair not in {("atom", "evidence"), ("evidence", "source")}:
            raise LifecycleError("invalid_reference_direction")
        key = (left, right, ref["relation"])
        if key in seen:
            raise LifecycleError("duplicate_reference")
        seen.add(key)
        if ref["relation"] == "source":
            supported.add(left)
    if any(kind != "source" and key not in supported for key, (kind, _) in index.items()):
        raise LifecycleError("missing_supporting_reference")
    return dict(packet)


def records_bundle(*, records: list[dict[str, Any]], namespace: str, project: str) -> dict[str, Any]:
    """Normalize explicit daily-report/work-record imports without a model.

    Each record needs its stable external id AND actual occurrence time. A
    generated PAW report must be explicitly re-authored/confirmed; its automatic
    metadata marker is rejected by the ingress gate.
    """
    identifier(namespace, field="namespace")
    identifier(project, allow_empty=True)
    if not records or len(records) > MAX_OBJECTS:
        raise LifecycleError("invalid_records")
    sources, evidence, refs = [], [], []
    for record in records:
        rid = identifier(record.get("id"))
        occurred = timestamp(record.get("occurredAtMs"))
        origin = {"namespace": namespace, "id": rid}
        safe = assess_capture(source="work_record", text=record.get("text"), metadata=record.get("metadata", {}))
        if not safe.allowed:
            raise LifecycleError("record_excluded_by_privacy")
        source = _object("source", origin, source="work_record_import", text=safe.text,
            contentSha256=text_digest(safe.text), occurredAtMs=occurred, revision=1)
        item = _object("evidence", origin, text=safe.text, contentSha256=text_digest(safe.text),
            occurredAtMs=occurred, recordedAtMs=timestamp(record.get("recordedAtMs", occurred)),
            source={"kind": "work_record", "id": rid}, provenance=safe.metadata,
            admissionState="needs_review", redacted=safe.redacted)
        sources.append(source)
        evidence.append(item)
        refs.append({"from": item["id"], "to": source["id"], "relation": "source"})
    packet = _sealed({"schemaVersion": SCHEMA, "namespace": namespace, "project": project,
        "owner": {"kind": "user", "id": "default"}, "exportedAtMs": now_ms(),
        "sources": sources, "evidence": evidence, "atoms": [], "references": refs,
        "omitted": {"evidence": 0, "atoms": 0}})
    return validate_bundle(packet)


def _atom_properties(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties", {})
    if not isinstance(props, dict) or set(props) - {"confidence", "qualityScore", "echoRisk", "language", "scopeApp"}:
        raise LifecycleError("invalid_atom_properties")
    result = {"confidence": 0.5, "qualityScore": 0.5, "echoRisk": 0.0, "language": "zh", "scopeApp": "", **props}
    for key in ("confidence", "qualityScore", "echoRisk"):
        if type(result[key]) not in {int, float} or not 0 <= result[key] <= 1:
            raise LifecycleError("invalid_atom_score")
        result[key] = float(result[key])
    identifier(result["language"], field="language")
    identifier(result["scopeApp"], field="scope_app", allow_empty=True)
    return result


def _identity_fingerprint(item: dict[str, Any], refs: list[dict[str, str]]) -> str:
    # Review status and transfer timestamps are not immutable content identity.
    body = {k: v for k, v in item.items() if k not in {"status", "admissionState", "recordedAtMs", "updatedAtMs", "redacted"}}
    if item["id"].startswith("atom:"):
        body["properties"] = _atom_properties(item)
        body.setdefault("displayText", item["text"])
    elif item["id"].startswith("source:"):
        body.setdefault("revision", 1)
    return digest({"object": body, "references": sorted(refs, key=lambda x: (x["to"], x["relation"]))})


class _DryRunRollback(Exception):
    pass


def import_bundle(conn: sqlite3.Connection, packet: Mapping[str, Any], *, target_project: str,
                  dry_run: bool = True) -> dict[str, Any]:
    """Validate and import atomically. Default is rollback-only preview."""
    packet = validate_bundle(packet)
    project = identifier(target_project, field="project", allow_empty=True)
    require_schema(conn)
    counts = {"source": 0, "evidence": 0, "atom": 0, "reused": 0}
    refs = packet["references"]
    refs_by_id: dict[str, list[dict[str, str]]] = {}
    for ref in refs:
        refs_by_id.setdefault(ref["from"], []).append(ref)
    id_map: dict[str, str] = {}
    imported_at = now_ms()
    try:
        with transaction(conn):
            for group in _LISTS:
                kind = _TYPES[group]
                for original in packet[group]:
                    item = dict(original)
                    origin = item["origin"]
                    ns, ext = origin["namespace"], origin["id"]
                    if conn.execute("SELECT 1 FROM memory_portable_revocations WHERE namespace=? AND object_kind=? AND external_id=?", (ns, kind, ext)).fetchone():
                        raise LifecycleError("source_was_forgotten")
                    # Re-run LOCAL privacy rules. A bundle hash is NOT authorization.
                    metadata = item.get("provenance", {}) if kind == "evidence" else {}
                    decision = assess_capture(source=item["source"] if kind == "source" else item["source"]["kind"] if kind == "evidence" else kind,
                        text=item["text"], metadata=metadata)
                    if not decision.allowed:
                        raise LifecycleError("import_excluded_by_local_privacy")
                    item["text"] = decision.text
                    item["contentSha256"] = text_digest(decision.text)
                    if kind == "atom":
                        item["displayText"] = redact_text(item.get("displayText", original["text"]))
                        item["properties"] = sanitize_json(_atom_properties(item))
                    if kind == "evidence":
                        item["provenance"] = decision.metadata
                        item["source"] = sanitize_json(item["source"])
                    semantic = _identity_fingerprint(item, refs_by_id.get(item["id"], []))
                    existing = conn.execute("""SELECT local_id,input_digest FROM memory_portable_imports
                        WHERE namespace=? AND object_kind=? AND external_id=? AND project=?""", (ns, kind, ext, project)).fetchone()
                    if existing:
                        if existing[1] != semantic:
                            raise LifecycleError("source_identity_content_conflict")
                        id_map[item["id"]] = str(existing[0])
                        _assert_live_import(conn, kind, str(existing[0]), project)
                        counts["reused"] += 1
                        continue
                    key = f"portable-{kind}:" + digest([ns, ext, project])
                    local_id = _insert_object(conn, kind=kind, item=item, key=key, project=project,
                        refs=refs_by_id.get(item["id"], []), id_map=id_map, imported_at=imported_at)
                    conn.execute("""INSERT INTO memory_portable_imports(namespace,object_kind,external_id,
                        project,local_id,input_digest,imported_at_ms) VALUES (?,?,?,?,?,?,?)""",
                        (ns, kind, ext, project, local_id, semantic, imported_at))
                    id_map[item["id"]] = local_id
                    counts[kind] += 1
            if dry_run:
                raise _DryRunRollback()
    except _DryRunRollback:
        pass
    return {"ok": True, "dryRun": dry_run, "project": project, "counts": counts,
            "requiresReview": True, "approvedAtomsCreated": 0,
            "idMap": id_map, "bundleSha256": packet["sha256"]}


def _assert_live_import(conn: sqlite3.Connection, kind: str, local_id: str, project: str) -> None:
    queries = {
        "source": ("SELECT 1 FROM input_events e JOIN memory_state s ON s.event_id=e.id WHERE e.id=? AND e.project=? AND s.deleted=0", (local_id, project)),
        "evidence": ("SELECT 1 FROM agent_memory_evidence WHERE evidence_id=? AND project=? AND status='active' AND admission_state!='forgotten'", (local_id, project)),
        "atom": ("SELECT 1 FROM memory_atoms WHERE id=? AND scope_project=? AND status NOT IN ('tombstoned','deleted')", (local_id, project)),
    }
    sql, args = queries[kind]
    if not conn.execute(sql, args).fetchone():
        raise LifecycleError("import_target_no_longer_live")


def _insert_object(conn: sqlite3.Connection, *, kind: str, item: dict[str, Any], key: str,
                   project: str, refs: list[dict[str, str]], id_map: dict[str, str], imported_at: int) -> str:
    if kind == "source":
        insert_row(conn, "input_events", {
            "created_at_ms": item["occurredAtMs"], "source": "memory_portable_import",
            "committed_text": item["text"], "recent_context": "", "preedit": "", "schema_id": "memory-import-v1",
            "app": "PAW", "project": project, "candidate_rank": None, "provider_name": "user-import",
            "tags_json": '["memory-import","needs-review"]', "context_group_id": key, "context_group_level": "project",
            "capture_metadata_json": canonical_json({"portableOriginalSource": item["source"], "memoryRetention": "durable"})})
        event_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        insert_row(conn, "memory_state", {"event_id": event_id, "updated_at_ms": imported_at})
        insert_row(conn, "agent_memory_sources", {"source_id": key, "session_id": "", "pi_entry_id": key,
            "input_event_id": event_id, "source_role": "user", "source_revision": item.get("revision", 1),
            "canonical_text_sha256": item["contentSha256"], "created_at_ms": item["occurredAtMs"],
            "owner_kind": "user", "owner_id": "default", "source_kind": "explicit_memory",
            "trust_class": "explicit_command", "disposition": "needs_review", "disposition_reason": "portable_import_requires_review",
            "disposition_updated_at_ms": imported_at,
            "metadata_json": canonical_json({"portableOrigin": item["origin"], "originalSource": item["source"], "untrustedImport": True}),
            "knowledge_domain": "personal_memory", "scope_kind": "user", "scope_id": "default",
            "visibility": "private", "authorization_revision": "memory-portable-import-v1", "binding_id": key, "scope_mode": "authoritative"})
        insert_row(conn, "memory_source_disposition_events", {"event_id": key + ":admission", "source_id": key,
            "previous_disposition": "", "new_disposition": "needs_review", "reason_code": "portable_import_requires_review",
            "actor_kind": "user", "created_at_ms": imported_at, "metadata_json": '{}'})
        return str(event_id)
    if kind == "evidence":
        source_refs = [r for r in refs if r["relation"] == "source"]
        primary_event = int(id_map[source_refs[0]["to"]])
        primary_source = conn.execute("SELECT source_id FROM agent_memory_sources WHERE input_event_id=? ORDER BY source_id LIMIT 1", (primary_event,)).fetchone()[0]
        insert_row(conn, "agent_memory_evidence", {"evidence_id": key, "project": project, "role_id": "", "session_id": "",
            "source_kind": "user_message", "source_id": primary_source, "idempotency_key": key,
            "content_text": item["text"], "content_sha256": item["contentSha256"],
            "provenance_json": canonical_json({"portableOrigin": item["origin"], "portableOriginalSource": sanitize_json(item["source"]),
                "portableOriginalProvenance": item.get("provenance", {}), "originalRecordedAtMs": item["recordedAtMs"]}),
            "metadata_json": canonical_json({"untrustedImport": True, "sourceAdmissionState": item.get("admissionState", "unknown")}),
            "privacy_class": "private", "status": "active", "occurred_at_ms": item["occurredAtMs"],
            "recorded_at_ms": item["recordedAtMs"], "owner_kind": "user", "owner_id": "default",
            "knowledge_domain": "personal_memory", "scope_kind": "user", "scope_id": "default", "visibility": "private",
            "authorization_revision": "memory-portable-import-v1", "binding_id": key, "scope_mode": "authoritative",
            "evidence_domain": "personal_memory", "origin_kind": "explicit_user_memory", "admission_state": "needs_review",
            "admission_reason": "portable_import_requires_review", "trust_class": "user_claim", "boundary_kind": "explicit_user_import_review",
            "admission_revision": 1, "admission_updated_at_ms": imported_at})
        for pos, ref in enumerate(refs):
            event_id = int(id_map[ref["to"]])
            source_text = conn.execute("SELECT committed_text FROM input_events WHERE id=?", (event_id,)).fetchone()[0]
            insert_row(conn, "memory_evidence_input_event_links", {"evidence_id": key, "input_event_id": event_id,
                "ordinal": pos, "relation": ref["relation"], "content_sha256": text_digest(source_text), "created_at_ms": imported_at})
        insert_row(conn, "memory_evidence_admission_events", {"event_id": key + ":admission", "evidence_id": key,
            "previous_state": "", "new_state": "needs_review", "reason_code": "portable_import_requires_review",
            "actor_kind": "user", "created_at_ms": imported_at, "metadata_json": '{}'})
        return key
    events: set[int] = set()
    for ref in refs:
        if ref["relation"] == "source":
            events.update(r[0] for r in conn.execute("SELECT input_event_id FROM memory_evidence_input_event_links WHERE evidence_id=? AND relation='source'", (id_map[ref["to"]],)))
    insert_row(conn, "memory_atoms", {"id": key, "kind": item["kind"], "text": item.get("displayText", item["text"]), "canonical_text": item["text"],
        "source_event_ids_json": canonical_json(sorted(events)), "source_memory_ids_json": '[]', "scope_project": project,
        "scope_app": item["properties"]["scopeApp"], "language": item["properties"]["language"],
        "confidence": item["properties"]["confidence"], "quality_score": item["properties"]["qualityScore"], "echo_risk": item["properties"]["echoRisk"],
        "status": "draft", "privacy_level": "private", "owner_kind": "user", "owner_id": "default",
        "created_at_ms": item["createdAtMs"], "updated_at_ms": item["updatedAtMs"],
        "claim_state": item["claimState"], "valid_from_ms": item.get("validFromMs", 0), "valid_to_ms": item.get("validToMs")})
    for ref in refs:
        insert_row(conn, "memory_lifecycle_atom_evidence_links", {"atom_id": key, "evidence_id": id_map[ref["to"]],
            "relation": ref["relation"], "created_at_ms": imported_at})
    return key
