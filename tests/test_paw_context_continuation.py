from __future__ import annotations

import json
import unittest

from scripts.eval_paw_context_continuation import (
    FIXTURES,
    REQUIRED_TRACE_STAGES,
    run_evaluation,
)


class PawContextContinuationEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # The runner owns four isolated temporary SQLite databases.  Reuse one
        # receipt across assertions so this focused test remains a small local
        # check and never starts a Provider.
        cls.result = run_evaluation()

        calls = []

        def consumer(*, prompt, fixture_id):
            # The model-facing prompt must carry only the natural-language
            # question and actual resumed context.  Fixture labels and
            # expected answers stay host-side even though fixture_id is passed
            # as an adapter routing identity.
            calls.append((prompt, fixture_id))
            if fixture_id in prompt:
                raise AssertionError("routing fixture_id crossed model prompt")
            for hidden in (
                "USE_RETAINED_FACT",
                "USE_UPDATED_FACT",
                "WRONG_OR_STALE_MEMORY",
                "expectedAnswer",
                "targetText",
                "retained",
                "updated",
                "forgotten",
                "abstain",
            ):
                if hidden in prompt:
                    raise AssertionError(f"hidden fixture data crossed callback: {hidden}")
            usage = {
                "inputTokens": 10,
                "outputTokens": 4,
                "totalTokens": 14,
                "estimatedCostUsd": 0.01,
                "costBasis": "test_catalog_estimate",
            }
            if "哪两类" in prompt:
                return {
                    "text": "应保留原始需求和失败轨迹。",
                    "usage": usage,
                    "providerCalls": 1,
                    "receipt": {"status": "completed", "fixture": fixture_id},
                }
            if "哪个模型" in prompt:
                return {
                    "text": "无法确认。",
                    "usage": usage,
                    "providerCalls": 1,
                    "receipt": {"status": "completed", "fixture": fixture_id},
                }
            if "旧部署方案" in prompt:
                return {
                    # A missing answer is never repaired or counted as a pass.
                    "text": "",
                    "usage": usage,
                    "providerCalls": 1,
                    "receipt": {"status": "completed", "fixture": fixture_id},
                }
            return {
                # This answer is semantically safe, but usage is unknown, so
                # it must not become model success by default.
                "text": "不能直接写进回答。",
                "usage": {},
                "providerCalls": 1,
                "receipt": {"status": "completed", "fixture": fixture_id},
            }

        cls.consumer_calls = calls
        cls.consumer_result = run_evaluation(consumer=consumer)

    def test_metrics_cover_labeled_memory_consumer_cases(self) -> None:
        result = self.result
        self.assertEqual(
            result["schemaVersion"],
            "paw.context-continuation-evaluation.v1",
        )
        self.assertTrue(result["syntheticLabels"])
        self.assertEqual(
            {case["label"] for case in result["cases"]},
            {"retained", "updated", "forgotten", "abstain"},
        )
        self.assertEqual(
            result["metrics"]["contextContinuationContract"]["passed"],
            4,
        )
        self.assertEqual(
            result["metrics"]["positiveKeyInformationRecall"]["passed"],
            2,
        )
        self.assertEqual(
            result["metrics"]["positiveKeyInformationRecall"]["total"],
            2,
        )
        self.assertEqual(
            result["metrics"]["negativeMemoryExclusion"]["passed"],
            2,
        )
        self.assertEqual(
            result["metrics"]["negativeMemoryExclusion"]["total"],
            2,
        )
        self.assertEqual(
            result["metrics"]["wrongOrStaleMemoryExposure"]["cases"],
            0,
        )
        for ambiguous_name in (
            "realContinuationTaskSuccess",
            "keyInformationRecall",
            "wrongOrStaleMemoryUse",
        ):
            self.assertNotIn(ambiguous_name, result["metrics"])

    def test_resume_and_trace_evidence_are_from_the_real_consumer_path(self) -> None:
        result = self.result
        boundary = result["evidenceBoundary"]
        self.assertEqual(boundary["providerCalls"], 0)
        self.assertTrue(boundary["agentServiceReopenResume"])
        self.assertTrue(boundary["sourceRuntimeEvidenceOnly"])
        self.assertFalse(boundary["formalAgentLabJob"])
        self.assertEqual(boundary["modelAnswerQuality"], "unmeasured")
        for case in result["cases"]:
            self.assertTrue(case["resumed"]["compactionRecoveryPresent"])
            for phase in ("initial", "resumed"):
                trace = case[phase]["trace"]
                self.assertEqual(trace["status"], "accepted")
                self.assertTrue(trace["requiredStagesPresent"])
                self.assertEqual(
                    trace["stages"],
                    list(REQUIRED_TRACE_STAGES),
                )
                self.assertEqual(
                    trace["traceContractAccepted"],
                    True,
                )

    def test_stale_and_sensitive_rows_do_not_enter_the_resumed_context(self) -> None:
        result = self.result
        by_label = {case["label"]: case for case in result["cases"]}
        self.assertEqual(
            by_label["updated"]["resumed"]["trace"]["memoryAtomIds"],
            [FIXTURES[1]["targetId"]],
        )
        self.assertEqual(
            by_label["forgotten"]["resumed"]["trace"]["memoryAtomIds"],
            [],
        )
        self.assertEqual(
            by_label["abstain"]["resumed"]["trace"]["memoryAtomIds"],
            [],
        )
        self.assertFalse(by_label["updated"]["wrongOrStaleMemoryExposure"])
        self.assertFalse(by_label["abstain"]["wrongOrStaleMemoryExposure"])
        self.assertTrue(by_label["retained"]["positiveKeyInformationRecall"])
        self.assertTrue(by_label["updated"]["positiveKeyInformationRecall"])
        self.assertTrue(by_label["forgotten"]["negativeMemoryExcluded"])
        self.assertTrue(by_label["abstain"]["negativeMemoryExcluded"])

    def test_context_token_totals_are_trace_token_estimates(self) -> None:
        result = self.result
        rows = result["metrics"]["contextTokens"]["memoryContext"]["perTurn"]
        expected_memory_total = sum(
            int(row["initialMemory"]) + int(row["resumedMemory"])
            for row in rows
        )
        self.assertEqual(
            result["metrics"]["contextTokens"]["memoryContext"]["total"],
            expected_memory_total,
        )
        for case, row in zip(result["cases"], rows, strict=True):
            self.assertEqual(
                row["fixtureId"],
                case["fixtureId"],
            )
            self.assertEqual(
                row["initialMemory"],
                case["initial"]["trace"]["memoryTokens"],
            )
            self.assertEqual(
                row["resumedMemory"],
                case["resumed"]["trace"]["memoryTokens"],
            )
        # The receipt is privacy-safe: detailed fixture text is never emitted.
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("PAW 输入法评测必须保留原始需求和失败轨迹", encoded)
        self.assertNotIn("部署凭据属于敏感记忆，不应进入 Agent 上下文", encoded)

    def test_callback_receives_only_prompt_context_and_requires_real_usage(self) -> None:
        result = self.consumer_result
        self.assertEqual(len(self.consumer_calls), 4)
        self.assertEqual(
            len({fixture_id for _prompt, fixture_id in self.consumer_calls}),
            4,
        )
        self.assertEqual(
            result["evaluationBudget"]["maxConsumerCompletionsPerFixture"],
            1,
        )
        self.assertEqual(
            result["metrics"]["modelUsageCompleteness"]["callbackCalls"],
            4,
        )
        self.assertEqual(
            result["metrics"]["modelContinuationSuccess"]["passed"],
            1,
        )
        self.assertEqual(
            result["metrics"]["modelContinuationSuccess"]["total"],
            4,
        )
        self.assertEqual(
            result["metrics"]["modelContinuationSuccess"]["answerAcceptedCases"],
            2,
        )
        self.assertEqual(
            result["metrics"]["modelUsageCompleteness"]["usageCompleteCases"],
            3,
        )
        # One callback omitted usage; the aggregate must not turn the three
        # known totals into a falsely complete four-case Provider total.
        self.assertIsNone(
            result["metrics"]["modelUsageCompleteness"]["observedTotalTokens"]
        )
        self.assertIsNone(
            result["metrics"]["modelUsageCompleteness"]["observedCostUsd"]
        )
        by_id = {case["fixtureId"]: case for case in result["cases"]}
        self.assertTrue(by_id["retained-001"]["modelContinuationSuccess"])
        self.assertFalse(by_id["updated-001"]["modelContinuationSuccess"])
        self.assertFalse(by_id["forgotten-001"]["modelContinuationSuccess"])
        self.assertFalse(by_id["abstain-001"]["modelContinuationSuccess"])
        self.assertEqual(
            by_id["retained-001"]["modelConsumer"]["answer"],
            "应保留原始需求和失败轨迹。",
        )
        self.assertEqual(
            by_id["retained-001"]["modelConsumer"]["receipt"]["status"],
            "completed",
        )
        self.assertEqual(
            by_id["abstain-001"]["modelConsumer"]["usageCompleteness"]["complete"],
            False,
        )


if __name__ == "__main__":
    unittest.main()
