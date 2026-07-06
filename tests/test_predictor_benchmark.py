from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.models import ModelPrediction
from rag_ime.predictor_benchmark import (
    benchmark_predictor_latency,
    load_predictor_latency_cases,
    write_predictor_benchmark_report,
)


class _FastProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5, **_kwargs):
        return [
            ModelPrediction(
                text="候选稳定性",
                rank=1,
                provider_name="local-mlx",
                latency_ms=12,
                metadata={
                    "latency_trace": {
                        "firstCandidateMs": 12,
                        "threeCandidatesMs": 18,
                        "totalMs": 20,
                        "cacheHit": True,
                        "cacheHitTokens": 8,
                    }
                },
            ),
            ModelPrediction(text="显示状态机", rank=2, provider_name="local-mlx", latency_ms=14),
            ModelPrediction(text="刷新显示解耦", rank=3, provider_name="local-mlx", latency_ms=18),
        ][:max_candidates]


class PredictorBenchmarkTests(unittest.TestCase):
    def test_load_predictor_latency_cases(self) -> None:
        cases = load_predictor_latency_cases(Path("docs/eval/predictor_latency_cases.jsonl"))

        self.assertGreaterEqual(len(cases), 1)
        self.assertEqual(cases[0].case_id, "post-commit-short")
        self.assertEqual(getattr(cases[0], "request_type"), "ime_post_commit")

    def test_benchmark_predictor_reports_gate(self) -> None:
        cases = load_predictor_latency_cases(Path("docs/eval/predictor_latency_cases.jsonl"))
        report = benchmark_predictor_latency(_FastProvider(), cases[:1], profile="qwen3_06b_ime_hot", repeat=2)

        self.assertTrue(report["gatePassed"])
        self.assertEqual(report["summary"]["formatValidRate"], 1.0)
        self.assertLessEqual(report["summary"]["firstCandidateP95Ms"], 500)

    def test_benchmark_report_can_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            write_predictor_benchmark_report({"ok": True}, path)

            self.assertIn('"ok": true', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
