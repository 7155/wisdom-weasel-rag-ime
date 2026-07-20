from __future__ import annotations

import unittest

from rag_ime.assistant_overlay import build_assistant_overlay_payload


class AssistantOverlayTests(unittest.TestCase):
    def test_ready_model_candidate_stops_thinking_animation_even_when_rag_pending(self) -> None:
        payload = build_assistant_overlay_payload(
            ui_mode="post_commit_prediction",
            input_mode="post_commit_predicting",
            display_candidates=[
                {
                    "text": "我晚点再发一版",
                    "insertText": "我晚点再发一版",
                    "sourceType": "model",
                    "metadata": {"presentationPartial": False},
                }
            ],
            rag_candidates=[],
            prediction_session={"phase": "post_commit", "requestSeq": 5},
            key_policy={},
            progressive={"enabled": True, "partial": True, "shouldFollowUp": True, "pendingLanes": ["rag"]},
            frontend_transaction={},
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(payload["animation"]["kind"], "none")
        self.assertEqual(payload["statusText"], "智能建议")

    def test_partial_model_candidate_keeps_thinking_animation(self) -> None:
        payload = build_assistant_overlay_payload(
            ui_mode="post_commit_prediction",
            input_mode="post_commit_predicting",
            display_candidates=[
                {
                    "text": "我晚",
                    "insertText": "我晚",
                    "sourceType": "model",
                    "metadata": {"presentationPartial": True},
                }
            ],
            rag_candidates=[],
            prediction_session={"phase": "post_commit", "requestSeq": 2},
            key_policy={},
            progressive={"enabled": True, "partial": True, "shouldFollowUp": True, "pendingLanes": ["model"]},
            frontend_transaction={},
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(payload["animation"]["kind"], "thinking_dots")
        self.assertEqual(payload["statusText"], "AI 正在想...")

    def test_post_commit_generation_action_remains_visible_without_model_result(self) -> None:
        payload = build_assistant_overlay_payload(
            ui_mode="post_commit_prediction",
            input_mode="post_commit_predicting",
            display_candidates=[
                {
                    "text": "DeepSeek 生成",
                    "insertText": "",
                    "sourceType": "action",
                }
            ],
            rag_candidates=[],
            prediction_session={"phase": "post_commit", "requestSeq": 2},
            key_policy={},
            progressive={"enabled": True, "partial": True, "shouldFollowUp": True, "pendingLanes": ["model"]},
            frontend_transaction={},
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(payload["dismissReason"], "")
        self.assertEqual([item["sourceType"] for item in payload["candidates"]], ["action"])

    def test_deepseek_action_is_visible_beside_real_model_candidates(self) -> None:
        payload = build_assistant_overlay_payload(
            ui_mode="post_commit_prediction",
            input_mode="post_commit_predicting",
            display_candidates=[
                {"text": "继续优化上下文", "insertText": "继续优化上下文", "sourceType": "model"},
                {
                    "text": "DeepSeek 生成",
                    "insertText": "",
                    "sourceType": "action",
                    "selectionAction": "start_active_rag_from_context",
                },
            ],
            rag_candidates=[],
            prediction_session={"phase": "post_commit", "requestSeq": 3},
            key_policy={},
            progressive={},
            frontend_transaction={},
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(
            [(item["sourceType"], item["text"]) for item in payload["candidates"]],
            [("model", "继续优化上下文"), ("action", "DeepSeek 生成")],
        )


if __name__ == "__main__":
    unittest.main()
