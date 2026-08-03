from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping

from .agent_memory_sources import (
    assert_source_curation_not_running,
    invalidate_source_review_drafts,
    rewind_curation_cursors_for_source,
)
from .text_utils import compact_whitespace


PERSONAL_MEMORY_DOMAIN = "personal_memory"
PERSONAL_EVIDENCE_ORIGINS = frozenset(
    {
        "capture_v2_input",
        "capture_v2_voice",
        "explicit_user_memory",
        "applied_personal_receipt",
        # Legacy recovery stays audit-only unless an immutable historical
        # promotion receipt proves the user's explicit full-history request.
        "legacy_untyped_input",
    }
)
ADMISSION_STATES = frozenset(
    {"candidate", "admitted", "needs_review", "rejected", "forgotten"}
)
ADMISSION_ACTORS = frozenset(
    {"rule", "luna", "user", "system", "migration", "rollback"}
)
_SQL_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def admitted_personal_evidence_sql(alias: str = "evidence") -> str:
    """Return the single fail-closed predicate for personal Memory Evidence.

    Every personal Evidence list, count, search, recall, and reference path uses
    this fragment. Role-book/audit evidence has separate domain-specific reads
    and cannot become personal Evidence merely because an Atom still links it.
    """

    return _personal_evidence_sql(
        alias,
        admission_state_sql="= 'admitted'",
    )


def curatable_personal_evidence_sql(alias: str = "evidence") -> str:
    """Return the structural gate for Evidence that Luna may adjudicate.

    Candidate, review, and already-admitted rows can be replayed safely. A
    rejected or forgotten row is never silently resurrected by maintenance.
    """

    return _personal_evidence_sql(
        alias,
        admission_state_sql="IN ('candidate', 'needs_review', 'admitted')",
    )


def _personal_evidence_sql(alias: str, *, admission_state_sql: str) -> str:
    table = _sql_alias(alias)
    origins = ", ".join(f"'{value}'" for value in sorted(PERSONAL_EVIDENCE_ORIGINS))
    return f"""
    {table}.status = 'active'
    AND {table}.evidence_domain = '{PERSONAL_MEMORY_DOMAIN}'
    AND {table}.admission_state {admission_state_sql}
    AND {table}.origin_kind IN ({origins})
    AND {table}.scope_mode = 'authoritative'
    AND {table}.knowledge_domain = 'personal_memory'
    AND {table}.owner_kind = 'user'
    AND {table}.owner_id = 'default'
    AND (
        {table}.origin_kind != 'legacy_untyped_input'
        OR EXISTS (
            SELECT 1
            FROM memory_evidence_historical_promotion_receipts AS historical_promotion
            WHERE historical_promotion.promoted_evidence_id = {table}.evidence_id
              AND historical_promotion.content_sha256 = {table}.content_sha256
              AND historical_promotion.authorization_kind =
                  'user_authorized_full_history_v1'
        )
    )
    AND EXISTS (
        SELECT 1
        FROM memory_evidence_input_event_links AS canonical_source_link
        WHERE canonical_source_link.evidence_id = {table}.evidence_id
          AND canonical_source_link.relation = 'source'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM memory_tombstones AS evidence_tombstone
        WHERE evidence_tombstone.active = 1
          AND evidence_tombstone.target_type = 'memory_id'
          AND evidence_tombstone.target_value = {table}.evidence_id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM memory_evidence_input_event_links AS hidden_source_link
        LEFT JOIN memory_state AS hidden_source_state
          ON hidden_source_state.event_id = hidden_source_link.input_event_id
        WHERE hidden_source_link.evidence_id = {table}.evidence_id
          AND hidden_source_link.relation = 'source'
          AND (
              (
                  COALESCE(hidden_source_state.deleted, 0) != 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM memory_evidence_historical_promotion_receipts
                           AS historical_hidden_source_promotion
                      WHERE historical_hidden_source_promotion.promoted_evidence_id =
                            {table}.evidence_id
                        AND historical_hidden_source_promotion.input_event_id =
                            hidden_source_link.input_event_id
                  )
              )
              OR EXISTS (
                  SELECT 1
                  FROM memory_tombstones AS source_tombstone
                  WHERE source_tombstone.active = 1
                    AND (
                        (
                            source_tombstone.target_type = 'source_event_id'
                            AND source_tombstone.target_value =
                                CAST(hidden_source_link.input_event_id AS TEXT)
                        )
                        OR (
                            source_tombstone.target_type = 'memory_id'
                            AND source_tombstone.target_value =
                                ('event:' || hidden_source_link.input_event_id)
                        )
                    )
              )
          )
    )
    """.strip()


