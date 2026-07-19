from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


EVENT_TYPES = (
    "session_start",
    "turn_end",
    "compaction",
    "project_complete",
    "tool_failed",
    "idle",
)
_ACTIONS = {"audit_only", "context_checkpoint", "memory_review_suggestion"}


class AgentLifecycleHookService:
    """Durable, governed lifecycle boundary for the managed Agent runtime."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def snapshot(self, *, limit: int = 30) -> dict[str, object]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            policies = [
                {
                    "eventType": str(row["event_type"]),
                    "enabled": bool(row["enabled"]),
                    "action": str(row["action"]),
                    "tokenLimit": int(row["token_limit"]),
                    "cooldownSeconds": int(row["cooldown_seconds"]),
                    "updatedAtMs": int(row["updated_at_ms"]),
                }
                for row in conn.execute(
                    "SELECT * FROM agent_lifecycle_hook_policies ORDER BY rowid"
                )
            ]
            events = [
                self._event_payload(row)
                for row in conn.execute(
                    """
                    SELECT * FROM agent_lifecycle_hook_events
                    ORDER BY created_at_ms DESC LIMIT ?
                    """,
                    (limit,),
                )
            ]
        return {
            "schemaVersion": "rag-ime.agent-lifecycle-hooks.v1",
            "ok": True,
            "policies": policies,
            "recentEvents": events,
            "guardrails": {
                "writesLongTermMemory": False,
                "expandsToolPermissions": False,
                "bypassesApprovals": False,
                "suggestionsConsumedOnNextTurn": True,
            },
        }

    def update_policy(self, payload: Mapping[str, object]) -> dict[str, object]:
        event_type = _event_type(payload.get("eventType"))
        changes: list[str] = []
        values: list[object] = []
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("lifecycle enabled must be a boolean")
            changes.append("enabled = ?")
            values.append(1 if payload["enabled"] else 0)
        if "tokenLimit" in payload:
            token_limit = _bounded_int(payload["tokenLimit"], "tokenLimit", 0, 2048)
            changes.append("token_limit = ?")
            values.append(token_limit)
        if "cooldownSeconds" in payload:
            cooldown = _bounded_int(payload["cooldownSeconds"], "cooldownSeconds", 0, 86400)
            changes.append("cooldown_seconds = ?")
            values.append(cooldown)
        if "action" in payload:
            action = str(payload["action"] or "")
            if action not in _ACTIONS:
                raise ValueError("unsupported lifecycle hook action")
            if event_type == "project_complete" and action == "context_checkpoint":
                raise ValueError(
                    "project completion may be audited or proposed for memory review, "
                    "but not injected as an implicit checkpoint"
                )
            changes.append("action = ?")
            values.append(action)
        if not changes:
            raise ValueError("lifecycle policy update has no supported changes")
        changes.append("updated_at_ms = ?")
        values.append(_now_ms())
        values.append(event_type)
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                f"UPDATE agent_lifecycle_hook_policies SET {', '.join(changes)} WHERE event_type = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise ValueError("lifecycle policy does not exist")
        return self.snapshot()

    def record_event(self, payload: Mapping[str, object]) -> dict[str, object]:
        if str(payload.get("schemaVersion") or "") != "rag-ime.agent-lifecycle-event.v1":
            raise ValueError("unsupported lifecycle event schemaVersion")
        event_id = _identifier(payload.get("eventId"), "eventId")
        event_type = _event_type(payload.get("eventType"))
        session_id = _identifier(payload.get("sessionId"), "sessionId")
        project = str(payload.get("project") or "")[:256]
        occurred_at_ms = int(payload.get("occurredAtMs") or _now_ms())
        raw_event_payload = payload.get("payload")
        if not isinstance(raw_event_payload, Mapping):
            raise ValueError("lifecycle payload must be an object")
        raw_facts = raw_event_payload.get("facts", raw_event_payload.get("stableFacts"))
        if raw_facts is None:
            facts: list[dict[str, str]] = []
        elif not isinstance(raw_facts, list):
            raise ValueError("lifecycle facts must be an array")
        else:
            facts = []
            for item in raw_facts[:20]:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        facts.append({"text": text[:1000], "evidence": ""})
                    continue
                if not isinstance(item, Mapping):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                facts.append(
                    {
                        "text": text[:1000],
                        "evidence": str(item.get("evidence") or "").strip()[:500],
                    }
                )
        clean_metadata = {
            str(key): value
            for key, value in raw_event_payload.items()
            if key not in {"facts", "stableFacts"}
        }
        with self._connect(immediate=True) as conn:
            policy = conn.execute(
                "SELECT * FROM agent_lifecycle_hook_policies WHERE event_type = ?",
                (event_type,),
            ).fetchone()
            if policy is None:
                raise ValueError("lifecycle policy does not exist")
            idle_policy = conn.execute(
                "SELECT cooldown_seconds FROM agent_lifecycle_hook_policies WHERE event_type = 'idle'"
            ).fetchone()
            idle_delay_ms = int(idle_policy["cooldown_seconds"]) * 1000 if idle_policy else 0
            existing = conn.execute(
                "SELECT * FROM agent_lifecycle_hook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["event_type"]) != event_type
                    or str(existing["session_id"]) != session_id
                ):
                    raise ValueError(
                        "lifecycle eventId was already used for a different event"
                    )
                return self._result(
                    self._event_payload(existing),
                    policy=policy,
                    deduplicated=True,
                    idle_delay_ms=idle_delay_ms,
                )
            action = str(policy["action"])
            status = "recorded"
            reason = ""
            suggestion: dict[str, object] | None = None
            if not bool(policy["enabled"]):
                status, reason = "disabled", "policy_disabled"
            elif not facts and action != "audit_only":
                status, reason = "skipped", "no_facts"
            elif int(policy["cooldown_seconds"]) > 0:
                latest = conn.execute(
                    """
                    SELECT created_at_ms FROM agent_lifecycle_hook_events
                    WHERE event_type = ? AND session_id = ?
                      AND status IN ('recorded', 'suggested')
                    ORDER BY created_at_ms DESC LIMIT 1
                    """,
                    (event_type, session_id),
                ).fetchone()
                if latest is not None and _now_ms() - int(latest["created_at_ms"]) < int(policy["cooldown_seconds"]) * 1000:
                    status, reason = "cooldown", "cooldown_active"
            if status == "recorded" and action == "memory_review_suggestion":
                status = "suggested"
                suggestion = {
                    "kind": "memory_review",
                    "consume": "next_turn",
                    "tokenLimit": int(policy["token_limit"]),
                    "facts": facts,
                    "nextTurnContext": _next_turn_context(
                        event_type,
                        facts,
                        token_limit=int(policy["token_limit"]),
                    ),
                }
            elif status == "recorded" and action == "context_checkpoint":
                suggestion = {
                    "kind": "context_checkpoint",
                    "consume": "next_turn",
                    "tokenLimit": int(policy["token_limit"]),
                    "facts": facts,
                    "nextTurnContext": _next_turn_context(
                        event_type,
                        facts,
                        token_limit=int(policy["token_limit"]),
                    ),
                }
            created_at_ms = _now_ms()
            conn.execute(
                """
                INSERT INTO agent_lifecycle_hook_events(
                    event_id, event_type, session_id, project, facts_json,
                    metadata_json, status, action, reason, suggestion_json,
                    occurred_at_ms, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    session_id,
                    project,
                    _json(facts),
                    _json(clean_metadata),
                    status,
                    action,
                    reason,
                    _json(suggestion) if suggestion is not None else None,
                    occurred_at_ms,
                    created_at_ms,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_lifecycle_hook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return self._result(
            self._event_payload(row),
            policy=policy,
            deduplicated=False,
            idle_delay_ms=idle_delay_ms,
        )

    @staticmethod
    def _result(
        event: Mapping[str, object],
        *,
        policy: sqlite3.Row,
        deduplicated: bool,
        idle_delay_ms: int,
    ) -> dict[str, object]:
        suggestion = event.get("suggestion")
        next_turn_context = (
            str(suggestion.get("nextTurnContext") or "")
            if isinstance(suggestion, Mapping)
            else ""
        )
        return {
            "schemaVersion": "rag-ime.agent-lifecycle-event-result.v1",
            "ok": True,
            "result": {
                "eventId": str(event.get("eventId") or ""),
                "deduplicated": deduplicated,
                "enabled": bool(policy["enabled"]),
                "action": str(event.get("action") or policy["action"]),
                "nextTurnContext": next_turn_context[:2000],
                "idleDelayMs": idle_delay_ms,
                "status": str(event.get("status") or ""),
                "reason": str(event.get("reason") or ""),
            },
            "guardrails": {
                "writesLongTermMemory": False,
                "expandsToolPermissions": False,
                "bypassesPlanGoalOrApproval": False,
            },
        }

    @staticmethod
    def _event_payload(row: sqlite3.Row) -> dict[str, object]:
        suggestion = json.loads(str(row["suggestion_json"])) if row["suggestion_json"] else None
        return {
            "eventId": str(row["event_id"]),
            "eventType": str(row["event_type"]),
            "sessionId": str(row["session_id"]),
            "project": str(row["project"]),
            "status": str(row["status"]),
            "action": str(row["action"]),
            "reason": str(row["reason"]),
            "suggestion": suggestion,
            "occurredAtMs": int(row["occurred_at_ms"]),
            "createdAtMs": int(row["created_at_ms"]),
        }

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _event_type(value: object) -> str:
    event_type = str(value or "")
    if event_type not in EVENT_TYPES:
        raise ValueError("unsupported lifecycle eventType")
    return event_type


def _identifier(value: object, name: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 256:
        raise ValueError(f"lifecycle {name} is required and must be at most 256 characters")
    return result


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"lifecycle {name} must be an integer")
    result = int(value)
    if result < minimum or result > maximum:
        raise ValueError(f"lifecycle {name} must be between {minimum} and {maximum}")
    return result


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _next_turn_context(
    event_type: str,
    facts: list[dict[str, str]],
    *,
    token_limit: int,
) -> str:
    maximum = max(0, min(2000, token_limit * 4))
    if not facts or maximum == 0:
        return ""
    lines = [
        f"Lifecycle review suggestion ({event_type}).",
        "Check only these evidenced facts on the next turn. Do not write long-term memory directly:",
    ]
    for fact in facts:
        evidence = fact.get("evidence") or "evidence not supplied"
        lines.append(f"- {fact['text']} (evidence: {evidence})")
    return "\n".join(lines)[:maximum]
