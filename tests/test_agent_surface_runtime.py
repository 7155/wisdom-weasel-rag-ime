from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_surface_runtime import (
    AgentSurfaceRuntime,
    PiSurfaceCompletionProvider,
    SURFACE_TOOL_PROFILE,
)
from rag_ime.deepseek_completion import DeepSeekCompletionRequest


class _SurfaceRuntimeStub:
    def __init__(self, events: AgentEventHub) -> None:
        self.events = events
        self.prompt_session_ids: list[str] = []
        self.images: list[list[dict[str, str]]] = []
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
        del message, client_message_id
        turn_id = f"turn-{len(self.prompt_session_ids) + 1}"
        self.prompt_session_ids.append(session_id)
        self.images.append([dict(item) for item in images or []])
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "role": "assistant",
                    "blocks": [{"type": "text", "data": {"text": "继续完成这段文字。"}}],
                }
            },
            turn_id=turn_id,
        )
        self.events.publish(session_id, "turn_completed", {}, turn_id=turn_id)
        return {"turnId": turn_id}

    def model_catalog(self, _session_id):
        return {"selected": dict(self.selected), "models": [dict(item) for item in self.models]}

    def set_model(self, _session_id, *, provider, model_id):
        self.selected = next(
            dict(item)
            for item in self.models
            if item["provider"] == provider and item["id"] == model_id
        )
        return {"selected": dict(self.selected)}

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
        self.surface = AgentSurfaceRuntime(self.agent)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_provider_reuses_hidden_tool_free_session_for_same_app(self) -> None:
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
        self.assertEqual(len(set(self.runtime.prompt_session_ids)), 1)
        hidden = self.sessions.list(include_internal=True)
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0]["sessionKind"], "subagent_runtime")
        self.assertEqual(hidden[0]["toolProfileVersion"], SURFACE_TOOL_PROFILE)
        self.assertEqual(hidden[0]["toolAllowlistMode"], "explicit")
        self.assertEqual(hidden[0]["allowedTools"], [])
        self.assertEqual(self.sessions.list(), [])

    def test_visual_request_switches_to_image_model_and_forwards_screenshot(self) -> None:
        provider = PiSurfaceCompletionProvider(local_runtime=self.surface)
        request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context="根据界面继续",
            surface_request_id="surface-request-image",
            front_app_bundle_id="com.example.Editor",
            visual_context={
                "mimeType": "image/jpeg",
                "dataBase64": base64.b64encode(b"jpeg-fixture").decode("ascii"),
                "pixelWidth": 800,
                "pixelHeight": 600,
                "source": "front_app_window",
            },
        )

        result = list(provider.stream_candidates(request))

        self.assertTrue(result[0].metadata["visualContextUsed"])
        self.assertEqual(self.runtime.selected["id"], "gpt-5.6-luna")
        self.assertEqual(self.runtime.images[0][0]["mimeType"], "image/jpeg")
        self.assertEqual(base64.b64decode(self.runtime.images[0][0]["data"]), b"jpeg-fixture")


if __name__ == "__main__":
    unittest.main()
