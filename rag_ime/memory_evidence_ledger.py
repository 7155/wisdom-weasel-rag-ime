from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from .memory_ingest import looks_sensitive
from .text_utils import compact_whitespace


INPUT_MEMORY_LEDGER_SESSION_ID = "system:input-memory-evidence-ledger"
_INPUT_MEMORY_LEDGER_ROLE_ID = "system-input-memory-ledger"
_USER_FINAL_SOURCES = frozenset(
    {
        "debug_page_commit",
        "manual_commit",
        "squirrel_rime_commit_burst",
        "voice_final",
        "voice_streaming_asr",
    }
)
_EXPLICIT_MEMORY_SOURCES = frozenset({"squirrel_assistant_remember"})
_ELIGIBLE_SOURCES = tuple(sorted(_USER_FINAL_SOURCES | _EXPLICIT_MEMORY_SOURCES))


@dataclass(frozen=True)
class InputEvidencePolicy:
    source_kind: str
    trust_class: str


def input_event_evidence_policy(
    source: str,
    *,
    tags: Iterable[str] = (),
) -> InputEvidencePolicy | None:
    """Classify only final human input and explicit remember actions.

    Generated side-candidate text, eval fixtures, imported history and optimizer
    output intentionally stay outside this ledger. They must not become personal
    memory merely because they passed through ``input_events``.
    """

    del tags  # Reserved for additive, explicitly reviewed source policies.
    normalized = compact_whitespace(source).lower()
    if normalized in _EXPLICIT_MEMORY_SOURCES:
        return InputEvidencePolicy(
            source_kind="explicit_memory",
            trust_class="explicit_command",
        )
    if normalized in _USER_FINAL_SOURCES:
        return InputEvidencePolicy(
            source_kind="user_final",
            trust_class="user_claim",
        )
    return None


def checkpoint_input_event_evidence(
    conn: sqlite3.Connection,
    *,
    event_id: int,
    created_at_ms: int,
    source: str,
    committed_text: str,
    project: str,
    app: str = "",
    provider_name: str = "",
    tags: Iterable[str] = (),
) -> dict[str, object]:
    """Link a persisted foreground input to the reversible memory ledger."""

    normalized_tags = tuple(
        dict.fromkeys(
            compact_whitespace(str(tag))
            for tag in tags
            if compact_whitespace(str(tag))
        )
    )
    policy = input_event_evidence_policy(source, tags=normalized_tags)
    if policy is None:
        return {
            "stored": False,
            "status": "source_not_eligible",
            "sourceId": "",
        }

    existing = conn.execute(
        """
        SELECT source_id, disposition
        FROM agent_memory_sources
        WHERE input_event_id = ?
        ORDER BY created_at_ms ASC, source_id ASC
        LIMIT 1
        """,
        (max(1, int(event_id)),),
    ).fetchone()
    if existing is not None:
        return {
            "stored": False,
            "status": "already_checkpointed",
            "sourceId": str(existing["source_id"]),
            "disposition": str(existing["disposition"]),
        }

    canonical = compact_whitespace(committed_text)
    if not canonical:
        return {
            "stored": False,
            "status": "empty_input",
            "sourceId": "",
        }

    timestamp = max(0, int(created_at_ms))
    sensitive = looks_sensitive(canonical)
    disposition = "not_for_memory" if sensitive else "pending"
    reason = "sensitive_input" if sensitive else ""
    source_id = f"input-memory:{max(1, int(event_id))}"
    _ensure_input_memory_ledger_session(conn, timestamp=timestamp)
    metadata = {
        "ledgerVersion": 1,
        "transportSource": compact_whitespace(source),
        "project": compact_whitespace(project),
        "app": compact_whitespace(app),
        "providerName": compact_whitespace(provider_name),
        "sourceMetadataTags": list(normalized_tags[:24]),
    }
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO agent_memory_sources(
            source_id, session_id, pi_entry_id, input_event_id, source_role,
            source_revision, canonical_text_sha256, status, turn_id,
            approval_id, created_at_ms, owner_kind, owner_id, role_id,
            role_version, source_kind, trust_class, disposition,
            disposition_reason, disposition_updated_at_ms, processed_at_ms,
            metadata_json
        ) VALUES (
            ?, ?, ?, ?, 'user', 1, ?, 'active', '', '', ?,
            'user', 'default', ?, '1', ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            source_id,
            INPUT_MEMORY_LEDGER_SESSION_ID,
            f"input-event:{max(1, int(event_id))}",
            max(1, int(event_id)),
            digest,
            timestamp,
            _INPUT_MEMORY_LEDGER_ROLE_ID,
            policy.source_kind,
            policy.trust_class,
            disposition,
            reason,
            timestamp,
            timestamp if sensitive else None,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ),
    )
    conn.execute(
        """
        UPDATE memory_items
        SET owner_kind = 'user', owner_id = 'default'
        WHERE source_event_id = ?
        """,
        (max(1, int(event_id)),),
    )
    conn.execute(
        """
        INSERT INTO memory_source_disposition_events(
            event_id, source_id, previous_disposition, new_disposition,
            reason_code, actor_kind, run_id, created_at_ms, metadata_json
        ) VALUES (?, ?, '', ?, ?, ?, '', ?, '{}')
        """,
        (
            f"memory-disposition:input:{max(1, int(event_id))}:initial",
            source_id,
            disposition,
            reason or "checkpoint_created",
            "rule" if sensitive else "system",
            timestamp,
        ),
    )
    return {
        "stored": True,
        "status": "checkpointed",
        "sourceId": source_id,
        "sourceKind": policy.source_kind,
        "trustClass": policy.trust_class,
        "disposition": disposition,
    }


