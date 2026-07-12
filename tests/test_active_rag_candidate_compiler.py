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


if __name__ == "__main__":
    unittest.main()
