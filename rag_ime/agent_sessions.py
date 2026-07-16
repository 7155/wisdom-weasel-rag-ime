from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Iterable, Mapping

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


class AgentSessionNotFound(KeyError):
    pass


class AgentApprovalNotFound(KeyError):
    pass


_SESSION_SELECT = """
SELECT
    s.*,
    b.driver_id AS runtime_driver_id,
    b.runtime_kind AS runtime_kind,
    b.generation AS runtime_generation,
    b.binding_state AS runtime_binding_state,
    b.created_at_ms AS runtime_binding_created_at_ms,
    b.updated_at_ms AS runtime_binding_updated_at_ms,
    tp.allowed_tools_json AS allowed_tools_json
FROM agent_sessions AS s
LEFT JOIN agent_runtime_bindings AS b ON b.session_id = s.id
LEFT JOIN agent_session_tool_policies AS tp ON tp.session_id = s.id
"""


class AgentSessionStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def create(
        self,
        *,
        title: str,
        mode: str = "assistant",
        role_id: str = "zhiyou-v1",
        role_version: str = "1",
        model_profile: str = "deepseek-v4",
        thinking_level: str = "",
        tool_profile_version: str = "control-center-v1",
        workspace_roots: Iterable[str] = (),
        shell_policy_version: str | None = None,
        session_kind: str = "conversation",
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        if mode not in {"assistant", "coordinator"}:
            raise ValueError("agent session mode must be assistant or coordinator")
        normalized_title = " ".join(str(title).split())[:120]
        if not normalized_title:
            raise ValueError("agent session title must not be empty")
        roots = _workspace_roots(workspace_roots)
        if mode == "assistant" and roots:
            raise ValueError("assistant sessions cannot carry workspace roots")
        normalized_kind = str(session_kind or "").strip()
        if normalized_kind not in {"conversation", "subagent_runtime"}:
            raise ValueError("agent session kind must be conversation or subagent_runtime")
        normalized_thinking = str(thinking_level or "").strip().lower()
        if normalized_thinking not in {
            "",
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("agent thinking level is not supported")
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        session_id = f"agent:{uuid.uuid4()}"
        shell_policy = shell_policy_version or (
            "coordinator-per-command-v1" if mode == "coordinator" else "assistant-no-shell-v1"
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions(
                    id, title, session_mode, role_id, role_version, model_profile, thinking_level,
                    tool_profile_version, workspace_roots_json, shell_policy_version,
                    session_kind, created_at_ms, updated_at_ms, last_opened_at_ms, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle')
                """,
                (
                    session_id,
                    normalized_title,
                    mode,
                    role_id,
                    role_version,
                    model_profile,
                    normalized_thinking,
                    tool_profile_version,
                    json.dumps(roots, ensure_ascii=False, separators=(",", ":")),
                    shell_policy,
                    normalized_kind,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(session_id)

    def get(self, session_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                f"{_SESSION_SELECT} WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise AgentSessionNotFound(session_id)
        return _session_payload(row, _joined_runtime_binding(row))

    def list(
        self,
        *,
        include_archived: bool = False,
        include_internal: bool = False,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        bounded_limit = max(1, min(int(limit), 500))
        clauses = [] if include_archived else ["s.status <> 'archived'"]
        if not include_internal:
            clauses.extend(
                [
                    "s.session_kind = 'conversation'",
                    "s.id NOT IN (SELECT child_session_id FROM agent_subagent_runs)",
                ]
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"{_SESSION_SELECT} {where} ORDER BY s.updated_at_ms DESC LIMIT ?",  # noqa: S608
                (bounded_limit,),
            ).fetchall()
        return [_session_payload(row, _joined_runtime_binding(row)) for row in rows]

    def runtime_binding(self, session_id: str) -> dict[str, object] | None:
        self.get(session_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runtime_bindings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _runtime_binding_payload(row) if row is not None else None

    def bind_runtime_session(
        self,
        session_id: str,
        *,
        driver_id: str,
        runtime_kind: str,
        external_session_id: str,
        transcript_ref: str = "",
        branch_anchor: str = "",
        binding_state: str = "active",
        metadata: Mapping[str, object] | None = None,
        message_count: int = 0,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        driver = _runtime_binding_text(driver_id, field="driverId", maximum=120)
        kind = _runtime_binding_text(runtime_kind, field="runtimeKind", maximum=80)
        external_id = _runtime_binding_text(
            external_session_id,
            field="externalSessionId",
            maximum=240,
        )
        transcript = _runtime_binding_text(
            transcript_ref,
            field="transcriptRef",
            maximum=4096,
            required=False,
        )
        anchor = _runtime_binding_text(
            branch_anchor,
            field="branchAnchor",
            maximum=240,
            required=False,
        )
        if binding_state not in {"prepared", "active", "stale"}:
            raise ValueError("runtime binding state must be prepared, active, or stale")
        try:
            metadata_json = json.dumps(
                dict(metadata or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime binding metadata must be JSON serializable") from exc
        if len(metadata_json.encode("utf-8")) > 16_384:
            raise ValueError("runtime binding metadata is too large")
        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            session = conn.execute(
                "SELECT id FROM agent_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise AgentSessionNotFound(session_id)
            existing = conn.execute(
                "SELECT * FROM agent_runtime_bindings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None and (
                str(existing["driver_id"]) != driver
                or str(existing["runtime_kind"]) != kind
            ):
                raise ValueError("an Agent session cannot change runtime driver in place")
            if existing is not None and not anchor:
                anchor = str(existing["branch_anchor"] or "")
            generation = int(existing["generation"]) + 1 if existing is not None else 1
            created_at_ms = int(existing["created_at_ms"]) if existing is not None else timestamp
            try:
                conn.execute(
                    """
                    INSERT INTO agent_runtime_bindings(
                        session_id, driver_id, runtime_kind, external_session_id,
                        transcript_ref, branch_anchor, generation, binding_state,
                        metadata_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        external_session_id = excluded.external_session_id,
                        transcript_ref = excluded.transcript_ref,
                        branch_anchor = excluded.branch_anchor,
                        generation = excluded.generation,
                        binding_state = excluded.binding_state,
                        metadata_json = excluded.metadata_json,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (
                        session_id,
                        driver,
                        kind,
                        external_id,
                        transcript,
                        anchor,
                        generation,
                        binding_state,
                        metadata_json,
                        created_at_ms,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("runtime session is already bound to another Agent session") from exc
            assignments = ["updated_at_ms = ?"]
            values: list[object] = [timestamp]
            if binding_state == "active":
                assignments.extend(
                    ["status = 'active'", "last_opened_at_ms = ?", "message_count = ?"]
                )
                values.extend([timestamp, max(0, int(message_count))])
            if kind == "pi_rpc" and driver == "managed-pi":
                assignments.extend(["pi_session_id = ?", "session_file = ?"])
                values.extend([external_id, transcript])
            conn.execute(
                f"UPDATE agent_sessions SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
                (*values, session_id),
            )
        return self.get(session_id)

    def prepare_session_file(
        self,
        session_id: str,
        *,
        pi_session_id: str,
        session_file: str,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Attach a prebuilt managed Pi branch without marking it active."""

        if not str(pi_session_id).strip() or not str(session_file).strip():
            raise ValueError("prepared Pi session identity and file must not be empty")
        return self.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=pi_session_id,
            transcript_ref=session_file,
            binding_state="prepared",
            updated_at_ms=updated_at_ms,
        )

    def rename(self, session_id: str, title: str, *, updated_at_ms: int | None = None) -> dict[str, object]:
        normalized = " ".join(str(title).split())[:120]
        if not normalized:
            raise ValueError("agent session title must not be empty")
        self._update(
            session_id,
            "title = ?, updated_at_ms = ?",
            (normalized, _timestamp(updated_at_ms)),
        )
        return self.get(session_id)

    def set_model_profile(
        self,
        session_id: str,
        model_profile: str,
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized = "/".join(part.strip() for part in str(model_profile).split("/", 1))
        if "/" not in normalized or normalized.startswith("/") or normalized.endswith("/"):
            raise ValueError("agent model profile must be provider/model")
        if len(normalized) > 240:
            raise ValueError("agent model profile is too long")
        self._update(
            session_id,
            "model_profile = ?, updated_at_ms = ?",
            (normalized, _timestamp(updated_at_ms)),
        )
        return self.get(session_id)

    def set_thinking_level(
        self,
        session_id: str,
        thinking_level: str,
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized = str(thinking_level or "").strip().lower()
        if normalized not in {
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("agent thinking level is not supported")
        self._update(
            session_id,
            "thinking_level = ?, updated_at_ms = ?",
            (normalized, _timestamp(updated_at_ms)),
        )
        return self.get(session_id)

    def set_mode(
        self,
        session_id: str,
        mode: str,
        *,
        workspace_roots: Iterable[str] | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_mode = str(mode or "").strip()
        if normalized_mode not in {"assistant", "coordinator"}:
            raise ValueError("agent session mode must be assistant or coordinator")
        current = self.get(session_id)
        roots = _workspace_roots(
            current.get("workspaceRoots", []) if workspace_roots is None else workspace_roots
        )
        if normalized_mode == "assistant":
            roots = []
        shell_policy = (
            "coordinator-per-command-v1"
            if normalized_mode == "coordinator"
            else "assistant-no-shell-v1"
        )
        self._update(
            session_id,
            "session_mode = ?, workspace_roots_json = ?, shell_policy_version = ?, updated_at_ms = ?",
            (
                normalized_mode,
                json.dumps(roots, ensure_ascii=False, separators=(",", ":")),
                shell_policy,
                _timestamp(updated_at_ms),
            ),
        )
        return self.get(session_id)

    def set_runtime_policy(
        self,
        session_id: str,
        *,
        mode: str,
        tool_profile_version: str,
        allowed_tools: Iterable[str] | None,
        workspace_roots: Iterable[str] | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_mode = str(mode or "").strip()
        if normalized_mode not in {"assistant", "coordinator"}:
            raise ValueError("agent session mode must be assistant or coordinator")
        profile = str(tool_profile_version or "").strip()
        if profile not in {"control-center-v1", "subagent-readonly-v1", "subagent-worker-v1"}:
            raise ValueError("unsupported Agent tool profile")
        current = self.get(session_id)
        roots = _workspace_roots(
            current.get("workspaceRoots", []) if workspace_roots is None else workspace_roots
        )
        if normalized_mode == "assistant":
            roots = []
        normalized_tools = _allowed_tools(allowed_tools)
        shell_policy = (
            "coordinator-per-command-v1"
            if normalized_mode == "coordinator"
            else "assistant-no-shell-v1"
        )
        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agent_sessions
                SET session_mode = ?, tool_profile_version = ?, workspace_roots_json = ?,
                    shell_policy_version = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    normalized_mode,
                    profile,
                    json.dumps(roots, ensure_ascii=False, separators=(",", ":")),
                    shell_policy,
                    timestamp,
                    session_id,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentSessionNotFound(session_id)
            conn.execute(
                """
                INSERT INTO agent_session_tool_policies(session_id, allowed_tools_json, updated_at_ms)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    allowed_tools_json = excluded.allowed_tools_json,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    session_id,
                    json.dumps(normalized_tools, ensure_ascii=False, separators=(",", ":"))
                    if normalized_tools is not None
                    else "null",
                    timestamp,
                ),
            )
        return self.get(session_id)

    def archive(self, session_id: str, *, archived: bool = True, updated_at_ms: int | None = None) -> dict[str, object]:
        timestamp = _timestamp(updated_at_ms)
        if archived:
            self._update(
                session_id,
                "status = 'archived', archived_at_ms = ?, updated_at_ms = ?",
                (timestamp, timestamp),
            )
        else:
            self._update(
                session_id,
                "status = 'idle', archived_at_ms = NULL, updated_at_ms = ?",
                (timestamp,),
            )
        return self.get(session_id)

    def retire_internal(
        self,
        session_id: str,
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Make a delegated runtime identity non-resumable without deleting its audit owner."""

        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT 1 FROM agent_subagent_runs WHERE child_session_id = ?",
                (session_id,),
            ).fetchone()
            if owned is None:
                raise ValueError("only delegated runtime sessions can be retired")
            conn.execute(
                "DELETE FROM agent_runtime_bindings WHERE session_id = ?",
                (session_id,),
            )
            cursor = conn.execute(
                """
                UPDATE agent_sessions
                SET session_kind = 'subagent_runtime', status = 'archived',
                    pi_session_id = '', session_file = '', workspace_roots_json = '[]',
                    last_message_preview = '', archived_at_ms = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, session_id),
            )
            if cursor.rowcount != 1:
                raise AgentSessionNotFound(session_id)
        return self.get(session_id)

    def destroy_internal(self, session_id: str) -> dict[str, object]:
        """Delete an expired delegated Session while leaving its run projection intact."""

        session = self.get(session_id)
        with self._connect() as conn:
            owned = conn.execute(
                """
                SELECT state FROM agent_subagent_runs
                WHERE child_session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if owned is None:
                raise ValueError("only delegated runtime sessions can be destroyed")
            if str(owned["state"]) not in {"completed", "failed", "aborted", "timed_out"}:
                raise ValueError("active delegated runtime sessions cannot be destroyed")
            cursor = conn.execute(
                """
                DELETE FROM agent_sessions
                WHERE id = ? AND session_kind = 'subagent_runtime'
                """,
                (session_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("only internal subagent sessions can be destroyed")
        return session

    def delete(self, session_id: str) -> dict[str, object]:
        session = self.get(session_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))
        return session

    def bind_pi_session(
        self,
        session_id: str,
        *,
        pi_session_id: str,
        session_file: str,
        message_count: int = 0,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        return self.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=pi_session_id,
            transcript_ref=session_file,
            binding_state="active",
            message_count=message_count,
            updated_at_ms=updated_at_ms,
        )

    def set_status(
        self,
        session_id: str,
        status: str,
        *,
        message_count: int | None = None,
        last_message_preview: str | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        if status not in {"idle", "active", "busy", "faulted", "archived"}:
            raise ValueError(f"unsupported agent session status: {status}")
        assignments = ["status = ?", "updated_at_ms = ?"]
        values: list[object] = [status, _timestamp(updated_at_ms)]
        if message_count is not None:
            assignments.append("message_count = ?")
            values.append(max(0, int(message_count)))
        if last_message_preview is not None:
            assignments.append("last_message_preview = ?")
            values.append(" ".join(last_message_preview.split())[:240])
        self._update(session_id, ", ".join(assignments), tuple(values))
        return self.get(session_id)

    def max_event_sequence(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_runtime_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row[0] if row else 0)

    def agent_plan(self, session_id: str, *, limit: int = 100) -> dict[str, object]:
        self.get(session_id)
        bounded_limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH latest AS (
                    SELECT event_id, sequence, item_id, title, status, created_at_ms,
                           ROW_NUMBER() OVER (
                               PARTITION BY item_id ORDER BY sequence DESC
                           ) AS row_number
                    FROM agent_plan_events
                    WHERE session_id = ?
                )
                SELECT event_id, sequence, item_id, title, status, created_at_ms
                FROM latest
                WHERE row_number = 1
                ORDER BY
                    CASE status
                        WHEN 'in_progress' THEN 0
                        WHEN 'pending' THEN 1
                        ELSE 2
                    END,
                    sequence,
                    item_id
                LIMIT ?
                """,
                (session_id, bounded_limit),
            ).fetchall()
            revision_row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_plan_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        items = [_agent_plan_item(row) for row in rows]
        completed = sum(1 for item in items if item["status"] == "completed")
        in_progress = sum(1 for item in items if item["status"] == "in_progress")
        return {
            "schemaVersion": "rag-ime.agent-plan.v1",
            "sessionId": session_id,
            "revision": int(revision_row[0] if revision_row else 0),
            "items": items,
            "counts": {
                "total": len(items),
                "pending": len(items) - completed - in_progress,
                "inProgress": in_progress,
                "completed": completed,
            },
        }

    def update_agent_plan_item(
        self,
        session_id: str,
        *,
        item_id: str = "",
        title: str = "",
        status: str = "",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_item_id = str(item_id or "").strip()
        if not normalized_item_id:
            normalized_item_id = f"plan-item:{uuid.uuid4()}"
        if len(normalized_item_id) > 160 or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-."
            for character in normalized_item_id
        ):
            raise ValueError("agent plan itemId is invalid")
        requested_title = " ".join(str(title or "").split())[:240]
        requested_status = str(status or "").strip()
        if requested_status and requested_status not in {"pending", "in_progress", "completed"}:
            raise ValueError("agent plan status must be pending, in_progress, or completed")
        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            # Serialize the read-check-append sequence across Sidecar workers.
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT id FROM agent_sessions WHERE id = ? AND status <> 'archived'",
                (session_id,),
            ).fetchone()
            if session is None:
                raise AgentSessionNotFound(session_id)
            current = conn.execute(
                """
                SELECT title, status FROM agent_plan_events
                WHERE session_id = ? AND item_id = ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (session_id, normalized_item_id),
            ).fetchone()
            if current is None:
                item_count = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT item_id) FROM agent_plan_events WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()[0]
                )
                if item_count >= 100:
                    raise ValueError("agent plan is limited to 100 items")
            normalized_title = requested_title or (str(current["title"]) if current is not None else "")
            normalized_status = requested_status or (
                str(current["status"]) if current is not None else "pending"
            )
            if not normalized_title:
                raise ValueError("title is required when creating an agent plan item")
            if normalized_status == "in_progress":
                other = conn.execute(
                    """
                    WITH latest AS (
                        SELECT item_id, status,
                               ROW_NUMBER() OVER (
                                   PARTITION BY item_id ORDER BY sequence DESC
                               ) AS row_number
                        FROM agent_plan_events WHERE session_id = ?
                    )
                    SELECT item_id FROM latest
                    WHERE row_number = 1 AND status = 'in_progress' AND item_id <> ?
                    LIMIT 1
                    """,
                    (session_id, normalized_item_id),
                ).fetchone()
                if other is not None:
                    raise ValueError("only one agent plan item may be in_progress")
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_plan_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            event_id = f"plan-event:{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO agent_plan_events(
                    event_id, session_id, sequence, item_id, title, status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    sequence,
                    normalized_item_id,
                    normalized_title,
                    normalized_status,
                    timestamp,
                ),
            )
            conn.execute(
                "UPDATE agent_sessions SET updated_at_ms = ? WHERE id = ?",
                (timestamp, session_id),
            )
        plan = self.agent_plan(session_id)
        return {
            "event": {
                "eventId": event_id,
                "sequence": sequence,
                "itemId": normalized_item_id,
                "title": normalized_title,
                "status": normalized_status,
                "createdAtMs": timestamp,
            },
            "plan": plan,
        }

    def record_runtime_event(
        self,
        *,
        event_id: str,
        session_id: str,
        turn_id: str,
        sequence: int,
        event_type: str,
        created_at_ms: int,
        redacted_summary: str = "",
        retain_per_session: int = 1000,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_runtime_events(
                    event_id, session_id, turn_id, sequence, event_type,
                    created_at_ms, redacted_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    turn_id,
                    sequence,
                    event_type,
                    created_at_ms,
                    " ".join(redacted_summary.split())[:240],
                ),
            )
            conn.execute(
                """
                DELETE FROM agent_runtime_events
                WHERE session_id = ? AND sequence <= (
                    SELECT COALESCE(MAX(sequence), 0) - ?
                    FROM agent_runtime_events WHERE session_id = ?
                )
                """,
                (session_id, max(100, int(retain_per_session)), session_id),
            )

    def create_approval(
        self,
        *,
        session_id: str,
        tool_name: str,
        operation: str,
        payload_sha256: str,
        preview: Mapping[str, object],
        risk_level: str,
        requested_at_ms: int | None = None,
        ttl_ms: int = 60_000,
    ) -> dict[str, object]:
        self.get(session_id)
        tool = " ".join(str(tool_name).split())[:120]
        action = " ".join(str(operation).split())[:120]
        digest = str(payload_sha256).strip().lower()
        if not tool or not action:
            raise ValueError("approval tool and operation must not be empty")
        if not _valid_sha256(digest):
            raise ValueError("approval payloadSha256 must be a 64-character hex digest")
        if risk_level not in {"R1", "R2", "R3"}:
            raise ValueError("approval risk level must be R1, R2, or R3")
        timestamp = _timestamp(requested_at_ms)
        bounded_ttl = max(1_000, min(int(ttl_ms), 5 * 60_000))
        approval_id = f"approval:{uuid.uuid4()}"
        preview_json = json.dumps(dict(preview), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_approvals(
                    approval_id, session_id, tool_name, operation, payload_sha256,
                    preview_json, risk_level, state, requested_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    session_id,
                    tool,
                    action,
                    digest,
                    preview_json,
                    risk_level,
                    timestamp,
                    timestamp + bounded_ttl,
                ),
            )
        return self.get_approval(approval_id, now_ms=timestamp)

    def get_approval(self, approval_id: str, *, now_ms: int | None = None) -> dict[str, object]:
        timestamp = _timestamp(now_ms)
        with self._connect() as conn:
            self._expire_approvals(conn, timestamp, approval_id=approval_id)
            row = conn.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise AgentApprovalNotFound(approval_id)
        return _approval_payload(row)

    def list_approvals(
        self,
        *,
        session_id: str,
        state: str = "",
        limit: int = 100,
        now_ms: int | None = None,
    ) -> list[dict[str, object]]:
        self.get(session_id)
        allowed_states = {
            "pending",
            "approved",
            "external_pending",
            "rejected",
            "expired",
            "stale",
            "applied",
            "failed",
        }
        if state and state not in allowed_states:
            raise ValueError("unsupported approval state")
        bounded_limit = max(1, min(int(limit), 500))
        timestamp = _timestamp(now_ms)
        with self._connect() as conn:
            self._expire_approvals(conn, timestamp, session_id=session_id)
            if state:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_approvals
                    WHERE session_id = ? AND state = ?
                    ORDER BY requested_at_ms DESC LIMIT ?
                    """,
                    (session_id, state, bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM agent_approvals
                    WHERE session_id = ?
                    ORDER BY requested_at_ms DESC LIMIT ?
                    """,
                    (session_id, bounded_limit),
                ).fetchall()
        return [_approval_payload(row) for row in rows]

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        payload_sha256: str,
        decided_by: str = "native-control-center",
        decided_at_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = _timestamp(decided_at_ms)
        digest = str(payload_sha256).strip().lower()
        terminal_error = ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise AgentApprovalNotFound(approval_id)
            if str(row["state"]) != "pending":
                terminal_error = f"approval is already {row['state']}"
            elif int(row["expires_at_ms"]) <= timestamp:
                conn.execute(
                    "UPDATE agent_approvals SET state = 'expired', decided_at_ms = ? WHERE approval_id = ?",
                    (timestamp, approval_id),
                )
                terminal_error = "approval has expired"
            elif not _valid_sha256(digest) or digest != str(row["payload_sha256"]):
                conn.execute(
                    "UPDATE agent_approvals SET state = 'stale', decided_at_ms = ? WHERE approval_id = ?",
                    (timestamp, approval_id),
                )
                terminal_error = "approval payload is stale"
            else:
                conn.execute(
                    """
                    UPDATE agent_approvals
                    SET state = ?, decided_at_ms = ?, decided_by = ?
                    WHERE approval_id = ? AND state = 'pending'
                    """,
                    (
                        "approved" if approved else "rejected",
                        timestamp,
                        " ".join(str(decided_by).split())[:120],
                        approval_id,
                    ),
                )
        if terminal_error:
            raise ValueError(terminal_error)
        return self.get_approval(approval_id, now_ms=timestamp)

    def complete_approval(
        self,
        approval_id: str,
        *,
        state: str,
        receipt: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if state not in {"external_pending", "applied", "failed", "stale"}:
            raise ValueError("unsupported approval completion state")
        receipt_json = (
            json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if receipt is not None
            else None
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agent_approvals SET state = ?, receipt_json = ?
                WHERE approval_id = ? AND state = 'approved'
                """,
                (state, receipt_json, approval_id),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    "SELECT state FROM agent_approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                if row is None:
                    raise AgentApprovalNotFound(approval_id)
                raise ValueError(f"approval cannot complete from state {row['state']}")
        return self.get_approval(approval_id)

    def finalize_external_approval(
        self,
        approval_id: str,
        *,
        state: str,
        receipt: Mapping[str, object],
    ) -> dict[str, object]:
        if state not in {"applied", "failed"}:
            raise ValueError("unsupported external approval completion state")
        receipt_json = json.dumps(
            dict(receipt),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agent_approvals SET state = ?, receipt_json = ?
                WHERE approval_id = ? AND state = 'external_pending'
                """,
                (state, receipt_json, approval_id),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    "SELECT state FROM agent_approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                if row is None:
                    raise AgentApprovalNotFound(approval_id)
                raise ValueError(f"external approval cannot complete from state {row['state']}")
        return self.get_approval(approval_id)

    @staticmethod
    def _expire_approvals(
        conn: sqlite3.Connection,
        now_ms: int,
        *,
        approval_id: str = "",
        session_id: str = "",
    ) -> None:
        where = ["state = 'pending'", "expires_at_ms <= ?"]
        values: list[object] = [now_ms]
        if approval_id:
            where.append("approval_id = ?")
            values.append(approval_id)
        if session_id:
            where.append("session_id = ?")
            values.append(session_id)
        conn.execute(
            f"UPDATE agent_approvals SET state = 'expired', decided_at_ms = ? WHERE {' AND '.join(where)}",  # noqa: S608
            (now_ms, *values),
        )

    def _update(self, session_id: str, assignments: str, values: tuple[object, ...]) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE agent_sessions SET {assignments} WHERE id = ?",  # noqa: S608
                (*values, session_id),
            )
            if cursor.rowcount != 1:
                raise AgentSessionNotFound(session_id)

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


def _session_payload(
    row: sqlite3.Row,
    runtime_binding: Mapping[str, object] | None = None,
) -> dict[str, object]:
    roots = json.loads(str(row["workspace_roots_json"] or "[]"))
    allowed_tools = _stored_allowed_tools(row["allowed_tools_json"])
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-session.v1",
        "id": str(row["id"]),
        "piSessionId": str(row["pi_session_id"] or ""),
        "sessionFile": str(row["session_file"] or ""),
        "title": str(row["title"]),
        "mode": str(row["session_mode"]),
        "status": str(row["status"]),
        "sessionKind": str(row["session_kind"]),
        "roleId": str(row["role_id"]),
        "roleVersion": str(row["role_version"]),
        "modelProfile": str(row["model_profile"]),
        "thinkingLevel": str(row["thinking_level"] or ""),
        "toolProfileVersion": str(row["tool_profile_version"]),
        "toolAllowlistMode": "explicit" if allowed_tools is not None else "profile",
        "allowedTools": allowed_tools or [],
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "lastOpenedAtMs": int(row["last_opened_at_ms"]),
        "archivedAtMs": int(row["archived_at_ms"]) if row["archived_at_ms"] is not None else None,
        "messageCount": int(row["message_count"]),
        "lastMessagePreview": str(row["last_message_preview"] or ""),
        "workspaceRoots": [str(value) for value in roots if str(value).strip()],
        "shellPolicyVersion": str(row["shell_policy_version"]),
    }
    if runtime_binding is not None:
        payload["runtimeBinding"] = dict(runtime_binding)
    validate_contract(payload, "agent-session.v1.json")
    return payload


def _joined_runtime_binding(row: sqlite3.Row) -> dict[str, object] | None:
    if row["runtime_driver_id"] is None:
        return None
    return {
        "schemaVersion": "rag-ime.agent-runtime-binding.v1",
        "driverId": str(row["runtime_driver_id"]),
        "runtimeKind": str(row["runtime_kind"]),
        "generation": int(row["runtime_generation"]),
        "state": str(row["runtime_binding_state"]),
        "createdAtMs": int(row["runtime_binding_created_at_ms"]),
        "updatedAtMs": int(row["runtime_binding_updated_at_ms"]),
    }


def _runtime_binding_payload(row: sqlite3.Row) -> dict[str, object]:
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    return {
        "schemaVersion": "rag-ime.agent-runtime-binding.v1",
        "sessionId": str(row["session_id"]),
        "driverId": str(row["driver_id"]),
        "runtimeKind": str(row["runtime_kind"]),
        "externalSessionId": str(row["external_session_id"]),
        "transcriptRef": str(row["transcript_ref"] or ""),
        "branchAnchor": str(row["branch_anchor"] or ""),
        "generation": int(row["generation"]),
        "state": str(row["binding_state"]),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
    }


def _agent_plan_item(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": str(row["item_id"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "sequence": int(row["sequence"]),
        "updatedAtMs": int(row["created_at_ms"]),
    }


def _runtime_binding_text(
    value: object,
    *,
    field: str,
    maximum: int,
    required: bool = True,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"runtime binding {field} must not be empty")
    if len(text) > maximum or "\x00" in text:
        raise ValueError(f"runtime binding {field} is invalid")
    return text


def _approval_payload(row: sqlite3.Row) -> dict[str, object]:
    preview = json.loads(str(row["preview_json"] or "{}"))
    receipt = json.loads(str(row["receipt_json"])) if row["receipt_json"] else None
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-approval.v1",
        "approvalId": str(row["approval_id"]),
        "sessionId": str(row["session_id"]),
        "toolId": str(row["tool_name"]),
        "operation": str(row["operation"]),
        "payloadSha256": str(row["payload_sha256"]),
        "preview": preview if isinstance(preview, dict) else {},
        "riskLevel": str(row["risk_level"]),
        "state": str(row["state"]),
        "requestedAtMs": int(row["requested_at_ms"]),
        "expiresAtMs": int(row["expires_at_ms"]),
        "decidedAtMs": int(row["decided_at_ms"]) if row["decided_at_ms"] is not None else None,
        "receipt": receipt if isinstance(receipt, dict) else None,
    }
    validate_contract(payload, "agent-approval.v1.json")
    return payload


def _workspace_roots(values: Iterable[str]) -> list[str]:
    roots: list[str] = []
    for value in values:
        path = str(value).strip()
        if not path:
            continue
        normalized = str(Path(path).expanduser().resolve(strict=False))
        if normalized not in roots:
            roots.append(normalized)
    return roots


def _allowed_tools(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ValueError("allowedTools must be an array")
    tools: list[str] = []
    for value in values:
        tool = str(value or "").strip()
        if not tool or len(tool) > 120 or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in tool):
            raise ValueError("allowedTools contains an invalid tool id")
        if tool not in tools:
            tools.append(tool)
    if len(tools) > 100:
        raise ValueError("allowedTools contains too many tool ids")
    return tools


def _stored_allowed_tools(value: object) -> list[str] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(str(value or "null"))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [str(item) for item in parsed if str(item).strip()]


def _timestamp(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
