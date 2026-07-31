from __future__ import annotations

import hashlib
import json
import time
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
        room_skill_receipts: Any,
        room_context_epochs: Any,
        room_recovery_context_provider: Callable[
            [
                str,
                Mapping[str, object] | None,
                Mapping[str, object] | None,
            ],
            str,
        ],
        runtime_provider: Callable[[], Any],
    ) -> None:
        self.sessions = sessions
        self.personas = personas
        self.role_books = role_books
        self.memory_bootstrap = memory_bootstrap
        self.context_runtime = context_runtime
        self.task_context = task_context
        self.room_capabilities = room_capabilities
        self.room_skill_receipts = room_skill_receipts
        self.room_context_epochs = room_context_epochs
        self.room_recovery_context_provider = (
            room_recovery_context_provider
        )
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
                    dedupe_key=self.context_runtime.active_dedupe_key(
                        session_id,
                        source_kind="memory_bootstrap",
                    ),
                    expired_legacy=expired_legacy,
                )
            recent = self.recent_messages(session_id)
            task = self.task_context.resolve(session_id)
            objective = bounded_text(
                task.get("objective"),
                maximum=4_000,
            )
            room_ids = self.task_context.room_ids(session_id)
            managed_room = bool(room_ids)
            projected_recent = [] if managed_room else recent
            retrieval_recent = (
                last_user_recall_text(recent)
                if managed_room
                else recall_message_text(recent)
            )
            specification = self.memory_bootstrap.build(
                session_id,
                role_id=role_id,
                query_text=task_aware_recall_query(
                    query_text,
                    objective,
                ),
                room_ids=room_ids,
                trigger=self.task_context.trigger(session_id),
                retrieval_context_text=bounded_text(
                    f"{retrieval_recent}\n"
                    f"{objective}",
                    maximum=6_000,
                ),
                vector_context_text="",
                vector_context_weight=(
                    session_recall_policy()
                    .start_summary_weight
                ),
                recent_messages=projected_recent,
                planning_context=self.sessions.agent_plan(
                    session_id
                ),
                task_context=_memory_task_projection(task),
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

    def refresh_for_turn(
        self,
        session: Mapping[str, object],
        *,
        query_text: str,
    ) -> dict[str, object]:
        """Refresh the generic memory projection for one new user task.

        Room and ordinary Agent Sessions share this lifecycle. Room-specific
        responsibility context is composed elsewhere and never becomes a
        prerequisite for personal-memory recall.
        """

        session_id = str(session.get("id") or "")
        self.remember_query(session_id, query_text)
        expired_legacy = 0
        try:
            expired_legacy = (
                self.context_runtime
                .expire_legacy_memory_bootstrap(
                    session_id,
                    current_dedupe_key=(
                        self.memory_bootstrap.dedupe_key(
                            session_id
                        )
                    ),
                )
            )
            refreshed = self.refresh(
                {
                    "sessionId": session_id,
                    "trigger": "turn_start",
                    "queryText": query_text,
                }
            )
        except RoomKernelFenceError:
            raise
        except Exception as exc:
            existing = self.context_runtime.active_item(
                session_id,
                source_kind="memory_bootstrap",
            )
            if existing is not None:
                receipt = _ready_existing(
                    session_id,
                    existing,
                    dedupe_key=self.context_runtime.active_dedupe_key(
                        session_id,
                        source_kind="memory_bootstrap",
                    ),
                    expired_legacy=expired_legacy,
                )
                receipt["status"] = "ready_stale"
                receipt["refreshError"] = _error_text(exc)
                return receipt
            return _bootstrap_failure(session_id, exc)

        result = refreshed["result"]
        return {
            "schemaVersion": (
                "rag-ime.memory-bootstrap-enqueue-result.v1"
            ),
            "ok": True,
            "sessionId": session_id,
            "status": "ready",
            "itemId": str(result.get("itemId") or ""),
            "dedupeKey": str(result.get("dedupeKey") or ""),
            "sourceCount": int(result.get("sourceCount") or 0),
            "queryAware": True,
            "refreshedForCurrentTurn": True,
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
        recent = recall_messages(
            payload.get("recentMessages"),
            first_user_maximum=(
                4_000 if is_compaction else 1_200
            ),
        )
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
        task_trigger = self.task_context.trigger(session_id)
        if is_compaction:
            trigger = "compaction"
        elif task_trigger != "first_user_prompt":
            trigger = task_trigger
        elif (
            trigger_value == "turn_start"
            and self.context_runtime.active_item(
                session_id,
                source_kind="memory_bootstrap",
            )
            is not None
        ):
            # Ordinary Sessions bootstrap once, then replace their query-aware
            # memory pack on every later user turn.  Reusing
            # `first_user_prompt` would reuse the static v3 dedupe key and
            # silently retain the previous turn's recall.
            trigger = "turn_start"
        else:
            trigger = "first_user_prompt"
        before = self.room_capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        room_ids = self.task_context.room_ids(session_id)
        managed_room = before is not None or bool(room_ids)
        projected_recent = (
            []
            if managed_room or is_compaction
            else recent
        )
        retrieval_recent = (
            last_user_recall_text(recent)
            if managed_room
            else recall_message_text(recent)
        )
        compaction_recovery = (
            _ordinary_compaction_recovery(
                summary=summary,
                agent_skill_recovery=payload.get(
                    "agentSkillRecovery"
                ),
                agent_tool_recovery=payload.get(
                    "agentToolRecovery"
                ),
            )
            if is_compaction and not managed_room
            else None
        )
        specification = self.memory_bootstrap.build(
            session_id,
            role_id=str(session.get("roleId") or ""),
            query_text=query,
            room_ids=room_ids,
            trigger=trigger,
            retrieval_context_text=bounded_text(
                f"{retrieval_recent}\n"
                f"{str(task.get('objective') or '')}",
                maximum=6_000,
            ),
            vector_context_text=(
                summary
                if is_compaction and not managed_room
                else ""
            ),
            vector_context_weight=(
                session_recall_policy()
                .compaction_summary_weight
                if is_compaction and summary and not managed_room
                else 0.0
            ),
            recent_messages=projected_recent,
            planning_context=self.sessions.agent_plan(
                session_id
            ),
            task_context=_memory_task_projection(task),
            compaction_recovery=compaction_recovery,
        )
        after = self.room_capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        self._validate_room_fence(
            before,
            after,
        )
        rendered = _render_specification(specification)
        rendered, room_recovery, room_tool_recovery = self._room_recovery(
            session_id,
            payload=payload,
            rendered=rendered,
            allow_revoked=is_compaction,
        )
        room_recovery_context = self.room_recovery_context_provider(
            session_id,
            room_recovery,
            room_tool_recovery,
        )
        context_epoch_transition = None
        current_context_epoch = self.room_context_epochs.current(session_id)
        if is_compaction and current_context_epoch is not None:
            compaction_entry_id = _required_text(
                payload,
                "compactionEntryId",
            )
            expected_context_epoch = payload.get("expectedContextEpoch")
            if (
                isinstance(expected_context_epoch, bool)
                or not isinstance(expected_context_epoch, int)
                or expected_context_epoch < 1
            ):
                raise ValueError(
                    "expectedContextEpoch must be a positive integer"
                )
            context_epoch_transition = (
                self.room_context_epochs.advance_compaction(
                    session_id=session_id,
                    compaction_entry_id=compaction_entry_id,
                    expected_epoch=expected_context_epoch,
                    room_recovery_context=room_recovery_context,
                    session_context=rendered,
                    now_ms=int(time.time() * 1000),
                )
            )
            if room_recovery_context:
                self._persist_room_compaction_recovery(
                    session_id=session_id,
                    compaction_entry_id=compaction_entry_id,
                    room_recovery_context=room_recovery_context,
                    transition=context_epoch_transition,
                )
        # Keep the previous valid bootstrap active until every Room fence,
        # receipt, and epoch transition has been validated. A failed recovery
        # must not expire good context and leave a pending replacement behind.
        item = self.context_runtime.replace_active(
            **specification
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
                "dedupeKey": str(
                    specification.get("dedupe_key") or ""
                ),
                "recallId": str(
                    recall_payload.get("recallId") or ""
                ),
                "sourceCount": len(
                    recall_payload.get("items") or []
                ),
                "recentConversationCount": len(
                    projected_recent
                ),
                "compactionRecoveryPacket": bool(
                    compaction_recovery
                ),
                "roomContextRecovery": room_recovery,
                "roomToolRecovery": room_tool_recovery,
                "roomRecoveryContext": room_recovery_context,
                "contextEpochTransition": context_epoch_transition,
                "contextEpoch": (
                    context_epoch_transition["toEpoch"]
                    if context_epoch_transition is not None
                    else None
                ),
                "contextEpochReason": (
                    context_epoch_transition["epochReason"]
                    if context_epoch_transition is not None
                    else None
                ),
            },
        }

    def _persist_room_compaction_recovery(
        self,
        *,
        session_id: str,
        compaction_entry_id: str,
        room_recovery_context: str,
        transition: Mapping[str, object],
    ) -> None:
        try:
            recovery = json.loads(room_recovery_context)
        except json.JSONDecodeError as exc:
            raise RoomKernelFenceError(
                "Room compaction recovery is not canonical JSON"
            ) from exc
        if not isinstance(recovery, Mapping):
            raise RoomKernelFenceError(
                "Room compaction recovery must be an object"
            )
        transition_id = str(
            transition.get("transitionId") or ""
        ).strip()
        if not transition_id:
            raise RoomKernelFenceError(
                "Room compaction recovery has no context transition"
            )
        self.context_runtime.replace_active(
            session_id=session_id,
            source_kind="room_compaction_recovery",
            source_id=compaction_entry_id,
            lane="room",
            lifecycle="persistent",
            title="最近一次 Room 压缩恢复包",
            summary=(
                "只恢复同一 Session 已确认的任务与交付事实；"
                "不授予新权限，也不恢复私有推理。"
            ),
            payload={
                "schemaVersion": (
                    "wisdom-weasel.room-session-recovery-item.v1"
                ),
                "recovery": dict(recovery),
            },
            dedupe_key=(
                f"room-compaction-recovery:{transition_id}"
            ),
        )

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

    def provider_context(
        self,
        session_id: str,
        *,
        include_room_recovery: bool = False,
    ) -> str:
        """Render the latest valid generic RAG projection for one Agent.

        The same projection is used by ordinary prompts and Kernel-managed
        Room dispatches. Room responsibility stays in the Room provider
        context while its capability is active. After revocation, the latest
        bounded recovery packet may be restored here so the same Session can
        continue as an ordinary Agent.
        """

        materialized = self.context_runtime.materialize(
            session_id
        )
        allowed_source_kinds = {"memory_bootstrap"}
        if include_room_recovery:
            allowed_source_kinds.add("room_compaction_recovery")
        items = [
            item
            for item in materialized.get("items") or []
            if isinstance(item, Mapping)
            and item.get("sourceKind") in allowed_source_kinds
        ]
        return render_context_items(items)

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
        explicit_query = bounded_text(
            payload.get("queryText"),
            maximum=8_000,
        )
        if explicit_query:
            return explicit_query
        return self.recall_query(
            session_id,
            fallback=latest_user,
        )

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

    def _room_recovery(
        self,
        session_id: str,
        *,
        payload: Mapping[str, object],
        rendered: str,
        allow_revoked: bool = False,
    ) -> tuple[
        str,
        dict[str, object] | None,
        dict[str, object] | None,
    ]:
        bound = self.room_capabilities.manifest_for_runtime(
            session_id,
            active_only=not allow_revoked,
        )
        manifest, binding = bound if bound is not None else ({}, None)
        requested_skill = payload.get("roomSkillRecovery")
        requested_tools = payload.get("roomToolRecovery")
        if requested_skill is not None and not isinstance(
            requested_skill, Mapping
        ):
            raise RoomKernelFenceError(
                "Room Skill recovery must be an object"
            )
        if requested_tools is not None and not isinstance(
            requested_tools, Mapping
        ):
            raise RoomKernelFenceError(
                "Room Tool recovery must be an object"
            )
        if binding is None:
            if requested_skill is not None or requested_tools is not None:
                raise RoomKernelFenceError(
                    "Room compaction recovery has no active capability binding"
                )
            return rendered, None, None
        pinned = (
            self.room_skill_receipts.latest_for_session(session_id)
            if allow_revoked
            else self.room_skill_receipts.active_for_session(session_id)
        )
        skill_recovery: dict[str, object] | None = None
        if pinned is not None:
            revision = (
                str(requested_skill.get("catalogRevision") or "")
                if isinstance(requested_skill, Mapping)
                else str(pinned["catalogRevision"])
            )
            skill_recovery = (
                self.room_skill_receipts
                .restore_for_compaction(
                    str(pinned["receiptId"]),
                    expected_root_id=str(manifest["rootId"]),
                    expected_task_id=str(manifest["taskId"]),
                    expected_dispatch_id=str(
                        manifest["dispatchId"]
                    ),
                    expected_session_id=session_id,
                    expected_capability_epoch=int(
                        manifest["capabilityEpoch"]
                    ),
                    catalog_revision=revision,
                    allow_revoked=allow_revoked,
                )
            )
        elif requested_skill is not None:
            raise RoomKernelFenceError(
                "Room compaction requested a Skill receipt that is not pinned"
            )
        tool_recovery = (
            self.room_capabilities.restore_runtime_tool_disclosures(
                session_id=session_id,
                recovery=requested_tools,
                allow_revoked=allow_revoked,
            )
            if isinstance(requested_tools, Mapping)
            else None
        )
        # The exact Room Skill body is already pinned in the stable system
        # prompt. Recovery verifies that pin without duplicating the body in
        # the generic RAG projection. Tool schemas likewise remain disclosed
        # by Pi; only their current governed receipts are revalidated here.
        return rendered, skill_recovery, tool_recovery


def _memory_task_projection(
    task: Mapping[str, object],
) -> Mapping[str, object]:
    """Keep retrieval task-aware without duplicating Room governance facts."""

    if str(task.get("kind") or "") == "room_kernel_task":
        return {}
    return task


def _ordinary_compaction_recovery(
    *,
    summary: str,
    agent_skill_recovery: object,
    agent_tool_recovery: object,
) -> dict[str, object]:
    """Identify Pi's persisted summary without duplicating its contents.

    Pi already places the generated compaction summary back into the active
    conversation as a ``compactionSummary`` message.  This local packet only
    proves which summary and capability receipts were recovered for the new
    context epoch.  Current Task and Plan state are projected separately by
    their authoritative owners.
    """

    summary_text = str(summary or "")
    summary_bytes = summary_text.encode("utf-8")
    return {
        "schemaVersion": "rag-ime.agent-compaction-recovery.v2",
        "summaryPresent": bool(summary_text.strip()),
        "summarySha256": hashlib.sha256(summary_bytes).hexdigest(),
        "summaryChars": len(summary_text),
        "skills": _recovery_receipts(
            agent_skill_recovery,
            revision_key="contentRevision",
        ),
        "tools": _recovery_receipts(
            agent_tool_recovery,
            revision_key="schemaRevision",
        ),
    }


def _recovery_receipts(
    value: object,
    *,
    revision_key: str,
) -> list[dict[str, str]]:
    if not isinstance(value, Mapping):
        return []
    items = value.get("items")
    if not isinstance(items, (list, tuple)):
        return []
    receipts: dict[tuple[str, str], dict[str, str]] = {}
    for item in items[:32]:
        if not isinstance(item, Mapping):
            continue
        name = bounded_text(item.get("name"), maximum=128)
        revision = str(item.get(revision_key) or "").strip().lower()
        if (
            not name
            or len(revision) != 64
            or any(char not in "0123456789abcdef" for char in revision)
        ):
            continue
        receipts[(name, revision)] = {
            "name": name,
            revision_key: revision,
        }
    return [
        receipts[key]
        for key in sorted(receipts)
    ]


def _ready_existing(
    session_id: str,
    existing: Mapping[str, object],
    *,
    dedupe_key: str,
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
        "dedupeKey": str(dedupe_key or ""),
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
        "error": _error_text(error),
    }


def _error_text(error: BaseException) -> str:
    return (
        " ".join(str(error).split())[:240]
        or error.__class__.__name__
    )


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
