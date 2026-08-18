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
    pi_message_completes_public_turn,
    pi_message_is_public,
    pi_message_payload,
    public_code_tool_activity,
    public_reasoning_summaries,
    public_usage_evidence,
)
from rag_ime.pi_runtime_v2 import (
    PiRuntimeHostClient,
    PiRuntimeHostManager,
    _pi_durable_branch_messages,
    _pi_tool_history_events,
    _runtime_primitive_capabilities,
)
from rag_ime.pi_runtime_values import PiRuntimeCommandRejected


FAKE_HOST = r'''#!/usr/bin/env python3
import json
import os
import pathlib
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
                             "continuationEnvelope": os.environ.get("TEST_CONTINUATION_ENVELOPE", "2"),
                             "cancelScope": "1",
                             "sessionContinuationQueue": True,
                             "sessionCancelOperationRegistry": True,
                             "sessionCancelOperations": {
                                 "provider": True, "tool": True, "retrySleep": True,
                                 "manualCompaction": True, "autoCompaction": True,
                                 "branchSummary": True, "bashProcess": True,
                                 "continuationTimer": True}}}})
    elif method == "health":
        result(request, {"ok": True, "protocolVersion": "2",
                         "openSessions": len(sessions), "maxSessions": 4, "modelError": ""})
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
        session = sessions.setdefault(session_id, {
            "sessionId": session_id, "piSessionId": "pi-" + session_id,
            "sessionFile": str(pathlib.Path(os.environ["RAG_IME_PI_SESSION_DIR"]) / (session_id + ".jsonl")),
            "leafId": "", "messages": [], "thinkingLevel": params.get("thinkingLevel", "medium"),
            "model": model,
            "isIdle": True,
            "messageQueue": {"steering": [], "followUp": [], "steeringMode": "one-at-a-time",
                             "followUpMode": "one-at-a-time"},
        })
        if os.environ.get("TEST_SESSION_OPEN_MESSAGE_COUNT"):
            session["messageCount"] = int(os.environ["TEST_SESSION_OPEN_MESSAGE_COUNT"])
        result(request, {"snapshot": session, "evictedSessionId": None})
    elif method == "session.control_state":
        session = sessions[session_id]
        result(request, {
            "schemaVersion": "rag-ime.pi-session-control-state.v1",
            "sessionId": session_id,
            "isIdle": session.get("isIdle", True),
            "isCompacting": False,
            "activeTurn": None,
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
        if params.get("message") == "host-reject-session-idle":
            write({"protocolVersion": "2", "id": request["id"], "ok": False,
                   "error": {"code": "SESSION_IDLE",
                             "message": "Session has no active turn to receive a queued message"}})
            continue
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
    elif method == "session.debug.context":
        if os.environ.get("TEST_DEBUG_CONTEXT_HANG") == "1":
            time.sleep(2)
        result(request, {})
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

    def test_opening_runtime_does_not_replace_public_message_count_with_provider_entries(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        self.store.set_status(
            session_id,
            "idle",
            message_count=3,
            last_message_preview="公开助手回复",
        )

        self.runtime.config = replace(
            self.runtime.config,
            provider_environment={"TEST_SESSION_OPEN_MESSAGE_COUNT": "61"},
        )
        self.runtime.ensure(session_id)

        session = self.store.get(session_id)
        self.assertEqual(session["messageCount"], 3)
        self.assertEqual(session["lastMessagePreview"], "公开助手回复")

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

    def test_stateless_completion_timeout_cancels_only_that_request(self) -> None:
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
        self.assertIsNone(receipt)
        self.assertEqual(timed_out_status["status"], "ready")
        self.assertTrue(first_client.running)

        retried = self.runtime.complete_once(
            request_id="surface-timeout-retry",
            provider="deepseek",
            model_id="deepseek-v4-flash",
            thinking_level="high",
            message="新 Host 应该正常完成",
            timeout_seconds=15,
        )

        self.assertEqual(retried["text"], "one-shot reply")
        self.assertIs(self.runtime._client, first_client)
        self.assertEqual(self.runtime._client.host_identity, first_host_identity)
        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertIn("completion.cancel", [request["method"] for request in requests])

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

    def test_pi_package_draft_and_prepare_use_native_host_methods_without_approval(self) -> None:
        self.runtime.plugin_create_package(
            {
                "draftId": "context-helper",
                "packageJson": {
                    "name": "@paw/context-helper",
                    "version": "1.0.0",
                    "pi": {"skills": ["skills/context-helper/SKILL.md"]},
                },
                "files": {"skills/context-helper/SKILL.md": "skill body"},
            }
        )
        self.runtime.plugin_prepare_package("npm:@paw/context-helper@1.0.0")

        requests = [
            json.loads(line)
            for line in (self.root / "agent" / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        package_requests = [
            request
            for request in requests
            if request["method"] in {"plugins.package.create", "plugins.package.prepare"}
        ]
        self.assertEqual(
            [request["method"] for request in package_requests],
            ["plugins.package.create", "plugins.package.prepare"],
        )
        self.assertEqual(
            package_requests[1]["params"],
            {"source": "npm:@paw/context-helper@1.0.0"},
        )
        self.assertTrue(
            all("approvalToken" not in request["params"] for request in package_requests)
        )

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
        edit = public_code_tool_activity(
            "workspace_edit",
            {
                "operation": "apply",
                "path": "src/main.py",
                "edits": [{
                    "oldText": "first\nsecond\n",
                    "newText": "replacement\n",
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
        self.assertEqual(edit["additions"], 1)
        self.assertEqual(edit["deletions"], 2)
        serialized_edit = json.dumps(edit)
        self.assertNotIn("edits", serialized_edit)
        self.assertNotIn("oldText", serialized_edit)
        self.assertNotIn("newText", serialized_edit)

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

    def test_coding_tool_projection_redacts_commands_and_never_previews_secret_files(self) -> None:
        command = public_code_tool_activity(
            "bash",
            {
                "command": (
                    "OPENAI_API_KEY=plain-secret python scripts/probe.py "
                    "--token bearer-secret"
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
        self.assertEqual(
            command["command"],
            (
                "OPENAI_API_KEY=[REDACTED_SECRET] python scripts/probe.py "
                "--token [REDACTED_SECRET]"
            ),
        )
        self.assertEqual(command["outputPreview"], "probe complete")
        self.assertNotIn("outputPreview", secret_file)
        self.assertNotIn("do-not-show", json.dumps(secret_file))

    def test_host_coding_tool_event_keeps_public_projection_and_inspectable_result(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-grep-projection"
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "tool_execution_update",
                    "toolCallId": "call-grep-progress-projection",
                    "toolName": "grep",
                    "args": {"path": "rag_ime", "pattern": "provider_payload"},
                    "partialResult": {
                        "content": [{
                            "type": "text",
                            "text": "rag_ime/pi_runtime.py:90:provider_payload pending",
                        }],
                    },
                    "isError": False,
                },
            }
        )
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
                        "details": {
                            "sourcePath": "/Users/private/project/rag_ime/pi_runtime.py",
                            "accessToken": "do-not-render-this-token",
                        },
                    },
                    "isError": False,
                },
            }
        )

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        progress_event = next(
            item
            for item in events
            if item.event_type == "tool_progress"
            and item.payload.get("toolCallId") == "call-grep-progress-projection"
        )
        self.assertEqual(
            progress_event.payload["publicResult"]["outputPreview"],
            "rag_ime/pi_runtime.py:90:provider_payload pending",
        )
        self.assertNotIn("partialResult", progress_event.payload)
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
        self.assertEqual(
            event.payload["result"]["content"][0]["text"],
            "rag_ime/pi_runtime.py:100:def provider_payload():",
        )
        self.assertEqual(
            event.payload["result"]["details"]["sourcePath"],
            "/Users/private/project/rag_ime/pi_runtime.py",
        )
        self.assertEqual(
            event.payload["result"]["details"]["accessToken"],
            "[REDACTED_SECRET]",
        )

    def test_host_bash_receipt_exit_status_is_the_authoritative_tool_result(self) -> None:
        session_id = str(self.first["id"])
        turn_id = "turn-bash-exit-status"

        cases = (
            ("success", {"exitCode": 0, "timedOut": False}, False),
            ("failed", {"exitCode": 1, "timedOut": False}, True),
            ("timeout", {"exitCode": -15, "timedOut": True}, True),
        )
        for label, receipt, expected_error in cases:
            self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
                {
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": {
                        "type": "tool_execution_end",
                        "toolCallId": f"call-bash-{label}",
                        "toolName": "bash",
                        "args": {},
                        "result": {
                            "content": [{
                                "type": "text",
                                "text": (
                                    "FAILED is ordinary command output"
                                    if label == "success"
                                    else f"command {label}"
                                ),
                            }],
                            "details": {"receipt": receipt},
                        },
                        # Backend coding tools currently return a normal Pi
                        # ToolResult even when their structured command receipt
                        # records a non-zero exit. The receipt, not output text,
                        # is the command's terminal authority.
                        "isError": False,
                    },
                }
            )

        # Pi-originated interruption already carries isError and must remain a
        # failure even when there is no command receipt to inspect.
        self.runtime._handle_host_event(  # noqa: SLF001 - protocol boundary
            {
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": {
                    "type": "tool_execution_end",
                    "toolCallId": "call-bash-aborted",
                    "toolName": "bash",
                    "args": {},
                    "result": {
                        "content": [{"type": "text", "text": "Command aborted"}],
                    },
                    "isError": True,
                },
            }
        )

        events = {
            str(item.payload.get("toolCallId")): item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "tool_finished"
            and item.turn_id == turn_id
        }
        self.assertFalse(events["call-bash-success"].payload["isError"])
        for label in ("failed", "timeout", "aborted"):
            with self.subTest(label=label):
                payload = events[f"call-bash-{label}"].payload
                self.assertTrue(payload["isError"])
                self.assertEqual(
                    payload["publicResult"]["error"],
                    payload["publicResult"]["outputPreview"],
                )

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

    def test_transcript_tool_messages_rebuild_an_inspectable_durable_timeline(self) -> None:
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
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("top-secret", serialized)
        self.assertIn("/Users/private/project/README.md", serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)

    def test_transcript_bash_failure_uses_the_structured_exit_receipt(self) -> None:
        raw_messages = [
            {
                "id": "user-bash",
                "role": "user",
                "timestamp": 100,
                "content": [{"type": "text", "text": "运行测试"}],
            },
            {
                "id": "assistant-bash",
                "role": "assistant",
                "timestamp": 101,
                "content": [{
                    "type": "toolCall",
                    "id": "tool-bash-failed",
                    "name": "bash",
                    "arguments": {"command": "python3 -m unittest"},
                }],
            },
            {
                "role": "toolResult",
                "timestamp": 102,
                "toolCallId": "tool-bash-failed",
                "toolName": "bash",
                "isError": False,
                "content": [{"type": "text", "text": "FAILED"}],
                "details": {
                    "receipt": {
                        "exitCode": 1,
                        "timedOut": False,
                    }
                },
            },
        ]

        events = _pi_tool_history_events(
            raw_messages,
            session_id="session-bash-history",
        )

        finished = next(
            event for event in events if event["eventType"] == "tool_finished"
        )
        self.assertTrue(finished["payload"]["isError"])

    def test_tool_history_applies_one_bounded_public_budget_per_session_snapshot(
        self,
    ) -> None:
        raw_messages: list[dict[str, object]] = [{
            "id": "user-tool-budget",
            "role": "user",
            "timestamp": 100,
            "content": [{"type": "text", "text": "执行多项检查"}],
        }]
        for index in range(20):
            tool_call_id = f"tool-budget-{index + 1}"
            raw_messages.extend([
                {
                    "id": f"assistant-{index + 1}",
                    "role": "assistant",
                    "timestamp": 101 + index * 2,
                    "content": [{
                        "type": "toolCall",
                        "id": tool_call_id,
                        "name": "bash",
                        "arguments": {"command": f"probe-{index + 1}"},
                    }],
                },
                {
                    "role": "toolResult",
                    "timestamp": 102 + index * 2,
                    "toolCallId": tool_call_id,
                    "toolName": "bash",
                    "isError": False,
                    "details": {"output": "X" * 5_000},
                },
            ])

        events = _pi_tool_history_events(
            raw_messages,
            session_id="session-tool-budget",
        )
        serialized = json.dumps(
            events,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        tool_ids = {
            str(event["payload"].get("toolCallId") or "")
            for event in events
        }

        self.assertLessEqual(len(serialized), 50_000)
        self.assertIn("tool-budget-20", tool_ids)
        self.assertNotIn("tool-budget-1", tool_ids)
        for tool_call_id in tool_ids:
            self.assertEqual(
                [
                    event["eventType"]
                    for event in events
                    if event["payload"].get("toolCallId")
                    == tool_call_id
                ],
                ["tool_started", "tool_finished"],
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
            "2",
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
        self.assertNotIn("roomTypes", status["capabilities"]["runtimePrimitives"])
        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        opened = [row for row in requests if row["method"] == "session.open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0]["params"]["toolManifest"][0]["name"], "memory")
        self.assertEqual(opened[0]["params"]["thinkingLevel"], "max")

    def test_runtime_primitives_accept_only_supported_continuation_envelopes(self) -> None:
        self.assertEqual(
            _runtime_primitive_capabilities({"continuationEnvelope": "1"})[
                "continuationEnvelope"
            ],
            "1",
        )
        self.assertEqual(
            _runtime_primitive_capabilities({"continuationEnvelope": "2"})[
                "continuationEnvelope"
            ],
            "2",
        )
        for unsupported in ("3", 2, True, None):
            with self.subTest(unsupported=unsupported):
                self.assertEqual(
                    _runtime_primitive_capabilities(
                        {"continuationEnvelope": unsupported}
                    )["continuationEnvelope"],
                    "",
                )

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

    def test_exhausted_provider_retries_are_reported_on_terminal_failure(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-provider-retry-exhausted"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id

        def host_event(payload: dict[str, object]) -> None:
            self.runtime._handle_host_event({
                "protocolVersion": "2",
                "event": "agent.event",
                "sessionId": session_id,
                "turnId": turn_id,
                "payload": payload,
            })

        host_event({
            "type": "auto_retry_start",
            "attempt": 6,
            "maxAttempts": 6,
            "delayMs": 64_000,
            "errorMessage": "private upstream diagnostic",
        })
        host_event({
            "type": "agent_end",
            "willRetry": False,
            "messages": [{
                "role": "assistant",
                "stopReason": "error",
                "errorMessage": "fetch failed",
                "content": [],
            }],
        })
        host_event({
            "type": "auto_retry_end",
            "attempt": 6,
            "success": False,
            "finalError": "private upstream diagnostic",
        })
        host_event({"type": "agent_settled"})

        failed = [
            event for event in self.events.replay(session_id)[0]
            if event.event_type == "turn_failed" and event.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertTrue(failed[0].payload["retryExhausted"])
        self.assertEqual(failed[0].payload["providerRetryAttempts"], 6)
        self.assertEqual(failed[0].payload["providerRetryMaxAttempts"], 6)
        self.assertIn("自动重试", failed[0].payload["nextStep"])
        self.assertNotIn(
            "private upstream diagnostic",
            json.dumps(failed[0].payload, ensure_ascii=False),
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
        self.assertIn("工具 read", guarded[-1].payload["nextStep"])
        failed = [
            event for event in events
            if event.event_type == "turn_failed"
            and event.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertIn("受管无进展策略停止", failed[0].payload["error"])
        self.assertEqual(failed[0].payload["reason"], "repeated_failure_signature")
        self.assertEqual(failed[0].payload["toolNames"], ["read"])
        self.assertIn("当前任务上重试", failed[0].payload["nextStep"])
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

    def test_prompt_uses_turn_timeout_instead_of_short_control_timeout(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        client = self.runtime._require_client()
        original_send = client.send
        prompt_timeouts: list[float | None] = []

        def record_send(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
            before_write=None,
        ) -> dict[str, object]:
            if method == "session.prompt":
                prompt_timeouts.append(timeout)
            return original_send(
                method,
                params,
                timeout=timeout,
                before_write=before_write,
            )

        with patch.object(client, "send", side_effect=record_send):
            self.runtime.prompt(session_id, "允许一轮长时间使用工具")

        self.assertEqual(prompt_timeouts, [3_600.0])
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

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

    def test_steer_waits_for_reserved_prompt_to_reach_host(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        client = self.runtime._require_client()
        self.runtime.reserve_prompt_admission(
            session_id,
            client_message_id="initial-race",
        )
        original_write = client._write_record
        prompt_write_entered = threading.Event()
        release_prompt_write = threading.Event()
        results: dict[str, object] = {}
        failures: list[BaseException] = []

        def delayed_write(process, request, *, before_write=None) -> None:
            if request.get("method") == "session.prompt":
                prompt_write_entered.set()
                if not release_prompt_write.wait(timeout=2):
                    raise TimeoutError("test did not release prompt write")
            original_write(
                process,
                request,
                before_write=before_write,
            )

        def run_prompt() -> None:
            try:
                results["prompt"] = self.runtime.prompt(
                    session_id,
                    "hang-without-settled",
                    client_message_id="initial-race",
                )
            except BaseException as exc:
                failures.append(exc)

        def run_steer() -> None:
            try:
                results["steer"] = self.runtime.prompt(
                    session_id,
                    "立即改变当前执行",
                    client_message_id="steer-during-admission",
                    delivery="steer",
                )
            except BaseException as exc:
                failures.append(exc)

        with patch.object(
            client,
            "_write_record",
            side_effect=delayed_write,
        ):
            prompt_thread = threading.Thread(target=run_prompt)
            steer_thread = threading.Thread(target=run_steer)
            prompt_thread.start()
            self.assertTrue(prompt_write_entered.wait(timeout=1))
            steer_thread.start()
            self.assertFalse(
                self.runtime._states[
                    session_id
                ].prompt_dispatch_signal.is_set()
            )
            release_prompt_write.set()
            prompt_thread.join(timeout=2)
            steer_thread.join(timeout=2)

        self.assertFalse(prompt_thread.is_alive())
        self.assertFalse(steer_thread.is_alive())
        self.assertEqual(failures, [])
        prompt = results["prompt"]
        steer = results["steer"]
        self.assertEqual(steer["turnId"], prompt["turnId"])
        self.assertTrue(steer["queued"])
        requests = [
            json.loads(line)
            for line in (
                self.root / "agent" / "host-requests.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        methods = [row["method"] for row in requests]
        self.assertLess(
            methods.index("session.prompt"),
            methods.index("session.steer"),
        )

    def test_host_rejection_preserves_code_and_ends_as_known_failure(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.prompt(
            session_id,
            "hang-without-settled",
            client_message_id="initial-for-rejection",
        )

        with self.assertRaises(PiRuntimeCommandRejected) as rejected:
            self.runtime.prompt(
                session_id,
                "host-reject-session-idle",
                client_message_id="stale-steer",
                delivery="steer",
            )

        self.assertEqual(
            rejected.exception.error_code,
            "PI_RUNTIME_COMMAND_REJECTED",
        )
        self.assertEqual(
            rejected.exception.host_error_code,
            "SESSION_IDLE",
        )

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

    def test_debug_context_does_not_restore_a_nonresident_session(self) -> None:
        session_id = str(self.first["id"])

        response = self.runtime.debug_context(session_id)

        self.assertEqual(
            response,
            {
                "schemaVersion": "rag-ime.pi-debug-context-response.v1",
                "sessionId": session_id,
                "turnId": "",
                "available": False,
                "transient": True,
                "context": None,
                "telemetry": None,
                "reason": "session_not_resident",
            },
        )
        self.assertFalse((self.root / "agent" / "host-requests.jsonl").exists())

    def test_debug_context_timeout_is_bounded_and_does_not_fail_the_session(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.config = replace(
            self.runtime.config,
            provider_environment={"TEST_DEBUG_CONTEXT_HANG": "1"},
        )
        self.runtime.ensure(session_id)
        started = time.monotonic()
        response = self.runtime.debug_context(session_id)

        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(
            response,
            {
                "schemaVersion": "rag-ime.pi-debug-context-response.v1",
                "sessionId": session_id,
                "turnId": "",
                "available": False,
                "transient": True,
                "context": None,
                "telemetry": None,
                "reason": "runtime_unresponsive",
            },
        )

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
                    "error": "Optional settled hook rejected the final message",
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

    def test_agent_settle_failed_retires_stale_session_turn(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-session-settle-failed"
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
                    "error": "Session settlement request returned HTTP 400",
                },
            })
            self.runtime._settle_fallback_probe(session_id, turn_id)

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed"
            and item.turn_id == turn_id
        ]
        self.assertEqual(
            failed[-1].payload["terminalEvent"],
            "idle_control_reconciliation",
        )
        self.assertIn("HTTP 400", failed[-1].payload["error"])
        warnings = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "status_changed"
            and item.payload.get("phase") == "settlement_warning"
        ]
        self.assertIn("HTTP 400", warnings[-1].payload["warning"])
        self.assertEqual(self.store.get(session_id)["status"], "faulted")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_terminal_agent_settle_failed_receipt_fails_the_turn_once(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-terminal-settle-failed"
        with self.runtime._lock:
            state = self.runtime._states[session_id]
            state.turn_id = turn_id
            state.had_tool_activity = True
        self.store.set_status(session_id, "busy")
        envelope = {
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_settle_failed",
                "error": "Agent finalization failed after tool execution",
                "receipt": {
                    "schemaVersion": "pi.agent-settled.v2",
                    "receiptId": "pi-settled:terminal-failure",
                    "disposition": "failed",
                    "stopReason": "settlement_rejected",
                    "pendingOperations": 0,
                    "operations": {"pending": 0},
                    "finalMessage": {
                        "errorMessage": (
                            "Agent finalization failed after tool execution"
                        ),
                    },
                },
            },
        }

        self.runtime._handle_host_event(envelope)
        self.runtime._handle_host_event(envelope)

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed" and item.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertIn("finalization failed", failed[0].payload["error"])
        self.assertTrue(failed[0].payload["hadToolActivity"])
        self.assertEqual(self.store.get(session_id)["status"], "faulted")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_failed_agent_settled_receipt_is_never_completed(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-failed-settled-receipt"
        with self.runtime._lock:
            state = self.runtime._states[session_id]
            state.turn_id = turn_id
            state.last_agent_messages = [{
                "role": "assistant",
                "content": [{"type": "text", "text": "review complete"}],
            }]
        self.store.set_status(session_id, "busy")

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_settled",
                "receipt": {
                    "schemaVersion": "pi.agent-settled.v2",
                    "receiptId": "pi-settled:failed-agent-settled",
                    "disposition": "failed",
                    "stopReason": "settlement_rejected",
                    "pendingOperations": 0,
                    "operations": {"pending": 0},
                    "finalMessage": {
                        "errorMessage": "Session settlement was rejected",
                    },
                },
            },
        })

        events = self.events.replay(session_id)[0]
        failed = [
            item
            for item in events
            if item.event_type == "turn_failed" and item.turn_id == turn_id
        ]
        completed = [
            item
            for item in events
            if item.event_type == "turn_completed" and item.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(completed, [])
        self.assertIn("settlement was rejected", failed[0].payload["error"])
        self.assertEqual(self.store.get(session_id)["status"], "faulted")

    def test_terminal_aborted_agent_settle_failed_receipt_is_turn_failed(self) -> None:
        session_id = str(self.second["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-terminal-settle-aborted"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id
        self.store.set_status(session_id, "busy")

        self.runtime._handle_host_event({
            "protocolVersion": "2",
            "event": "agent.event",
            "sessionId": session_id,
            "turnId": turn_id,
            "payload": {
                "type": "agent_settle_failed",
                "error": "Session settlement was aborted",
                "receipt": {
                    "schemaVersion": "pi.agent-settled.v2",
                    "receiptId": "pi-settled:aborted-settlement",
                    "disposition": "aborted",
                    "stopReason": "cancelled",
                    "pendingOperations": 0,
                    "operations": {"pending": 0},
                },
            },
        })

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed" and item.turn_id == turn_id
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.store.get(session_id)["status"], "faulted")

    def test_abort_timeout_on_responsive_shared_host_is_isolated_to_session(self) -> None:
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
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "abort_timeout_isolated",
        )
        _wait_until(
            lambda: any(
                item.event_type == "status_changed"
                and item.payload.get("cancellationPending") is True
                for item in self.events.replay(session_id)[0]
            ),
            timeout=2.5,
        )
        escalations = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "status_changed"
            and item.payload.get("cancellationPending") is True
        ]
        self.assertEqual(escalations[-1].payload["status"], "idle")
        self.assertEqual(escalations[-1].payload["runtimeStatus"], "ready")
        self.assertFalse(escalations[-1].payload["escalated"])
        runtime_status = self.runtime.runtime_status()
        self.assertEqual(runtime_status["status"], "ready")
        self.assertIsNone(
            runtime_status["runtimeHostKillGate"]["lastKillReceipt"]
        )
        client = self.runtime._require_client()
        self.assertTrue(client.running)

        other_session_id = str(self.second["id"])
        self.runtime.prompt(other_session_id, "other-session-survives")
        _wait_until(lambda: self.store.get(other_session_id)["status"] == "idle")

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
        self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_abort_timeout_kills_host_only_when_health_lane_is_unresponsive(self) -> None:
        session_id = str(self.first["id"])
        accepted = self.runtime.prompt(session_id, "hang-without-settled")
        turn_id = str(accepted["turnId"])
        client = self.runtime._require_client()
        original_send = client.send

        def fail_health(method, params=None, *, timeout=None, before_write=None):
            if method == "health":
                raise PiRuntimeError("Pi Runtime Host command timed out: health")
            return original_send(
                method,
                params,
                timeout=timeout,
                before_write=before_write,
            )

        with patch.object(client, "send", side_effect=fail_health):
            self.runtime.abort(session_id)
            _wait_until(
                lambda: self.runtime.runtime_status()["runtimeHostKillGate"]["lastKillReceipt"]
                is not None,
                timeout=2.5,
            )

        completed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_completed" and item.turn_id == turn_id
        ]
        self.assertEqual(completed[-1].payload["terminalEvent"], "abort_timeout_kill")
        kill_gate = self.runtime.runtime_status()["runtimeHostKillGate"]
        self.assertEqual(kill_gate["lastKillReceipt"]["requestKind"], "cancel_timeout")

    def test_abort_accepts_host_idle_receipt_after_turn_already_settled(self) -> None:
        session_id = str(self.first["id"])
        accepted = self.runtime.prompt(session_id, "host-settled-before-abort-ack")
        turn_id = str(accepted["turnId"])
        client = self.runtime._require_client()
        original_send = client.send

        def idle_abort_receipt(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
        ) -> dict[str, object]:
            if method != "session.abort":
                return original_send(method, params, timeout=timeout)
            return {
                "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
                "sessionId": session_id,
                "turnId": "",
                "cancelledDecisionIds": [],
                "cancelledUIRequestIds": [],
                "lifecycle": {
                    "schemaVersion": "pi.agent-abort-receipt.v1",
                    "scopeId": session_id,
                    "generation": 2,
                    "reason": "user_abort",
                    "cancelledContinuationIds": [],
                    "cancelledOperationIds": [],
                    "failedOperationIds": [],
                    "operations": [],
                    "pendingOperations": [],
                    "drained": True,
                    "idle": True,
                },
            }

        with patch.object(client, "send", side_effect=idle_abort_receipt):
            receipt = self.runtime.abort(session_id)

        self.assertEqual(receipt["turnId"], turn_id)
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        self.assertEqual(self.runtime._states[session_id].turn_id, "")
        completed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_completed" and item.turn_id == turn_id
        ]
        self.assertEqual(completed[-1].payload["status"], "aborted")
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "idle_abort_receipt",
        )
        time.sleep(1.1)
        self.assertIsNone(
            self.runtime.runtime_status()["runtimeHostKillGate"]["lastKillReceipt"]
        )

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

    def test_abort_racing_provider_failure_remains_terminal_aborted(self) -> None:
        """A late Provider error must not overwrite an accepted user Stop."""

        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = f"turn-{session_id}"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id
        self.store.set_status(session_id, "busy")

        self.runtime.abort(session_id)
        self.runtime._turn_failed_once(
            session_id,
            turn_id,
            RuntimeError("fetch failed after user abort"),
        )

        events = self.events.replay(session_id)[0]
        self.assertFalse(
            any(
                item.event_type == "turn_failed" and item.turn_id == turn_id
                for item in events
            )
        )
        completed = [
            item
            for item in events
            if item.event_type == "turn_completed" and item.turn_id == turn_id
        ]
        self.assertEqual(completed[-1].payload["status"], "aborted")
        self.assertEqual(
            completed[-1].payload["terminalEvent"],
            "abort_failure_race",
        )
        self.assertEqual(self.store.get(session_id)["status"], "idle")

    def test_abort_publishes_stopping_state_before_waiting_for_host_ack(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = f"turn-{session_id}"
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = turn_id
        client = self.runtime._client
        self.assertIsNotNone(client)
        assert client is not None
        original_send = client.send

        def observe_send(method, params, *, timeout=None):
            if method == "session.abort":
                statuses = [
                    event.payload.get("status")
                    for event in self.events.replay(session_id)[0]
                    if event.event_type == "status_changed"
                    and event.turn_id == turn_id
                ]
                self.assertEqual(statuses[-1], "aborting")
            return original_send(method, params, timeout=timeout)

        with patch.object(client, "send", side_effect=observe_send):
            self.runtime.abort(session_id)

    def test_abort_during_prompt_admission_reaches_host_before_prompt_ack(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        client = self.runtime._require_client()
        original_send = client.send
        prompt_entered = threading.Event()
        release_prompt = threading.Event()
        abort_delivered = threading.Event()
        abort_settled = threading.Event()
        turn_id = f"turn-admission-{session_id}"

        def delayed_send(
            method: str,
            params: dict[str, object] | None = None,
            *,
            timeout: float | None = None,
            before_write=None,
        ) -> dict[str, object]:
            if method == "session.prompt":
                if before_write is not None:
                    before_write()
                prompt_entered.set()
                self.assertTrue(release_prompt.wait(2.0))
                return {"accepted": True, "turnId": turn_id}
            if method == "session.abort":
                abort_delivered.set()
                self.runtime._handle_host_event({
                    "protocolVersion": "2",
                    "event": "agent.event",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "payload": {"type": "agent_settled"},
                })
                abort_settled.set()
                return {
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
                        "cancelledOperationIds": ["provider"],
                        "failedOperationIds": [],
                        "operations": [],
                        "pendingOperations": [],
                        "drained": True,
                        "idle": True,
                    },
                }
            return original_send(method, params, timeout=timeout)

        prompt_result: dict[str, object] = {}
        prompt_error: list[BaseException] = []

        def run_prompt() -> None:
            try:
                prompt_result.update(
                    self.runtime.prompt(
                        session_id,
                        "stop while admission is pending",
                        client_message_id="client:admission-race",
                    )
                )
            except BaseException as exc:  # pragma: no cover - assertion below
                prompt_error.append(exc)

        with patch.object(client, "send", side_effect=delayed_send):
            prompt_thread = threading.Thread(target=run_prompt)
            prompt_thread.start()
            self.assertTrue(prompt_entered.wait(1.0))

            started = time.monotonic()
            early_receipt = self.runtime.abort(session_id)
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 0.2)
            self.assertTrue(early_receipt["pendingAdmission"])
            self.assertTrue(abort_delivered.wait(1.0))
            self.assertTrue(abort_settled.wait(1.0))
            self.assertEqual(self.store.get(session_id)["status"], "idle")
            release_prompt.set()
            prompt_thread.join(timeout=2.0)

        self.assertFalse(prompt_thread.is_alive())
        self.assertEqual(prompt_error, [])
        self.assertTrue(abort_delivered.is_set())
        self.assertTrue(prompt_result["abortRequested"])
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        completed = [
            event
            for event in self.events.replay(session_id)[0]
            if event.event_type == "turn_completed"
            and event.turn_id == turn_id
        ]
        self.assertEqual(completed[-1].payload["status"], "aborted")

    def test_reserved_prompt_admission_stops_before_host_dispatch(
        self,
    ) -> None:
        session_id = str(self.first["id"])
        client_message_id = "client:application-admission-race"

        reserved = self.runtime.reserve_prompt_admission(
            session_id,
            client_message_id=client_message_id,
        )
        self.assertTrue(reserved["reserved"])
        early_receipt = self.runtime.abort(session_id)
        self.assertTrue(early_receipt["pendingAdmission"])
        self.assertTrue(early_receipt["admissionCancelled"])
        self.assertTrue(early_receipt["lifecycle"]["drained"])
        self.assertTrue(early_receipt["lifecycle"]["idle"])
        self.assertEqual(
            early_receipt["lifecycle"]["pendingOperations"],
            [],
        )
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        admission_statuses = [
            event.payload.get("status")
            for event in self.events.replay(session_id)[0]
            if event.event_type == "status_changed"
        ]
        self.assertEqual(admission_statuses[-1], "aborting")
        with self.assertRaises(PiRuntimeCommandRejected) as cancelled:
            self.runtime.prompt(
                session_id,
                "stop before context preparation finishes",
                client_message_id=client_message_id,
            )
        self.assertEqual(
            cancelled.exception.host_error_code,
            "PROMPT_ADMISSION_CANCELLED",
        )
        self.assertEqual(self.store.get(session_id)["status"], "idle")
        self.assertEqual(self.runtime.runtime_status()["activeSessionIds"], [])

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

    def test_websocket_failure_is_classified_as_transport_interruption(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)

        self.runtime._turn_failed(
            session_id,
            "turn-websocket-error",
            RuntimeError("WebSocket error"),
        )

        failed = [
            item
            for item in self.events.replay(session_id)[0]
            if item.event_type == "turn_failed"
        ][-1]
        self.assertEqual(
            failed.payload["reasonCode"],
            "provider_transport_failure",
        )
        self.assertTrue(failed.payload["retryable"])

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
                failed[-1].payload["error"],
                "Pi Runtime Host exited with code -9",
            )
        finally:
            assert client is not None
            client.stop()

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
