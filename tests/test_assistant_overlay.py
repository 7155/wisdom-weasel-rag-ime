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
        self.assertEqual(payload["statusText"], "AI 建议")

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


if __name__ == "__main__":
    unittest.main()
