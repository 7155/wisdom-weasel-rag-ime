from __future__ import annotations

import unittest

from rag_ime.active_rag_candidate_compiler import compile_active_rag_candidates
from rag_ime.deepseek_completion import CompletionCandidateDelta


class ActiveRagCandidateCompilerTests(unittest.TestCase):
    def test_unlimited_remote_candidate_preserves_full_paragraph_layout(self) -> None:
        first = "第一段保留完整结果。" * 12
        second = "第二段也不能被本地截断。" * 12
        expected = f"{first}\n\n{second}"

        candidates = compile_active_rag_candidates(
            (CompletionCandidateDelta(text=expected, insert_text=expected),),
            max_chars=0,
        )

        self.assertGreater(len(expected), 180)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].text, expected)
        self.assertEqual(candidates[0].insert_text, expected)
        self.assertNotIn("lengthGoverned", candidates[0].metadata)

    def test_positive_legacy_limit_still_governs_candidate_length(self) -> None:
        candidates = compile_active_rag_candidates(
            (CompletionCandidateDelta(text="这是一个需要保持兼容的过长候选", insert_text=""),),
            max_chars=6,
        )

        self.assertEqual(len(candidates), 1)
        self.assertLessEqual(len(candidates[0].text), 6)
        self.assertTrue(candidates[0].metadata["lengthGoverned"])

    def test_explicit_generation_keeps_normal_technical_prose(self) -> None:
        text = (
            "下一步先检查 Git、Pi、MCP、OpenAI WebSocket 和 127.0.0.1 的运行链路，"
            "再根据日志确认失败发生在检索、传输还是内容解析阶段。"
        )

        candidates = compile_active_rag_candidates(
            (CompletionCandidateDelta(text=text, insert_text=text),),
            selected_text="请分析输入法为什么生成失败",
            max_chars=0,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].text, text)

    def test_selected_request_prefix_is_not_committed_as_an_answer(self) -> None:
        selected = "请分析输入法为什么生成失败，并给出完整修复方案。"

        candidates = compile_active_rag_candidates(
            (CompletionCandidateDelta(text="请分析输入法为什么生成失败", insert_text=""),),
            selected_text=selected,
            max_chars=0,
        )

        self.assertEqual(candidates, ())


if __name__ == "__main__":
    unittest.main()
