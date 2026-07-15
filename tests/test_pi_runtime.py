from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.deepseek_config import DeepSeekConfig
from rag_ime.pi_provider_config import PiProviderConfigError, load_pi_provider_config
from rag_ime.pi_runtime import PiRuntimeConfig, PiRuntimeError, PiRuntimeManager, _pi_message_payload


FAKE_PI = r'''#!/usr/bin/env python3
import json
import pathlib
import sys
import time

args = sys.argv[1:]
session_dir = pathlib.Path(args[args.index("--session-dir") + 1])
session_dir.mkdir(parents=True, exist_ok=True)
session_file = session_dir / "fake-session.jsonl"
session_file.touch()
entries = []
available_models = [
    {"provider": "deepseek", "id": "deepseek-v4", "name": "DeepSeek V4", "api": "openai-completions",
     "reasoning": False, "input": ["text"], "contextWindow": 128000, "maxTokens": 8192,
     "baseUrl": "https://example.invalid", "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}},
    {"provider": "openrouter", "id": "anthropic/claude-sonnet", "name": "Claude Sonnet", "api": "openai-completions",
     "reasoning": True, "input": ["text", "image"], "contextWindow": 200000, "maxTokens": 16384,
     "thinkingLevelMap": {"off": "none", "xhigh": "xhigh"},
     "baseUrl": "https://example.invalid", "headers": {"Authorization": "secret"},
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}},
]
current_model = available_models[0]
current_thinking = "off"

def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

for line in sys.stdin:
    command = json.loads(line)
    request_id = command.get("id")
    kind = command.get("type")
    if kind == "get_state":
        emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": {
            "sessionId": "pi-fake-1", "sessionFile": str(session_file), "messageCount": 0,
            "thinkingLevel": current_thinking, "isStreaming": False, "isCompacting": False,
            "steeringMode": "all", "followUpMode": "one-at-a-time",
            "autoCompactionEnabled": True, "pendingMessageCount": 0, "model": current_model
        }})
    elif kind == "get_available_models":
        emit({"id": request_id, "type": "response", "command": kind, "success": True,
              "data": {"models": available_models}})
    elif kind == "set_model":
        selected = next((item for item in available_models
                         if item["provider"] == command.get("provider") and item["id"] == command.get("modelId")), None)
        if selected is None:
            emit({"id": request_id, "type": "response", "command": kind, "success": False, "error": "not found"})
        else:
            current_model = selected
            emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": selected})
    elif kind == "set_thinking_level":
        current_thinking = str(command.get("level") or "off")
        emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": None})
    elif kind == "prompt":
        entry = {
            "type": "message",
            "id": "entry-user-" + str(len(entries) + 1),
            "parentId": entries[-1]["id"] if entries else None,
            "timestamp": "2026-07-13T00:00:00.000Z",
            "message": {"role": "user", "content": command.get("message", ""), "timestamp": 100},
        }
        entries.append(entry)
        emit({"id": request_id, "type": "response", "command": kind, "success": True,
              "data": {"imageCount": len(command.get("images") or [])}})
        emit({"type": "agent_start"})
        if str(command.get("message", "")) == "provider-error":
            assistant = {
                "role": "assistant",
                "timestamp": 103,
                "content": [],
                "stopReason": "error",
                "errorMessage": "400 upstream request failed",
            }
            emit({"type": "message_end", "message": assistant})
            emit({"type": "agent_end", "messages": [assistant]})
            continue
        if str(command.get("message", "")) == "tool-loop":
            first = {"role": "assistant", "timestamp": 105, "content": [
                {"type": "text", "text": "我先检查相关记忆。"},
                {"type": "toolCall", "id": "call-1", "name": "ime_memory", "arguments": {"op": "recent"}}
            ]}
            emit({"type": "message_update", "message": {"role": "assistant", "timestamp": 105},
                  "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "我先检查相关记忆。"}})
            emit({"type": "message_end", "message": first})
            emit({"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "ime_memory",
                  "args": {"op": "recent"}})
            emit({"type": "message_end", "message": {"role": "toolResult", "timestamp": 106,
                  "content": [{"type": "text", "text": "{\"summary\":\"raw tool json\"}"}]}})
            emit({"type": "tool_execution_end", "toolCallId": "call-1", "toolName": "ime_memory",
                  "args": {"op": "recent"}, "result": {"summary": "读取 2 条近期记录"}, "isError": False})
            final = {"role": "assistant", "timestamp": 107, "content": [
                {"type": "text", "text": "## 结论\n\n找到了两条相关记录。"}
            ]}
            emit({"type": "message_update", "message": {"role": "assistant", "timestamp": 107},
                  "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "## 结论\n\n"}})
            emit({"type": "message_update", "message": {"role": "assistant", "timestamp": 107},
                  "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "找到了两条相关记录。"}})
            emit({"type": "message_end", "message": final})
            emit({"type": "agent_end", "messages": [first, final]})
            continue
        if str(command.get("message", "")).startswith("approval:"):
            emit({
                "type": "extension_ui_request",
                "id": "ui-confirm-1",
                "method": "confirm",
                "title": "RAG-IME-APPROVAL:" + str(command.get("message")),
                "message": "Review in the native control center",
                "timeout": 60000,
            })
            continue
        emit({"type": "message_update", "message": {"role": "assistant", "timestamp": 101},
              "assistantMessageEvent": {"type": "thinking_delta", "contentIndex": 0, "delta": "private chain of thought"}})
        emit({"type": "message_update", "message": {"role": "assistant", "timestamp": 101},
              "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "已找到"}})
        assistant = {"role": "assistant", "timestamp": 101, "content": [
            {"type": "thinking", "thinking": "private chain of thought"},
            {"type": "text", "text": "已找到两条记录。"}
        ]}
        emit({"type": "message_end", "message": assistant})
        emit({"type": "agent_end", "messages": [assistant]})
    elif kind == "extension_ui_response":
        assistant = {"role": "assistant", "timestamp": 102, "content": [
            {"type": "text", "text": "审批结果已收到。"}
        ]}
        emit({"type": "message_end", "message": assistant})
        emit({"type": "agent_end", "messages": [assistant]})
    elif kind == "get_entries":
        selected = entries
        if command.get("since"):
            index = next((i for i, item in enumerate(entries) if item["id"] == command.get("since")), -1)
            selected = entries[index + 1:] if index >= 0 else entries
        emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": {
            "entries": selected, "leafId": entries[-1]["id"] if entries else None
        }})
    elif kind == "get_messages":
        emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": {"messages": [
            {"role": "user", "timestamp": 100, "content": [{"type": "text", "text": "今天做了什么"}]},
            {"role": "assistant", "timestamp": 101, "content": [{"type": "text", "text": "已找到两条记录。"}]}
        ]}})
    elif kind == "compact":
        emit({"id": request_id, "type": "response", "command": kind, "success": True, "data": {"compacted": True}})
    elif kind == "abort":
        emit({"id": request_id, "type": "response", "command": kind, "success": True})
    else:
        emit({"id": request_id, "type": "response", "command": kind, "success": False, "error": "unsupported"})
'''


class PiRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-pi-runtime-")
        self.root = Path(self.tmp.name)
        self.fake_pi = self.root / "fake-pi"
        self.fake_pi.write_text(FAKE_PI, encoding="utf-8")
        self.fake_pi.chmod(0o755)
        self.store = AgentSessionStore(self.root / "rag-ime.sqlite")
        self.store.initialize()
        self.session = self.store.create(title="输入助手", created_at_ms=100)
        self.events = AgentEventHub(
            sequence_loader=self.store.max_event_sequence,
            event_recorder=self._record_event,
        )
        self.config = PiRuntimeConfig(
            enabled=True,
            executable=self.fake_pi,
            agent_dir=self.root / "agent-config",
            session_dir=self.root / "sessions",
            logs_dir=self.root / "logs",
            idle_timeout_seconds=0,
            command_timeout_seconds=3,
            pi_version="test",
        )
        self.runtime = PiRuntimeManager(config=self.config, sessions=self.store, events=self.events)

    def tearDown(self) -> None:
        self.runtime.stop()
        self.tmp.cleanup()

    def test_launch_is_isolated_and_uses_no_tools_before_gateway_exists(self) -> None:
        command = self.config.launch_command(session=self.session)
        self.assertIn("--mode", command)
        self.assertIn("rpc", command)
        self.assertIn("--no-context-files", command)
        self.assertIn("--no-approve", command)
        self.assertIn("--no-extensions", command)
        self.assertIn("--no-skills", command)
        self.assertIn("--no-prompt-templates", command)
        self.assertIn("--no-themes", command)
        self.assertIn("--offline", command)
        self.assertIn("--no-tools", command)
        self.assertNotIn("bash", command)
        self.assertIn("--system-prompt", command)
        prompt = command[command.index("--system-prompt") + 1]
        self.assertIn("你是“智鼬”", prompt)
        self.assertIn("词表相关操作必须经过预览", prompt)

        environment = self.config.child_environment()
        self.assertEqual(environment["PI_CODING_AGENT_DIR"], str(self.root / "agent-config"))
        self.assertNotIn("RAG_IME_DEEPSEEK_API_KEY", environment)

    def test_environment_model_slot_is_scoped_to_the_pi_child(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "RAG_IME_APP_SUPPORT_DIR": str(self.root / "support"),
                "RAG_IME_PI_EXECUTABLE": str(self.fake_pi),
                "RAG_IME_PI_ENABLED": "1",
            },
            clear=True,
        ), mock.patch(
            "rag_ime.pi_runtime.load_deepseek_config",
            return_value=DeepSeekConfig(
                api_base_url="https://gateway.example/v1",
                api_key="test-secret",
                model="deepseek-v4-flash",
            ),
        ):
            config = PiRuntimeConfig.from_environment()

        self.assertTrue(config.model_configured)
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertNotIn("test-secret", repr(config))
        child = config.child_environment()
        self.assertEqual(child["DEEPSEEK_API_KEY"], "test-secret")
        self.assertNotIn("RAG_IME_DEEPSEEK_API_KEY", child)
        config.prepare_agent_config()
        models_path = config.agent_dir / "models.json"
        models_text = models_path.read_text(encoding="utf-8")
        self.assertIn("https://gateway.example/v1", models_text)
        self.assertIn("$DEEPSEEK_API_KEY", models_text)
        self.assertNotIn("test-secret", models_text)
        self.assertEqual(models_path.stat().st_mode & 0o777, 0o600)

    def test_opencode_provider_file_is_translated_without_persisting_secrets(self) -> None:
        provider_path = self.root / "pikey.md"
        provider_path.write_text(
            json.dumps(
                {
                    "provider": {
                        "openai": {
                            "options": {
                                "baseURL": "https://gpt.example/v1",
                                "apiKey": "gpt-test-secret",
                            },
                            "models": {
                                "gpt-5.4": {
                                    "name": "GPT-5.4",
                                    "limit": {"context": 1_050_000, "output": 128_000},
                                    "variants": {"high": {}, "max": {}},
                                    "modalities": {"image": True},
                                }
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(
            os.environ,
            {
                "RAG_IME_APP_SUPPORT_DIR": str(self.root / "support"),
                "RAG_IME_PI_EXECUTABLE": str(self.fake_pi),
                "RAG_IME_PI_ENABLED": "1",
                "RAG_IME_PI_PROVIDER_CONFIG": str(provider_path),
                "RAG_IME_PI_PROVIDER": "gpt",
                "RAG_IME_PI_MODEL": "gpt-5.4",
            },
            clear=True,
        ), mock.patch(
            "rag_ime.pi_runtime.load_deepseek_config",
            return_value=DeepSeekConfig(
                api_base_url="https://deepseek.example/v1",
                api_key="deepseek-test-secret",
                model="deepseek-v4-flash",
            ),
        ):
            config = PiRuntimeConfig.from_environment()

        self.assertTrue(config.model_configured)
        self.assertEqual(config.provider, "gpt")
        self.assertEqual(config.model, "gpt-5.4")
        self.assertEqual(config.child_environment()["RAG_IME_PI_GPT_API_KEY"], "gpt-test-secret")
        self.assertNotIn("gpt-test-secret", repr(config))
        config.prepare_agent_config()
        models_text = (config.agent_dir / "models.json").read_text(encoding="utf-8")
        self.assertIn('"gpt"', models_text)
        self.assertIn('"deepseek"', models_text)
        self.assertIn("$RAG_IME_PI_GPT_API_KEY", models_text)
        self.assertIn('"supportsDeveloperRole": false', models_text)
        self.assertIn('"supportsReasoningEffort": false', models_text)
        self.assertIn('"thinkingLevelMap"', models_text)
        self.assertIn('"image"', models_text)
        self.assertNotIn("gpt-test-secret", models_text)
        self.assertNotIn("deepseek-test-secret", models_text)
        command = config.launch_command(session=self.session)
        self.assertEqual(command[command.index("--provider") + 1], "gpt")
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.4")

    def test_imported_provider_omits_product_personas_and_uses_declared_capabilities(self) -> None:
        provider_path = self.root / "provider-capabilities.json"
        provider_path.write_text(
            json.dumps(
                {
                    "provider": {
                        "gpt": {
                            "options": {
                                "baseURL": "https://gpt.example/v1",
                                "apiKey": "test-only",
                            },
                            "models": {
                                "gpt-5.2": {"name": "GPT-5.2"},
                                "gpt-5.4": {
                                    "name": "GPT-5.4",
                                    "variants": {"low": {}, "max": {}},
                                    "input": ["text", "image"],
                                },
                                "gpt-5.6": {"name": "GPT-5.6"},
                                "gpt-5.6-luna": {"name": "GPT-5.6 Luna"},
                                "gpt-5.6-terra": {"name": "GPT-5.6 Terra"},
                                "gpt-5.6-sol": {"name": "GPT-5.6 Sol"},
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        bundle = load_pi_provider_config(provider_path)
        provider = bundle.providers["gpt"]
        models = {str(model["id"]): model for model in provider["models"]}

        self.assertEqual(set(models), {"gpt-5.2", "gpt-5.4"})
        self.assertFalse(models["gpt-5.2"]["reasoning"])
        self.assertEqual(models["gpt-5.2"]["input"], ["text"])
        self.assertTrue(models["gpt-5.4"]["reasoning"])
        self.assertEqual(models["gpt-5.4"]["thinkingLevelMap"], {"xhigh": "max"})
        self.assertEqual(models["gpt-5.4"]["input"], ["text", "image"])
        self.assertTrue(provider["compat"]["supportsReasoningEffort"])

    def test_stale_custom_session_model_falls_back_inside_the_same_provider(self) -> None:
        config = PiRuntimeConfig(
            enabled=True,
            executable=self.fake_pi,
            agent_dir=self.root / "fallback-config",
            session_dir=self.root / "fallback-sessions",
            logs_dir=self.root / "fallback-logs",
            provider="gpt",
            model="gpt-5.2",
            model_providers={
                "gpt": {
                    "models": [
                        {"id": "gpt-5.2", "name": "GPT-5.2", "reasoning": False}
                    ]
                }
            },
        )
        stale = {**self.session, "modelProfile": "gpt/gpt-5.6"}

        command = config.launch_command(session=stale)

        self.assertEqual(command[command.index("--provider") + 1], "gpt")
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.2")

    def test_imported_provider_rejects_credentials_and_query_parameters_in_url(self) -> None:
        for endpoint in (
            "https://user:secret@gpt.example/v1",
            "https://gpt.example/v1?token=secret",
            "https://gpt.example/v1#secret",
        ):
            with self.subTest(endpoint=endpoint):
                provider_path = self.root / f"provider-{len(endpoint)}.json"
                provider_path.write_text(
                    json.dumps(
                        {
                            "provider": {
                                "openai": {
                                    "options": {"baseURL": endpoint, "apiKey": "test-only"},
                                    "models": {"gpt-test": {"name": "GPT Test"}},
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(PiProviderConfigError, "不能包含凭据"):
                    load_pi_provider_config(provider_path)

    def test_missing_model_credential_is_a_distinct_runtime_state(self) -> None:
        config = PiRuntimeConfig(
            enabled=True,
            executable=self.fake_pi,
            agent_dir=self.root / "missing-model-config",
            session_dir=self.root / "missing-model-sessions",
            logs_dir=self.root / "missing-model-logs",
            model_configured=False,
            model_configuration_error="尚未配置对话模型",
        )
        runtime = PiRuntimeManager(config=config, sessions=self.store, events=self.events)

        status = runtime.runtime_status()
        self.assertEqual(status["status"], "needs_configuration")
        self.assertFalse(status["capabilities"]["modelConfigured"])
        with self.assertRaisesRegex(PiRuntimeError, "尚未配置对话模型"):
            runtime.ensure(str(self.session["id"]))

    def test_audited_extension_receives_only_scoped_gateway_capability(self) -> None:
        extension = self.root / "rag-ime-control.ts"
        extension.write_text("export default function () {}\n", encoding="utf-8")
        config = PiRuntimeConfig(
            enabled=True,
            executable=self.fake_pi,
            agent_dir=self.root / "tool-config",
            session_dir=self.root / "tool-sessions",
            logs_dir=self.root / "tool-logs",
            extension_path=extension,
            tools=("ime_memory",),
            tool_gateway_token="scoped-test-token",
        )
        command = config.launch_command(session=self.session)
        environment = config.child_environment(session=self.session)

        self.assertIn("--no-builtin-tools", command)
        self.assertIn(str(extension.resolve()), command)
        self.assertIn("ime_memory", command)
        self.assertNotIn("--no-tools", command)
        self.assertEqual(environment["RAG_IME_AGENT_TOOL_TOKEN"], "scoped-test-token")
        self.assertEqual(environment["RAG_IME_AGENT_SESSION_ID"], self.session["id"])
        self.assertEqual(environment["RAG_IME_AGENT_SESSION_MODE"], "assistant")
        self.assertNotIn("RAG_IME_MANAGEMENT_TOKEN", environment)

    def test_coordinator_tools_are_selected_only_for_explicit_coordinator_session(self) -> None:
        extension = self.root / "rag-ime-coordinator.ts"
        extension.write_text("export default function () {}\n", encoding="utf-8")
        config = PiRuntimeConfig(
            enabled=True,
            executable=self.fake_pi,
            agent_dir=self.root / "coordinator-config",
            session_dir=self.root / "coordinator-sessions",
            logs_dir=self.root / "coordinator-logs",
            extension_path=extension,
            tools=("ime_memory", "workspace_list", "workspace_read", "workspace_shell"),
        )
        coordinator = self.store.create(
            title="coordinator",
            mode="coordinator",
            workspace_roots=[str(self.root)],
        )
        assistant_command = config.launch_command(session=self.session)
        coordinator_command = config.launch_command(session=coordinator)
        assistant_tools = assistant_command[assistant_command.index("--tools") + 1]
        coordinator_tools = coordinator_command[coordinator_command.index("--tools") + 1]

        self.assertEqual(assistant_tools, "ime_memory")
        self.assertIn("workspace_shell", coordinator_tools)
        environment = config.child_environment(session=coordinator)
        self.assertEqual(environment["RAG_IME_AGENT_SESSION_MODE"], "coordinator")

    def test_runtime_prompt_maps_typed_events_without_raw_thinking(self) -> None:
        session_id = str(self.session["id"])
        ensured = self.runtime.ensure(session_id)
        self.assertEqual(ensured["state"]["sessionId"], "pi-fake-1")
        self.assertEqual(self.store.get(session_id)["modelProfile"], "deepseek/deepseek-v4")
        self.assertEqual(self.runtime.runtime_status()["status"], "ready")

        accepted = self.runtime.prompt(session_id, "今天做了什么")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["piEntryId"], "entry-user-1")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

    def test_runtime_prompt_forwards_rpc_image_content(self) -> None:
        session_id = str(self.session["id"])
        accepted = self.runtime.prompt(
            session_id,
            "看看这张图",
            images=[{"type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"}],
        )

        self.assertEqual(accepted["response"]["data"]["imageCount"], 1)
        self.assertEqual(accepted["piEntryId"], "entry-user-1")

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        event_types = [event.event_type for event in events]
        self.assertIn("text_delta", event_types)
        self.assertIn("message_completed", event_types)
        self.assertIn("turn_completed", event_types)
        serialized = json.dumps([event.to_payload() for event in events], ensure_ascii=False)
        self.assertNotIn("private chain of thought", serialized)

        completed = next(event for event in events if event.event_type == "message_completed")
        message = completed.payload["message"]
        self.assertEqual(message["blocks"][0]["type"], "text")
        self.assertEqual(message["blocks"][0]["data"]["text"], "已找到两条记录。")

    def test_agent_loop_is_one_public_assistant_row_with_expandable_tool_events(self) -> None:
        session_id = str(self.session["id"])
        self.runtime.prompt(session_id, "tool-loop")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        completed = [event for event in events if event.event_type == "message_completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].payload["message"]["id"], f"{completed[0].turn_id}:assistant")
        self.assertEqual(
            completed[0].payload["message"]["blocks"][0]["data"]["text"],
            "## 结论\n\n找到了两条相关记录。",
        )
        deltas = [event.payload for event in events if event.event_type == "text_delta"]
        self.assertTrue(deltas[0]["replaceBlock"])
        self.assertTrue(deltas[1]["replaceBlock"])
        self.assertFalse(deltas[2]["replaceBlock"])
        self.assertEqual(len({payload["messageId"] for payload in deltas}), 1)
        self.assertIn("tool_started", [event.event_type for event in events])
        self.assertIn("tool_finished", [event.event_type for event in events])
        self.assertNotIn("raw tool json", json.dumps([event.to_payload() for event in events]))

    def test_messages_compaction_abort_and_stop_are_session_bound(self) -> None:
        session_id = str(self.session["id"])
        messages = self.runtime.messages(session_id)
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["id"], "pi:message:user:100")
        self.assertEqual(messages[1]["id"], "pi:message:assistant:101")
        self.assertEqual(self.runtime.compact(session_id), {"compacted": True})
        self.runtime.abort(session_id)

        other = self.store.create(title="另一个会话", created_at_ms=200)
        with self.assertRaisesRegex(PiRuntimeError, "not active"):
            self.runtime.abort(str(other["id"]))

        self.runtime.stop()
        self.assertEqual(self.runtime.runtime_status()["status"], "stopped")

    def test_pi_owns_model_catalog_and_session_selection(self) -> None:
        session_id = str(self.session["id"])

        catalog = self.runtime.model_catalog(session_id)
        self.assertEqual(catalog["selected"]["id"], "deepseek-v4")
        self.assertEqual(catalog["thinkingLevel"], "off")
        self.assertEqual(len(catalog["models"]), 2)
        image_model = catalog["models"][1]
        self.assertTrue(image_model["supportsImages"])
        self.assertEqual(image_model["thinkingLevels"], ["off", "minimal", "low", "medium", "high", "xhigh"])
        self.assertNotIn("headers", image_model)
        self.assertNotIn("baseUrl", image_model)

        changed = self.runtime.set_model(
            session_id,
            provider="openrouter",
            model_id="anthropic/claude-sonnet",
        )
        self.assertEqual(changed["selected"]["name"], "Claude Sonnet")
        self.assertEqual(changed["session"]["modelProfile"], "openrouter/anthropic/claude-sonnet")
        command = self.config.launch_command(session=changed["session"])
        self.assertEqual(command[command.index("--provider") + 1], "openrouter")
        self.assertEqual(command[command.index("--model") + 1], "anthropic/claude-sonnet")

        thinking = self.runtime.set_thinking_level(session_id, level="xhigh")
        self.assertEqual(thinking["thinkingLevel"], "xhigh")
        self.assertEqual(self.runtime.model_catalog(session_id)["thinkingLevel"], "xhigh")

        reset = self.runtime.set_model(session_id, provider="deepseek", model_id="deepseek-v4")
        self.assertEqual(reset["selected"]["id"], "deepseek-v4")
        self.assertEqual(self.runtime.model_catalog(session_id)["thinkingLevel"], "off")
        with self.assertRaisesRegex(ValueError, "不支持这个思考强度"):
            self.runtime.set_thinking_level(session_id, level="high")
        with self.assertRaisesRegex(PiRuntimeError, "目录中没有这个模型"):
            self.runtime.set_model(session_id, provider="gpt", model_id="gpt-5.6")

    def test_provider_error_becomes_failed_message_and_failed_turn(self) -> None:
        session_id = str(self.session["id"])
        self.runtime.prompt(session_id, "provider-error")
        _wait_until(lambda: self.store.get(session_id)["status"] == "idle")

        events, gap = self.events.replay(session_id)
        self.assertFalse(gap)
        completed = next(event for event in events if event.event_type == "message_completed")
        message = completed.payload["message"]
        self.assertEqual(message["status"], "failed")
        self.assertEqual(message["blocks"][-1]["type"], "error")
        self.assertIn("400 upstream", message["blocks"][-1]["data"]["message"])
        self.assertIn("turn_failed", [event.event_type for event in events])
        self.assertNotIn("turn_completed", [event.event_type for event in events])

    def test_deep_search_transport_prompt_is_not_exposed_as_user_message(self) -> None:
        message = _pi_message_payload(
            {
                "role": "user",
                "timestamp": 104,
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<rag-ime-deep-search-context>internal</rag-ime-deep-search-context>\n"
                            "<rag-ime-user-query>最近做了什么？</rag-ime-user-query>\n"
                            "本地时间：2026-07-14"
                        ),
                    }
                ],
            },
            session_id=str(self.session["id"]),
            turn_id="turn:deep",
        ).to_payload()

        self.assertEqual(message["blocks"][0]["data"]["text"], "最近做了什么？")

    def test_native_approval_response_unblocks_pi_extension_ui(self) -> None:
        session_id = str(self.session["id"])
        approval = self.store.create_approval(
            session_id=session_id,
            tool_name="ime_runtime",
            operation="restart",
            payload_sha256="a" * 64,
            preview={"summary": "重启运行组件"},
            risk_level="R2",
        )
        approval_id = str(approval["approvalId"])

        self.runtime.prompt(session_id, approval_id)
        _wait_until(lambda: self.runtime.has_pending_approval(session_id, approval_id))
        events, _ = self.events.replay(session_id)
        required = next(event for event in events if event.event_type == "approval_required")
        self.assertEqual(required.payload["approvalId"], approval_id)
        self.assertEqual(required.payload["payloadSha256"], "a" * 64)

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
        resolved = next(event for event in events if event.event_type == "approval_resolved")
        self.assertEqual(resolved.payload["state"], "external_pending")
        self.assertIn("turn_completed", [event.event_type for event in events])

    def test_disabled_and_uninstalled_states_fail_closed(self) -> None:
        disabled = PiRuntimeManager(
            config=PiRuntimeConfig(
                enabled=False,
                executable=self.fake_pi,
                agent_dir=self.root / "disabled-config",
                session_dir=self.root / "disabled-sessions",
                logs_dir=self.root / "disabled-logs",
            ),
            sessions=self.store,
            events=self.events,
        )
        with self.assertRaisesRegex(PiRuntimeError, "disabled"):
            disabled.ensure(str(self.session["id"]))

        missing = PiRuntimeConfig(
            enabled=True,
            executable=self.root / "missing-pi",
            agent_dir=self.root / "missing-config",
            session_dir=self.root / "missing-sessions",
            logs_dir=self.root / "missing-logs",
        )
        self.assertEqual(
            PiRuntimeManager(config=missing, sessions=self.store, events=self.events).runtime_status()["status"],
            "not_installed",
        )

    def test_session_path_outside_managed_directory_is_rejected(self) -> None:
        unsafe = {**self.session, "sessionFile": str(self.root / "outside.jsonl")}
        (self.root / "outside.jsonl").touch()
        with self.assertRaisesRegex(PiRuntimeError, "outside the managed session directory"):
            self.config.launch_command(session=unsafe)

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
    raise AssertionError("condition did not become true")


if __name__ == "__main__":
    unittest.main()
