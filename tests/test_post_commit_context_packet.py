from __future__ import annotations

import unittest

from rag_ime.smart_rag_context_packet import build_post_commit_context_packet


class PostCommitContextPacketTest(unittest.TestCase):
    def test_packet_is_small_group_scoped_and_has_one_fixed_task(self) -> None:
        packet = build_post_commit_context_packet(
            current_input="当前真实输入" * 100,
            context_group_id="doc:a",
            app="com.apple.TextEdit",
            project="ime",
            group_events=[
                {"text": "同文档第一条", "contextGroupId": "doc:a", "ageMs": 20},
                {"text": "其他文档不得进入", "contextGroupId": "doc:b"},
                {"text": "同文档第二条", "contextGroupId": "doc:a", "accepted": True},
                {"text": "已删除", "contextGroupId": "doc:a", "deleted": True},
            ],
            memory_books=[
                {
                    "bookId": "book:1",
                    "title": "RAG 输入法设计",
                    "summary": "组合阶段由 Rime 独占",
                    "surfaceHints": ["限制无效调用"] * 8,
                    "tags": [f"tag-{index}" for index in range(20)],
                    "sourceEventIds": [1, 2],
                }
            ] * 4,
            tag_hints=[f"tag-{index}" for index in range(20)],
            surface_hints=[f"提示{index}" for index in range(10)],
            negative_signals=[f"负向{index}" for index in range(20)],
        )
        self.assertLessEqual(len(packet["currentInput"]["committedTail"]), 500)
        self.assertEqual(len(packet["groupBuffer"]), 2)
        self.assertNotIn("其他文档不得进入", str(packet["groupBuffer"]))
        self.assertEqual(len(packet["memoryBook"]), 2)
        self.assertTrue(all(not item["directCandidateAllowed"] for item in packet["memoryBook"]))
        self.assertEqual(len(packet["tagHints"]), 8)
        self.assertEqual(len(packet["surfaceHints"]), 4)
        self.assertEqual(len(packet["negativeSignals"]), 8)
        self.assertEqual(
            packet["outputContract"],
            {
                "task": "post_commit_suffix",
                "suffixOnly": True,
                "maxChars": 18,
                "candidateCount": 3,
                "noExplanation": True,
                "noContextEcho": True,
            },
        )
        self.assertNotIn("timeline", packet)
        self.assertNotIn("intent", packet)


if __name__ == "__main__":
    unittest.main()
