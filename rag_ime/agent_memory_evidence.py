from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .agent_protocol import AgentEventEnvelope
from .memory_evidence_policy import memory_evidence_exclusion_reason
from .memory_maintenance_settings import memory_enabled_from_settings


class AgentMemoryEvidenceService:
    """Journal evidence without allowing failures to block a turn."""

    def __init__(
        self,
        *,
        sessions: Any,
        memory_evidence: Any,
        message_text: Callable[[Mapping[str, object]], str],
        memory_enabled_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.sessions = sessions
        self.memory_evidence = memory_evidence
        self.message_text = message_text
        sessions_db_path = getattr(sessions, "db_path", "")
        self._memory_enabled_provider = memory_enabled_provider or (
            lambda: memory_enabled_from_settings(sessions_db_path)
        )

    def record_user(
        self,
        *,
        session_id: str,
        pi_entry_id: str,
        turn_id: str,
        text: str,
    ) -> dict[str, object]:
        if not self._memory_enabled():
            return _skipped("skipped_memory_disabled")
        if reason := memory_evidence_exclusion_reason(text):
            return _skipped(f"skipped_{reason}")
        try:
            session = self.sessions.get(session_id)
            return self.memory_evidence.record_user_message(
                session_id=session_id,
                pi_entry_id=pi_entry_id,
                turn_id=turn_id,
                text=text,
                role_id=str(session.get("roleId") or ""),
            )
        except Exception as exc:
            return _failure("user_message", exc)

    def record_assistant(
        self,
        event: AgentEventEnvelope,
    ) -> dict[str, object]:
        if not self._memory_enabled():
            return _skipped("skipped_memory_disabled")
        message = event.payload.get("message")
        if (
            not isinstance(message, Mapping)
            or str(message.get("role") or "") != "assistant"
        ):
            return _skipped("skipped_non_assistant")
        text = self.message_text(message)
        if not text:
            return _skipped("skipped_empty")
        if reason := memory_evidence_exclusion_reason(text):
            return _skipped(f"skipped_{reason}")
        try:
            session = self.sessions.get(event.session_id)
            return self.memory_evidence.record_assistant_message(
                session_id=event.session_id,
                pi_entry_id=str(
                    message.get("id") or event.event_id
                ),
                turn_id=event.turn_id,
                text=text,
                role_id=str(session.get("roleId") or ""),
                occurred_at_ms=event.created_at_ms,
            )
        except Exception as exc:
            return _failure("assistant_message", exc)

    def record_tool_receipt(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        if not self._memory_enabled():
            return _skipped("skipped_memory_disabled")
        session_id = str(approval.get("sessionId") or "")
        try:
            session = self.sessions.get(session_id)
            return self.memory_evidence.record_tool_receipt(
                approval,
                role_id=str(session.get("roleId") or ""),
            )
        except Exception as exc:
            return _failure("tool_receipt", exc)

    def record_room(
        self,
        *,
        room_id: str,
        room_event: Mapping[str, object],
        text: str,
        role_id: str,
        session_id: str,
        event_type: str,
        accepted: bool,
    ) -> dict[str, object]:
        if not self._memory_enabled():
            return _skipped("skipped_memory_disabled")
        try:
            return self.memory_evidence.record_room_event(
                room_id=room_id,
                event_id=str(
                    room_event.get("eventId") or ""
                ),
                text=text,
                role_id=role_id,
                session_id=session_id,
                event_type=event_type,
                accepted=accepted,
                occurred_at_ms=int(
                    room_event.get("createdAtMs") or 0
                ),
            )
        except Exception as exc:
            return _failure("room_event", exc)

    def _memory_enabled(self) -> bool:
        try:
            return bool(self._memory_enabled_provider())
        except Exception:
            return False


def _skipped(status: str) -> dict[str, object]:
    return {
        "schemaVersion": (
            "rag-ime.agent-memory-evidence-write.v1"
        ),
        "ok": True,
        "stored": False,
        "status": status,
    }


def _failure(
    source_kind: str,
    error: BaseException,
) -> dict[str, object]:
    text = " ".join(str(error).split())[:240]
    return {
        "schemaVersion": (
            "rag-ime.agent-memory-evidence-write.v1"
        ),
        "ok": False,
        "stored": False,
        "status": "evidence_write_failed",
        "sourceKind": source_kind,
        "error": text or error.__class__.__name__,
    }
