from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from .agent_protocol import AgentEventEnvelope
from .agent_rooms import AgentRoomEventHub


PUBLIC_ROOM_REPORT_MAX_CHARS = 8_000
_PUBLIC_ROOM_REPORT_INTERNAL_MARKER = re.compile(
    r"(?:"
    r"\b[A-Za-z][A-Za-z0-9_]*(?:Id|Ref|Hash|Receipt)\b"
    r"|(?i:\b(?:kernel|root|dispatch|task|receipt(?:\s+id)?)\b)"
    r"|(?i:\bAC\b(?!-\d))"
    r"|(?i:\bsha256\b)"
    r"|(?i:(?:room-(?:root|work|task|dispatch|commit|post|receipt)|"
    r"execution:invoke|invoke|participant|agent|dispatch|task|root|"
    r"receipt|evidence|proof|criterion|commit):[^\s`]+)"
    r"|(?i:\b(?:qualityGateReceipt|requirementCoverage|acceptanceAliases|"
    r"resourceUsage|commandInvocationReceipt|continuation)\b)"
    r"|(?i:\b(?:execution|quality[_-]?gate|command|invocation|room|root|task|"
    r"dispatch|participant|session|evidence|proof|criterion|commit)[_-]?"
    r"(?:id|ref|hash|receipt)\b\s*(?:=|:|为))"
    r"|(?i:(?:file://|/(?:Users|Volumes|private|tmp)/|~/|\.\.?/)\S+)"
    r"|(?i:(?:\b[A-Z]:[\\/]|\\\\[^\\\s]+\\)\S+)"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    r"|\b[0-9a-fA-F]{40,64}\b"
    r")"
)
_PUBLIC_ROOM_REPORT_PROTOCOL_PLACEHOLDER = re.compile(
    r"(?i)^(?:public\s*[:：]\s*)?(?:"
    r"deliver|handoff|wait|blocked|done|complete(?:d)?|result|success|failed?"
    r"|已?完成|已?转交|等待|已?阻塞|成功|失败"
    r")\s*[.!。！]?$"
)
_PUBLIC_ROOM_REPORT_GENERIC_PROGRESS_PLACEHOLDER = re.compile(
    r"(?i)^(?:"
    r"(?:(?:i(?:'m| am)\s+|still\s+)?"
    r"(?:processing|working|analy[sz]ing|checking|executing)"
    r"(?:\s+(?:on it|now))?)"
    r"|(?:(?:我|当前|任务)?(?:正在|还在|在)?"
    r"(?:处理|分析|检查|执行|工作|进行)"
    r"(?:中|一下|(?:这个)?(?:任务|请求))?)"
    r")[\s.!。！…]*$"
)
_PUBLIC_ROOM_REPORT_GLOBAL_COMPLETION_CLAIM = re.compile(
    r"(?i)(?:"
    r"\b(?:entire|whole|all)\s+(?:request|task|work)\b.{0,20}"
    r"\b(?:complete(?:d)?|done|finished)\b"
    r"|(?:整个|全部|所有)(?:请求|任务|工作|事项).{0,12}"
    r"(?:已经|已)?(?:完成|结束|交付)"
    r"|(?:请求|任务|工作|事项).{0,8}(?:已经|已|全部|均)"
    r"(?:完成|结束|交付)"
    r")"
)
_PUBLIC_ROOM_REPORT_VERIFICATION_CLAIM = re.compile(
    r"(?i)(?:"
    r"\b(?:all|every)\b.{0,20}\b(?:tests?|checks?|verification|criteria)\b"
    r".{0,12}\b(?:passed|verified|complete(?:d)?)\b"
    r"|\b(?:tests?|checks?|verification)\b.{0,12}"
    r"\b(?:all\s+)?(?:passed|verified|complete(?:d)?)\b"
    r"|(?:全部|所有|各项)(?:测试|检查|验证|验收|标准).{0,12}"
    r"(?:通过|完成|满足)"
    r"|(?:测试|检查|验证|验收|标准).{0,8}(?:全部|均|都|已经|已)"
    r"(?:通过|完成|满足)"
    r")"
)
_PUBLIC_ROOM_REPORT_ACCEPTANCE_CLAIM = re.compile(
    r"(?i)(?:"
    r"\b(?:all|every)\b.{0,20}\b(?:criteria|requirements?)\b"
    r".{0,12}\b(?:passed|verified|complete(?:d)?|satisfied)\b"
    r"|(?:全部|所有|各项)(?:验收|标准|需求).{0,12}"
    r"(?:通过|完成|满足)"
    r"|(?:验收|标准|需求).{0,8}(?:全部|均|都|已经|已)"
    r"(?:通过|完成|满足)"
    r")"
)
_PUBLIC_ROOM_ALIGNMENT_PROTOCOL_MATERIAL = re.compile(
    r"(?:"
    r"(?i:(?<![A-Za-z0-9_])(?:schemaVersion|rootId|taskId|dispatchId|"
    r"postId|receiptId|participantId|qualityGateReceipt|"
    r"requirementCoverage|acceptanceAliases|resourceUsage|"
    r"commandInvocationReceipt|continuation)(?![A-Za-z0-9_]))"
    r"|(?i:(?:room-(?:root|work|task|dispatch|commit|post|receipt)|"
    r"execution:invoke|invoke|participant|agent|session|root|task|dispatch|"
    r"receipt|evidence|proof|criterion|requirement|commit):"
    r"[^\s，。；、“”]+)"
    r"|(?i:(?<![A-Za-z0-9_])AC-\d+(?![A-Za-z0-9_]))"
    r"|(?i:(?<![A-Za-z0-9_])(?:root|task|dispatch|receipt|requirement|"
    r"evidence|proof|criterion)-(?=[A-Za-z0-9_.-]*\d)"
    r"[A-Za-z0-9_.-]+(?![A-Za-z0-9_]))"
    r"|(?i:\b(?:wisdom-weasel|rag-ime)\.[A-Za-z0-9_.-]+)"
    r"|(?:\{|\[)\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*:"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    r"|\b[0-9a-fA-F]{40,64}\b"
    r")"
)


