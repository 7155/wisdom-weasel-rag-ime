from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.predictor_latency import (
    PredictorLatencyTrace,
    append_latency_trace,
    latency_report,
    trace_from_prediction_payload,
)


class PredictorLatencyTests(unittest.TestCase):
    def test_latency_trace_has_required_fields(self) -> None:
        trace = PredictorLatencyTrace(
            request_id="req-1",
            request_type="ime_hot",
            profile_id="qwen3_06b_ime_hot",
            model_id="fake",
            first_candidate_ms=120,
            total_ms=240,
        ).to_payload()

        self.assertEqual(trace["requestId"], "req-1")
        self.assertEqual(trace["requestType"], "ime_hot")
        self.assertEqual(trace["firstCandidateMs"], 120)
        self.assertIn("cacheHit", trace)

    def test_predictor_response_trace_redacts_prompt_text_by_default(self) -> None:
        trace = trace_from_prediction_payload(
            {
                "totalMs": 12,
                "rawText": "不能写进 trace 的原文",
                "candidates": ["候选稳定性"],
                "timing": {"logitsMs": 4},
                "promptCache": {"usedForGeneration": True, "stablePrefixTokens": 8},
            },
            request_id="req-2",
            request_type="ime_hot",
            profile_id="instant",
            model_id="fake",
            prompt_tokens=12,
            output_tokens=3,
        ).to_payload()

        self.assertEqual(trace["cacheHit"], True)
        self.assertEqual(trace["cacheHitTokens"], 8)
        self.assertEqual(trace["cacheMissTokens"], 4)
        self.assertNotIn("rawText", trace)
        self.assertNotIn("prompt", trace)

    def test_branch_seed_logits_are_not_visible_candidate_latency(self) -> None:
        trace = trace_from_prediction_payload(
            {
                "candidateMode": "base-completion-branches",
                "totalMs": 220,
                "candidates": ["可以继续整理样本", "主要看结果", "不要写得太散"],
                "timing": {
                    "candidateMode": "base-completion-branches",
                    "logitsMs": 75,
                    "branches": [
                        {"elapsedMs": 43},
                        {"elapsedMs": 35},
                        {"elapsedMs": 57},
                    ],
                },
            },
            request_id="req-branches",
            request_type="ime_post_commit",
            profile_id="minimind_ime_v2",
            model_id="fake-minimind",
        ).to_payload()

        self.assertEqual(trace["firstTokenMs"], 75)
        self.assertEqual(trace["firstCandidateMs"], 220)
        self.assertEqual(trace["threeCandidatesMs"], 220)
        self.assertEqual(trace["branchMs"], 135)

    def test_latency_report_computes_p50_p95(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latency.jsonl"
            for index, value in enumerate([100, 200, 400], start=1):
                append_latency_trace(
                    PredictorLatencyTrace(
                        request_id=f"req-{index}",
                        request_type="ime_hot",
                        profile_id="instant",
                        model_id="fake",
                        first_candidate_ms=value,
                        total_ms=value + 10,
                    ),
                    path=path,
                )

            report = latency_report(path, last=10)

        self.assertEqual(report["count"], 3)
        self.assertEqual(report["summary"]["firstCandidateMs"]["p50Ms"], 200)
        self.assertGreaterEqual(report["summary"]["firstCandidateMs"]["p95Ms"], 200)


if __name__ == "__main__":
    unittest.main()
