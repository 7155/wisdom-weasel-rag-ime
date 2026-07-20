from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .agent_prompt_support import (
    bounded_text,
    deep_search_prompt,
    optional_client_message_id,
    prompt_delivery,
    prompt_user_message_payload,
)


class AgentPromptApplicationService:
    """Own prompt idempotency, attachments, and memory checkpoints."""

    def __init__(
        self,
        *,
        sessions: Any,
        command_receipts: Any,
        configuration_store: Any,
        media: Any,
        events: Any,
        memory_sources: Any,
        memory_context: Any,
        memory_evidence: Any,
        prompt_delivery_service: Any,
        runtime_provider: Callable[[], Any],
        runtime_status: Callable[[], Mapping[str, object]],
        create_session: Callable[
            [Mapping[str, object]],
            Mapping[str, object],
        ],
        dispatch_checkpoint: Callable[..., Mapping[str, object]],
        context_source_token: object,
        transient_context_char_budget: int,
    ) -> None:
        self.sessions = sessions
        self.command_receipts = command_receipts
        self.configuration_store = configuration_store
        self.media = media
        self.events = events
        self.memory_sources = memory_sources
        self.memory_context = memory_context
        self.memory_evidence = memory_evidence
        self.prompt_delivery_service = prompt_delivery_service
        self._runtime_provider = runtime_provider
        self.runtime_status = runtime_status
        self.create_session = create_session
        self.dispatch_checkpoint = dispatch_checkpoint
        self.context_source_token = context_source_token
        self.transient_context_char_budget = (
            transient_context_char_budget
        )

    @property
    def runtime(self) -> Any:
        return self._runtime_provider()

    def prompt(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = self._prompt_request(payload)
        client_message_id = str(
            request["clientMessageId"]
        )
        if not client_message_id:
            self.sessions.require_goal_execution(session_id)
            return dict(self.dispatch_checkpoint(
                session_id=session_id,
                **_checkpoint_arguments(request),
            ))
        receipt_payload = {
            "message": request["message"],
            "attachments": request["attachmentIds"],
            "contextSource": request["contextSource"],
            "delivery": request["delivery"],
        }
        claim = self.command_receipts.begin(
            command_scope="session_prompt",
            scope_id=session_id,
            client_message_id=client_message_id,
            payload=receipt_payload,
        )
        if claim.replay_response is not None:
            return {
                **claim.replay_response,
                "idempotentReplay": True,
            }
        try:
            self.sessions.require_goal_execution(session_id)
            response = dict(self.dispatch_checkpoint(
                session_id=session_id,
                **_checkpoint_arguments(request),
            ))
        except Exception as exc:
            self.command_receipts.fail(
                claim,
                command_scope="session_prompt",
                scope_id=session_id,
                client_message_id=client_message_id,
                error=exc,
            )
            raise
        return self.command_receipts.complete(
            claim,
            command_scope="session_prompt",
            scope_id=session_id,
            client_message_id=client_message_id,
            response=response,
        )

    def deep_search(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        if (
            str(
                payload.get("privacyDisposition") or ""
            ).strip()
            != "allowed"
        ):
            raise ValueError(
                "deep search requires an allowed foreground privacy disposition"
            )
        question = bounded_text(
            payload.get("query"),
            maximum=4_000,
        )
        if not question:
            raise ValueError("query must not be empty")
        runtime = self.runtime_status()
        self._validate_deep_search_runtime(runtime)
        session, created = self.deep_search_session(runtime)
        prompt_message, evidence_count = deep_search_prompt(
            payload,
            question=question,
        )
        accepted = dict(self.dispatch_checkpoint(
            session_id=str(session["id"]),
            message=prompt_message,
            checkpoint_text=question,
            attachment_ids=[],
            context_source="deep_search",
        ))
        return {
            "schemaVersion": "rag-ime.agent-deep-search.v1",
            "ok": True,
            "accepted": True,
            "sessionId": session["id"],
            "sessionCreated": created,
            "session": self.sessions.get(
                str(session["id"])
            ),
            "questionChars": len(question),
            "evidenceCount": evidence_count,
            "controlDestination": "assistant",
            "turnId": accepted.get("turnId", ""),
        }

    def deep_search_session(
        self,
        runtime: Mapping[str, object],
    ) -> tuple[dict[str, object], bool]:
        active_session_id = str(
            runtime.get("activeSessionId") or ""
        ).strip()
        if active_session_id:
            active = self.sessions.get(active_session_id)
            if (
                active.get("mode") == "assistant"
                and active.get("status") != "archived"
            ):
                return active, False
        daily_title = (
            "输入助手 "
            f"{datetime.now().astimezone().date().isoformat()}"
        )
        for session in self.sessions.list(
            include_archived=False,
            limit=100,
        ):
            if (
                session.get("mode") == "assistant"
                and session.get("title") == daily_title
            ):
                return session, False
        defaults = self.configuration_store.snapshot()[
            "configuration"
        ]["sessionDefaults"]
        created = self.create_session(
            {
                "title": daily_title,
                "mode": "assistant",
                "roleId": str(defaults["roleId"]),
                "roleVersion": str(defaults["roleVersion"]),
                "modelProfile": str(defaults["modelProfile"]),
                "toolProfileVersion": str(
                    defaults["toolProfileVersion"]
                ),
                "_internalModelOverride": True,
            }
        )
        return dict(created["session"]), True

    def prompt_with_checkpoint(
        self,
        *,
        session_id: str,
        message: str,
        checkpoint_text: str,
        attachment_ids: list[str],
        client_message_id: str = "",
        context_source: str = "user",
        delivery: str = "prompt",
        transient_context: str = "",
    ) -> dict[str, object]:
        session = self.memory_context.ensure_role_book(
            session_id
        )
        self.memory_context.remember_query(
            session_id,
            checkpoint_text,
        )
        bootstrap = self.memory_context.ensure_bootstrap(
            session,
            query_text=checkpoint_text,
        )
        self._validate_images(session_id, attachment_ids)
        images = self.media.pi_images(
            session_id,
            attachment_ids,
        )
        accepted, trace_id, delivered = (
            self.prompt_delivery_service.deliver(
                session_id,
                message,
                images=images,
                client_message_id=client_message_id,
                source_kind=context_source,
                delivery=delivery,
                transient_context=transient_context,
            )
        )
        self.media.bind_to_pi_entry(
            session_id=session_id,
            pi_entry_id=str(
                accepted.get("piEntryId") or ""
            ),
            turn_id=str(accepted.get("turnId") or ""),
            media_ids=attachment_ids,
        )
        attachments = [
            self.media.receipt(
                media_id,
                session_id=session_id,
            )
            for media_id in dict.fromkeys(attachment_ids)
        ]
        turn_id = str(accepted.get("turnId") or "")
        self._publish_user_message(
            session_id=session_id,
            turn_id=turn_id,
            message=message,
            client_message_id=client_message_id,
            attachments=attachments,
            delivery=delivery,
            accepted=accepted,
        )
        checkpoint = self._checkpoint_user_message(
            session_id=session_id,
            checkpoint_text=checkpoint_text,
            accepted=accepted,
        )
        evidence = (
            _room_evidence_placeholder()
            if context_source == "room"
            else self.memory_evidence.record_user(
                session_id=session_id,
                pi_entry_id=str(
                    accepted.get("piEntryId")
                    or accepted.get("turnId")
                    or ""
                ),
                turn_id=turn_id,
                text=checkpoint_text,
            )
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-prompt-accepted.v1"
            ),
            "ok": True,
            "sessionId": session_id,
            "memoryCheckpoint": checkpoint,
            "memoryEvidence": evidence,
            "memoryBootstrap": bootstrap,
            "attachments": attachments,
            "contextTraceId": trace_id,
            "contextItemsDelivered": delivered,
            **accepted,
        }

    def _prompt_request(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        message = _required_text(payload, "message")
        raw_attachments = payload.get("attachments")
        if raw_attachments is None:
            attachment_ids: list[str] = []
        elif isinstance(raw_attachments, list):
            attachment_ids = [
                str(item) for item in raw_attachments
            ]
        else:
            raise ValueError(
                "attachments must be an array of managed mediaId values"
            )
        trusted = (
            payload.get("_contextSourceToken")
            is self.context_source_token
        )
        return {
            "message": message,
            "clientMessageId": optional_client_message_id(
                payload.get("clientMessageId")
            ),
            "delivery": prompt_delivery(
                payload.get("delivery")
            ),
            "attachmentIds": attachment_ids,
            "contextSource": (
                str(payload.get("_contextSource") or "user")
                if trusted
                else "user"
            ),
            "checkpointText": (
                str(payload.get("_checkpointText") or message)
                if trusted
                else message
            ),
            "transientContext": (
                bounded_text(
                    payload.get("_transientContext"),
                    maximum=(
                        self.transient_context_char_budget
                    ),
                )
                if trusted
                else ""
            ),
        }

    @staticmethod
    def _validate_deep_search_runtime(
        runtime: Mapping[str, object],
    ) -> None:
        capabilities = (
            runtime.get("capabilities")
            if isinstance(
                runtime.get("capabilities"),
                Mapping,
            )
            else {}
        )
        if runtime.get("enabled") is not True:
            raise ValueError("Pi runtime is disabled")
        if capabilities.get("rpc") is not True:
            raise ValueError(
                "managed Pi runtime is not installed"
            )
        if capabilities.get("modelConfigured") is False:
            raise ValueError("Pi model is not configured")
        if runtime.get("status") == "busy":
            raise ValueError(
                "Pi is already processing another task"
            )

    def _validate_images(
        self,
        session_id: str,
        attachment_ids: list[str],
    ) -> None:
        if not attachment_ids:
            return
        selected = self.runtime.model_catalog(
            session_id
        ).get("selected")
        if (
            not isinstance(selected, Mapping)
            or selected.get("supportsImages") is not True
        ):
            raise ValueError(
                "当前模型不支持图片，请切换到支持图片的模型后重试"
            )

    def _publish_user_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: str,
        client_message_id: str,
        attachments: list[dict[str, object]],
        delivery: str,
        accepted: Mapping[str, object],
    ) -> None:
        user_message = prompt_user_message_payload(
            session_id=session_id,
            turn_id=turn_id,
            message_id=(
                str(accepted.get("piEntryId") or "")
                or f"{turn_id}:user"
            ),
            text=message,
            client_message_id=client_message_id,
            attachments=attachments,
            delivery=delivery,
        )
        event_payload: dict[str, object] = {
            "message": user_message
        }
        if client_message_id:
            event_payload["clientMessageId"] = (
                client_message_id
            )
        self.events.publish(
            session_id,
            "message_completed",
            event_payload,
            turn_id=turn_id,
        )

    def _checkpoint_user_message(
        self,
        *,
        session_id: str,
        checkpoint_text: str,
        accepted: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            return self.memory_sources.checkpoint_user_message(
                session_id=session_id,
                pi_entry_id=str(
                    accepted.get("piEntryId")
                    or accepted.get("turnId")
                    or ""
                ),
                turn_id=str(
                    accepted.get("turnId") or ""
                ),
                text=checkpoint_text,
            )
        except Exception as exc:
            return {
                "schemaVersion": (
                    "rag-ime.agent-memory-checkpoint.v1"
                ),
                "ok": False,
                "stored": False,
                "status": "checkpoint_failed",
                "error": _public_error(exc),
            }


def _checkpoint_arguments(
    request: Mapping[str, object],
) -> dict[str, object]:
    return {
        "message": str(request["message"]),
        "checkpoint_text": str(
            request["checkpointText"]
        ),
        "attachment_ids": list(
            request["attachmentIds"]
        ),
        "client_message_id": str(
            request["clientMessageId"]
        ),
        "context_source": str(request["contextSource"]),
        "delivery": str(request["delivery"]),
        "transient_context": str(
            request["transientContext"]
        ),
    }


def _room_evidence_placeholder() -> dict[str, object]:
    return {
        "schemaVersion": (
            "rag-ime.agent-memory-evidence-write.v1"
        ),
        "ok": True,
        "stored": False,
        "status": "recorded_as_room_event",
    }


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _public_error(error: BaseException) -> str:
    return (
        " ".join(str(error).split())[:240]
        or error.__class__.__name__
    )
