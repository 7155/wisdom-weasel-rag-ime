"""Read-only topic pages derived from authoritative Atoms and admitted Evidence.

Book summaries are navigation caches. They never supply current page prose.
Explicit Atom kinds select sections; this projection does not infer reasons,
resolve semantic contradictions, or promote questions to confirmed facts.
"""
from __future__ import annotations

import json
import sqlite3

from .management_work_contract import canonical_payload_sha256
from .memory_evidence_admission import admitted_personal_evidence_sql
from .memory_ingest import looks_sensitive
from .memory_projection_consistency import AUTHORITATIVE_ATOM_STATUSES
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace, now_ms, truncate_text


MAX_ATOMS = 256
MAX_TEXT = 4_000
MAX_REFERENCES = 20
MAX_SOURCES = 80
CONSTRAINT_KINDS = frozenset({"constraint", "project_constraint", "security_constraint",
                             "requirement", "project_requirement", "personal_principle"})
QUESTION_KINDS = frozenset({"question", "project_question"})


def _json(value: object, default):
    try:
        result = json.loads(str(value or ""))
    except (ValueError, TypeError):
        return default
    return result if isinstance(result, type(default)) else default


def _sensitive(text: str) -> bool:
    return looks_sensitive(text) or contains_sensitive_content(text)


def _reference(kind: str, identifier: str, text: str = "") -> dict:
    reference = {"kind": kind, "id": identifier,
                 "referenceKind": kind, "referenceId": identifier}
    if text:
        reference["label"] = "[敏感内容已隐藏]" if _sensitive(text) else truncate_text(text, 180)
    return reference


def read_memory_topic_page(conn: sqlite3.Connection, book_id: str, *, project: str) -> dict:
    # All sections and their Evidence links describe one SQLite read snapshot.
    # Reuse an enclosing transaction, and never commit or undo caller writes.
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        return _read_memory_topic_page(conn, book_id, project=project)
    finally:
        if owns_transaction:
            conn.rollback()


