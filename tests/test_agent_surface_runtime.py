from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_surface_runtime import (
    AgentSurfaceRuntime,
    PiSurfaceCompletionProvider,
    VOICE_REFINEMENT_TOOL_PROFILE,
    _validated_voice_refinement,
)
from rag_ime.deepseek_completion import DeepSeekCompletionRequest


class _SurfaceRuntimeStub:
    def __init__(self, events: AgentEventHub) -> None:
        self.events = events
        self.prompt_session_ids: list[str] = []
        self.images: list[list[dict[str, str]]] = []
        self.messages: list[str] = []
        self.thinking_levels: list[tuple[str, str]] = []
        self.completions: list[dict[str, object]] = []
        self.cancelled_completion_ids: list[str] = []
        self.selected = {
            "provider": "test",
            "id": "text-only",
            "supportsImages": False,
        }
        self.models = [
            dict(self.selected),
            {
                "provider": "test",
                "id": "gpt-5.6-luna",
                "supportsImages": True,
            },
        ]

    def prompt(self, session_id, message, *, images=None, client_message_id=""):
        del client_message_id
        turn_id = f"turn-{len(self.prompt_session_ids) + 1}"
        self.prompt_session_ids.append(session_id)
        self.messages.append(message)
        self.images.append([dict(item) for item in images or []])
        answer = (
            "这个项目在哪里注入这些工具？如果使用自定义配置，就要把工具和功能都注入进去，对吧？"
            if "第三遍文字校对器" in message
            else "继续完成这段文字。"
        )
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "role": "assistant",
                    "blocks": [{"type": "text", "data": {"text": answer}}],
                }
            },
            turn_id=turn_id,
        )
        self.events.publish(session_id, "turn_completed", {}, turn_id=turn_id)
        return {"turnId": turn_id}

    def complete_once(
        self,
        *,
        request_id,
        provider,
        model_id,
        thinking_level,
        message,
        on_text_delta=None,
        timeout_seconds=120.0,
    ):
        call = {
            "requestId": request_id,
            "provider": provider,
            "modelId": model_id,
            "thinkingLevel": thinking_level,
            "message": message,
            "timeoutSeconds": timeout_seconds,
        }
        self.completions.append(call)
        if on_text_delta is not None:
            on_text_delta("继续完成")
            on_text_delta("这段文字。")
        return {
            "text": "继续完成这段文字。",
            "firstTokenMs": 3800,
            "elapsedMs": 4200,
            "usage": {"totalTokens": 24},
        }

    def cancel_completion(self, request_id):
        self.cancelled_completion_ids.append(request_id)
        return True

    def model_catalog(self, _session_id):
        return {"selected": dict(self.selected), "models": [dict(item) for item in self.models]}

    def set_model(self, _session_id, *, provider, model_id):
        self.selected = next(
            dict(item)
            for item in self.models
            if item["provider"] == provider and item["id"] == model_id
        )
        return {"selected": dict(self.selected)}

    def set_thinking_level(self, session_id, *, level):
        self.thinking_levels.append((session_id, level))
        return {"thinkingLevel": level}

    def abort(self, _session_id):
        return None


class AgentSurfaceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rag-ime-surface-")
        self.sessions = AgentSessionStore(Path(self.temp.name) / "surface.sqlite")
        self.sessions.initialize()
        self.events = AgentEventHub()
        self.runtime = _SurfaceRuntimeStub(self.events)
        self.agent = SimpleNamespace(
            sessions=self.sessions,
            events=self.events,
            runtime=self.runtime,
            runtime_factory=SimpleNamespace(default_model_profile="test/text-only"),
        )
        self.settings = {
            "activeRag": {
                "quickModel": "deepseek/deepseek-v4-flash",
                "quickThinkingLevel": "off",
                "visualModel": "gpt/gpt-5.6-luna",
                "visualThinkingLevel": "low",
            }
        }
        self.surface = AgentSurfaceRuntime(
            self.agent,
            settings_provider=lambda: self.settings,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_provider_uses_independent_stateless_flash_completions(self) -> None:
        provider = PiSurfaceCompletionProvider(local_runtime=self.surface)
        request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context="请继续",
            surface_request_id="surface-request-1",
            front_app_bundle_id="com.example.Editor",
        )

        first = list(provider.stream_candidates(request))
        second = list(provider.stream_candidates(request))

        self.assertEqual(first[0].text, "继续完成这段文字。")
        self.assertEqual(second[0].source_lane, "pi_surface")
        self.assertFalse(first[0].metadata["surfaceSession"])
        self.assertTrue(first[0].metadata["statelessCompletion"])
        self.assertEqual(first[0].metadata["elapsedMs"], 4200)
        self.assertEqual(len(self.runtime.completions), 2)
        self.assertEqual(self.runtime.completions[0]["provider"], "deepseek")
        self.assertEqual(self.runtime.completions[0]["modelId"], "deepseek-v4-flash")
        self.assertEqual(self.runtime.completions[0]["thinkingLevel"], "off")
        self.assertIn("不调用工具", str(self.runtime.completions[0]["message"]))
        self.assertIn("可按内容需要使用简洁 Markdown", str(self.runtime.completions[0]["message"]))
        self.assertEqual(self.runtime.prompt_session_ids, [])
        self.assertEqual(self.sessions.list(include_internal=True), [])
        self.assertEqual(self.sessions.list(), [])

    def test_provider_forwards_ax_context_packet_and_evidence_without_a_screenshot(self) -> None:
        provider = PiSurfaceCompletionProvider(local_runtime=self.surface)
        partials: list[str] = []
        request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context="根据界面继续",
            selected_text="补全这段话",
            evidence_pack=({"sourceType": "memory", "text": "用户偏好简洁表达"},),
            context_packet={
                "schemaVersion": "rag-ime.active-rag-context-packet.v1",
                "windowContext": {
                    "schemaVersion": "rag-ime.window-context.v1",
                    "captureMode": "accessibility_semantics",
                    "snapshotId": "axsnap-1",
                    "nodeCount": 2,
                    "semanticText": "[ax_1] AXTextArea focused value=根据界面继续",
                },
            },
            surface_request_id="surface-request-semantic",
            front_app_bundle_id="com.example.Editor",
        )

        result = list(provider.stream_candidates(request, on_text_delta=partials.append))

        self.assertTrue(result[0].metadata["semanticContextUsed"])
        self.assertEqual(result[0].metadata["firstTokenMs"], 3800)
        self.assertEqual(partials, ["继续完成", "继续完成这段文字。"])
        call = self.runtime.completions[0]
        self.assertEqual(call["provider"], "deepseek")
        self.assertEqual(call["modelId"], "deepseek-v4-flash")
        request_data = json.loads(str(call["message"]).split("\n", 1)[1])
        self.assertEqual(request_data["currentRequest"], "根据界面继续")
        self.assertEqual(request_data["selectedText"], "补全这段话")
        self.assertEqual(request_data["windowContext"]["snapshotId"], "axsnap-1")
        self.assertEqual(request_data["contextPacket"]["windowContext"]["nodeCount"], 2)
        self.assertEqual(request_data["evidencePack"][0]["sourceType"], "memory")
        self.assertNotIn("images", call)
        self.assertEqual(self.sessions.list(include_internal=True), [])

    def test_cancel_routes_active_one_shot_request_without_aborting_a_session(self) -> None:
        self.surface._active_completions.add("surface-cancel-1")

        result = self.surface.cancel({"requestId": "surface-cancel-1"})

        self.assertTrue(result["cancelled"])
        self.assertEqual(self.runtime.cancelled_completion_ids, ["surface-cancel-1"])
        self.assertEqual(self.runtime.prompt_session_ids, [])

    def test_voice_refinement_uses_separate_tool_free_session_and_preserves_scope(self) -> None:
        source = "这个项目是在哪里注入这些工具的？如果你要是用自使用自定义的话，就得把工具和功能都注入进去，对吧？"

        result = self.surface.refine_voice(
            {
                "privacyDisposition": "allowed",
                "requestId": "voice-refine-1",
                "frontAppBundleId": "com.example.Editor",
                "transcript": source,
                "hotwords": ["Pi", "Tool", "Skill"],
                "latencyBudgetMs": 2_000,
            }
        )

        self.assertTrue(result["changed"])
        self.assertIn("自定义配置", result["text"])
        self.assertIn("第三遍文字校对器", self.runtime.messages[-1])
        hidden = self.sessions.list(include_internal=True)
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0]["toolProfileVersion"], VOICE_REFINEMENT_TOOL_PROFILE)
        self.assertEqual(hidden[0]["allowedTools"], [])
        self.assertEqual(hidden[0]["thinkingLevel"], "off")
        self.assertEqual(self.runtime.thinking_levels, [])

    def test_voice_refinement_rejects_answer_or_large_semantic_drift(self) -> None:
        with self.assertRaises(ValueError):
            _validated_voice_refinement(
                "当然可以。首先需要修改系统提示词，然后注册工具。",
                source="这个项目是在哪里注入这些工具的？",
            )


if __name__ == "__main__":
    unittest.main()
