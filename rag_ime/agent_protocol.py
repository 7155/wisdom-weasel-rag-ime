from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts.json_schema import validate_contract


AGENT_EVENT_TYPES = frozenset(
    {
        "snapshot",
        "text_delta",
        "reasoning_summary",
        "status_changed",
        "session_configuration_changed",
        "session_command_invoked",
        "message_queue_updated",
        "workflow_changed",
        "lifecycle_cancellation_changed",
        "tool_started",
        "tool_progress",
        "tool_finished",
        "approval_required",
        "approval_resolved",
        "background_job_started",
        "background_job_progress",
        "background_job_completed",
        "background_job_failed",
        "background_job_cancelled",
        "memory_checkpointed",
        "memory_maintenance_updated",
        "user_input_required",
        "message_completed",
        "provider_request_completed",
        "provider_request_failed",
        "compaction_started",
        "compaction_completed",
        "turn_completed",
        "turn_failed",
        "snapshot_required",
        "heartbeat",
    }
)

AGENT_BLOCK_TYPES = frozenset(
    {
        "text",
        "code",
        "reasoning_summary",
        "progress",
        "tool_call",
        "tool_result",
        "citation",
        "image",
        "audio",
        "file",
        "sticker",
        "task_plan",
        "diff",
        "approval",
        "error",
        "card",
        "checklist",
        "table",
        "artifact",
        "reference",
        "status",
        "unknown",
    }
)

TRUSTED_PRESENTATIONS: dict[str, frozenset[str]] = {
    "text": frozenset({"markdown", "plain_text"}),
    "code": frozenset({"code"}),
    "reasoning_summary": frozenset({"reasoning_summary"}),
    "progress": frozenset({"progress"}),
    "tool_call": frozenset({"tool_call"}),
    "tool_result": frozenset({"tool_result", "status", "table", "citation", "diff", "terminal", "media"}),
    "citation": frozenset({"citation"}),
    "image": frozenset({"image"}),
    "audio": frozenset({"audio"}),
    "file": frozenset({"file"}),
    "sticker": frozenset({"sticker"}),
    "task_plan": frozenset({"task_plan"}),
    "diff": frozenset({"diff"}),
    "approval": frozenset({"approval"}),
    "error": frozenset({"error"}),
    "card": frozenset({"card.v1"}),
    "checklist": frozenset({"checklist.v1"}),
    "table": frozenset({"table.v1"}),
    "artifact": frozenset({"artifact.v1"}),
    "reference": frozenset({"reference.v1"}),
    "status": frozenset({"status.v1"}),
    "unknown": frozenset({"unsupported"}),
}

DEFAULT_PRESENTATION: dict[str, str] = {
    block_type: next(iter(presentations))
    for block_type, presentations in TRUSTED_PRESENTATIONS.items()
}
DEFAULT_PRESENTATION.update(
    {
        "text": "markdown",
        "tool_result": "tool_result",
        "unknown": "unsupported",
    }
)

_MANAGED_MEDIA_ID = re.compile(r"^media_[A-Za-z0-9_-]{12,80}$")


@dataclass(frozen=True)
class AgentEventEnvelope:
    event_id: str
    session_id: str
    turn_id: str
    sequence: int
    created_at_ms: int
    event_type: str
    payload: dict[str, object]
    resume_token: str
    schema_version: str = "rag-ime.agent-event.v1"

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> AgentEventEnvelope:
        value = dict(payload)
        validate_contract(value, "agent-event.v1.json")
        return cls(
            event_id=str(value["eventId"]),
            session_id=str(value["sessionId"]),
            turn_id=str(value["turnId"]),
            sequence=int(value["sequence"]),
            created_at_ms=int(value["createdAtMs"]),
            event_type=str(value["eventType"]),
            payload=dict(_mapping(value.get("payload"))),
            resume_token=str(value["resumeToken"]),
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "sequence": self.sequence,
            "createdAtMs": self.created_at_ms,
            "eventType": self.event_type,
            "payload": dict(self.payload),
            "resumeToken": self.resume_token,
        }
        validate_contract(payload, "agent-event.v1.json")
        return payload

    def sse(self) -> bytes:
        body = json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":"))
        return (
            f"id: {self.event_id}\n"
            f"event: {self.event_type}\n"
            f"data: {body}\n\n"
        ).encode("utf-8")


