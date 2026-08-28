from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class RoomWorkHost(Protocol):
    rooms: Any
    room_work: Any
    room_intercom: Any
    room_events: Any

    def _require_room_participant(self, session_id: str) -> dict[str, object]: ...
    def _notify_room_work(
        self,
        work: Mapping[str, object],
        *,
        source_session_id: str,
        kind: str,
        payload: Mapping[str, object],
    ) -> object: ...
    def _enqueue_room_intercom(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]: ...
    def _publish_room_work_activity(
        self,
        work: Mapping[str, object],
        *,
        phase: str,
        actor: Mapping[str, object],
        document_sync: Mapping[str, object] | None = None,
    ) -> None: ...

    @staticmethod
    def _room_work_operation(
        operation: str,
        work: Mapping[str, object],
        *,
        delivery: Mapping[str, object] | None,
    ) -> dict[str, object]: ...


class RoomWorkApplicationService:
    """Room responsibility, handoff, review, and intercom commands."""

    def __init__(self, host: RoomWorkHost) -> None:
        self.host = host

    def room_work_items(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.host.rooms.get(room_id)
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
        items = self.host.room_work.list(
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
        self.host.rooms.get(room_id)
        work_item = self.host.room_work.get(work_item_id, room_id=room_id)
        return {
            "schemaVersion": "rag-ime.agent-room-work-item-get.v1",
            "ok": True,
            "roomId": room_id,
            "workItem": work_item,
            "events": self.host.room_work.list_events(work_item_id),
        }

    def create_room_work_item(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.host.rooms.get(room_id)
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
        work_item = self.host.room_work.create(
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
        room = self.host.rooms.get(room_id)
        if str(room.get("status") or "") != "active":
            raise ValueError("agent room is archived")
        self.host.room_work.get(work_item_id, room_id=room_id)
        target_id = _bounded_text(
            payload.get("targetParticipantId")
            or payload.get("currentOwnerParticipantId"),
            maximum=320,
        )
        if not target_id:
            raise ValueError("targetParticipantId must not be empty")
        work_item = self.host.room_work.reassign(
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
        item = self.host._enqueue_room_intercom(source_session_id, payload)
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
        participant = self.host.rooms.participant_for_session(session_id, active_only=True)
        if participant is None:
            raise ValueError("session is not a room participant")
        return {
            "schemaVersion": "rag-ime.agent-room-intercom-list.v1",
            "ok": True,
            "sessionId": session_id,
            "participant": participant,
            "room": self.host.rooms.get(str(participant["roomId"])),
            "items": self.host.room_intercom.list(
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
        self.host._guard_room_session_route("work_item.assign", session_id)
        participant = self.host.rooms.participant_for_session(session_id)
        if participant is None:
            raise ValueError("session is not an active Room participant")
        room = self.host.rooms.get(str(participant["roomId"]))
        work, created = self.host.room_work.assign(
            session_id,
            payload,
            root_turn_id=self.host.rooms.latest_turn_for_participant(
                str(participant["roomId"]),
                str(participant["id"]),
            ),
            topic_id=str(room.get("activeTopicId") or ""),
        )
        delivery: Mapping[str, object] | None = None
        if created:
            self.host._publish_room_work_activity(
                work,
                phase="assigned",
                actor=participant,
            )
        if str(work.get("state") or "") == "queued":
            criteria = "\n".join(
                f"- {_bounded_text(value, maximum=240)}"
                for value in list(work.get("acceptanceCriteria", []))[:6]
            )
            try:
                delivery = self.host._enqueue_room_intercom(
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
                failed = self.host.room_work.fail_assignment(
                    str(work["id"]),
                    actor_participant_id=str(participant["id"]),
                    reason=str(exc),
                )
                self.host._publish_room_work_activity(
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
        self.host._guard_room_session_route("work_item.submit", session_id)
        actor = self.host._require_room_participant(session_id)
        work = self.host.room_work.submit(session_id, payload)
        self.host._publish_room_work_activity(work, phase="submitted", actor=actor)
        reviewer_id = self.host.room_work.reviewer_participant_id(str(work["id"]))
        delivery = self.host._notify_room_work(
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
        return self.host._room_work_operation("submit", work, delivery=delivery)

    def accept_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.host._guard_room_session_route("work_item.accept", session_id)
        actor = self.host._require_room_participant(session_id)
        work = self.host.room_work.accept(session_id, payload)
        self.host._publish_room_work_activity(work, phase="completed", actor=actor)
        delivery = self.host._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["currentOwnerParticipantId"]),
            action="accepted",
            content=f"WorkItem {work['id']} 已通过验收，责任闭环完成。",
        )
        return self.host._room_work_operation("accept", work, delivery=delivery)

    def return_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.host._guard_room_session_route("work_item.return", session_id)
        actor = self.host._require_room_participant(session_id)
        work = self.host.room_work.return_for_revision(session_id, payload)
        self.host._publish_room_work_activity(work, phase="returned", actor=actor)
        delivery = self.host._notify_room_work(
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
        return self.host._room_work_operation("return", work, delivery=delivery)

    def block_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.host._guard_room_session_route("work_item.block", session_id)
        actor = self.host._require_room_participant(session_id)
        work = self.host.room_work.block(session_id, payload)
        self.host._publish_room_work_activity(work, phase="blocked", actor=actor)
        delivery = self.host._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["accountableParticipantId"]),
            action="blocked",
            content=(
                f"WorkItem {work['id']} 已阻塞。\n"
                f"原因：{_bounded_text(dict(work['blocker']).get('reason'), maximum=1_600)}\n"
                f"下一步：{_bounded_text(dict(work['blocker']).get('nextStep'), maximum=1_600)}"
            ),
        )
        return self.host._room_work_operation("block", work, delivery=delivery)

    def escalate_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.host._guard_room_session_route("work_item.escalate", session_id)
        actor = self.host._require_room_participant(session_id)
        work = self.host.room_work.escalate(session_id, payload)
        self.host._publish_room_work_activity(work, phase="escalated", actor=actor)
        delivery = self.host._notify_room_work(
            session_id,
            work,
            target_participant_id=str(work["accountableParticipantId"]),
            action="escalated",
            content=(
                f"WorkItem {work['id']} 已升级给责任人。\n"
                f"原因：{_bounded_text(dict(work['blocker']).get('reason'), maximum=1_600)}\n"
                f"建议下一步：{_bounded_text(dict(work['blocker']).get('nextStep'), maximum=1_600)}"
            ),
        )
        return self.host._room_work_operation("escalate", work, delivery=delivery)

    def list_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        participant = self.host._require_room_participant(session_id, active_only=False)
        return {
            "schemaVersion": "rag-ime.agent-room-work-list.v1",
            "ok": True,
            "sessionId": session_id,
            "participant": participant,
            "items": self.host.room_work.list_for_session(
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
        participant = self.host.rooms.participant_for_session(
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
        source = self.host._require_room_participant(session_id)
        if target_participant_id == str(source["id"]):
            return None
        return self.host._enqueue_room_intercom(
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
        route = self.host.room_intercom.store.resolve_route(source_session_id, payload)
        kind = str(payload.get("kind") or "send")
        route_id = f"intercom.{kind}"
        self.host._guard_room_session_route(route_id, str(route["source"]["sessionId"]))
        self.host._guard_room_session_route(route_id, str(route["target"]["sessionId"]))
        return self.host.room_intercom.enqueue(source_session_id, payload)

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
        self.host.room_events.publish(
            room_id=str(work.get("roomId") or ""),
            event_type="participant_activity",
            payload={
                "activityKind": "work",
                "phase": phase,
                "workItemId": str(work.get("id") or ""),
                "workItemRevision": int(work.get("revision") or 0),
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
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))
