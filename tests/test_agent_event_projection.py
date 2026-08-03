from __future__ import annotations

from collections.abc import Mapping
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_event_projection import (
    AgentEventProjectionService,
    room_event_projection,
)
from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.agent_room_public_timeline import RoomPublicTimelineProjector
from rag_ime.agent_room_turn_registry import RoomTurnRegistry
from rag_ime.agent_rooms import AgentRoomEventHub, AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


class _KernelWithoutBinding:
    mode = "kernel_only"

    @staticmethod
    def session_binding(_session_id: str) -> None:
        return None


class _Rooms:
    @staticmethod
    def participant_for_session(_session_id: str) -> dict[str, object]:
        return {"id": "participant:1", "roomId": "room:1"}


class _Observations:
    def __init__(self) -> None:
        self.count = 0

    def enqueue_agent_event(self, _event: object, *, room_id: str) -> None:
        self.count += 1
        if room_id != "room:1":
            raise AssertionError("participant Room was not preserved")


class _Sessions:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    def record_runtime_event(self, **values: object) -> None:
        self.event_types.append(str(values["event_type"]))


class _ForbiddenLegacyTurns:
    @staticmethod
    def private_intercom_for_event(_event: object) -> str:
        return ""

    @staticmethod
    def turn_for_event(_event: object) -> str:
        raise AssertionError("kernel event fell through to legacy Room mapping")


