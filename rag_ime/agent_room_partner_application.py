from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        send_room_intercom: Callable[[str, Mapping[str, object]], Mapping[str, object]] | None = None,
        list_room_intercom: Callable[[str], list[Mapping[str, object]]] | None = None,
        room_work: Any | None = None,
        publish_room_work_activity: Callable[..., None] | None = None,
        work_document_for_authority: Callable[[str, str], Mapping[str, object] | None] | None = None,
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
        self.send_room_intercom = send_room_intercom
        self.list_room_intercom = list_room_intercom
        self.room_work = room_work
        self.publish_room_work_activity = publish_room_work_activity
        self.work_document_for_authority = work_document_for_authority

    def execute(
        self,
        session_id: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        source_loop_id: str = "",
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
        if operation == "delegate_batch":
            return self._delegate_batch(
                source,
                args,
                tool_call_id=tool_call_id,
            )
        if operation == "post":
            return self._post(
                source,
                args,
                tool_call_id=tool_call_id,
                source_loop_id=source_loop_id,
            )
        if operation == "peer_list":
            return self._peer_list(source)
        if operation in {"peer_send", "peer_ask", "peer_reply"}:
            return self._peer_message(
                source,
                args,
                operation=operation,
                tool_call_id=tool_call_id,
            )
        raise ValueError(
            "room_partner op must be list, delegate, delegate_batch, post, "
            "peer_list, peer_send, peer_ask, or peer_reply"
        )

    def _peer_list(self, source: Mapping[str, object]) -> dict[str, object]:
        root_id, dispatch_id = self.room_turns.active_turn(
            str(source["sessionId"])
        )
        items = (
            self.list_room_intercom(str(source["sessionId"]))
            if self.list_room_intercom is not None
            else []
        )
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "peer_list",
            "roomId": str(source["roomId"]),
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "messages": [dict(item) for item in items],
        }

    def _peer_message(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        operation: str,
        tool_call_id: str,
    ) -> dict[str, object]:
        if self.send_room_intercom is None:
            raise ValueError("Room peer messaging is unavailable")
        # Peer communication is Room-member authority, not Facilitator or
        # parent-turn authority. In particular, an intercom-delivered Pi turn
        # may answer its sender even though it is not a dispatched Room root.
        root_id, dispatch_id = self.room_turns.active_turn(
            str(source["sessionId"])
        )
        kind = {
            "peer_send": "send",
            "peer_ask": "ask",
            "peer_reply": "reply",
        }[operation]
        payload: dict[str, object] = {
            "kind": kind,
            "content": _required_text(args, "content", maximum=4_000),
            "clientMessageId": _text(args.get("clientMessageId"), maximum=200)
            or tool_call_id,
        }
        if kind != "reply":
            payload["targetParticipantId"] = _required_text(
                args,
                "targetParticipantId",
                maximum=240,
            )
        else:
            payload["replyTo"] = _required_text(args, "replyTo", maximum=240)
        item = self.send_room_intercom(str(source["sessionId"]), payload)
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": operation,
            "roomId": str(source["roomId"]),
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "message": dict(item),
        }

    def _delegate_batch(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list) or not 2 <= len(raw_tasks) <= 3:
            raise ValueError("tasks must contain between two and three Partner tasks")
        tasks: list[dict[str, object]] = []
        target_ids: list[str] = []
        for index, value in enumerate(raw_tasks):
            if not isinstance(value, Mapping):
                raise ValueError(f"tasks[{index}] must be an object")
            task = dict(value)
            target_id = _required_text(
                task,
                "targetParticipantId",
                maximum=240,
            )
            _required_text(task, "task", maximum=8_000)
            _required_text(task, "expectedOutput", maximum=1_200)
            criteria = _string_list(
                task.get("acceptanceCriteria"),
                limit=8,
                maximum=320,
            )
            if not criteria:
                raise ValueError(
                    f"tasks[{index}].acceptanceCriteria must not be empty"
                )
            if target_id in target_ids:
                raise ValueError("delegate_batch requires unique target Partners")
            target_ids.append(target_id)
            tasks.append(task)

        room_id = str(source["roomId"])
        root_id, _parent_dispatch_id = self._active_root(source)
        existing_session_ids = {
            session_id
            for _participant, session_id, _turn_id in self.room_turns.turn_targets(
                root_id,
                resolve=lambda value: self.rooms.participant_for_session(
                    value,
                    active_only=False,
                ),
            )
        }
        targets: list[Mapping[str, object]] = []
        target_session_ids: list[str] = []
        existing_dispatch_ids: list[str] = []
        for target_id in target_ids:
            target = self.rooms.participant(target_id)
            if (
                str(target.get("roomId") or "") != room_id
                or str(target.get("status") or "") != "active"
            ):
                raise ValueError("target Partner is not active in this Room")
            if target_id == str(source["id"]):
                raise ValueError("a Partner cannot delegate Room work to itself")
            target_session_id = str(target.get("sessionId") or "")
            if not target_session_id:
                raise ValueError("target Partner has no Session")
            index = len(targets)
            existing_dispatch_id = self._existing_child_dispatch(
                room_id,
                root_id,
                f"{tool_call_id}:{index}",
            )
            if target_session_id in existing_session_ids and not existing_dispatch_id:
                raise ValueError(
                    "target Partner is already active in this Room turn"
                )
            targets.append(target)
            target_session_ids.append(target_session_id)
            existing_dispatch_ids.append(existing_dispatch_id)

        reserved_session_ids = [
            session_id
            for session_id, existing_dispatch_id in zip(
                target_session_ids,
                existing_dispatch_ids,
                strict=True,
            )
            if not existing_dispatch_id
        ]

        target_by_session_id = {
            session_id: target
            for session_id, target in zip(
                target_session_ids,
                targets,
                strict=True,
            )
        }

        def ensure_active(session_id: str) -> None:
            target = target_by_session_id[session_id]
            latest = self.rooms.participant_for_session(
                session_id,
                active_only=True,
            )
            if latest is None or str(latest.get("id") or "") != str(target["id"]):
                raise ValueError("target Partner changed before batch dispatch")

        try:
            if reserved_session_ids:
                self.room_turns.hold_priority_if_idle(
                    reserved_session_ids,
                    ensure_available=ensure_active,
                )
        except RoomSessionBusyError:
            raise ValueError("one or more target Partners are currently busy") from None
        busy = [
            target
            for target, session_id in zip(targets, target_session_ids, strict=True)
            if session_id in reserved_session_ids and not self.room_target_idle(
                session_id,
                allow_user_priority=True,
            )
        ]
        if busy:
            for session_id in reserved_session_ids:
                self.room_turns.release_priority_session(session_id)
            names = "、".join(
                str(item.get("displayName") or "Partner") for item in busy
            )
            raise ValueError(f"target Partners are currently busy: {names}")

        phase = _required_text(args, "phase", maximum=120)
        timeout_seconds = _integer(
            args.get("timeoutSeconds"),
            default=180,
            minimum=5,
            maximum=300,
        )
        wave_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"rag-ime:{room_id}:{root_id}:{tool_call_id}",
        )
        wave_id = f"room-wave:{wave_uuid}"
        indexed_results: dict[int, dict[str, object]] = {}
        try:
            with ThreadPoolExecutor(
                max_workers=len(tasks),
                thread_name_prefix="room-partner-wave",
            ) as executor:
                futures = {
                    executor.submit(
                        self._delegate,
                        source,
                        {
                            **task,
                            "timeoutSeconds": timeout_seconds,
                        },
                        tool_call_id=f"{tool_call_id}:{index}",
                        priority_reserved=not existing_dispatch_ids[index],
                        wave_id=wave_id,
                        phase=phase,
                        parallel_index=index,
                        parallel_size=len(tasks),
                    ): index
                    for index, task in enumerate(tasks)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        indexed_results[index] = future.result()
                    except Exception as exc:
                        indexed_results[index] = {
                            "schemaVersion": "rag-ime.room-partner-result.v1",
                            "operation": "delegate",
                            "roomId": room_id,
                            "rootId": root_id,
                            "participantId": target_ids[index],
                            "status": "failed",
                            "result": "",
                            "error": _public_error(exc),
                            "waveId": wave_id,
                            "phase": phase,
                            "parallelIndex": index,
                            "parallelSize": len(tasks),
                        }
        finally:
            # dispatch_target releases successful reservations. This final pass
            # also clears reservations for tasks that failed before Pi accepted
            # their Session turn.
            for session_id in reserved_session_ids:
                self.room_turns.release_priority_session(session_id)

        results = [indexed_results[index] for index in range(len(tasks))]
        completed = sum(
            str(item.get("status") or "") == "completed" for item in results
        )
        failed = len(results) - completed
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "delegate_batch",
            "roomId": room_id,
            "rootId": root_id,
            "waveId": wave_id,
            "phase": phase,
            "parallelism": len(tasks),
            "status": (
                "completed"
                if failed == 0
                else "failed"
                if completed == 0
                else "partial"
            ),
            "completed": completed,
            "failed": failed,
            "results": results,
        }

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
        priority_reserved: bool = False,
        wave_id: str = "",
        phase: str = "",
        parallel_index: int = 0,
        parallel_size: int = 1,
    ) -> dict[str, object]:
        target_id = _required_text(args, "targetParticipantId", maximum=240)
        task = _required_text(args, "task", maximum=8_000)
        expected_output = _required_text(args, "expectedOutput", maximum=1_200)
        criteria = _string_list(
            args.get("acceptanceCriteria"),
            limit=8,
            maximum=320,
        )
        if not criteria:
            raise ValueError("acceptanceCriteria must not be empty")
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
        existing_dispatch_id = self._existing_child_dispatch(
            room_id,
            root_id,
            tool_call_id,
        )
        if existing_dispatch_id:
            work_item = self._create_delegated_work(
                room_id=room_id,
                root_id=root_id,
                topic_id=str(room.get("activeTopicId") or ""),
                tool_call_id=tool_call_id,
                source=source,
                target=target,
                task=task,
                expected_output=expected_output,
                acceptance_criteria=criteria,
            )
            result = self._wait_for_child(
                room_id=room_id,
                root_id=root_id,
                child_dispatch_id=existing_dispatch_id,
                target=target,
                source=source,
                timeout_seconds=timeout_seconds,
                idempotent_replay=True,
                work_item=work_item,
            )
            if wave_id:
                result.update(
                    {
                        "waveId": wave_id,
                        "phase": phase,
                        "parallelIndex": parallel_index,
                        "parallelSize": parallel_size,
                    }
                )
            return result

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

        def ensure_active(session_id: str) -> None:
            latest = self.rooms.participant_for_session(
                session_id,
                active_only=True,
            )
            if latest is None or str(latest.get("id") or "") != target_id:
                raise ValueError("target Partner changed before dispatch")

        if not priority_reserved:
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
        work_item = self._create_delegated_work(
            room_id=room_id,
            root_id=root_id,
            topic_id=str(room.get("activeTopicId") or ""),
            tool_call_id=tool_call_id,
            source=source,
            target=target,
            task=task,
            expected_output=expected_output,
            acceptance_criteria=criteria,
        )
        decision.update(
            {
                # A Partner Tool dispatch is an explicit coordinator
                # delegation, not a fresh invitation from the user.  Keep the
                # distinction in the public route event so Room projections do
                # not attribute this child Session to the user.
                "reason": "partner_delegate",
                "rootId": root_id,
                "dispatchId": child_dispatch_id,
                "targetSessionId": target_session_id,
                "parentDispatchId": parent_dispatch_id,
                "child": True,
                "toolCallId": tool_call_id,
                **({"waveId": wave_id} if wave_id else {}),
                **({"phaseName": phase} if phase else {}),
                "parallelIndex": parallel_index,
                "parallelSize": parallel_size,
                **(
                    {
                        "workItemId": str(work_item["id"]),
                        "workItemState": str(work_item.get("state") or ""),
                    }
                    if work_item
                    else {}
                ),
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
                "expectedOutput": expected_output,
                "acceptanceCriteria": criteria,
                **({"workItem": dict(work_item)} if work_item else {}),
                **({"waveId": wave_id} if wave_id else {}),
                **({"phaseName": phase} if phase else {}),
                "parallelIndex": parallel_index,
                "parallelSize": parallel_size,
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
        previous_accepted_turn_id = str(work_item.get("acceptedTurnId") or "")
        work_claimed = False
        if self.room_work is not None and previous_accepted_turn_id != root_id:
            work_item = self.room_work.claim_dispatch(
                str(work_item["id"]),
                room_id=room_id,
                owner_participant_id=target_id,
                assignment_key=str(work_item["assignmentKey"]),
                previous_accepted_turn_id=previous_accepted_turn_id,
                room_turn_id=root_id,
            )
            work_claimed = True
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
            work_item=work_item or None,
            attachment_ids=(),
        )
        if dispatched.get("accepted") is not True:
            self._fail_delegated_work(
                work_item,
                source=source,
                target=target,
                root_id=root_id,
                previous_accepted_turn_id=previous_accepted_turn_id,
                work_claimed=work_claimed,
                reason=str(dispatched.get("error") or "Partner rejected task"),
            )
            raise RuntimeError(str(dispatched.get("error") or "Partner rejected task"))
        result = self._wait_for_child(
            room_id=room_id,
            root_id=root_id,
            child_dispatch_id=child_dispatch_id,
            target=target,
            source=source,
            timeout_seconds=timeout_seconds,
            idempotent_replay=False,
            work_item=work_item,
        )
        if wave_id:
            result.update(
                {
                    "waveId": wave_id,
                    "phase": phase,
                    "parallelIndex": parallel_index,
                    "parallelSize": parallel_size,
                }
            )
        return result

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
        work_item: Mapping[str, object] | None = None,
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
            work_result_post: Mapping[str, object] | None = None
            for event in events:
                payload = event.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                if str(event.get("eventType") or "") == "room_post":
                    post = payload.get("post")
                    if (
                        isinstance(post, Mapping)
                        and str(post.get("rootId") or "") == root_id
                        and str(post.get("dispatchId") or "")
                        == child_dispatch_id
                        and str(post.get("authorActorRef") or "")
                        == str(target["id"])
                        and str(post.get("kind") or "") == "work_result"
                    ):
                        work_result_post = post
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
                settled_work = self._settle_delegated_work(
                    work_item,
                    phase=phase,
                    result=text,
                    child_dispatch_id=child_dispatch_id,
                    source=source,
                    target=target,
                )
                settled_status = (
                    "blocked"
                    if phase == "completed"
                    and settled_work is not None
                    and str(settled_work.get("state") or "") == "blocked"
                    else phase
                )
                return {
                    "schemaVersion": "rag-ime.room-partner-result.v1",
                    "operation": "delegate",
                    "roomId": room_id,
                    "rootId": root_id,
                    "childDispatchId": child_dispatch_id,
                    "participantId": str(target["id"]),
                    "displayName": str(target.get("displayName") or ""),
                    "status": settled_status,
                    "result": text[:16_000],
                    "idempotentReplay": idempotent_replay,
                    **(
                        {"workItem": dict(settled_work)}
                        if settled_work is not None
                        else {}
                    ),
                }
            if work_result_post is not None:
                # A typed work_result is the participant's explicit delivery
                # boundary.  Do not keep the parent Tool call open until the
                # whole Pi Session turn also becomes terminal: direct peer
                # messages may legitimately start more loops after delivery.
                # WorkDocument readiness is still enforced by the same durable
                # settlement path used for a normal child terminal.
                text = str(work_result_post.get("content") or "")
                settled_work = self._settle_delegated_work(
                    work_item,
                    phase="completed",
                    result=text,
                    child_dispatch_id=child_dispatch_id,
                    source=source,
                    target=target,
                )
                settled_status = (
                    "blocked"
                    if settled_work is not None
                    and str(settled_work.get("state") or "") == "blocked"
                    else "completed"
                )
                return {
                    "schemaVersion": "rag-ime.room-partner-result.v1",
                    "operation": "delegate",
                    "roomId": room_id,
                    "rootId": root_id,
                    "childDispatchId": child_dispatch_id,
                    "participantId": str(target["id"]),
                    "displayName": str(target.get("displayName") or ""),
                    "status": settled_status,
                    "result": text[:16_000],
                    "completionSource": "room_post",
                    "postId": str(work_result_post.get("postId") or ""),
                    "idempotentReplay": idempotent_replay,
                    **(
                        {"workItem": dict(settled_work)}
                        if settled_work is not None
                        else {}
                    ),
                }
            if self.room_turns.is_cancelled(
                str(source["sessionId"]),
                root_id,
            ):
                settled_work = self._settle_delegated_work(
                    work_item,
                    phase="aborted",
                    result="Room root turn was cancelled",
                    child_dispatch_id=child_dispatch_id,
                    source=source,
                    target=target,
                )
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
                    **(
                        {"workItem": dict(settled_work)}
                        if settled_work is not None
                        else {}
                    ),
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
        settled_work = self._settle_delegated_work(
            work_item,
            phase="timed_out",
            result="Partner dispatch exceeded its bounded wait",
            child_dispatch_id=child_dispatch_id,
            source=source,
            target=target,
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
            **(
                {"workItem": dict(settled_work)}
                if settled_work is not None
                else {}
            ),
        }

    def _create_delegated_work(
        self,
        *,
        room_id: str,
        root_id: str,
        topic_id: str,
        tool_call_id: str,
        source: Mapping[str, object],
        target: Mapping[str, object],
        task: str,
        expected_output: str,
        acceptance_criteria: list[str],
    ) -> dict[str, object]:
        if self.room_work is None:
            # Compatibility for isolated adapters. The installed AgentService
            # always supplies the durable Room responsibility ledger.
            return {}
        client_message_id = f"room-partner:{root_id}:{tool_call_id}"
        for existing in self.room_work.list(
            room_id=room_id,
            states=(),
            limit=200,
        ):
            if (
                str(existing.get("createdByParticipantId") or "")
                == str(source["id"])
                and str(existing.get("clientMessageId") or "")
                == client_message_id
            ):
                return dict(existing)
        work = self.room_work.create(
            room_id=room_id,
            objective=task,
            expected_output=expected_output,
            current_owner_participant_id=str(target["id"]),
            created_by_participant_id=str(source["id"]),
            accountable_participant_id=str(source["id"]),
            client_message_id=client_message_id,
            topic_id=topic_id,
            root_turn_id=root_id,
            acceptance_criteria=acceptance_criteria,
            state="active",
            depth=1,
        )
        self._publish_work_activity(work, phase="assigned", actor=source)
        return dict(work)

    def _settle_delegated_work(
        self,
        work_item: Mapping[str, object] | None,
        *,
        phase: str,
        result: str,
        child_dispatch_id: str,
        source: Mapping[str, object],
        target: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        if self.room_work is None or not work_item or not work_item.get("id"):
            return work_item
        current = self.room_work.get(
            str(work_item["id"]),
            room_id=str(work_item["roomId"]),
        )
        state = str(current.get("state") or "")
        if phase == "completed":
            document: Mapping[str, object] | None = None
            if self.work_document_for_authority is not None:
                document = self.work_document_for_authority(
                    "room_work_item",
                    str(current["id"]),
                )
                document_revision = int(
                    (document or {}).get("documentRevision") or 0
                )
                if document is None or document_revision < 2:
                    if state == "active":
                        current = self.room_work.block(
                            str(target["sessionId"]),
                            {
                                "workId": current["id"],
                                "reason": (
                                    "伙伴回合已结束，但负责的 WorkDocument 尚未完成开工与交付同步。"
                                ),
                                "nextStep": (
                                    "先登记 room_work_item 活动文档，写入目标/范围；完成后再次更新结果、"
                                    "证据、改动文件、验证与剩余风险，使 documentRevision 至少为 2。"
                                ),
                            },
                        )
                        self._publish_work_activity(
                            current,
                            phase="blocked",
                            actor=target,
                        )
                    return current
            if state in {"active", "blocked"}:
                evidence_refs = [child_dispatch_id]
                if document is not None:
                    evidence_refs.append(
                        "workdoc:"
                        f"{document.get('documentId')}@"
                        f"{document.get('documentRevision')}"
                    )
                current = self.room_work.submit(
                    str(target["sessionId"]),
                    {
                        "workId": current["id"],
                        "resultSummary": result[:4_000]
                        or "Partner Session completed the delegated WorkItem.",
                        "evidenceRefs": evidence_refs,
                    },
                )
                self._publish_work_activity(
                    current,
                    phase="submitted",
                    actor=target,
                )
                current = self.room_work.accept(
                    str(source["sessionId"]),
                    {"workId": current["id"]},
                )
                self._publish_work_activity(
                    current,
                    phase="completed",
                    actor=source,
                )
            return current
        if state in {"active", "blocked"}:
            current = self.room_work.escalate(
                str(target["sessionId"]),
                {
                    "workId": current["id"],
                    "reason": result[:2_000] or f"Partner dispatch ended as {phase}",
                    "nextStep": "由 Room 伙伴缩小范围后重新分派，或明确保留为未解决项。",
                },
            )
            self._publish_work_activity(current, phase="failed", actor=target)
        return current

    def _fail_delegated_work(
        self,
        work_item: Mapping[str, object],
        *,
        source: Mapping[str, object],
        target: Mapping[str, object],
        root_id: str,
        previous_accepted_turn_id: str,
        work_claimed: bool,
        reason: str,
    ) -> None:
        if self.room_work is None or not work_item.get("id"):
            return
        current = dict(work_item)
        if work_claimed:
            current = self.room_work.fail_dispatch(
                str(current["id"]),
                room_id=str(current["roomId"]),
                actor_participant_id=str(source["id"]),
                room_turn_id=root_id,
                previous_accepted_turn_id=previous_accepted_turn_id,
                reason=reason,
            )
        if str(current.get("state") or "") in {"active", "blocked"}:
            current = self.room_work.escalate(
                str(target["sessionId"]),
                {
                    "workId": current["id"],
                    "reason": reason,
                    "nextStep": "检查目标 Session 后重新分派。",
                },
            )
        self._publish_work_activity(current, phase="failed", actor=source)

    def _publish_work_activity(
        self,
        work: Mapping[str, object],
        *,
        phase: str,
        actor: Mapping[str, object],
    ) -> None:
        if self.publish_room_work_activity is None or not work:
            return
        self.publish_room_work_activity(work, phase=phase, actor=actor)

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
        source_loop_id: str = "",
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
        settled_work_items: list[dict[str, object]] = []
        if kind in {"result", "blocked"} and self.room_work is not None:
            for work in self.room_work.list(
                room_id=str(room["id"]),
                states=("review",),
                limit=200,
            ):
                if (
                    str(work.get("rootTurnId") or "") != root_id
                    or str(work.get("accountableParticipantId") or "")
                    != str(source["id"])
                ):
                    continue
                accepted = self.room_work.accept(
                    str(source["sessionId"]),
                    {"workId": work["id"]},
                )
                self._publish_work_activity(
                    accepted,
                    phase="completed",
                    actor=source,
                )
                settled_work_items.append(dict(accepted))
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
        latest_runtime_turn_id = getattr(
            self.sessions,
            "latest_runtime_turn_id",
            None,
        )
        source_turn_id = (
            str(latest_runtime_turn_id(str(source["sessionId"])) or "")
            if callable(latest_runtime_turn_id)
            else ""
        )
        self.room_events.publish(
            room_id=str(room["id"]),
            event_type="room_post",
            payload={
                "post": post,
                **(
                    {"sourceTurnId": source_turn_id}
                    if source_turn_id
                    else {}
                ),
                **(
                    {"sourceLoopId": source_loop_id[:240]}
                    if source_loop_id
                    else {}
                ),
            },
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
            "settledWorkItems": settled_work_items,
        }


def _partner_task_message(
    *,
    source: Mapping[str, object],
    task: str,
    expected_output: str,
    acceptance_criteria: list[str],
) -> str:
    lines = [
        f"来自 Room 伙伴 {source.get('displayName') or 'Partner'} 的 WorkItem：",
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
            "直接完成当前 WorkItem 并返回有界结果；需要其他伙伴信息时直接使用 peer @ 通道，不要让发送者代为转发。Root 伙伴负责最终汇合。",
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


def _public_error(error: BaseException) -> str:
    return " ".join(str(error).split())[:240] or error.__class__.__name__