def event_has_admitted_personal_evidence_sql(
    event_alias: str = "event",
    *,
    evidence_alias: str = "linked_evidence",
) -> str:
    """Return an EXISTS predicate proving an event belongs to admitted Evidence."""

    event = _sql_alias(event_alias)
    evidence = _sql_alias(evidence_alias)
    admitted = admitted_personal_evidence_sql(evidence)
    return f"""
    EXISTS (
        SELECT 1
        FROM memory_evidence_input_event_links AS admitted_event_link
        JOIN agent_memory_evidence AS {evidence}
          ON {evidence}.evidence_id = admitted_event_link.evidence_id
        WHERE admitted_event_link.input_event_id = {event}.id
          AND admitted_event_link.relation = 'source'
          AND {admitted}
    )
    """.strip()


def evidence_is_admitted(conn: sqlite3.Connection, evidence_id: str) -> bool:
    identifier = compact_whitespace(evidence_id)
    if not identifier:
        return False
    row = conn.execute(
        f"""
        SELECT 1
        FROM agent_memory_evidence AS evidence
        WHERE evidence.evidence_id = ?
          AND {admitted_personal_evidence_sql('evidence')}
        LIMIT 1
        """,
        (identifier,),
    ).fetchone()
    return row is not None


def transition_evidence_admission(
    conn: sqlite3.Connection,
    evidence_id: str,
    *,
    new_state: str,
    reason_code: str,
    actor_kind: str,
    created_at_ms: int,
    run_id: str = "",
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Apply one auditable Evidence transition, validating admission fail closed."""

    identifier = compact_whitespace(evidence_id)
    state = compact_whitespace(new_state).lower()
    reason = compact_whitespace(reason_code)[:160]
    actor = compact_whitespace(actor_kind).lower()
    if not identifier:
        raise ValueError("evidence_id is required")
    if state not in ADMISSION_STATES:
        raise ValueError("unsupported Evidence admission state")
    if actor not in ADMISSION_ACTORS:
        raise ValueError("unsupported Evidence admission actor")
    if not reason:
        raise ValueError("Evidence admission reason is required")

    row = conn.execute(
        "SELECT * FROM agent_memory_evidence WHERE evidence_id = ?",
        (identifier,),
    ).fetchone()
    if row is None:
        raise KeyError(identifier)
    previous = str(row["admission_state"])
    if state == "admitted":
        _assert_admittable(conn, row)
    if previous == state and str(row["admission_reason"] or "") == reason:
        return {
            "changed": False,
            "evidenceId": identifier,
            "admissionState": previous,
            "reason": reason,
        }

    timestamp = max(0, int(created_at_ms))
    compatibility_source = conn.execute(
        """
        SELECT source.*
        FROM agent_memory_sources AS source
        JOIN memory_evidence_input_event_links AS source_link
          ON source_link.input_event_id = source.input_event_id
         AND source_link.relation = 'source'
        WHERE source_link.evidence_id = ?
        ORDER BY
            CASE WHEN source.source_id = ? THEN 0 ELSE 1 END,
            source.created_at_ms, source.source_id
        LIMIT 1
        """,
        (identifier, str(row["source_id"] or "")),
    ).fetchone()
    if actor in {"user", "rollback"} and compatibility_source is not None:
        assert_source_curation_not_running(
            conn,
            compatibility_source,
            timestamp=timestamp,
        )
    conn.execute(
        """
        UPDATE agent_memory_evidence
        SET admission_state = ?, admission_reason = ?,
            admission_revision = admission_revision + 1,
            admission_updated_at_ms = ?,
            forgotten_at_ms = CASE WHEN ? = 'forgotten' THEN ? ELSE NULL END
        WHERE evidence_id = ?
        """,
        (state, reason, timestamp, state, timestamp, identifier),
    )
    event_id = f"evidence-admission:{uuid.uuid4()}"
    source_event_id = ""
    source_previous = ""
    source_new = ""
    if compatibility_source is not None:
        source_previous = str(compatibility_source["disposition"])
        source_new = {
            "candidate": "pending",
            "admitted": "remember",
            "needs_review": "needs_review",
            "rejected": "not_for_memory",
            "forgotten": "not_for_memory",
        }[state]
        if source_previous != source_new or str(
            compatibility_source["disposition_reason"] or ""
        ) != reason:
            source_event_id = f"memory-disposition:{uuid.uuid4()}"
            conn.execute(
                """
                UPDATE agent_memory_sources
                SET disposition = ?, disposition_reason = ?,
                    disposition_updated_at_ms = ?, processed_at_ms = ?,
                    curation_run_id = ?
                WHERE source_id = ?
                """,
                (
                    source_new,
                    reason,
                    timestamp,
                    timestamp,
                    compact_whitespace(run_id),
                    str(compatibility_source["source_id"]),
                ),
            )
            source_actor = {
                "luna": "model",
                "migration": "system",
            }.get(actor, actor)
            conn.execute(
                """
                INSERT INTO memory_source_disposition_events(
                    event_id, source_id, previous_disposition, new_disposition,
                    reason_code, actor_kind, run_id, created_at_ms,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_event_id,
                    str(compatibility_source["source_id"]),
                    source_previous,
                    source_new,
                    reason,
                    source_actor,
                    compact_whitespace(run_id),
                    timestamp,
                    json.dumps(
                        {"evidenceAdmissionEventId": event_id},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        if actor in {"user", "rollback"}:
            invalidate_source_review_drafts(
                conn,
                source_id=str(compatibility_source["source_id"]),
                timestamp=timestamp,
            )
            if state in {"candidate", "admitted", "needs_review"}:
                updated_source = conn.execute(
                    "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                    (str(compatibility_source["source_id"]),),
                ).fetchone()
                if updated_source is not None:
                    rewind_curation_cursors_for_source(
                        conn,
                        source=updated_source,
                        timestamp=timestamp,
                    )
    event_metadata = dict(metadata or {})
    event_metadata.setdefault(
        "previousAdmissionReason",
        str(row["admission_reason"] or ""),
    )
    conn.execute(
        """
        INSERT INTO memory_evidence_admission_events(
            event_id, evidence_id, previous_state, new_state, reason_code,
            actor_kind, run_id, source_disposition_event_id,
            source_previous_disposition, source_new_disposition,
            created_at_ms, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            identifier,
            previous,
            state,
            reason,
            actor,
            compact_whitespace(run_id),
            source_event_id,
            source_previous,
            source_new,
            timestamp,
            json.dumps(
                event_metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    conn.execute(
        """
        UPDATE input_capture_receipts
        SET evidence_state = ?, evidence_reason = ?, evidence_id = ?
        WHERE evidence_id = ?
           OR capture_id = (
               SELECT source_id FROM agent_memory_evidence WHERE evidence_id = ?
           )
        """,
        (state, reason, identifier, identifier, identifier),
    )
    return {
        "changed": True,
        "eventId": event_id,
        "evidenceId": identifier,
        "previousState": previous,
        "admissionState": state,
        "reason": reason,
        "sourceId": (
            str(compatibility_source["source_id"])
            if compatibility_source is not None
            else ""
        ),
        "sourceDisposition": source_new,
    }


def rollback_evidence_admissions_for_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    created_at_ms: int,
) -> dict[str, object]:
    """Restore Evidence changed by one run without overwriting newer decisions.

    A curation run can touch Evidence before it writes an Atom. Rollback is
    therefore run-scoped and compares the latest admission event before doing
    anything. A later user/model decision wins and is reported as guarded.
    """

    normalized_run_id = compact_whitespace(run_id)
    if not normalized_run_id:
        raise ValueError("Evidence admission rollback run_id is required")
    rows = conn.execute(
        """
        SELECT event_id, evidence_id, previous_state, new_state,
               created_at_ms, metadata_json
        FROM memory_evidence_admission_events
        WHERE run_id = ?
        ORDER BY evidence_id, created_at_ms, event_id
        """,
        (normalized_run_id,),
    ).fetchall()
    by_evidence: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_evidence.setdefault(str(row["evidence_id"]), []).append(row)

    restored: list[str] = []
    guarded: list[str] = []
    for evidence_id, events in by_evidence.items():
        first = events[0]
        last = events[-1]
        latest = conn.execute(
            """
            SELECT event_id
            FROM memory_evidence_admission_events
            WHERE evidence_id = ?
            ORDER BY created_at_ms DESC, event_id DESC
            LIMIT 1
            """,
            (evidence_id,),
        ).fetchone()
        current = conn.execute(
            """
            SELECT admission_state
            FROM agent_memory_evidence
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
        if (
            latest is None
            or current is None
            or str(latest["event_id"]) != str(last["event_id"])
            or str(current["admission_state"]) != str(last["new_state"])
        ):
            guarded.append(evidence_id)
            continue
        first_metadata = _json_object(first["metadata_json"])
        previous_reason = compact_whitespace(
            str(first_metadata.get("previousAdmissionReason") or "")
        )[:160]
        transition_evidence_admission(
            conn,
            evidence_id,
            new_state=str(first["previous_state"]),
            reason_code=previous_reason or "curation_run_rolled_back",
            actor_kind="rollback",
            created_at_ms=max(0, int(created_at_ms)),
            run_id=f"rollback:{normalized_run_id}",
            metadata={
                "rolledBackRunId": normalized_run_id,
                "rolledBackAdmissionEventId": str(last["event_id"]),
            },
        )
        restored.append(evidence_id)
    return {
        "schemaVersion": "rag-ime.memory-evidence-admission-rollback.v1",
        "ok": not guarded,
        "runId": normalized_run_id,
        "restoredEvidenceIds": restored,
        "guardedEvidenceIds": guarded,
    }


def _assert_admittable(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    if str(row["status"]) != "active":
        raise ValueError("tombstoned Evidence cannot be admitted")
    if str(row["evidence_domain"]) != PERSONAL_MEMORY_DOMAIN:
        raise ValueError("only personal Memory Evidence can be admitted")
    origin = str(row["origin_kind"])
    if origin not in PERSONAL_EVIDENCE_ORIGINS:
        raise ValueError("Evidence origin is not eligible for personal Memory")
    if str(row["scope_mode"]) != "authoritative":
        raise ValueError("quarantined or legacy Evidence cannot be admitted")
    if str(row["knowledge_domain"]) != PERSONAL_MEMORY_DOMAIN:
        raise ValueError("Evidence knowledge domain is not personal Memory")
    if str(row["owner_kind"]) != "user" or str(row["owner_id"]) != "default":
        raise ValueError("personal Memory Evidence must use the user owner")

    links = conn.execute(
        """
        SELECT link.input_event_id, link.content_sha256,
               event.committed_text, event.source
        FROM memory_evidence_input_event_links AS link
        JOIN input_events AS event ON event.id = link.input_event_id
        WHERE link.evidence_id = ? AND link.relation = 'source'
        ORDER BY link.ordinal, link.input_event_id
        """,
        (str(row["evidence_id"]),),
    ).fetchall()
    if not links:
        raise ValueError("personal Memory Evidence requires a normalized source link")
    if any(str(link["content_sha256"]) != str(row["content_sha256"]) for link in links):
        raise ValueError("Evidence source hash does not match canonical content")

    if origin in {"capture_v2_input", "capture_v2_voice"}:
        channel = "input_method" if origin == "capture_v2_input" else "voice"
        receipt = conn.execute(
            """
            SELECT 1
            FROM input_capture_receipts
            WHERE capture_id = ? AND input_event_id = ?
              AND channel = ? AND boundary_confidence = 'strong'
              AND outcome = 'stored'
            LIMIT 1
            """,
            (str(row["source_id"]), int(links[0]["input_event_id"]), channel),
        ).fetchone()
        if receipt is None:
            raise ValueError("capture-v2 Evidence is missing its strong storage receipt")
    elif origin == "explicit_user_memory":
        hint = conn.execute(
            """
            SELECT 1
            FROM memory_capture_hints
            WHERE source_id = ? AND status = 'active'
            LIMIT 1
            """,
            (str(row["source_id"]),),
        ).fetchone()
        if hint is None:
            raise ValueError("explicit Memory Evidence is missing its active capture hint")
    elif origin == "applied_personal_receipt":
        metadata = _json_object(row["metadata_json"])
        if metadata.get("applied") is not True or metadata.get("personalMemoryEligible") is not True:
            raise ValueError("Tool receipt is not explicitly legal personal Memory Evidence")
    elif origin == "legacy_untyped_input":
        _assert_historical_promotion_receipt(conn, row, links)


def _assert_historical_promotion_receipt(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    links: list[sqlite3.Row],
) -> None:
    if str(row["trust_class"]) != "user_claim":
        raise ValueError("historical promotion must preserve user-claim trust")
    if str(row["boundary_kind"]) != "historical_reconstruction":
        raise ValueError("historical promotion has the wrong reconstruction boundary")
    if len(links) != 1:
        raise ValueError("historical promotion requires exactly one source event")
    receipt = conn.execute(
        """
        SELECT promotion.*, legacy.status AS legacy_status,
               legacy.origin_kind AS legacy_origin_kind,
               legacy.evidence_domain AS legacy_evidence_domain,
               legacy.scope_mode AS legacy_scope_mode,
               legacy.knowledge_domain AS legacy_knowledge_domain,
               legacy.content_sha256 AS legacy_content_sha256,
               legacy.trust_class AS legacy_trust_class,
               source.status AS source_status,
               source.source_role, source.source_kind,
               source.trust_class AS source_trust_class,
               source.owner_kind AS source_owner_kind,
               source.owner_id AS source_owner_id,
               source.input_event_id AS source_input_event_id,
               source.canonical_text_sha256 AS source_content_sha256,
               event.committed_text
        FROM memory_evidence_historical_promotion_receipts AS promotion
        JOIN agent_memory_evidence AS legacy
          ON legacy.evidence_id = promotion.legacy_evidence_id
        JOIN agent_memory_sources AS source
          ON source.source_id = promotion.source_id
        JOIN input_events AS event ON event.id = promotion.input_event_id
        WHERE promotion.promoted_evidence_id = ?
          AND promotion.authorization_kind = 'user_authorized_full_history_v1'
        LIMIT 1
        """,
        (str(row["evidence_id"]),),
    ).fetchone()
    if receipt is None:
        raise ValueError("historical promotion is missing its immutable receipt")
    event_id = int(links[0]["input_event_id"])
    digest = str(row["content_sha256"])
    if (
        int(receipt["input_event_id"]) != event_id
        or int(receipt["source_input_event_id"]) != event_id
        or str(receipt["source_id"]) != str(row["source_id"])
        or str(receipt["content_sha256"]) != digest
        or str(receipt["legacy_content_sha256"]) != digest
        or str(receipt["source_content_sha256"]) != digest
        or hashlib.sha256(str(receipt["committed_text"]).encode("utf-8")).hexdigest()
        != digest
    ):
        raise ValueError("historical promotion receipt does not match its source")
    if (
        str(receipt["legacy_status"]) != "active"
        or str(receipt["legacy_origin_kind"]) != "legacy_untyped_input"
        or str(receipt["legacy_evidence_domain"])
        not in {"audit_context", "personal_memory"}
        or str(receipt["legacy_scope_mode"]) != "legacy"
        or str(receipt["legacy_knowledge_domain"]) != "legacy"
        or str(receipt["legacy_trust_class"]) != "user_claim"
        or str(receipt["source_status"]) != "active"
        or str(receipt["source_role"]) != "user"
        or str(receipt["source_kind"]) != "user_final"
        or str(receipt["source_trust_class"]) != "user_claim"
        or str(receipt["source_owner_kind"]) != "user"
        or str(receipt["source_owner_id"]) != "default"
    ):
        raise ValueError("historical promotion source is not eligible")
    hidden = conn.execute(
        """
        SELECT 1
        FROM memory_tombstones AS tombstone
        WHERE tombstone.active = 1
          AND (
              (tombstone.target_type = 'memory_id'
               AND tombstone.target_value IN (?, ?))
              OR
              (tombstone.target_type = 'source_event_id'
               AND tombstone.target_value = ?)
          )
        LIMIT 1
        """,
        (
            str(receipt["legacy_evidence_id"]),
            f"event:{event_id}",
            str(event_id),
        ),
    ).fetchone()
    if hidden is not None:
        raise ValueError("forgotten historical Evidence cannot be promoted")


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _sql_alias(value: str) -> str:
    alias = compact_whitespace(value)
    if not _SQL_ALIAS_RE.fullmatch(alias):
        raise ValueError("invalid SQL alias")
    return alias


__all__ = [
    "ADMISSION_ACTORS",
    "ADMISSION_STATES",
    "PERSONAL_EVIDENCE_ORIGINS",
    "PERSONAL_MEMORY_DOMAIN",
    "admitted_personal_evidence_sql",
    "curatable_personal_evidence_sql",
    "event_has_admitted_personal_evidence_sql",
    "evidence_is_admitted",
    "rollback_evidence_admissions_for_run",
    "transition_evidence_admission",
]
