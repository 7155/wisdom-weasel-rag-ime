from __future__ import annotations

import uuid

from .agent_room_kernel import kernel_owns_room_execution
from .agent_room_turn_registry import (
    RoomSessionBusyError,
    RoomTurnRegistry,
)
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol


ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT = 12


class LegacyRoomHost(Protocol):
    rooms: Any
    personas: Any
    role_books: Any
    room_work: Any
    room_events: Any
    room_kernel: Any
    room_application: Any
    room_turns: RoomTurnRegistry
    _context_source_token: object

    def _restore_legacy_room_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> None: ...

    def _ensure_session_role_book(
        self,
        session_id: str,
    ) -> Mapping[str, object]: ...

    def _guard_legacy_room_route(
        self,
        route: str,
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


class RoomLegacyDispatchService:
    """Dispatch ordinary Room conversation through participant Sessions.

    Managed work remains Kernel-only. The same Session-backed path is retained
    for pre-Kernel installations so conversation mirroring has one owner.
    """

    def __init__(
        self,
        host: LegacyRoomHost,
        *,
        build_participant_prompt: Callable[..., str],
    ) -> None:
        self.host = host
        self.build_participant_prompt = build_participant_prompt

    def post_message(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
    ) -> dict[str, object]:
        route_id = (
            "room.message.execute"
            if str(work_item_id or "").strip()
            else "room.message.conversation"
        )
        if kernel_owns_room_execution(self.host.room_kernel.mode):
            return self.host.room_application.post_message(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
            )
        return self._post_session_messages(
            room_id,
            message=message,
            client_message_id=client_message_id,
            requested_participant_ids=requested_participant_ids,
            work_item_id=work_item_id,
            guard_legacy_route=True,
            route_id=route_id,
        )

    def post_conversation(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
    ) -> dict[str, object]:
        """Route an unbound Room conversation through ordinary Agent Sessions."""

        return self._post_session_messages(
            room_id,
            message=message,
            client_message_id=client_message_id,
            requested_participant_ids=requested_participant_ids,
            work_item_id="",
            guard_legacy_route=False,
            route_id="room.message.conversation",
        )

    def _post_session_messages(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        guard_legacy_route: bool,
        route_id: str,
    ) -> dict[str, object]:
        room = self.host.rooms.get(room_id)
        self.host._restore_legacy_room_participant_sessions(room)
        work_item: dict[str, object] | None = None
        authoritative_participant_id = ""
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
            role = self.host.personas.resolve(value.get("roleId"), value.get("roleVersion") or "1")
            session = self.host._ensure_session_role_book(str(value["sessionId"]))
            try:
                role_book_profile = self.host.role_books.routing_profile(
                    role.role_id,
                    role.version,
                    str(session.get("roleBookRevisionId") or ""),
                )
            except (ValueError, RuntimeError):
                role_book_profile = {}
            capability_texts = _role_book_profile_texts(
                role_book_profile.get("capabilities")
            )
            recent_work_texts = _role_book_profile_texts(
                role_book_profile.get("recentWork")
            )
            profiles[str(value["id"])] = {
                "tagline": role.tagline,
                "summary": " ".join(
                    [role.summary, *capability_texts[:4], *recent_work_texts[:3]]
                ),
                "traits": list(role.traits),
                "routingTags": [
                    *role.traits,
                    *capability_texts[:8],
                    *recent_work_texts[:4],
                ],
                "roleBookRevisionId": str(
                    role_book_profile.get("revisionId") or ""
                ),
            }
        decisions = self.host.rooms.plan_routes(
            room_id,
            message,
            requested_participant_ids=requested_participant_ids,
            profiles=profiles,
            authoritative_participant_id=authoritative_participant_id,
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
        if len(set(target_session_ids)) != len(target_session_ids):
            raise RuntimeError("Room routing produced duplicate participant Sessions")
        if guard_legacy_route:
            for session_id in target_session_ids:
                self.host._guard_legacy_room_route(
                    route_id,
                    session_id,
                )

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
            if work_item_id:
                user_event_payload["workItemId"] = work_item_id
            user_room_event = self.host.room_events.publish(
                room_id=room_id,
                event_type="user_message",
                payload=user_event_payload,
                turn_id=room_turn_id,
                topic_id=topic_id,
            )
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
                self.host.room_events.publish(
                    room_id=room_id,
                    event_type="route_decision",
                    payload=decision,
                    turn_id=room_turn_id,
                    participant_id=str(target["id"]),
                    source_session_id=str(target["sessionId"]),
                    topic_id=topic_id,
                )
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
        if work_claimed and work_item is not None and not successful:
            try:
                work_item = self.host.room_work.fail_dispatch(
                    str(work_item["id"]),
                    room_id=room_id,
                    actor_participant_id=str(targets[0]["id"]),
                    room_turn_id=room_turn_id,
                    previous_accepted_turn_id=previous_accepted_turn_id,
                    reason="Room runtime rejected the assigned dispatch",
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
            "status": "accepted" if successful else "rejected",
            "executionOwner": (
                "session" if work_item is None else "legacy_work_item"
            ),
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
            "participant": targets[primary_index],
            "participants": targets,
            "routeDecision": decisions[primary_index],
            "routeDecisions": decisions,
            "dispatches": dispatch_results,
            "topicId": topic_id,
            "sessionTurnId": primary_result.get("sessionTurnId", ""),
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
                    "_contextSourceToken": self.host._context_source_token,
                    "_contextSource": "room",
                    "_checkpointText": message,
                    "_transientContext": room_turn_context,
                },
            )
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
                "sessionTurnId": session_turn_id,
                "error": "",
            }
        except Exception as exc:
            self.host._cancel_room_turn(session_id, room_turn_id)
            self.host.room_events.publish(
                room_id=str(room["id"]),
                event_type="turn_failed",
                payload={
                    "rootId": room_turn_id,
                    "dispatchId": dispatch_id,
                    "error": _public_error(exc),
                },
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
                "sessionTurnId": "",
                "error": _public_error(exc),
                "_exception": exc,
            }
        finally:
            self.host.room_turns.release_priority_session(session_id)

def _role_book_profile_texts(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        text = " ".join(str(item.get("text") or "").split())[:280]
        if text and text not in result:
            result.append(text)
    return result


def _public_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:240] or error.__class__.__name__
