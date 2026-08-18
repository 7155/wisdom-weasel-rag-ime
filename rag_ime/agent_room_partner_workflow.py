from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable

from .agent_room_partner_application import (
    RoomPartnerApplicationService as _SessionPartnerApplicationService,
    _integer,
    _required_text,
    _string_list,
    _text,
)


@dataclass
class _PartnerWorkContext:
    work: dict[str, object]
    source: Mapping[str, object]
    target: Mapping[str, object]
    room_id: str
    root_id: str
    child_dispatch_id: str = ""
    dependencies: tuple[str, ...] = ()
    phase: str = ""


class _RoomEventWorkItemAdapter:
    """Attach authority facts to the existing public Room event stream."""

    def __init__(
        self,
        delegate: Any,
        context: ContextVar[_PartnerWorkContext | None],
    ) -> None:
        self._delegate = delegate
        self._context = context

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def publish(self, **values: object) -> dict[str, object]:
        context = self._context.get()
        payload = values.get("payload")
        if context is not None and isinstance(payload, Mapping):
            event_type = str(values.get("event_type") or "")
            activity_kind = str(payload.get("activityKind") or "")
            if event_type == "route_decision" or (
                event_type == "participant_activity" and activity_kind == "child"
            ):
                enriched = dict(payload)
                enriched.setdefault("workItemId", str(context.work["id"]))
                enriched.setdefault("phaseName", context.phase)
                if context.dependencies:
                    enriched.setdefault(
                        "dependsOnWorkItemIds",
                        list(context.dependencies),
                    )
                values = {**values, "payload": enriched}
        return dict(self._delegate.publish(**values))


class _RoomDispatchWorkItemAdapter:
    """Bind an ordinary Pi Session dispatch to the durable WorkItem lease."""

    def __init__(
        self,
        delegate: Any,
        context: ContextVar[_PartnerWorkContext | None],
        *,
        room_work: Any,
        publish_room_work_activity: Callable[..., None],
    ) -> None:
        self._delegate = delegate
        self._context = context
        self._room_work = room_work
        self._publish_room_work_activity = publish_room_work_activity

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def dispatch_target(self, **kwargs: object) -> dict[str, object]:
        context = self._context.get()
        if context is None:
            return dict(self._delegate.dispatch_target(**kwargs))
        decision = kwargs.get("decision")
        if isinstance(decision, Mapping):
            context.child_dispatch_id = str(decision.get("dispatchId") or "")
        kwargs = {**kwargs, "work_item": dict(context.work)}
        try:
            result = dict(self._delegate.dispatch_target(**kwargs))
        except Exception as exc:
            self._record_dispatch_failure(context, str(exc))
            raise
        if result.get("accepted") is not True:
            self._record_dispatch_failure(
                context,
                str(result.get("error") or "Partner rejected task"),
            )
            return result
        context.work = self._claim(context)
        self._publish_room_work_activity(
            context.work,
            phase="accepted",
            actor=context.target,
        )
        result["workItemId"] = str(context.work["id"])
        return result

    def _claim(self, context: _PartnerWorkContext) -> dict[str, object]:
        current = dict(
            self._room_work.get(
                str(context.work["id"]),
                room_id=context.room_id,
            )
        )
        state = str(current.get("state") or "")
        if state == "queued":
            return dict(
                self._room_work.accept_assignment(
                    str(current["id"]),
                    target_participant_id=str(context.target["id"]),
                    accepted_turn_id=context.child_dispatch_id,
                )
            )
        if state == "active":
            return dict(
                self._room_work.claim_dispatch(
                    str(current["id"]),
                    room_id=context.room_id,
                    owner_participant_id=str(context.target["id"]),
                    assignment_key=str(current["assignmentKey"]),
                    previous_accepted_turn_id=str(
                        current.get("acceptedTurnId") or ""
                    ),
                    room_turn_id=context.child_dispatch_id,
                )
            )
        raise ValueError(
            "Room Partner work must be queued or active before dispatch"
        )

    def _record_dispatch_failure(
        self,
        context: _PartnerWorkContext,
        reason: str,
    ) -> None:
        current = dict(
            self._room_work.get(
                str(context.work["id"]),
                room_id=context.room_id,
            )
        )
        state = str(current.get("state") or "")
        if state == "queued":
            failed = self._room_work.fail_assignment(
                str(current["id"]),
                actor_participant_id=str(context.source["id"]),
                reason=reason,
            )
        elif state == "active" and context.child_dispatch_id:
            failed = self._room_work.fail_dispatch(
                str(current["id"]),
                room_id=context.room_id,
                actor_participant_id=str(context.source["id"]),
                room_turn_id=context.child_dispatch_id,
                previous_accepted_turn_id=str(
                    current.get("acceptedTurnId") or ""
                ),
                reason=reason,
            )
        else:
            return
        self._publish_room_work_activity(
            failed,
            phase="assignment_failed",
            actor=context.source,
        )


