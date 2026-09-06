from __future__ import annotations

import unittest

from rag_ime.prediction_trigger import PredictionTrigger, PredictionTriggerConfig


class PredictionTriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0
        self.trigger = PredictionTrigger(clock_ms=lambda: self.now)

    def test_ten_fast_commits_coalesce_to_one_predictor_call(self) -> None:
        calls = 0
        for index in range(10):
            self.now = index * 100
            self.trigger.record_commit(
                group_id="doc:a",
                text="输入",
                context_hash=f"ctx:{index}",
                reliable=True,
            )
            self.assertFalse(self.trigger.poll("doc:a").should_call_predictor)
        self.now = 1_400
        decision = self.trigger.poll("doc:a")
        if decision.should_call_predictor:
            calls += 1
        self.assertEqual(calls, 1)
        self.assertTrue(self.trigger.complete(decision, result_count=1))

    def test_unreliable_context_never_calls(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="已经输入六个字", context_hash="x", reliable=False)
        self.now = 500
        self.assertFalse(self.trigger.poll("doc:a").should_call_predictor)

    def test_duplicate_hash_does_not_increase_calls(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="已经输入六个字", context_hash="same", reliable=True)
        self.now = 500
        first = self.trigger.poll("doc:a")
        self.assertTrue(first.should_call_predictor)
        self.trigger.complete(first, result_count=1)
        self.trigger.record_commit(group_id="doc:a", text="继续输入六个字", context_hash="same", reliable=True)
        self.now = 1_000
        self.assertFalse(self.trigger.poll("doc:a").should_call_predictor)

    def test_punctuation_and_accepted_candidate_can_trigger(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="好。", context_hash="p1", reliable=True)
        self.now = 500
        punctuation = self.trigger.poll("doc:a")
        self.assertTrue(punctuation.should_call_predictor)
        self.trigger.complete(punctuation, result_count=1)
        self.now = 2_100
        self.trigger.record_commit(
            group_id="doc:a",
            text="短",
            context_hash="p2",
            reliable=True,
            accepted_candidate=True,
        )
        self.assertTrue(self.trigger.poll("doc:a").should_call_predictor)

    def test_accepted_continuations_bypass_normal_limit_but_keep_dedupe_and_chain_cap(self) -> None:
        self.trigger = PredictionTrigger(
            PredictionTriggerConfig(max_calls_per_10s=2),
            clock_ms=lambda: self.now,
        )
        for index in range(2):
            self.now = index * 1_000
            self.trigger.record_commit(
                group_id="doc:tab-chain",
                text="普通输入已经达到阈值",
                context_hash=f"normal:{index}",
                reliable=True,
            )
            self.now += 500
            decision = self.trigger.poll("doc:tab-chain")
            self.assertTrue(decision.should_call_predictor)
            self.assertTrue(self.trigger.complete(decision, result_count=3))

        # Explicit Tab acceptance is a user-driven continuation, so it must
        # keep working after the ordinary two-calls-per-10s budget is full.
        for index in range(6):
            self.now = 2_100 + index * 100
            self.trigger.record_commit(
                group_id="doc:tab-chain",
                text="短",
                context_hash=f"accepted:{index}",
                reliable=True,
                accepted_candidate=True,
            )
            decision = self.trigger.poll("doc:tab-chain")
            self.assertTrue(decision.should_call_predictor)
            self.assertTrue(self.trigger.complete(decision, result_count=3))

        self.now = 2_800
        self.trigger.record_commit(
            group_id="doc:tab-chain",
            text="短",
            context_hash="accepted:overflow",
            reliable=True,
            accepted_candidate=True,
        )
        limited = self.trigger.poll("doc:tab-chain")
        self.assertFalse(limited.should_call_predictor)
        self.assertEqual(limited.reason, "accepted_continuation_rate_limit")

        self.now = 12_500
        self.trigger.record_commit(
            group_id="doc:tab-chain",
            text="短",
            context_hash="accepted:5",
            reliable=True,
            accepted_candidate=True,
        )
        duplicate = self.trigger.poll("doc:tab-chain")
        self.assertFalse(duplicate.should_call_predictor)
        self.assertEqual(duplicate.reason, "duplicate_context_hash")

    def test_empty_result_enters_cooldown(self) -> None:
        self.trigger = PredictionTrigger(
            PredictionTriggerConfig(ignore_cooldown_ms=400),
            clock_ms=lambda: self.now,
        )
        self.trigger.record_commit(group_id="doc:a", text="已经输入六个字", context_hash="a", reliable=True)
        self.now = 500
        first = self.trigger.poll("doc:a")
        self.trigger.complete(first, result_count=0)
        self.trigger.record_commit(group_id="doc:a", text="继续输入六个字", context_hash="b", reliable=True)
        self.now = 899
        self.assertFalse(self.trigger.poll("doc:a").should_call_predictor)
        self.now = 900
        self.assertTrue(self.trigger.poll("doc:a").should_call_predictor)

    def test_single_chinese_commit_triggers_after_idle(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="你", context_hash="one", reliable=True)
        self.now = 179
        self.assertFalse(self.trigger.poll("doc:a").should_call_predictor)
        self.now = 180
        self.assertTrue(self.trigger.poll("doc:a").should_call_predictor)

    def test_t0_direct_memory_skips_model_and_remote_provider_is_forbidden(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="已经输入六个字", context_hash="a", reliable=True)
        self.now = 500
        direct = self.trigger.poll("doc:a", direct_memory=("完成前台闭环", 0.9))
        self.assertEqual(direct.direct_candidate, "完成前台闭环")
        self.assertFalse(direct.should_call_predictor)
        self.now = 2_100
        self.trigger.record_commit(group_id="doc:a", text="继续输入六个字", context_hash="b", reliable=True)
        self.now = 2_600
        remote = self.trigger.poll("doc:a", provider_kind="deepseek")
        self.assertFalse(remote.should_call_predictor)
        self.assertEqual(remote.reason, "remote_provider_forbidden")

    def test_latest_wins_discards_old_inflight_result(self) -> None:
        self.trigger.record_commit(group_id="doc:a", text="已经输入六个字", context_hash="a", reliable=True)
        self.now = 500
        old = self.trigger.poll("doc:a")
        self.now = 600
        self.trigger.record_commit(group_id="doc:a", text="新的输入六个字", context_hash="b", reliable=True)
        self.assertFalse(self.trigger.complete(old, result_count=1))

    def test_stale_ignored_result_does_not_cooldown_newer_generation(self) -> None:
        self.trigger = PredictionTrigger(
            PredictionTriggerConfig(idle_ms=0, ignore_cooldown_ms=400),
            clock_ms=lambda: self.now,
        )
        self.trigger.record_commit(group_id="doc:a", text="旧输入", context_hash="old", reliable=True)
        old = self.trigger.poll("doc:a")

        self.now = 1
        self.trigger.record_commit(group_id="doc:a", text="新输入", context_hash="new", reliable=True)
        newer = self.trigger.poll("doc:a")
        self.assertTrue(newer.should_call_predictor)

        self.now = 2
        self.assertFalse(self.trigger.complete(old, result_count=0, ignored=True, now=self.now))
        self.assertTrue(self.trigger.complete(newer, result_count=1, now=self.now))

        self.now = 3
        self.trigger.record_commit(group_id="doc:a", text="后续输入", context_hash="next", reliable=True)
        self.assertTrue(self.trigger.poll("doc:a").should_call_predictor)

    def test_stale_t0_resolution_does_not_remove_newer_provider_budget(self) -> None:
        self.trigger = PredictionTrigger(
            PredictionTriggerConfig(idle_ms=0, max_calls_per_10s=2),
            clock_ms=lambda: self.now,
        )
        self.trigger.record_commit(group_id="doc:a", text="旧输入", context_hash="old", reliable=True)
        old = self.trigger.poll("doc:a")

        self.now = 1
        self.trigger.record_commit(group_id="doc:a", text="新输入", context_hash="new", reliable=True)
        newer = self.trigger.poll("doc:a")
        self.assertTrue(newer.should_call_predictor)

        self.now = 2
        self.assertFalse(self.trigger.complete(old, result_count=1, provider_called=False, now=self.now))
        self.assertTrue(self.trigger.complete(newer, result_count=1, now=self.now))

        self.now = 3
        self.trigger.record_commit(group_id="doc:a", text="后续输入", context_hash="next", reliable=True)
        limited = self.trigger.poll("doc:a")
        self.assertFalse(limited.should_call_predictor)
        self.assertEqual(limited.reason, "max_calls_per_10s")

    def test_t0_resolution_does_not_consume_provider_rate_budget(self) -> None:
        for index in range(2):
            self.now = index * 1_000
            self.trigger.record_commit(
                group_id="doc:a",
                text="已经输入六个字",
                context_hash=f"memory:{index}",
                reliable=True,
            )
            self.now += 500
            decision = self.trigger.poll("doc:a")
            self.assertTrue(decision.should_call_predictor)
            self.assertTrue(self.trigger.complete(decision, result_count=1, provider_called=False))

        self.now = 2_500
        self.trigger.record_commit(
            group_id="doc:a",
            text="现在调用本地模型",
            context_hash="local:model",
            reliable=True,
        )
        self.now = 3_000
        self.assertTrue(self.trigger.poll("doc:a").should_call_predictor)


if __name__ == "__main__":
    unittest.main()
