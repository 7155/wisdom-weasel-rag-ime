from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_inspect_model_path_reports_text_only_qwen3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3ForCausalLM"],
                        "model_type": "qwen3",
                        "hidden_size": 2048,
                        "num_hidden_layers": 28,
                        "vocab_size": 151936,
                        "quantization": {"bits": 4, "group_size": 64},
                    }
                ),
                encoding="utf-8",
            )
            (model_dir / "tokenizer_config.json").write_text(
                json.dumps({"chat_template": "{% if enable_thinking is false %}<think></think>{% endif %}"}),
                encoding="utf-8",
            )

            info = matrix.inspect_model_path(str(model_dir))

        self.assertTrue(info["exists"])
        self.assertTrue(info["textOnly"])
        self.assertFalse(info["hasVisionConfig"])
        self.assertEqual(info["architecture"], "Qwen3ForCausalLM")
        self.assertEqual(info["quantization"]["bits"], 4)
        self.assertTrue(info["hasChatTemplate"])
        self.assertTrue(info["chatTemplateSupportsThinking"])

    def test_inspect_model_path_flags_vision_language_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3_5ForConditionalGeneration"],
                        "model_type": "qwen3_5",
                        "text_config": {"model_type": "qwen3_5_text", "hidden_size": 2048},
                        "vision_config": {"model_type": "qwen3_5_vision"},
                    }
                ),
                encoding="utf-8",
            )

            info = matrix.inspect_model_path(str(model_dir))

        self.assertTrue(info["exists"])
        self.assertFalse(info["textOnly"])
        self.assertTrue(info["hasVisionConfig"])
        self.assertEqual(info["textModelType"], "qwen3_5_text")

    def test_dry_run_includes_model_info_without_loading_mlx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps({"architectures": ["Qwen3ForCausalLM"], "model_type": "qwen3"}),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = matrix.main(["--models", str(model_dir), "--dry-run", "--pretty"])

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "rag-ime.mlx-model-matrix-plan.v1")
        self.assertEqual(payload["models"][0]["model"], str(model_dir))
        self.assertTrue(payload["models"][0]["modelInfo"]["textOnly"])

    def test_summarize_cases_penalizes_bad_markers_and_low_value_candidates(self) -> None:
        summary = matrix.summarize_cases(
            [
                {
                    "totalMs": 200,
                    "candidateCount": 2,
                    "badRawMarkers": ["<think>", "<|im_end|>"],
                    "lowValueCandidates": ["补后端测试", "验证 LLM 候选"],
                    "weakCandidates": ["优化"],
                    "duplicatePrefixGroups": [{"prefix": "把流程跑", "items": ["把流程跑通", "把流程跑"]}],
                    "candidateMode": "json-generation",
                },
                {
                    "totalMs": 100,
                    "candidateCount": 0,
                    "badRawMarkers": [],
                    "lowValueCandidates": [],
                    "weakCandidates": [],
                    "duplicatePrefixGroups": [],
                    "candidateMode": "next-token-logits",
                },
            ]
        )

        self.assertEqual(summary["caseCount"], 2)
        self.assertEqual(summary["totalCandidates"], 2)
        self.assertEqual(summary["emptyCases"], 1)
        self.assertEqual(summary["badRawMarkerCount"], 2)
        self.assertEqual(summary["lowValueCandidateCount"], 2)
        self.assertEqual(summary["weakCandidateCount"], 1)
        self.assertEqual(summary["duplicatePrefixGroupCount"], 1)
        self.assertLess(summary["qualityScore"], 100)

    def test_quality_helpers_flag_chat_template_echo_short_and_duplicate_candidates(self) -> None:
        self.assertIn("<|im_end|>", matrix.BAD_RAW_MARKERS)
        self.assertIn("Human:", matrix.BAD_RAW_MARKERS)
        self.assertEqual(
            matrix.weak_candidates_for_case(["优化", "部署本地记忆模块"], request_type="no_input_prediction"),
            ["优化"],
        )
        self.assertEqual(
            matrix.duplicate_prefix_groups(["把流程跑通", "把流程跑", "接入本地记忆"])[0],
            {"prefix": "把流程跑", "items": ["把流程跑通", "把流程跑"]},
        )

    def test_choose_winner_prefers_quality_before_latency(self) -> None:
        winner = matrix.choose_winner(
            [
                {
                    "model": "fast",
                    "ok": True,
                    "summary": {
                        "qualityScore": 80,
                        "p50TotalMs": 50,
                        "lowValueCandidateCount": 0,
                        "weakCandidateCount": 0,
                        "duplicatePrefixGroupCount": 0,
                    },
                },
                {
                    "model": "better",
                    "ok": True,
                    "summary": {
                        "qualityScore": 90,
                        "p50TotalMs": 500,
                        "lowValueCandidateCount": 0,
                        "weakCandidateCount": 0,
                        "duplicatePrefixGroupCount": 0,
                    },
                },
            ]
        )

        self.assertEqual(winner["model"], "better")


if __name__ == "__main__":
    unittest.main()
