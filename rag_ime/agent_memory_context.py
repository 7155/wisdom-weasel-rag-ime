from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from threading import RLock
from typing import Any

from .agent_context_runtime import render_context_items
from .agent_memory_context_support import (
    last_user_recall_text,
    recall_message_text,
    recall_messages,
    room_recall_fence,
    task_aware_recall_query,
)
from .agent_prompt_support import bounded_text
from .agent_room_kernel import RoomKernelFenceError
from .session_recall_policy import session_recall_policy


class AgentMemoryContextService:
    """Own query-aware Session memory bootstrap and compaction recovery."""

    def __init__(
        self,
        *,
        sessions: Any,
        personas: Any,
        role_books: Any,
        memory_bootstrap: Any,
        context_runtime: Any,
        task_context: Any,
        room_capabilities: Any,
        room_prompt_plans: Any,
        room_skill_receipts: Any,
        room_skill_policy: Any,
        runtime_provider: Callable[[], Any],
    ) -> None:
        self.sessions = sessions
        self.personas = personas
        self.role_books = role_books
        self.memory_bootstrap = memory_bootstrap
        self.context_runtime = context_runtime
        self.task_context = task_context
        self.room_capabilities = room_capabilities
        self.room_prompt_plans = room_prompt_plans
        self.room_skill_receipts = room_skill_receipts
        self.room_skill_policy = room_skill_policy
        self._runtime_provider = runtime_provider
        self._state_lock = RLock()
        self._last_query: dict[str, str] = {}
        self._recent_messages: dict[
            str,
            list[dict[str, object]],
        ] = {}

    @property
    def runtime(self) -> Any:
        return self._runtime_provider()

    def ensure_role_book(
        self,
        session_id: str,
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        if str(
            session.get("roleBookRevisionId") or ""
        ).strip():
            return session
        role = self.personas.resolve(
            session.get("roleId") or "companion-present-v1",
            session.get("roleVersion") or "1",
        )
        try:
            self.role_books.pin_session(
                session_id,
                role.role_id,
                role.version,
                role.display_name,
                role.summary,
                role.version,
            )
        except Exception:
            return session
        return self.sessions.get(session_id)

    @staticmethod
    def pending_bootstrap(
        session: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "schemaVersion": (
                "rag-ime.memory-bootstrap-enqueue-result.v1"
            ),
            "ok": True,
            "sessionId": str(session.get("id") or ""),
            "status": "awaiting_first_prompt",
            "queryAware": True,
            "priority": "developer",
            "lifecycle": "session",
        }

    def ensure_bootstrap(
        self,
        session: Mapping[str, object],
        *,
        query_text: str,
    ) -> dict[str, object]:
        session_id = str(session.get("id") or "")
        role_id = str(session.get("roleId") or "")
        dedupe_key = self.memory_bootstrap.dedupe_key(
            session_id
        )
        try:
            expired_legacy = (
                self.context_runtime
                .expire_legacy_memory_bootstrap(
                    session_id,
                    current_dedupe_key=dedupe_key,
                )
            )
            existing = self.context_runtime.active_item(
                session_id,
                source_kind="memory_bootstrap",
            )
            if existing is not None:
                return _ready_existing(
                    session_id,
                    existing,
                    expired_legacy=expired_legacy,
                )
            recent = self.recent_messages(session_id)
            task = self.task_context.resolve(session_id)
            objective = bounded_text(
                task.get("objective"),
                maximum=4_000,
            )
            specification = self.memory_bootstrap.build(
                session_id,
                role_id=role_id,
                query_text=task_aware_recall_query(
                    query_text,
                    objective,
                ),
                room_ids=self.task_context.room_ids(
                    session_id
                ),
                trigger=self.task_context.trigger(session_id),
                retrieval_context_text=bounded_text(
                    f"{recall_message_text(recent)}\n"
                    f"{objective}",
                    maximum=6_000,
                ),
                vector_context_text="",
                vector_context_weight=(
                    session_recall_policy()
                    .start_summary_weight
                ),
                recent_messages=recent,
                planning_context=self.sessions.agent_plan(
                    session_id
                ),
                task_context=task,
            )
            item = self.context_runtime.enqueue(
                **specification
            )
        except Exception as exc:
            return _bootstrap_failure(session_id, exc)
        payload = specification.get("payload")
        source_count = (
            len(payload.get("items") or [])
            if isinstance(payload, Mapping)
            else 0
        )
        return {
            "schemaVersion": (
                "rag-ime.memory-bootstrap-enqueue-result.v1"
            ),
            "ok": True,
            "sessionId": session_id,
            "status": "ready",
            "itemId": str(item.get("itemId") or ""),
            "dedupeKey": dedupe_key,
            "sourceCount": source_count,
            "queryAware": True,
            "priority": "developer",
            "lifecycle": "session",
            "expiredLegacyItems": expired_legacy,
        }

    def refresh(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        session = self.ensure_role_book(session_id)
        trigger_value = str(
            payload.get("trigger") or "session_start"
        ).strip().lower()
        is_compaction = trigger_value == "compaction"
        recent = recall_messages(payload.get("recentMessages"))
        if recent:
            self.replace_recent_messages(session_id, recent)
        else:
            recent = self.recent_messages(session_id)
        summary = bounded_text(
            payload.get("summary"),
            maximum=8_000,
        )
        query = self._refresh_query(
            session_id,
            payload=payload,
            recent=recent,
            is_compaction=is_compaction,
        )
        task = self.task_context.resolve(session_id)
        objective = bounded_text(
            task.get("objective"),
            maximum=4_000,
        )
        query = (
            task_aware_recall_query(query, objective)
            or "继续当前 Session 的任务"
        )
        trigger = (
            "compaction"
            if is_compaction
            else self.task_context.trigger(session_id)
        )
        before = self.room_capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        specification = self.memory_bootstrap.build(
            session_id,
            role_id=str(session.get("roleId") or ""),
            query_text=query,
            room_ids=self.task_context.room_ids(session_id),
            trigger=trigger,
            retrieval_context_text=bounded_text(
                f"{recall_message_text(recent)}\n"
                f"{str(task.get('objective') or '')}",
                maximum=6_000,
            ),
            vector_context_text=(
                summary if is_compaction else ""
            ),
            vector_context_weight=(
                session_recall_policy()
                .compaction_summary_weight
                if is_compaction and summary
                else 0.0
            ),
            recent_messages=recent,
            planning_context=self.sessions.agent_plan(
                session_id
            ),
            task_context=task,
        )
        after = self.room_capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        self._validate_room_fence(before, after)
        item = self.context_runtime.replace_active(
            **specification
        )
        rendered = _render_specification(specification)
        rendered, room_recovery = self._room_recovery(
            session_id,
            payload=payload,
            rendered=rendered,
        )
        recall_payload = (
            specification.get("payload")
            if isinstance(
                specification.get("payload"),
                Mapping,
            )
            else {}
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-session-context-refresh.v1"
            ),
            "ok": True,
            "result": {
                "sessionId": session_id,
                "trigger": trigger,
                "sessionContext": rendered,
                "itemId": str(item.get("itemId") or ""),
                "recallId": str(
                    recall_payload.get("recallId") or ""
                ),
                "sourceCount": len(
                    recall_payload.get("items") or []
                ),
                "recentConversationCount": len(recent),
                "roomContextRecovery": room_recovery,
            },
        }

    def remember_query(
        self,
        session_id: str,
        query_text: str,
    ) -> None:
        query = bounded_text(query_text, maximum=8_000)
        if not query:
            return
        with self._state_lock:
            self._last_query[session_id] = query

    def recall_query(
        self,
        session_id: str,
        *,
        fallback: str = "",
    ) -> str:
        with self._state_lock:
            cached = self._last_query.get(session_id, "")
        return cached or bounded_text(
            fallback,
            maximum=8_000,
        )

    def replace_recent_messages(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, object]],
    ) -> None:
        normalized = recall_messages(messages)
        with self._state_lock:
            self._recent_messages[session_id] = normalized

    def append_recent_message(
        self,
        session_id: str,
        message: Mapping[str, object],
    ) -> None:
        normalized = recall_messages([message])
        if not normalized:
            return
        with self._state_lock:
            current = list(
                self._recent_messages.get(session_id, [])
            )
            current.extend(normalized)
            self._recent_messages[session_id] = current[-8:]

    def recent_messages(
        self,
        session_id: str,
    ) -> list[dict[str, object]]:
        with self._state_lock:
            cached = list(
                self._recent_messages.get(session_id, [])
            )
        if cached:
            return cached
        snapshot_provider = getattr(
            self.runtime,
            "session_snapshot",
            None,
        )
        if not callable(snapshot_provider):
            return []
        try:
            snapshot = snapshot_provider(session_id)
        except Exception:
            return []
        messages = recall_messages(
            snapshot.get("messages")
            if isinstance(snapshot, Mapping)
            else None
        )
        if messages:
            self.replace_recent_messages(
                session_id,
                messages,
            )
        return messages

    def clear_recall_state(
        self,
        session_ids: Sequence[str],
    ) -> None:
        """Invalidate only the process-local cache owned by this service."""

        with self._state_lock:
            for session_id in session_ids:
                self._last_query.pop(session_id, None)
                self._recent_messages.pop(session_id, None)

    def _refresh_query(
        self,
        session_id: str,
        *,
        payload: Mapping[str, object],
        recent: Sequence[Mapping[str, object]],
        is_compaction: bool,
    ) -> str:
        latest_user = last_user_recall_text(recent)
        if is_compaction and latest_user:
            return latest_user
        query = self.recall_query(
            session_id,
            fallback=bounded_text(
                payload.get("queryText"),
                maximum=8_000,
            ),
        )
        return query or latest_user

    @staticmethod
    def _validate_room_fence(
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
    ) -> None:
        if room_recall_fence(before) != room_recall_fence(
            after
        ):
            raise RoomKernelFenceError(
                "Room generation/capability changed while "
                "Session context was rebuilding"
            )
        if (
            after is not None
            and str(after.get("state") or "") == "revoked"
        ):
            raise RoomKernelFenceError(
                "Room Session context refresh was cancelled "
                "before projection"
            )

    def _room_recovery(
        self,
        session_id: str,
        *,
        payload: Mapping[str, object],
        rendered: str,
    ) -> tuple[str, dict[str, object] | None]:
        binding = self.room_capabilities.runtime_binding(
            session_id
        )
        if binding is None:
            return rendered, None
        prompt = self.room_prompt_plans.provider_payload(
            str(binding["promptCompileReceiptId"])
        )
        parts = [rendered, str(prompt["providerContext"])]
        pinned = self.room_skill_receipts.active_for_session(
            session_id
        )
        if pinned is None:
            return "\n\n".join(
                part for part in parts if part.strip()
            ), None
        requested = payload.get("roomSkillRecovery")
        revision = (
            str(requested.get("catalogRevision") or "")
            if isinstance(requested, Mapping)
            else str(pinned["catalogRevision"])
        )
        recovery = (
            self.room_skill_receipts
            .restore_for_compaction(
                str(pinned["receiptId"]),
                expected_capability_epoch=int(
                    binding["capabilityEpoch"]
                ),
                catalog_revision=revision,
            )
        )
        skill_id = str(recovery["skillId"])
        parts.append(
            f'<loaded_skill name="{skill_id}" '
            f'revision="sha256:{recovery["skillHash"]}">\n'
            f"{self.room_skill_policy.skill_body(skill_id)}\n"
            "</loaded_skill>"
        )
        return "\n\n".join(
            part for part in parts if part.strip()
        ), recovery