@dataclass(frozen=True)
class AgentBlock:
    block_id: str
    block_type: str
    status: str
    presentation_kind: str
    data: dict[str, object] = field(default_factory=dict)
    schema_version: str = ""
    summary: str = ""
    source: dict[str, object] = field(default_factory=dict)
    visibility: str = ""
    digest: str = ""
    ref: str = ""
    generation: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> AgentBlock:
        block_type = str(payload.get("type") or "unknown")
        presentation = str(payload.get("presentationKind") or "")
        if block_type not in AGENT_BLOCK_TYPES:
            raise ValueError(f"unsupported agent block type: {block_type}")
        if presentation not in TRUSTED_PRESENTATIONS[block_type]:
            raise ValueError(f"untrusted presentation {presentation!r} for block type {block_type!r}")
        data = dict(_mapping(payload.get("data")))
        if block_type == "approval" and not _trusted_action_payload(data):
            raise ValueError("approval block requires a server-issued approvalId and payloadSha256")
        if block_type in {"image", "audio", "file"} and not _trusted_media_payload(data):
            raise ValueError(f"{block_type} block requires a managed mediaId")
        return cls(
            block_id=str(payload.get("id") or ""),
            block_type=block_type,
            status=str(payload.get("status") or "completed"),
            presentation_kind=presentation,
            data=data,
            schema_version=str(payload.get("schemaVersion") or ""),
            summary=str(payload.get("summary") or ""),
            source=dict(_mapping(payload.get("source"))),
            visibility=str(payload.get("visibility") or ""),
            digest=str(payload.get("digest") or ""),
            ref=str(payload.get("ref") or ""),
            generation=max(0, int(payload.get("generation") or 0)),
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.block_id,
            "type": self.block_type,
            "status": self.status,
            "presentationKind": self.presentation_kind,
            "data": dict(self.data),
        }
        if self.schema_version:
            payload.update(
                {
                    "schemaVersion": self.schema_version,
                    "summary": self.summary,
                    "source": dict(self.source),
                    "visibility": self.visibility,
                    "digest": self.digest,
                    "ref": self.ref,
                    "generation": self.generation,
                }
            )
        return payload


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    session_id: str
    turn_id: str
    role: str
    status: str
    blocks: tuple[AgentBlock, ...]
    created_at_ms: int
    attachments: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    completed_at_ms: int | None = None
    client_message_id: str = ""
    provider: str = ""
    model: str = ""
    usage: dict[str, int] | None = None
    schema_version: str = "rag-ime.agent-message.v1"

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> AgentMessage:
        value = dict(payload)
        validate_contract(value, "agent-message.v1.json")
        raw_blocks = value.get("blocks") if isinstance(value.get("blocks"), list) else []
        return cls(
            message_id=str(value["id"]),
            session_id=str(value["sessionId"]),
            turn_id=str(value["turnId"]),
            role=str(value["role"]),
            status=str(value["status"]),
            blocks=tuple(AgentBlock.from_payload(_mapping(item)) for item in raw_blocks),
            attachments=tuple(str(item) for item in value.get("attachments") or []),
            citations=tuple(str(item) for item in value.get("citations") or []),
            created_at_ms=int(value["createdAtMs"]),
            completed_at_ms=int(value["completedAtMs"]) if value.get("completedAtMs") is not None else None,
            client_message_id=str(value.get("clientMessageId") or ""),
            provider=str(value.get("provider") or ""),
            model=str(value.get("model") or ""),
            usage={str(key): int(item) for key, item in _mapping(value.get("usage")).items()}
            if isinstance(value.get("usage"), Mapping)
            else None,
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "id": self.message_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "role": self.role,
            "status": self.status,
            "blocks": [block.to_payload() for block in self.blocks],
            "attachments": list(self.attachments),
            "citations": list(self.citations),
            "createdAtMs": self.created_at_ms,
            "completedAtMs": self.completed_at_ms,
        }
        if self.client_message_id:
            payload["clientMessageId"] = self.client_message_id
        if self.provider:
            payload["provider"] = self.provider
        if self.model:
            payload["model"] = self.model
        if self.usage is not None:
            payload["usage"] = dict(self.usage)
        validate_contract(payload, "agent-message.v1.json")
        return payload


def normalize_agent_block(
    payload: Mapping[str, object],
    *,
    trusted_action: bool = False,
    trusted_presentation: str | None = None,
) -> AgentBlock:
    """Convert provider/tool output into a renderer-safe block.

    Only the Sidecar may opt into approval blocks or override a presentation.
    Unknown model output becomes inert text metadata instead of executable UI.
    """

    raw_type = str(payload.get("type") or "unknown")
    block_type = raw_type if raw_type in AGENT_BLOCK_TYPES else "unknown"
    if block_type == "approval" and not trusted_action:
        block_type = "unknown"
    requested = trusted_presentation or str(payload.get("presentationKind") or "")
    allowed = TRUSTED_PRESENTATIONS[block_type]
    presentation = requested if requested in allowed else DEFAULT_PRESENTATION[block_type]
    data = dict(_mapping(payload.get("data")))
    if block_type == "unknown":
        data = {
            "title": "暂不支持此内容",
            "originalType": raw_type[:80],
            "summary": _safe_summary(data),
        }
    normalized = AgentBlock(
        block_id=str(payload.get("id") or "block:unknown"),
        block_type=block_type,
        status=str(payload.get("status") or "completed"),
        presentation_kind=presentation,
        data=data,
        schema_version=str(payload.get("schemaVersion") or ""),
        summary=str(payload.get("summary") or ""),
        source=dict(_mapping(payload.get("source"))),
        visibility=str(payload.get("visibility") or ""),
        digest=str(payload.get("digest") or ""),
        ref=str(payload.get("ref") or ""),
        generation=max(0, int(payload.get("generation") or 0)),
    )
    return AgentBlock.from_payload(normalized.to_payload())


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _safe_summary(data: Mapping[str, object]) -> str:
    text = str(data.get("text") or data.get("summary") or "")
    return " ".join(text.split())[:240]


def _trusted_action_payload(data: Mapping[str, object]) -> bool:
    approval_id = str(data.get("approvalId") or "")
    payload_hash = str(data.get("payloadSha256") or "")
    return bool(approval_id and len(payload_hash) == 64)


def _trusted_media_payload(data: Mapping[str, object]) -> bool:
    media_id = str(data.get("mediaId") or "")
    return _MANAGED_MEDIA_ID.fullmatch(media_id) is not None
