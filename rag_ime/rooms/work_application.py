from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import SupportsInt, SupportsIndex

from rag_ime.rooms.intercom import AgentRoomIntercomRouter
from rag_ime.rooms.work import AgentRoomWorkStore
from rag_ime.rooms.store import AgentRoomEventHub, AgentRoomStore


class RoomWorkApplicationService:
    """Room responsibility, handoff, review, and intercom commands."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        room_work: AgentRoomWorkStore,
        room_intercom: AgentRoomIntercomRouter,
        room_events: AgentRoomEventHub,
        guard_session_route: Callable[[str, str], None],
    ) -> None:
        self.rooms = rooms
        self.room_work = room_work
        self.room_intercom = room_intercom
        self.room_events = room_events
        self._guard_session_route = guard_session_route

    def room_work_items(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.rooms.get(room_id)
        values = payload or {}
        raw_states = values.get("states")
        if raw_states is None:
            single_state = str(values.get("state") or "").strip()
            states: list[str] = [single_state] if single_state else []
        elif isinstance(raw_states, list):
            states = [
                str(value or "").strip()
                for value in raw_states
                if str(value or "").strip()
            ]
        else:
            raise ValueError("states must be an array")
        items = self.room_work.list(
            room_id=room_id,
            states=states,
            owner_participant_id=str(
                values.get("ownerParticipantId") or ""
            ),
            limit=_integer(
                values.get("limit"),
                default=100,
                minimum=1,
                maximum=200,
            ),
        )
        return {
            "schemaVersion": "rag-ime.agent-room-work-item-list.v1",
            "ok": True,
            "roomId": room_id,
            "items": items,
        }

    def room_work_item(
        self,
        room_id: str,
        work_item_id: str,
    ) -> dict[str, object]:
        self.rooms.get(room_id)
        work_item = self.room_work.get(work_item_id, room_id=room_id)
        return {
            "schemaVersion": "rag-ime.agent-room-work-item-get.v1",
            "ok": True,
            "roomId": room_id,
            "workItem": work_item,
            "events": self.room_work.list_events(work_item_id),
        }

    def create_room_work_item(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        if str(room.get("status") or "") != "active":
            raise ValueError("agent room is archived")
        if str(room.get("roomKind") or "collaboration") != "collaboration":
            raise ValueError("roleplay Rooms cannot create managed work")
        owner_id = _required_text(payload, "currentOwnerParticipantId")
        creator_id = (
            _bounded_text(
                payload.get("createdByParticipantId"),
                maximum=320,
            )
            or owner_id
        )
        raw_criteria = payload.get("acceptanceCriteria")
        if raw_criteria is None:
            criteria: list[object] = []
        elif isinstance(raw_criteria, list):
            criteria = list(raw_criteria)
        else:
            raise ValueError("acceptanceCriteria must be an array")
        work_item = self.room_work.create(
            room_id=room_id,
            objective=_bounded_text(
                payload.get("objective"),
                maximum=8_000,
            ),
            expected_output=_bounded_text(
                payload.get("expectedOutput"),
                maximum=8_000,
            ),
            current_owner_participant_id=owner_id,
            created_by_participant_id=creator_id,
            client_message_id=_required_text(payload, "clientMessageId"),
            accountable_participant_id=_bounded_text(
                payload.get("accountableParticipantId"),
                maximum=320,
            ),
            topic_id=_bounded_text(
                payload.get("topicId") or room.get("activeTopicId"),
                maximum=320,
            ),
            root_turn_id=_bounded_text(
                payload.get("rootTurnId"),
                maximum=320,
            ),
            parent_work_id=_bounded_text(
                payload.get("parentWorkId"),
                maximum=320,
            ),
            acceptance_criteria=criteria,
            state=str(payload.get("state") or "active"),
            depth=_integer(
                payload.get("depth"),
                default=1,
                minimum=1,
                maximum=3,
            ),
        )
        return {
            "schemaVersion": "rag-ime.agent-room-work-item-create.v1",
            "ok": True,
            "roomId": room_id,
            "workItem": work_item,
        }

    def reassign_room_work_item(
        self,
        room_id: str,
        work_item_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        if str(room.get("status") or "") != "active":
            raise ValueError("agent room is archived")
        self.room_work.get(work_item_id, room_id=room_id)
        target_id = _bounded_text(
            payload.get("targetParticipantId")
            or payload.get("currentOwnerParticipantId"),
            maximum=320,
        )
        if not target_id:
            raise ValueError("targetParticipantId must not be empty")
        work_item = self.room_work.reassign(
            work_item_id,
            actor_participant_id=_required_text(
                payload,
                "actorParticipantId",
            ),
            current_owner_participant_id=target_id,
            reason=_bounded_text(payload.get("reason"), maximum=500),
        )
        return {
            "schemaVersion": "rag-ime.agent-room-work-item-reassign.v1",
            "ok": True,
            "roomId": room_id,
            "workItem": work_item,
        }

    def send_room_intercom(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        item = self._enqueue_room_intercom(source_session_id, payload)
        return {
            "schemaVersion": "rag-ime.agent-room-intercom-enqueue.v1",
            "ok": True,
            "accepted": True,
            "message": item,
        }

    def list_room_intercom(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        participant = self.rooms.participant_for_session(session_id, active_only=True)
        if participant is None:
            raise ValueError("session is not a room participant")
        return {
            "schemaVersion": "rag-ime.agent-room-intercom-list.v1",
            "ok": True,
            "sessionId": session_id,
            "participant": participant,
            "room": self.rooms.get(str(participant["roomId"])),
            "items": self.room_intercom.list(
                session_id,
                status=str(value.get("status") or ""),
                limit=_integer(value.get("limit"), default=100, minimum=1, maximum=200),
            ),
        }

    def assign_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.assign", session_id)
        participant = self.rooms.participant_for_session(session_id)
        if participant is None:
            raise ValueError("session is not an active Room participant")
        room = self.rooms.get(str(participant["roomId"]))
        work, created = self.room_work.assign(
            session_id,
            payload,
            root_turn_id=self.rooms.latest_turn_for_participant(
                str(participant["roomId"]),
                str(participant["id"]),
            ),
            topic_id=str(room.get("activeTopicId") or ""),
        )
        delivery: Mapping[str, object] | None = None
        if created:
            self._publish_room_work_activity(
                work,
                phase="assigned",
                actor=participant,
            )
        if str(work.get("state") or "") == "queued":
            raw_criteria = work.get("acceptanceCriteria", [])
            assert isinstance(raw_criteria, list)
            criteria = "\n".join(
                f"- {_bounded_text(value, maximum=240)}"
                for value in raw_criteria[:6]
            )
            try:
                delivery = self._enqueue_room_intercom(
                    session_id,
                    {
                        "kind": "send",
                        "targetParticipantId": work["offeredToParticipantId"],
                        "clientMessageId": work["clientMessageId"],
                        "workItemId": work["id"],
                        "workAction": "assignment",
                        "content": (
                            f"责任交接 WorkItem {work['id']}\n"
                            f"目标：{_bounded_text(work['objective'], maximum=1_200)}\n"
                            f"交付物：{_bounded_text(work['expectedOutput'], maximum=800)}\n"
                            f"验收标准：\n{criteria}\n"
                            "请先按责任账本执行；完成后通过当前 Room "
                            "交付能力提交证据，不要用普通 @ 消息冒充交付。"
                        ),
                    },
                )
            except Exception as exc:
                failed = self.room_work.fail_assignment(
                    str(work["id"]),
                    actor_participant_id=str(participant["id"]),
                    reason=str(exc),
                )
                self._publish_room_work_activity(
                    failed,
                    phase="assignment_failed",
                    actor=participant,
                )
                raise
        return {
            "schemaVersion": "rag-ime.agent-room-work-operation.v1",
            "ok": True,
            "operation": "assign",
            "created": created,
            "work": work,
            "delivery": dict(delivery) if isinstance(delivery, Mapping) else None,
        }

    def submit_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.submit", session_id)
        actor = self._require_room_participant(session_id)
        work = self.room_work.submit(session_id, payload)
        self._publish_room_work_activity(work, phase="submitted", actor=actor)
        reviewer_id = self.room_work.reviewer_participant_id(str(work["id"]))
        delivery = self._notify_room_work(
            session_id,
            work,
            target_participant_id=reviewer_id,
            action="submission",
            content=(
                f"WorkItem {work['id']} 已提交验收。\n"
                f"交付摘要：{_bounded_text(work['resultSummary'], maximum=3_000)}\n"
                "请核对验收标准后提交验收结论或具体返修理由。"
            ),
        )
        return self._room_work_operation("submit", work, delivery=delivery)

    def accept_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.accept", session_id)
        actor = self._require_room_participant(session_id)
        work = self.room_work.accept(session_id, payload)
        self._publish_room_work_activity(work, phase="completed", actor=actor)
        delivery = self._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["currentOwnerParticipantId"]),
            action="accepted",
            content=f"WorkItem {work['id']} 已通过验收，责任闭环完成。",
        )
        return self._room_work_operation("accept", work, delivery=delivery)

    def return_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.return", session_id)
        actor = self._require_room_participant(session_id)
        work = self.room_work.return_for_revision(session_id, payload)
        self._publish_room_work_activity(work, phase="returned", actor=actor)
        delivery = self._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["currentOwnerParticipantId"]),
            action="revision",
            content=(
                f"WorkItem {work['id']} 需要第 {work['revision']} 次修订。\n"
                f"原因：{payload.get('reason')}\n"
                "完成修订后重新提交交付证据。"
            ),
        )
        return self._room_work_operation("return", work, delivery=delivery)

    def block_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.block", session_id)
        actor = self._require_room_participant(session_id)
        work = self.room_work.block(session_id, payload)
        self._publish_room_work_activity(work, phase="blocked", actor=actor)
        blocker = work["blocker"]
        assert isinstance(blocker, Mapping)
        delivery = self._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["accountableParticipantId"]),
            action="blocked",
            content=(
                f"WorkItem {work['id']} 已阻塞。\n"
                f"原因：{_bounded_text(blocker.get('reason'), maximum=1_600)}\n"
                f"下一步：{_bounded_text(blocker.get('nextStep'), maximum=1_600)}"
            ),
        )
        return self._room_work_operation("block", work, delivery=delivery)

    def escalate_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self._guard_session_route("work_item.escalate", session_id)
        actor = self._require_room_participant(session_id)
        work = self.room_work.escalate(session_id, payload)
        self._publish_room_work_activity(work, phase="escalated", actor=actor)
        blocker = work["blocker"]
        assert isinstance(blocker, Mapping)
        delivery = self._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["accountableParticipantId"]),
            action="escalated",
            content=(
                f"WorkItem {work['id']} 已升级给责任人。\n"
                f"原因：{_bounded_text(blocker.get('reason'), maximum=1_600)}\n"
                f"建议下一步：{_bounded_text(blocker.get('nextStep'), maximum=1_600)}"
            ),
        )
        return self._room_work_operation("escalate", work, delivery=delivery)

    def list_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        participant = self._require_room_participant(session_id, active_only=False)
        return {
            "schemaVersion": "rag-ime.agent-room-work-list.v1",
            "ok": True,
            "sessionId": session_id,
            "participant": participant,
            "items": self.room_work.list_for_session(
                session_id,
                status=str(value.get("status") or ""),
                limit=_integer(value.get("limit"), default=100, minimum=1, maximum=200),
            ),
        }

    def _require_room_participant(
        self,
        session_id: str,
        *,
        active_only: bool = True,
    ) -> dict[str, object]:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=active_only,
        )
        if participant is None:
            raise ValueError("session is not a Room participant")
        return participant

    def _notify_room_work(
        self,
        session_id: str,
        work: Mapping[str, object],
        *,
        target_participant_id: str,
        action: str,
        content: str,
    ) -> Mapping[str, object] | None:
        source = self._require_room_participant(session_id)
        if target_participant_id == str(source["id"]):
            return None
        return self._enqueue_room_intercom(
            session_id,
            {
                "kind": "send",
                "targetParticipantId": target_participant_id,
                "clientMessageId": (
                    f"work-{action}:{work['id']}:{work.get('revision', 0)}"
                ),
                "workItemId": work["id"],
                "workAction": action,
                "content": content,
            },
        )

    def _enqueue_room_intercom(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        route = self.room_intercom.store.resolve_route(source_session_id, payload)
        kind = str(payload.get("kind") or "send")
        route_id = f"intercom.{kind}"
        source, target = route["source"], route["target"]
        assert isinstance(source, Mapping) and isinstance(target, Mapping)
        self._guard_session_route(route_id, str(source["sessionId"]))
        self._guard_session_route(route_id, str(target["sessionId"]))
        return self.room_intercom.enqueue(source_session_id, payload)

    @staticmethod
    def _room_work_operation(
        operation: str,
        work: Mapping[str, object],
        *,
        delivery: Mapping[str, object] | None,
    ) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-room-work-operation.v1",
            "ok": True,
            "operation": operation,
            "work": dict(work),
            "delivery": dict(delivery) if isinstance(delivery, Mapping) else None,
        }

    def _publish_room_work_activity(
        self,
        work: Mapping[str, object],
        *,
        phase: str,
        actor: Mapping[str, object],
        document_sync: Mapping[str, object] | None = None,
    ) -> None:
        self.room_events.publish(
            room_id=str(work.get("roomId") or ""),
            event_type="participant_activity",
            payload={
                "activityKind": "work",
                "phase": phase,
                "workItemId": str(work.get("id") or ""),
                "workItemRevision": _integer_value(work.get("revision") or 0),
                "attemptId": str(work.get("acceptedTurnId") or ""),
                **(
                    {"dispatchId": str(work.get("acceptedTurnId") or "")}
                    if str(work.get("acceptedTurnId") or "")
                    else {}
                ),
                "work": dict(work),
                **(
                    {"documentSync": dict(document_sync)}
                    if document_sync is not None
                    else {}
                ),
            },
            turn_id=str(work.get("rootTurnId") or work.get("id") or ""),
            participant_id=str(actor.get("id") or ""),
            source_session_id=str(actor.get("sessionId") or ""),
            topic_id=str(work.get("topicId") or ""),
        )

def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[: max(0, maximum)]


def _integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = _integer_value(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _integer_value(value: object) -> int:
    if isinstance(value, (str, bytes, bytearray, SupportsInt, SupportsIndex)):
        return int(value)
    raise TypeError("expected an integer-compatible value")
