from __future__ import annotations

import unittest

from rag_ime.sequence_fork import BranchSpec, run_sequence_fork


class SequenceForkTests(unittest.TestCase):
    def test_sequence_fork_prefills_once_for_multiple_branches(self) -> None:
        calls = {"prefill": 0, "clone": 0}

        def prefill(tokens):
            calls["prefill"] += 1
            return {"tokens": tuple(tokens)}

        def clone(cache):
            calls["clone"] += 1
            return dict(cache)

        def decode(_cache, branch):
            return (branch.seed_text + "完成", 2)

        results = run_sequence_fork(
            prompt_tokens=(1, 2, 3),
            branches=(
                BranchSpec("a", "候选", 0.1, 8, 12),
                BranchSpec("b", "显示", 0.1, 8, 12),
            ),
            prefill=prefill,
            clone_cache=clone,
            decode_branch=decode,
        )

        self.assertEqual(calls["prefill"], 1)
        self.assertEqual(calls["clone"], 2)
        self.assertTrue(all(item.cache_fork_supported for item in results))
        self.assertEqual([item.candidate for item in results], ["候选完成", "显示完成"])

    def test_sequence_fork_falls_back_when_clone_unavailable(self) -> None:
        results = run_sequence_fork(
            prompt_tokens=(1, 2, 3),
            branches=(BranchSpec("a", "候选", 0.1, 8, 12),),
            prefill=lambda _tokens: object(),
            clone_cache=lambda _cache: (_ for _ in ()).throw(RuntimeError("no clone")),
            decode_branch=lambda _cache, _branch: ("", 0),
        )

        self.assertFalse(results[0].cache_fork_supported)
        self.assertEqual(results[0].fallback_reason, "cache_clone_unsupported")


if __name__ == "__main__":
    unittest.main()