class RoomPartnerApplicationService(_SessionPartnerApplicationService):
    """Room workflow authority over ordinary Pi Partner Sessions.

    The base adapter continues to launch and wait for ordinary Pi Sessions.
    This layer adds only PAW-owned WorkItems, dependency gates, review state,
    public authority facts, and the Root final-delivery gate.
    """

    def __init__(
        self,
        *,
        room_work: Any,
        publish_room_work_activity: Callable[..., None],
        **kwargs: object,
    ) -> None:
        self.room_work = room_work
        self.publish_room_work_activity = publish_room_work_activity
        self._work_context: ContextVar[_PartnerWorkContext | None] = ContextVar(
            "room_partner_work_context",
            default=None,
        )
        room_events = kwargs.pop("room_events")
        room_dispatch = kwargs.pop("room_dispatch")
        super().__init__(
            **kwargs,
            room_events=_RoomEventWorkItemAdapter(
                room_events,
                self._work_context,
            ),
            room_dispatch=_RoomDispatchWorkItemAdapter(
                room_dispatch,
                self._work_context,
                room_work=room_work,
                publish_room_work_activity=publish_room_work_activity,
            ),
        )

    def execute(
        self,
        session_id: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        source = self._participant(session_id)
        operation = str(args.get("op") or "list").strip()
        if operation == "accept":
            return self._review(
                source,
                args,
                accept=True,
            )
        if operation == "return":
            return self._review(
                source,
                args,
                accept=False,
            )
        if operation == "resume":
            return self._resume(
                source,
                args,
                tool_call_id=tool_call_id,
            )
        return super().execute(
            session_id,
            args,
            tool_call_id=tool_call_id,
        )

    def _list(self, source: Mapping[str, object]) -> dict[str, object]:
        result = super()._list(source)
        root_id = str(result["rootId"])
        work_items = [
            dict(item)
            for item in self.room_work.list(
                room_id=str(source["roomId"]),
                limit=200,
            )
            if str(item.get("rootTurnId") or "") == root_id
        ]
        result["workItems"] = work_items
        result["pendingReviewCount"] = sum(
            str(item.get("state") or "") == "review"
            for item in work_items
        )
        result["openWorkCount"] = sum(
            str(item.get("state") or "")
            in {"queued", "active", "review", "blocked"}
            for item in work_items
        )
        return result

    def _delegate_batch(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        result = super()._delegate_batch(
            source,
            args,
            tool_call_id=tool_call_id,
        )
        values = [
            item
            for item in result.get("results", [])
            if isinstance(item, Mapping)
        ]
        pending = sum(
            str(item.get("contractStatus") or "") == "pending_review"
            for item in values
        )
        invalid = sum(
            str(item.get("contractStatus") or "") == "invalid"
            for item in values
        )
        result["acceptance"] = {
            "pending": pending,
            "invalid": invalid,
            "accepted": sum(
                str(item.get("contractStatus") or "") == "accepted"
                for item in values
            ),
        }
        result["workflowStatus"] = (
            "invalid"
            if invalid
            else "awaiting_review"
            if pending
            else str(result.get("status") or "completed")
        )
        return result

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
        normalized_phase = _text(
            phase or args.get("phase"),
            maximum=120,
        )
        if not normalized_phase:
            raise ValueError("phase must not be empty")
        target_id = _required_text(
            args,
            "targetParticipantId",
            maximum=240,
        )
        task = _required_text(args, "task", maximum=8_000)
        expected_output = _required_text(
            args,
            "expectedOutput",
            maximum=1_200,
        )
        criteria = _string_list(
            args.get("acceptanceCriteria"),
            limit=8,
            maximum=320,
        )
        if not criteria:
            raise ValueError("acceptanceCriteria must not be empty")
        dependencies = tuple(
            _string_list(
                args.get("dependsOnWorkItemIds"),
                limit=8,
                maximum=240,
            )
        )
        room_id = str(source["roomId"])
        root_id, _parent_dispatch_id = self._active_root(source)
        self._require_dependencies(
            room_id=room_id,
            work_item_ids=dependencies,
        )
        target = self.rooms.participant(target_id)
        if existing_work_item is None:
            assignment_id = f"room-partner:{uuid.uuid5(uuid.NAMESPACE_URL, f'{room_id}:{root_id}:{tool_call_id}')}"
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
                topic_id=str(
                    self.rooms.get(room_id).get("activeTopicId") or ""
                ),
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
                raise ValueError("only returned active Room work may be resumed")
        context = _PartnerWorkContext(
            work=work,
            source=source,
            target=target,
            room_id=room_id,
            root_id=root_id,
            dependencies=dependencies,
            phase=normalized_phase,
        )
        token = self._work_context.set(context)
        try:
            result = super()._delegate(
                source,
                {
                    **dict(args),
                    "targetParticipantId": target_id,
                    "task": task,
                    "expectedOutput": expected_output,
                    "acceptanceCriteria": criteria,
                },
                tool_call_id=tool_call_id,
                priority_reserved=priority_reserved,
                wave_id=wave_id,
                phase=normalized_phase,
                parallel_index=parallel_index,
                parallel_size=parallel_size,
            )
        finally:
            self._work_context.reset(token)
        return self._settle_work_item(
            result,
            work_id=str(work["id"]),
            room_id=room_id,
            target=target,
        )

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
        if str(work.get("state") or "") != "active":
            raise ValueError("Room work must be returned before it can be resumed")
        reviewer_id = str(self.room_work.reviewer_participant_id(work_id))
        if reviewer_id != str(source["id"]):
            raise ValueError("only the accountable reviewer may resume returned work")
        target_id = str(work.get("currentOwnerParticipantId") or "")
        blocker = work.get("blocker")
        feedback = (
            str(blocker.get("reviewFeedback") or "").strip()
            if isinstance(blocker, Mapping)
            else ""
        )
        objective = str(work.get("objective") or "").strip()
        task = objective
        if feedback:
            task = f"{objective}\n\n返修要求：{feedback}"
        return self._delegate(
            source,
            {
                "targetParticipantId": target_id,
                "task": task,
                "expectedOutput": str(work.get("expectedOutput") or ""),
                "acceptanceCriteria": list(
                    work.get("acceptanceCriteria") or []
                ),
                "phase": _required_text(args, "phase", maximum=120),
                "timeoutSeconds": _integer(
                    args.get("timeoutSeconds"),
                    default=180,
                    minimum=5,
                    maximum=300,
                ),
            },
            tool_call_id=tool_call_id,
            existing_work_item=work,
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
        current = self.room_work.get(work_id, room_id=room_id)
        root_id, _dispatch_id = self._active_root(source)
        if str(current.get("rootTurnId") or "") != root_id:
            raise ValueError("workItemId does not belong to the active Room turn")
        if accept:
            work = self.room_work.accept(
                str(source["sessionId"]),
                {"workId": work_id},
            )
            phase = "completed"
            operation = "accept"
            contract_status = "accepted"
        else:
            reason = _required_text(args, "reason", maximum=2_000)
            work = self.room_work.return_for_revision(
                str(source["sessionId"]),
                {"workId": work_id, "reason": reason},
            )
            phase = "returned"
            operation = "return"
            contract_status = "revision_required"
        self.publish_room_work_activity(
            work,
            phase=phase,
            actor=source,
        )
        return {
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": operation,
            "roomId": room_id,
            "rootId": root_id,
            "workItemId": work_id,
            "workItem": dict(work),
            "contractStatus": contract_status,
        }

    def _post(
        self,
        source: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        kind = _text(args.get("kind"), maximum=40) or "progress"
        if kind == "result":
            room = self.rooms.get(str(source["roomId"]))
            if str(room.get("moderatorParticipantId") or "") != str(source["id"]):
                raise ValueError("only the Room Root may publish the final result")
            root_id, _dispatch_id = self._active_root(source)
            open_work = [
                item
                for item in self.room_work.list(
                    room_id=str(source["roomId"]),
                    limit=200,
                )
                if str(item.get("rootTurnId") or "") == root_id
                and str(item.get("state") or "")
                in {"queued", "active", "review", "blocked"}
            ]
            if open_work:
                states = ", ".join(
                    f"{item['id']}={item['state']}"
                    for item in open_work[:8]
                )
                raise ValueError(
                    "Root final result is blocked until all formal WorkItems "
                    f"are accepted or explicitly failed: {states}"
                )
        return super()._post(
            source,
            args,
            tool_call_id=tool_call_id,
        )

    def _require_dependencies(
        self,
        *,
        room_id: str,
        work_item_ids: tuple[str, ...],
    ) -> None:
        pending: list[str] = []
        for work_id in work_item_ids:
            work = self.room_work.get(work_id, room_id=room_id)
            if str(work.get("state") or "") != "done":
                pending.append(f"{work_id}={work.get('state') or 'unknown'}")
        if pending:
            raise ValueError(
                "Room phase dependencies are not accepted: "
                + ", ".join(pending)
            )

    def _settle_work_item(
        self,
        result: dict[str, object],
        *,
        work_id: str,
        room_id: str,
        target: Mapping[str, object],
    ) -> dict[str, object]:
        work = dict(self.room_work.get(work_id, room_id=room_id))
        state = str(work.get("state") or "")
        if state in {"review", "done", "failed", "cancelled"}:
            return self._attach_contract(result, work)
        status = str(result.get("status") or "failed")
        text = str(result.get("result") or "").strip()
        if status == "completed" and text:
            try:
                work = dict(
                    self.room_work.submit(
                        str(target["sessionId"]),
                        {
                            "workId": work_id,
                            "resultSummary": text[:4_000],
                            "evidenceRefs": [
                                f"room-dispatch:{result.get('childDispatchId') or ''}",
                                f"room-session:{target['sessionId']}",
                            ],
                        },
                    )
                )
                self.publish_room_work_activity(
                    work,
                    phase="submitted",
                    actor=target,
                )
                return self._attach_contract(result, work)
            except Exception as exc:
                result["contractStatus"] = "invalid"
                result["contractError"] = " ".join(str(exc).split())[:500]
                result["workItemId"] = work_id
                result["workItem"] = work
                result["requiresAcceptance"] = False
                self.publish_room_work_activity(
                    work,
                    phase="submission_invalid",
                    actor=target,
                )
                return result
        reason = (
            "Partner Session returned without a public result"
            if status == "completed"
            else f"Partner Session ended with status {status}"
        )
        try:
            work = dict(
                self.room_work.escalate(
                    str(target["sessionId"]),
                    {
                        "workId": work_id,
                        "reason": reason,
                        "nextStep": (
                            "repair the node explicitly, return it for revision, "
                            "or reassign it; do not auto-accept the result"
                        ),
                    },
                )
            )
            self.publish_room_work_activity(
                work,
                phase="escalated",
                actor=target,
            )
        except Exception as exc:
            result["contractError"] = " ".join(str(exc).split())[:500]
        result["contractStatus"] = "invalid"
        return self._attach_contract(result, work)

    @staticmethod
    def _attach_contract(
        result: dict[str, object],
        work: Mapping[str, object],
    ) -> dict[str, object]:
        state = str(work.get("state") or "")
        result["workItemId"] = str(work["id"])
        result["workItem"] = dict(work)
        if state == "review":
            result["contractStatus"] = "pending_review"
            result["requiresAcceptance"] = True
        elif state == "done":
            result["contractStatus"] = "accepted"
            result["requiresAcceptance"] = False
        elif state == "active":
            result.setdefault("contractStatus", "revision_required")
            result["requiresAcceptance"] = False
        elif state in {"failed", "cancelled"}:
            result["contractStatus"] = "invalid"
            result["requiresAcceptance"] = False
        else:
            result.setdefault("contractStatus", "pending")
            result["requiresAcceptance"] = False
        return result