def _ready_existing(
    session_id: str,
    existing: Mapping[str, object],
    *,
    expired_legacy: int,
) -> dict[str, object]:
    return {
        "schemaVersion": (
            "rag-ime.memory-bootstrap-enqueue-result.v1"
        ),
        "ok": True,
        "sessionId": session_id,
        "status": "ready",
        "itemId": str(existing.get("itemId") or ""),
        "dedupeKey": "active-memory-context",
        "queryAware": True,
        "priority": "developer",
        "lifecycle": "session",
        "expiredLegacyItems": expired_legacy,
    }


def _bootstrap_failure(
    session_id: str,
    error: BaseException,
) -> dict[str, object]:
    return {
        "schemaVersion": (
            "rag-ime.memory-bootstrap-enqueue-result.v1"
        ),
        "ok": False,
        "sessionId": session_id,
        "status": "recall_failed",
        "queryAware": True,
        "priority": "developer",
        "lifecycle": "session",
        "error": (
            " ".join(str(error).split())[:240]
            or error.__class__.__name__
        ),
    }


def _render_specification(
    specification: Mapping[str, object],
) -> str:
    return render_context_items(
        [
            {
                "sourceKind": specification["source_kind"],
                "title": specification["title"],
                "summary": specification["summary"],
                "payload": specification["payload"],
            }
        ]
    )


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value