def public_room_report_content(value: object, *, field_name: str) -> str:
    """Validate model-authored text before it enters the public Room timeline."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    content = value.strip()
    if not content:
        raise ValueError(f"{field_name} must not be empty")
    if len(content) > PUBLIC_ROOM_REPORT_MAX_CHARS:
        raise ValueError(
            f"{field_name} must contain at most "
            f"{PUBLIC_ROOM_REPORT_MAX_CHARS} characters"
        )
    if (
        _PUBLIC_ROOM_REPORT_PROTOCOL_PLACEHOLDER.fullmatch(content)
        or _PUBLIC_ROOM_REPORT_GENERIC_PROGRESS_PLACEHOLDER.fullmatch(content)
    ):
        raise ValueError(
            f"{field_name} must be a meaningful user-facing report, not a "
            "protocol label, generic progress filler, or terminal status"
        )
    if _PUBLIC_ROOM_REPORT_INTERNAL_MARKER.search(content):
        raise ValueError(
            f"{field_name} must be rewritten for users without internal Room "
            "identifiers, raw receipts, hashes, or machine paths"
        )
    return content


def canonical_room_alignment_content(
    *,
    objective: object,
    expected_output: object,
) -> str:
    """Render the accepted goal and delivery boundary as one public summary."""

    normalized_objective = _canonical_alignment_fragment(
        objective,
        field_name="objective",
    )
    normalized_output = _canonical_alignment_fragment(
        expected_output,
        field_name="expectedOutput",
    )
    content = (
        f"已经对齐：目标是“{normalized_objective}”，"
        f"交付边界是“{normalized_output}”。"
    )
    if len(content) > PUBLIC_ROOM_REPORT_MAX_CHARS:
        raise ValueError(
            "alignment summary must contain at most "
            f"{PUBLIC_ROOM_REPORT_MAX_CHARS} characters"
        )
    return content


def _canonical_alignment_fragment(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"alignment {field_name} must be natural language"
        )
    content = " ".join(value.split()).strip().rstrip("。！？!?；;")
    if not content or _PUBLIC_ROOM_ALIGNMENT_PROTOCOL_MATERIAL.search(content):
        raise ValueError(
            f"alignment {field_name} must be natural language without raw "
            "Room protocol material"
        )
    return content


def assert_public_room_report_claims(
    content: str,
    *,
    field_name: str,
    decision: str,
    all_criteria_verified: bool,
) -> None:
    """Fence terminal prose against claims stronger than Kernel evidence."""

    if decision not in {"deliver", "handoff", "wait", "blocked"}:
        raise ValueError("decision is invalid")
    if (
        decision != "deliver"
        and _PUBLIC_ROOM_REPORT_GLOBAL_COMPLETION_CLAIM.search(content)
    ):
        raise ValueError(
            f"{field_name} must not claim the whole request is complete for "
            f"a {decision} outcome"
        )
    if (
        decision != "deliver"
        and not all_criteria_verified
        and _PUBLIC_ROOM_REPORT_VERIFICATION_CLAIM.search(content)
        and (
            decision != "handoff"
            or _PUBLIC_ROOM_REPORT_ACCEPTANCE_CLAIM.search(content)
        )
    ):
        raise ValueError(
            f"{field_name} must not claim completed verification without "
            "authoritative evidence for every acceptance criterion"
        )


_ROOM_POST_PUBLIC_FIELDS = (
    "schemaVersion",
    "postId",
    "roomId",
    "rootId",
    "generation",
    "taskId",
    "dispatchId",
    "authorActorRef",
    "kind",
    "visibility",
    "content",
    "question",
    "mentions",
    "blocks",
    "attachments",
    "chronology",
    "idempotencyKey",
    "publicationSource",
    "createdAtMs",
)


def public_room_post_payload(
    post: Mapping[str, object],
) -> dict[str, object]:
    """Strip private context enrichment from a public Room Post payload."""

    return {
        field: post[field]
        for field in _ROOM_POST_PUBLIC_FIELDS
        if field in post
    }


class RoomPublicTimelineProjector:
    """Project canonical Room work into one replayable public timeline.

    The Kernel remains the sole execution owner. This class only owns the
    user-facing read model: accepted input, routing, bounded live progress,
    explicit RoomPost publication, and terminal state.
    """

    def __init__(
        self,
        events: AgentRoomEventHub,
        *,
        root_is_terminal: Callable[[str], bool] | None = None,
    ) -> None:
        self.events = events
        self.root_is_terminal = root_is_terminal

    def publish_ingress(
        self,
        *,
        room: Mapping[str, object],
        post: Mapping[str, object],
        client_message_id: str,
        route_decisions: Sequence[Mapping[str, object]],
        dispatches: Sequence[Mapping[str, object]],
        answer_to_post_id: str = "",
        answer_display_text: str = "",
        chronology_after_post_id: str = "",
    ) -> list[dict[str, object]]:
        room_id = str(post["roomId"])
        root_id = str(post["rootId"])
        topic_id = str(room.get("activeTopicId") or "")
        projected: list[dict[str, object]] = []
        user_event = self.events.publish_projection(
            projection_key=f"room-post:{post['postId']}",
            room_id=room_id,
            event_type="user_message",
            payload={
                "messageId": str(post["postId"]),
                "clientMessageId": client_message_id,
                "text": str(post["content"]),
                "rootId": root_id,
                "postId": str(post["postId"]),
                "attachmentReceipts": list(post.get("attachments") or []),
                **(
                    {"answerToPostId": answer_to_post_id}
                    if answer_to_post_id
                    else {}
                ),
                **(
                    {"displayText": answer_display_text}
                    if answer_display_text
                    and answer_display_text != str(post["content"])
                    else {}
                ),
                **(
                    {"afterPostId": chronology_after_post_id}
                    if chronology_after_post_id
                    else {}
                ),
            },
            turn_id=root_id,
            topic_id=topic_id,
            created_at_ms=int(post["createdAtMs"]),
        )
        if user_event is not None:
            projected.append(user_event)

        participants = {
            str(value.get("id") or ""): value
            for value in room.get("participants", [])
            if isinstance(value, Mapping)
        }
        for decision, dispatch in zip(
            route_decisions,
            dispatches,
            strict=True,
        ):
            participant_id = str(dispatch.get("participantId") or "")
            participant = participants.get(participant_id, {})
            display_name = str(
                participant.get("displayName") or "协作成员"
            )
            dispatch_id = str(dispatch.get("dispatchId") or "")
            event = self.events.publish_projection(
                projection_key=f"room-dispatch:{dispatch_id}:accepted",
                room_id=room_id,
                event_type="route_decision",
                payload={
                    "rootId": root_id,
                    "taskId": str(decision.get("taskId") or ""),
                    "dispatchId": dispatch_id,
                    "targetParticipantId": participant_id,
                    "status": "queued",
                    "reason": str(decision.get("reason") or "")[:160],
                    "summary": (
                        f"{display_name} 正在判断是否需要澄清"
                        if decision.get("phase") == "alignment"
                        else f"{display_name} 已进入执行队列"
                    ),
                    "phase": str(decision.get("phase") or "execution"),
                    "alignmentOrdinal": decision.get(
                        "alignmentOrdinal"
                    ),
                    "dependsOnDispatchIds": list(
                        decision.get("dependsOnDispatchIds") or []
                    ),
                },
                turn_id=root_id,
                participant_id=participant_id or None,
                source_session_id=str(dispatch.get("sessionId") or ""),
                topic_id=topic_id,
                created_at_ms=int(post["createdAtMs"]),
            )
            if event is not None:
                projected.append(event)
        return projected

    def publish_runtime(
        self,
        *,
        event: AgentEventEnvelope,
        binding: Mapping[str, object],
        participant: Mapping[str, object],
        event_type: str,
        public_data: Mapping[str, object],
        topic_id: str = "",
        allow_after_terminal: bool = False,
    ) -> dict[str, object] | None:
        root_id = str(binding["rootId"])
        if self._after_root_terminal(root_id) and not allow_after_terminal:
            return None
        dispatch_id = str(binding["dispatchId"])
        data = {
            **dict(public_data),
            "rootId": root_id,
            "dispatchId": dispatch_id,
        }
        return self.events.publish_projection(
            projection_key=f"room-runtime:{event.event_id}",
            room_id=str(binding["roomId"]),
            event_type=event_type,
            payload={
                "sourceEventId": event.event_id,
                "sourceEventType": event.event_type,
                "data": data,
            },
            turn_id=root_id,
            participant_id=str(participant["id"]),
            source_session_id=event.session_id,
            topic_id=topic_id,
            created_at_ms=event.created_at_ms,
        )

    def publish_post(
        self,
        post: Mapping[str, object],
        *,
        participant_id: str,
        source_session_id: str,
        topic_id: str = "",
    ) -> dict[str, object] | None:
        if self._after_root_terminal(str(post["rootId"])):
            return None
        public_post = public_room_post_payload(post)
        return self.events.publish_projection(
            projection_key=f"room-post:{post['postId']}",
            room_id=str(post["roomId"]),
            event_type="room_post",
            # Context storage enriches a post with hashes and its journal
            # entry. Those are private evidence, not part of RoomPostV2.
            payload={"post": public_post},
            turn_id=str(post["rootId"]),
            participant_id=participant_id or None,
            source_session_id=source_session_id,
            topic_id=topic_id,
            created_at_ms=int(post["createdAtMs"]),
        )

    def _after_root_terminal(self, root_id: str) -> bool:
        return bool(
            self.root_is_terminal is not None
            and self.root_is_terminal(root_id)
        )

    def publish_terminal(
        self,
        *,
        room_id: str,
        root_id: str,
        generation: int,
        state: str,
        receipt_id: str,
        created_at_ms: int,
    ) -> dict[str, object] | None:
        normalized_state = (
            "aborted"
            if state == "cancelled"
            else "failed"
            if state == "failed"
            else "completed"
        )
        event_type = (
            "turn_failed" if normalized_state == "failed" else "turn_completed"
        )
        return self.events.publish_projection(
            projection_key=(
                f"room-root:{root_id}:generation:{generation}:terminal:{receipt_id or state}"
            ),
            room_id=room_id,
            event_type=event_type,
            payload={
                "rootId": root_id,
                "generation": generation,
                "status": normalized_state,
                "receiptId": receipt_id,
            },
            turn_id=root_id,
            created_at_ms=created_at_ms,
        )

    def sync_terminal_root(
        self,
        root: Mapping[str, object],
    ) -> dict[str, object] | None:
        state = str(root.get("state") or "")
        if state not in {
            "completed",
            "cancelled",
            "failed",
        }:
            return None
        return self.publish_terminal(
            room_id=str(root["roomId"]),
            root_id=str(root["rootId"]),
            generation=int(root["generation"]),
            state=state,
            receipt_id=str(root.get("terminalReceiptId") or ""),
            created_at_ms=int(root.get("updatedAtMs") or 0),
        )