def _read_memory_topic_page(conn: sqlite3.Connection, book_id: str, *, project: str) -> dict:
    # Current catalog readers deliberately omit superseded Books. An explicit
    # entity deep link still needs a truthful historical projection, though:
    # keep the owner/project boundary and rebuild the body from visible Atoms
    # rather than reviving the retired summary.
    book = conn.execute("""
        SELECT * FROM memory_books WHERE book_id = ?
          AND status IN ('active', 'approved', 'archived', 'superseded')
          AND owner_kind = 'user' AND owner_id = 'default'
          AND (? = '' OR project IN ('', ?))
    """, (book_id, project, project)).fetchone()
    if book is None:
        raise ValueError("memory book was not found in the requested project")
    # An omitted request filter means browsing the catalog, not permission to
    # merge another project's matching lineage into this Book. Global Atoms
    # remain eligible under the existing shared-scope policy.
    scope_project = str(book["project"] or project)
    member_ids = list(dict.fromkeys(str(value) for value in _json(book["memory_atom_ids_json"], [])
                                   if isinstance(value, str) and value))
    rows = conn.execute("""
        WITH RECURSIVE scoped AS (
            SELECT * FROM memory_atoms
            WHERE owner_kind = ? AND owner_id = ? AND privacy_level != 'sensitive'
              AND status NOT IN ('hidden', 'tombstoned') AND claim_state != 'retracted'
              AND (? = '' OR COALESCE(scope_project, '') IN ('', ?))
        ), related(id) AS (
            SELECT id FROM scoped WHERE id IN (SELECT value FROM json_each(?))
            UNION
            SELECT candidate.id FROM scoped AS candidate
            JOIN scoped AS previous ON (
                (previous.lineage_id != '' AND candidate.lineage_id = previous.lineage_id)
                OR candidate.supersedes_id = previous.id OR previous.supersedes_id = candidate.id
            )
            JOIN related ON previous.id = related.id
            LIMIT ?
        )
        SELECT scoped.* FROM scoped JOIN related ON related.id = scoped.id
        ORDER BY CASE WHEN claim_state = 'current' THEN 0 ELSE 1 END,
                 valid_from_ms DESC, updated_at_ms DESC, id
    """, (book["owner_kind"], book["owner_id"], scope_project, scope_project,
          json.dumps(member_ids[:MAX_ATOMS]), MAX_ATOMS + 1)).fetchall()
    truncated = len(member_ids) > MAX_ATOMS or len(rows) > MAX_ATOMS
    rows = rows[:MAX_ATOMS]
    sections: dict[str, list[dict]] = {key: [] for key in ("current", "constraints", "openQuestions", "history")}
    sources: dict[tuple[str, str], dict] = {}
    visible_ids: set[str] = set()
    omitted_ids: set[str] = set(member_ids) - {str(row["id"]) for row in rows}
    timestamp = now_ms()
    admitted = admitted_personal_evidence_sql("evidence")
    for row in rows:
        atom_id = str(row["id"])
        text = compact_whitespace(str(row["canonical_text"] or row["text"] or ""))
        valid_from = int(row["valid_from_ms"] or 0)
        valid_to = int(row["valid_to_ms"]) if row["valid_to_ms"] is not None else None
        if not text or _sensitive(text) or valid_from > timestamp:
            omitted_ids.add(atom_id)
            continue
        linked_count = conn.execute("SELECT COUNT(*) FROM memory_atom_evidence_links WHERE memory_atom_id = ?",
                                    (atom_id,)).fetchone()[0]
        evidence_rows = conn.execute(f"""
            SELECT DISTINCT evidence.evidence_id, evidence.content_text, evidence.occurred_at_ms
            FROM memory_atom_evidence_links AS link
            JOIN agent_memory_evidence AS evidence ON evidence.evidence_id = link.evidence_id
            WHERE link.memory_atom_id = ? AND link.relation IN ('supports', 'corrects') AND {admitted}
              AND link.content_sha256 = evidence.content_sha256
              AND evidence.owner_kind = ? AND evidence.owner_id = ?
              AND (? = '' OR evidence.project IN ('', ?))
            ORDER BY evidence.occurred_at_ms DESC, evidence.evidence_id
            LIMIT ?
        """, (atom_id, book["owner_kind"], book["owner_id"], scope_project, scope_project,
              MAX_REFERENCES + 1)).fetchall()
        # An explicitly withdrawn/rejected support must not reappear through a
        # still-linked Atom. Legacy Atoms with no link remain inspectable with
        # sourceStatus=unavailable; no raw event fallback manufactures support.
        if linked_count and not evidence_rows:
            omitted_ids.add(atom_id)
            continue
        truncated = truncated or len(text) > MAX_TEXT or len(evidence_rows) > MAX_REFERENCES
        refs = [_reference("evidence", str(e["evidence_id"]), compact_whitespace(str(e["content_text"] or "")))
                for e in evidence_rows[:MAX_REFERENCES]]
        for ref in refs:
            sources[(ref["kind"], ref["id"])] = ref
        current = (row["status"] in AUTHORITATIVE_ATOM_STATUSES and row["claim_state"] == "current"
                   and (valid_to is None or valid_to > timestamp))
        section = ("constraints" if row["kind"] in CONSTRAINT_KINDS else
                   "openQuestions" if row["kind"] in QUESTION_KINDS else "current") if current else "history"
        superseded_by = [str(other["id"]) for other in rows
                         if str(other["supersedes_id"] or "") == atom_id]
        sections[section].append({
            "id": atom_id, "text": truncate_text(text, MAX_TEXT), "kind": str(row["kind"]),
            "status": str(row["status"]), "claimState": str(row["claim_state"]),
            "atomIds": [atom_id], "references": [_reference("atom", atom_id), *refs],
            "sourceStatus": "available" if refs else "unavailable",
            "lineageId": str(row["lineage_id"] or ""), "validFromMs": valid_from, "validToMs": valid_to,
            "supersedesId": str(row["supersedes_id"] or ""), "supersededByIds": superseded_by,
            "reason": None,
        })
        visible_ids.add(atom_id)
    for entries in sections.values():
        for entry in entries:
            entry["supersededByIds"] = [atom_id for atom_id in entry["supersededByIds"]
                                        if atom_id in visible_ids]
    metadata = _json(book["metadata_json"], {})
    current_ids = {entry["id"] for key, entries in sections.items() if key != "history" for entry in entries}
    needs_refresh = metadata.get("retrievalStale") is True or set(member_ids) != current_ids
    summary = truncate_text("；".join(entry["text"] for key in ("current", "constraints")
                                     for entry in sections[key]), 900)
    body = {
        "schemaVersion": "rag-ime.memory-topic-page.v1", "bookId": book_id,
        "authority": "atom_projection", "freshness": "needs_refresh" if needs_refresh else "current",
        "summary": summary, "sections": sections, "sources": list(sources.values())[:MAX_SOURCES],
        "coverage": {"memberCount": len(member_ids), "visibleAtomCount": len(visible_ids),
                     "omittedAtomCount": len(omitted_ids), "truncated": truncated or len(sources) > MAX_SOURCES},
    }
    return {**body, "revision": canonical_payload_sha256(body)}
