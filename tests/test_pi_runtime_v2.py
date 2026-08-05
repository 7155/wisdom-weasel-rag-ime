from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.pi_runtime import PiRuntimeConfig, PiRuntimeError
from rag_ime.pi_runtime_public import (
    canonical_code_tool_name,
    pi_message_completes_public_turn,
    pi_message_is_public,
    pi_message_payload,
    public_code_tool_arguments,
    public_code_tool_activity,
    public_reasoning_summaries,
    public_usage_evidence,
)
from rag_ime.pi_runtime_v2 import (
    PiRuntimeHostClient,
    PiRuntimeHostManager,
    _pi_durable_branch_messages,
    _pi_tool_history_events,
)
from rag_ime.pi_runtime_values import redact_runtime_text


FAKE_HOST = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import signal
import sys
import time

sessions = {}
sequence = 0
log_path = pathlib.Path(os.environ["RAG_IME_PI_AGENT_DIR"]) / "host-requests.jsonl"
model = {"provider": "gpt", "id": "gpt-5.6-luna", "name": "GPT-5.6 Luna",
         "api": "responses", "reasoning": True,
         "thinkingLevels": ["off", "medium", "xhigh", "max"],
         "input": ["text", "image"], "contextWindow": 1000000, "maxTokens": 128000}

