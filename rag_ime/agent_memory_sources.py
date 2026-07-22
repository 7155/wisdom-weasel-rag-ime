from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .agent_sessions import AgentSessionStore
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .knowledge_scope import quarantine_scope_issue, session_knowledge_scope
from .memory_evidence_policy import memory_evidence_exclusion_reason
from .memory_ingest import looks_sensitive, sync_event_to_memory_v2
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace


_OWNER_KINDS = frozenset({"user", "shared", "agent", "session", "room"})
_SOURCE_KINDS = frozenset(
    {
        "user_final",
        "tool_receipt",
        "session_compaction",
        "session_digest",
        "explicit_memory",
    }
)
_TRUST_CLASSES = frozenset(
    {
        "user_claim",
        "applied_receipt",
        "session_summary",
        "assistant_claim",
        "explicit_command",
    }
)
_DISPOSITIONS = frozenset(
    {
        "pending",
        "remember",
        "not_for_memory",
        "needs_review",
        "consolidated",
        "expired",
    }
)
_DISPOSITION_ACTORS = frozenset({"rule", "model", "user", "system", "rollback"})
_CURATION_ELIGIBLE_DISPOSITIONS = frozenset({"pending", "remember", "needs_review"})


class AgentMemorySourceStore:
    """Immutable Agent evidence plus a reversible curation disposition."""

    def __init__(self, db_path: str | Path, *, project: str = "") -> None:
        self.db_path = Path(db_path)
        self.project = compact_whitespace(project)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def checkpoint_user_message(
        self,
        *,
        session_id: str,
        pi_entry_id: str,
        turn_id: str,
        text: str,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        canonical = compact_whitespace(text)
        if not canonical:
            raise ValueError("final user message must not be empty")
        if reason := memory_evidence_exclusion_reason(canonical):
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": f"skipped_{reason}",
            }
        if looks_sensitive(canonical):
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "skipped_sensitive",
            }
        entry_id = compact_whitespace(pi_entry_id) or compact_whitespace(turn_id)
        if not entry_id:
            raise ValueError("Pi entry id or turn id is required")
        return self._checkpoint(
            session_id=session_id,
            pi_entry_id=entry_id,
            turn_id=turn_id,
            source_role="user",
            source_kind="user_final",
            trust_class="user_claim",
            owner_kind="user",
            owner_id="default",
            source="pi_agent_user",
            canonical=canonical,
            tags=("agent-session", "final-user-message"),
            created_at_ms=created_at_ms,
        )

    def checkpoint_tool_receipt(
        self,
        approval: Mapping[str, object],
        *,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        receipt = approval.get("receipt") if isinstance(approval.get("receipt"), Mapping) else {}
        if str(approval.get("state") or "") != "applied" or receipt.get("mutationApplied") is not True:
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "skipped_unapplied",
            }
        summary = compact_whitespace(str(receipt.get("summary") or ""))
        approval_id = compact_whitespace(str(approval.get("approvalId") or ""))
        if not summary or not approval_id:
            raise ValueError("applied tool receipt requires summary and approvalId")
        return self._checkpoint(
            session_id=str(approval.get("sessionId") or ""),
            pi_entry_id=f"approval:{approval_id}",
            turn_id="",
            approval_id=approval_id,
            source_role="tool_receipt",
            source_kind="tool_receipt",
            trust_class="applied_receipt",
            owner_kind="shared",
            owner_id=self.project or "default",
            source="pi_agent_tool_receipt",
            canonical=summary,
            tags=("agent-session", "approved-tool-receipt"),
            created_at_ms=created_at_ms,
        )

    def checkpoint_compaction(
        self,
        *,
        session_id: str,
        result: Mapping[str, object],
        trigger: str,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        compacted = _compaction_payload(result)
        summary = compact_whitespace(str(compacted.get("summary") or ""))
        if not summary:
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "skipped_missing_summary",
            }
        if looks_sensitive(summary):
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "skipped_sensitive",
            }
        normalized_trigger = compact_whitespace(trigger).lower() or "automatic"
        coverage_start = compact_whitespace(
            str(
                compacted.get("coverageStartEntryId")
                or compacted.get("firstSummarizedEntryId")
                or ""
            )
        )
        coverage_end = compact_whitespace(
            str(
                compacted.get("coverageEndEntryId")
                or compacted.get("lastSummarizedEntryId")
                or compacted.get("firstKeptEntryId")
                or ""
            )
        )
        digest = hashlib.sha256(
            f"{coverage_start}\0{coverage_end}\0{summary}".encode("utf-8")
        ).hexdigest()
        metadata = {
            "trigger": normalized_trigger[:40],
            "firstKeptEntryId": compact_whitespace(
                str(compacted.get("firstKeptEntryId") or "")
            ),
            "tokensBefore": _optional_non_negative_int(compacted.get("tokensBefore")),
            "estimatedTokensAfter": _optional_non_negative_int(
                compacted.get("estimatedTokensAfter")
            ),
            "coverageEndExclusive": bool(
                compacted.get("firstKeptEntryId")
                and not compacted.get("lastSummarizedEntryId")
                and not compacted.get("coverageEndEntryId")
            ),
        }
        return self._checkpoint(
            session_id=session_id,
            pi_entry_id=f"compaction:{digest[:32]}",
            turn_id="",
            # source_role is the legacy two-value compatibility column. The
            # authoritative classification is source_kind.
            source_role="user",
            source_kind="session_compaction",
            trust_class="session_summary",
            owner_kind="agent",
            owner_id="",
            source="pi_agent_compaction",
            canonical=summary,
            tags=("agent-session", "session-compaction"),
            coverage_start_entry_id=coverage_start,
            coverage_end_entry_id=coverage_end,
            metadata=metadata,
            created_at_ms=created_at_ms,
        )

    def checkpoint_external_summary(
        self,
        *,
        provider: str,
        external_ref: str,
        text: str,
        tier: str,
        source_occurred_at_ms: int,
        metadata: Mapping[str, object] | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Checkpoint an Agent-curated external digest without importing its raw transcript."""

        normalized_provider = compact_whitespace(provider).casefold()
        if not normalized_provider or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in normalized_provider
        ):
            raise ValueError("external memory provider must be a stable identifier")
        normalized_ref = compact_whitespace(external_ref)[:500]
        canonical = compact_whitespace(text)
        normalized_tier = compact_whitespace(tier).casefold()[:80]
        if not normalized_ref:
            raise ValueError("external memory reference is required")
        if not canonical:
            raise ValueError("external memory summary must not be empty")
        if contains_sensitive_content(canonical):
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "skipped_sensitive",
            }

        timestamp = int(
            created_at_ms if created_at_ms is not None else time.time() * 1000
        )
        occurred_at_ms = max(0, int(source_occurred_at_ms))
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        session_id = self._external_source_session(
            normalized_provider,
            created_at_ms=timestamp,
        )
        external_metadata = {
            **dict(metadata or {}),
            "externalProvider": normalized_provider,
            "externalRef": normalized_ref,
            "externalTier": normalized_tier or "summary",
            "agentCurated": True,
            "contentSha256": content_hash,
            "sourceOccurredAtMs": occurred_at_ms,
            "rawTranscriptImported": False,
        }
        pi_entry_id = (
            "external:"
            + normalized_provider
            + ":"
            + hashlib.sha256(normalized_ref.encode("utf-8")).hexdigest()[:20]
            + ":"
            + content_hash[:20]
            + ":"
            + hashlib.sha256(str(occurred_at_ms).encode("ascii")).hexdigest()[:12]
        )
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM agent_memory_sources
                WHERE session_id = ? AND source_kind = 'session_digest'
                  AND status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = ?
                  AND json_extract(metadata_json, '$.externalRef') = ?
                  AND json_extract(metadata_json, '$.externalTier') = ?
                  AND CAST(
                        json_extract(metadata_json, '$.sourceOccurredAtMs')
                        AS INTEGER
                      ) = ?
                  AND canonical_text_sha256 = ?
                ORDER BY created_at_ms DESC
                LIMIT 1
                """,
                (
                    session_id,
                    normalized_provider,
                    normalized_ref,
                    normalized_tier or "summary",
                    occurred_at_ms,
                    content_hash,
                ),
            ).fetchone()
            if existing is not None:
                # External importers keep filesystem observations in metadata so
                # later runs can avoid reopening unchanged curated summaries.
                # The evidence text and revision stay immutable.
                existing_metadata = _loaded_json_object(existing["metadata_json"])
                merged_metadata = {**existing_metadata, **external_metadata}
                if merged_metadata != existing_metadata:
                    conn.execute(
                        """
                        UPDATE agent_memory_sources
                        SET metadata_json = ?
                        WHERE source_id = ?
                        """,
                        (
                            _json_object(merged_metadata),
                            str(existing["source_id"]),
                        ),
                    )
                    existing = conn.execute(
                        "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                        (str(existing["source_id"]),),
                    ).fetchone()
        if existing is not None:
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": True,
                "stored": False,
                "status": "already_checkpointed",
                "source": _source_payload(existing),
                "supersededSourceIds": [],
            }

        result = self._checkpoint(
            session_id=session_id,
            pi_entry_id=pi_entry_id,
            turn_id="",
            source_role="user",
            source_kind="session_digest",
            trust_class="session_summary",
            owner_kind="user",
            owner_id="default",
            source=f"{normalized_provider}_memory_index",
            canonical=canonical,
            tags=(
                "external-memory",
                normalized_provider,
                "agent-curated",
                normalized_tier or "summary",
            ),
            metadata=external_metadata,
            created_at_ms=timestamp,
        )
        source = result.get("source")
        new_source_id = (
            str(source.get("sourceId") or "")
            if isinstance(source, Mapping)
            else ""
        )
        if not new_source_id:
            result["supersededSourceIds"] = []
            return result

        superseded_ids: list[str] = []
        with self._connect() as conn:
            previous_rows = conn.execute(
                """
                SELECT source_id, input_event_id, disposition
                FROM agent_memory_sources
                WHERE session_id = ? AND source_kind = 'session_digest'
                  AND status = 'active' AND source_id <> ?
                  AND json_extract(metadata_json, '$.externalProvider') = ?
                  AND json_extract(metadata_json, '$.externalRef') = ?
                ORDER BY created_at_ms ASC
                """,
                (
                    session_id,
                    new_source_id,
                    normalized_provider,
                    normalized_ref,
                ),
            ).fetchall()
            for previous in previous_rows:
                previous_id = str(previous["source_id"])
                superseded_ids.append(previous_id)
                conn.execute(
                    """
                    UPDATE agent_memory_sources
                    SET status = 'superseded', superseded_at_ms = ?,
                        disposition = 'expired',
                        disposition_reason = 'external_source_replaced',
                        disposition_updated_at_ms = ?, processed_at_ms = ?
                    WHERE source_id = ?
                    """,
                    (timestamp, timestamp, timestamp, previous_id),
                )
                conn.execute(
                    """
                    INSERT INTO memory_source_disposition_events(
                        event_id, source_id, previous_disposition,
                        new_disposition, reason_code, actor_kind,
                        created_at_ms, metadata_json
                    ) VALUES (?, ?, ?, 'expired', 'external_source_replaced',
                              'system', ?, ?)
                    """,
                    (
                        f"memory-disposition:{uuid.uuid4()}",
                        previous_id,
                        str(previous["disposition"]),
                        timestamp,
                        _json_object(
                            {
                                "externalProvider": normalized_provider,
                                "externalRef": normalized_ref,
                                "replacementSourceId": new_source_id,
                            }
                        ),
                    ),
                )
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status = 'superseded', updated_at_ms = ?
                    WHERE source_event_id = ?
                    """,
                    (timestamp, int(previous["input_event_id"])),
                )
        result["supersededSourceIds"] = superseded_ids
        return result

    def active_external_summary_index(
        self,
        *,
        provider: str,
    ) -> dict[tuple[str, str], dict[str, object]]:
        """Return the latest active external revisions for incremental discovery."""

        normalized_provider = compact_whitespace(provider).casefold()
        if not normalized_provider:
            raise ValueError("external memory provider is required")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, canonical_text_sha256, created_at_ms,
                       metadata_json
                FROM agent_memory_sources
                WHERE source_kind = 'session_digest' AND status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = ?
                ORDER BY created_at_ms DESC, source_id DESC
                """,
                (normalized_provider,),
            ).fetchall()
        index: dict[tuple[str, str], dict[str, object]] = {}
        for row in rows:
            metadata = _loaded_json_object(row["metadata_json"])
            external_ref = compact_whitespace(
                str(metadata.get("externalRef") or "")
            )
            tier = compact_whitespace(
                str(metadata.get("externalTier") or "summary")
            ).casefold()
            key = (external_ref, tier)
            if not external_ref or key in index:
                continue
            index[key] = {
                **metadata,
                "sourceId": str(row["source_id"]),
                "canonicalTextSha256": str(row["canonical_text_sha256"]),
                "createdAtMs": int(row["created_at_ms"]),
            }
        return index

    def expire_external_summaries_not_in_refs(
        self,
        *,
        provider: str,
        retained_external_refs: set[str],
        tier: str,
        reason_code: str,
        created_at_ms: int | None = None,
    ) -> list[str]:
        """Expire external evidence that has fallen out of a bounded source view."""

        normalized_provider = compact_whitespace(provider).casefold()
        normalized_tier = compact_whitespace(tier).casefold()
        normalized_reason = compact_whitespace(reason_code).casefold()
        retained = {
            compact_whitespace(value)
            for value in retained_external_refs
            if compact_whitespace(value)
        }
        if not normalized_provider or not normalized_tier:
            raise ValueError("external provider and tier are required")
        if not normalized_reason:
            raise ValueError("external expiry reason is required")
        timestamp = int(
            created_at_ms if created_at_ms is not None else time.time() * 1000
        )
        expired_ids: list[str] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, input_event_id, disposition, metadata_json
                FROM agent_memory_sources
                WHERE source_kind = 'session_digest' AND status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = ?
                  AND json_extract(metadata_json, '$.externalTier') = ?
                ORDER BY created_at_ms ASC, source_id ASC
                """,
                (normalized_provider, normalized_tier),
            ).fetchall()
            for row in rows:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
                external_ref = compact_whitespace(
                    str(metadata.get("externalRef") or "")
                )
                if external_ref in retained:
                    continue
                source_id = str(row["source_id"])
                expired_ids.append(source_id)
                conn.execute(
                    """
                    UPDATE agent_memory_sources
                    SET status = 'superseded', superseded_at_ms = ?,
                        disposition = 'expired',
                        disposition_reason = ?,
                        disposition_updated_at_ms = ?, processed_at_ms = ?
                    WHERE source_id = ?
                    """,
                    (
                        timestamp,
                        normalized_reason,
                        timestamp,
                        timestamp,
                        source_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO memory_source_disposition_events(
                        event_id, source_id, previous_disposition,
                        new_disposition, reason_code, actor_kind,
                        created_at_ms, metadata_json
                    ) VALUES (?, ?, ?, 'expired', ?, 'system', ?, ?)
                    """,
                    (
                        f"memory-disposition:{uuid.uuid4()}",
                        source_id,
                        str(row["disposition"]),
                        normalized_reason,
                        timestamp,
                        _json_object(
                            {
                                "externalProvider": normalized_provider,
                                "externalRef": external_ref,
                                "externalTier": normalized_tier,
                            }
                        ),
                    ),
                )
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status = 'superseded', updated_at_ms = ?
                    WHERE source_event_id = ?
                    """,
                    (timestamp, int(row["input_event_id"])),
                )
        return expired_ids

    def _external_source_session(
        self,
        provider: str,
        *,
        created_at_ms: int,
    ) -> str:
        role_id = f"external-memory:{provider}"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM agent_sessions
                WHERE role_id = ? AND session_kind = 'subagent_runtime'
                ORDER BY created_at_ms ASC
                LIMIT 1
                """,
                (role_id,),
            ).fetchone()
        if row is not None:
            return str(row["id"])

        sessions = AgentSessionStore(self.db_path)
        session = sessions.create(
            title=f"{provider.title()} 外部记忆源",
            role_id=role_id,
            role_version="1",
            model_profile="external-memory-index",
            project_context_enabled=False,
            session_kind="subagent_runtime",
            created_at_ms=created_at_ms,
        )
        session_id = str(session["id"])
        sessions.archive(
            session_id,
            updated_at_ms=created_at_ms,
        )
        return session_id

    def list_for_session(self, session_id: str, *, limit: int = 100) -> list[dict[str, object]]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_memory_sources
                WHERE session_id = ?
                ORDER BY created_at_ms DESC, source_id DESC
                LIMIT ?
                """,
                (session_id, bounded_limit),
            ).fetchall()
        return [_source_payload(row) for row in rows]

    def get(self, source_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return _source_payload(row)

    def capture_hint(
        self,
        *,
        session_id: str,
        kind: str,
        claim: str,
        scope: str,
        reason: str,
        source_id: str = "",
        evidence_ids: list[str] | tuple[str, ...] = (),
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Attach a non-authoritative curation hint to current user evidence."""

        normalized_session = compact_whitespace(session_id)
        normalized_kind = compact_whitespace(kind).lower()
        normalized_scope = compact_whitespace(scope).lower() or "project"
        normalized_claim = compact_whitespace(claim)[:800]
        normalized_reason = compact_whitespace(reason)[:500]
        requested_source = compact_whitespace(source_id)
        normalized_evidence = list(
            dict.fromkeys(
                compact_whitespace(str(value))
                for value in evidence_ids
                if compact_whitespace(str(value))
            )
        )[:32]
        if not normalized_session:
            raise ValueError("memory capture requires the current session")
        if normalized_kind not in {
            "preference",
            "fact",
            "decision",
            "correction",
            "pitfall",
        }:
            raise ValueError("unsupported memory capture kind")
        if normalized_scope not in {"user", "project"}:
            raise ValueError("memory capture scope must be user or project")
        if not normalized_claim or not normalized_reason:
            raise ValueError("memory capture requires claim and reason")
        if memory_evidence_exclusion_reason(normalized_claim):
            raise ValueError("memory capture claim is workflow noise or transient input")
        if looks_sensitive(normalized_claim) or contains_sensitive_content(
            f"{normalized_claim} {normalized_reason}"
        ):
            raise ValueError("sensitive content cannot be captured as a memory hint")

        timestamp = int(
            created_at_ms if created_at_ms is not None else time.time() * 1000
        )
        with self._connect() as conn:
            if requested_source:
                source = conn.execute(
                    """
                    SELECT source.source_id, source.status, source.disposition,
                           source.source_kind, source.pi_entry_id, session.role_id
                    FROM agent_memory_sources AS source
                    JOIN agent_sessions AS session ON session.id = source.session_id
                    WHERE source.source_id = ? AND source.session_id = ?
                    """,
                    (requested_source, normalized_session),
                ).fetchone()
            else:
                source = conn.execute(
                    """
                    SELECT source.source_id, source.status, source.disposition,
                           source.source_kind, source.pi_entry_id, session.role_id
                    FROM agent_memory_sources AS source
                    JOIN agent_sessions AS session ON session.id = source.session_id
                    WHERE source.session_id = ?
                      AND source.status = 'active'
                      AND source.source_kind = 'user_final'
                      AND source.disposition IN ('pending', 'remember', 'needs_review')
                    ORDER BY source.created_at_ms DESC, source.source_id DESC
                    LIMIT 1
                    """,
                    (normalized_session,),
                ).fetchone()
            if source is None:
                raise ValueError("memory capture has no active user evidence in this session")
            if (
                str(source["status"]) != "active"
                or str(source["source_kind"]) != "user_final"
                or str(source["disposition"])
                not in {"pending", "remember", "needs_review"}
            ):
                raise ValueError("memory capture source is not eligible for curation")

            if normalized_evidence:
                placeholders = ",".join("?" for _ in normalized_evidence)
                available = {
                    str(row[0])
                    for row in conn.execute(
                        f"""
                        SELECT evidence_id
                        FROM agent_memory_evidence
                        WHERE evidence_id IN ({placeholders})
                          AND session_id = ? AND status = 'active'
                          AND (? = '' OR project = ? OR project = '')
                          AND (
                              (
                                  source_kind = 'user_message'
                                  AND source_id = ?
                              )
                              OR (
                                  source_kind = 'tool_receipt'
                                  AND json_valid(metadata_json)
                                  AND json_extract(metadata_json, '$.applied') = 1
                              )
                          )
                        """,
                        (
                            *normalized_evidence,
                            normalized_session,
                            self.project,
                            self.project,
                            str(source["pi_entry_id"] or ""),
                        ),
                    ).fetchall()
                }
                if available != set(normalized_evidence):
                    raise ValueError("memory capture evidence is missing or outside this session")

            resolved_source_id = str(source["source_id"])
            hint_id = f"capture:{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO memory_capture_hints(
                    hint_id, source_id, kind, normalized_claim, scope, reason,
                    evidence_ids_json, captured_by_session_id,
                    captured_by_role_id, status, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(source_id, kind, normalized_claim) DO UPDATE SET
                    scope = excluded.scope,
                    reason = excluded.reason,
                    evidence_ids_json = excluded.evidence_ids_json,
                    captured_by_session_id = excluded.captured_by_session_id,
                    captured_by_role_id = excluded.captured_by_role_id,
                    status = 'active',
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    hint_id,
                    resolved_source_id,
                    normalized_kind,
                    normalized_claim,
                    normalized_scope,
                    normalized_reason,
                    json.dumps(normalized_evidence, ensure_ascii=False),
                    normalized_session,
                    str(source["role_id"] or ""),
                    timestamp,
                    timestamp,
                ),
            )
            stored = conn.execute(
                """
                SELECT hint_id
                FROM memory_capture_hints
                WHERE source_id = ? AND kind = ? AND normalized_claim = ?
                """,
                (resolved_source_id, normalized_kind, normalized_claim),
            ).fetchone()
        return {
            "schemaVersion": "rag-ime.memory-capture-hint.v1",
            "ok": True,
            "captured": True,
            "hintId": str(stored[0]),
            "sourceId": resolved_source_id,
            "kind": normalized_kind,
            "scope": normalized_scope,
            "createsAtom": False,
            "requiresApproval": False,
        }

    def list_for_owner(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        disposition: str = "",
        project: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        owner = _owner(owner_kind, owner_id)
        normalized_disposition = compact_whitespace(disposition)
        if normalized_disposition and normalized_disposition not in _DISPOSITIONS:
            raise ValueError("unsupported memory source disposition")
        clauses = ["s.owner_kind = ?", "s.owner_id = ?"]
        values: list[object] = [owner[0], owner[1]]
        normalized_project = (
            self.project if project is None else compact_whitespace(project)
        )
        if normalized_project:
            clauses.append("(e.project = ? OR e.project = '')")
            values.append(normalized_project)
        if normalized_disposition:
            clauses.append("s.disposition = ?")
            values.append(normalized_disposition)
        values.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT s.* FROM agent_memory_sources AS s
                JOIN input_events AS e ON e.id = s.input_event_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.created_at_ms DESC, s.source_id DESC
                LIMIT ?
                """,  # noqa: S608 - clauses are fixed above.
                tuple(values),
            ).fetchall()
        return [_source_payload(row) for row in rows]

    def set_disposition(
        self,
        source_id: str,
        *,
        disposition: str,
        reason_code: str,
        actor_kind: str,
        run_id: str = "",
        metadata: Mapping[str, object] | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_disposition = compact_whitespace(disposition)
        normalized_actor = compact_whitespace(actor_kind)
        normalized_reason = compact_whitespace(reason_code)[:120]
        if normalized_disposition not in _DISPOSITIONS:
            raise ValueError("unsupported memory source disposition")
        if normalized_actor not in _DISPOSITION_ACTORS:
            raise ValueError("unsupported memory disposition actor")
        if not normalized_reason:
            raise ValueError("memory disposition reason is required")
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise KeyError(source_id)
            previous = str(row["disposition"])
            if normalized_actor in {"user", "rollback"}:
                _assert_source_curation_not_running(
                    conn,
                    row,
                    timestamp=timestamp,
                )
            if previous == normalized_disposition and str(row["disposition_reason"]) == normalized_reason:
                return {
                    "schemaVersion": "rag-ime.agent-memory-disposition.v1",
                    "ok": True,
                    "changed": False,
                    "source": _source_payload(row),
                }
            conn.execute(
                """
                UPDATE agent_memory_sources
                SET disposition = ?, disposition_reason = ?,
                    disposition_updated_at_ms = ?, processed_at_ms = ?,
                    curation_run_id = ?
                WHERE source_id = ?
                """,
                (
                    normalized_disposition,
                    normalized_reason,
                    timestamp,
                    timestamp,
                    compact_whitespace(run_id),
                    source_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_source_disposition_events(
                    event_id, source_id, previous_disposition, new_disposition,
                    reason_code, actor_kind, run_id, created_at_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"memory-disposition:{uuid.uuid4()}",
                    source_id,
                    previous,
                    normalized_disposition,
                    normalized_reason,
                    normalized_actor,
                    compact_whitespace(run_id),
                    timestamp,
                    _json_object(metadata),
                ),
            )
            updated = conn.execute(
                "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if normalized_actor in {"user", "rollback"}:
                _invalidate_source_review_drafts(
                    conn,
                    source_id=source_id,
                    timestamp=timestamp,
                )
                if normalized_disposition in _CURATION_ELIGIBLE_DISPOSITIONS:
                    _rewind_curation_cursors_for_source(
                        conn,
                        source=updated,
                        timestamp=timestamp,
                    )
        return {
            "schemaVersion": "rag-ime.agent-memory-disposition.v1",
            "ok": True,
            "changed": True,
            "source": _source_payload(updated),
        }

    def _checkpoint(
        self,
        *,
        session_id: str,
        pi_entry_id: str,
        source_role: str,
        source_kind: str,
        trust_class: str,
        owner_kind: str,
        owner_id: str,
        source: str,
        canonical: str,
        tags: tuple[str, ...],
        turn_id: str = "",
        approval_id: str = "",
        coverage_start_entry_id: str = "",
        coverage_end_entry_id: str = "",
        metadata: Mapping[str, object] | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        if source_role not in {"user", "tool_receipt"}:
            raise ValueError("unsupported Agent memory source role")
        if source_kind not in _SOURCE_KINDS:
            raise ValueError("unsupported Agent memory source kind")
        if trust_class not in _TRUST_CLASSES:
            raise ValueError("unsupported Agent memory trust class")
        normalized_owner_kind = compact_whitespace(owner_kind)
        if normalized_owner_kind not in _OWNER_KINDS:
            raise ValueError("unsupported Agent memory owner kind")
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT role_id, role_version, session_kind
                FROM agent_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(session_id)
            if (
                str(session["session_kind"] or "conversation") != "conversation"
                and source_kind in {"user_final", "session_compaction"}
            ):
                return {
                    "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                    "ok": True,
                    "stored": False,
                    "status": "skipped_transient_session",
                }
            role_id = compact_whitespace(str(session["role_id"] or ""))
            role_version = compact_whitespace(str(session["role_version"] or ""))
            scope_status, authoritative_scope, scope_reason = session_knowledge_scope(
                conn,
                session_id,
            )
            if scope_status == "quarantined":
                quarantine_id = quarantine_scope_issue(
                    conn,
                    source_table="agent_memory_sources",
                    source_id=f"{session_id}:{pi_entry_id}:{source_kind}",
                    reason_code=scope_reason,
                    observed_scope={"sessionId": session_id, "sourceKind": source_kind},
                    observed_at_ms=timestamp,
                )
                return {
                    "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                    "ok": True,
                    "stored": False,
                    "status": "quarantined",
                    "quarantineId": quarantine_id,
                }
            normalized_owner_id = compact_whitespace(owner_id)
            scope_columns = {
                "knowledge_domain": "legacy",
                "scope_kind": "legacy",
                "scope_id": "",
                "visibility": "legacy",
                "authorization_revision": "",
                "binding_id": "",
                "scope_mode": "legacy",
            }
            if authoritative_scope is not None:
                normalized_owner_kind = authoritative_scope.owner_kind
                normalized_owner_id = authoritative_scope.owner_id
                scope_columns = authoritative_scope.columns()
            if normalized_owner_kind == "agent" and not normalized_owner_id:
                normalized_owner_id = role_id
            if not normalized_owner_id:
                normalized_owner_id = "default"
            existing = conn.execute(
                """
                SELECT * FROM agent_memory_sources
                WHERE session_id = ? AND pi_entry_id = ? AND source_kind = ? AND source_revision = 1
                """,
                (session_id, pi_entry_id, source_kind),
            ).fetchone()
            if existing is not None:
                payload = _source_payload(existing)
                return {
                    "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                    "ok": True,
                    "stored": False,
                    "status": "already_checkpointed",
                    "source": payload,
                }

            event = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, recent_context, preedit,
                    schema_id, app, project, candidate_rank, provider_name, tags_json,
                    context_group_id, context_group_level
                ) VALUES (?, ?, ?, '', '', 'agent-session', 'RagImeControl', ?, NULL, 'pi-rpc', ?, ?, 'session')
                """,
                (
                    timestamp,
                    source,
                    canonical,
                    self.project,
                    _json_tags(tags),
                    f"agent-session:{session_id}",
                ),
            )
            event_id = int(event.lastrowid)
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, ?)",
                (event_id, timestamp),
            )
            sync_event_to_memory_v2(
                conn,
                event_id=event_id,
                created_at_ms=timestamp,
                source=source,
                committed_text=canonical,
                recent_context="",
                preedit="",
                project=self.project,
                app="RagImeControl",
                provider_name="pi-rpc",
                tags=tags,
                context_group_id=f"agent-session:{session_id}",
                context_group_level="session",
                embedding_provider=None,
            )
            conn.execute(
                """
                UPDATE memory_items
                SET owner_kind = ?, owner_id = ?, knowledge_domain = ?,
                    scope_kind = ?, scope_id = ?, visibility = ?,
                    authorization_revision = ?, binding_id = ?, scope_mode = ?
                WHERE source_event_id = ?
                """,
                (
                    normalized_owner_kind, normalized_owner_id,
                    scope_columns["knowledge_domain"], scope_columns["scope_kind"],
                    scope_columns["scope_id"], scope_columns["visibility"],
                    scope_columns["authorization_revision"], scope_columns["binding_id"],
                    scope_columns["scope_mode"], event_id,
                ),
            )
            source_id = f"agent-memory:{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id, source_role,
                    source_revision, canonical_text_sha256, status, turn_id,
                    approval_id, created_at_ms, owner_kind, owner_id, role_id,
                    role_version, source_kind, trust_class, disposition,
                    coverage_start_entry_id, coverage_end_entry_id, metadata_json,
                    knowledge_domain, scope_kind, scope_id, visibility,
                    authorization_revision, binding_id, scope_mode
                ) VALUES (
                    ?, ?, ?, ?, ?, 1, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    source_id,
                    session_id,
                    pi_entry_id,
                    event_id,
                    source_role,
                    digest,
                    compact_whitespace(turn_id),
                    compact_whitespace(approval_id),
                    timestamp,
                    normalized_owner_kind,
                    normalized_owner_id,
                    role_id,
                    role_version,
                    source_kind,
                    trust_class,
                    compact_whitespace(coverage_start_entry_id),
                    compact_whitespace(coverage_end_entry_id),
                    _json_object(metadata),
                    scope_columns["knowledge_domain"],
                    scope_columns["scope_kind"],
                    scope_columns["scope_id"],
                    scope_columns["visibility"],
                    scope_columns["authorization_revision"],
                    scope_columns["binding_id"],
                    scope_columns["scope_mode"],
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_source_disposition_events(
                    event_id, source_id, previous_disposition, new_disposition,
                    reason_code, actor_kind, created_at_ms, metadata_json
                ) VALUES (?, ?, '', 'pending', 'checkpoint_created', 'system', ?, '{}')
                """,
                (f"memory-disposition:{uuid.uuid4()}", source_id, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM agent_memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        payload = _source_payload(row)
        return {
            "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
            "ok": True,
            "stored": True,
            "status": "checkpointed",
            "source": payload,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _assert_source_curation_not_running(
    conn: sqlite3.Connection,
    source: sqlite3.Row,
    *,
    timestamp: int,
) -> None:
    event = conn.execute(
        "SELECT project FROM input_events WHERE id = ?",
        (int(source["input_event_id"]),),
    ).fetchone()
    event_project = compact_whitespace(
        str(event["project"] or "") if event is not None else ""
    )
    row = conn.execute(
        """
        SELECT 1
        FROM memory_curation_cursors
        WHERE owner_kind = ? AND owner_id = ? AND lane = 'daily'
          AND status = 'running'
          AND updated_at_ms > ?
          AND (project = '' OR ? = '' OR project = ?)
        LIMIT 1
        """,
        (
            str(source["owner_kind"]),
            str(source["owner_id"]),
            max(0, timestamp - 60 * 60 * 1000),
            event_project,
            event_project,
        ),
    ).fetchone()
    if row is not None:
        raise ValueError("memory source curation is currently running")


def _invalidate_source_review_drafts(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    timestamp: int,
) -> None:
    rows = conn.execute(
        """
        SELECT DISTINCT run.run_id
        FROM memory_cleanup_runs AS run
        JOIN json_each(
            CASE
                WHEN json_valid(run.metadata_json) THEN run.metadata_json
                ELSE '{}'
            END,
            '$.sourceIds'
        ) AS source
        WHERE run.status = 'draft'
          AND run.run_kind IN ('daily_curation', 'manual_curation')
          AND CAST(source.value AS TEXT) = ?
        """,
        (source_id,),
    ).fetchall()
    run_ids = [str(row["run_id"]) for row in rows]
    if not run_ids:
        return
    placeholders = ",".join("?" for _ in run_ids)
    conn.execute(
        f"""
        UPDATE memory_cleanup_runs
        SET status = 'superseded'
        WHERE run_id IN ({placeholders})
        """,  # noqa: S608 - placeholders contain no user-controlled SQL.
        tuple(run_ids),
    )
    conn.execute(
        f"""
        UPDATE memory_curation_cursors
        SET status = 'idle', next_due_at_ms = 0, last_error = '',
            updated_at_ms = ?
        WHERE last_run_id IN ({placeholders})
        """,  # noqa: S608 - placeholders contain no user-controlled SQL.
        (timestamp, *run_ids),
    )


def _rewind_curation_cursors_for_source(
    conn: sqlite3.Connection,
    *,
    source: sqlite3.Row,
    timestamp: int,
) -> None:
    event = conn.execute(
        "SELECT project FROM input_events WHERE id = ?",
        (int(source["input_event_id"]),),
    ).fetchone()
    event_project = compact_whitespace(
        str(event["project"] or "") if event is not None else ""
    )
    source_position = (
        int(source["created_at_ms"] or 0),
        str(source["source_id"]),
    )
    cursors = conn.execute(
        """
        SELECT *
        FROM memory_curation_cursors
        WHERE owner_kind = ? AND owner_id = ? AND lane = 'daily'
        """,
        (str(source["owner_kind"]), str(source["owner_id"])),
    ).fetchall()
    for cursor in cursors:
        cursor_project = compact_whitespace(str(cursor["project"] or ""))
        if (
            cursor_project
            and event_project
            and cursor_project != event_project
        ):
            continue
        cursor_position = (
            int(cursor["last_source_created_at_ms"] or 0),
            str(cursor["last_source_id"] or ""),
        )
        active_draft = (
            str(cursor["status"] or "") == "waiting_review"
            and bool(cursor["last_run_id"])
            and conn.execute(
                """
                SELECT 1
                FROM memory_cleanup_runs
                WHERE run_id = ? AND status = 'draft'
                """,
                (str(cursor["last_run_id"]),),
            ).fetchone()
            is not None
        )
        next_position = cursor_position
        if cursor_position >= source_position:
            placeholders = ",".join(
                "?" for _ in _CURATION_ELIGIBLE_DISPOSITIONS
            )
            previous = conn.execute(
                f"""
                SELECT candidate.created_at_ms, candidate.source_id
                FROM agent_memory_sources AS candidate
                JOIN input_events AS candidate_event
                  ON candidate_event.id = candidate.input_event_id
                WHERE candidate.owner_kind = ? AND candidate.owner_id = ?
                  AND candidate.status = 'active'
                  AND candidate.disposition IN ({placeholders})
                  AND (
                      ? = ''
                      OR candidate_event.project = ?
                      OR candidate_event.project = ''
                  )
                  AND (
                      candidate.created_at_ms < ?
                      OR (
                          candidate.created_at_ms = ?
                          AND candidate.source_id < ?
                      )
                  )
                ORDER BY candidate.created_at_ms DESC, candidate.source_id DESC
                LIMIT 1
                """,
                (
                    str(source["owner_kind"]),
                    str(source["owner_id"]),
                    *_CURATION_ELIGIBLE_DISPOSITIONS,
                    cursor_project,
                    cursor_project,
                    source_position[0],
                    source_position[0],
                    source_position[1],
                ),
            ).fetchone()
            next_position = (
                (
                    int(previous["created_at_ms"] or 0),
                    str(previous["source_id"] or ""),
                )
                if previous is not None
                else (0, "")
            )
        conn.execute(
            """
            UPDATE memory_curation_cursors
            SET last_source_created_at_ms = ?, last_source_id = ?,
                next_due_at_ms = 0, status = ?, last_error = '',
                updated_at_ms = ?
            WHERE owner_kind = ? AND owner_id = ? AND project = ?
              AND lane = 'daily'
            """,
            (
                next_position[0],
                next_position[1],
                "waiting_review" if active_draft else "idle",
                timestamp,
                str(source["owner_kind"]),
                str(source["owner_id"]),
                cursor_project,
            ),
        )


def _source_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = {
        "schemaVersion": "rag-ime.agent-memory-source.v1",
        "sourceId": str(row["source_id"]),
        "sessionId": str(row["session_id"]),
        "piEntryId": str(row["pi_entry_id"]),
        "inputEventId": int(row["input_event_id"]),
        "sourceRole": str(row["source_role"]),
        "sourceRevision": int(row["source_revision"]),
        "canonicalTextSha256": str(row["canonical_text_sha256"]),
        "status": str(row["status"]),
        "ownerKind": str(row["owner_kind"]),
        "ownerId": str(row["owner_id"]),
        "knowledgeDomain": str(row["knowledge_domain"]),
        "scopeKind": str(row["scope_kind"]),
        "scopeId": str(row["scope_id"]),
        "visibility": str(row["visibility"]),
        "authorizationRevision": str(row["authorization_revision"]),
        "bindingId": str(row["binding_id"]),
        "scopeMode": str(row["scope_mode"]),
        "roleId": str(row["role_id"]),
        "roleVersion": str(row["role_version"]),
        "sourceKind": str(row["source_kind"]),
        "trustClass": str(row["trust_class"]),
        "disposition": str(row["disposition"]),
        "dispositionReason": str(row["disposition_reason"]),
        "dispositionUpdatedAtMs": (
            int(row["disposition_updated_at_ms"])
            if row["disposition_updated_at_ms"] is not None
            else None
        ),
        "processedAtMs": (
            int(row["processed_at_ms"]) if row["processed_at_ms"] is not None else None
        ),
        "curationRunId": str(row["curation_run_id"]),
        "coverageStartEntryId": str(row["coverage_start_entry_id"]),
        "coverageEndEntryId": str(row["coverage_end_entry_id"]),
        "expiresAtMs": int(row["expires_at_ms"]) if row["expires_at_ms"] is not None else None,
        "metadata": _loaded_json_object(row["metadata_json"]),
        "createdAtMs": int(row["created_at_ms"]),
        "supersededAtMs": (
            int(row["superseded_at_ms"]) if row["superseded_at_ms"] is not None else None
        ),
    }
    validate_contract(payload, "agent-memory-source.v1.json")
    return payload


def _json_tags(tags: tuple[str, ...]) -> str:
    return json.dumps(list(tags), ensure_ascii=False, separators=(",", ":"))


def _owner(owner_kind: object, owner_id: object) -> tuple[str, str]:
    kind = compact_whitespace(str(owner_kind or ""))
    identity = compact_whitespace(str(owner_id or ""))
    if kind not in _OWNER_KINDS:
        raise ValueError("unsupported memory owner kind")
    if not identity:
        raise ValueError("memory owner id must not be empty")
    return kind, identity


def _json_object(value: Mapping[str, object] | None) -> str:
    return json.dumps(
        _json_safe(dict(value or {})),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _loaded_json_object(value: object) -> dict[str, object]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _json_safe(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        return str(value)[:500]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value if not isinstance(value, str) else value[:2000]
    if isinstance(value, Mapping):
        return {
            str(key)[:120]: _json_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value[:80]]
    return str(value)[:500]


def _compaction_payload(result: Mapping[str, object]) -> dict[str, object]:
    current: Mapping[str, object] = result
    for key in ("result", "data", "compaction"):
        nested = current.get(key)
        if isinstance(nested, Mapping) and not compact_whitespace(str(current.get("summary") or "")):
            current = nested
    payload = dict(current)
    details = current.get("details")
    if isinstance(details, Mapping):
        for key in (
            "summary",
            "firstKeptEntryId",
            "firstSummarizedEntryId",
            "lastSummarizedEntryId",
            "coverageStartEntryId",
            "coverageEndEntryId",
            "tokensBefore",
            "estimatedTokensAfter",
        ):
            current_value = payload.get(key)
            detail_value = details.get(key)
            if (current_value is None or current_value == "") and (
                detail_value is not None and detail_value != ""
            ):
                payload[key] = detail_value
    return payload


def _optional_non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, parsed)
