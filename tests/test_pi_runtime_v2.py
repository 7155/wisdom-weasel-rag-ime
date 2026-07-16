from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.pi_runtime import PiRuntimeConfig, PiRuntimeError
from rag_ime.pi_runtime_v2 import PiRuntimeHostManager


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
                         "settledEvents": True, "dynamicTools": True, "managedPlugins": True}})
    elif method == "session.open":
        session = sessions.setdefault(session_id, {
            "sessionId": session_id, "piSessionId": "pi-" + session_id,
            "sessionFile": str(pathlib.Path(os.environ["RAG_IME_PI_SESSION_DIR"]) / (session_id + ".jsonl")),
            "leafId": "", "messages": [], "thinkingLevel": "medium",
            "model": model,
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
        assistant = {"role": "assistant", "timestamp": 101,
                     "content": [{"type": "text", "text": "host reply for " + session_id}]}
        sessions[session_id]["messages"] = [
            {"role": "user", "timestamp": 100, "content": [{"type": "text", "text": params["message"]}]},
            assistant,
        ]
        result(request, {"accepted": True, "turnId": turn_id})
        event(session_id, turn_id, client_message_id, {"type": "agent_start"})
        event(session_id, turn_id, client_message_id, {"type": "message_end", "message": assistant})
        event(session_id, turn_id, client_message_id, {"type": "agent_end", "messages": [assistant]})
        time.sleep(0.15)
        event(session_id, turn_id, client_message_id, {"type": "agent_settled"})
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
        )

    def tearDown(self) -> None:
        self.runtime.stop()
        self.tmp.cleanup()

    def test_one_host_keeps_multiple_sessions_open_and_syncs_dynamic_tools(self) -> None:
        first_id = str(self.first["id"])
        second_id = str(self.second["id"])
        self.runtime.ensure(first_id)
        self.runtime.ensure(second_id)

        status = self.runtime.runtime_status()
        self.assertEqual(status["openSessionIds"], sorted([first_id, second_id]))
        self.assertTrue(status["capabilities"]["multiSession"])
        requests = [json.loads(line) for line in (self.root / "agent" / "host-requests.jsonl").read_text().splitlines()]
        opened = [row for row in requests if row["method"] == "session.open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0]["params"]["toolManifest"][0]["name"], "ime_memory")

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

        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")
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

    def test_v2_reports_branching_as_unavailable_until_host_protocol_supports_it(self) -> None:
        first_id = str(self.first["id"])
        self.assertFalse(self.runtime.runtime_status()["capabilities"]["conversationFork"])
        with self.assertRaisesRegex(PiRuntimeError, "unavailable"):
            self.runtime.fork_candidates(first_id)
        with self.assertRaisesRegex(PiRuntimeError, "unavailable"):
            self.runtime.fork_session(
                first_id,
                str(self.second["id"]),
                entry_id="entry-user-1",
            )

    def test_prompt_rejects_a_second_turn_until_the_active_turn_settles(self) -> None:
        session_id = str(self.first["id"])
        self.runtime.ensure(session_id)
        with self.runtime._lock:
            self.runtime._states[session_id].turn_id = "turn-still-aborting"

        with self.assertRaisesRegex(PiRuntimeError, "上一轮"):
            self.runtime.prompt(session_id, "不要覆盖旧回合")

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
