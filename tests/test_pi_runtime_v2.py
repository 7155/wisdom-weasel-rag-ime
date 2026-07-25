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
from rag_ime.pi_runtime_v2 import PiRuntimeHostManager, _pi_tool_history_events


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
            "roomProviderContext": params.get("roomProviderContext"),
            "roomSkillLoad": room_skill_load,
            "isIdle": True,
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
            "activeRoom": None,
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
        if params["message"] == "hang-without-settled":
            continue
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
            "rootId": params["rootId"], "generation": params["generation"],
            "sessionId": session_id, "cancelledContinuationIds": [],
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
                "name": "ime_memory",
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
                session_id=session_id,
                root_id="root:cross-process",
                generation=5,
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
                command_timeout_seconds=1.0,
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
                    "runtimeBindingHash": ("e" if revision < 3 else "9") * 64,
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
            methods[-4:],
            [
                "session.debug.context",
                "session.snapshot",
                "session.snapshot",
                "session.compact",
            ],
        )
        self.assertTrue(compacted["memoryCheckpoint"]["stored"])

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
                "idempotencyKey": "agent-room-agent:room",
            },
            message="同一个 Session 进入 Room",
            lease_token="lease:agent-room-agent",
        )

        cancelled = self.runtime.cancel_room(
            session_id=session_id,
            root_id="root:agent-room-agent",
            generation=1,
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
                "timestamp": 101,
                "content": [{
                    "type": "toolCall",
                    "id": "tool-1",
                    "name": "workspace_read",
                    "arguments": {
                        "path": "/Users/private/project/README.md",
                        "apiKey": "top-secret",
                    },
                }],
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

        self.assertEqual([event["eventType"] for event in events], ["tool_started", "tool_finished"])
        self.assertEqual([event["turnId"] for event in events], ["history:user-1", "history:user-1"])
        self.assertEqual([event["createdAtMs"] for event in events], [501, 902])
        self.assertEqual(events[0]["payload"]["publicResult"]["fileName"], "README.md")
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("top-secret", serialized)
        self.assertNotIn("/Users/private", serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)

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
                "content": [{"type": "toolCall", "id": "call-next", "name": "agent_plan"}],
            },
        })
        send({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "timestamp": 102,
                "content": [{"type": "text", "text": "变更已经交付。"}],
            },
        })

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        completed = [event.payload["message"] for event in events if event.event_type == "message_completed"]
        self.assertEqual(len(completed), 1)
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
        self.assertEqual(opened[0]["params"]["toolManifest"][0]["name"], "ime_memory")
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

    def test_agent_end_is_not_terminal_and_max_comes_from_host_catalog(self) -> None:
        session_id = str(self.first["id"])
        catalog = self.runtime.model_catalog(session_id)
        self.assertEqual(catalog["models"][0]["thinkingLevels"], ["off", "medium", "xhigh", "max"])
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

        with self.assertRaisesRegex(PiRuntimeError, "上一轮"):
            self.runtime.prompt(session_id, "不要覆盖旧回合")

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
