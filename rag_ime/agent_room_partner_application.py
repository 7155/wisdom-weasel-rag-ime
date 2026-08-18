from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .agent_room_prompt_context import agent_message_text
from .agent_room_turn_registry import RoomSessionBusyError
from .agent_room_work import (
    AgentRoomWorkAssignmentChanged,
    AgentRoomWorkAttemptChanged,
)


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
        room_work: Any,
        publish_room_work_activity: Callable[..., None],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
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
        self.room_work = room_work
        self.publish_room_work_activity = publish_room_work_activity
        self.monotonic = monotonic
        self.sleep = sleep

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
            )
        if operation == "accept":
            return self._review(source, args, accept=True)
        if operation == "return":
            return self._review(source, args, accept=False)
        if operation == "resume":
            return self._resume(source, args, tool_call_id=tool_call_id)
        if operation == "reassign":
            return self._reassign(source, args, tool_call_id=tool_call_id)
        if operation == "fail":
            return self._terminate(source, args, abandon=False)
        if operation == "abandon":
            return self._terminate(source, args, abandon=True)
        raise ValueError(
            "room_partner op must be list, delegate, delegate_batch, accept, "
            "return, resume, reassign, fail, abandon, or post"
        )

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
            default=300,
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
                        failed_result: dict[str, object] = {
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
                        work = self._work_for_tool_call(
                            room_id=room_id,
                            root_id=root_id,
                            tool_call_id=f"{tool_call_id}:{index}",
                        )
                        if work is not None:
                            failed_result = self._attach_contract(
                                failed_result,
                                work,
                            )
                        indexed_results[index] = failed_result
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
        pending_review = sum(
            str(item.get("contractStatus") or "") == "pending_review"
            for item in results
        )
        invalid = sum(
            str(item.get("contractStatus") or "")
            in {"invalid", "failed", "abandoned", "blocked", "stale_attempt"}
            for item in results
        )
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
            "acceptance": {
                "pending": pending_review,
                "invalid": invalid,
                "accepted": sum(
                    str(item.get("contractStatus") or "") == "accepted"
                    for item in results
                ),
            },
            "workflowStatus": (
                "invalid"
                if invalid
                else "awaiting_review"
                if pending_review
                else "completed"
            ),
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
        work_items = [
            dict(item)
            for item in self.room_work.list(
                room_id=str(source["roomId"]),
                limit=200,
            )
            if str(item.get("rootTurnId") or "") == root_id
        ]
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "list",
            "roomId": str(room["id"]),
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "partners": partners,
            "workItems": work_items,
            "pendingReviewCount": sum(
                str(item.get("state") or "") == "review"
                for item in work_items
            ),
            "openWorkCount": sum(
                str(item.get("state") or "")
                in {"queued", "active", "review", "blocked"}
                for item in work_items
            ),
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
        existing_work_item: Mapping[str, object] | None = None,
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
        normalized_phase = _text(phase or args.get("phase"), maximum=120)
        if not normalized_phase:
            raise ValueError("phase must not be empty")
        dependencies = tuple(
            _string_list(
                args.get("dependsOnWorkItemIds"),
                limit=8,
                maximum=240,
            )
        )
        timeout_seconds = _integer(
            args.get("timeoutSeconds"),
            default=300,
            minimum=5,
            maximum=300,
        )
        room_id = str(source["roomId"])
        room = self.rooms.get(room_id)
        root_id, parent_dispatch_id = self._active_root(source)
        self.room_work.require_dependencies_done(room_id, dependencies)
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

        if existing_work_item is None:
            assignment_id = _assignment_client_message_id(
                room_id,
                root_id,
                tool_call_id,
            )
            work, created = self.room_work.assign(
                str(source["sessionId"]),
                {
                    "targetParticipantId": target_id,
                    "clientMessageId": assignment_id,
                    "objective": task,
                    "expectedOutput": expected_output,
                    "acceptanceCriteria": criteria,
                    **(
                        {
                            "parentWorkId": _required_text(
                                args,
                                "parentWorkItemId",
                                maximum=240,
                            )
                        }
                        if str(args.get("parentWorkItemId") or "").strip()
                        else {}
                    ),
                },
                root_turn_id=root_id,
                topic_id=str(room.get("activeTopicId") or ""),
            )
            work = dict(work)
            if created:
                self.publish_room_work_activity(
                    work,
                    phase="assigned",
                    actor=source,
                )
        else:
            work = dict(existing_work_item)
            if str(work.get("roomId") or "") != room_id:
                raise ValueError("workItemId does not belong to this Room")
            if str(work.get("currentOwnerParticipantId") or "") != target_id:
                raise ValueError("workItemId is not owned by the selected Partner")
            if str(work.get("state") or "") != "active":
                raise ValueError("only active Room work may be dispatched again")

        existing_dispatch_id = self._existing_child_dispatch(
            room_id,
            root_id,
            tool_call_id,
        )
        if existing_dispatch_id:
            result = self._wait_for_child(
                room_id=room_id,
                root_id=root_id,
                child_dispatch_id=existing_dispatch_id,
                target=target,
                source=source,
                timeout_seconds=timeout_seconds,
                idempotent_replay=True,
                work=work,
            )
            if wave_id:
                result.update(
                    {
                        "waveId": wave_id,
                        "phase": normalized_phase,
                        "parallelIndex": parallel_index,
                        "parallelSize": parallel_size,
                    }
                )
            return self._settle_work_item(
                result,
                work=work,
                target=target,
                source=source,
                attempt_id=existing_dispatch_id,
                expected_revision=int(work.get("revision") or 0),
            )

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
                "workItemId": str(work["id"]),
                "workItemRevision": int(work.get("revision") or 0),
                "attemptId": child_dispatch_id,
                **(
                    {"dependsOnWorkItemIds": list(dependencies)}
                    if dependencies
                    else {}
                ),
                **({"waveId": wave_id} if wave_id else {}),
                "phaseName": normalized_phase,
                "parallelIndex": parallel_index,
                "parallelSize": parallel_size,
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
                "workItemId": str(work["id"]),
                "workItemRevision": int(work.get("revision") or 0),
                "attemptId": child_dispatch_id,
                **(
                    {"dependsOnWorkItemIds": list(dependencies)}
                    if dependencies
                    else {}
                ),
                **({"waveId": wave_id} if wave_id else {}),
                "phaseName": normalized_phase,
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
            work_item_id=str(work["id"]),
            work_item_revision=int(work.get("revision") or 0),
            attempt_id=child_dispatch_id,
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
            work_item=work,
        )
        try:
            dispatched = self.room_dispatch.dispatch_target(
                room=room,
                target=target,
                decision=decision,
                message=task_message,
                room_turn_id=root_id,
                topic_id=topic_id,
                unread=unread,
                work_item=work,
                attachment_ids=(),
            )
        except Exception as exc:
            self._record_dispatch_failure(
                work,
                source=source,
                reason=_public_error(exc),
            )
            self.cancel_room_turn(target_session_id, root_id)
            raise
        if dispatched.get("accepted") is not True:
            reason = str(dispatched.get("error") or "Partner rejected task")
            self._record_dispatch_failure(work, source=source, reason=reason)
            self.cancel_room_turn(target_session_id, root_id)
            raise RuntimeError(reason)
        try:
            work = self._claim_work_attempt(
                work,
                target=target,
                room_id=room_id,
                root_id=root_id,
                child_dispatch_id=child_dispatch_id,
            )
        except AgentRoomWorkAssignmentChanged:
            self.cancel_room_turn(target_session_id, root_id)
            try:
                self.abort_session(target_session_id)
            except Exception:
                pass
            raise
        self.publish_room_work_activity(work, phase="accepted", actor=target)
        result = self._wait_for_child(
            room_id=room_id,
            root_id=root_id,
            child_dispatch_id=child_dispatch_id,
            target=target,
            source=source,
            timeout_seconds=timeout_seconds,
            idempotent_replay=False,
            work=work,
        )
        if wave_id:
            result.update(
                {
                    "waveId": wave_id,
                    "phase": normalized_phase,
                    "parallelIndex": parallel_index,
                    "parallelSize": parallel_size,
                }
            )
        return self._settle_work_item(
            result,
            work=work,
            target=target,
            source=source,
            attempt_id=child_dispatch_id,
            expected_revision=int(work.get("revision") or 0),
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
        work: Mapping[str, object],
    ) -> dict[str, object]:
        idle_deadline = self.monotonic() + timeout_seconds
        latest_message: Mapping[str, object] | None = None
        last_progress_sequence = 0
        last_progress_at_ms = 0
        last_progress_summary = "Partner 已接收任务"
        while True:
            events = self.rooms.list_events(
                room_id,
                after_sequence=0,
                limit=2_000,
            )
            terminal: Mapping[str, object] | None = None
            newest_progress_sequence = last_progress_sequence
            for event in events:
                payload = event.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                data = payload.get("data")
                if not isinstance(data, Mapping):
                    data = payload
                event_dispatch_id = str(
                    data.get("dispatchId") or data.get("childDispatchId") or ""
                )
                if event_dispatch_id != child_dispatch_id:
                    continue
                sequence = int(event.get("sequence") or 0)
                if sequence > newest_progress_sequence:
                    newest_progress_sequence = sequence
                    last_progress_at_ms = int(event.get("createdAtMs") or 0)
                    last_progress_summary = _room_progress_summary(event, data)
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
            if newest_progress_sequence > last_progress_sequence:
                last_progress_sequence = newest_progress_sequence
                idle_deadline = self.monotonic() + timeout_seconds
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
                    "lastProgressSequence": last_progress_sequence,
                    "lastProgressAtMs": last_progress_at_ms,
                    "lastProgressSummary": last_progress_summary,
                    **_work_identity(work, attempt_id=child_dispatch_id),
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
                    **_work_identity(work, attempt_id=child_dispatch_id),
                }
            if self.monotonic() >= idle_deadline:
                break
            self.sleep(0.05)
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
                "reason": "idle_lease_expired",
                "idleSeconds": timeout_seconds,
                "lastProgressSequence": last_progress_sequence,
                "lastProgressAtMs": last_progress_at_ms,
                "lastProgressSummary": last_progress_summary,
                **_work_identity(work, attempt_id=child_dispatch_id),
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
            "error": (
                f"Partner 在 {timeout_seconds} 秒内没有新的公开运行进度；"
                "当前 WorkItem 已暂停，Root 可恢复同一任务或改派。"
            ),
            "nextStep": (
                "resume the same WorkItem, reassign it, or make an explicit "
                "fail/abandon decision"
            ),
            "lastProgressSequence": last_progress_sequence,
            "lastProgressAtMs": last_progress_at_ms,
            "lastProgressSummary": last_progress_summary,
            "idempotentReplay": idempotent_replay,
            **_work_identity(work, attempt_id=child_dispatch_id),
        }

    def _claim_work_attempt(
        self,
        work: Mapping[str, object],
        *,
        target: Mapping[str, object],
        room_id: str,
        root_id: str,
        child_dispatch_id: str,
    ) -> dict[str, object]:
        current = dict(self.room_work.get(str(work["id"]), room_id=room_id))
        state = str(current.get("state") or "")
        if state == "queued":
            return dict(
                self.room_work.accept_assignment(
                    str(current["id"]),
                    target_participant_id=str(target["id"]),
                    accepted_turn_id=child_dispatch_id,
                )
            )
        if state == "active":
            return dict(
                self.room_work.claim_dispatch(
                    str(current["id"]),
                    room_id=room_id,
                    owner_participant_id=str(target["id"]),
                    assignment_key=str(current["assignmentKey"]),
                    previous_accepted_turn_id=str(
                        current.get("acceptedTurnId") or ""
                    ),
                    room_turn_id=child_dispatch_id,
                    root_turn_id=root_id,
                )
            )
        raise AgentRoomWorkAssignmentChanged(
            "Room WorkItem changed before the Partner Session accepted its turn"
        )

    def _record_dispatch_failure(
        self,
        work: Mapping[str, object],
        *,
        source: Mapping[str, object],
        reason: str,
    ) -> None:
        current = dict(
            self.room_work.get(
                str(work["id"]),
                room_id=str(work["roomId"]),
            )
        )
        if str(current.get("state") or "") == "queued":
            current = dict(
                self.room_work.fail_assignment(
                    str(current["id"]),
                    actor_participant_id=str(source["id"]),
                    reason=reason,
                )
            )
        self.publish_room_work_activity(
            current,
            phase="assignment_failed",
            actor=source,
        )

    def _settle_work_item(
        self,
        result: dict[str, object],
        *,
        work: Mapping[str, object],
        target: Mapping[str, object],
        source: Mapping[str, object],
        attempt_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        current = dict(
            self.room_work.get(
                str(work["id"]),
                room_id=str(work["roomId"]),
            )
        )
        if (
            int(current.get("revision") or 0) != int(expected_revision)
            or str(current.get("acceptedTurnId") or "") != attempt_id
        ):
            return self._attach_contract(
                result,
                current,
                contract_status="stale_attempt",
                contract_error=(
                    "WorkItem owner, revision, or attempt changed before this "
                    "Partner result arrived"
                ),
            )
        state = str(current.get("state") or "")
        if state in {"review", "done", "failed", "cancelled", "blocked"}:
            return self._attach_contract(result, current)

        status = str(result.get("status") or "failed")
        text = str(result.get("result") or "").strip()
        try:
            if status == "completed" and text:
                settled = dict(
                    self.room_work.submit_attempt(
                        str(target["sessionId"]),
                        {
                            "workId": str(current["id"]),
                            "resultSummary": text[:4_000],
                            "evidenceRefs": [
                                f"room-dispatch:{attempt_id}",
                                f"room-session:{target['sessionId']}",
                            ],
                        },
                        attempt_id=attempt_id,
                        expected_revision=expected_revision,
                    )
                )
                self.publish_room_work_activity(
                    settled,
                    phase="submitted",
                    actor=target,
                )
                return self._attach_contract(result, settled)

            root_cancelled = status == "aborted" and self.room_turns.is_cancelled(
                str(source["sessionId"]),
                str(current.get("rootTurnId") or result.get("rootId") or ""),
            )
            if root_cancelled:
                settled = dict(
                    self.room_work.abandon(
                        str(source["sessionId"]),
                        {
                            "workId": str(current["id"]),
                            "reason": "Root turn was stopped before Partner completion",
                            "nextStep": "start a new Root turn if this work is still needed",
                        },
                    )
                )
                phase = "abandoned"
                actor = source
            else:
                reason = str(result.get("error") or "").strip() or (
                    "Partner Session returned without a public result"
                    if status == "completed"
                    else f"Partner Session ended with status {status}"
                )
                settled = dict(
                    self.room_work.block_attempt(
                        str(target["sessionId"]),
                        {
                            "workId": str(current["id"]),
                            "reason": reason,
                            "nextStep": str(result.get("nextStep") or "").strip() or (
                                "resume the same WorkItem, reassign it, or make an "
                                "explicit fail/abandon decision"
                            ),
                        },
                        attempt_id=attempt_id,
                        expected_revision=expected_revision,
                    )
                )
                phase = "blocked"
                actor = target
            self.publish_room_work_activity(settled, phase=phase, actor=actor)
            return self._attach_contract(result, settled)
        except AgentRoomWorkAttemptChanged as exc:
            latest = dict(
                self.room_work.get(
                    str(current["id"]),
                    room_id=str(current["roomId"]),
                )
            )
            return self._attach_contract(
                result,
                latest,
                contract_status="stale_attempt",
                contract_error=_public_error(exc),
            )
        except Exception as exc:
            latest = dict(
                self.room_work.get(
                    str(current["id"]),
                    room_id=str(current["roomId"]),
                )
            )
            return self._attach_contract(
                result,
                latest,
                contract_status="invalid",
                contract_error=_public_error(exc),
            )

    def _review(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        accept: bool,
    ) -> dict[str, object]:
        work_id = _required_text(args, "workItemId", maximum=240)
        room_id = str(source["roomId"])
        current = dict(self.room_work.get(work_id, room_id=room_id))
        root_id, _dispatch_id = self._active_root(source)
        if str(current.get("rootTurnId") or "") != root_id:
            raise ValueError("workItemId does not belong to the active Room turn")
        if accept:
            work = dict(
                self.room_work.accept(
                    str(source["sessionId"]),
                    {"workId": work_id},
                )
            )
            operation = "accept"
            phase = "completed"
            contract_status = "accepted"
        else:
            reason = _required_text(args, "reason", maximum=2_000)
            work = dict(
                self.room_work.return_for_revision(
                    str(source["sessionId"]),
                    {"workId": work_id, "reason": reason},
                )
            )
            operation = "return"
            phase = "returned"
            contract_status = "revision_required"
        self.publish_room_work_activity(work, phase=phase, actor=source)
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": operation,
            "roomId": room_id,
            "rootId": root_id,
            "workItem": work,
            "contractStatus": contract_status,
            **_work_identity(work),
        }

    def _resume(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        work_id = _required_text(args, "workItemId", maximum=240)
        room_id = str(source["roomId"])
        work = dict(self.room_work.get(work_id, room_id=room_id))
        root_id, _dispatch_id = self._active_root(source)
        if str(work.get("rootTurnId") or "") != root_id:
            raise ValueError("workItemId does not belong to the active Room turn")
        if str(self.room_work.reviewer_participant_id(work_id)) != str(source["id"]):
            raise ValueError("only the accountable reviewer may resume Room work")
        if str(work.get("state") or "") == "blocked":
            work = dict(
                self.room_work.resume(
                    str(source["sessionId"]),
                    {"workId": work_id},
                )
            )
            self.publish_room_work_activity(work, phase="resumed", actor=source)
        elif str(work.get("state") or "") != "active":
            raise ValueError("only returned or blocked Room work may be resumed")
        return self._dispatch_existing_work(
            source,
            args,
            work=work,
            tool_call_id=tool_call_id,
        )

    def _reassign(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        work_id = _required_text(args, "workItemId", maximum=240)
        target_id = _required_text(args, "targetParticipantId", maximum=240)
        reason = _required_text(args, "reason", maximum=2_000)
        room_id = str(source["roomId"])
        current = dict(self.room_work.get(work_id, room_id=room_id))
        root_id, _dispatch_id = self._active_root(source)
        if str(current.get("rootTurnId") or "") != root_id:
            raise ValueError("workItemId does not belong to the active Room turn")
        target = self.rooms.participant(target_id)
        if (
            str(target.get("roomId") or "") != room_id
            or str(target.get("status") or "") != "active"
        ):
            raise ValueError("target Partner is not active in this Room")
        work = dict(
            self.room_work.reassign(
                work_id,
                actor_participant_id=str(source["id"]),
                current_owner_participant_id=target_id,
                reason=reason,
            )
        )
        self.publish_room_work_activity(work, phase="reassigned", actor=source)
        return self._dispatch_existing_work(
            source,
            args,
            work=work,
            tool_call_id=tool_call_id,
        )

    def _dispatch_existing_work(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        work: Mapping[str, object],
        tool_call_id: str,
    ) -> dict[str, object]:
        blocker = work.get("blocker")
        feedback = (
            str(blocker.get("reviewFeedback") or blocker.get("reason") or "").strip()
            if isinstance(blocker, Mapping)
            else ""
        )
        objective = str(work.get("objective") or "").strip()
        task = objective if not feedback else f"{objective}\n\n返修或恢复要求：{feedback}"
        return self._delegate(
            source,
            {
                "targetParticipantId": str(work["currentOwnerParticipantId"]),
                "task": task,
                "expectedOutput": str(work.get("expectedOutput") or ""),
                "acceptanceCriteria": list(work.get("acceptanceCriteria") or []),
                "phase": _required_text(args, "phase", maximum=120),
                "timeoutSeconds": _integer(
                    args.get("timeoutSeconds"),
                    default=300,
                    minimum=5,
                    maximum=300,
                ),
            },
            tool_call_id=tool_call_id,
            existing_work_item=work,
        )

    def _terminate(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        abandon: bool,
    ) -> dict[str, object]:
        work_id = _required_text(args, "workItemId", maximum=240)
        room_id = str(source["roomId"])
        current = dict(self.room_work.get(work_id, room_id=room_id))
        root_id, _dispatch_id = self._active_root(source)
        if str(current.get("rootTurnId") or "") != root_id:
            raise ValueError("workItemId does not belong to the active Room turn")
        payload = {
            "workId": work_id,
            "reason": _required_text(args, "reason", maximum=2_000),
            "nextStep": _text(args.get("nextStep"), maximum=2_000),
        }
        operation = "abandon" if abandon else "fail"
        transition = self.room_work.abandon if abandon else self.room_work.fail
        work = dict(transition(str(source["sessionId"]), payload))
        self.publish_room_work_activity(work, phase=operation, actor=source)
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": operation,
            "roomId": room_id,
            "rootId": root_id,
            "workItem": work,
            "contractStatus": "abandoned" if abandon else "failed",
            "requiresAcceptance": False,
            **_work_identity(work),
        }

    @staticmethod
    def _attach_contract(
        result: dict[str, object],
        work: Mapping[str, object],
        *,
        contract_status: str = "",
        contract_error: str = "",
    ) -> dict[str, object]:
        state = str(work.get("state") or "")
        result["workItem"] = dict(work)
        result.update(_work_identity(work))
        if contract_status:
            result["contractStatus"] = contract_status
        elif state == "review":
            result["contractStatus"] = "pending_review"
        elif state == "done":
            result["contractStatus"] = "accepted"
        elif state == "active":
            result["contractStatus"] = "revision_required"
        elif state == "blocked":
            result["contractStatus"] = "blocked"
        elif state == "failed":
            result["contractStatus"] = "failed"
        elif state == "cancelled":
            result["contractStatus"] = "abandoned"
        else:
            result["contractStatus"] = "pending"
        result["requiresAcceptance"] = state == "review"
        if contract_error:
            result["contractError"] = contract_error
        return result

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

    def _work_for_tool_call(
        self,
        *,
        room_id: str,
        root_id: str,
        tool_call_id: str,
    ) -> dict[str, object] | None:
        client_message_id = _assignment_client_message_id(
            room_id,
            root_id,
            tool_call_id,
        )
        return next(
            (
                dict(item)
                for item in self.room_work.list(room_id=room_id, limit=200)
                if str(item.get("rootTurnId") or "") == root_id
                and str(item.get("clientMessageId") or "") == client_message_id
            ),
            None,
        )

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
        if kind == "result":
            if str(room.get("moderatorParticipantId") or "") != str(source["id"]):
                raise ValueError("only the Room Root may publish the final result")
            open_work = self.room_work.open_for_root(
                room_id=str(room["id"]),
                root_turn_id=root_id,
            )
            if open_work:
                states = ", ".join(
                    f"{item['id']}={item['state']}" for item in open_work[:8]
                )
                raise ValueError(
                    "Root final result is blocked until all formal WorkItems are "
                    f"accepted or explicitly terminated: {states}"
                )
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
    work_item: Mapping[str, object],
) -> str:
    lines = [
        f"来自 Room 主伙伴 {source.get('displayName') or 'Facilitator'} 的子任务：",
        task,
        "",
        (
            f"权威 WorkItem：{work_item.get('id')}，"
            f"revision={work_item.get('revision', 0)}。"
        ),
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


def _work_identity(
    work: Mapping[str, object],
    *,
    attempt_id: str = "",
) -> dict[str, object]:
    accepted_turn_id = attempt_id or str(work.get("acceptedTurnId") or "")
    return {
        "workItemId": str(work.get("id") or ""),
        "workItemRevision": int(work.get("revision") or 0),
        "attemptId": accepted_turn_id,
    }


def _room_progress_summary(
    event: Mapping[str, object],
    data: Mapping[str, object],
) -> str:
    event_type = str(event.get("eventType") or "运行进度")
    phase = str(data.get("phase") or data.get("status") or "").strip()
    label = str(
        data.get("summary")
        or data.get("toolName")
        or data.get("activityKind")
        or ""
    ).strip()
    if event_type == "participant_message":
        return "Partner 发布了新的公开消息"
    parts = [event_type]
    if label:
        parts.append(label[:120])
    if phase:
        parts.append(phase[:80])
    return " · ".join(parts)[:240]


def _assignment_client_message_id(
    room_id: str,
    root_id: str,
    tool_call_id: str,
) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{room_id}:{root_id}:{tool_call_id}",
    )
    return f"room-partner:{value}"


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