def write(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

def result(request, value):
    write({"protocolVersion": "2", "id": request["id"], "ok": True, "result": value})

def event(session_id, turn_id, client_message_id, payload):
    global sequence
    sequence += 1
    write({
        "protocolVersion": "2", "event": "agent.event", "sequence": sequence,
        "sessionId": session_id, "turnId": turn_id,
        "clientMessageId": client_message_id, "payload": payload,
    })

for line in sys.stdin:
    request = json.loads(line)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(request, ensure_ascii=False) + "\n")
    method = request["method"]
    params = request.get("params") or {}
    session_id = params.get("sessionId", "")
    if method == "hello":
        result(request, {"protocol": "rag-ime.pi-runtime-host", "protocolVersion": "2", "hostVersion": "test",
                         "piVersion": "0.80.7", "capabilities": {"multiSession": True, "maxSessions": 4,
                         "settledEvents": True, "dynamicTools": True, "managedPlugins": True,
                         "sessionControlState": True,
                         "transientContext": True,
                         "statelessCompletion": True,
                         "conversationFork": True,
                         "runtimePrimitives": {
                             "continuationEnvelope": "1", "cancelScope": "1",
                             "sessionContinuationQueue": True,
                             "sessionCancelOperationRegistry": True,
                             "sessionCancelOperations": {
                                 "provider": True, "tool": True, "retrySleep": True,
                                 "manualCompaction": True, "autoCompaction": True,
                                 "branchSummary": True, "bashProcess": True,
                                 "continuationTimer": True},
                             "roomTypes": os.environ.get("TEST_ROOM_TYPES") == "1"}}})
    elif method == "completion.once":
        sequence += 1
        write({
            "protocolVersion": "2", "event": "runtime.notice", "sequence": sequence,
            "sessionId": params["requestId"],
            "payload": {"type": "completion_text_delta", "requestId": params["requestId"],
                        "delta": "one-shot reply", "elapsedMs": 350},
        })
        result(request, {
            "requestId": params["requestId"], "text": "one-shot reply",
            "provider": params["provider"], "modelId": params["modelId"],
            "thinkingLevel": params["thinkingLevel"],
            "firstTokenMs": 350,
            "elapsedMs": 4200,
            "usage": {"totalTokens": 32},
        })
    elif method == "completion.cancel":
        result(request, {"requestId": params["requestId"], "cancelled": True})
    elif method == "session.open":
        room_skill = params.get("roomSkillPolicy") or {}
        room_skill_load = ({
            "schemaVersion": "rag-ime.skill-load.v1",
            "name": room_skill["skillId"],
            "catalogRevision": "c" * 64,
            "contentRevision": room_skill["skillHash"],
            "loadReason": "stage_required",
        } if room_skill.get("selection") == "required" else None)
        session = sessions.setdefault(session_id, {
            "sessionId": session_id, "piSessionId": "pi-" + session_id,
            "sessionFile": str(pathlib.Path(os.environ["RAG_IME_PI_SESSION_DIR"]) / (session_id + ".jsonl")),
            "leafId": "", "messages": [], "thinkingLevel": params.get("thinkingLevel", "medium"),
            "model": model,
            "roomCapability": params.get("roomCapability"),
            "activeRoom": ({
                "rootId": "root:stale",
                "dispatchId": "dispatch:stale",
                "generation": 0,
            } if os.environ.get("TEST_STALE_ACTIVE_ROOM") == "1" else None),
            "roomProviderContext": params.get("roomProviderContext"),
            "roomSkillLoad": room_skill_load,
            "isIdle": os.environ.get("TEST_STALE_ACTIVE_ROOM_BUSY") != "1",
            "messageQueue": {"steering": [], "followUp": [], "steeringMode": "one-at-a-time",
                             "followUpMode": "one-at-a-time"},
        })
        result(request, {"snapshot": session, "evictedSessionId": None,
                         "roomSkillLoad": room_skill_load})
    elif method == "session.control_state":
        session = sessions[session_id]
        result(request, {
            "schemaVersion": "rag-ime.pi-session-control-state.v1",
            "sessionId": session_id,
            "isIdle": session.get("isIdle", True),
            "isCompacting": False,
            "activeTurn": None,
            "roomCapability": session.get("roomCapability"),
            "activeRoom": session.get("activeRoom"),
            "sequence": sequence,
        })
    elif method == "session.snapshot":
        if os.environ.get("TEST_SESSION_SNAPSHOT_HANG") == "1":
            time.sleep(2)
        result(request, sessions[session_id])
    elif method == "session.commands":
        result(request, {"commands": [{"name": "skill:plugin-creator",
                                        "description": "Create and propose a managed plugin", "source": "skill"}]})
    elif method == "models.list":
        if os.environ.get("TEST_PARTIAL_STDOUT_EXIT") == "1":
            sys.stdout.write('{"protocolVersion":"2","event":"runtime.notice"')
            sys.stdout.flush()
            os.kill(os.getpid(), signal.SIGKILL)
        result(request, {"models": [model]})
    elif method == "session.thinking.set":
        sessions[session_id]["thinkingLevel"] = params["level"]
        result(request, {"level": params["level"]})
    elif method == "session.prompt":
        turn_id = "turn-" + session_id
        sessions[session_id]["activeTurnId"] = turn_id
        client_message_id = params.get("clientMessageId", "")
        sessions[session_id]["activeClientMessageId"] = client_message_id
        user_entry_id = "entry-user-" + str(len(sessions[session_id].get("forkItems", [])) + 1)
        assistant_entry_id = "entry-assistant-" + str(len(sessions[session_id].get("forkItems", [])) + 1)
        user_message = {"id": user_entry_id, "role": "user", "timestamp": 100,
                        "content": [{"type": "text", "text": params["message"]}]}
        assistant = {"id": assistant_entry_id, "role": "assistant", "timestamp": 101,
                     "content": [{"type": "text", "text": "host reply for " + session_id}]}
        if params["message"] == "duplicate-across-native-followup":
            previous_messages = list(sessions[session_id]["messages"])
            previous_assistant = next(
                item for item in reversed(previous_messages)
                if item.get("role") == "assistant"
            )
            assistant = {
                **assistant,
                "content": [{"type": "text", "text": "second host reply for " + session_id}],
            }
            replayed_assistant = {
                **previous_assistant,
                "id": str(previous_assistant["id"]) + "-replayed",
                "timestamp": 102,
            }
            sessions[session_id]["messages"].extend(
                [user_message, replayed_assistant, assistant]
            )
            durable_messages = [*previous_messages, user_message, assistant]
            sessions[session_id]["entries"] = [
                {
                    "type": "message",
                    "id": "durable-" + str(message["id"]),
                    "message": message,
                }
                for message in durable_messages
            ]
        else:
            sessions[session_id]["messages"].extend([user_message, assistant])
        if params["message"] == "duplicate-final-snapshot":
            sessions[session_id]["messages"].append({
                **assistant,
                "id": assistant_entry_id + "-duplicate",
                "timestamp": 102,
            })
        sessions[session_id].setdefault("forkItems", []).extend([
            {"entryId": user_entry_id, "text": params["message"], "role": "user", "createdAtMs": 100},
            {"entryId": assistant_entry_id, "text": "host reply for " + session_id,
             "role": "assistant", "createdAtMs": 101},
        ])
        sessions[session_id]["leafId"] = assistant_entry_id
        transcript = pathlib.Path(sessions[session_id]["sessionFile"])
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"type": "session", "id": sessions[session_id]["piSessionId"]}) + "\n")
        result(request, {"accepted": True, "turnId": turn_id})
        event(session_id, turn_id, client_message_id, {"type": "agent_start"})
        if params["message"].startswith("approval:"):
            event(session_id, turn_id, client_message_id, {
                "type": "extension_ui_request",
                "id": "ui-approval-1",
                "method": "confirm",
                "title": "RAG-IME-APPROVAL:" + params["message"],
            })
            continue
        if params["message"] == "grouped-questions":
            event(session_id, turn_id, client_message_id, {
                "type": "extension_ui_request",
                "id": "ui-grouped-1",
                "method": "editor",
                "title": "RAG-IME-QUESTIONS:call-grouped-1",
                "prefill": json.dumps({
                    "schemaVersion": "rag-ime.grouped-questions.v2",
                    "questions": [
                        {
                            "id": "deploy_target",
                            "question": "这次部署到哪里？",
                            "options": [
                                {"label": "预发布环境", "description": "先验证变更。"},
                                {"label": "生产环境", "description": "直接面向用户发布。"},
                            ],
                            "recommended": 0,
                        },
                        {
                            "id": "release_window",
                            "question": "什么时候发布？",
                            "options": [
                                {"label": "现在"},
                                {"label": "今晚"},
                            ],
                        },
                    ],
                }, ensure_ascii=False, separators=(",", ":")),
            })
            continue
        if params["message"] == "hang-without-settled":
            continue
        event(session_id, turn_id, client_message_id, {"type": "message_end", "message": assistant})
        event(session_id, turn_id, client_message_id, {"type": "agent_end", "messages": [assistant]})
        if params["message"] == "end-without-settled":
            continue
        time.sleep(0.15)
        event(session_id, turn_id, client_message_id, {"type": "agent_settled"})
    elif method == "approval.resolve":
        result(request, {
            "resolved": True,
            "approvalId": params.get("approvalId", ""),
            "approved": bool(params.get("approved")),
        })
        turn_id = sessions[session_id]["activeTurnId"]
        client_message_id = sessions[session_id].get("activeClientMessageId", "")
        assistant = sessions[session_id]["messages"][-1]
        event(session_id, turn_id, client_message_id, {"type": "message_end", "message": assistant})
        event(session_id, turn_id, client_message_id, {"type": "agent_end", "messages": [assistant]})
        time.sleep(0.15)
        event(session_id, turn_id, client_message_id, {"type": "agent_settled"})
    elif method == "ui.resolve":
        result(request, {"resolved": True, "requestId": params.get("requestId", "")})
        if params.get("requestId") == "ui-grouped-1":
            turn_id = sessions[session_id]["activeTurnId"]
            client_message_id = sessions[session_id].get("activeClientMessageId", "")
            assistant = {
                "id": "entry-assistant-grouped",
                "role": "assistant",
                "timestamp": 102,
                "content": [{"type": "text", "text": str((params.get("response") or {}).get("value") or "")}],
            }
            event(session_id, turn_id, client_message_id, {"type": "message_end", "message": assistant})
            event(session_id, turn_id, client_message_id, {"type": "agent_end", "messages": [assistant]})
            time.sleep(0.15)
            event(session_id, turn_id, client_message_id, {"type": "agent_settled"})
    elif method in {"session.steer", "session.follow_up"}:
        turn_id = "turn-" + session_id
        queue = sessions[session_id]["messageQueue"]
        key = "steering" if method == "session.steer" else "followUp"
        queue[key].append(params["message"])
        delivery = "steer" if method == "session.steer" else "followUp"
        result(request, {"accepted": True, "queued": True, "delivery": delivery,
                         "turnId": turn_id, "messageQueue": queue})
        event(session_id, turn_id, params.get("clientMessageId", ""),
              {"type": "queue_update", "steering": queue["steering"],
               "followUp": queue["followUp"]})
    elif method == "session.fork.candidates":
        result(request, {"items": sessions[session_id].get("forkItems", [])})
    elif method == "session.fork":
        target_id = params["targetSessionId"]
        candidates = sessions[session_id].get("forkItems", [])
        selected = next((item for item in candidates if item["entryId"] == params["entryId"]), None)
        if selected is None:
            result(request, {})
            continue
        target_file = pathlib.Path(os.environ["RAG_IME_PI_SESSION_DIR"]) / ("fork-" + target_id + ".jsonl")
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps({"type": "session", "id": "pi-fork-" + target_id}) + "\n")
        target = {
            "sessionId": target_id, "piSessionId": "pi-fork-" + target_id,
            "sessionFile": str(target_file), "leafId": "", "messages": [], "forkItems": [],
            "thinkingLevel": sessions[session_id]["thinkingLevel"], "model": model,
        }
        sessions[target_id] = target
        result(request, {
            "sourceSessionId": session_id, "targetSessionId": target_id,
            "entryId": params["entryId"],
            "selectedText": selected["text"] if selected["role"] == "user" else "",
            "branchAnchor": params["entryId"], "snapshot": target, "evictedSessionId": None,
        })
    elif method == "session.compact":
        result(request, {
            "summary": "用户要求角色每天整理主题书。",
            "coverageStartEntryId": "entry-user-1",
            "coverageEndEntryId": "entry-assistant-1",
            "tokensBefore": 1200,
            "estimatedTokensAfter": 320,
        })
    elif method == "session.abort":
        turn_id = sessions[session_id].get("activeTurnId", "turn-" + session_id)
        result(request, {
            "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
            "sessionId": session_id,
            "turnId": turn_id,
            "cancelledDecisionIds": [],
            "cancelledUIRequestIds": [],
            "lifecycle": {
                "schemaVersion": "pi.agent-abort-receipt.v1",
                "scopeId": session_id,
                "generation": 1,
                "reason": "user_abort",
                "cancelledContinuationIds": [],
                "cancelledOperationIds": ["provider-" + session_id],
                "failedOperationIds": [],
                "operations": [{
                    "operationId": "provider-" + session_id,
                    "kind": "provider",
                }],
                "pendingOperations": [],
                "drained": True,
                "idle": True,
            },
        })
    elif method == "session.close":
        result(request, {"closed": sessions.pop(session_id, None) is not None})
    elif method == "room.dispatch":
        if params.get("message") == "crash-host-after-room-dispatch":
            os._exit(23)
        if params.get("message") == "event-before-room-dispatch-ack":
            event(session_id, "room-turn-" + params["dispatchId"], params["idempotencyKey"], {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta", "contentIndex": 0, "delta": "working",
                },
                "message": {"role": "assistant", "id": "assistant-before-ack"},
            })
        if params.get("roomCapability") is not None:
            sessions[session_id]["roomCapability"] = params["roomCapability"]
        if params.get("roomProviderContext") is not None:
            sessions[session_id]["roomProviderContext"] = params["roomProviderContext"]
        room_provider = sessions[session_id].get("roomProviderContext") or {}
        result(request, {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted", "status": "accepted",
            "rootId": params["rootId"], "dispatchId": params["dispatchId"],
            "generation": params["generation"],
            "capabilityEpoch": params["capabilityEpoch"],
            "sessionId": session_id,
            "delivery": "prompt", "turnId": "room-turn-" + params["dispatchId"],
            **({"roomSkillLoad": sessions[session_id]["roomSkillLoad"]}
               if sessions[session_id].get("roomSkillLoad") else {}),
            "providerContextReceipt": ({**room_provider,
                "providerRequestId": "room-turn-" + params["dispatchId"]}
                if room_provider else None),
        })
    elif method == "room.cancel":
        result(request, {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied", "status": "applied",
            "cancelId": params["cancelId"],
            "rootId": params["rootId"], "dispatchId": params["dispatchId"],
            "generation": params["generation"], "sessionId": session_id,
            "turnId": params["turnId"],
            "capabilityEpoch": params["capabilityEpoch"],
            "cancelledContinuationIds": [],
            "activeRunAborted": False,
            "cancellationSurfaces": {name: {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": name, "state": "terminated", "targetIds": [],
            } for name in (
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session")},
            "pendingTargets": [],
        })
    elif method == "plugins.list":
        result(request, {"plugins": []})
    else:
        result(request, {})
'''


class PiRuntimeV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-pi-v2-")
        self.root = Path(self.tmp.name)
        self.fake_host = self.root / "fake-host"
        self.fake_host.write_text(FAKE_HOST, encoding="utf-8")
        self.fake_host.chmod(0o755)
        self.store = AgentSessionStore(self.root / "rag-ime.sqlite")
        self.store.initialize()
        self.first = self.store.create(title="first", created_at_ms=100)
        self.second = self.store.create(title="second", created_at_ms=101)
        self.events = AgentEventHub(
            sequence_loader=self.store.max_event_sequence,
            event_recorder=self._record_event,
        )
        self.compactions: list[tuple[str, dict[str, object], str]] = []
        self.runtime = PiRuntimeHostManager(
            config=PiRuntimeConfig(
                enabled=True,
                executable=self.fake_host,
                agent_dir=self.root / "agent",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
                idle_timeout_seconds=0,
                command_timeout_seconds=5,
                provider="gpt",
                model="gpt-5.6-luna",
                pi_version="0.80.7",
                protocol_version="2",
                max_sessions=4,
            ),
            sessions=self.store,
            events=self.events,
            tool_manifest_provider=lambda _session: [{
                "name": "memory",
                "description": "memory operations",
                "parameters": {"type": "object", "properties": {"op": {"type": "string"}}},
            }],
            compaction_observer=self._observe_compaction,
        )

    def tearDown(self) -> None:
        self.runtime.stop()
        self.tmp.cleanup()

    def _observe_compaction(
        self,
        session_id: str,
        result: dict[str, object],
        trigger: str,
    ) -> dict[str, object]:
        self.compactions.append((session_id, dict(result), trigger))
        return {
            "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
            "ok": True,
            "stored": True,
            "status": "checkpointed",
        }

    def test_usage_evidence_distinguishes_cache_report_from_missing_fields(
        self,
    ) -> None:
        self.assertEqual(
            public_usage_evidence({"role": "assistant"}),
            {
                "usageReported": False,
                "cacheUsageReported": False,
            },
        )
        self.assertEqual(
            public_usage_evidence({
                "usage": {"input": 120, "output": 30},
            }),
            {
                "usageReported": True,
                "cacheUsageReported": False,
            },
        )
        self.assertEqual(
            public_usage_evidence({
                "usage": {
                    "input": 120,
                    "output": 30,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                },
            }),
            {
                "usageReported": True,
                "cacheUsageReported": True,
            },
        )

    def test_managed_approval_events_keep_tool_call_and_causal_turn(self) -> None:
        session_id = str(self.first["id"])
        turn_id = f"turn-{session_id}"
        approval = self.store.create_approval(
            session_id=session_id,
            tool_name="workspace_shell",
            operation="run",
            payload_sha256="a" * 64,
            preview={"summary": "运行受控命令"},
            risk_level="R3",
            causal_metadata={"turnId": turn_id},
        )
        approval = self.store.bind_approval_tool_call(
            str(approval["approvalId"]),
            tool_call_id="tool:managed-approval",
        )
        approval_id = str(approval["approvalId"])

        self.runtime.prompt(
            session_id,
            approval_id,
            client_message_id="client:managed-approval",
        )
        _wait_until(
            lambda: self.runtime.has_pending_approval(
                session_id,
                approval_id,
            )
        )
        events, _ = self.events.replay(session_id)
        required = next(
            event
            for event in events
            if event.event_type == "approval_required"
        )
        self.assertEqual(required.payload["toolCallId"], "tool:managed-approval")
        self.assertEqual(required.turn_id, turn_id)

        self.store.decide_approval(
            approval_id,
            approved=True,
            payload_sha256="a" * 64,
        )
        self.runtime.resolve_approval(
            session_id,
            approval_id,
            approved=True,
            resolution_state="external_pending",
        )
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")
        events, _ = self.events.replay(session_id)
        resolved = next(
            event
            for event in events
            if event.event_type == "approval_resolved"
        )
        self.assertEqual(resolved.payload["toolCallId"], "tool:managed-approval")
        self.assertEqual(resolved.turn_id, turn_id)

    def test_grouped_questions_project_once_and_validate_one_answer_map(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(
            session_id,
            "grouped-questions",
            client_message_id="client:grouped-questions",
        )
        _wait_until(lambda: bool(self.runtime.pending_ui_requests(session_id)))

        pending = self.runtime.pending_ui_requests(session_id)
        self.assertEqual(len(pending), 1)
        request = pending[0]
        self.assertEqual(request["requestKind"], "grouped_questions")
        self.assertEqual(request["method"], "editor")
        self.assertEqual(
            request["questions"],
            [
                {
                    "id": "deploy_target",
                    "question": "这次部署到哪里？",
                    "options": [
                        {"label": "预发布环境", "description": "先验证变更。"},
                        {"label": "生产环境", "description": "直接面向用户发布。"},
                    ],
                    "recommended": 0,
                },
                {
                    "id": "release_window",
                    "question": "什么时候发布？",
                    "options": [{"label": "现在"}, {"label": "今晚"}],
                },
            ],
        )
        self.assertNotIn("prefill", request)
        self.assertNotIn("RAG-IME-QUESTIONS", str(request["title"]))

        with self.assertRaisesRegex(PiRuntimeError, "当前问题或可选项不一致"):
            self.runtime.resolve_ui_request(
                session_id,
                str(request["requestId"]),
                response={
                    "value": json.dumps(
                        {
                            "answers": {
                                "deploy_target": {"selected": ["不存在的环境"]},
                                "release_window": {"selected": ["今晚"]},
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "resolutionSource": "direct_user",
                },
            )
        with self.assertRaisesRegex(PiRuntimeError, "当前问题或可选项不一致"):
            self.runtime.resolve_ui_request(
                session_id,
                str(request["requestId"]),
                response={
                    "value": json.dumps(
                        {"answers": {"deploy_target": {"selected": ["预发布环境"]}}},
                        ensure_ascii=False,
                    ),
                    "resolutionSource": "direct_user",
                },
            )
        self.assertEqual(len(self.runtime.pending_ui_requests(session_id)), 1)

        self.runtime.resolve_ui_request(
            session_id,
            str(request["requestId"]),
            response={
                "value": json.dumps(
                    {
                        "answers": {
                            "deploy_target": {"selected": ["预发布环境"]},
                            "release_window": {"selected": ["今晚"]},
                        }
                    },
                    ensure_ascii=False,
                ),
                "resolutionSource": "direct_user",
            },
        )
        _wait_until(
            lambda: any(
                event.event_type == "turn_completed"
                for event in self.events.replay(session_id)[0]
            )
        )
        self.assertEqual(self.store.get(session_id)["status"], "idle")

        events, _ = self.events.replay(session_id)
        required = next(
            event
            for event in events
            if event.event_type == "user_input_required"
            and event.payload.get("requestKind") == "grouped_questions"
        )
        resolved = next(
            event
            for event in events
            if event.event_type == "user_input_required"
            and event.payload.get("resolutionState") == "resolved"
        )
        with self.assertRaisesRegex(PiRuntimeError, "no longer pending"):
            self.runtime.resolve_ui_request(
                session_id,
                str(request["requestId"]),
                response={
                    "value": json.dumps(
                        {
                            "answers": {
                                "deploy_target": {"selected": ["预发布环境"]},
                                "release_window": {"selected": ["今晚"]},
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "resolutionSource": "direct_user",
                },
            )
        completed_message = next(
            event for event in events if event.event_type == "message_completed"
        )
        self.assertEqual(
            completed_message.payload["message"]["blocks"][0]["data"]["text"],
            '{"answers":{"deploy_target":{"selected":["预发布环境"]},"release_window":{"selected":["今晚"]}}}',
        )
        completed = next(event for event in events if event.event_type == "turn_completed")
        self.assertEqual(
            {required.turn_id, resolved.turn_id, completed.turn_id},
            {required.turn_id},
        )

    def test_managed_room_rejects_competing_native_question(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        with self.runtime._lock:
            state = self.runtime._states[session_id]
            state.turn_id = "turn:room-question-owner"
            state.room_skill_policy = {
                "selection": "required",
                "skillId": "alignment-and-decision",
                "skillHash": "a" * 64,
            }

        self.runtime._handle_ui_request(
            session_id,
            "turn:room-question-owner",
            {
                "id": "ui-room-question-1",
                "method": "editor",
                "title": "RAG-IME-QUESTIONS:room-question-1",
                "prefill": json.dumps({
                    "schemaVersion": "rag-ime.grouped-questions.v2",
                    "questions": [],
                }),
            },
        )

        self.assertEqual(self.runtime.pending_ui_requests(session_id), [])
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        resolution = next(
            request
            for request in reversed(requests)
            if request["method"] == "ui.resolve"
        )
        self.assertEqual(
            resolution["params"],
            {
                "sessionId": session_id,
                "requestId": "ui-room-question-1",
                "response": {"cancelled": True},
            },
        )
        events, _ = self.events.replay(session_id)
        rejected = next(
            event
            for event in events
            if event.payload.get("requestKind")
            == "room_native_question_rejected"
        )
        self.assertEqual(rejected.payload["resolutionState"], "cancelled")
        self.assertEqual(rejected.turn_id, "turn:room-question-owner")

    def test_stateless_completion_does_not_open_or_persist_a_session(self) -> None:
        deltas: list[str] = []
        result = self.runtime.complete_once(
            request_id="surface-one-shot-1",
            provider="deepseek",
            model_id="deepseek-v4-flash",
            thinking_level="high",
            message="只回复这一次",
            on_text_delta=deltas.append,
            timeout_seconds=15,
        )

        self.assertEqual(result["text"], "one-shot reply")
        self.assertEqual(result["elapsedMs"], 4200)
        self.assertEqual(result["firstTokenMs"], 350)
        self.assertEqual(deltas, ["one-shot reply"])
        self.assertEqual(list((self.root / "sessions").glob("*.jsonl")), [])
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        methods = [request["method"] for request in requests]
        self.assertEqual(methods, ["hello", "completion.once"])
        params = requests[-1]["params"]
        self.assertEqual(params["provider"], "deepseek")
        self.assertEqual(params["modelId"], "deepseek-v4-flash")
        self.assertEqual(params["thinkingLevel"], "high")
        self.assertNotIn("sessionId", params)
        self.assertNotIn("images", params)
        self.assertTrue(self.runtime.runtime_status()["capabilities"]["statelessCompletion"])

    def test_stateless_completion_timeout_retires_host_before_retry(self) -> None:
        first_client = self.runtime._host()
        first_host_identity = first_client.host_identity
        original_send = first_client.send

        def timeout_completion(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if method == "completion.once":
                raise PiRuntimeError(
                    "Pi Runtime Host command timed out: completion.once"
                )
            return original_send(method, params, timeout=timeout)

        with patch.object(first_client, "send", side_effect=timeout_completion):
            with self.assertRaisesRegex(
                PiRuntimeError,
                "command timed out: completion.once",
            ):
                self.runtime.complete_once(
                    request_id="surface-timeout-1",
                    provider="deepseek",
                    model_id="deepseek-v4-flash",
                    thinking_level="high",
                    message="这一次模拟无响应",
                    timeout_seconds=15,
                )

        timed_out_status = self.runtime.runtime_status()
        receipt = timed_out_status["runtimeHostKillGate"]["lastKillReceipt"]
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["hostIdentity"], first_host_identity)
        self.assertEqual(receipt["requestKind"], "cancel_timeout")
        self.assertEqual(receipt["requestedBy"], "completion:surface-timeout-1")
        self.assertEqual(receipt["state"], "terminated")
        self.assertEqual(timed_out_status["status"], "faulted")
        self.assertFalse(first_client.running)

        retried = self.runtime.complete_once(
            request_id="surface-timeout-retry",
            provider="deepseek",
            model_id="deepseek-v4-flash",
            thinking_level="high",
            message="新 Host 应该正常完成",
            timeout_seconds=15,
        )

        self.assertEqual(retried["text"], "one-shot reply")
        self.assertIsNot(self.runtime._client, first_client)
        assert self.runtime._client is not None
        self.assertNotEqual(
            self.runtime._client.host_identity,
            first_host_identity,
        )

    def test_plugin_mutations_use_a_dedicated_approval_capability(self) -> None:
        self.runtime.stop()
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                tool_gateway_token="tool-gateway-only",
                plugin_approval_token="plugin-approval-only",
            ),
            sessions=self.store,
            events=self.events,
            tool_manifest_provider=lambda _session: [],
        )

        self.runtime.plugin_install({"sourcePath": "/tmp/plugin"})
        self.runtime.plugin_enable(
            "plugin:test",
            enabled=True,
            expected_active_digest="a" * 64,
            expected_enabled=False,
        )
        self.runtime.plugin_rollback(
            "plugin:test",
            expected_active_digest="b" * 64,
            target_digest="c" * 64,
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        mutations = [
            request
            for request in requests
            if request["method"]
            in {"plugins.install", "plugins.enable", "plugins.rollback"}
        ]
        self.assertEqual(len(mutations), 3)
        self.assertTrue(
            all(
                request["params"]["approvalToken"] == "plugin-approval-only"
                for request in mutations
            )
        )
        self.assertNotIn("tool-gateway-only", json.dumps(mutations))

    def test_session_context_resource_settings_reach_pi_session_open(self) -> None:
        session_id = str(self.first["id"])
        self.store.set_runtime_policy(
            session_id,
            mode="assistant",
            tool_profile_version="control-center-v1",
            allowed_tools=None,
            project_context_enabled=False,
            pi_skills_enabled=True,
            codex_skills_enabled=True,
        )

        self.runtime.ensure(session_id)

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        opened = next(request for request in requests if request["method"] == "session.open")
        self.assertTrue(opened["params"]["noContextFiles"])
        self.assertTrue(opened["params"]["piSkillsEnabled"])
        self.assertTrue(opened["params"]["codexSkillsEnabled"])

    def test_room_capability_identity_reaches_session_open_unchanged(self) -> None:
        self.runtime.stop()
        capability = {
            "manifestId": "manifest:1",
            "manifestHash": "a" * 64,
            "promptCompileReceiptId": "prompt:1",
            "promptPlanHash": "b" * 64,
            "compiledRuntimeProfileRef": {"profileId": "profile:1", "revision": "1", "contentHash": "sha256:abcdef"},
            "capabilityEpoch": 4,
        }
        self.runtime = PiRuntimeHostManager(
            config=self.runtime.config,
            sessions=self.store,
            events=self.events,
            session_context_provider=lambda _session: {
                "roomCapability": capability,
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "dynamic-room-tail",
                "roomProviderContext": {
                    "journalId": "journal:1",
                    "throughSequence": 1,
                    "projectionHash": "c" * 64,
                },
                "roomSkillPolicy": {
                    "selection": "required",
                    "skillId": "test-driven-implementation",
                    "skillHash": "d" * 64,
                },
            },
            tool_manifest_provider=lambda _session: [],
        )
        self.runtime.ensure(str(self.first["id"]))
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        opened = [request for request in requests if request["method"] == "session.open"][-1]
        self.assertEqual(opened["params"]["roomCapability"], capability)
        self.assertEqual(opened["params"]["systemPrompt"], "stable-room-prefix")
        self.assertEqual(opened["params"]["sessionContext"], "generic-agent-rag")
        self.assertEqual(opened["params"]["roomContext"], "dynamic-room-tail")
        self.assertEqual(opened["params"]["roomProviderContext"]["journalId"], "journal:1")
        self.assertEqual(
            opened["params"]["roomSkillPolicy"]["skillId"],
            "test-driven-implementation",
        )

    def test_typed_room_rpc_is_negotiated_and_correlated_across_the_host_process(self) -> None:
        self.runtime.stop()
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=lambda _session: {
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
            },
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        payload = {
            "targetSessionId": session_id,
            "rootId": "root:cross-process",
            "dispatchId": "dispatch:cross-process",
            "generation": 4,
            "capabilityEpoch": 0,
            "attempt": 0,
            "idempotencyKey": "cross-process-key",
        }

        receipt = self.runtime.dispatch_room(
            payload,
            message="Execute the bounded Room task.",
            lease_token="lease-token:cross-process",
        )
        with patch.object(
            self.runtime,
            "ensure",
            side_effect=AssertionError("Room cancellation must not rebind the active Session"),
        ):
            cancelled = self.runtime.cancel_room(
                cancel_id="cancel:cross-process",
                session_id=session_id,
                root_id="root:cross-process",
                dispatch_id="dispatch:cross-process",
                generation=5,
                turn_id="room-turn-dispatch:cross-process",
                capability_epoch=0,
            )

        self.assertTrue(
            self.runtime.runtime_status()["capabilities"]["runtimePrimitives"]["roomTypes"]
        )
        self.assertEqual(receipt["turnId"], "room-turn-dispatch:cross-process")
        self.assertEqual(cancelled["receiptKind"], "cancel_applied")
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        methods = [item["method"] for item in requests]
        self.assertEqual(methods[:3], ["hello", "session.open", "room.dispatch"])
        self.assertEqual(methods[-1], "room.cancel")
        delivered = next(item for item in requests if item["method"] == "room.dispatch")
        self.assertEqual(delivered["params"]["leaseToken"], "lease-token:cross-process")
        self.assertEqual(delivered["params"]["dispatchAttempt"], 0)
        delivered_cancel = next(
            item for item in requests if item["method"] == "room.cancel"
        )
        self.assertEqual(
            {
                key: delivered_cancel["params"][key]
                for key in (
                    "cancelId",
                    "sessionId",
                    "rootId",
                    "dispatchId",
                    "generation",
                    "turnId",
                    "capabilityEpoch",
                )
            },
            {
                "cancelId": "cancel:cross-process",
                "sessionId": session_id,
                "rootId": "root:cross-process",
                "dispatchId": "dispatch:cross-process",
                "generation": 5,
                "turnId": "room-turn-dispatch:cross-process",
                "capabilityEpoch": 0,
            },
        )

        crashed_payload = dict(payload)
        crashed_payload.update(
            {"dispatchId": "dispatch:crashed-host", "idempotencyKey": "crashed-host-key"}
        )
        with self.assertRaises(PiRuntimeError):
            self.runtime.dispatch_room(
                crashed_payload,
                message="crash-host-after-room-dispatch",
                lease_token="lease-token:crashed-host",
            )
        self.assertEqual(self.runtime.runtime_status()["status"], "faulted")

    def test_room_cancel_rejects_forged_runtime_receipt_lineage(self) -> None:
        self.runtime.stop()
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=lambda _session: {
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
            },
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        dispatch_id = "dispatch:cancel-response-lineage"
        accepted = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:cancel-response-lineage",
                "dispatchId": dispatch_id,
                "generation": 2,
                "capabilityEpoch": 3,
                "attempt": 0,
                "idempotencyKey": "cancel-response-lineage",
            },
            message="Start a bounded cancellation lineage test.",
            lease_token="lease:cancel-response-lineage",
        )
        forged = {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "cancelId": "cancel:response-lineage",
            "sessionId": session_id,
            "rootId": "root:cancel-response-lineage",
            "dispatchId": dispatch_id,
            "generation": 3,
            "turnId": "turn:forged",
            "capabilityEpoch": 3,
            "cancellationSurfaces": {
                surface: {
                    "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                    "surface": surface,
                    "state": "terminated",
                    "targetIds": [],
                }
                for surface in (
                    "provider", "tool", "exec", "retry", "compaction",
                    "branch_summary", "timer", "continuation", "session",
                )
            },
            "pendingTargets": [],
        }
        client = self.runtime._require_client()
        with patch.object(client, "send", return_value=forged):
            with self.assertRaisesRegex(
                PiRuntimeError,
                "invalid Room cancellation receipt",
            ):
                self.runtime.cancel_room(
                    cancel_id="cancel:response-lineage",
                    session_id=session_id,
                    root_id="root:cancel-response-lineage",
                    dispatch_id=dispatch_id,
                    generation=3,
                    turn_id=str(accepted["turnId"]),
                    capability_epoch=3,
                )

    def test_room_retry_attempt_uses_a_distinct_persisted_delivery_key(
        self,
    ) -> None:
        self.runtime.stop()
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=lambda _session: {
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
            },
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        logical_key = "room-task:stable-logical-key"
        base = {
            "targetSessionId": session_id,
            "rootId": "root:runtime-retry-key",
            "generation": 0,
            "idempotencyKey": logical_key,
            "attempt": 0,
        }

        for invalid_attempt in (None, -1, True):
            invalid_payload = {
                **base,
                "dispatchId": "dispatch:runtime-invalid-attempt",
            }
            if invalid_attempt is None:
                invalid_payload.pop("attempt")
            else:
                invalid_payload["attempt"] = invalid_attempt
            with self.subTest(invalid_attempt=invalid_attempt):
                with self.assertRaisesRegex(
                    ValueError,
                    "attempt must be a non-negative integer",
                ):
                    self.runtime.dispatch_room(
                        invalid_payload,
                        message="Invalid durable delivery.",
                        lease_token="lease-token:invalid-attempt",
                    )

        self.runtime.dispatch_room(
            {
                **base,
                "dispatchId": "dispatch:runtime-attempt-zero",
                "attempt": 0,
            },
            message="First durable delivery.",
            lease_token="lease-token:attempt-zero",
        )
        self.runtime.dispatch_room(
            {
                **base,
                "dispatchId": "dispatch:runtime-attempt-one",
                "attempt": 1,
            },
            message="Retry after a confirmed final failure.",
            lease_token="lease-token:attempt-one",
        )
        longest_host_key = "k" * 512
        self.runtime.dispatch_room(
            {
                **base,
                "dispatchId": "dispatch:runtime-attempt-long-key",
                "idempotencyKey": longest_host_key,
                "attempt": 2,
            },
            message="Retry a Dispatch whose logical key fills the Host limit.",
            lease_token="lease-token:attempt-long-key",
        )

        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        delivered = [
            item["params"]
            for item in requests
            if item["method"] == "room.dispatch"
        ]
        self.assertEqual(delivered[0]["idempotencyKey"], logical_key)
        self.assertEqual(
            [request["dispatchAttempt"] for request in delivered],
            [0, 1, 2],
        )
        self.assertEqual(
            delivered[1]["idempotencyKey"],
            f"{logical_key}:runtime-attempt:1",
        )
        self.assertEqual(len(delivered[2]["idempotencyKey"]), 512)
        self.assertTrue(
            delivered[2]["idempotencyKey"].endswith(
                ":runtime-attempt:2"
            )
        )
        self.assertNotEqual(
            delivered[2]["idempotencyKey"],
            longest_host_key,
        )
        self.assertEqual(
            base["idempotencyKey"],
            logical_key,
            "the logical Dispatch identity must remain unchanged",
        )

    def test_room_dispatch_ack_is_not_blocked_by_slow_event_projection(self) -> None:
        self.runtime.stop()
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=lambda _session: {
                "providerContext": "bounded-room-context",
            },
            tool_manifest_provider=lambda _session: [],
        )
        observer_started = threading.Event()
        release_observer = threading.Event()

        def slow_projection(envelope) -> None:
            if envelope.event_type != "text_delta":
                return
            observer_started.set()
            release_observer.wait(timeout=2.0)

        remove_observer = self.events.add_observer(slow_projection)
        try:
            started_at = time.monotonic()
            receipt = self.runtime.dispatch_room(
                {
                    "targetSessionId": str(self.first["id"]),
                    "rootId": "root:event-lane",
                    "dispatchId": "dispatch:event-lane",
                    "generation": 0,
                    "capabilityEpoch": 1,
                    "attempt": 0,
                    "idempotencyKey": "event-lane:1",
                },
                message="event-before-room-dispatch-ack",
                lease_token="lease:event-lane",
            )
            elapsed = time.monotonic() - started_at

            self.assertTrue(observer_started.wait(timeout=1.0))
            self.assertEqual(receipt["receiptKind"], "dispatch_accepted")
            self.assertLess(elapsed, 1.0)
        finally:
            release_observer.set()
            remove_observer()

    def test_room_handoff_uses_control_state_instead_of_full_snapshot(
        self,
    ) -> None:
        self.runtime.stop()
        state = {"room": False}

        def context_provider(_session):
            if not state["room"]:
                return {}
            return {
                "roomCapability": {
                    "manifestId": "manifest:handoff",
                    "manifestHash": "a" * 64,
                    "promptCompileReceiptId": "prompt:handoff",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:handoff",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "capabilityEpoch": 2,
                    "rootId": "root:handoff",
                    "dispatchId": "dispatch:handoff",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "providerContext": "bounded-room-context",
                "roomRecoveryContext": "bounded-room-recovery",
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                command_timeout_seconds=5.0,
                provider_environment={
                    "TEST_ROOM_TYPES": "1",
                    "TEST_SESSION_SNAPSHOT_HANG": "1",
                },
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        state["room"] = True

        receipt = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:handoff",
                "dispatchId": "dispatch:handoff",
                "generation": 0,
                "capabilityEpoch": 2,
                "attempt": 0,
                "idempotencyKey": "handoff:1",
            },
            message="Execute the handed-off Room task.",
            lease_token="lease:handoff",
        )

        self.assertEqual(receipt["receiptKind"], "dispatch_accepted")
        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        methods = [item["method"] for item in requests]
        self.assertEqual(methods.count("session.open"), 2)
        self.assertIn("session.control_state", methods)
        self.assertNotIn("session.snapshot", methods)
        self.assertLess(
            methods.index("session.control_state"),
            methods.index("session.close"),
        )

    def test_room_control_state_timeout_retires_host_before_retry(self) -> None:
        self.runtime.stop()

        def context_provider(_session):
            return {
                "roomCapability": {
                    "manifestId": "manifest:control-timeout",
                    "manifestHash": "a" * 64,
                    "promptCompileReceiptId": "prompt:control-timeout",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:control-timeout",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "capabilityEpoch": 2,
                    "rootId": "root:control-timeout",
                    "dispatchId": "dispatch:control-timeout",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "providerContext": "bounded-room-context",
                "roomRecoveryContext": "bounded-room-recovery",
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        first_client = self.runtime._host()
        first_host_identity = first_client.host_identity
        original_send = first_client.send
        intent_calls: list[str] = []
        payload = {
            "targetSessionId": session_id,
            "rootId": "root:control-timeout",
            "dispatchId": "dispatch:control-timeout",
            "generation": 0,
            "capabilityEpoch": 2,
            "attempt": 0,
            "idempotencyKey": "control-timeout:1",
        }

        def timeout_control_state(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if method == "session.control_state":
                raise PiRuntimeError(
                    "Pi Runtime Host command timed out: session.control_state"
                )
            return original_send(method, params, timeout=timeout)

        with patch.object(
            first_client,
            "send",
            side_effect=timeout_control_state,
        ):
            with self.assertRaisesRegex(
                PiRuntimeError,
                "command timed out: session.control_state",
            ):
                self.runtime.dispatch_room(
                    payload,
                    message="Execute after a bounded control-state handoff.",
                    lease_token="lease:control-timeout:0",
                    record_intent=lambda: intent_calls.append("intent"),
                )

        timed_out_status = self.runtime.runtime_status()
        receipt = timed_out_status["runtimeHostKillGate"]["lastKillReceipt"]
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["hostIdentity"], first_host_identity)
        self.assertEqual(receipt["requestedBy"], "room:dispatch:control-timeout")
        self.assertEqual(receipt["state"], "terminated")
        self.assertEqual(timed_out_status["status"], "faulted")
        self.assertFalse(first_client.running)
        self.assertEqual(intent_calls, [])

        payload["attempt"] = 1
        retried = self.runtime.dispatch_room(
            payload,
            message="Execute after a bounded control-state handoff.",
            lease_token="lease:control-timeout:1",
            record_intent=lambda: intent_calls.append("intent"),
        )

        self.assertEqual(retried["receiptKind"], "dispatch_accepted")
        self.assertEqual(intent_calls, ["intent"])

    def test_room_dispatch_reuses_session_for_delta_and_task_switch_epoch(self) -> None:
        self.runtime.stop()
        context_revision = {"value": 1}

        def context_provider(_session):
            revision = context_revision["value"]
            root_id = "root:stable" if revision < 3 else "root:next"
            context_epoch = 1 if revision < 3 else 2
            return {
                "roomCapability": {
                    "manifestId": f"manifest:{revision}",
                    "manifestHash": ("a" if revision == 1 else "b") * 64,
                    "promptCompileReceiptId": f"prompt:{revision}",
                    "promptPlanHash": ("c" if revision == 1 else "d") * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:stable",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "capabilityEpoch": 4,
                    "rootId": root_id,
                    "dispatchId": f"dispatch:{revision}",
                    "generation": 0,
                    "contextEpoch": context_epoch,
                    "contextEpochReason": (
                        "session_open" if revision < 3 else "task_switch"
                    ),
                    "runtimeBindingHash": (
                        "e" if revision == 1 else "8" if revision == 2 else "9"
                    ) * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": f"generic-agent-rag-{revision}",
                "providerContext": f"room-bootstrap-{revision}",
                "providerContextDelta": f"room-delta-{revision}",
                "roomRecoveryContext": f"room-recovery-{revision}",
                "roomProviderContext": {
                    "journalId": f"journal:{revision}",
                    "throughSequence": revision,
                    "projectionHash": ("f" if revision == 1 else "0") * 64,
                },
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])

        first = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:stable",
                "dispatchId": "dispatch:1",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "stable:1",
            },
            message="first bounded task",
            lease_token="lease:1",
        )
        context_revision["value"] = 2
        second = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:stable",
                "dispatchId": "dispatch:2",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "stable:2",
            },
            message="second bounded task",
            lease_token="lease:2",
        )
        context_revision["value"] = 3
        third = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:next",
                "dispatchId": "dispatch:3",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "next:3",
            },
            message="third task starts a new context epoch",
            lease_token="lease:3",
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(sum(item["method"] == "session.open" for item in requests), 1)
        self.assertFalse(any(item["method"] == "session.close" for item in requests))
        delivered = [item for item in requests if item["method"] == "room.dispatch"]
        self.assertEqual(len(delivered), 3)
        self.assertEqual(delivered[1]["params"]["roomContext"], "room-delta-2")
        self.assertEqual(
            delivered[1]["params"]["roomRecoveryContext"],
            "room-recovery-2",
        )
        self.assertEqual(
            delivered[1]["params"]["roomProviderContext"]["journalId"],
            "journal:2",
        )
        self.assertEqual(
            delivered[1]["params"]["roomCapability"]["promptPlanHash"],
            "d" * 64,
        )
        self.assertEqual(first["providerContextReceipt"]["journalId"], "journal:1")
        self.assertEqual(second["providerContextReceipt"]["journalId"], "journal:2")
        self.assertEqual(delivered[2]["params"]["roomContext"], "room-bootstrap-3")
        self.assertEqual(delivered[2]["params"]["roomCapability"]["contextEpoch"], 2)
        self.assertEqual(third["providerContextReceipt"]["journalId"], "journal:3")

    def test_room_retry_reuses_sealed_context_when_no_delta_remains(
        self,
    ) -> None:
        self.runtime.stop()
        initial_delivery = {"value": True}

        def context_provider(_session):
            return {
                "sessionContext": "generic-agent-rag",
                "providerContext": (
                    "governed-room-task"
                    if initial_delivery["value"]
                    else ""
                ),
                "providerContextDelta": "",
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        payload = {
            "targetSessionId": session_id,
            "rootId": "root:sealed-retry",
            "dispatchId": "dispatch:sealed-retry",
            "generation": 0,
            "capabilityEpoch": 1,
            "attempt": 0,
            "idempotencyKey": "sealed-retry",
        }

        self.runtime.dispatch_room(
            payload,
            message="First bounded delivery.",
            lease_token="lease:sealed-retry:0",
        )
        initial_delivery["value"] = False
        retried = self.runtime.dispatch_room(
            {**payload, "attempt": 1},
            message="Retry after the task context was sealed.",
            lease_token="lease:sealed-retry:1",
        )

        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        delivered = [
            request["params"]
            for request in requests
            if request["method"] == "room.dispatch"
        ]
        self.assertEqual(retried["receiptKind"], "dispatch_accepted")
        self.assertEqual(len(delivered), 2)
        self.assertEqual(delivered[1]["dispatchAttempt"], 1)
        self.assertEqual(delivered[1]["roomContext"], "")

    def test_room_dispatch_reopens_session_when_required_skill_changes(self) -> None:
        self.runtime.stop()
        stage = {"value": "implementation"}

        def context_provider(_session):
            review = stage["value"] == "review"
            marker = "b" if review else "a"
            skill_id = "independent-review" if review else "implementation-execution"
            return {
                "roomCapability": {
                    "manifestId": f"manifest:skill:{stage['value']}",
                    "manifestHash": marker * 64,
                    "promptCompileReceiptId": f"prompt:skill:{stage['value']}",
                    "promptPlanHash": marker * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:skill-switch",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "capabilityEpoch": 4,
                    "rootId": "root:skill-switch",
                    "dispatchId": f"dispatch:{stage['value']}",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": marker * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "providerContext": f"room-context-{stage['value']}",
                "roomRecoveryContext": f"room-recovery-{stage['value']}",
                "roomProviderContext": {
                    "journalId": f"journal:{stage['value']}",
                    "throughSequence": 1,
                    "projectionHash": marker * 64,
                },
                "roomSkillPolicy": {
                    "selection": "required",
                    "skillId": skill_id,
                    "skillHash": marker * 64,
                },
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        first = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:skill-switch",
                "dispatchId": "dispatch:implementation",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "skill-switch:implementation",
            },
            message="Implement the bounded change.",
            lease_token="lease:skill-switch:implementation",
        )
        stage["value"] = "review"
        second = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:skill-switch",
                "dispatchId": "dispatch:review",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "skill-switch:review",
            },
            message="Review the bounded change.",
            lease_token="lease:skill-switch:review",
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened = [item for item in requests if item["method"] == "session.open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(
            [item["params"]["roomSkillPolicy"]["skillId"] for item in opened],
            ["implementation-execution", "independent-review"],
        )
        self.assertEqual(
            sum(item["method"] == "session.close" for item in requests),
            1,
        )
        self.assertEqual(
            first["roomSkillLoad"]["name"],
            "implementation-execution",
        )
        self.assertEqual(second["roomSkillLoad"]["name"], "independent-review")

    def test_room_dispatch_reopens_busy_session_with_stale_active_room(self) -> None:
        self.runtime.stop()
        revision = {"value": 1}

        def context_provider(_session):
            current = revision["value"]
            return {
                "roomCapability": {
                    "manifestId": f"manifest:stale-active:{current}",
                    "manifestHash": ("a" if current == 1 else "b") * 64,
                    "promptCompileReceiptId": f"prompt:stale-active:{current}",
                    "promptPlanHash": ("c" if current == 1 else "d") * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:stale-active",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "capabilityEpoch": current,
                    "rootId": f"root:stale-active:{current}",
                    "dispatchId": f"dispatch:stale-active:{current}",
                    "generation": 0,
                    "contextEpoch": current,
                    "contextEpochReason": (
                        "session_open" if current == 1 else "task_switch"
                    ),
                    "runtimeBindingHash": ("e" if current == 1 else "f") * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": f"room-bootstrap-{current}",
                "roomRecoveryContext": f"room-recovery-{current}",
                "roomProviderContext": {
                    "journalId": f"journal:stale-active:{current}",
                    "throughSequence": current,
                    "projectionHash": ("0" if current == 1 else "1") * 64,
                },
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={
                    "TEST_ROOM_TYPES": "1",
                    "TEST_STALE_ACTIVE_ROOM": "1",
                    "TEST_STALE_ACTIVE_ROOM_BUSY": "1",
                },
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:stale-active:1",
                "dispatchId": "dispatch:stale-active:1",
                "generation": 0,
                "capabilityEpoch": 1,
                "attempt": 0,
                "idempotencyKey": "stale-active:1",
            },
            message="first task",
            lease_token="lease:stale-active:1",
        )
        revision["value"] = 2

        receipt = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:stale-active:2",
                "dispatchId": "dispatch:stale-active:2",
                "generation": 0,
                "capabilityEpoch": 2,
                "attempt": 0,
                "idempotencyKey": "stale-active:2",
            },
            message="replacement task",
            lease_token="lease:stale-active:2",
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        methods = [request["method"] for request in requests]
        self.assertEqual(methods.count("session.open"), 2)
        self.assertEqual(methods.count("session.close"), 1)
        self.assertIn("session.control_state", methods)
        self.assertEqual(receipt["dispatchId"], "dispatch:stale-active:2")

    def test_sealed_room_maintenance_reuses_idle_session_after_capability_revocation(self) -> None:
        self.runtime.stop()
        state = {"revoked": False}
        manifest_id = "manifest:settled-compaction"
        manifest_hash = "a" * 64

        def context_provider(_session):
            room_capability = {
                "manifestId": manifest_id,
                "manifestHash": manifest_hash,
                "capabilityEpoch": 8 if state["revoked"] else 7,
            }
            if state["revoked"]:
                return {
                    "roomCapability": {
                        **room_capability,
                        "status": "revoked",
                    },
                    "sessionContext": "settled-room-recovery",
                }
            return {
                "roomCapability": {
                    **room_capability,
                    "promptCompileReceiptId": "prompt:settled-compaction",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:settled-compaction",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
                "roomRecoveryContext": "sealed-room-recovery",
            }

        self.runtime = PiRuntimeHostManager(
            config=self.runtime.config,
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
            compaction_observer=self._observe_compaction,
        )
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        state["revoked"] = True

        self.assertEqual(self.runtime.debug_context(session_id), {})
        self.assertEqual(self.runtime.messages(session_id), [])
        compacted = self.runtime.compact(session_id, "保留受管恢复事实")

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        methods = [request["method"] for request in requests]
        self.assertEqual(methods.count("session.open"), 1)
        self.assertNotIn("session.close", methods)
        self.assertEqual(
            methods[-2:],
            [
                "session.control_state",
                "session.compact",
            ],
        )
        self.assertEqual(methods.count("session.snapshot"), 1)
        self.assertTrue(compacted["memoryCheckpoint"]["stored"])

    def test_revoked_room_compaction_recovers_stale_and_nonresident_sessions(self) -> None:
        self.runtime.stop()
        state = {
            "revoked": False,
            "manifestId": "manifest:resident-compaction",
        }
        manifest_hash = "d" * 64

        def context_provider(_session):
            if state["revoked"]:
                return {
                    "roomCapability": {
                        "manifestId": state["manifestId"],
                        "manifestHash": manifest_hash,
                        "capabilityEpoch": 5,
                        "status": "revoked",
                    },
                    "sessionContext": "bounded-room-recovery",
                }
            return {
                "roomCapability": {
                    "manifestId": state["manifestId"],
                    "manifestHash": manifest_hash,
                    "capabilityEpoch": 4,
                    "promptCompileReceiptId": "prompt:resident-compaction",
                    "promptPlanHash": "e" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:resident-compaction",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "rootId": "root:resident-compaction",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": "f" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
                "roomRecoveryContext": "bounded-room-recovery",
            }

        self.runtime = PiRuntimeHostManager(
            config=self.runtime.config,
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
            compaction_observer=self._observe_compaction,
        )
        session_id = str(self.first["id"])
        opened = self.runtime.ensure(session_id)
        original_transcript = str(opened["state"]["sessionFile"])
        state["revoked"] = True
        state["manifestId"] = "manifest:revoked-compaction"

        stale_compacted = self.runtime.compact(
            session_id,
            "保留陈旧 Room 恢复事实",
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened_requests = [
            request for request in requests if request["method"] == "session.open"
        ]
        self.assertEqual(len(opened_requests), 2)
        self.assertEqual(
            sum(request["method"] == "session.close" for request in requests),
            1,
        )
        ordinary_open = opened_requests[-1]["params"]
        self.assertNotIn("roomCapability", ordinary_open)
        self.assertNotIn("roomContext", ordinary_open)
        self.assertEqual(ordinary_open["sessionContext"], "bounded-room-recovery")
        self.assertEqual(ordinary_open["sessionFile"], original_transcript)
        self.assertTrue(stale_compacted["memoryCheckpoint"]["stored"])

        self.runtime.stop()
        nonresident_compacted = self.runtime.compact(
            session_id,
            "保留非驻留 Room 恢复事实",
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened_requests = [
            request for request in requests if request["method"] == "session.open"
        ]
        self.assertEqual(len(opened_requests), 3)
        nonresident_open = opened_requests[-1]["params"]
        self.assertNotIn("roomCapability", nonresident_open)
        self.assertEqual(
            nonresident_open["sessionContext"],
            "bounded-room-recovery",
        )
        self.assertEqual(nonresident_open["sessionFile"], original_transcript)
        self.assertTrue(nonresident_compacted["memoryCheckpoint"]["stored"])

    def test_revoked_room_session_reopens_as_an_ordinary_agent_and_keeps_transcript(self) -> None:
        self.runtime.stop()
        state = {"revoked": False}
        manifest_id = "manifest:shared-session"
        manifest_hash = "a" * 64

        def context_provider(_session):
            if state["revoked"]:
                return {
                    "roomCapability": {
                        "manifestId": manifest_id,
                        "manifestHash": manifest_hash,
                        "capabilityEpoch": 3,
                        "status": "revoked",
                    },
                    "sessionContext": "settled-room-recovery",
                }
            return {
                "roomCapability": {
                    "manifestId": manifest_id,
                    "manifestHash": manifest_hash,
                    "capabilityEpoch": 2,
                    "promptCompileReceiptId": "prompt:shared-session",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:shared-session",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "rootId": "root:shared-session",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
                "roomRecoveryContext": "sealed-room-recovery",
            }

        ordinary_tools = [
            {
                "name": "workspace_read",
                "description": "Read one workspace file",
                "parameters": {"type": "object"},
            }
        ]
        self.runtime = PiRuntimeHostManager(
            config=self.runtime.config,
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: ordinary_tools,
        )
        session_id = str(self.first["id"])
        first_open = self.runtime.ensure(session_id)
        original_transcript = str(first_open["state"]["sessionFile"])
        state["revoked"] = True

        accepted = self.runtime.prompt(
            session_id,
            "Room 已收工，现在继续普通对话",
            client_message_id="client:ordinary-after-room",
        )
        self.assertTrue(accepted["accepted"])
        _wait_until(
            lambda: self.store.get(session_id)["status"] == "idle"
        )
        self.assertEqual(
            self.runtime.debug_context(
                session_id,
                str(accepted["turnId"]),
            ),
            {},
        )
        self.runtime.prompt(
            session_id,
            "继续第二轮普通对话",
            client_message_id="client:ordinary-second",
        )
        _wait_until(
            lambda: self.store.get(session_id)["status"] == "idle"
        )

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened = [
            request
            for request in requests
            if request["method"] == "session.open"
        ]
        self.assertEqual(len(opened), 2)
        self.assertEqual(
            sum(
                request["method"] == "session.close"
                for request in requests
            ),
            1,
        )
        ordinary_open = opened[-1]["params"]
        self.assertNotIn("roomCapability", ordinary_open)
        self.assertNotIn("roomContext", ordinary_open)
        self.assertEqual(
            ordinary_open["sessionContext"],
            "settled-room-recovery",
        )
        self.assertNotEqual(
            ordinary_open["systemPrompt"],
            "stable-room-prefix",
        )
        self.assertEqual(
            ordinary_open["toolManifest"],
            ordinary_tools,
        )
        self.assertEqual(
            ordinary_open["sessionFile"],
            original_transcript,
        )
        prompts = [
            request
            for request in requests
            if request["method"] == "session.prompt"
        ]
        self.assertEqual(len(prompts), 2)
        self.assertIn(
            "session.debug.context",
            [request["method"] for request in requests],
        )

    def test_ordinary_agent_session_reopens_in_room_mode_for_a_dispatch(self) -> None:
        self.runtime.stop()
        state = {"room": False}

        def context_provider(_session):
            if not state["room"]:
                return {}
            return {
                "roomCapability": {
                    "manifestId": "manifest:agent-to-room",
                    "manifestHash": "a" * 64,
                    "capabilityEpoch": 4,
                    "promptCompileReceiptId": "prompt:agent-to-room",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:agent-to-room",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "rootId": "root:agent-to-room",
                    "dispatchId": "dispatch:agent-to-room",
                    "generation": 0,
                    "contextEpoch": 1,
                    "contextEpochReason": "session_open",
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
                "roomRecoveryContext": "governed-room-task",
            }

        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: [],
        )
        session_id = str(self.first["id"])
        self.runtime.prompt(
            session_id,
            "先在 Agent 里讨论任务",
            client_message_id="client:agent-first",
        )
        _wait_until(
            lambda: self.store.get(session_id)["status"] == "idle"
        )
        transcript = str(
            self.store.runtime_binding(session_id)["transcriptRef"]
        )
        state["room"] = True

        receipt = self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:agent-to-room",
                "dispatchId": "dispatch:agent-to-room",
                "generation": 0,
                "capabilityEpoch": 4,
                "attempt": 0,
                "idempotencyKey": "agent-to-room:1",
            },
            message="现在由 Room 接管同一个 Session",
            lease_token="lease:agent-to-room",
        )

        self.assertEqual(receipt["status"], "accepted")
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened = [
            request
            for request in requests
            if request["method"] == "session.open"
        ]
        self.assertEqual(len(opened), 2)
        self.assertEqual(
            sum(
                request["method"] == "session.close"
                for request in requests
            ),
            1,
        )
        room_open = opened[-1]["params"]
        self.assertEqual(
            room_open["roomCapability"]["dispatchId"],
            "dispatch:agent-to-room",
        )
        self.assertEqual(
            room_open["systemPrompt"],
            "stable-room-prefix",
        )
        self.assertEqual(room_open["sessionFile"], transcript)
        self.assertTrue(
            any(
                request["method"] == "room.dispatch"
                for request in requests
            )
        )

    def test_one_session_moves_agent_room_agent_without_changing_transcript(self) -> None:
        self.runtime.stop()
        state = {"mode": "agent"}

        def context_provider(_session):
            if state["mode"] == "agent":
                return {}
            capability = {
                "manifestId": "manifest:agent-room-agent",
                "manifestHash": "a" * 64,
                "capabilityEpoch": 5,
                "rootId": "root:agent-room-agent",
                "dispatchId": "dispatch:agent-room-agent",
                "generation": 0,
                "contextEpoch": 1,
                "contextEpochReason": "session_open",
            }
            if state["mode"] == "revoked":
                return {
                    "roomCapability": {
                        **capability,
                        "capabilityEpoch": 6,
                        "status": "revoked",
                    }
                }
            return {
                "roomCapability": {
                    **capability,
                    "promptCompileReceiptId": "prompt:agent-room-agent",
                    "promptPlanHash": "b" * 64,
                    "compiledRuntimeProfileRef": {
                        "profileId": "profile:agent-room-agent",
                        "revision": "1",
                        "contentHash": "sha256:abcdef",
                    },
                    "runtimeBindingHash": "c" * 64,
                },
                "managedSystemPrompt": "stable-room-prefix",
                "sessionContext": "generic-agent-rag",
                "providerContext": "governed-room-task",
                "roomRecoveryContext": "governed-room-task",
            }

        ordinary_tools = [
            {
                "name": "workspace_read",
                "description": "Read one workspace file",
                "parameters": {"type": "object"},
            }
        ]
        self.runtime = PiRuntimeHostManager(
            config=replace(
                self.runtime.config,
                provider_environment={"TEST_ROOM_TYPES": "1"},
            ),
            sessions=self.store,
            events=self.events,
            session_context_provider=context_provider,
            tool_manifest_provider=lambda _session: ordinary_tools,
        )
        session_id = str(self.first["id"])

        self.runtime.prompt(
            session_id,
            "普通 Agent 第一轮",
            client_message_id="client:agent-before-room",
        )
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")
        transcript = str(
            self.store.runtime_binding(session_id)["transcriptRef"]
        )

        state["mode"] = "room"
        self.runtime.dispatch_room(
            {
                "targetSessionId": session_id,
                "rootId": "root:agent-room-agent",
                "dispatchId": "dispatch:agent-room-agent",
                "generation": 0,
                "capabilityEpoch": 5,
                "attempt": 0,
                "idempotencyKey": "agent-room-agent:room",
            },
            message="同一个 Session 进入 Room",
            lease_token="lease:agent-room-agent",
        )

        cancelled = self.runtime.cancel_room(
            cancel_id="cancel:agent-room-agent",
            session_id=session_id,
            root_id="root:agent-room-agent",
            dispatch_id="dispatch:agent-room-agent",
            generation=1,
            turn_id="room-turn-dispatch:agent-room-agent",
            capability_epoch=5,
        )
        self.assertEqual(cancelled["receiptKind"], "cancel_applied")
        self.assertEqual(cancelled["pendingTargets"], [])
        state["mode"] = "revoked"
        self.runtime.prompt(
            session_id,
            "Room 已收工，继续普通 Agent",
            client_message_id="client:agent-after-room",
        )
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opens = [
            request["params"]
            for request in requests
            if request["method"] == "session.open"
        ]
        self.assertEqual(len(opens), 3)
        self.assertEqual(
            [params.get("sessionFile", transcript) for params in opens],
            [transcript, transcript, transcript],
        )
        self.assertNotIn("roomCapability", opens[0])
        self.assertEqual(
            opens[1]["roomCapability"]["dispatchId"],
            "dispatch:agent-room-agent",
        )
        self.assertEqual(opens[1]["systemPrompt"], "stable-room-prefix")
        self.assertNotIn("roomCapability", opens[2])
        self.assertNotEqual(opens[2]["systemPrompt"], "stable-room-prefix")
        self.assertEqual(opens[2]["toolManifest"], ordinary_tools)
        methods = [request["method"] for request in requests]
        self.assertLess(
            methods.index("room.cancel"),
            max(
                index
                for index, method in enumerate(methods)
                if method == "session.open"
            ),
        )
        self.assertEqual(
            sum(
                request["method"] == "session.close"
                for request in requests
            ),
            2,
        )

    def test_coding_tool_projection_keeps_useful_request_and_bounded_output(self) -> None:
        result = public_code_tool_activity(
            "grep",
            {
                "path": "/Users/private/project/rag_ime",
                "pattern": "rime_lexicon_review",
                "glob": "*.py",
                "limit": 100,
                "context": 2,
            },
            {
                "content": [{
                    "type": "text",
                    "text": (
                        "/Users/private/project/rag_ime/agent_tools.py:41:"
                        " def rime_lexicon_review(): pass\n"
                        "OPENAI_API_KEY=sk-never-render-this"
                    ),
                }],
            },
        )

        self.assertEqual(result["path"], "…/project/rag_ime")
        self.assertEqual(result["pattern"], "rime_lexicon_review")
        self.assertEqual(result["glob"], "*.py")
        self.assertEqual(result["limit"], 100)
        self.assertEqual(result["context"], 2)
        self.assertIn("~/project/rag_ime/agent_tools.py:41", result["outputPreview"])
        self.assertIn("OPENAI_API_KEY=[REDACTED_SECRET]", result["outputPreview"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("/Users/private", serialized)
        self.assertNotIn("sk-never-render-this", serialized)

    def test_coding_tool_aliases_collapse_to_one_public_contract(self) -> None:
        self.assertEqual(canonical_code_tool_name("workspace_read"), "read")
        self.assertEqual(canonical_code_tool_name("read_file"), "read")
        self.assertEqual(canonical_code_tool_name("workspace_edit"), "edit")
        self.assertEqual(canonical_code_tool_name("apply_patch"), "edit")
        self.assertEqual(canonical_code_tool_name("workspace_write"), "write")
        self.assertEqual(canonical_code_tool_name("write_file"), "write")
        self.assertEqual(canonical_code_tool_name("workspace_shell"), "bash")
        self.assertEqual(canonical_code_tool_name("workspace_job"), "bash")

    def test_public_mutation_arguments_keep_target_but_drop_the_second_body_carrier(self) -> None:
        write = public_code_tool_arguments(
            "write_file",
            {
                "path": "src/generated.py",
                "content": "private source body",
                "mode": "overwrite",
            },
        )
        edit = public_code_tool_arguments(
            "workspace_edit",
            {
                "path": "src/main.py",
                "oldText": "private old body",
                "newText": "private new body",
                "edits": [{"new_text": "nested private body"}],
            },
        )

        self.assertEqual(write, {"path": "src/generated.py", "mode": "overwrite"})
        self.assertEqual(edit, {"path": "src/main.py"})
        serialized = json.dumps({"write": write, "edit": edit})
        self.assertNotIn("private", serialized)

    def test_canonical_workspace_tools_keep_meaningful_bounded_details(self) -> None:
        lsp = public_code_tool_activity(
            "workspace_lsp",
            {
                "operation": "diagnostics",
                "root": "/Users/private/project",
                "path": "src/main.py",
                "server": "pyright",
                "line": 12,
                "column": 4,
            },
            {"content": [{"type": "text", "text": "2 diagnostics"}]},
        )
        job = public_code_tool_activity(
            "workspace_job",
            {
                "operation": "logs",
                "jobId": "bg_123",
                "cwd": "/Volumes/private/project",
                "command": "python -m unittest",
                "cursor": 64,
                "limitBytes": 4096,
            },
            {"content": [{"type": "text", "text": "tests complete"}]},
        )
        write = public_code_tool_activity(
            "workspace_write",
            {
                "operation": "apply",
                "path": "src/new_file.py",
                "content": "first\nsecond\n",
            },
        )
        command = public_code_tool_activity(
            "workspace_shell",
            {"command": "python3 -m unittest", "cwd": "/Users/private/project"},
            {
                "details": {
                    "approval": {
                        "receipt": {
                            "stdout": "test_one ... ok",
                            "stderr": "warning: bounded",
                            "output": "test_one ... ok\nwarning: bounded",
                            "exitCode": 0,
                        },
                    },
                },
                "content": [{
                    "type": "text",
                    "text": "test_one ... ok\n[stderr]\nwarning: bounded\n[exit code: 0]",
                }],
            },
        )

        self.assertEqual(
            {
                key: lsp[key]
                for key in ("path", "root", "operation", "server", "line", "column")
            },
            {
                "path": "src/main.py",
                "root": "…/project",
                "operation": "diagnostics",
                "server": "pyright",
                "line": 12,
                "column": 4,
            },
        )
        self.assertEqual(lsp["outputPreview"], "2 diagnostics")
        self.assertEqual(job["jobId"], "bg_123")
        self.assertEqual(job["cwd"], "…/project")
        self.assertEqual(job["cursor"], 64)
        self.assertEqual(job["limitBytes"], 4096)
        self.assertEqual(job["outputPreview"], "tests complete")
        self.assertEqual(write["summary"], "new_file.py +2")
        self.assertNotIn("content", write)
        self.assertEqual(command["stdoutPreview"], "test_one ... ok")
        self.assertEqual(command["stderrPreview"], "warning: bounded")
        self.assertEqual(command["exitCode"], 0)

    def test_edit_projection_keeps_safe_diff_and_per_file_counts(self) -> None:
        result = public_code_tool_activity(
            "edit",
            {"path": "/Users/private/project/src/main.py"},
            {
                "details": {
                    "diff": (
                        "--- a/src/main.py\n"
                        "+++ b/src/main.py\n"
                        "@@ -1,2 +1,3 @@\n"
                        "-print('old')\n"
                        "+print('new')\n"
                        "+print('ready')\n"
                    ),
                    "path": "/Users/private/project/src/main.py",
                }
            },
        )

        self.assertEqual(result["summary"], "main.py +2 -1")
        self.assertEqual(result["additions"], 2)
        self.assertEqual(result["deletions"], 1)
        self.assertEqual(
            result["changedFiles"],
            [{
                "path": "…/project/src/main.py",
                "fileName": "main.py",
                "additions": 2,
                "deletions": 1,
            }],
        )
        self.assertIn("+print('ready')", result["outputPreview"])
        self.assertNotIn("/Users/private", json.dumps(result, ensure_ascii=False))

    def test_coding_tool_projection_unwraps_managed_evidence_receipts(self) -> None:
        evidence_summary = (
            "wisdom-weasel-rag-ime/rag_ime/agent_tools.py:41: "
            "def rime_lexicon_review(): pass"
        )
        result = public_code_tool_activity(
            "grep",
            {},
            {
                "content": [{
                    "type": "text",
                    "text": json.dumps(
                        {
                            "evidenceHandle": "internal-handle-must-not-render",
                            "evidenceRequest": {
                                "path": "/Volumes/private/project/rag_ime",
                                "pattern": "rime_lexicon_review",
                                "limit": 100,
                                "context": 2,
                            },
                            "evidenceSummary": evidence_summary,
                            "evidenceBytes": len(evidence_summary.encode("utf-8")) + 500,
                            "evidenceSha256": "a" * 64,
                        },
                        ensure_ascii=False,
                    ),
                }],
            },
        )

        self.assertEqual(result["path"], "…/project/rag_ime")
        self.assertEqual(result["pattern"], "rime_lexicon_review")
        self.assertEqual(result["limit"], 100)
        self.assertEqual(result["context"], 2)
        self.assertEqual(result["outputPreview"], evidence_summary)
        self.assertTrue(result["outputTruncated"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("evidenceHandle", serialized)
        self.assertNotIn("internal-handle", serialized)
        self.assertNotIn("evidenceSha256", serialized)

    def test_coding_tool_projection_removes_plain_internal_evidence_prefix(self) -> None:
        result = public_code_tool_activity(
            "grep",
            {"path": "scripts", "pattern": "missing_symbol"},
            {
                "content": [{
                    "type": "text",
                    "text": (
                        "[evidence ref: execution:invoke:private-handle] "
                        "在 417 个文件中找到 0 条匹配"
                    ),
                }],
            },
        )

        self.assertEqual(result["outputPreview"], "在 417 个文件中找到 0 条匹配")
        self.assertNotIn("evidence ref", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("private-handle", json.dumps(result, ensure_ascii=False))

    def test_structured_workspace_read_and_search_keep_renderable_results(self) -> None:
        read = public_code_tool_activity(
            "workspace_read",
            {"path": "src/runtime.py"},
            {
                "summary": "已读取 runtime.py 第 12-13 行",
                "relativePath": "src/runtime.py",
                "content": "def start():\n    return True\n",
                "startLine": 12,
                "endLine": 13,
                "truncated": False,
            },
        )
        search = public_code_tool_activity(
            "workspace_search",
            {"query": "start", "path": "src"},
            {
                "summary": "在 8 个文件中找到 2 条匹配",
                "matches": [
                    {
                        "relativePath": "src/runtime.py",
                        "lineNumber": 12,
                        "preview": "def start():",
                    },
                    {
                        "relativePath": "tests/test_runtime.py",
                        "lineNumber": 7,
                        "preview": "def test_start():",
                    },
                ],
                "filesScanned": 8,
                "truncated": False,
            },
        )

        self.assertEqual(read["outputPreview"], "def start():\n    return True")
        self.assertEqual(read["startLine"], 12)
        self.assertEqual(read["endLine"], 13)
        self.assertEqual(read["lineCount"], 2)
        self.assertIn("src/runtime.py:12:def start():", search["outputPreview"])
        self.assertIn("tests/test_runtime.py:7:def test_start():", search["outputPreview"])
        self.assertEqual(search["matchCount"], 2)
        self.assertEqual(search["filesScanned"], 8)

    def test_coding_tool_projection_redacts_commands_and_never_previews_secret_files(self) -> None:
        command = public_code_tool_activity(
            "bash",
            {
                "command": (
                    "TOKEN=plain-secret OPENAI_API_KEY=api-secret "
                    "python scripts/probe.py --token cli-secret "
                    "'https://example.test/run?token=url-secret&mode=1' "
                    "-H 'Authorization: Bearer header-secret' echo token 用量"
                ),
                "timeout": 30,
            },
            {"content": [{"type": "text", "text": "probe complete"}]},
        )
        secret_file = public_code_tool_activity(
            "read",
            {"path": "/Users/private/project/.env", "limit": 100},
            {"content": [{"type": "text", "text": "DATABASE_PASSWORD=do-not-show"}]},
        )

        self.assertEqual(command["timeout"], 30)
        serialized_command = str(command["command"])
        for secret in (
            "plain-secret", "api-secret", "cli-secret", "url-secret",
            "header-secret",
        ):
            self.assertNotIn(secret, serialized_command)
        self.assertIn("TOKEN=[REDACTED_SECRET]", serialized_command)
        self.assertIn("token 用量", serialized_command)
        self.assertIn("mode=1", serialized_command)
        self.assertEqual(command["outputPreview"], "probe complete")
        self.assertNotIn("outputPreview", secret_file)
        self.assertNotIn("do-not-show", json.dumps(secret_file))

        for sensitive_name in (".env.staging", "secrets.yaml", "tokens.json"):
            sensitive_edit = public_code_tool_activity(
                "edit",
                {"path": f"/Users/private/project/{sensitive_name}"},
                {
                    "details": {
                        "path": f"/Users/private/project/{sensitive_name}",
                        "diff": (
                            f"--- a/{sensitive_name}\n+++ b/{sensitive_name}\n"
                            "@@ -1 +1 @@\n-token=old-secret\n+token=new-secret\n"
                        ),
                    }
                },
            )
            sensitive_serialized = json.dumps(sensitive_edit, ensure_ascii=False)
            self.assertNotIn("outputPreview", sensitive_edit)
            self.assertNotIn("changedFiles", sensitive_edit)
            self.assertNotIn("old-secret", sensitive_serialized)
            self.assertNotIn("new-secret", sensitive_serialized)

            shell_commands = (
                f"cat ./config/{sensitive_name}",
                f"source ./config/{sensitive_name}",
                f"grep DATABASE ./config/{sensitive_name}",
                f"sed -n 1p ./config/{sensitive_name}",
            )
            for shell_tool in ("bash", "workspace_shell"):
                for shell_command in shell_commands:
                    protected_shell = public_code_tool_activity(
                        shell_tool,
                        {"command": shell_command},
                        {
                            "content": [{
                                "type": "text",
                                "text": "DATABASE_URL=postgres://private-password-value",
                            }],
                        },
                    )
                    self.assertEqual(
                        protected_shell.get("command"),
                        "已运行受保护命令",
                    )
                    self.assertNotIn("outputPreview", protected_shell)
                    protected_serialized = json.dumps(
                        protected_shell,
                        ensure_ascii=False,
                    )
                    self.assertNotIn(sensitive_name, protected_serialized)
                    self.assertNotIn(
                        "private-password-value",
                        protected_serialized,
                    )

    def test_runtime_secret_redaction_covers_headers_json_and_url_queries(self) -> None:
        redacted = redact_runtime_text(
            "TOKEN=plain-secret "
            '"token": "json-secret" '
            "cookie: session-secret "
            "Authorization: Bearer header-secret "
            "https://example.test/run?token=url-secret&mode=1 token 用量"
        )

        for secret in (
            "plain-secret", "json-secret", "session-secret", "header-secret",
            "url-secret",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("mode=1", redacted)
        self.assertIn("token 用量", redacted)

    def test_host_coding_tool_event_sends_one_bounded_result_projection(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-grep-projection"
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "tool_execution_end",
                    "toolCallId": "call-grep-projection",
                    "toolName": "grep",
                    "args": {
                        "path": "/Users/private/project/rag_ime",
                        "pattern": "provider_payload",
                        "limit": 100,
                    },
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": "rag_ime/pi_runtime.py:100:def provider_payload():",
                        }],
                    },
                    "isError": False,
                },
            }
        )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        event = next(
            item
            for item in events
            if item.event_type == "tool_finished"
            and item.payload.get("toolCallId") == "call-grep-projection"
        )
        self.assertEqual(
            event.payload["publicResult"]["outputPreview"],
            "rag_ime/pi_runtime.py:100:def provider_payload():",
        )
        self.assertNotIn("result", event.payload)

    def test_host_bash_progress_stream_uses_the_canonical_name_and_partial_output(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-bash-progress"
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "tool_execution_update",
                    "toolCallId": "call-bash-progress",
                    "toolName": "workspace_shell",
                    "args": {
                        "command": "python3 -m unittest tests.test_runtime",
                        "cwd": "/Users/private/project",
                    },
                    "partialResult": {
                        "content": [{
                            "type": "text",
                            "text": "test_one ... ok\ntest_two ...",
                        }],
                        "details": {
                            "summary": "运行命令仍在执行，已持续 2 秒",
                        },
                    },
                    "isError": False,
                },
            }
        )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        event = next(
            item
            for item in events
            if item.event_type == "tool_progress"
            and item.payload.get("toolCallId") == "call-bash-progress"
        )
        self.assertEqual(event.payload["toolName"], "bash")
        self.assertEqual(
            event.payload["publicResult"]["command"],
            "python3 -m unittest tests.test_runtime",
        )
        self.assertEqual(
            event.payload["publicResult"]["outputPreview"],
            "test_one ... ok\ntest_two ...",
        )
        self.assertEqual(
            event.payload["publicResult"]["summary"],
            "运行命令仍在执行，已持续 2 秒",
        )
        self.assertNotIn("partialResult", event.payload)

    def test_host_background_job_uses_bash_projection_without_losing_stream_or_exit_code(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-background-job-progress"
        for event_type, result_key, raw_result in (
            (
                "tool_execution_update",
                "partialResult",
                {
                    "stdout": "collected 12 items\n...",
                    "stderr": "warning: cache miss",
                },
            ),
            (
                "tool_execution_end",
                "result",
                {
                    "stdout": "collected 12 items\n12 passed",
                    "stderr": "warning: cache miss",
                    "exitCode": 0,
                },
            ),
        ):
            self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
                {
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": {
                        "type": event_type,
                        "toolCallId": "call-background-job",
                        "toolName": "workspace_job",
                        "args": {
                            "operation": "logs",
                            "jobId": "bg_123",
                            "command": "python3 -m pytest",
                        },
                        result_key: raw_result,
                        "isError": False,
                    },
                }
            )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        lifecycle = {
            item.event_type: item
            for item in events
            if item.payload.get("toolCallId") == "call-background-job"
        }
        progress = lifecycle["tool_progress"]
        completed = lifecycle["tool_finished"]
        self.assertEqual(progress.payload["toolName"], "bash")
        self.assertEqual(progress.payload["publicResult"]["stdoutPreview"], "collected 12 items\n...")
        self.assertEqual(progress.payload["publicResult"]["stderrPreview"], "warning: cache miss")
        self.assertEqual(completed.payload["toolName"], "bash")
        self.assertEqual(completed.payload["publicResult"]["stdoutPreview"], "collected 12 items\n12 passed")
        self.assertEqual(completed.payload["publicResult"]["exitCode"], 0)

    def test_host_failed_room_tool_preserves_a_bounded_public_reason(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-room-tool-error"
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "tool_execution_end",
                    "toolCallId": "call-room-commit-error",
                    "toolName": "room_commit",
                    "args": {"decision": "wait"},
                    "result": (
                        "questionOptions[0].value is required; "
                        "API_KEY=must-not-leak"
                    ),
                    "isError": True,
                },
            }
        )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        event = next(
            item
            for item in events
            if item.event_type == "tool_finished"
            and item.payload.get("toolCallId") == "call-room-commit-error"
        )
        self.assertEqual(
            event.payload["error"],
            "这个问题的选项没有准备完整，伙伴会修正后重新发送。",
        )
        self.assertNotIn("must-not-leak", json.dumps(event.payload))

    def test_host_marks_only_the_direct_failed_tool_recovery_as_one_lineage(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-tool-recovery-lineage"

        def emit(payload: dict[str, object]) -> None:
            self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
                {
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": payload,
                }
            )

        emit({
            "type": "tool_execution_start",
            "toolCallId": "commit-1",
            "toolName": "room_commit",
            "args": {"decision": "wait"},
        })
        emit({
            "type": "tool_execution_end",
            "toolCallId": "commit-1",
            "toolName": "room_commit",
            "result": {"error": "missing question options"},
            "isError": True,
        })
        emit({
            "type": "tool_execution_start",
            "toolCallId": "commit-2",
            "toolName": "room_commit",
            "args": {"decision": "ask", "question": "请选择目标范围"},
        })
        emit({
            "type": "tool_execution_end",
            "toolCallId": "commit-2",
            "toolName": "room_commit",
            "result": {"status": "waiting"},
            "isError": False,
        })
        # A later successful call with no pending failure is an independent
        # action even when the Tool name is identical.
        emit({
            "type": "tool_execution_start",
            "toolCallId": "commit-3",
            "toolName": "room_commit",
            "args": {"decision": "continue"},
        })
        # A failed edit followed by a different file is also independent.
        emit({
            "type": "tool_execution_start",
            "toolCallId": "edit-a",
            "toolName": "edit",
            "args": {"path": "src/a.ts"},
        })
        emit({
            "type": "tool_execution_end",
            "toolCallId": "edit-a",
            "toolName": "edit",
            "result": {"error": "old text not found"},
            "isError": True,
        })
        emit({
            "type": "tool_execution_start",
            "toolCallId": "edit-b",
            "toolName": "edit",
            "args": {"path": "src/b.ts"},
        })
        # Upstream lineage is advisory: it cannot turn a successful unrelated
        # operation into a retry merely by naming it as a parent.
        emit({
            "type": "tool_execution_start",
            "toolCallId": "read-a",
            "toolName": "read",
            "args": {"path": "src/a.ts"},
        })
        emit({
            "type": "tool_execution_end",
            "toolCallId": "read-a",
            "toolName": "read",
            "result": {"content": "a"},
            "isError": False,
        })
        emit({
            "type": "tool_execution_start",
            "toolCallId": "edit-explicit-unrelated",
            "toolName": "edit",
            "retryOfToolCallId": "read-a",
            "args": {"path": "src/b.ts"},
        })
        # Commands share an executable but not necessarily a target. Different
        # command text must remain two rows even when calls are adjacent.
        emit({
            "type": "tool_execution_start",
            "toolCallId": "command-a",
            "toolName": "bash",
            "args": {"cwd": "/workspace", "command": "python tests/a.py"},
        })
        emit({
            "type": "tool_execution_end",
            "toolCallId": "command-a",
            "toolName": "bash",
            "result": {"error": "failed"},
            "isError": True,
        })
        emit({
            "type": "tool_execution_start",
            "toolCallId": "command-b",
            "toolName": "bash",
            "args": {"cwd": "/workspace", "command": "python tests/b.py"},
        })

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        lifecycle = {
            (str(event.payload.get("toolCallId")), event.event_type): event.payload
            for event in events
            if event.event_type in {"tool_started", "tool_finished"}
        }
        self.assertEqual(
            lifecycle[("commit-2", "tool_started")]["retryOfToolCallId"],
            "commit-1",
        )
        self.assertEqual(
            lifecycle[("commit-2", "tool_finished")]["retryOfToolCallId"],
            "commit-1",
        )
        self.assertNotIn("retryOfToolCallId", lifecycle[("commit-3", "tool_started")])
        self.assertNotIn("retryOfToolCallId", lifecycle[("edit-b", "tool_started")])
        self.assertNotIn(
            "retryOfToolCallId",
            lifecycle[("edit-explicit-unrelated", "tool_started")],
        )
        self.assertNotIn("retryOfToolCallId", lifecycle[("command-b", "tool_started")])

    def test_host_projects_codex_thinking_end_as_public_work_summary(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-codex-reasoning"
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "thinking_end",
                        "contentIndex": 0,
                    },
                    "message": {
                        "id": "assistant-codex-reasoning",
                        "role": "assistant",
                        "api": "openai-codex-responses",
                        "content": [{
                            "type": "thinking",
                            "thinking": (
                                "**Inspecting /Users/private/project/runtime.py**\n\n"
                                "**Planning the visible fix**"
                            ),
                            "thinkingSignature": "private-provider-signature",
                        }],
                    },
                },
            }
        )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        reasoning = [
            event for event in events
            if event.event_type == "reasoning_summary"
            and event.turn_id == turn_id
        ]
        self.assertEqual(len(reasoning), 1)
        self.assertEqual(reasoning[0].payload["summary"], "Planning the visible fix")
        self.assertEqual(
            reasoning[0].payload["items"],
            ["Inspecting [REDACTED_PATH]", "Planning the visible fix"],
        )
        self.assertEqual(
            reasoning[0].payload["source"],
            "provider_reasoning_summary",
        )
        self.assertNotIn(
            "private-provider-signature",
            json.dumps(reasoning[0].payload, ensure_ascii=False),
        )

    def test_cold_history_reads_managed_jsonl_without_opening_provider_context(self) -> None:
        session_id = str(self.first["id"])
        transcript = self.root / "sessions" / "cold-history.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {"type": "session", "id": "pi-cold-history"},
            {
                "type": "message",
                "id": "cold-user",
                "parentId": "",
                "timestamp": "1970-01-01T00:00:00.100Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "冷启动历史问题"}],
                },
            },
            {
                "type": "message",
                "id": "cold-assistant",
                "parentId": "cold-user",
                "timestamp": "1970-01-01T00:00:00.200Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "冷启动历史回答"}],
                },
            },
        ]
        transcript.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )
        self.store.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id="pi-cold-history",
            transcript_ref=transcript.as_posix(),
            branch_anchor="cold-assistant",
            binding_state="active",
            metadata={"protocolVersion": "2"},
            message_count=2,
        )
        context_calls: list[str] = []
        self.runtime._session_context_provider = (  # noqa: SLF001 - latency contract
            lambda session: context_calls.append(str(session["id"])) or {}
        )

        with patch.object(
            self.runtime,
            "_host",
            side_effect=AssertionError("history must not start the Runtime Host"),
        ):
            snapshot = self.runtime.session_snapshot(session_id)

        self.assertEqual(
            [
                block["data"]["text"]
                for message in snapshot["messages"]
                for block in message["blocks"]
                if block["type"] == "text"
            ],
            ["冷启动历史问题", "冷启动历史回答"],
        )
        self.assertEqual(context_calls, [])
        self.assertFalse((self.root / "agent" / "host-requests.jsonl").exists())

    def test_resident_history_and_command_reads_skip_context_reassembly(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        context_calls: list[str] = []
        self.runtime._session_context_provider = (  # noqa: SLF001 - latency contract
            lambda session: context_calls.append(str(session["id"])) or {}
        )

        with patch.object(
            self.store,
            "set_status",
            wraps=self.store.set_status,
        ) as set_status:
            snapshot = self.runtime.session_snapshot(session_id)
            commands = self.runtime.command_catalog(session_id)

        self.assertTrue(snapshot["messages"] == [])
        self.assertTrue(commands)
        self.assertEqual(context_calls, [])
        set_status.assert_not_called()

    def test_resident_idle_history_prefers_populated_durable_branch_without_live_snapshot(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        binding = self.store.runtime_binding(session_id)
        transcript = Path(binding["transcriptRef"])
        root_id = str(binding["externalSessionId"])
        time.sleep(0.01)
        entries = [
            {"type": "session", "id": root_id},
            {
                "type": "message",
                "id": "resident-user",
                "parentId": root_id,
                "timestamp": "1970-01-01T00:00:00.100Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "常驻历史问题"}],
                },
            },
            {
                "type": "message",
                "id": "resident-answer",
                "parentId": "resident-user",
                "timestamp": "1970-01-01T00:00:00.200Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "常驻历史回答"}],
                },
            },
        ]
        transcript.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )
        request_log = self.root / "agent" / "host-requests.jsonl"
        before = [
            json.loads(line)
            for line in request_log.read_text(encoding="utf-8").splitlines()
        ]

        snapshot = self.runtime.session_snapshot(session_id)

        self.assertEqual(
            [
                block["data"]["text"]
                for message in snapshot["messages"]
                for block in message["blocks"]
                if block["type"] == "text"
            ],
            ["常驻历史问题", "常驻历史回答"],
        )
        after = [
            json.loads(line)
            for line in request_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [item["method"] for item in after].count("session.snapshot"),
            [item["method"] for item in before].count("session.snapshot"),
        )

    def test_resident_idle_history_keeps_body_across_repeated_reads(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(session_id, "resident history")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        transcript = Path(
            self.store.runtime_binding(session_id)["transcriptRef"]
        )
        self.assertEqual(
            [json.loads(line)["type"] for line in transcript.read_text().splitlines()],
            ["session"],
        )

        for _ in range(2):
            snapshot = self.runtime.session_snapshot(session_id)
            self.assertEqual(
                [
                    block["data"]["text"]
                    for message in snapshot["messages"]
                    for block in message["blocks"]
                    if block["type"] == "text"
                ],
                ["resident history", f"host reply for {session_id}"],
            )

        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [item["method"] for item in requests].count("session.open"),
            1,
        )
        self.assertEqual(
            [item["method"] for item in requests].count("session.snapshot"),
            2,
        )

    def test_snapshot_history_uses_only_the_selected_durable_branch(self) -> None:
        entries = [
            {"type": "session", "id": "root"},
            {
                "type": "message",
                "id": "entry-user",
                "parentId": "root",
                "timestamp": "1970-01-01T00:00:00.100Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "保留的提问"}],
                },
            },
            {
                "type": "message",
                "id": "entry-answer",
                "parentId": "entry-user",
                "timestamp": "1970-01-01T00:00:00.200Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "保留的回答"}],
                },
            },
            {
                "type": "message",
                "id": "entry-other-branch",
                "parentId": "entry-user",
                "timestamp": "1970-01-01T00:00:00.300Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "另一分支"}],
                },
            },
        ]

        messages, selected_entries = _pi_durable_branch_messages(
            entries,
            leaf_id="entry-answer",
        )

        self.assertEqual(
            [message["content"][0]["text"] for message in messages],
            ["保留的提问", "保留的回答"],
        )
        self.assertEqual([entry["id"] for entry in selected_entries], ["entry-user", "entry-answer"])
        self.assertEqual(messages[0]["id"], "entry-user")
        self.assertEqual(messages[0]["timestamp"], 100)

    def test_mixed_text_and_tool_message_keeps_text_but_not_tool_protocol(self) -> None:
        mixed = {
            "role": "assistant",
            "timestamp": 101,
            "content": [
                {"type": "text", "text": "我先检查项目入口。"},
                {
                    "type": "toolCall",
                    "id": "call-read",
                    "name": "workspace_read",
                    "arguments": {
                        "path": "/Users/private/project/README.md",
                        "apiKey": "top-secret",
                    },
                },
            ],
        }
        tool_only = {
            **mixed,
            "content": [mixed["content"][1]],
        }

        self.assertTrue(pi_message_is_public(mixed))
        self.assertFalse(pi_message_completes_public_turn(mixed))
        self.assertFalse(pi_message_is_public(tool_only))
        payload = pi_message_payload(
            mixed,
            session_id="session-1",
            turn_id="turn-1",
        ).to_payload()
        self.assertEqual(
            [block["type"] for block in payload["blocks"]],
            ["text"],
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertIn("我先检查项目入口", serialized)
        self.assertNotIn("workspace_read", serialized)
        self.assertNotIn("top-secret", serialized)
        self.assertNotIn("/Users/private", serialized)

    def test_only_openai_response_family_summaries_are_public(self) -> None:
        openai = {
            "api": "openai-responses",
            "content": [{
                "type": "thinking",
                "thinking": (
                    "**Analyzing session history**\n\n"
                    "**Inspecting /Users/private/project/runtime.py**"
                ),
                "thinkingSignature": "opaque-provider-signature",
            }],
        }
        codex = {**openai, "api": "openai-codex-responses"}
        anthropic = {**openai, "api": "anthropic-messages"}

        expected = ["Analyzing session history", "Inspecting [REDACTED_PATH]"]
        self.assertEqual(public_reasoning_summaries(openai), expected)
        self.assertEqual(public_reasoning_summaries(codex), expected)
        self.assertEqual(public_reasoning_summaries(anthropic), [])

    def test_transcript_tool_messages_rebuild_a_redacted_durable_timeline(self) -> None:
        raw_messages = [
            {
                "id": "user-1",
                "role": "user",
                "timestamp": 100,
                "content": [{"type": "text", "text": "检查项目"}],
            },
            {
                "id": "assistant-tool-1",
                "role": "assistant",
                "api": "openai-codex-responses",
                "timestamp": 101,
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "**Planning project inspection**",
                    },
                    {
                        "type": "toolCall",
                        "id": "tool-1",
                        "name": "workspace_read",
                        "arguments": {
                            "path": "/Users/private/project/README.md",
                            "apiKey": "top-secret",
                        },
                    },
                ],
            },
            {
                "role": "toolResult",
                "timestamp": 102,
                "toolCallId": "tool-1",
                "toolName": "workspace_read",
                "isError": False,
                "details": {"summary": "读取 /Users/private/project/README.md", "token": "secret"},
            },
        ]
        events = _pi_tool_history_events(
            raw_messages,
            session_id="session-1",
            raw_entries=[
                {
                    "type": "message",
                    "timestamp": "1970-01-01T00:00:00.100Z",
                    "message": raw_messages[0],
                },
                {
                    "type": "message",
                    "timestamp": "1970-01-01T00:00:00.501Z",
                    "message": raw_messages[1],
                },
                {
                    "type": "message",
                    "timestamp": "1970-01-01T00:00:00.902Z",
                    "message": raw_messages[2],
                },
            ],
        )

        self.assertEqual(
            [event["eventType"] for event in events],
            ["reasoning_summary", "tool_started", "tool_finished"],
        )
        self.assertEqual(
            [event["turnId"] for event in events],
            ["history:user-1", "history:user-1", "history:user-1"],
        )
        self.assertEqual([event["createdAtMs"] for event in events], [501, 502, 902])
        self.assertEqual(events[0]["payload"]["items"], ["Planning project inspection"])
        self.assertEqual(events[1]["payload"]["publicResult"]["fileName"], "README.md")
        self.assertEqual(events[1]["payload"]["toolName"], "read")
        self.assertEqual(events[2]["payload"]["toolName"], "read")
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("top-secret", serialized)
        self.assertNotIn("/Users/private", serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)

    def test_transcript_rebuild_keeps_direct_failed_tool_recovery_lineage(self) -> None:
        raw_messages = [
            {
                "id": "user-recovery",
                "role": "user",
                "timestamp": 100,
                "content": [{"type": "text", "text": "完成任务"}],
            },
            {
                "id": "assistant-recovery-1",
                "role": "assistant",
                "timestamp": 101,
                "content": [{
                    "type": "toolCall",
                    "id": "commit-history-1",
                    "name": "room_commit",
                    "arguments": {"decision": "wait"},
                }],
            },
            {
                "role": "toolResult",
                "timestamp": 102,
                "toolCallId": "commit-history-1",
                "toolName": "room_commit",
                "isError": True,
                "content": [{"type": "text", "text": "missing question options"}],
            },
            {
                "id": "assistant-recovery-2",
                "role": "assistant",
                "timestamp": 103,
                "content": [{
                    "type": "toolCall",
                    "id": "commit-history-2",
                    "name": "room_commit",
                    "arguments": {"decision": "ask", "question": "请选择目标范围"},
                }],
            },
            {
                "role": "toolResult",
                "timestamp": 104,
                "toolCallId": "commit-history-2",
                "toolName": "room_commit",
                "isError": False,
                "content": [{"type": "text", "text": "ok"}],
            },
            {
                "id": "assistant-independent",
                "role": "assistant",
                "timestamp": 105,
                "content": [{
                    "type": "toolCall",
                    "id": "commit-history-3",
                    "name": "room_commit",
                    "arguments": {"decision": "continue"},
                }],
            },
        ]

        events = _pi_tool_history_events(raw_messages, session_id="session-recovery")
        lifecycle = {
            (str(event["payload"].get("toolCallId")), str(event["eventType"])):
                event["payload"]
            for event in events
            if event["eventType"] in {"tool_started", "tool_finished"}
        }
        self.assertEqual(
            lifecycle[("commit-history-2", "tool_started")]["retryOfToolCallId"],
            "commit-history-1",
        )
        self.assertEqual(
            lifecycle[("commit-history-2", "tool_finished")]["retryOfToolCallId"],
            "commit-history-1",
        )
        self.assertNotIn(
            "retryOfToolCallId",
            lifecycle[("commit-history-3", "tool_started")],
        )

    def test_host_tool_artifact_is_carried_to_the_final_assistant_message(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-host-file-artifact"
        file_block = {
            "id": "tool-artifact:file:0123456789abcdef",
            "type": "file",
            "data": {
                "mediaId": "media_abcdefghijklmnop",
                "sessionId": session_id,
                "fileName": "result.diff",
                "mimeType": "text/x-diff",
                "byteSize": 80,
                "sha256": "b" * 64,
                "receiptUrl": (
                    "/api/agent/media/media_abcdefghijklmnop/content"
                    f"?sessionId={session_id}"
                ),
            },
        }

        def send(payload: dict[str, object]) -> None:
            self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
                {
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": payload,
                }
            )

        send({
            "type": "tool_execution_end",
            "toolCallId": "call-patch",
            "toolName": "workspace_patch",
            "result": {"details": {"agentBlocks": [file_block]}},
            "isError": False,
        })
        send({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "timestamp": 101,
                "content": [
                    {"type": "text", "text": "我已经找到主要结构，继续核对最后一项。"},
                    {"type": "toolCall", "id": "call-next", "name": "todo"},
                ],
            },
        })
        send({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "timestamp": 102,
                "content": [{"type": "text", "text": "变更已经交付。"}],
                "usage": {"input": 100, "output": 20, "totalTokens": 120},
            },
        })

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        completed = [event.payload["message"] for event in events if event.event_type == "message_completed"]
        progress = [event.payload for event in events if event.event_type == "text_delta"]
        self.assertEqual(
            [(item["delta"], item.get("replaceContent")) for item in progress],
            [("我已经找到主要结构，继续核对最后一项。", True)],
        )
        self.assertEqual(len(completed), 1)
        completed_event = next(
            event
            for event in events
            if event.event_type == "message_completed"
        )
        self.assertIs(completed_event.payload["usageReported"], True)
        self.assertIs(completed_event.payload["cacheUsageReported"], False)
        self.assertEqual([block["type"] for block in completed[-1]["blocks"]], ["file", "text"])
        self.assertEqual(completed[-1]["blocks"][0]["data"]["mimeType"], "text/x-diff")

    def test_tool_only_host_turn_reports_response_evidence_after_settlement(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-host-tool-only-evidence"
        assistant = {
            "role": "assistant",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "usage": {
                "input": 2873,
                "output": 426,
                "cacheRead": 10752,
                "cacheWrite": 0,
                "totalTokens": 14051,
            },
            "timestamp": 101,
            "content": [{
                "type": "toolCall",
                "id": "call-room-commit",
                "name": "room_commit",
                "arguments": {"decision": "deliver"},
            }],
        }

        def send(payload: dict[str, object]) -> None:
            self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
                {
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": payload,
                }
            )

        send({"type": "message_end", "message": assistant})
        send({"type": "agent_end", "messages": [assistant]})
        send({"type": "agent_settled"})

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        event_types = [event.event_type for event in events]
        self.assertNotIn("message_completed", event_types)
        self.assertLess(
            event_types.index("response_evidence"),
            event_types.index("turn_completed"),
        )
        evidence = next(
            event.payload
            for event in events
            if event.event_type == "response_evidence"
        )
        self.assertEqual(evidence, {
            "toolCallId": "call-room-commit",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "usage": {
                "input": 2873,
                "output": 426,
                "cacheRead": 10752,
                "cacheWrite": 0,
                "totalTokens": 14051,
            },
            "usageReported": True,
            "cacheUsageReported": True,
        })

    def test_manual_and_automatic_compaction_notify_memory_checkpoint_observer(self) -> None:
        session_id = str(self.first["id"])

        manual = self.runtime.compact(session_id, "保留长期决定")
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol integration boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": "turn:auto-compact",
                "payload": {
                    "type": "compaction_end",
                    "trigger": "automatic",
                    "result": {
                        "summary": "自动压缩保留了桌面语义操控约束。",
                        "coverageStartEntryId": "entry-user-2",
                        "coverageEndEntryId": "entry-assistant-2",
                    },
                },
            }
        )

        self.assertTrue(manual["memoryCheckpoint"]["stored"])
        self.assertEqual(
            [(item[0], item[2]) for item in self.compactions],
            [(session_id, "manual"), (session_id, "automatic")],
        )
        self.assertEqual(
            self.compactions[1][1]["coverageEndEntryId"],
            "entry-assistant-2",
        )

    def test_one_host_keeps_multiple_sessions_open_and_syncs_dynamic_tools(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.store.set_thinking_level(first_id, "max")
        self.runtime.ensure(first_id)
        self.runtime.ensure(second_id)

        status = self.runtime.runtime_status()
        self.assertEqual(status["openSessionIds"], sorted([first_id, second_id]))
        self.assertTrue(status["capabilities"]["multiSession"])
        self.assertEqual(
            status["capabilities"]["runtimePrimitives"]["continuationEnvelope"],
            "1",
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperationRegistry"
            ]
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"]["sessionContinuationQueue"]
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperations"
            ]["manualCompaction"]
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperations"
            ]["bashProcess"]
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperations"
            ]["branchSummary"]
        )
        self.assertTrue(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperations"
            ]["continuationTimer"]
        )
        self.assertFalse(status["capabilities"]["runtimePrimitives"]["roomTypes"])
        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        opened = [row for row in requests if row["method"] == "session.open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0]["params"]["toolManifest"][0]["name"], "memory")
        self.assertEqual(opened[0]["params"]["thinkingLevel"], "max")

    def test_live_peer_runtime_manager_cannot_kill_the_active_host(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        client = self.runtime._client
        self.assertIsNotNone(client)
        assert client is not None
        active_host_identity = client.host_identity

        peer = PiRuntimeHostManager(
            config=self.runtime.config,
            sessions=self.store,
            events=self.events,
            tool_manifest_provider=lambda _session: [],
        )
        try:
            self.assertEqual(
                peer.runtime_status()["runtimeHostKillGate"][
                    "orphanReconcileReceipts"
                ],
                [],
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "unreconciled Runtime Host",
            ):
                peer.available_models()

            self.assertTrue(client.running)
            self.assertEqual(
                self.runtime.ensure(session_id)["state"][
                    "sessionId"
                ],
                session_id,
            )
            self.assertEqual(
                self.runtime._kill_gate.process(
                    active_host_identity
                )["state"],
                "running",
            )
        finally:
            peer.stop()

    def test_concurrent_catalog_reads_admit_exactly_one_runtime_host(self) -> None:
        workers = 6
        start_barrier = threading.Barrier(workers)
        state_lock = threading.Lock()
        active_starts = 0
        maximum_active_starts = 0
        errors: list[BaseException] = []
        catalogs: list[list[dict[str, object]]] = []
        original_start = PiRuntimeHostClient.start

        def delayed_start(client: PiRuntimeHostClient) -> dict[str, object]:
            nonlocal active_starts, maximum_active_starts
            with state_lock:
                active_starts += 1
                maximum_active_starts = max(
                    maximum_active_starts,
                    active_starts,
                )
            try:
                # Widen the admission window enough that the old unlocked
                # implementation deterministically started competing Hosts.
                time.sleep(0.05)
                return original_start(client)
            finally:
                with state_lock:
                    active_starts -= 1

        def read_catalog() -> None:
            start_barrier.wait()
            try:
                catalog = self.runtime.available_models()
                with state_lock:
                    catalogs.append(catalog)
            except BaseException as exc:
                with state_lock:
                    errors.append(exc)

        with patch.object(
            PiRuntimeHostClient,
            "start",
            autospec=True,
            side_effect=delayed_start,
        ):
            threads = [
                threading.Thread(target=read_catalog)
                for _ in range(workers)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(catalogs), workers)
        self.assertEqual(maximum_active_starts, 1)
        self.assertTrue(all(catalog for catalog in catalogs))
        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            sum(request["method"] == "hello" for request in requests),
            1,
        )
        self.assertEqual(
            sum(request["method"] == "models.list" for request in requests),
            1,
        )

    def test_close_session_keeps_other_hosted_sessions_ready(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.runtime.ensure(first_id)
        self.runtime.ensure(second_id)

        self.assertTrue(self.runtime.close_session(first_id))

        status = self.runtime.runtime_status()
        self.assertEqual(status["openSessionIds"], [second_id])
        self.assertEqual(self.store.get(first_id)["status"], "idle")
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        closed = [
            row["params"]["sessionId"]
            for row in requests
            if row["method"] == "session.close"
        ]
        self.assertEqual(closed, [first_id])
        self.assertTrue(self.runtime._client and self.runtime._client.running)  # noqa: SLF001

    def test_surface_profile_disables_project_context_files(self) -> None:
        surface = self.store.create(
            title="输入法联想 · test",
            session_kind="subagent_runtime",
            tool_profile_version="ime-surface-v1",
        )
        self.store.set_runtime_policy(
            str(surface["id"]),
            mode="assistant",
            tool_profile_version="ime-surface-v1",
            allowed_tools=[],
            workspace_roots=[],
        )

        self.runtime.ensure(str(surface["id"]))

        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        opened = [row for row in requests if row["method"] == "session.open"]
        self.assertTrue(opened[-1]["params"]["noContextFiles"])
        self.assertIn("只输出可以直接插入光标", opened[-1]["params"]["systemPrompt"])

    def test_memory_curation_profile_opens_without_tools_context_or_skills(self) -> None:
        memory_session = self.store.create(
            title="memory curation",
            session_kind="subagent_runtime",
            tool_profile_version="memory-curation-v1",
            project_context_enabled=True,
            pi_skills_enabled=True,
            codex_skills_enabled=True,
        )
        self.store.set_runtime_policy(
            str(memory_session["id"]),
            mode="assistant",
            tool_profile_version="memory-curation-v1",
            allowed_tools=["memory"],
            project_context_enabled=True,
            pi_skills_enabled=True,
            codex_skills_enabled=True,
            workspace_roots=[str(self.root)],
        )

        self.runtime.ensure(str(memory_session["id"]))

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened = [row for row in requests if row["method"] == "session.open"][-1]
        self.assertEqual(opened["params"]["toolManifest"], [])
        self.assertTrue(opened["params"]["noContextFiles"])
        self.assertFalse(opened["params"]["piSkillsEnabled"])
        self.assertFalse(opened["params"]["codexSkillsEnabled"])
        self.assertIn(
            "governed personal-memory curation engine",
            opened["params"]["systemPrompt"],
        )

    def test_agent_end_is_not_terminal_and_max_comes_from_host_catalog(self) -> None:
        session_id = str(self.first["id"])
        catalog = self.runtime.model_catalog(session_id)
        self.assertEqual(catalog["models"][0]["thinkingLevels"], ["off", "medium", "xhigh", "max"])
        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [request["method"] for request in requests],
            ["hello", "models.list"],
        )
        self.assertEqual(self.runtime.runtime_status()["openSessionIds"], [])
        self.runtime.set_thinking_level(session_id, level="max")

        accepted = self.runtime.prompt(session_id, "hello", client_message_id="client-1")
        self.assertEqual(accepted["clientMessageId"], "client-1")
        time.sleep(0.05)
        self.assertEqual(self.store.get(session_id)["status"], "busy")
        self.assertFalse(any(item.event_type == "turn_completed" for item in self.events.replay(session_id)[0]))

        _wait_until(
            lambda: any(
                item.event_type == "turn_completed"
                for item in self.events.replay(session_id)[0]
            )
        )
        completed = [item for item in self.events.replay(session_id)[0] if item.event_type == "turn_completed"]
        self.assertEqual(completed[-1].payload["terminalEvent"], "agent_settled")
        messages = self.runtime.messages(session_id)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])

    def test_provider_retry_events_are_projected_without_raw_diagnostics(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-provider-retry"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "auto_retry_start",
                "attempt": 2,
                "maxAttempts": 3,
                "delayMs": 4_000,
                "errorMessage": "private upstream diagnostic",
            },
        })
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_end",
                "willRetry": True,
                "messages": [{
                    "role": "assistant",
                    "stopReason": "error",
                    "errorMessage": "private upstream diagnostic",
                    "content": [],
                }],
            },
        })

        events = self.events.replay(session_id)[0]
        statuses = [
            event for event in events
            if event.event_type == "status_changed"
            and event.payload.get("phase") == "provider_retry"
        ]
        self.assertEqual(statuses[-1].payload["status"], "retrying")
        self.assertEqual(statuses[-1].payload["attempt"], 2)
        self.assertEqual(statuses[-1].payload["maxAttempts"], 3)
        self.assertFalse(any(event.event_type == "turn_failed" for event in events))
        self.assertNotIn(
            "private upstream diagnostic",
            json.dumps(statuses[-1].payload, ensure_ascii=False),
        )

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "auto_retry_end",
                "attempt": 2,
                "success": False,
                "finalError": "must not escape",
            },
        })
        statuses = [
            event for event in self.events.replay(session_id)[0]
            if event.event_type == "status_changed"
            and event.payload.get("phase") == "provider_retry"
        ]
        self.assertEqual(statuses[-1].payload["status"], "working")
        self.assertEqual(statuses[-1].payload["activityState"], "failed")
        self.assertNotIn(
            "must not escape",
            json.dumps(statuses[-1].payload, ensure_ascii=False),
        )

    def test_nonfatal_extension_error_does_not_terminalize_active_turn(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-extension-warning"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "extension_error",
                "extensionPath": "session-context-refresh.ts",
                "event": "before_agent_start",
                "error": "optional context refresh failed",
            },
        })

        events = self.events.replay(session_id)[0]
        warnings = [
            event for event in events
            if event.event_type == "status_changed"
            and event.payload.get("phase") == "extension_warning"
        ]
        self.assertEqual(warnings[-1].payload["status"], "working")
        self.assertEqual(
            warnings[-1].payload["extensionEvent"],
            "before_agent_start",
        )
        self.assertFalse(
            any(event.event_type == "turn_failed" for event in events)
        )
        with self.runtime._lock:
            self.assertEqual(
                self.runtime._states[session_id].turn_id,
                turn_id,
            )

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_end",
                "messages": [{
                    "role": "assistant",
                    "content": [{"type": "text", "text": "继续并完成"}],
                }],
            },
        })
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {"type": "agent_settled"},
        })

        events = self.events.replay(session_id)[0]
        self.assertFalse(
            any(event.event_type == "turn_failed" for event in events)
        )
        completed = [
            event for event in events
            if event.event_type == "turn_completed"
        ]
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "agent_settled",
        )

    def test_tool_loop_no_progress_becomes_one_public_failed_terminal(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-tool-loop-no-progress"
        with self.runtime._lock:
            state = self.runtime._states[session_id]
            state.turn_id = turn_id
            state.had_tool_activity = True

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "tool_loop_no_progress",
                "message": "Tool Loop 连续未产生成功结果，已按受管无进展策略停止。",
                "reason": "repeated_failure_signature",
                "consecutiveAllErrorTurns": 3,
                "repeatedFailureSignature": 3,
                "toolNames": ["read"],
            },
        })
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_end",
                "messages": [{
                    "role": "assistant",
                    "stopReason": "toolUse",
                    "content": [{
                        "type": "toolCall",
                        "id": "call-3",
                        "name": "read",
                        "arguments": {"path": "/missing"},
                    }],
                }],
            },
        })
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {"type": "agent_settled"},
        })

        events = self.events.replay(session_id)[0]
        guarded = [
            event for event in events
            if event.event_type == "status_changed"
            and event.payload.get("phase") == "tool_loop_no_progress"
        ]
        self.assertEqual(guarded[-1].payload["reason"], "repeated_failure_signature")
        self.assertEqual(guarded[-1].payload["toolNames"], ["read"])
        failed = [
            event for event in events
            if event.event_type == "turn_failed"
            and event.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertIn("受管无进展策略停止", failed[0].payload["error"])
        self.assertFalse(failed[0].payload["retryable"])
        self.assertEqual(self.store.get(session_id)["status"], "faulted")

    def test_snapshot_collapses_only_adjacent_duplicate_assistant_projection(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(session_id, "duplicate-final-snapshot")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        messages = self.runtime.messages(session_id)

        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(
            messages[-1]["blocks"][0]["data"]["text"],
            f"host reply for {session_id}",
        )

    def test_snapshot_uses_durable_entries_to_remove_cross_turn_assistant_replay(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(session_id, "first turn")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")
        self.runtime.prompt(session_id, "duplicate-across-native-followup")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        messages = self.runtime.messages(session_id)
        assistant_texts = [
            item["blocks"][0]["data"]["text"]
            for item in messages
            if item["role"] == "assistant"
        ]

        self.assertEqual(
            assistant_texts,
            [
                f"host reply for {session_id}",
                f"second host reply for {session_id}",
            ],
        )

    def test_v2_exposes_managed_skill_commands_to_the_composer(self) -> None:
        session_id = str(self.first["id"])

        self.assertEqual(
            self.runtime.command_catalog(session_id),
            [
                {
                    "name": "skill:plugin-creator",
                    "invocation": "/skill:plugin-creator",
                    "description": "Create and propose a managed plugin",
                    "source": "skill",
                }
            ],
        )

    def test_v2_fork_uses_host_owned_anchor_and_binds_a_distinct_target(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.assertTrue(self.runtime.runtime_status()["capabilities"]["conversationFork"])
        self.runtime.prompt(first_id, "从这条消息建立分支")
        _wait_until(lambda: self.store.get(first_id)["status"] == "idle")
        self.assertTrue(self.runtime.runtime_status()["capabilities"]["transientContext"])
        source_binding = self.store.runtime_binding(first_id)

        self.assertEqual(
            self.runtime.fork_candidates(first_id),
            [
                {
                    "entryId": "entry-user-1",
                    "text": "从这条消息建立分支",
                    "role": "user",
                    "createdAtMs": 100,
                },
                {
                    "entryId": "entry-assistant-1",
                    "text": f"host reply for {first_id}",
                    "role": "assistant",
                    "createdAtMs": 101,
                },
            ],
        )
        forked = self.runtime.fork_session(first_id, second_id, entry_id="entry-user-1")

        self.assertTrue(self.runtime.runtime_status()["capabilities"]["conversationFork"])
        self.assertEqual(self.store.runtime_binding(first_id), source_binding)
        target_binding = self.store.runtime_binding(second_id)
        self.assertIsNotNone(target_binding)
        assert source_binding is not None and target_binding is not None
        self.assertNotEqual(target_binding["externalSessionId"], source_binding["externalSessionId"])
        self.assertNotEqual(target_binding["transcriptRef"], source_binding["transcriptRef"])
        self.assertEqual(target_binding["branchAnchor"], "entry-user-1")
        self.assertEqual(target_binding["metadata"]["forkedFromSessionId"], first_id)
        self.assertEqual(forked["selectedText"], "从这条消息建立分支")
        self.assertEqual(self.store.get(first_id)["status"], "idle")
        self.assertEqual(self.store.get(second_id)["status"], "idle")

        self.runtime.prompt(second_id, "只发送到新分支")
        _wait_until(lambda: self.store.get(second_id)["status"] == "idle")
        self.assertEqual(self.runtime.messages(second_id)[0]["blocks"][0]["data"]["text"], "只发送到新分支")

    def test_v2_fork_after_assistant_keeps_answer_context_without_restoring_draft(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.runtime.prompt(first_id, "先回答这个问题")
        _wait_until(lambda: self.store.get(first_id)["status"] == "idle")

        forked = self.runtime.fork_session(
            first_id,
            second_id,
            entry_id="entry-assistant-1",
        )

        self.assertEqual(forked["selectedText"], "")
        target_binding = self.store.runtime_binding(second_id)
        self.assertIsNotNone(target_binding)
        assert target_binding is not None
        self.assertEqual(target_binding["branchAnchor"], "entry-assistant-1")

    def test_v2_fork_catalog_exposes_only_the_public_deep_search_question(self) -> None:
        first_id = str(self.first["id"])
        self.runtime.prompt(
            first_id,
            "<agent-deep-search-context>private evidence</agent-deep-search-context>\n"
            "<agent-user-query>最近做了什么？</agent-user-query>\n"
            "本地时间：2026-07-16",
        )
        _wait_until(lambda: self.store.get(first_id)["status"] == "idle")

        candidates = self.runtime.fork_candidates(first_id)

        self.assertEqual(
            candidates,
            [
                {
                    "entryId": "entry-user-1",
                    "text": "最近做了什么？",
                    "role": "user",
                    "createdAtMs": 100,
                },
                {
                    "entryId": "entry-assistant-1",
                    "text": f"host reply for {first_id}",
                    "role": "assistant",
                    "createdAtMs": 101,
                },
            ],
        )
        self.assertNotIn("private evidence", json.dumps(candidates, ensure_ascii=False))

    def test_v2_fork_rejects_unknown_anchor_without_binding_target(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.runtime.prompt(first_id, "原始消息")
        _wait_until(lambda: self.store.get(first_id)["status"] == "idle")
        source_binding = self.store.runtime_binding(first_id)

        with self.assertRaisesRegex(PiRuntimeError, "not available"):
            self.runtime.fork_session(first_id, second_id, entry_id="entry-missing")

        self.assertEqual(self.store.runtime_binding(first_id), source_binding)
        self.assertIsNone(self.store.runtime_binding(second_id))

    def test_prompt_rejects_a_second_turn_until_the_active_turn_settles(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = "turn-still-aborting"

        with self.assertRaisesRegex(PiRuntimeError, "上一轮") as conflict:
            self.runtime.prompt(session_id, "不要覆盖旧回合")
        self.assertEqual(
            conflict.exception.error_code,
            "AGENT_TURN_CONFLICT",
        )

    def test_busy_turn_accepts_native_steer_and_follow_up_messages(self) -> None:
        session_id = str(self.first["id"])
        active = self.runtime.prompt(session_id, "hang-without-settled", client_message_id="initial")

        steered = self.runtime.prompt(
            session_id,
            "先不要修改配置",
            client_message_id="steer-1",
            delivery="steer",
        )
        followed = self.runtime.prompt(
            session_id,
            "完成后再给我测试结果",
            client_message_id="follow-1",
            delivery="followUp",
        )

        self.assertEqual(steered["turnId"], active["turnId"])
        self.assertEqual(followed["turnId"], active["turnId"])
        self.assertTrue(steered["queued"])
        self.assertEqual(followed["delivery"], "followUp")
        _wait_until(
            lambda: len([
                item for item in self.events.replay(session_id)[0]
                if item.event_type == "message_queue_updated"
            ]) >= 2
        )
        queue_events = [
            item for item in self.events.replay(session_id)[0]
            if item.event_type == "message_queue_updated"
        ]
        self.assertEqual(queue_events[-1].payload["steering"], ["先不要修改配置"])
        self.assertEqual(queue_events[-1].payload["followUp"], ["完成后再给我测试结果"])
        snapshot = self.runtime.session_snapshot(session_id)
        self.assertEqual(snapshot["messageQueue"]["steering"], ["先不要修改配置"])
        self.assertEqual(snapshot["messageQueue"]["followUp"], ["完成后再给我测试结果"])
        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        self.assertIn("session.steer", [row["method"] for row in requests])
        self.assertIn("session.follow_up", [row["method"] for row in requests])

    def test_debug_context_reads_a_resident_busy_session_without_snapshot(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(
            session_id,
            "hang-without-settled",
            client_message_id="debug-active",
        )

        self.assertEqual(self.runtime.debug_context(session_id), {})

        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        methods = [item["method"] for item in requests]
        self.assertEqual(methods[-1], "session.debug.context")
        self.assertNotIn("session.snapshot", methods)

    def test_idle_control_probe_closes_tool_loop_when_agent_settled_is_lost(self) -> None:
        session_id = str(self.first["id"])
        accepted = self.runtime.prompt(
            session_id,
            "end-without-settled",
            client_message_id="lost-settled",
        )
        turn_id = str(accepted["turnId"])

        _wait_until(
            lambda: any(
                item.event_type == "turn_completed"
                and item.turn_id == turn_id
                for item in self.events.replay(session_id)[0]
            ),
            timeout=2.5,
        )
        completed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_completed"
            and item.turn_id == turn_id
        ]
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "idle_control_reconciliation",
        )
        self.assertEqual(completed[-1].payload["status"], "completed")
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

        continued = self.runtime.prompt(
            session_id,
            "继续发送",
            client_message_id="after-lost-settled",
        )
        self.assertTrue(continued["accepted"])


    def test_settled_extension_error_retires_stale_host_turn(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-settled-extension-error"
        assistant = {
            "role": "assistant",
            "content": [{"type": "text", "text": "review complete"}],
        }
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id
        self.store.set_status(session_id, "busy")
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_end",
                "messages": [assistant],
            },
        })
        client = self.runtime._require_client()
        original_send = client.send

        def stale_control_state(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if method == "session.control_state":
                return {
                    "isIdle": True,
                    "activeTurn": {"turnId": turn_id},
                }
            return original_send(method, params, timeout=timeout)

        with patch.object(
            client,
            "send",
            side_effect=stale_control_state,
        ):
            self.runtime._settle_fallback_probe(session_id, turn_id)
            self.assertEqual(
                self.runtime._states[session_id].turn_id,
                turn_id,
            )
            self.runtime._handle_host_event({
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "payload": {
                    "type": "extension_error",
                    "event": "agent_settled",
                    "error": "Room settlement guard rejected the final commit",
                },
            })
            self.runtime._settle_fallback_probe(session_id, turn_id)

        completed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_completed"
            and item.turn_id == turn_id
        ]
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "idle_control_reconciliation",
        )
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_agent_settle_failed_retires_stale_room_turn(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-room-settle-failed"
        with self.runtime._lock:
            state = self.runtime._states[session_id]
            state.turn_id = turn_id
            state.last_agent_messages = [{
                "role": "assistant",
                "content": [{"type": "text", "text": "review complete"}],
            }]
        self.store.set_status(session_id, "busy")
        client = self.runtime._require_client()
        original_send = client.send

        def stale_control_state(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if method == "session.control_state":
                return {
                    "isIdle": True,
                    "activeTurn": {"turnId": turn_id},
                }
            return original_send(method, params, timeout=timeout)

        with patch.object(
            client,
            "send",
            side_effect=stale_control_state,
        ):
            self.runtime._handle_host_event({
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "payload": {
                    "type": "agent_settle_failed",
                    "error": "Room settlement request returned HTTP 400",
                },
            })
            self.runtime._settle_fallback_probe(session_id, turn_id)

        completed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_completed"
            and item.turn_id == turn_id
        ]
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "idle_control_reconciliation",
        )
        warnings = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "status_changed"
            and item.payload.get("phase") == "settlement_warning"
        ]
        self.assertIn("HTTP 400", warnings[-1].payload["warning"])
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_abort_ack_without_agent_settled_escalates_to_durable_host_tree_kill(self) -> None:
        session_id = str(self.first["id"])
        accepted = self.runtime.prompt(session_id, "hang-without-settled")
        turn_id = str(accepted["turnId"])

        self.runtime.abort(session_id)

        _wait_until(
            lambda: any(
                item.event_type == "turn_completed" and item.payload.get("status") == "aborted"
                for item in self.events.replay(session_id)[0]
            ),
            timeout=2.5,
        )
        completed = [item for item in self.events.replay(session_id)[0] if item.event_type == "turn_completed"]
        self.assertEqual(completed[-1].turn_id, turn_id)
        self.assertEqual(completed[-1].payload["status"], "aborted")
        self.assertEqual(completed[-1].payload["terminalEvent"], "abort_timeout_kill")
        _wait_until(
            lambda: any(
                item.event_type == "status_changed"
                and item.payload.get("escalated") is True
                for item in self.events.replay(session_id)[0]
            ),
            timeout=2.5,
        )
        escalations = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "status_changed"
            and item.payload.get("escalated") is True
        ]
        self.assertEqual(escalations[-1].payload["status"], "idle")
        self.assertEqual(escalations[-1].payload["runtimeStatus"], "stopping")
        _wait_until(
            lambda: self.runtime.runtime_status()["status"] == "faulted"
            and self.runtime.runtime_status()["runtimeHostKillGate"]["lastKillReceipt"] is not None
        )
        kill_gate = self.runtime.runtime_status()["runtimeHostKillGate"]
        self.assertEqual(kill_gate["lastKillReceipt"]["requestKind"], "cancel_timeout")
        self.assertEqual(kill_gate["lastKillReceipt"]["state"], "terminated")

        completed_count = len(completed)
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {"type": "agent_settled"},
        })
        self.assertEqual(
            len([item for item in self.events.replay(session_id)[0] if item.event_type == "turn_completed"]),
            completed_count,
        )
        self.assertNotIn(session_id, self.runtime._states)

    def test_abort_settled_error_is_terminal_aborted_not_faulted(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = f"turn-{session_id}"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id
        self.store.set_status(session_id, "busy")

        self.runtime.abort(session_id)
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_end",
                "messages": [{
                    "role": "assistant",
                    "stopReason": "error",
                    "errorMessage": "This operation was aborted",
                    "content": [],
                }],
            },
        })
        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {"type": "agent_settled"},
        })

        self.assertEqual(self.store.get(session_id)["status"], "idle")
        events = self.events.replay(session_id)[0]
        self.assertFalse(any(item.event_type == "turn_failed" for item in events))
        completed = [item for item in events if item.event_type == "turn_completed"]
        self.assertEqual(completed[-1].payload["status"], "aborted")
        self.assertEqual(completed[-1].payload["terminalEvent"], "agent_settled")

    def test_open_idle_session_can_list_fork_candidates(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        self.assertEqual(self.store.get(session_id)["status"], "idle")

        self.assertEqual(self.runtime.fork_candidates(session_id), [])
        self.assertEqual(self.store.get(session_id)["status"], "idle")

    def test_turn_failure_uses_supported_faulted_status_and_publishes_event(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)

        self.runtime._turn_failed(session_id, "turn-provider-error", RuntimeError("provider failed"))

        self.assertEqual(self.store.get(session_id)["status"], "faulted")
        failed = [item for item in self.events.replay(session_id)[0] if item.event_type == "turn_failed"]
        self.assertEqual(failed[-1].turn_id, "turn-provider-error")
        self.assertEqual(failed[-1].payload["error"], "provider failed")
        self.assertEqual(
            failed[-1].payload["reasonCode"],
            "provider_failure_unclassified",
        )
        self.assertFalse(failed[-1].payload["retryable"])
        self.assertFalse(failed[-1].payload["hadToolActivity"])

    def test_transport_failure_without_tool_activity_is_retryable(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)

        self.runtime._turn_failed(
            session_id,
            "turn-transport-error",
            RuntimeError("fetch failed"),
        )

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed"
        ][-1]
        self.assertEqual(
            failed.payload["failureKind"],
            "transient_provider_failure",
        )
        self.assertEqual(
            failed.payload["reasonCode"],
            "provider_transport_failure",
        )
        self.assertTrue(failed.payload["retryable"])
        self.assertFalse(failed.payload["hadToolActivity"])

    def test_transport_failure_after_tool_activity_is_not_retryable(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        with self.runtime._lock:
            self.runtime._states[session_id].had_tool_activity = True

        self.runtime._turn_failed(
            session_id,
            "turn-tool-transport-error",
            RuntimeError("fetch failed"),
        )

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed"
        ][-1]
        self.assertEqual(
            failed.payload["reasonCode"],
            "tool_activity_observed",
        )
        self.assertFalse(failed.payload["retryable"])
        self.assertTrue(failed.payload["hadToolActivity"])

    def test_host_exit_is_classified_separately_from_provider_failure(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        client = self.runtime._client
        self.assertIsNotNone(client)
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = (
                "turn-runtime-host-exit"
            )
            self.runtime._states[session_id].had_tool_activity = True

        try:
            self.runtime._handle_host_exit(-9, "")

            failed = [
                item
                for item in self.events.replay(session_id)[0]
                if item.event_type == "turn_failed"
            ]
            self.assertEqual(
                failed[-1].payload["failureKind"],
                "runtime_host_exit",
            )
            self.assertEqual(failed[-1].payload["exitCode"], -9)
            self.assertEqual(
                failed[-1].payload["reasonCode"],
                "runtime_host_exit",
            )
            self.assertTrue(failed[-1].payload["retryable"])
            self.assertTrue(failed[-1].payload["hadToolActivity"])
            self.assertEqual(
                failed[-1].payload["error"],
                "Pi Runtime Host exited with code -9",
            )
        finally:
            assert client is not None
            client.stop()

    def test_stop_publishes_recoverable_failure_for_active_turn(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = (
                "turn-runtime-service-stop"
            )
            self.runtime._states[session_id].had_tool_activity = True

        self.runtime.stop()

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed"
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(
            failed[0].payload["failureKind"],
            "runtime_host_exit",
        )
        self.assertEqual(
            failed[0].payload["reasonCode"],
            "runtime_host_exit",
        )
        self.assertTrue(failed[0].payload["retryable"])
        self.assertTrue(failed[0].payload["hadToolActivity"])

    def test_truncated_final_stdout_frame_keeps_host_exit_as_diagnostic(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.config = replace(
            self.runtime.config,
            provider_environment={"TEST_PARTIAL_STDOUT_EXIT": "1"},
        )
        self.runtime.ensure(session_id)
        client = self.runtime._client
        self.assertIsNotNone(client)
        assert client is not None

        with self.assertRaises(PiRuntimeError) as caught:
            client.send("models.list")

        _wait_until(lambda: self.runtime._status == "faulted")
        self.assertNotIn("invalid Pi Runtime Host JSONL", str(caught.exception))
        self.assertNotIn("Unterminated string", self.runtime._last_error)
        self.assertEqual(
            self.runtime._last_error,
            "Pi Runtime Host exited with code -9",
        )

    def _record_event(self, event) -> None:
        self.store.record_runtime_event(
            event_id=event.event_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            sequence=event.sequence,
            event_type=event.event_type,
            created_at_ms=event.created_at_ms,
            redacted_summary=str(event.payload.get("status") or event.payload.get("error") or ""),
        )


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


if __name__ == "__main__":
    unittest.main()