def backfill_input_event_evidence(
    conn: sqlite3.Connection,
    *,
    project: str = "",
    limit: int = 5000,
) -> dict[str, object]:
    """Idempotently migrate eligible historical foreground inputs in batches."""

    normalized_project = compact_whitespace(project)
    bounded_limit = max(1, min(int(limit), 50_000))
    placeholders = ",".join("?" for _ in _ELIGIBLE_SOURCES)
    rows = conn.execute(
        f"""
        SELECT e.id, e.created_at_ms, e.source, e.committed_text, e.project,
               e.app, e.provider_name, e.tags_json
        FROM input_events AS e
        WHERE lower(e.source) IN ({placeholders})
          AND (? = '' OR e.project = ? OR e.project = '')
          AND length(trim(e.committed_text, ' ' || char(9) || char(10) || char(13))) > 0
          AND NOT EXISTS (
              SELECT 1
              FROM agent_memory_sources AS memory_source
              WHERE memory_source.input_event_id = e.id
          )
        ORDER BY e.id ASC
        LIMIT ?
        """,  # noqa: S608 - placeholders are generated from a fixed allowlist.
        (*_ELIGIBLE_SOURCES, normalized_project, normalized_project, bounded_limit),
    ).fetchall()
    stored = 0
    sensitive = 0
    for row in rows:
        tags = _json_strings(row["tags_json"])
        result = checkpoint_input_event_evidence(
            conn,
            event_id=int(row["id"]),
            created_at_ms=int(row["created_at_ms"] or 0),
            source=str(row["source"] or ""),
            committed_text=str(row["committed_text"] or ""),
            project=str(row["project"] or ""),
            app=str(row["app"] or ""),
            provider_name=str(row["provider_name"] or ""),
            tags=tags,
        )
        if bool(result["stored"]):
            stored += 1
        if result.get("disposition") == "not_for_memory":
            sensitive += 1
    remaining = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM input_events AS e
            WHERE lower(e.source) IN ({placeholders})
              AND (? = '' OR e.project = ? OR e.project = '')
              AND length(trim(e.committed_text, ' ' || char(9) || char(10) || char(13))) > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM agent_memory_sources AS memory_source
                  WHERE memory_source.input_event_id = e.id
              )
            """,  # noqa: S608 - placeholders are generated from a fixed allowlist.
            (*_ELIGIBLE_SOURCES, normalized_project, normalized_project),
        ).fetchone()[0]
    )
    return {
        "scannedCount": len(rows),
        "storedCount": stored,
        "sensitiveCount": sensitive,
        "remainingCount": remaining,
    }


def _ensure_input_memory_ledger_session(
    conn: sqlite3.Connection,
    *,
    timestamp: int,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO agent_sessions(
            id, agent_id, title, session_mode, role_id, role_version,
            model_profile, thinking_level, tool_profile_version,
            workspace_roots_json, shell_policy_version, session_kind,
            created_at_ms, updated_at_ms, last_opened_at_ms, status,
            archived_at_ms, message_count, last_message_preview
        ) VALUES (
            ?, ?, 'Input memory evidence ledger', 'assistant', ?, '1',
            'none', 'off', 'none', '[]', 'assistant-no-shell-v1',
            'subagent_runtime', ?, ?, ?, 'archived', ?, 0, ''
        )
        """,
        (
            INPUT_MEMORY_LEDGER_SESSION_ID,
            INPUT_MEMORY_LEDGER_SESSION_ID,
            _INPUT_MEMORY_LEDGER_ROLE_ID,
            timestamp,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def _json_strings(value: object) -> tuple[str, ...]:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(
        compact_whitespace(str(item))
        for item in decoded
        if compact_whitespace(str(item))
    )
