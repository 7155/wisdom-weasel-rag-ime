from __future__ import annotations

import uuid
from .agent_room_turn_registry import (
    RoomSessionBusyError,
    RoomTurnRegistry,
)
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol


ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT = 12


class RoomSessionHost(Protocol):
    rooms: Any
    room_work: Any
    room_events: Any
    room_turns: RoomTurnRegistry
    _context_source_token: object

    def _restore_room_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> None: ...

    def _guard_room_session_route(
        self,
        route: str,
        session_id: str,
    ) -> None: ...

    def _recover_faulted_room_session(
        self,
        session_id: str,
    ) -> None: ...

    def _resume_room_goal_if_paused(
        self,
        session_id: str,
    ) -> None: ...

    def _room_target_idle(
        self,
        session_id: str,
        *,
        allow_user_priority: bool = False,
    ) -> bool: ...

    def _record_room_evidence_safely(self, **kwargs: object) -> object: ...
    def _begin_room_turn(self, *args: object, **kwargs: object) -> None: ...
    def _accept_room_turn(self, *args: object, **kwargs: object) -> None: ...
    def _cancel_room_turn(self, *args: object, **kwargs: object) -> None: ...
    def prompt(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]: ...


class RoomSessionDispatchService:
    """Dispatch every Room request through ordinary participant Pi Sessions.

    Room contributes routing and bounded context. Pi remains the sole owner of
    turns, tools, Steer, Stop and compaction.
    """

    def __init__(
        self,
        host: RoomSessionHost,
        *,
        build_participant_prompt: Callable[..., str],
        resolve_attachments: Callable[
            [str, Sequence[str], Sequence[str]], list[dict[str, object]]
        ],
    ) -> None:
        self.host = host
        self.build_participant_prompt = build_participant_prompt
        self.resolve_attachments = resolve_attachments

    def post_message(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        retry_of_root_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        route_id = (
            "room.message.execute"
            if str(work_item_id or "").strip()
            else "room.message.conversation"
        )
        return self._post_session_messages(
            room_id,
            message=message,
            client_message_id=client_message_id,
            retry_of_root_id=retry_of_root_id,
            requested_participant_ids=requested_participant_ids,
            work_item_id=work_item_id,
            attachment_ids=attachment_ids,
            route_id=route_id,
        )

    def _post_session_messages(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        retry_of_root_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str],
        route_id: str,
    ) -> dict[str, object]:
        room = self.host.rooms.get(room_id)
        self.host._restore_room_participant_sessions(room)
        work_item: dict[str, object] | None = None
        authoritative_participant_id = ""
        if retry_of_root_id and not str(work_item_id or "").strip():
            returned_candidates: list[Mapping[str, object]] = []
            for candidate in self.host.room_work.list(
                room_id=room_id,
                states=("active",),
                limit=200,
            ):
                if (
                    not isinstance(candidate, Mapping)
                    or str(candidate.get("rootTurnId") or "")
                    != retry_of_root_id
                ):
                    continue
                blocker = candidate.get("blocker")
                review = candidate.get("review")
                has_return_feedback = (
                    isinstance(blocker, Mapping)
                    and bool(str(blocker.get("reviewFeedback") or "").strip())
                ) or (
                    isinstance(review, Mapping)
                    and bool(str(review.get("reason") or "").strip())
                )
                if has_return_feedback:
                    returned_candidates.append(candidate)
            if len(returned_candidates) > 1:
                raise ValueError(
                    "retryOfRootId matches multiple returned WorkItems; "
                    "provide workItemId"
                )
            if returned_candidates:
                work_item_id = str(returned_candidates[0].get("id") or "")
                route_id = "room.message.execute"
        if work_item_id:
            work_item, authoritative_participant_id = (
                self.host.room_work.authoritative_owner(
                    work_item_id,
                    room_id=room_id,
                )
            )
        profiles: dict[str, dict[str, object]] = {}
        for value in room["participants"]:
            if not isinstance(value, Mapping):
                continue
            if str(value.get("status") or "") != "active":
                continue
            # Room routing consumes only explicit mentions, collaboration
            # responsibility and WorkItem ownership. Persona/Role Book is an
            # optional Package and must not be loaded by the core Room path.
            profiles[str(value["id"])] = {
                "tagline": "",
                "summary": "",
                "traits": [],
                "routingTags": [],
                "roleBookRevisionId": "",
            }
        decisions = self.host.rooms.plan_routes(
            room_id,
            message,
            requested_participant_ids=requested_participant_ids,
            profiles=profiles,
            authoritative_participant_id=authoritative_participant_id,
            # A Room is one lead Session with optional child/partner Sessions,
            # not an automatic broadcast.  Explicit @mentions can still fan
            # out; an unaddressed request always starts one lead turn.
            conversation_only=work_item is None,
        )
        if work_item is not None:
            for decision in decisions:
                decision["workItemId"] = work_item_id
                decision["workItemState"] = str(work_item["state"])

        targets = [
            self.host.rooms.participant(str(decision["targetParticipantId"]))
            for decision in decisions
        ]
        target_session_ids = [str(target["sessionId"]) for target in targets]
        if retry_of_root_id:
            for session_id in target_session_ids:
                self.host._recover_faulted_room_session(session_id)
        attachment_receipts = self.resolve_attachments(
            room_id,
            target_session_ids,
            attachment_ids,
        )
        if len(set(target_session_ids)) != len(target_session_ids):
            raise RuntimeError("Room routing produced duplicate participant Sessions")
        for session_id in target_session_ids:
            self.host._guard_room_session_route(
                route_id,
                session_id,
            )
        # The explicit user message carries the resume intent for a paused
        # target Goal. This runs before the Root and user event become
        # durable; wake, partner and Tool Agent dispatches never reach here.
        for session_id in target_session_ids:
            self.host._resume_room_goal_if_paused(session_id)

        target_by_session_id = {
            session_id: target
            for target, session_id in zip(targets, target_session_ids, strict=True)
        }

        def _ensure_participant_active(session_id: str) -> None:
            target = target_by_session_id[session_id]
            latest_target = self.host.rooms.participant(str(target["id"]))
            if str(latest_target.get("status") or "") != "active":
                raise ValueError("selected Room participant is no longer active")

        try:
            # ensure_available runs inside the registry lock, so the
            # participant re-check and the priority reservation remain the
            # single critical section they were as inline code.
            self.host.room_turns.hold_priority_if_idle(
                target_session_ids,
                ensure_available=_ensure_participant_active,
            )
        except RoomSessionBusyError as busy:
            target = target_by_session_id[busy.session_id]
            raise ValueError(
                f"{target.get('displayName') or 'selected Room participant'} "
                "is currently busy"
            ) from None
        busy_targets = [
            target
            for target, session_id in zip(targets, target_session_ids, strict=True)
            if not self.host._room_target_idle(session_id, allow_user_priority=True)
        ]
        if busy_targets:
            self.host.room_turns.release_priority(target_session_ids)
            names = "、".join(str(item.get("displayName") or "Agent") for item in busy_targets)
            raise ValueError(f"Room participants are currently busy: {names}")

        room_turn_id = f"room-turn:{uuid.uuid4()}"
        topic_id = str(room.get("activeTopicId") or "")
        for decision, target in zip(decisions, targets, strict=True):
            decision["rootId"] = room_turn_id
            decision["dispatchId"] = f"room-dispatch:{uuid.uuid4()}"
            decision["targetSessionId"] = str(target["sessionId"])
        try:
            user_event_payload: dict[str, object] = {
                "text": message,
                "targetParticipantIds": [
                    str(decision["targetParticipantId"]) for decision in decisions
                ],
                "dispatches": [
                    {
                        "dispatchId": str(decision["dispatchId"]),
                        "participantId": str(decision["targetParticipantId"]),
                    }
                    for decision in decisions
                ],
            }
            if client_message_id:
                user_event_payload["clientMessageId"] = client_message_id
            if retry_of_root_id:
                user_event_payload["retryOfRootId"] = retry_of_root_id
            if work_item_id:
                user_event_payload["workItemId"] = work_item_id
            if attachment_receipts:
                user_event_payload["attachmentReceipts"] = attachment_receipts
            user_room_event = self.host.room_events.publish(
                room_id=room_id,
                event_type="user_message",
                payload=user_event_payload,
                turn_id=room_turn_id,
                topic_id=topic_id,
            )
            timeline_events = [user_room_event]
            self.host._record_room_evidence_safely(
                room_id=room_id,
                room_event=user_room_event,
                text=message,
                role_id=str(targets[0].get("roleId") or ""),
                session_id=target_session_ids[0],
                event_type="user_message",
                accepted=False,
            )
            for decision, target in zip(decisions, targets, strict=True):
                route_room_event = self.host.room_events.publish(
                    room_id=room_id,
                    event_type="route_decision",
                    payload=decision,
                    turn_id=room_turn_id,
                    participant_id=str(target["id"]),
                    source_session_id=str(target["sessionId"]),
                    topic_id=topic_id,
                )
                timeline_events.append(route_room_event)
                self.host._begin_room_turn(
                    str(target["sessionId"]),
                    room_turn_id,
                    topic_id,
                    dispatch_id=str(decision["dispatchId"]),
                )
            unread_by_participant = {
                str(target["id"]): self.host.rooms.unread_public_messages(
                    room_id,
                    str(target["id"]),
                    topic_id=topic_id,
                    exclude_turn_id=room_turn_id,
                    limit=ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT,
                )
                for target in targets
            }
        except Exception:
            for session_id in target_session_ids:
                self.host._cancel_room_turn(session_id, room_turn_id)
            self.host.room_turns.release_priority(target_session_ids)
            raise

        work_claimed = False
        previous_accepted_turn_id = ""
        retry_dispatch_id = ""
        try:
            if work_item is not None:
                previous_accepted_turn_id = str(
                    work_item.get("acceptedTurnId") or ""
                )
                work_item = self.host.room_work.claim_dispatch(
                    str(work_item["id"]),
                    room_id=room_id,
                    owner_participant_id=str(targets[0]["id"]),
                    assignment_key=str(work_item["assignmentKey"]),
                    previous_accepted_turn_id=previous_accepted_turn_id,
                    room_turn_id=room_turn_id,
                )
                work_claimed = True
                # A retry submitted from the Room UI still represents the
                # same governed Partner WorkItem.  Register its ordinary Room
                # dispatch in the existing durable Partner ledger so a typed
                # work_result can settle to review and wake the accountable
                # Facilitator exactly like a tool-originated retry.
                retry_dispatch_id = str(decisions[0]["dispatchId"])
                accountable = self.host.rooms.participant(
                    str(work_item["accountableParticipantId"])
                )
                self.host.room_partner_dispatches.register(
                    child_dispatch_id=retry_dispatch_id,
                    room_id=room_id,
                    root_id=room_turn_id,
                    parent_dispatch_id=f"room-user-retry:{room_turn_id}",
                    tool_call_id=client_message_id or room_turn_id,
                    source_participant_id=str(accountable["id"]),
                    source_session_id=str(accountable["sessionId"]),
                    target_participant_id=str(targets[0]["id"]),
                    target_session_id=str(targets[0]["sessionId"]),
                    work_item_id=str(work_item["id"]),
                )
        except Exception as exc:
            for decision, target in zip(decisions, targets, strict=True):
                self.host._cancel_room_turn(str(target["sessionId"]), room_turn_id)
                self.host.room_events.publish(
                    room_id=room_id,
                    event_type="turn_failed",
                    payload={
                        "rootId": room_turn_id,
                        "dispatchId": decision["dispatchId"],
                        "error": _public_error(exc),
                    },
                    turn_id=room_turn_id,
                    participant_id=str(target["id"]),
                    source_session_id=str(target["sessionId"]),
                    topic_id=topic_id,
                )
            self.host.room_turns.release_priority(target_session_ids)
            # The compatibility path historically failed synchronously when the
            # authoritative WorkItem changed between route planning and claim.
            # Do not turn that concurrency fence into a superficially successful
            # `accepted=false` response: callers must retry against the new owner.
            raise

        dispatch_results: list[dict[str, object]] = []
        with ThreadPoolExecutor(
            max_workers=len(targets),
            thread_name_prefix="room-user-dispatch",
        ) as executor:
            futures = {
                executor.submit(
                    self.host._dispatch_room_target,
                    room=room,
                    target=target,
                    decision=decision,
                    message=message,
                    room_turn_id=room_turn_id,
                    topic_id=topic_id,
                    unread=unread_by_participant[str(target["id"])],
                    work_item=work_item,
                    attachment_ids=attachment_ids,
                ): index
                for index, (decision, target) in enumerate(
                    zip(decisions, targets, strict=True)
                )
            }
            indexed_results: dict[int, dict[str, object]] = {}
            for future in as_completed(futures):
                indexed_results[futures[future]] = future.result()
            dispatch_results = [
                indexed_results[index] for index in range(len(indexed_results))
            ]

        successful = [result for result in dispatch_results if result["accepted"] is True]
        if retry_dispatch_id and successful:
            self.host.room_partner_dispatches.mark_dispatched(
                retry_dispatch_id,
                target_session_turn_id=str(
                    successful[0].get("sessionTurnId") or ""
                ),
            )
        cancelled_only = bool(dispatch_results) and all(
            result.get("status") == "cancelled" for result in dispatch_results
        )
        if work_claimed and work_item is not None and not successful:
            try:
                work_item = self.host.room_work.fail_dispatch(
                    str(work_item["id"]),
                    room_id=room_id,
                    actor_participant_id=str(targets[0]["id"]),
                    room_turn_id=room_turn_id,
                    previous_accepted_turn_id=previous_accepted_turn_id,
                    reason=(
                        "Room dispatch was cancelled before Runtime admission"
                        if cancelled_only
                        else "Room Runtime rejected the assigned dispatch"
                    ),
                )
            except Exception:
                pass
        if not successful:
            first_error = next(
                (
                    result.get("_exception")
                    for result in dispatch_results
                    if isinstance(result.get("_exception"), BaseException)
                ),
                None,
            )
            if isinstance(first_error, BaseException):
                raise first_error
        for result in dispatch_results:
            result.pop("_exception", None)

        primary_result = successful[0] if successful else dispatch_results[0]
        primary_index = dispatch_results.index(primary_result)
        response: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": bool(successful),
            "status": (
                "accepted"
                if successful
                else "cancelled"
                if cancelled_only
                else "rejected"
            ),
            "cancelled": cancelled_only,
            "executionOwner": "session",
            "phase": (
                "alignment"
                if work_item is None
                and str(room.get("roomKind") or "collaboration")
                == "collaboration"
                else "conversation"
                if work_item is None
                else "execution"
            ),
            "roomId": room_id,
            "roomTurnId": room_turn_id,
            "clientMessageId": client_message_id,
            "retryOfRootId": retry_of_root_id,
            "participant": targets[primary_index],
            "participants": targets,
            "routeDecision": decisions[primary_index],
            "routeDecisions": decisions,
            "dispatches": dispatch_results,
            "topicId": topic_id,
            "sessionTurnId": primary_result.get("sessionTurnId", ""),
            "timelineEvents": timeline_events,
        }
        if work_item is not None:
            response["workItem"] = work_item
        return response

    def dispatch_target(
        self,
        *,
        room: Mapping[str, object],
        target: Mapping[str, object],
        decision: Mapping[str, object],
        message: str,
        room_turn_id: str,
        topic_id: str,
        unread: Mapping[str, object],
        work_item: Mapping[str, object] | None,
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        session_id = str(target["sessionId"])
        participant_id = str(target["id"])
        dispatch_id = str(decision["dispatchId"])
        try:
            room_turn_context = self.build_participant_prompt(
                room,
                target,
                "",
                recent_messages=[
                    item
                    for item in unread["items"]
                    if isinstance(item, Mapping)
                ],
                omitted_message_count=int(unread["omittedCount"]),
                work_item=work_item,
            )
            accepted = self.host.prompt(
                session_id,
                {
                    "message": message,
                    "clientMessageId": dispatch_id,
                    "_contextSourceToken": self.host._context_source_token,
                    "_contextSource": "room",
                    "_checkpointText": message,
                    "_transientContext": room_turn_context,
                    "attachments": list(attachment_ids),
                    "_mediaOwnerRoomId": str(room["id"]),
                },
            )
            if accepted.get("accepted") is False:
                cancelled = (
                    accepted.get("cancelled") is True
                    or accepted.get("admissionCancelled") is True
                )
                receipt_error = " ".join(
                    str(accepted.get("error") or "").split()
                )[:240]
                error = receipt_error or (
                    "Pi Runtime cancelled the Room dispatch before admission"
                    if cancelled
                    else "Pi Runtime rejected the Room dispatch"
                )
                self.host._cancel_room_turn(session_id, room_turn_id)
                child = decision.get("child") is True
                self.host.room_events.publish(
                    room_id=str(room["id"]),
                    event_type=(
                        "participant_activity" if child else "turn_failed"
                    ),
                    payload=(
                        {
                            "activityKind": "child",
                            "phase": "aborted" if cancelled else "failed",
                            "status": (
                                "dispatch_cancelled"
                                if cancelled
                                else "dispatch_rejected"
                            ),
                            "rootId": room_turn_id,
                            "childDispatchId": dispatch_id,
                            "dispatchId": dispatch_id,
                            "parentDispatchId": str(
                                decision.get("parentDispatchId") or ""
                            ),
                            "error": error,
                        }
                        if child
                        else {
                            "rootId": room_turn_id,
                            "dispatchId": dispatch_id,
                            "status": (
                                "dispatch_cancelled"
                                if cancelled
                                else "dispatch_rejected"
                            ),
                            "cancelled": cancelled,
                            "error": error,
                        }
                    ),
                    turn_id=room_turn_id,
                    participant_id=participant_id,
                    source_session_id=session_id,
                    topic_id=topic_id,
                )
                return {
                    "participantId": participant_id,
                    "sessionId": session_id,
                    "dispatchId": dispatch_id,
                    "accepted": False,
                    "cancelled": cancelled,
                    "admissionCancelled": (
                        accepted.get("admissionCancelled") is True
                    ),
                    "status": "cancelled" if cancelled else "rejected",
                    "sessionTurnId": "",
                    "error": error,
                }
            session_turn_id = str(accepted.get("turnId") or "")
            if not session_turn_id:
                raise RuntimeError("Pi Runtime accepted a Room dispatch without a turnId")
            self.host._accept_room_turn(
                session_id,
                session_turn_id,
                room_turn_id,
            )
            self.host.rooms.advance_delivery_cursor(
                str(room["id"]),
                participant_id,
                topic_id=topic_id,
                through_sequence=int(unread["throughSequence"]),
            )
            self.host.rooms.commit_route(str(room["id"]), decision)
            return {
                "participantId": participant_id,
                "sessionId": session_id,
                "dispatchId": dispatch_id,
                "accepted": True,
                "cancelled": False,
                "status": "accepted",
                "sessionTurnId": session_turn_id,
                "error": "",
            }
        except Exception as exc:
            self.host._cancel_room_turn(session_id, room_turn_id)
            child = decision.get("child") is True
            cause_code = _error_cause_code(exc)
            self.host.room_events.publish(
                room_id=str(room["id"]),
                event_type=(
                    "participant_activity" if child else "turn_failed"
                ),
                payload=(
                    {
                        "activityKind": "child",
                        "phase": "failed",
                        "status": "dispatch_failed",
                        "rootId": room_turn_id,
                        "childDispatchId": dispatch_id,
                        "dispatchId": dispatch_id,
                        "parentDispatchId": str(
                            decision.get("parentDispatchId") or ""
                        ),
                        "error": _public_error(exc),
                        **({"causeCode": cause_code} if cause_code else {}),
                    }
                    if child
                    else {
                        "rootId": room_turn_id,
                        "dispatchId": dispatch_id,
                        "error": _public_error(exc),
                        **({"causeCode": cause_code} if cause_code else {}),
                    }
                ),
                turn_id=room_turn_id,
                participant_id=participant_id,
                source_session_id=session_id,
                topic_id=topic_id,
            )
            return {
                "participantId": participant_id,
                "sessionId": session_id,
                "dispatchId": dispatch_id,
                "accepted": False,
                "cancelled": False,
                "status": "failed",
                "sessionTurnId": "",
                "error": _public_error(exc),
                "_exception": exc,
            }
        finally:
            self.host.room_turns.release_priority_session(session_id)

def _public_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:240] or error.__class__.__name__


def _error_cause_code(error: BaseException) -> str:
    """Project a durable Room causeCode.

    Session receipts keep the canonical lowercase ``error_code``
    (``goal_paused``). Room timeline events uppercase the same token so they
    match existing wake/partner cause comparisons.
    """

    return " ".join(
        str(
            getattr(error, "cause_code", "")
            or getattr(error, "error_code", "")
            or ""
        ).split()
    ).upper()[:80]
