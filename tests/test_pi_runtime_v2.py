from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

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
                         "transientContext": True,
                         "statelessCompletion": True,
                         "conversationFork": True,
                         "runtimePrimitives": {
                             "continuationEnvelope": "1", "cancelScope": "1",
                             "sessionContinuationQueue": False,
                             "sessionCancelOperationRegistry": False,
                             "sessionCancelOperations": {
                                 "provider": True, "tool": True, "retrySleep": True,
                                 "manualCompaction": False, "autoCompaction": False,
                                 "branchSummary": False, "bashProcess": False,
                                 "continuationTimer": False},
                             "roomTypes": False}}})
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
            "messageQueue": {"steering": [], "followUp": [], "steeringMode": "one-at-a-time",
                             "followUpMode": "one-at-a-time"},
        })
        result(request, {"snapshot": session, "evictedSessionId": None})
    elif method == "session.snapshot":
        result(request, sessions[session_id])
    elif method == "session.commands":
        result(request, {"commands": [{"name": "skill:rag-ime-plugin-creator",
                                        "description": "Create and propose a managed plugin", "source": "skill"}]})
    elif method == "models.list":
        result(request, {"models": [model]})
    elif method == "session.thinking.set":
        sessions[session_id]["thinkingLevel"] = params["level"]
        result(request, {"level": params["level"]})
    elif method == "session.prompt":
        turn_id = "turn-" + session_id
        client_message_id = params.get("clientMessageId", "")
        user_entry_id = "entry-user-" + str(len(sessions[session_id].get("forkItems", [])) + 1)
        assistant_entry_id = "entry-assistant-" + str(len(sessions[session_id].get("forkItems", [])) + 1)
        user_message = {"id": user_entry_id, "role": "user", "timestamp": 100,
                        "content": [{"type": "text", "text": params["message"]}]}
        assistant = {"id": assistant_entry_id, "role": "assistant", "timestamp": 101,
                     "content": [{"type": "text", "text": "host reply for " + session_id}]}
        sessions[session_id]["messages"].extend([user_message, assistant])
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
            thinking_level="off",
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
        self.assertEqual(params["thinkingLevel"], "off")
        self.assertNotIn("sessionId", params)
        self.assertNotIn("images", params)
        self.assertTrue(self.runtime.runtime_status()["capabilities"]["statelessCompletion"])

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
        self.assertFalse(
            status["capabilities"]["runtimePrimitives"][
                "sessionCancelOperationRegistry"
            ]
        )
        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        opened = [row for row in requests if row["method"] == "session.open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0]["params"]["toolManifest"][0]["name"], "ime_memory")
        self.assertEqual(opened[0]["params"]["thinkingLevel"], "max")

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

    def test_v2_exposes_managed_skill_commands_to_the_composer(self) -> None:
        session_id = str(self.first["id"])

        self.assertEqual(
            self.runtime.command_catalog(session_id),
            [
                {
                    "name": "skill:rag-ime-plugin-creator",
                    "invocation": "/skill:rag-ime-plugin-creator",
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
            "<rag-ime-deep-search-context>private evidence</rag-ime-deep-search-context>\n"
            "<rag-ime-user-query>最近做了什么？</rag-ime-user-query>\n"
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

    def test_abort_ack_without_agent_settled_retires_only_the_old_turn(self) -> None:
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
        self.assertEqual(completed[-1].payload["terminalEvent"], "abort_timeout")

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
        with self.runtime._lock:
            self.assertEqual(self.runtime._states[session_id].turn_id, "")

    def test_abort_settled_error_is_terminal_aborted_not_faulted(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        turn_id = "turn-abort-settled-error"
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
        self.assertEqual(self.store.get(session_id)["status"], "active")

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
