from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_mlx_model_matrix.py"
SPEC = importlib.util.spec_from_file_location("benchmark_mlx_model_matrix", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
matrix = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = matrix
SPEC.loader.exec_module(matrix)


class MlxModelMatrixScriptTests(unittest.TestCase):
    def test_parse_models_deduplicates_and_preserves_order(self) -> None:
        self.assertEqual(matrix.parse_models("a,b,a\nc"), ["a", "b", "c"])

    def test_inline_case_parses_rime_candidates(self) -> None:
        case = matrix.parse_inline_case("design|pinyin_constrained|sj|我想|设计,世界,手机")

        self.assertEqual(case.case_id, "design")
        self.assertEqual(case.request_type, "pinyin_constrained")
        self.assertEqual(case.current_input, "sj")
        self.assertEqual(case.recent_context, "我想")
        self.assertEqual(case.rime_candidates, ("设计", "世界", "手机"))

    def test_load_cases_file_accepts_jsonl_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "id": "post",
                        "currentInput": "",
                        "recentContext": "我想接入本地记忆",
                        "requestType": "no_input",
                        "rimeCandidates": ["记忆"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            args = type("Args", (), {"cases_file": str(path), "case": []})()

            cases = matrix.load_cases(args)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case_id, "post")
        self.assertEqual(cases[0].rime_candidates, ("记忆",))

    def test_summarize_cases_penalizes_bad_markers_and_low_value_candidates(self) -> None:
        summary = matrix.summarize_cases(
            [
                {
                    "totalMs": 200,
                    "candidateCount": 2,
                    "badRawMarkers": ["<think>"],
                    "lowValueCandidates": ["补后端测试"],
                    "candidateMode": "json-generation",
                },
                {
                    "totalMs": 100,
                    "candidateCount": 0,
                    "badRawMarkers": [],
                    "lowValueCandidates": [],
                    "candidateMode": "next-token-logits",
                },
            ]
        )

        self.assertEqual(summary["caseCount"], 2)
        self.assertEqual(summary["totalCandidates"], 2)
        self.assertEqual(summary["emptyCases"], 1)
        self.assertEqual(summary["badRawMarkerCount"], 1)
        self.assertEqual(summary["lowValueCandidateCount"], 1)
        self.assertLess(summary["qualityScore"], 100)

    def test_choose_winner_prefers_quality_before_latency(self) -> None:
        winner = matrix.choose_winner(
            [
                {"model": "fast", "ok": True, "summary": {"qualityScore": 80, "p50TotalMs": 50, "lowValueCandidateCount": 0}},
                {"model": "better", "ok": True, "summary": {"qualityScore": 90, "p50TotalMs": 500, "lowValueCandidateCount": 0}},
            ]
        )

        self.assertEqual(winner["model"], "better")


if __name__ == "__main__":
    unittest.main()