class AgentEventProjectionTests(unittest.TestCase):
    def test_transient_fragments_stay_out_of_durable_runtime_events(
        self,
    ) -> None:
        sessions = _Sessions()
        service = AgentEventProjectionService(
            sessions=sessions,
            room_kernel=_KernelWithoutBinding(),
            rooms=_Rooms(),
            agent_blocks=None,
            observations=_Observations(),
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
        )
        for sequence, event_type in enumerate(
            ("text_delta", "tool_progress", "turn_completed"),
            start=1,
        ):
            service.record(
                AgentEventEnvelope(
                    event_id=f"event:{sequence}",
                    session_id="session:1",
                    turn_id="turn:1",
                    sequence=sequence,
                    created_at_ms=sequence,
                    event_type=event_type,
                    payload={},
                    resume_token=f"event:{sequence}",
                )
            )

        self.assertEqual(sessions.event_types, ["turn_completed"])

    def test_room_completion_projects_response_usage_and_cache_receipt(
        self,
    ) -> None:
        class Kernel:
            mode = "kernel_only"
            binding = {
                "roomId": "room:1",
                "rootId": "root:1",
                "dispatchId": "dispatch:1",
                "generation": 1,
                "state": "committed",
                "runtimeTurnId": "turn:1",
                "attempt": 0,
            }

            @classmethod
            def session_binding(
                cls,
                _session_id: str,
            ) -> dict[str, object]:
                return cls.binding

            @staticmethod
            def post_for_dispatch(
                dispatch_id: str,
            ) -> dict[str, object]:
                if dispatch_id != "dispatch:1":
                    raise AssertionError("response lookup used another Dispatch")
                return {"postId": "post:1"}

        class Rooms(_Rooms):
            @staticmethod
            def get(_room_id: str) -> dict[str, object]:
                return {"activeTopicId": "topic:1"}

        class Timeline:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict[str, object]]] = []
                self.allow_after_terminal = False

            def publish_runtime(self, **values: object) -> None:
                self.allow_after_terminal = bool(
                    values.get("allow_after_terminal")
                )
                self.events.append((
                    str(values["event_type"]),
                    dict(values["public_data"]),  # type: ignore[arg-type]
                ))

        class KernelProjection:
            @staticmethod
            def sync_room(_room_id: str, *, now_ms: int) -> None:
                if now_ms != 10:
                    raise AssertionError("completion timestamp was not preserved")

        timeline = Timeline()
        service = AgentEventProjectionService(
            sessions=None,
            room_kernel=Kernel(),
            rooms=Rooms(),
            agent_blocks=None,
            observations=_Observations(),
            room_kernel_projection=KernelProjection(),
            room_events=None,
            public_timeline=timeline,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
        )

        service.mirror_to_room(
            AgentEventEnvelope(
                event_id="event:usage",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=10,
                event_type="message_completed",
                payload={
                    "message": {
                        "role": "assistant",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "usage": {
                            "input": 1200,
                            "output": 80,
                            "cacheRead": 900,
                            "cacheWrite": 30,
                            "totalTokens": 2210,
                        },
                    },
                    "usageReported": True,
                    "cacheUsageReported": True,
                },
                resume_token="event:usage",
            )
        )

        self.assertEqual(timeline.events, [(
            "participant_activity",
            {
                "status": "draft_ready",
                "summary": "正在整理正式 Post",
                "requestId": "dispatch:1:provider",
                "runtimeTurnId": "turn:1",
                "usageReported": True,
                "cacheUsageReported": True,
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input": 1200,
                    "output": 80,
                    "cacheRead": 900,
                    "cacheWrite": 30,
                    "totalTokens": 2210,
                },
                "responsePostId": "post:1",
            },
        )])
        self.assertTrue(timeline.allow_after_terminal)

    def test_terminal_room_allows_only_explicit_response_provenance(
        self,
    ) -> None:
        class Events:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def publish_projection(
                self,
                **values: object,
            ) -> dict[str, object]:
                self.calls.append(dict(values))
                return dict(values)

        events = Events()
        projector = RoomPublicTimelineProjector(
            events,  # type: ignore[arg-type]
            root_is_terminal=lambda _root_id: True,
        )
        event = AgentEventEnvelope(
            event_id="event:final-usage",
            session_id="session:1",
            turn_id="runtime-turn:1",
            sequence=1,
            created_at_ms=10,
            event_type="message_completed",
            payload={},
            resume_token="event:final-usage",
        )
        values = {
            "event": event,
            "binding": {
                "roomId": "room:1",
                "rootId": "root:1",
                "dispatchId": "dispatch:1",
            },
            "participant": {"id": "participant:1"},
            "event_type": "participant_activity",
            "public_data": {
                "requestId": "dispatch:1:provider",
                "usageReported": True,
            },
        }

        self.assertIsNone(projector.publish_runtime(**values))
        self.assertEqual(events.calls, [])
        projected = projector.publish_runtime(
            **values,
            allow_after_terminal=True,
        )

        self.assertIsNotNone(projected)
        self.assertEqual(len(events.calls), 1)
        self.assertEqual(
            events.calls[0]["payload"],
            {
                "sourceEventId": "event:final-usage",
                "sourceEventType": "message_completed",
                "data": {
                    "requestId": "dispatch:1:provider",
                    "usageReported": True,
                    "rootId": "root:1",
                    "dispatchId": "dispatch:1",
                },
            },
        )

    def test_room_reasoning_projection_is_public_and_bounded(
        self,
    ) -> None:
        event_type, projected = room_event_projection(
            AgentEventEnvelope(
                event_id="event:reasoning",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=1,
                event_type="reasoning_summary",
                payload={
                    "status": "running",
                    "summary": "结" * 700,
                    "source": "runtime-" * 20,
                    "items": [f"{index}:" + ("步" * 300) for index in range(13)],
                },
                resume_token="event:reasoning",
            )
        )

        self.assertEqual(event_type, "participant_activity")
        self.assertEqual(projected["status"], "running")
        self.assertEqual(len(str(projected["summary"])), 500)
        self.assertLessEqual(len(str(projected["source"])), 80)
        self.assertEqual(len(projected["items"]), 12)  # type: ignore[arg-type]
        self.assertTrue(all(
            len(str(item)) <= 240
            for item in projected["items"]  # type: ignore[union-attr]
        ))

    def test_runtime_retry_and_missing_commit_recovery_stay_nonterminal(
        self,
    ) -> None:
        class Kernel:
            mode = "kernel_only"
            binding = {
                "roomId": "room:1",
                "rootId": "root:1",
                "dispatchId": "dispatch:1",
                "generation": 1,
                "state": "running",
                "runtimeTurnId": "turn:1",
                "attempt": 1,
            }

            @classmethod
            def session_binding(cls, _session_id: str) -> dict[str, object]:
                return cls.binding

        class Rooms(_Rooms):
            @staticmethod
            def get(_room_id: str) -> dict[str, object]:
                return {"activeTopicId": "topic:1"}

        class Timeline:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict[str, object]]] = []

            def publish_runtime(self, **values: object) -> None:
                self.events.append(
                    (
                        str(values["event_type"]),
                        dict(values["public_data"]),  # type: ignore[arg-type]
                    )
                )

        class KernelProjection:
            def sync_room(self, _room_id: str, *, now_ms: int) -> None:
                if now_ms < 1:
                    raise AssertionError("runtime projection time was lost")

        timeline = Timeline()
        failure_events: list[dict[str, object]] = []

        def record_runtime_failure(**values: object) -> dict[str, object]:
            failure_events.append(dict(values))
            Kernel.binding["state"] = "retry_wait"
            return {
                "receiptKind": "runtime_retry_scheduled",
                "details": {
                    "attempt": 2,
                    "availableAtMs": int(values["created_at_ms"]) + 1_000,
                },
            }

        service = AgentEventProjectionService(
            sessions=None,
            room_kernel=Kernel(),
            rooms=Rooms(),
            agent_blocks=None,
            observations=_Observations(),
            room_kernel_projection=KernelProjection(),
            room_events=None,
            public_timeline=timeline,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
            record_runtime_failure=record_runtime_failure,
        )
        service.mirror_to_room(
            AgentEventEnvelope(
                event_id="event:retry",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=1,
                event_type="turn_failed",
                payload={
                    "retryable": True,
                    "hadToolActivity": False,
                    "reasonCode": "provider_transport",
                },
                resume_token="event:retry",
            )
        )
        service.mirror_to_room(
            AgentEventEnvelope(
                event_id="event:completed",
                session_id="session:1",
                turn_id="turn:1",
                sequence=2,
                created_at_ms=2,
                event_type="turn_completed",
                payload={"status": "completed"},
                resume_token="event:completed",
            )
        )
        Kernel.binding["state"] = "running"
        service.mirror_to_room(
            AgentEventEnvelope(
                event_id="event:uncommitted",
                session_id="session:1",
                turn_id="turn:1",
                sequence=3,
                created_at_ms=3,
                event_type="turn_completed",
                payload={"status": "completed"},
                resume_token="event:uncommitted",
            )
        )

        self.assertEqual(
            [str(item["source_event_id"]) for item in failure_events],
            ["event:retry", "event:uncommitted"],
        )
        self.assertEqual(
            failure_events[1]["reason_code"],
            "room_commit_missing",
        )
        self.assertEqual(timeline.events[0], (
            "participant_activity",
            {
                "status": "retry_wait",
                "summary": "模型连接中断，已进入有界重试等待",
                "requestId": "dispatch:1:provider",
                "retryAttempt": 2,
                "retryAtMs": 1_001,
                "retryDelayMs": 1_000,
            },
        ))
        self.assertEqual(timeline.events[1][0], "turn_completed")
        self.assertEqual(timeline.events[2], (
            "participant_activity",
            {
                "status": "retry_wait",
                "summary": "当前回合未形成权威提交，已进入有界恢复等待",
                "requestId": "dispatch:1:provider",
                "retryAttempt": 2,
                "retryAtMs": 1_003,
                "retryDelayMs": 1_000,
            },
        ))

    def test_late_room_messages_do_not_contaminate_private_context(
        self,
    ) -> None:
        class Kernel:
            binding: dict[str, object] | None = {
                "roomId": "room:1",
                "rootId": "root:1",
                "taskId": "task:1",
                "dispatchId": "dispatch:1",
                "generation": 1,
                "state": "running",
                "runtimeTurnId": "turn:attempt-2",
                "attempt": 2,
            }
            managed_turn_ids = {
                "turn:attempt-1",
                "turn:attempt-2",
            }

            @classmethod
            def session_binding(
                cls,
                _session_id: str,
            ) -> dict[str, object] | None:
                return cls.binding

            @classmethod
            def is_managed_runtime_turn(
                cls,
                _session_id: str,
                runtime_turn_id: str,
            ) -> bool:
                return runtime_turn_id in cls.managed_turn_ids

            @staticmethod
            def root_ids(_room_id: str) -> list[str]:
                return ["root:1"]

        class Rooms:
            @staticmethod
            def participant_for_session(
                _session_id: str,
                *,
                active_only: bool,
            ) -> dict[str, object]:
                del active_only
                return {
                    "id": "participant:1",
                    "roomId": "room:1",
                }

        sessions = _Sessions()
        recent_messages: list[tuple[str, Mapping[str, object]]] = []
        evidence_event_ids: list[str] = []
        service = AgentEventProjectionService(
            sessions=sessions,
            room_kernel=Kernel(),
            rooms=Rooms(),
            agent_blocks=None,
            observations=_Observations(),
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda session_id, message: (
                recent_messages.append((session_id, message))
            ),
            record_assistant_evidence=lambda event: (
                evidence_event_ids.append(event.event_id) or {}
            ),
            notify_intercom=lambda: None,
        )

        def completed(
            event_id: str,
            turn_id: str,
            sequence: int,
        ) -> AgentEventEnvelope:
            return AgentEventEnvelope(
                event_id=event_id,
                session_id="session:1",
                turn_id=turn_id,
                sequence=sequence,
                created_at_ms=sequence,
                event_type="message_completed",
                payload={
                    "message": {
                        "id": f"message:{sequence}",
                        "role": "assistant",
                        "content": f"result:{sequence}",
                        "blocks": [],
                    }
                },
                resume_token=event_id,
            )

        service.record(
            completed("event:stale-attempt", "turn:attempt-1", 1)
        )
        Kernel.binding = None
        service.record(
            completed("event:post-terminal", "turn:attempt-2", 2)
        )

        self.assertEqual(recent_messages, [])
        self.assertEqual(evidence_event_ids, [])
        self.assertEqual(
            sessions.event_types,
            ["message_completed", "message_completed"],
        )

        service.record(
            completed("event:ordinary-agent", "turn:ordinary", 3)
        )
        self.assertEqual(
            [message[1]["content"] for message in recent_messages],
            ["result:3"],
        )
        self.assertEqual(
            evidence_event_ids,
            ["event:ordinary-agent"],
        )
        self.assertEqual(
            sessions.event_types,
            [
                "message_completed",
                "message_completed",
                "message_completed",
            ],
        )

    def test_room_approval_projection_preserves_public_model_history_evidence(self) -> None:
        event_type, data = room_event_projection(
            AgentEventEnvelope(
                event_id="event:approval",
                session_id="session:1",
                turn_id="turn:1",
                sequence=4,
                created_at_ms=4,
                event_type="approval_resolved",
                payload={
                    "approvalId": "approval:1",
                    "state": "rejected",
                    "automatic": True,
                    "decisionMode": "model",
                    "approvalModelDecision": {
                        "schemaVersion": "rag-ime.agent-approval-model-decision.v1",
                        "receiptId": "approval-model-decision:1",
                        "approvalId": "approval:1",
                        "sessionId": "session:1",
                        "contextKind": "room",
                        "contextId": "room:1",
                        "historyEntryCount": 5,
                        "mode": "model",
                        "automatic": True,
                        "decision": "deny",
                        "status": "decided",
                        "modelProvider": "openai-codex",
                        "modelId": "gpt-5.6-luna",
                        "modelProfile": "openai-codex/gpt-5.6-luna",
                        "thinkingLevel": "max",
                        "promptVersion": "approval-arbiter-v2",
                        "payloadSha256": "a" * 64,
                        "inputSha256": "b" * 64,
                        "scopeSha256": "c" * 64,
                        "reasonCodes": ["destructive_effect"],
                        "rationaleSummary": "该操作超出当前安全边界。",
                        "createdAtMs": 3,
                        "decidedAtMs": 4,
                    },
                },
                resume_token="event:approval",
            )
        )

        self.assertEqual(event_type, "participant_activity")
        decision = data["approvalModelDecision"]
        self.assertEqual(decision["contextKind"], "room")
        self.assertEqual(decision["contextId"], "room:1")
        self.assertEqual(decision["historyEntryCount"], 5)
        self.assertEqual(
            decision["rationaleSummary"],
            "该操作超出当前安全边界。",
        )
        self.assertNotIn("primaryAgentOutput", decision)

    def test_room_delta_preserves_replace_semantics_for_stream_final_dedup(
        self,
    ) -> None:
        event_type, data = room_event_projection(
            AgentEventEnvelope(
                event_id="event:replace",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=1,
                event_type="text_delta",
                payload={
                    "messageId": "turn:1:assistant",
                    "blockId": "turn:1:assistant:text",
                    "contentIndex": 0,
                    "delta": "authoritative progress",
                    "replaceBlock": False,
                    "replaceContent": True,
                },
                resume_token="event:replace",
            )
        )

        self.assertEqual(event_type, "participant_delta")
        self.assertIs(data["replaceBlock"], False)
        self.assertIs(data["replaceContent"], True)

    def test_trailing_private_delta_after_kernel_revoke_is_not_persisted_or_public(
        self,
    ) -> None:
        observations = _Observations()
        service = AgentEventProjectionService(
            sessions=None,
            room_kernel=_KernelWithoutBinding(),
            rooms=_Rooms(),
            agent_blocks=None,
            observations=observations,
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
        )
        event = AgentEventEnvelope(
            event_id="event:1",
            session_id="session:1",
            turn_id="private-turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="text_delta",
            payload={"delta": "private tail"},
            resume_token="event:1",
        )

        service.mirror_to_room(event)

        self.assertEqual(observations.count, 0)

    def test_private_intercom_turn_never_reaches_public_projection(
        self,
    ) -> None:
        observations = _Observations()
        turns = RoomTurnRegistry()
        notifications: list[str] = []
        service = AgentEventProjectionService(
            sessions=None,
            room_kernel=_KernelWithoutBinding(),
            rooms=_Rooms(),
            agent_blocks=None,
            observations=observations,
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=turns,
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: notifications.append("wake"),
        )
        turns.begin_private_intercom(
            "session:1",
            "intercom:notice",
        )
        for sequence, event_type in enumerate(
            ("text_delta", "turn_completed"),
            start=1,
        ):
            service.mirror_to_room(
                AgentEventEnvelope(
                    event_id=f"event:{sequence}",
                    session_id="session:1",
                    turn_id="turn:private",
                    sequence=sequence,
                    created_at_ms=sequence,
                    event_type=event_type,
                    payload={},
                    resume_token=f"event:{sequence}",
                )
            )

        self.assertEqual(observations.count, 0)
        self.assertEqual(notifications, [])
        self.assertFalse(
            turns.session_turn_active("session:1")
        )

    def test_structured_question_is_bounded_and_keeps_resolution_contract(
        self,
    ) -> None:
        event = AgentEventEnvelope(
            event_id="event:question",
            session_id="session:1",
            turn_id="turn:1",
            sequence=1,
            created_at_ms=10,
            event_type="user_input_required",
            payload={
                "requestId": "request:plan-review",
                "requestKind": "plan_review",
                "approvalId": "approval:plan-review",
                "method": "select",
                "title": "选择执行方式",
                "message": "请选择下一步",
                "options": [
                    f"方案 {index} " + ("选" * 300)
                    for index in range(105)
                ],
                "placeholder": "请选择",
                "prefill": "甲" * 5_000,
                "defaultValue": "方案 0",
                "timeout": 30_000,
                "_turnId": "private-turn",
                "privateDiagnostics": {
                    "provider": "must-not-project",
                },
            },
            resume_token="event:question",
        )

        event_type, data = room_event_projection(event)

        self.assertEqual(event_type, "participant_activity")
        self.assertEqual(data["requestId"], "request:plan-review")
        self.assertEqual(data["requestKind"], "plan_review")
        self.assertEqual(data["approvalId"], "approval:plan-review")
        self.assertEqual(data["method"], "select")
        self.assertEqual(len(data["options"]), 100)
        self.assertTrue(
            all(len(option) <= 240 for option in data["options"])
        )
        self.assertEqual(len(data["prefill"]), 4_000)
        self.assertEqual(data["defaultValue"], "方案 0")
        self.assertEqual(data["timeout"], 30_000)
        self.assertNotIn("_turnId", data)
        self.assertNotIn("privateDiagnostics", data)

        resolved = AgentEventEnvelope(
            event_id="event:question-resolved",
            session_id="session:1",
            turn_id="turn:1",
            sequence=2,
            created_at_ms=11,
            event_type="user_input_required",
            payload={
                "requestId": "request:plan-review",
                "method": "select",
                "resolutionState": "resolved",
                "resolutionSource": "direct_user",
            },
            resume_token="event:question-resolved",
        )
        _, resolution = room_event_projection(resolved)
        self.assertEqual(
            resolution,
            {
                "requestId": "request:plan-review",
                "requestKind": "user_input_required",
                "method": "select",
                "resolutionState": "resolved",
                "resolutionSource": "direct_user",
            },
        )

    def test_tool_projection_separates_public_arguments_and_results(
        self,
    ) -> None:
        cases = (
            (
                "grep",
                {
                    "path": "rag_ime",
                    "pattern": "user_input_required",
                    "outputPreview": (
                        "rag_ime/pi_runtime_v2.py:3082: "
                        "user_input_required"
                    ),
                    "outputTruncated": False,
                },
                {"path": "rag_ime", "pattern": "user_input_required"},
            ),
            (
                "read",
                {
                    "fileName": "agent_event_projection.py",
                    "path": "rag_ime/agent_event_projection.py",
                    "offset": 640,
                    "limit": 220,
                    "outputPreview": "def _room_tool_disclosure(...):",
                    "outputTruncated": False,
                },
                {
                    "fileName": "agent_event_projection.py",
                    "path": "rag_ime/agent_event_projection.py",
                    "offset": 640,
                    "limit": 220,
                },
            ),
        )
        for sequence, (tool_name, public_result, expected_args) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(tool_name=tool_name):
                started = AgentEventEnvelope(
                    event_id=f"event:tool-start:{sequence}",
                    session_id="session:1",
                    turn_id="turn:1",
                    sequence=sequence,
                    created_at_ms=sequence,
                    event_type="tool_started",
                    payload={
                        "toolName": tool_name,
                        "toolCallId": f"call:{sequence}",
                        "args": {
                            **expected_args,
                            "apiKey": "sk-private-credential",
                        },
                        "publicResult": expected_args,
                        "isError": False,
                    },
                    resume_token=f"event:tool-start:{sequence}",
                )
                started_type, started_data = room_event_projection(started)
                self.assertEqual(started_type, "participant_activity")
                self.assertEqual(started_data["arguments"], expected_args)
                self.assertNotIn("result", started_data)
                self.assertNotIn("error", started_data)

                event = AgentEventEnvelope(
                    event_id=f"event:tool:{sequence}",
                    session_id="session:1",
                    turn_id="turn:1",
                    sequence=sequence,
                    created_at_ms=sequence,
                    event_type="tool_finished",
                    payload={
                        "toolName": tool_name,
                        "toolCallId": f"call:{sequence}",
                        "args": {
                            **expected_args,
                            "apiKey": "sk-private-credential",
                            "rawPrompt": "must-not-project",
                        },
                        "result": {
                            "stdout": "raw private output",
                            "providerDiagnostics": "must-not-project",
                        },
                        "publicResult": public_result,
                        "isError": False,
                    },
                    resume_token=f"event:tool:{sequence}",
                )

                event_type, data = room_event_projection(event)

                self.assertEqual(event_type, "participant_activity")
                self.assertEqual(data["arguments"], expected_args)
                self.assertEqual(
                    data["result"],
                    {
                        "outputPreview": public_result["outputPreview"],
                        "outputTruncated": False,
                    },
                )
                encoded = repr(data)
                self.assertNotIn("apiKey", encoded)
                self.assertNotIn("sk-private-credential", encoded)
                self.assertNotIn("raw private output", encoded)
                self.assertNotIn("providerDiagnostics", encoded)

        failed = AgentEventEnvelope(
            event_id="event:tool:error",
            session_id="session:1",
            turn_id="turn:1",
            sequence=3,
            created_at_ms=3,
            event_type="tool_finished",
            payload={
                "toolName": "read",
                "toolCallId": "call:error",
                "args": {"path": "missing.py"},
                "result": {
                    "providerDiagnostics": "private stack",
                },
                "publicResult": {
                    "fileName": "missing.py",
                    "outputPreview": "读取失败，请检查文件权限",
                    "outputTruncated": False,
                    "error": "读取失败，请检查文件权限",
                },
                "isError": True,
            },
            resume_token="event:tool:error",
        )
        _, failed_data = room_event_projection(failed)
        self.assertEqual(
            failed_data["result"],
            {
                "outputPreview": "读取失败，请检查文件权限",
                "outputTruncated": False,
            },
        )
        self.assertEqual(
            failed_data["error"],
            "读取失败，请检查文件权限",
        )
        self.assertNotIn("providerDiagnostics", repr(failed_data))

        oversized = AgentEventEnvelope(
            event_id="event:tool:bounded",
            session_id="session:1",
            turn_id="turn:1",
            sequence=4,
            created_at_ms=4,
            event_type="tool_finished",
            payload={
                "toolName": "grep",
                "toolCallId": "call:bounded",
                "args": {
                    "path": "rag_ime",
                    "pattern": "x" * 500,
                },
                "publicResult": {
                    "path": "rag_ime",
                    "pattern": "x" * 500,
                    "outputPreview": "y" * 6_000,
                    "outputTruncated": True,
                },
                "isError": False,
            },
            resume_token="event:tool:bounded",
        )
        _, oversized_data = room_event_projection(oversized)
        self.assertEqual(
            len(oversized_data["arguments"]["pattern"]),
            500,
        )
        self.assertEqual(
            len(oversized_data["result"]["outputPreview"]),
            2_000,
        )
        self.assertIs(
            oversized_data["result"]["outputTruncated"],
            True,
        )

    def test_room_tool_lifecycle_projects_started_and_finished(
        self,
    ) -> None:
        started = AgentEventEnvelope(
            event_id="event:room-state:start",
            session_id="session:1",
            turn_id="turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="tool_started",
            payload={
                "toolName": "room_state",
                "toolCallId": "call:room-state",
                "args": {
                    "summary": "读取当前 Room 状态",
                    "targetParticipantRef": "P-2",
                    "modelInstruction": "private model context",
                    "invocationReceiptId": "private-receipt",
                },
                "isError": False,
            },
            resume_token="event:room-state:start",
        )

        started_type, started_data = room_event_projection(started)

        self.assertEqual(started_type, "participant_activity")
        self.assertEqual(started_data["toolCallId"], "call:room-state")
        self.assertEqual(started_data["toolName"], "room_state")
        self.assertEqual(
            started_data["arguments"],
            {
                "summary": "读取当前 Room 状态",
                "targetParticipantRef": "P-2",
            },
        )
        self.assertNotIn("result", started_data)
        self.assertNotIn("modelInstruction", repr(started_data))
        self.assertNotIn("private-receipt", repr(started_data))

        finished = AgentEventEnvelope(
            event_id="event:room-state:finish",
            session_id="session:1",
            turn_id="turn:1",
            sequence=2,
            created_at_ms=2,
            event_type="tool_finished",
            payload={
                "toolName": "room_state",
                "toolCallId": "call:room-state",
                "args": {
                    "summary": "读取当前 Room 状态",
                    "targetParticipantRef": "P-2",
                    "modelInstruction": "private model context",
                },
                "result": {
                    "privateModelContext": "must-not-project",
                    "details": {
                        "ok": True,
                        "created": True,
                        "result": {
                            "evidenceRef": "evidence:room-state",
                            "unchanged": False,
                            "stateRevision": "sha256:" + ("a" * 64),
                            "summary": "Room 状态已读取",
                            "status": "ready",
                            "currentResponsibility": {
                                "state": "running",
                                "objective": "private objective",
                                "expectedOutput": "private output",
                            },
                            "participants": [
                                {
                                    "displayName": "private participant",
                                },
                            ],
                            "privateDiagnostics": "must-not-project",
                        },
                    },
                },
                "isError": False,
            },
            resume_token="event:room-state:finish",
        )

        finished_type, finished_data = room_event_projection(finished)

        self.assertEqual(finished_type, "participant_activity")
        self.assertEqual(finished_data["toolCallId"], "call:room-state")
        self.assertEqual(
            finished_data["result"],
            {
                "ok": True,
                "created": True,
                "evidenceRef": "evidence:room-state",
                "unchanged": False,
                "stateRevision": "sha256:" + ("a" * 64),
                "currentResponsibility": {"state": "running"},
                "summary": "Room 状态已读取",
                "status": "ready",
            },
        )
        self.assertNotIn("privateModelContext", repr(finished_data))
        self.assertNotIn("privateDiagnostics", repr(finished_data))
        self.assertNotIn("private participant", repr(finished_data))
        self.assertNotIn("private objective", repr(finished_data))

    def test_room_tool_result_allowlist_covers_other_owned_tools(
        self,
    ) -> None:
        cases = (
            (
                "room_collaborate",
                {
                    "accepted": True,
                    "enqueued": True,
                    "deduplicated": False,
                    "targetParticipantRef": "P-2",
                    "currentResponsibilityContinues": True,
                },
            ),
            (
                "room_post",
                {
                    "published": True,
                    "postRef": "post:1",
                    "deduplicated": False,
                    "currentResponsibilityContinues": True,
                },
            ),
            (
                "room_commit",
                {
                    "accepted": True,
                    "executionPerformed": False,
                    "settlementStaged": True,
                    "terminalForModelTurn": True,
                    "canonicalTool": "room_commit",
                },
            ),
        )
        for sequence, (tool_name, expected_result) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(tool_name=tool_name):
                event_type, data = room_event_projection(
                    AgentEventEnvelope(
                        event_id=f"event:{tool_name}",
                        session_id="session:1",
                        turn_id="turn:1",
                        sequence=sequence,
                        created_at_ms=sequence,
                        event_type="tool_finished",
                        payload={
                            "toolName": tool_name,
                            "toolCallId": f"call:{tool_name}",
                            "args": {
                                "action": "execute",
                                "objective": "bounded objective",
                                "rawPrompt": "must-not-project",
                            },
                            "result": {
                                "details": {
                                    "result": {
                                        **expected_result,
                                        "privatePayload": "must-not-project",
                                    },
                                },
                            },
                            "isError": False,
                        },
                        resume_token=f"event:{tool_name}",
                    )
                )

                self.assertEqual(event_type, "participant_activity")
                self.assertEqual(data["result"], expected_result)
                self.assertEqual(
                    data["arguments"],
                    {
                        "action": "execute",
                        "objective": "bounded objective",
                    },
                )
                self.assertNotIn("privatePayload", repr(data))
                self.assertNotIn("rawPrompt", repr(data))

    def test_non_code_tool_request_projection_keeps_safe_nouns(
        self,
    ) -> None:
        event_type, data = room_event_projection(
            AgentEventEnvelope(
                event_id="event:memory",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=1,
                event_type="tool_finished",
                payload={
                    "toolName": "memory",
                    "toolCallId": "call:memory",
                    "args": {
                        "operation": "search",
                        "query": "Room projection",
                        "path": "memory",
                        "limit": 4,
                        "context": "private prompt context",
                        "rawPrompt": "must-not-project",
                    },
                    "result": {
                        "summary": "找到 4 条结果",
                        "privatePayload": "must-not-project",
                    },
                    "isError": False,
                },
                resume_token="event:memory",
            )
        )

        self.assertEqual(event_type, "participant_activity")
        self.assertEqual(
            data["arguments"],
            {
                "path": "memory",
                "operation": "search",
                "query": "Room projection",
                "limit": 4,
            },
        )
        self.assertEqual(data["result"], {"summary": "找到 4 条结果"})
        self.assertNotIn("private prompt context", repr(data))
        self.assertNotIn("must-not-project", repr(data))

    def test_approval_projection_keeps_only_authoritative_refs(
        self,
    ) -> None:
        event = AgentEventEnvelope(
            event_id="event:approval",
            session_id="session:1",
            turn_id="turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="approval_required",
            payload={
                "approvalId": "approval:plan",
                "requestId": "request:plan",
                "requestKind": "plan_review",
                "toolId": "planning",
                "operation": "plan_review",
                "state": "pending",
                "riskLevel": "R1",
                "payloadSha256": "a" * 64,
                "preview": {
                    "rawPlan": "must-not-project",
                    "providerDiagnostics": "must-not-project",
                },
            },
            resume_token="event:approval",
        )

        event_type, data = room_event_projection(event)

        self.assertEqual(event_type, "participant_activity")
        self.assertEqual(
            data,
            {
                "approvalId": "approval:plan",
                "requestId": "request:plan",
                "requestKind": "plan_review",
                "state": "pending",
                "riskLevel": "R1",
                "toolId": "planning",
                "operation": "plan_review",
            },
        )
        self.assertNotIn("payloadSha256", repr(data))
        self.assertNotIn("rawPlan", repr(data))
        self.assertNotIn("providerDiagnostics", repr(data))

    def test_room_snapshot_and_replay_keep_the_same_public_activity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rag-ime-room-projection-",
        ) as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            sessions = AgentSessionStore(db_path)
            sessions.initialize()
            room_store = AgentRoomStore(
                db_path,
                room_dir=root / "rooms",
            )
            room_store.initialize()

            def participant(
                role_id: str,
                display_name: str,
            ) -> dict[str, str]:
                session = sessions.create(
                    title=f"{display_name} Room Session",
                    role_id=role_id,
                    role_version="1",
                )
                return {
                    "sessionId": str(session["id"]),
                    "roleId": role_id,
                    "roleVersion": "1",
                    "displayName": display_name,
                }

            room = room_store.create(
                title="Projection Room",
                routing_policy="manual_mentions",
                participants=[
                    participant("companion-present-v1", "澄"),
                    participant("companion-firstlight-v1", "Hermes"),
                ],
                created_at_ms=1,
            )
            owner = room["participants"][0]
            event = AgentEventEnvelope(
                event_id="event:question",
                session_id=str(owner["sessionId"]),
                turn_id="session-turn:1",
                sequence=1,
                created_at_ms=2,
                event_type="user_input_required",
                payload={
                    "requestId": "request:question",
                    "requestKind": "plan_review",
                    "method": "select",
                    "title": "审阅计划",
                    "message": "请选择",
                    "options": ["批准", "修改"],
                    "placeholder": "选择一项",
                    "prefill": "批准",
                    "defaultValue": "批准",
                    "timeout": 60_000,
                },
                resume_token="event:question",
            )
            mapped_type, public_data = room_event_projection(event)
            projector = RoomPublicTimelineProjector(
                AgentRoomEventHub(room_store),
            )
            projector.publish_runtime(
                event=event,
                binding={
                    "roomId": str(room["id"]),
                    "rootId": "root:1",
                    "dispatchId": "dispatch:1",
                },
                participant=owner,
                event_type=mapped_type,
                public_data=public_data,
                topic_id=str(room["activeTopicId"]),
            )

            resolved_event = AgentEventEnvelope(
                event_id="event:question-resolved",
                session_id=str(owner["sessionId"]),
                turn_id="session-turn:1",
                sequence=2,
                created_at_ms=3,
                event_type="user_input_required",
                payload={
                    "requestId": "request:question",
                    "method": "select",
                    "resolutionState": "resolved",
                    "resolutionSource": "direct_user",
                },
                resume_token="event:question-resolved",
            )
            resolved_type, resolved_data = room_event_projection(
                resolved_event,
            )
            projector.publish_runtime(
                event=resolved_event,
                binding={
                    "roomId": str(room["id"]),
                    "rootId": "root:1",
                    "dispatchId": "dispatch:1",
                },
                participant=owner,
                event_type=resolved_type,
                public_data=resolved_data,
                topic_id=str(room["activeTopicId"]),
            )

            tool_receipts = (
                (
                    "grep",
                    {
                        "path": "rag_ime",
                        "pattern": "user_input_required",
                        "outputPreview": (
                            "rag_ime/pi_runtime_v2.py: "
                            "user_input_required"
                        ),
                        "outputTruncated": False,
                    },
                ),
                (
                    "read",
                    {
                        "path": "rag_ime/agent_event_projection.py",
                        "offset": 684,
                        "limit": 80,
                        "outputPreview": (
                            "def _room_user_input_disclosure(...):"
                        ),
                        "outputTruncated": False,
                    },
                ),
            )
            for sequence, (tool_name, public_result) in enumerate(
                tool_receipts,
                start=3,
            ):
                tool_event = AgentEventEnvelope(
                    event_id=f"event:{tool_name}",
                    session_id=str(owner["sessionId"]),
                    turn_id="session-turn:1",
                    sequence=sequence,
                    created_at_ms=sequence + 1,
                    event_type="tool_finished",
                    payload={
                        "toolName": tool_name,
                        "toolCallId": f"call:{tool_name}",
                        "args": {
                            **public_result,
                            "apiKey": "never-project",
                        },
                        "result": {
                            "providerDiagnostics": "never-project",
                        },
                        "publicResult": public_result,
                        "isError": False,
                    },
                    resume_token=f"event:{tool_name}",
                )
                tool_type, tool_data = room_event_projection(
                    tool_event,
                )
                projector.publish_runtime(
                    event=tool_event,
                    binding={
                        "roomId": str(room["id"]),
                        "rootId": "root:1",
                        "dispatchId": "dispatch:1",
                    },
                    participant=owner,
                    event_type=tool_type,
                    public_data=tool_data,
                    topic_id=str(room["activeTopicId"]),
                )

            snapshot_events = room_store.snapshot(
                str(room["id"]),
            )["events"]
            replay_events = room_store.list_events(
                str(room["id"]),
            )
            self.assertEqual(snapshot_events, replay_events)
            snapshot_event = next(
                item
                for item in snapshot_events
                if item["payload"]["sourceEventId"]
                == "event:question"
            )
            self.assertEqual(
                snapshot_event["payload"],
                {
                    "sourceEventId": "event:question",
                    "sourceEventType": "user_input_required",
                    "data": {
                        "requestId": "request:question",
                        "requestKind": "plan_review",
                        "method": "select",
                        "title": "审阅计划",
                        "message": "请选择",
                        "options": ["批准", "修改"],
                        "placeholder": "选择一项",
                        "prefill": "批准",
                        "defaultValue": "批准",
                        "timeout": 60_000,
                        "rootId": "root:1",
                        "dispatchId": "dispatch:1",
                    },
                },
            )
            self.assertEqual(
                snapshot_event["sourceSessionId"],
                owner["sessionId"],
            )
            self.assertEqual(snapshot_event["turnId"], "root:1")
            self.assertEqual(
                snapshot_event["participantId"],
                owner["id"],
            )
            resolved_snapshot = next(
                item
                for item in snapshot_events
                if item["payload"]["sourceEventId"]
                == "event:question-resolved"
            )
            self.assertEqual(
                resolved_snapshot["payload"]["data"],
                {
                    "requestId": "request:question",
                    "requestKind": "user_input_required",
                    "method": "select",
                    "resolutionState": "resolved",
                    "resolutionSource": "direct_user",
                    "rootId": "root:1",
                    "dispatchId": "dispatch:1",
                },
            )
            projected_tools = {
                item["payload"]["sourceEventId"]: item["payload"]["data"]
                for item in snapshot_events
                if item["payload"]["sourceEventType"]
                == "tool_finished"
            }
            self.assertEqual(
                projected_tools["event:grep"]["arguments"],
                {
                    "path": "rag_ime",
                    "pattern": "user_input_required",
                },
            )
            self.assertEqual(
                projected_tools["event:grep"]["result"],
                {
                    "outputPreview": (
                        "rag_ime/pi_runtime_v2.py: "
                        "user_input_required"
                    ),
                    "outputTruncated": False,
                },
            )
            self.assertEqual(
                projected_tools["event:read"]["arguments"],
                {
                    "path": "rag_ime/agent_event_projection.py",
                    "offset": 684,
                    "limit": 80,
                },
            )
            self.assertEqual(
                projected_tools["event:read"]["result"],
                {
                    "outputPreview": (
                        "def _room_user_input_disclosure(...):"
                    ),
                    "outputTruncated": False,
                },
            )
            self.assertNotIn(
                "never-project",
                repr(snapshot_events),
            )


if __name__ == "__main__":
    unittest.main()
