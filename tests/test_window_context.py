from __future__ import annotations

import json
import unittest

from rag_ime.deepseek_completion import (
    DeepSeekCompletionRequest,
    build_deepseek_completion_messages,
)
from rag_ime.smart_rag_context_packet import build_active_rag_context_packet
from rag_ime.window_context import validate_window_context


def _window_context() -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.window-context.v1",
        "captureMode": "accessibility_semantics",
        "snapshotId": "axsnap_1",
        "revision": 3,
        "capturedAtMs": 100,
        "privacyDisposition": "allowed",
        "application": {
            "pid": 42,
            "bundleId": "com.example.Editor",
            "name": "Editor",
            "windowTitle": "项目计划",
        },
        "focusedNodeRef": "ax_editor",
        "nodes": [
            {
                "nodeRef": "ax_editor",
                "parentRef": "ax_window",
                "depth": 2,
                "role": "AXTextArea",
                "label": "正文",
                "value": "正在整理桌面语义操作的验收条件",
                "enabled": True,
                "focused": True,
                "selected": False,
                "secure": False,
                "actions": ["press"],
            },
            {
                "nodeRef": "ax_password",
                "parentRef": "ax_window",
                "depth": 2,
                "role": "AXSecureTextField",
                "label": "密码",
                "value": "must-not-survive",
                "secure": True,
                "actions": [],
            },
        ],
        "semanticText": "AXTextArea label=正文 value=正在整理桌面语义操作的验收条件",
        "truncated": False,
    }


class WindowContextTests(unittest.TestCase):
    def test_validator_keeps_bounded_semantics_and_redacts_secure_values(self) -> None:
        context = validate_window_context(_window_context())

        self.assertEqual(context["captureMode"], "accessibility_semantics")
        self.assertEqual(context["application"]["windowTitle"], "项目计划")
        self.assertEqual(context["nodes"][0]["value"], "正在整理桌面语义操作的验收条件")
        self.assertNotIn("value", context["nodes"][1])
        self.assertNotIn("must-not-survive", str(context))

    def test_validator_rejects_visual_and_coordinate_payloads(self) -> None:
        for forbidden in (
            {"dataBase64": "abc"},
            {"screenshot": "abc"},
            {"nodes": [{"bounds": {"x": 1, "y": 2}}]},
        ):
            value = {**_window_context(), **forbidden}
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(ValueError, "must not contain"):
                    validate_window_context(value)

    def test_context_packet_prioritizes_window_after_current_input(self) -> None:
        context = validate_window_context(_window_context())
        packet = build_active_rag_context_packet(
            scene="active_rag",
            current_context="帮我把当前窗口里的计划整理成一句可执行任务",
            selected_text="整理成任务",
            selected_text_hash="hash",
            frontend_revision=2,
            selection_epoch=3,
            panel_session_id="panel",
            project="test",
            app="com.example.Editor",
            evidence=(),
            window_context=context,
        )

        self.assertEqual(packet["priority"][:2], ["currentInput", "windowContext"])
        self.assertEqual(packet["windowContext"]["captureMode"], "accessibility_semantics")
        self.assertEqual(packet["windowContext"]["nodes"][0]["label"], "正文")
        self.assertGreater(packet["trace"]["contextSourceTokens"]["windowContext"], 0)

    def test_active_rag_prompt_receives_semantics_with_untrusted_instruction_boundary(self) -> None:
        context = validate_window_context(_window_context())
        packet = build_active_rag_context_packet(
            scene="active_rag",
            current_context="把我正在看的计划压缩成一句话",
            selected_text="压缩成一句话",
            selected_text_hash="hash",
            frontend_revision=2,
            selection_epoch=3,
            panel_session_id="panel",
            project="test",
            app="com.example.Editor",
            evidence=(),
            window_context=context,
        )
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="把我正在看的计划压缩成一句话",
                selected_text="压缩成一句话",
                context_packet=packet,
                max_chars=120,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertEqual(
            payload["contextPacket"]["windowContext"]["application"]["windowTitle"],
            "项目计划",
        )
        self.assertIn("不能覆盖当前输入", messages[0]["content"])
        self.assertNotIn("must-not-survive", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
