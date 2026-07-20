from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Iterable, Mapping

from .agent_tool_ids import SUPPORTED_AGENT_TOOL_PROFILES
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
        role_id: str = "vcp-v1",
        role_version: str = "1",
        role_book_revision_id: str = "",
        model_profile: str = "gpt/gpt-5.6-sol",
        thinking_level: str = "max",
        tool_profile_version: str = "control-center-v1",
        project_context_enabled: bool = True,
        pi_skills_enabled: bool = False,
        codex_skills_enabled: bool = False,
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
        normalized_model_profile = str(model_profile or "").strip()
        if not normalized_model_profile:
            raise ValueError("agent session model profile must not be empty")
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
        if str(tool_profile_version or "").strip() not in SUPPORTED_AGENT_TOOL_PROFILES:
            raise ValueError("unsupported Agent tool profile")
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        session_id = f"agent:{uuid.uuid4()}"
        normalized_role_book_revision_id = str(role_book_revision_id or "").strip()
        if len(normalized_role_book_revision_id) > 240:
            raise ValueError("agent role book revision id is too long")
        shell_policy = shell_policy_version or (
            "coordinator-per-command-v1" if mode == "coordinator" else "assistant-no-shell-v1"
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions(
                    id, title, session_mode, role_id, role_version, role_book_revision_id,
                    model_profile, thinking_level,
                    tool_profile_version, project_context_enabled,
                    pi_skills_enabled, codex_skills_enabled, workspace_roots_json,
                    shell_policy_version, session_kind, created_at_ms, updated_at_ms,
                    last_opened_at_ms, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle')
                """,
                (
                    session_id,
                    normalized_title,
                    mode,
                    role_id,
                    role_version,
                    normalized_role_book_revision_id,
                    normalized_model_profile,
                    normalized_thinking,
                    tool_profile_version,
                    1 if project_context_enabled else 0,
                    1 if pi_skills_enabled else 0,
                    1 if codex_skills_enabled else 0,
                    json.dumps(roots, ensure_ascii=False, separators=(",", ":")),
                    shell_policy,
                    normalized_kind,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(session_id)

    def set_role_book_revision(
        self,
        session_id: str,
        revision_id: str,
        *,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized = str(revision_id or "").strip()
        if not normalized:
            raise ValueError("agent role book revision id must not be empty")
        if len(normalized) > 240:
            raise ValueError("agent role book revision id is too long")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role_book_revision_id FROM agent_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise AgentSessionNotFound(session_id)
            current = str(row["role_book_revision_id"] or "")
            if current and current != normalized:
                raise ValueError(
                    "agent session role book revision is immutable after pinning"
                )
            if not current:
                conn.execute(
                    """
                    UPDATE agent_sessions
                    SET role_book_revision_id = ?, updated_at_ms = ?
                    WHERE id = ? AND role_book_revision_id = ''
                    """,
                    (normalized, _timestamp(updated_at_ms), session_id),
                )
                selected = conn.execute(
                    "SELECT role_book_revision_id FROM agent_sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if selected is None or str(selected[0]) != normalized:
                    raise RuntimeError("agent session role book pin changed concurrently")
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
        project_context_enabled: bool | None = None,
        pi_skills_enabled: bool | None = None,
        codex_skills_enabled: bool | None = None,
        workspace_roots: Iterable[str] | None = None,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_mode = str(mode or "").strip()
        if normalized_mode not in {"assistant", "coordinator"}:
            raise ValueError("agent session mode must be assistant or coordinator")
        profile = str(tool_profile_version or "").strip()
        if profile not in SUPPORTED_AGENT_TOOL_PROFILES:
            raise ValueError("unsupported Agent tool profile")
        current = self.get(session_id)
        roots = _workspace_roots(
            current.get("workspaceRoots", []) if workspace_roots is None else workspace_roots
        )
        if normalized_mode == "assistant":
            roots = []
        normalized_tools = _allowed_tools(allowed_tools)
        context_enabled = (
            bool(current.get("projectContextEnabled", True))
            if project_context_enabled is None
            else bool(project_context_enabled)
        )
        load_pi_skills = (
            bool(current.get("piSkillsEnabled", False))
            if pi_skills_enabled is None
            else bool(pi_skills_enabled)
        )
        load_codex_skills = (
            bool(current.get("codexSkillsEnabled", False))
            if codex_skills_enabled is None
            else bool(codex_skills_enabled)
        )
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
                    shell_policy_version = ?, project_context_enabled = ?,
                    pi_skills_enabled = ?, codex_skills_enabled = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (
                    normalized_mode,
                    profile,
                    json.dumps(roots, ensure_ascii=False, separators=(",", ":")),
                    shell_policy,
                    1 if context_enabled else 0,
                    1 if load_pi_skills else 0,
                    1 if load_codex_skills else 0,
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
            return _agent_plan_projection(conn, session_id, limit=bounded_limit)

    def mutate_agent_plan(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        actor: str = "control-center-user",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        action = str(payload.get("action") or "").strip()
        if action not in {
            "save",
            "submit_review",
            "approve",
            "return_to_draft",
            "start_execution",
            "complete",
            "cancel",
            "reset",
        }:
            raise ValueError("unsupported agent plan action")
        timestamp = _timestamp(updated_at_ms)
        normalized_actor = _bounded_plan_text(actor, field="actor", maximum=120)
        note = _bounded_plan_text(payload.get("note"), field="note", maximum=600, required=False)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT id FROM agent_sessions WHERE id = ? AND status <> 'archived'",
                (session_id,),
            ).fetchone()
            if session is None:
                raise AgentSessionNotFound(session_id)
            current = _agent_plan_projection(conn, session_id, limit=100)
            expected_revision = payload.get("expectedRevision")
            if expected_revision is not None and int(expected_revision) != int(current["revision"]):
                raise ValueError("agent plan changed; refresh before saving")
            current_status = str(current["status"])
            if action in {"save", "submit_review"} and current_status != "draft":
                raise ValueError("only a draft plan can be edited or submitted")
            if action == "approve" and current_status != "review":
                raise ValueError("only a plan in review can be approved")
            if action == "return_to_draft" and current_status not in {"review", "approved"}:
                raise ValueError("only a reviewed or approved plan can return to draft")
            if action == "start_execution" and current_status not in {"approved", "executing"}:
                raise ValueError("plan approval is required before execution")
            if action == "complete" and current_status not in {"approved", "executing"}:
                raise ValueError("only an approved or executing plan can be completed")
            if action == "cancel" and current_status in {"completed", "cancelled"}:
                raise ValueError("terminal plans cannot be cancelled again")
            if action == "reset" and current_status not in {"completed", "cancelled"}:
                raise ValueError("only a terminal plan can be reset")

            title = _bounded_plan_text(
                payload.get("title") if "title" in payload else current.get("title"),
                field="title",
                maximum=160,
            )
            if action in {"save", "submit_review", "reset"}:
                raw_items = payload.get("items", [] if action == "reset" else None)
                if raw_items is not None:
                    if not isinstance(raw_items, list):
                        raise ValueError("agent plan items must be an array")
                    _replace_agent_plan_items(
                        conn,
                        session_id,
                        raw_items,
                        timestamp=timestamp,
                    )

            projected = _agent_plan_projection(conn, session_id, limit=100)
            if action in {"submit_review", "approve", "start_execution", "complete"} and not projected["items"]:
                raise ValueError("agent plan must contain at least one item")
            if action == "complete" and any(
                str(item.get("status") or "") != "completed"
                for item in projected["items"]
            ):
                raise ValueError("all agent plan items must be completed first")

            target_status = {
                "save": "draft",
                "submit_review": "review",
                "approve": "approved",
                "return_to_draft": "draft",
                "start_execution": "executing",
                "complete": "completed",
                "cancel": "cancelled",
                "reset": "draft",
            }[action]
            state_event = _append_agent_plan_state(
                conn,
                session_id,
                title=title,
                status=target_status,
                actor=normalized_actor,
                note=note,
                created_at_ms=timestamp,
            )
            conn.execute(
                "UPDATE agent_sessions SET updated_at_ms = ? WHERE id = ?",
                (timestamp, session_id),
            )
            plan = _agent_plan_projection(conn, session_id, limit=100)
        return {
            "schemaVersion": "rag-ime.agent-plan-mutation-result.v1",
            "ok": True,
            "action": action,
            "event": state_event,
            "plan": plan,
        }

    def agent_goal(self, session_id: str) -> dict[str, object]:
        self.get(session_id)
        with self._connect() as conn:
            return _agent_goal_projection(conn, session_id)

    def workflow_state(self, session_id: str) -> dict[str, object]:
        self.get(session_id)
        with self._connect() as conn:
            plan = _agent_plan_projection(conn, session_id, limit=100)
            goal = _agent_goal_projection(conn, session_id)
        return {
            "schemaVersion": "rag-ime.agent-workflow-state.v1",
            "ok": True,
            "sessionId": session_id,
            "plan": plan,
            "goal": goal,
            "actGate": _agent_act_gate(plan, goal),
        }

    def mutate_agent_goal(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        actor: str = "control-center-user",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        action = str(payload.get("action") or "").strip()
        if action not in {"set", "update", "pause", "resume", "complete", "clear"}:
            raise ValueError("unsupported agent goal action")
        timestamp = _timestamp(updated_at_ms)
        normalized_actor = _bounded_goal_text(actor, field="actor", maximum=120)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT id FROM agent_sessions WHERE id = ? AND status <> 'archived'",
                (session_id,),
            ).fetchone()
            if session is None:
                raise AgentSessionNotFound(session_id)
            current = _agent_goal_projection(conn, session_id)
            expected_revision = payload.get("expectedRevision")
            if expected_revision is not None and int(expected_revision) != int(current["revision"]):
                raise ValueError("agent goal changed; refresh before saving")
            configured = bool(current["configured"])
            current_status = str(current["status"])
            if action == "set" and configured:
                raise ValueError("clear the current agent goal before setting another")
            if action in {"update", "pause", "resume", "complete", "clear"} and not configured:
                raise ValueError("this Session has no active agent goal")
            if action == "update" and current_status not in {"active", "paused"}:
                raise ValueError("only an active or paused goal can be edited")
            if action == "pause" and current_status != "active":
                raise ValueError("only an active goal can be paused")
            if action == "resume" and current_status != "paused":
                raise ValueError("only a paused goal can be resumed")
            if action == "complete" and current_status not in {"active", "paused"}:
                raise ValueError("only an active or paused goal can be completed")
            if action == "clear" and current_status == "cleared":
                raise ValueError("agent goal is already cleared")

            goal_id = (
                f"goal:{uuid.uuid4()}"
                if action == "set"
                else str(current["goalId"])
            )
            objective = _bounded_goal_text(
                payload.get("objective")
                if action == "set" or "objective" in payload
                else current.get("objective"),
                field="objective",
                maximum=4_000,
            )
            current_budget = current.get("budget") if isinstance(current.get("budget"), Mapping) else {}
            token_budget = _optional_positive_budget(
                payload.get("tokenBudget")
                if "tokenBudget" in payload
                else current_budget.get("tokenLimit"),
                field="tokenBudget",
                maximum=100_000_000,
            )
            time_budget_ms = _optional_positive_budget(
                payload.get("timeBudgetMs")
                if "timeBudgetMs" in payload
                else current_budget.get("timeLimitMs"),
                field="timeBudgetMs",
                maximum=365 * 24 * 60 * 60 * 1000,
            )
            usage = current.get("usage") if isinstance(current.get("usage"), Mapping) else {}
            tokens_used = int(usage.get("tokens") or 0) if configured else 0
            elapsed_ms = int(usage.get("elapsedMs") or 0) if configured else 0
            audit_id: str | None = None
            if action == "complete":
                summary = _bounded_goal_text(
                    payload.get("summary"),
                    field="completion summary",
                    maximum=2_000,
                )
                evidence = _goal_completion_evidence(payload.get("evidence"))
                audit_id = f"goal-audit:{uuid.uuid4()}"
                conn.execute(
                    """
                    INSERT INTO agent_goal_completion_audits(
                        audit_id, session_id, goal_id, summary, evidence_json,
                        completed_by, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        session_id,
                        goal_id,
                        summary,
                        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                        normalized_actor,
                        timestamp,
                    ),
                )

            target_status = {
                "set": "active",
                "update": current_status,
                "pause": "paused",
                "resume": "active",
                "complete": "completed",
                "clear": "cleared",
            }[action]
            event = _append_agent_goal_event(
                conn,
                session_id,
                goal_id=goal_id,
                objective=objective,
                status=target_status,
                token_budget=token_budget,
                time_budget_ms=time_budget_ms,
                tokens_used=tokens_used,
                elapsed_ms=elapsed_ms,
                completion_audit_id=audit_id,
                actor=normalized_actor,
                created_at_ms=timestamp,
            )
            conn.execute(
                "UPDATE agent_sessions SET updated_at_ms = ? WHERE id = ?",
                (timestamp, session_id),
            )
            goal = _agent_goal_projection(conn, session_id)
            plan = _agent_plan_projection(conn, session_id, limit=100)
        return {
            "schemaVersion": "rag-ime.agent-goal-mutation-result.v1",
            "ok": True,
            "action": action,
            "event": event,
            "workflow": {
                "schemaVersion": "rag-ime.agent-workflow-state.v1",
                "ok": True,
                "sessionId": session_id,
                "plan": plan,
                "goal": goal,
                "actGate": _agent_act_gate(plan, goal),
            },
        }

    def record_agent_goal_usage(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        turn_id: str = "",
        event_id: str = "",
        token_delta: int = 0,
        elapsed_delta_ms: int = 0,
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_key = str(idempotency_key or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        normalized_event_id = str(event_id or "").strip()
        if not normalized_key or len(normalized_key) > 300 or "\x00" in normalized_key:
            raise ValueError("goal usage idempotencyKey is invalid")
        if len(normalized_turn_id) > 240 or "\x00" in normalized_turn_id:
            raise ValueError("goal usage turnId is invalid")
        if len(normalized_event_id) > 240 or "\x00" in normalized_event_id:
            raise ValueError("goal usage eventId is invalid")
        normalized_token_delta = int(token_delta)
        normalized_elapsed_delta = int(elapsed_delta_ms)
        if normalized_token_delta < 0 or normalized_token_delta > 10_000_000:
            raise ValueError("goal tokenDelta is invalid")
        if normalized_elapsed_delta < 0 or normalized_elapsed_delta > 7 * 24 * 60 * 60 * 1000:
            raise ValueError("goal elapsedDeltaMs is invalid")
        timestamp = _timestamp(updated_at_ms)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            receipt = conn.execute(
                """
                SELECT goal_id, turn_id, source_event_id, token_delta, elapsed_delta_ms
                FROM agent_goal_usage_receipts
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (session_id, normalized_key),
            ).fetchone()
            if receipt is not None:
                if (
                    str(receipt["turn_id"]) != normalized_turn_id
                    or str(receipt["source_event_id"]) != normalized_event_id
                    or int(receipt["token_delta"]) != normalized_token_delta
                    or int(receipt["elapsed_delta_ms"]) != normalized_elapsed_delta
                ):
                    raise ValueError("goal usage idempotencyKey was reused with different data")
                plan = _agent_plan_projection(conn, session_id, limit=100)
                goal = _agent_goal_projection(conn, session_id)
                return {
                    "schemaVersion": "rag-ime.agent-workflow-state.v1",
                    "ok": True,
                    "sessionId": session_id,
                    "plan": plan,
                    "goal": goal,
                    "actGate": _agent_act_gate(plan, goal),
                }
            current = _agent_goal_projection(conn, session_id)
            if not current["configured"] or current["status"] != "active":
                raise ValueError("goal usage can only be recorded for an active goal")
            budget = current["budget"] if isinstance(current.get("budget"), Mapping) else {}
            usage = current["usage"] if isinstance(current.get("usage"), Mapping) else {}
            usage_event = _append_agent_goal_event(
                conn,
                session_id,
                goal_id=str(current["goalId"]),
                objective=str(current["objective"]),
                status="active",
                token_budget=_optional_positive_budget(
                    budget.get("tokenLimit"), field="tokenBudget", maximum=100_000_000
                ),
                time_budget_ms=_optional_positive_budget(
                    budget.get("timeLimitMs"),
                    field="timeBudgetMs",
                    maximum=365 * 24 * 60 * 60 * 1000,
                ),
                tokens_used=int(usage.get("tokens") or 0) + normalized_token_delta,
                elapsed_ms=int(usage.get("elapsedMs") or 0) + normalized_elapsed_delta,
                completion_audit_id=None,
                actor="pi-runtime",
                created_at_ms=timestamp,
            )
            conn.execute(
                """
                INSERT INTO agent_goal_usage_receipts(
                    receipt_id, session_id, goal_id, idempotency_key, turn_id,
                    source_event_id, token_delta, elapsed_delta_ms,
                    goal_event_id, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"goal-usage:{uuid.uuid4()}",
                    session_id,
                    str(current["goalId"]),
                    normalized_key,
                    normalized_turn_id,
                    normalized_event_id,
                    normalized_token_delta,
                    normalized_elapsed_delta,
                    str(usage_event["eventId"]),
                    timestamp,
                ),
            )
            plan = _agent_plan_projection(conn, session_id, limit=100)
            goal = _agent_goal_projection(conn, session_id)
        return {
            "schemaVersion": "rag-ime.agent-workflow-state.v1",
            "ok": True,
            "sessionId": session_id,
            "plan": plan,
            "goal": goal,
            "actGate": _agent_act_gate(plan, goal),
        }

    def require_workspace_act(self, session_id: str) -> dict[str, object]:
        state = self.workflow_state(session_id)
        gate = state["actGate"] if isinstance(state.get("actGate"), Mapping) else {}
        if gate.get("allowed") is not True:
            reason = str(gate.get("reason") or "act_gate_closed")
            message = str(gate.get("message") or "workspace mutation is not approved")
            raise ValueError(f"Act Gate blocked workspace mutation ({reason}): {message}")
        return state

    def require_goal_execution(self, session_id: str) -> dict[str, object]:
        """Reject new cost-incurring work while a configured Goal cannot run."""

        state = self.workflow_state(session_id)
        goal = state["goal"] if isinstance(state.get("goal"), Mapping) else {}
        if goal.get("configured") is not True:
            return state
        status = str(goal.get("status") or "")
        if status == "paused":
            raise ValueError(
                "Goal execution blocked (goal_paused): 当前 Goal 已暂停，恢复后才能继续调用模型或委派任务。"
            )
        if goal.get("budgetExceeded") is True:
            raise ValueError(
                "Goal execution blocked (goal_budget_exhausted): Goal 的 Token 或时间预算已经耗尽。"
            )
        return state

    def begin_agent_plan_execution(self, session_id: str) -> dict[str, object]:
        state = self.require_workspace_act(session_id)
        plan = state["plan"] if isinstance(state.get("plan"), Mapping) else {}
        if plan.get("status") != "approved":
            return state
        self.mutate_agent_plan(
            session_id,
            {
                "action": "start_execution",
                "expectedRevision": plan.get("revision"),
                "note": "首个受控工作区写操作开始执行",
            },
            actor="agent-runtime",
        )
        return self.workflow_state(session_id)

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
                SELECT title, status, position, is_deleted FROM agent_plan_events
                WHERE session_id = ? AND item_id = ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (session_id, normalized_item_id),
            ).fetchone()
            plan_state = conn.execute(
                """
                SELECT status FROM agent_plan_state_events
                WHERE session_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            lifecycle = str(plan_state["status"]) if plan_state is not None else "draft"
            active_current = current is not None and int(current["is_deleted"]) == 0
            if lifecycle in {"review", "completed", "cancelled"}:
                raise ValueError(f"plan items cannot change while plan is {lifecycle}")
            if lifecycle in {"approved", "executing"}:
                if not active_current:
                    raise ValueError("approved plan scope cannot add new items")
                if requested_title and requested_title != str(current["title"]):
                    raise ValueError("approved plan item titles cannot change")
            active_stats = conn.execute(
                """
                WITH latest AS (
                    SELECT item_id, position, is_deleted,
                           ROW_NUMBER() OVER (
                               PARTITION BY item_id ORDER BY sequence DESC
                           ) AS row_number
                    FROM agent_plan_events WHERE session_id = ?
                )
                SELECT COUNT(*) AS item_count, COALESCE(MAX(position), 0) AS max_position
                FROM latest WHERE row_number = 1 AND is_deleted = 0
                """,
                (session_id,),
            ).fetchone()
            item_count = int(active_stats["item_count"])
            if not active_current and item_count >= 100:
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
                        SELECT item_id, status, is_deleted,
                               ROW_NUMBER() OVER (
                                   PARTITION BY item_id ORDER BY sequence DESC
                               ) AS row_number
                        FROM agent_plan_events WHERE session_id = ?
                    )
                    SELECT item_id FROM latest
                    WHERE row_number = 1 AND is_deleted = 0
                      AND status = 'in_progress' AND item_id <> ?
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
                    event_id, session_id, sequence, item_id, title, status,
                    position, is_deleted, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    event_id,
                    session_id,
                    sequence,
                    normalized_item_id,
                    normalized_title,
                    normalized_status,
                    (
                        int(current["position"])
                        if active_current
                        else int(active_stats["max_position"]) + 1
                    ),
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
        metrics: Mapping[str, object] | None = None,
        retain_per_session: int = 1000,
    ) -> None:
        try:
            metrics_json = json.dumps(
                dict(metrics or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime event metrics must be JSON serializable") from exc
        if len(metrics_json.encode("utf-8")) > 8_192:
            raise ValueError("runtime event metrics are too large")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_runtime_events(
                    event_id, session_id, turn_id, sequence, event_type,
                    created_at_ms, redacted_summary, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    turn_id,
                    sequence,
                    event_type,
                    created_at_ms,
                    " ".join(redacted_summary.split())[:240],
                    metrics_json,
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
    model_profile = str(row["model_profile"] or "").strip() or "pi/default"
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
        "roleBookRevisionId": str(row["role_book_revision_id"] or ""),
        "modelProfile": model_profile,
        "thinkingLevel": str(row["thinking_level"] or ""),
        "toolProfileVersion": str(row["tool_profile_version"]),
        "toolAllowlistMode": "explicit" if allowed_tools is not None else "profile",
        "allowedTools": allowed_tools or [],
        "projectContextEnabled": bool(row["project_context_enabled"]),
        "piSkillsEnabled": bool(row["pi_skills_enabled"]),
        "codexSkillsEnabled": bool(row["codex_skills_enabled"]),
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
        "position": int(row["position"]),
        "sequence": int(row["sequence"]),
        "updatedAtMs": int(row["created_at_ms"]),
    }


def _agent_plan_projection(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int,
) -> dict[str, object]:
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT event_id, sequence, item_id, title, status, position,
                   is_deleted, created_at_ms,
                   MIN(sequence) OVER (PARTITION BY item_id) AS first_sequence,
                   ROW_NUMBER() OVER (
                       PARTITION BY item_id ORDER BY sequence DESC
                   ) AS row_number
            FROM agent_plan_events
            WHERE session_id = ?
        )
        SELECT event_id, sequence, item_id, title, status, position, created_at_ms
        FROM latest
        WHERE row_number = 1 AND is_deleted = 0
        ORDER BY
            CASE WHEN position > 0 THEN position ELSE 1000000 + first_sequence END,
            first_sequence,
            item_id
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    state = conn.execute(
        """
        SELECT event_id, sequence, title, status, actor, note, created_at_ms
        FROM agent_plan_state_events
        WHERE session_id = ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    revisions = conn.execute(
        """
        SELECT
            (SELECT COALESCE(MAX(sequence), 0) FROM agent_plan_events WHERE session_id = ?) +
            (SELECT COALESCE(MAX(sequence), 0) FROM agent_plan_state_events WHERE session_id = ?)
        """,
        (session_id, session_id),
    ).fetchone()
    items = [_agent_plan_item(row) for row in rows]
    completed = sum(1 for item in items if item["status"] == "completed")
    in_progress = sum(1 for item in items if item["status"] == "in_progress")
    status = str(state["status"]) if state is not None else "draft"
    updated_at_ms = max(
        [int(item["updatedAtMs"]) for item in items]
        + ([int(state["created_at_ms"])] if state is not None else [0])
    )
    return {
        "schemaVersion": "rag-ime.agent-plan.v2",
        "id": f"plan:{session_id}",
        "sessionId": session_id,
        "revision": int(revisions[0] if revisions else 0),
        "title": str(state["title"]) if state is not None else "执行计划",
        "status": status,
        "actor": str(state["actor"]) if state is not None else "agent",
        "note": str(state["note"]) if state is not None else "",
        "updatedAtMs": updated_at_ms,
        "editable": status == "draft",
        "actApproved": status in {"approved", "executing"},
        "items": items,
        "counts": {
            "total": len(items),
            "pending": len(items) - completed - in_progress,
            "inProgress": in_progress,
            "completed": completed,
        },
    }


def _replace_agent_plan_items(
    conn: sqlite3.Connection,
    session_id: str,
    raw_items: list[object],
    *,
    timestamp: int,
) -> None:
    if len(raw_items) > 100:
        raise ValueError("agent plan is limited to 100 items")
    current_rows = conn.execute(
        """
        WITH latest AS (
            SELECT item_id, title, status, position, is_deleted,
                   ROW_NUMBER() OVER (
                       PARTITION BY item_id ORDER BY sequence DESC
                   ) AS row_number
            FROM agent_plan_events
            WHERE session_id = ?
        )
        SELECT item_id, title, status, position, is_deleted
        FROM latest WHERE row_number = 1
        """,
        (session_id,),
    ).fetchall()
    current = {str(row["item_id"]): row for row in current_rows}
    next_sequence = int(
        conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_plan_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    )
    seen: set[str] = set()
    in_progress_count = 0
    for position, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, Mapping):
            raise ValueError("agent plan item must be an object")
        item_id = str(raw_item.get("id") or raw_item.get("itemId") or "").strip()
        if not item_id:
            item_id = f"plan-item:{uuid.uuid4()}"
        _validate_agent_plan_item_id(item_id)
        if item_id in seen:
            raise ValueError("agent plan item ids must be unique")
        seen.add(item_id)
        previous = current.get(item_id)
        title = _bounded_plan_text(
            raw_item.get("title") if "title" in raw_item else (
                previous["title"] if previous is not None else ""
            ),
            field="item title",
            maximum=240,
        )
        status = str(
            raw_item.get("status")
            or (previous["status"] if previous is not None else "pending")
        ).strip()
        if status not in {"pending", "in_progress", "completed"}:
            raise ValueError("agent plan item status is invalid")
        if status == "in_progress":
            in_progress_count += 1
            if in_progress_count > 1:
                raise ValueError("only one agent plan item may be in_progress")
        conn.execute(
            """
            INSERT INTO agent_plan_events(
                event_id, session_id, sequence, item_id, title, status,
                position, is_deleted, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                f"plan-event:{uuid.uuid4()}",
                session_id,
                next_sequence,
                item_id,
                title,
                status,
                position,
                timestamp,
            ),
        )
        next_sequence += 1
    for item_id, previous in current.items():
        if item_id in seen or int(previous["is_deleted"]):
            continue
        conn.execute(
            """
            INSERT INTO agent_plan_events(
                event_id, session_id, sequence, item_id, title, status,
                position, is_deleted, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                f"plan-event:{uuid.uuid4()}",
                session_id,
                next_sequence,
                item_id,
                str(previous["title"]),
                str(previous["status"]),
                int(previous["position"]),
                timestamp,
            ),
        )
        next_sequence += 1


def _append_agent_plan_state(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    title: str,
    status: str,
    actor: str,
    note: str,
    created_at_ms: int,
) -> dict[str, object]:
    sequence = int(
        conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_plan_state_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    )
    event_id = f"plan-state:{uuid.uuid4()}"
    conn.execute(
        """
        INSERT INTO agent_plan_state_events(
            event_id, session_id, sequence, title, status, actor, note, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, session_id, sequence, title, status, actor, note, created_at_ms),
    )
    return {
        "eventId": event_id,
        "sequence": sequence,
        "title": title,
        "status": status,
        "actor": actor,
        "note": note,
        "createdAtMs": created_at_ms,
    }


def _validate_agent_plan_item_id(item_id: str) -> None:
    if len(item_id) > 160 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-."
        for character in item_id
    ):
        raise ValueError("agent plan itemId is invalid")


def _bounded_plan_text(
    value: object,
    *,
    field: str,
    maximum: int,
    required: bool = True,
) -> str:
    text = " ".join(str(value or "").split())[:maximum]
    if required and not text:
        raise ValueError(f"agent plan {field} must not be empty")
    if "\x00" in text:
        raise ValueError(f"agent plan {field} is invalid")
    return text


def _agent_goal_projection(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT event_id, goal_id, sequence, objective, status, token_budget,
               time_budget_ms, tokens_used, elapsed_ms, completion_audit_id,
               actor, created_at_ms
        FROM agent_thread_goal_events
        WHERE session_id = ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return {
            "schemaVersion": "rag-ime.agent-goal.v1",
            "sessionId": session_id,
            "configured": False,
            "goalId": "",
            "revision": 0,
            "objective": "",
            "status": "cleared",
            "budget": {"tokenLimit": None, "timeLimitMs": None},
            "usage": {"tokens": 0, "elapsedMs": 0},
            "remaining": {"tokens": None, "timeMs": None},
            "budgetExceeded": False,
            "completionAudit": None,
            "updatedAtMs": 0,
        }
    token_budget = int(row["token_budget"]) if row["token_budget"] is not None else None
    time_budget_ms = int(row["time_budget_ms"]) if row["time_budget_ms"] is not None else None
    tokens_used = int(row["tokens_used"])
    elapsed_ms = int(row["elapsed_ms"])
    remaining_tokens = max(0, token_budget - tokens_used) if token_budget is not None else None
    remaining_time = max(0, time_budget_ms - elapsed_ms) if time_budget_ms is not None else None
    audit = None
    audit_id = str(row["completion_audit_id"] or "")
    if audit_id:
        audit_row = conn.execute(
            """
            SELECT audit_id, summary, evidence_json, completed_by, created_at_ms
            FROM agent_goal_completion_audits
            WHERE audit_id = ? AND session_id = ?
            """,
            (audit_id, session_id),
        ).fetchone()
        if audit_row is not None:
            try:
                evidence = json.loads(str(audit_row["evidence_json"] or "[]"))
            except json.JSONDecodeError:
                evidence = []
            audit = {
                "auditId": str(audit_row["audit_id"]),
                "summary": str(audit_row["summary"]),
                "evidence": evidence if isinstance(evidence, list) else [],
                "completedBy": str(audit_row["completed_by"]),
                "createdAtMs": int(audit_row["created_at_ms"]),
            }
    status = str(row["status"])
    configured = status != "cleared"
    return {
        "schemaVersion": "rag-ime.agent-goal.v1",
        "sessionId": session_id,
        "configured": configured,
        "goalId": str(row["goal_id"]),
        "revision": int(row["sequence"]),
        "objective": str(row["objective"]),
        "status": status,
        "budget": {
            "tokenLimit": token_budget,
            "timeLimitMs": time_budget_ms,
        },
        "usage": {"tokens": tokens_used, "elapsedMs": elapsed_ms},
        "remaining": {"tokens": remaining_tokens, "timeMs": remaining_time},
        "budgetExceeded": (
            (token_budget is not None and tokens_used >= token_budget)
            or (time_budget_ms is not None and elapsed_ms >= time_budget_ms)
        ),
        "completionAudit": audit,
        "updatedAtMs": int(row["created_at_ms"]),
    }


def _append_agent_goal_event(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    goal_id: str,
    objective: str,
    status: str,
    token_budget: int | None,
    time_budget_ms: int | None,
    tokens_used: int,
    elapsed_ms: int,
    completion_audit_id: str | None,
    actor: str,
    created_at_ms: int,
) -> dict[str, object]:
    sequence = int(
        conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_thread_goal_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    )
    event_id = f"goal-event:{uuid.uuid4()}"
    conn.execute(
        """
        INSERT INTO agent_thread_goal_events(
            event_id, session_id, goal_id, sequence, objective, status,
            token_budget, time_budget_ms, tokens_used, elapsed_ms,
            completion_audit_id, actor, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            goal_id,
            sequence,
            objective,
            status,
            token_budget,
            time_budget_ms,
            tokens_used,
            elapsed_ms,
            completion_audit_id,
            actor,
            created_at_ms,
        ),
    )
    return {
        "eventId": event_id,
        "goalId": goal_id,
        "sequence": sequence,
        "status": status,
        "actor": actor,
        "createdAtMs": created_at_ms,
    }


def _agent_act_gate(
    plan: Mapping[str, object],
    goal: Mapping[str, object],
) -> dict[str, object]:
    plan_status = str(plan.get("status") or "draft")
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if not items:
        return {
            "allowed": False,
            "reason": "plan_required",
            "message": "先创建执行计划并提交审阅。",
        }
    if plan_status not in {"approved", "executing"}:
        return {
            "allowed": False,
            "reason": "plan_not_approved",
            "message": "计划尚未获得用户批准，只允许只读调研。",
        }
    if goal.get("configured") is True:
        goal_status = str(goal.get("status") or "")
        if goal_status == "paused":
            return {
                "allowed": False,
                "reason": "goal_paused",
                "message": "当前 Goal 已暂停，恢复后才能继续写入。",
            }
        if goal_status == "completed":
            return {
                "allowed": False,
                "reason": "goal_completed",
                "message": "当前 Goal 已完成审计，请清除或设置新 Goal。",
            }
        if goal.get("budgetExceeded") is True:
            return {
                "allowed": False,
                "reason": "goal_budget_exhausted",
                "message": "Goal 的 Token 或时间预算已经耗尽。",
            }
    return {
        "allowed": True,
        "reason": "approved",
        "message": "Plan 已批准，工作区写操作仍需通过原有预览与审批。",
    }


def _optional_positive_budget(
    value: object,
    *,
    field: str,
    maximum: int,
) -> int | None:
    if value in (None, ""):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"agent goal {field} must be an integer") from exc
    if normalized <= 0 or normalized > maximum:
        raise ValueError(f"agent goal {field} is out of range")
    return normalized


def _bounded_goal_text(
    value: object,
    *,
    field: str,
    maximum: int,
) -> str:
    text = " ".join(str(value or "").split())[:maximum]
    if not text or "\x00" in text:
        raise ValueError(f"agent goal {field} must not be empty")
    return text


def _goal_completion_evidence(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("goal completion requires 1 to 20 evidence items")
    evidence: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("goal completion evidence must be an object")
        kind = str(item.get("kind") or "").strip()
        if kind not in {"test", "artifact", "commit", "receipt", "note"}:
            raise ValueError("goal completion evidence kind is invalid")
        summary = " ".join(str(item.get("summary") or "").split())[:600]
        reference = " ".join(str(item.get("reference") or "").split())[:1_000]
        if not summary or not reference:
            raise ValueError("goal completion evidence requires summary and reference")
        evidence.append({"kind": kind, "summary": summary, "reference": reference})
    return evidence


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
