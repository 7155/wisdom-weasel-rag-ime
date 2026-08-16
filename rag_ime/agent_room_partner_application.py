from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any, Callable

from .agent_room_prompt_context import agent_message_text
from .agent_room_turn_registry import RoomSessionBusyError


class RoomPartnerApplicationService:
    """A thin Partner adapter over ordinary Pi Sessions.

    Room owns only routing, public events and the parent/child relationship.
    Pi continues to own each Session turn, Tool loop, Steer and cancellation.
    """

    def __init__(
        self,
        *,
        rooms: Any,
        room_turns: Any,
        runtime_status: Callable[[], Mapping[str, object]],
        sessions: Any,
        room_events: Any,
        room_target_idle: Callable[..., bool],
        begin_room_turn: Callable[..., None],
        room_dispatch: Any,
        cancel_room_turn: Callable[[str, str], None],
        abort_session: Callable[[str], Mapping[str, object]],
        room_topic_for_turn: Callable[[str], str],
    ) -> None:
        self.rooms = rooms
        self.room_turns = room_turns
        self.runtime_status = runtime_status
        self.sessions = sessions
        self.room_events = room_events
        self.room_target_idle = room_target_idle
        self.begin_room_turn = begin_room_turn
        self.room_dispatch = room_dispatch
        self.cancel_room_turn = cancel_room_turn
        self.abort_session = abort_session
        self.room_topic_for_turn = room_topic_for_turn

    def execute(
        self,
        session_id: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        source = self._participant(session_id)
        operation = str(args.get("op") or "list").strip()
        if operation == "list":
            return self._list(source)
        if operation == "delegate":
            return self._delegate(
                source,
                args,
                tool_call_id=tool_call_id,
            )
        if operation == "post":
            return self._post(
                source,
                args,
                tool_call_id=tool_call_id,
            )
        raise ValueError("room_partner op must be list, delegate, or post")

    def _participant(self, session_id: str) -> dict[str, object]:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=True,
        )
        if participant is None:
            raise ValueError("room_partner is only available in an active Room")
        room = self.rooms.get(str(participant["roomId"]))
        if str(room.get("status") or "") != "active":
            raise ValueError("Room is not active")
        return participant

    def _active_root(
        self,
        source: Mapping[str, object],
    ) -> tuple[str, str]:
        root_id, dispatch_id = self.room_turns.active_turn(
            str(source["sessionId"])
        )
        if not root_id or not dispatch_id:
            raise ValueError("room_partner requires an active Room turn")
        return root_id, dispatch_id

    def _list(self, source: Mapping[str, object]) -> dict[str, object]:
        room = self.rooms.get(str(source["roomId"]))
        root_id, dispatch_id = self._active_root(source)
        active_sessions = {
            str(value)
            for value in self.runtime_status().get(
                "activeSessionIds",
                [],
            )
            if str(value or "").strip()
        }
        partners = []
        for value in room.get("participants", []):
            if (
                not isinstance(value, Mapping)
                or str(value.get("status") or "") != "active"
                or str(value.get("id") or "") == str(source["id"])
            ):
                continue
            partner_session_id = str(value.get("sessionId") or "")
            session = self.sessions.get(partner_session_id)
            partners.append(
                {
                    "participantId": str(value.get("id") or ""),
                    "displayName": str(value.get("displayName") or ""),
                    "collaborationRole": str(
                        value.get("collaborationRole") or "implementer"
                    ),
                    "sessionId": partner_session_id,
                    "modelProfile": str(session.get("modelProfile") or ""),
                    "thinkingLevel": str(session.get("thinkingLevel") or ""),
                    "status": (
                        "busy"
                        if partner_session_id in active_sessions
                        else str(session.get("status") or "idle")
                    ),
                }
            )
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "list",
            "roomId": str(room["id"]),
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "partners": partners,
        }

    def _delegate(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        target_id = _required_text(args, "targetParticipantId", maximum=240)
        task = _required_text(args, "task", maximum=8_000)
        expected_output = _text(args.get("expectedOutput"), maximum=1_200)
        criteria = _string_list(
            args.get("acceptanceCriteria"),
            limit=8,
            maximum=320,
        )
        timeout_seconds = _integer(
            args.get("timeoutSeconds"),
            default=180,
            minimum=5,
            maximum=300,
        )
        room_id = str(source["roomId"])
        room = self.rooms.get(room_id)
        root_id, parent_dispatch_id = self._active_root(source)
        target = self.rooms.participant(target_id)
        if (
            str(target.get("roomId") or "") != room_id
            or str(target.get("status") or "") != "active"
        ):
            raise ValueError("target Partner is not active in this Room")
        if target_id == str(source["id"]):
            raise ValueError("a Partner cannot delegate Room work to itself")
        target_session_id = str(target.get("sessionId") or "")
        if any(
            session_id == target_session_id
            for _participant, session_id, _turn_id in self.room_turns.turn_targets(
                root_id,
                resolve=lambda value: self.rooms.participant_for_session(
                    value,
                    active_only=False,
                ),
            )
        ):
            raise ValueError("target Partner is already active in this Room turn")

        existing_dispatch_id = self._existing_child_dispatch(
            room_id,
            root_id,
            tool_call_id,
        )
        if existing_dispatch_id:
            return self._wait_for_child(
                room_id=room_id,
                root_id=root_id,
                child_dispatch_id=existing_dispatch_id,
                target=target,
                source=source,
                timeout_seconds=timeout_seconds,
                idempotent_replay=True,
            )

        def ensure_active(session_id: str) -> None:
            latest = self.rooms.participant_for_session(
                session_id,
                active_only=True,
            )
            if latest is None or str(latest.get("id") or "") != target_id:
                raise ValueError("target Partner changed before dispatch")

        try:
            self.room_turns.hold_priority_if_idle(
                [target_session_id],
                ensure_available=ensure_active,
            )
        except RoomSessionBusyError:
            raise ValueError("target Partner is currently busy") from None
        if not self.room_target_idle(
            target_session_id,
            allow_user_priority=True,
        ):
            self.room_turns.release_priority_session(target_session_id)
            raise ValueError("target Partner is currently busy")

        decision = self.rooms.plan_routes(
            room_id,
            task,
            requested_participant_ids=[target_id],
            conversation_only=False,
        )[0]
        child_dispatch_id = f"room-child:{uuid.uuid4()}"
        decision.update(
            {
                "rootId": root_id,
                "dispatchId": child_dispatch_id,
                "targetSessionId": target_session_id,
                "parentDispatchId": parent_dispatch_id,
                "child": True,
                "toolCallId": tool_call_id,
            }
        )
        topic_id = str(room.get("activeTopicId") or "")
        self.room_events.publish(
            room_id=room_id,
            event_type="route_decision",
            payload=decision,
            turn_id=root_id,
            participant_id=target_id,
            source_session_id=target_session_id,
            topic_id=topic_id,
        )
        self.room_events.publish(
            room_id=room_id,
            event_type="participant_activity",
            payload={
                "activityKind": "child",
                "phase": "started",
                "parentParticipantId": str(source["id"]),
                "targetParticipantId": target_id,
                "parentDispatchId": parent_dispatch_id,
                "childDispatchId": child_dispatch_id,
                "toolCallId": tool_call_id,
                "task": task[:1_200],
            },
            turn_id=root_id,
            participant_id=str(source["id"]),
            source_session_id=str(source["sessionId"]),
            topic_id=topic_id,
        )
        self.begin_room_turn(
            target_session_id,
            root_id,
            topic_id,
            dispatch_id=child_dispatch_id,
            child=True,
        )
        unread = self.rooms.unread_public_messages(
            room_id,
            target_id,
            topic_id=topic_id,
            exclude_turn_id=root_id,
            limit=12,
        )
        task_message = _partner_task_message(
            source=source,
            task=task,
            expected_output=expected_output,
            acceptance_criteria=criteria,
        )
        dispatched = self.room_dispatch.dispatch_target(
            room=room,
            target=target,
            decision=decision,
            message=task_message,
            room_turn_id=root_id,
            topic_id=topic_id,
            unread=unread,
            work_item=None,
            attachment_ids=(),
        )
        if dispatched.get("accepted") is not True:
            raise RuntimeError(str(dispatched.get("error") or "Partner rejected task"))
        return self._wait_for_child(
            room_id=room_id,
            root_id=root_id,
            child_dispatch_id=child_dispatch_id,
            target=target,
            source=source,
            timeout_seconds=timeout_seconds,
            idempotent_replay=False,
        )

    def _wait_for_child(
        self,
        *,
        room_id: str,
        root_id: str,
        child_dispatch_id: str,
        target: Mapping[str, object],
        source: Mapping[str, object],
        timeout_seconds: int,
        idempotent_replay: bool,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        latest_message: Mapping[str, object] | None = None
        while time.monotonic() < deadline:
            events = self.rooms.list_events(
                room_id,
                after_sequence=0,
                limit=2_000,
            )
            terminal: Mapping[str, object] | None = None
            for event in events:
                payload = event.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                data = payload.get("data")
                if not isinstance(data, Mapping):
                    data = payload
                if str(data.get("dispatchId") or data.get("childDispatchId") or "") != child_dispatch_id:
                    continue
                if str(event.get("eventType") or "") == "participant_message":
                    message = data.get("message")
                    if isinstance(message, Mapping):
                        latest_message = message
                if (
                    str(event.get("eventType") or "") == "participant_activity"
                    and str(data.get("activityKind") or "") == "child"
                    and str(data.get("phase") or "") in {"completed", "failed", "aborted"}
                ):
                    terminal = data
            if terminal is not None:
                phase = str(terminal.get("phase") or "failed")
                text = (
                    agent_message_text(latest_message)
                    if latest_message is not None
                    else ""
                )
                return {
                    "schemaVersion": "rag-ime.room-partner-result.v1",
                    "operation": "delegate",
                    "roomId": room_id,
                    "rootId": root_id,
                    "childDispatchId": child_dispatch_id,
                    "participantId": str(target["id"]),
                    "displayName": str(target.get("displayName") or ""),
                    "status": phase,
                    "result": text[:16_000],
                    "idempotentReplay": idempotent_replay,
                }
            if self.room_turns.is_cancelled(
                str(source["sessionId"]),
                root_id,
            ):
                return {
                    "schemaVersion": "rag-ime.room-partner-result.v1",
                    "operation": "delegate",
                    "roomId": room_id,
                    "rootId": root_id,
                    "childDispatchId": child_dispatch_id,
                    "participantId": str(target["id"]),
                    "status": "aborted",
                    "result": "",
                    "idempotentReplay": idempotent_replay,
                }
            time.sleep(0.05)
        target_session_id = str(target.get("sessionId") or "")
        # The Tool wait is bounded. Do not leave a Partner Session or its Room
        # activity card running after the caller has already received a timeout.
        # Drop the child mapping before abort so the late Pi terminal cannot be
        # projected as a second child terminal, then publish one explicit end.
        self.cancel_room_turn(target_session_id, root_id)
        abort_error = ""
        try:
            self.abort_session(target_session_id)
        except Exception as exc:
            abort_error = str(exc).strip()[:240]
        self.room_events.publish(
            room_id=room_id,
            event_type="participant_activity",
            payload={
                "activityKind": "child",
                "phase": "aborted",
                "status": "timed_out",
                "rootId": root_id,
                "childDispatchId": child_dispatch_id,
                "dispatchId": child_dispatch_id,
                "reason": "bounded_wait_expired",
                **({"abortError": abort_error} if abort_error else {}),
            },
            turn_id=root_id,
            participant_id=str(target["id"]),
            source_session_id=target_session_id,
            topic_id=self.room_topic_for_turn(root_id),
        )
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "delegate",
            "roomId": room_id,
            "rootId": root_id,
            "childDispatchId": child_dispatch_id,
            "participantId": str(target["id"]),
            "displayName": str(target.get("displayName") or ""),
            "status": "timed_out",
            "result": "",
            "idempotentReplay": idempotent_replay,
        }

    def _existing_child_dispatch(
        self,
        room_id: str,
        root_id: str,
        tool_call_id: str,
    ) -> str:
        for event in self.rooms.list_events(
            room_id,
            after_sequence=0,
            limit=2_000,
        ):
            if (
                str(event.get("turnId") or "") != root_id
                or str(event.get("eventType") or "") != "participant_activity"
            ):
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if (
                payload.get("activityKind") == "child"
                and payload.get("phase") == "started"
                and str(payload.get("toolCallId") or "") == tool_call_id
            ):
                return str(payload.get("childDispatchId") or "")
        return ""

    def _post(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        content = _required_text(args, "content", maximum=8_000)
        kind = _text(args.get("kind"), maximum=40) or "progress"
        if kind not in {
            "progress",
            "result",
            "work_result",
            "review_result",
            "handoff",
            "wait",
            "blocked",
        }:
            raise ValueError("room_partner post kind is invalid")
        root_id, dispatch_id = self._active_root(source)
        room = self.rooms.get(str(source["roomId"]))
        post_id = f"room-post:{tool_call_id}"
        created_at_ms = int(time.time() * 1_000)
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": post_id,
            "roomId": str(room["id"]),
            "rootId": root_id,
            "generation": 0,
            "dispatchId": dispatch_id,
            "authorActorRef": str(source["id"]),
            "kind": kind,
            "visibility": "room",
            "content": content,
            "idempotencyKey": tool_call_id,
            "publicationSource": {
                "kind": "room_post",
                "ref": tool_call_id,
            },
            "createdAtMs": created_at_ms,
        }
        self.room_events.publish(
            room_id=str(room["id"]),
            event_type="room_post",
            payload={"post": post},
            turn_id=root_id,
            participant_id=str(source["id"]),
            source_session_id=str(source["sessionId"]),
            topic_id=str(room.get("activeTopicId") or ""),
        )
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "post",
            "roomId": str(room["id"]),
            "rootId": root_id,
            "postId": post_id,
            "kind": kind,
            "published": True,
        }


def _partner_task_message(
    *,
    source: Mapping[str, object],
    task: str,
    expected_output: str,
    acceptance_criteria: list[str],
) -> str:
    lines = [
        f"来自 Room 主伙伴 {source.get('displayName') or 'Facilitator'} 的子任务：",
        task,
    ]
    if expected_output:
        lines.extend(["", f"预期输出：{expected_output}"])
    if acceptance_criteria:
        lines.extend(
            ["", "验收条件：", *[f"- {value}" for value in acceptance_criteria]]
        )
    lines.extend(
        [
            "",
            "直接完成当前子任务并返回有界结果；不要重新拆分整个 Room，也不要代替主伙伴给用户最终答复。",
        ]
    )
    return "\n".join(lines)[:12_000]


def _required_text(
    value: Mapping[str, object],
    key: str,
    *,
    maximum: int,
) -> str:
    text = _text(value.get(key), maximum=maximum)
    if not text:
        raise ValueError(f"{key} must not be empty")
    return text


def _text(value: object, *, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _string_list(value: object, *, limit: int, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _text(item, maximum=maximum)
        if text and text not in result:
            result.append(text)
    return result


def _integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
