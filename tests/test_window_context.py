from __future__ import annotations

import json
import unittest

from rag_ime.deepseek_completion import (
    DeepSeekCompletionRequest,
    build_deepseek_completion_messages,
)
from rag_ime.smart_rag_context_packet import build_active_rag_context_packet
from rag_ime.window_context import project_window_context_for_generation, validate_window_context


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
            {
                "nodeRef": "ax_button",
                "parentRef": "ax_window",
                "depth": 2,
                "role": "AXButton",
                "label": "提交并关闭",
                "value": "",
                "secure": False,
                "actions": ["press"],
            },
            {
                "nodeRef": "ax_group",
                "parentRef": "ax_window",
                "depth": 1,
                "role": "AXGroup",
                "secure": False,
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

    def test_generation_projection_keeps_readable_text_and_drops_ax_chrome(self) -> None:
        projected = project_window_context_for_generation(validate_window_context(_window_context()))

        self.assertEqual(projected["projection"], "generation_text")
        self.assertEqual(projected["nodeCount"], 1)
        self.assertEqual(projected["sourceNodeCount"], 4)
        self.assertEqual(projected["nodes"][0]["value"], "正在整理桌面语义操作的验收条件")
        self.assertNotIn("nodeRef", str(projected))
        self.assertNotIn("actions", str(projected))
        self.assertNotIn("提交并关闭", str(projected))
        self.assertEqual(
            projected["application"],
            {"name": "Editor", "windowTitle": "项目计划"},
        )

    def test_generation_projection_keeps_window_orientation_when_ax_tree_is_window_only(self) -> None:
        context = _window_context()
        context["application"] = {
            "pid": 42,
            "bundleId": "dev.zed.Zed",
            "name": "Zed",
            "windowTitle": "SGGL — two_sum.py",
        }
        context["nodes"] = [
            {
                "nodeRef": "ax_window",
                "parentRef": "",
                "depth": 0,
                "role": "AXWindow",
                "label": "SGGL — two_sum.py",
                "secure": False,
                "actions": ["AXRaise"],
            }
        ]

        projected = project_window_context_for_generation(validate_window_context(context))

        self.assertEqual(projected["nodes"], [])
        self.assertEqual(projected["nodeCount"], 0)
        self.assertEqual(projected["sourceNodeCount"], 1)
        self.assertEqual(
            projected["application"],
            {"name": "Zed", "windowTitle": "SGGL — two_sum.py"},
        )
        self.assertNotIn("pid", str(projected))
        self.assertNotIn("bundleId", str(projected))
        packet = build_active_rag_context_packet(
            scene="active_rag",
            current_context="解释当前屏幕",
            selected_text="解释当前屏幕",
            selected_text_hash="hash",
            frontend_revision=1,
            selection_epoch=1,
            panel_session_id="zed-window-only",
            project="SGGL",
            app="dev.zed.Zed",
            evidence=(),
            window_context=validate_window_context(context),
        )
        self.assertEqual(
            packet["windowContext"]["application"]["windowTitle"],
            "SGGL — two_sum.py",
        )

    def test_application_semantics_rejects_absolute_and_traversal_paths(self) -> None:
        context = _window_context()
        context["applicationSemantics"] = {
            "source": "zed_workspace_state",
            "projectName": "/Users/example/SecretProject",
            "activeFile": "/Users/example/SecretProject/main.py",
            "editorExcerpt": "1: print('safe excerpt')",
            "projectEntries": [
                "/Users/example/SecretProject",
                "../outside",
                "src/",
                "README.md",
            ],
            "contentOrigin": "workspace_file",
        }

        projected = project_window_context_for_generation(
            validate_window_context(context)
        )

        semantics = projected["applicationSemantics"]
        self.assertEqual(semantics["projectName"], "")
        self.assertEqual(semantics["activeFile"], "")
        self.assertEqual(semantics["projectEntries"], ["src/", "README.md"])
        self.assertIn("safe excerpt", semantics["editorExcerpt"])
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertNotIn("/Users/example", serialized)
        self.assertNotIn("../outside", serialized)

    def test_terminal_visible_range_survives_validation_and_generation_projection(self) -> None:
        visible_tail = "故障输出" * 1_000
        terminal = {
            **_window_context(),
            "captureMode": "terminal_visible_range",
            "nodes": [
                {
                    **_window_context()["nodes"][0],
                    "value": visible_tail,
                }
            ],
        }

        validated = validate_window_context(terminal)
        projected = project_window_context_for_generation(validated)

        self.assertEqual(validated["captureMode"], "terminal_visible_range")
        self.assertEqual(projected["captureMode"], "terminal_visible_range")
        self.assertGreater(len(projected["nodes"][0]["value"]), 800)
        self.assertLessEqual(len(projected["nodes"][0]["value"]), 4_000)

        packet = build_active_rag_context_packet(
            scene="active_rag",
            current_context="修复终端测试失败",
            selected_text="修复终端测试失败",
            selected_text_hash="hash",
            frontend_revision=1,
            selection_epoch=1,
            panel_session_id="terminal-panel",
            project="test",
            app="com.mitchellh.ghostty",
            evidence=(),
            window_context=validated,
        )
        self.assertEqual(packet["windowContext"]["captureMode"], "terminal_visible_range")
        self.assertEqual(packet["windowContext"]["nodeCount"], 1)
        self.assertTrue(packet["windowContext"]["truncated"])

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

    def test_context_packet_keeps_current_then_planning_then_window_priority(self) -> None:
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

        self.assertEqual(
            packet["priority"][:3],
            ["currentInput", "planning", "windowContext"],
        )
        self.assertEqual(packet["windowContext"]["captureMode"], "accessibility_semantics")
        self.assertEqual(packet["windowContext"]["nodes"][0]["label"], "正文")
        self.assertEqual(packet["windowContext"]["projection"], "generation_text")
        self.assertEqual(packet["windowContext"]["sourceNodeCount"], 4)
        self.assertNotIn("提交并关闭", str(packet["windowContext"]))
        self.assertNotIn("actions", str(packet["windowContext"]))
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

        self.assertEqual(payload["contextPacket"]["windowContext"]["nodeCount"], 1)
        self.assertEqual(
            payload["contextPacket"]["windowContext"]["application"],
            {"name": "Editor", "windowTitle": "项目计划"},
        )
        self.assertNotIn("提交并关闭", messages[1]["content"])
        self.assertIn("不能覆盖当前输入", messages[0]["content"])
        self.assertNotIn("must-not-survive", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
