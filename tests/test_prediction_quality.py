from __future__ import annotations

import unittest

from rag_ime.prediction.quality import (
    CandidateQualityContext,
    dedupe_candidates,
    reject_context_echo,
    reject_generic_low_value,
    reject_prompt_leak,
    score_memory_candidate,
    score_post_commit_candidate,
)


class PredictionQualityV1Tests(unittest.TestCase):
    def test_v1_rejects_current_context_echo(self) -> None:
        context = CandidateQualityContext(committed_context="我想彻底整理项目，先把", commit_preview="先把")

        self.assertTrue(reject_context_echo("我想彻底整理项目，先把", context.committed_context, context.commit_preview))
        self.assertTrue(reject_context_echo("先把", context.committed_context, context.commit_preview))
        self.assertGreater(score_post_commit_candidate("真实输入链路跑通", context), 0.6)

    def test_v1_rejects_low_value_generic_candidate(self) -> None:
        self.assertTrue(reject_generic_low_value("机器学习"))
        self.assertTrue(reject_generic_low_value("打一下再"))
        self.assertFalse(reject_generic_low_value("机器学习", context_terms=("机器学习",)))

    def test_v1_rejects_prompt_and_session_leaks(self) -> None:
        self.assertTrue(reject_prompt_leak('{"sessionId":"debug","requestSeq":1}'))
        self.assertTrue(reject_prompt_leak("requestSeq: 42"))
        self.assertTrue(reject_prompt_leak("sessionId debug request"))
        self.assertTrue(reject_prompt_leak("019f1228-34de-74b3-a627-c546f091e87e 继续调试"))
        self.assertFalse(reject_prompt_leak("候选质量验收"))
        self.assertFalse(reject_prompt_leak("requestSeq stale guard 防止旧候选覆盖新输入"))

    def test_v1_keeps_durable_user_memory(self) -> None:
        context = CandidateQualityContext(committed_context="现在要准备面试展示", strong_terms=("面试",))

        score = score_memory_candidate(
            "面试项目讲清楚真实输入链路",
            context,
            {"state": {"accepted_count": 2}, "durable": True},
        )

        self.assertGreaterEqual(score, 0.9)

    def test_v1_keeps_natural_post_commit_continuation(self) -> None:
        context = CandidateQualityContext(
            committed_context="我想彻底整理项目，先把",
            commit_preview="先把",
            strong_terms=("真实输入", "v1"),
        )

        self.assertGreater(score_post_commit_candidate("真实输入链路跑通", context), 0.6)
        self.assertEqual(score_post_commit_candidate("我想彻底整理项目", context), 0.0)

    def test_v1_dedupes_model_rag_memory_candidates(self) -> None:
        self.assertEqual(
            dedupe_candidates(["真实输入链路跑通", "真实 输入链路跑通", "候选质量验收", ""]),
            ["真实输入链路跑通", "候选质量验收"],
        )


if __name__ == "__main__":
    unittest.main()
