from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .memory_ingest import looks_sensitive, sync_event_to_memory_v2
from .text_utils import compact_whitespace


class AgentMemorySourceStore:
    """Checkpoint final Agent inputs without touching IME phrase frequency."""

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
            source="pi_agent_tool_receipt",
            canonical=summary,
            tags=("agent-session", "approved-tool-receipt"),
            created_at_ms=created_at_ms,
        )

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

    def _checkpoint(
        self,
        *,
        session_id: str,
        pi_entry_id: str,
        source_role: str,
        source: str,
        canonical: str,
        tags: tuple[str, ...],
        turn_id: str = "",
        approval_id: str = "",
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        if source_role not in {"user", "tool_receipt"}:
            raise ValueError("unsupported Agent memory source role")
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_memory_sources
                WHERE session_id = ? AND pi_entry_id = ? AND source_role = ? AND source_revision = 1
                """,
                (session_id, pi_entry_id, source_role),
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
            source_id = f"agent-memory:{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id, source_role,
                    source_revision, canonical_text_sha256, status, turn_id,
                    approval_id, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 'active', ?, ?, ?)
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
                ),
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
        "createdAtMs": int(row["created_at_ms"]),
        "supersededAtMs": (
            int(row["superseded_at_ms"]) if row["superseded_at_ms"] is not None else None
        ),
    }
    validate_contract(payload, "agent-memory-source.v1.json")
    return payload


def _json_tags(tags: tuple[str, ...]) -> str:
    return json.dumps(list(tags), ensure_ascii=False, separators=(",", ":"))
