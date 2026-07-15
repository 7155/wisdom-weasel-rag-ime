from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from rag_ime.mlx_predictor_server import (
    MlxLmEngine,
    _PromptCacheState,
    _branch_continuation_candidates,
    _base_completion_boundary_quality,
    _base_completion_sample_candidate,
    _build_mlx_dynamic_prompt,
    _best_non_eos_token_id,
    _is_base_completion_model,
    _is_low_value_base_candidate,
    _initial_base_completion_seed_indexes,
    QWEN_NON_THINKING_ASSISTANT_PREFIX,
    main as mlx_predictor_server_main,
    _normalize_prediction_request,
    _seed_replay_specs_from_logits,
    _seeded_replay_candidate,
    _token_decodes_visible_text,
    make_mlx_predictor_handler,
)
from rag_ime.predictor import (
    PREDICTION_REQUEST_IME_POST_COMMIT,
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
    PREDICTION_REQUEST_RIME_REORDER,
)


class _FakeMlxEngine:
    model_id = "fake-mlx-qwen"

    def __init__(self) -> None:
        self.prompt_cache = _PromptCacheState(
            enabled=True,
            prepared=True,
            stable_prefix="stable system prompt",
            stable_prefix_tokens=5,
            prepare_ms=7,
        )

    def health(self):
        return {
            "ok": True,
            "provider": "mlx-lm",
            "model": self.model_id,
            "modelLoaded": True,
            "promptCache": self.prompt_cache_status(),
        }

    def prompt_cache_status(self):
        return self.prompt_cache.to_payload()

    def predict(self, **kwargs):
        return {
            "ok": True,
            "rawText": '["本地记忆","输入法候选"]',
            "candidates": ["本地记忆", "输入法候选"],
            "totalMs": 12,
            "promptCache": self.prompt_cache_status(),
        }

    def stream_text(self, **kwargs):
        yield '["本地记忆"'
        yield ',"输入法候选"]'


class _RaisingMlxEngine(_FakeMlxEngine):
    def predict(self, **kwargs):
        raise ValueError("Either input_embeddings or prompt (or both) must be provided.")


class _BrokenPipeWriter:
    def write(self, _data: bytes) -> int:
        raise BrokenPipeError("client closed")

    def flush(self) -> None:
        raise AssertionError("flush should not run after a broken write")


class MlxPredictorServerTests(unittest.TestCase):
    def test_bos_sample_ranking_prefers_finished_sentences(self) -> None:
        self.assertEqual(_base_completion_boundary_quality("今晚再确认一次。", "今晚再确认一次"), 3)
        self.assertEqual(_base_completion_boundary_quality("今晚只收一小", "今晚只收一小"), 1)
        self.assertEqual(_base_completion_boundary_quality("晚点给你发消息", "晚点给你发消息"), 2)

    def test_bos_sample_candidate_keeps_sentence_and_removes_tokenizer_spacing(self) -> None:
        candidate = _base_completion_sample_candidate(
            "等水温稳定后，再 喂食。",
            current_input="",
            recent_context="我先给鱼缸换水",
            max_candidate_chars=24,
        )

        self.assertEqual(candidate, "等水温稳定后，再喂食")

    def test_direct_server_cli_passes_profile_decode_and_branch_contract(self) -> None:
        with patch("rag_ime.mlx_predictor_server.serve_mlx_predictor") as serve:
            result = mlx_predictor_server_main(
                [
                    "--model",
                    "/tmp/minimind-100m",
                    "--profile",
                    "minimind_ime_100m_v1",
                    "--decode-strategy",
                    "bos-sampled-completion-v1",
                    "--branch-count",
                    "8",
                    "--max-tokens",
                    "16",
                ]
            )

        self.assertEqual(result, 0)
        config = serve.call_args.args[0]
        self.assertEqual(config.profile_id, "minimind_ime_100m_v1")
        self.assertEqual(config.decode_strategy, "bos-sampled-completion-v1")
        self.assertEqual(config.branch_count, 8)
        self.assertEqual(config.max_tokens, 16)

    def test_heterogeneous_minimind_profiles_drive_real_engine_decode_contract(self) -> None:
        cases = (
            ("minimind_ime_100m_v1", 14, 12, 16384, "bos-sampled-completion-v1", 16),
            ("minimind_ime_60m_v8", 8, 8, 6400, "bos-short-completion-v8", 8),
        )
        for profile_id, layers, heads, vocab, strategy, branch_tokens in cases:
            with self.subTest(profile=profile_id), tempfile.TemporaryDirectory() as tmp:
                model_dir = Path(tmp)
                (model_dir / "config.json").write_text(
                    json.dumps(
                        {
                            "num_hidden_layers": layers,
                            "num_attention_heads": heads,
                            "vocab_size": vocab,
                        }
                    ),
                    encoding="utf-8",
                )
                modules, _calls = _fake_mlx_modules(
                    generated_text=["候选排序", "来源诊断", "上下文管理"],
                )
                with patch.dict(sys.modules, modules), patch.dict(
                    os.environ,
                    {"RAG_IME_MLX_PROMPT_MODE": ""},
                ):
                    engine = MlxLmEngine(str(model_dir), profile_id=profile_id)
                    with patch.object(
                        engine,
                        "prefill_base_completion_logits",
                        return_value={
                            "candidateScores": [
                                {"text": "结果", "tokenId": 101, "logprob": -0.1},
                                {"text": "速度", "tokenId": 102, "logprob": -0.2},
                                {"text": "方式", "tokenId": 103, "logprob": -0.3},
                            ],
                            "elapsedMs": 7,
                            "promptCache": {"shared": True},
                            "sharedPrefill": True,
                        },
                    ):
                        payload = engine.predict(
                            current_input="",
                            recent_context="本地模型已经完成快速推理",
                            max_candidates=3,
                            max_tokens=branch_tokens,
                            temperature=0.15,
                            top_p=0.85,
                            request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                        )
                    health = engine.health()

                self.assertEqual(payload["candidateMode"], "base-completion-samples")
                self.assertEqual(payload["timing"]["decodeStrategy"], strategy)
                self.assertEqual(payload["timing"]["branchBudget"], 8)
                self.assertEqual(payload["timing"]["sampling"]["topK"], 50)
                self.assertEqual(health["modelProfile"]["id"], profile_id)
                self.assertEqual(health["decodeContract"]["strategy"], strategy)
                self.assertEqual(health["decodeContract"]["branchCount"], 8)
                self.assertTrue(health["capabilities"]["baseCompletion"])

    def test_engine_rejects_decode_contract_that_disagrees_with_profile(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text="候选")
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "requires decodeStrategy"):
                MlxLmEngine(
                    "fake-minimind",
                    profile_id="minimind_ime_v2",
                    decode_strategy="bos-short-completion-v8",
                )

    def test_minimind_100m_http_health_and_predict_use_registered_profile_contract(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=["候选排序", "来源诊断", "上下文管理"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "num_hidden_layers": 14,
                        "num_attention_heads": 12,
                        "vocab_size": 16384,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(sys.modules, modules), patch.dict(
                os.environ,
                {"RAG_IME_MLX_PROMPT_MODE": ""},
            ):
                engine = MlxLmEngine(str(model_dir), profile_id="minimind_ime_100m_v1")
                with patch.object(
                    engine,
                    "prefill_base_completion_logits",
                    return_value={
                        "candidateScores": [
                            {"text": "结果", "tokenId": 101, "logprob": -0.1},
                            {"text": "速度", "tokenId": 102, "logprob": -0.2},
                            {"text": "方式", "tokenId": 103, "logprob": -0.3},
                        ],
                        "elapsedMs": 7,
                        "promptCache": {"shared": True},
                        "sharedPrefill": True,
                    },
                ):
                    try:
                        server, thread = _start_fake_server(engine)
                    except PermissionError:
                        self.skipTest("local socket binding is unavailable in this sandbox")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{server.server_port}/health",
                            timeout=1.0,
                        ) as response:
                            health = json.loads(response.read().decode("utf-8"))
                        body = json.dumps(
                            {
                                "current_input": "",
                                "recent_context": "本地模型已经完成快速推理",
                                "max_candidates": 3,
                                "request_type": "post_commit_completion",
                            },
                            ensure_ascii=False,
                        ).encode("utf-8")
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/predict",
                            data=body,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request, timeout=1.0) as response:
                            prediction = json.loads(response.read().decode("utf-8"))
                    finally:
                        _stop_server(server, thread)

        self.assertEqual(health["modelProfile"]["id"], "minimind_ime_100m_v1")
        self.assertEqual(health["decodeContract"]["strategy"], "bos-sampled-completion-v1")
        self.assertFalse(health["decodeContract"]["streamFirst"])
        self.assertEqual(prediction["candidateMode"], "base-completion-samples")
        self.assertEqual(len(prediction["candidates"]), 3)
        self.assertTrue(all(len(candidate) > 1 for candidate in prediction["candidates"]))
        self.assertEqual(prediction["timing"]["sampling"]["topK"], 50)
        self.assertEqual(prediction["timing"]["sampling"]["temperature"], 0.42)
        self.assertEqual(prediction["timing"]["sampling"]["topP"], 0.92)

    def test_base_candidate_rejects_dirty_adjacent_function_character_repeat(self) -> None:
        self.assertTrue(_is_low_value_base_candidate("能能接"))
        self.assertTrue(_is_low_value_base_candidate("再再处理"))
        self.assertTrue(_is_low_value_base_candidate("就改得太"))
        self.assertTrue(_is_low_value_base_candidate("就可以先拿"))
        self.assertTrue(_is_low_value_base_candidate("短候"))
        self.assertTrue(_is_low_value_base_candidate("预测太远路"))
        self.assertTrue(_is_low_value_base_candidate("太快路"))
        self.assertTrue(_is_low_value_base_candidate("太快路上"))
        self.assertTrue(_is_low_value_base_candidate("不要再临时加新事"))
        self.assertTrue(_is_low_value_base_candidate("过来等会儿再跑"))
        self.assertTrue(_is_low_value_base_candidate("但先把结果同步出"))
        self.assertTrue(_is_low_value_base_candidate("先把本地测试脚本放"))
        self.assertTrue(_is_low_value_base_candidate("去再说"))
        self.assertFalse(_is_low_value_base_candidate("慢慢处理"))

    def test_base_completion_repairs_deterministic_tiny_model_truncations(self) -> None:
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="太",
                raw_text="快先跑通",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "先跑通",
        )
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="使用",
                raw_text="场景最好加个简单",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "先补一个简单的使用场景",
        )
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="不要",
                raw_text="再临时加新事",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "不要再临时加新内容",
        )
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="太",
                raw_text="复杂先把最重要的两",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "先把最重要的两项",
        )
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="一",
                raw_text="版再说",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "先做一版再说",
        )
        self.assertEqual(
            _seeded_replay_candidate(
                seed_text="再",
                raw_text="定反",
                current_input="",
                recent_context="模型上下文不稳定",
                max_candidate_chars=18,
            ),
            "再定方案",
        )

    def test_base_completion_can_use_single_cjk_token_as_branch_seed(self) -> None:
        scores = [
            {"text": "遍", "tokenId": 10},
            {"text": "部分", "tokenId": 11},
            {"text": "版", "tokenId": 12},
            {"text": "的", "tokenId": 13},
        ]

        seeds = _seed_replay_specs_from_logits(
            scores,
            max_seeds=3,
            allow_single_cjk=True,
        )

        self.assertEqual([item["text"] for item in seeds], ["遍", "部分", "版"])

    def test_base_completion_can_select_visible_non_eos_first_token(self) -> None:
        class Tokenizer:
            eos_token_id = 0

            @staticmethod
            def decode(tokens):
                return {0: "", 1: "继续", 2: "\ufffd"}.get(tokens[0], "")

        self.assertEqual(_best_non_eos_token_id([9.0, 8.0, 7.0], Tokenizer()), 1)
        self.assertFalse(_token_decodes_visible_text(Tokenizer(), 0))
        self.assertTrue(_token_decodes_visible_text(Tokenizer(), 1))

    def test_base_completion_expands_top_logits_into_three_real_continuations(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=["候选排序", "来源诊断", "上下文管理"]
        )
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion"},
        ):
            engine = MlxLmEngine("fake-minimind", profile_id="minimind_ime_v2")
            with patch.object(
                engine,
                "prefill_base_completion_logits",
                return_value={
                    "candidates": ["结果", "速度", "方式", "继续", "模型"],
                    "candidateScores": [
                        {"text": "结果", "tokenId": 101, "logprob": -0.1},
                        {"text": "速度", "tokenId": 102, "logprob": -0.2},
                        {"text": "方式", "tokenId": 103, "logprob": -0.3},
                    ],
                    "elapsedMs": 18,
                    "promptCache": {"shared": True},
                    "sharedPrefill": True,
                },
            ) as prefill:
                payload = engine.predict(
                    current_input="",
                    recent_context="本地模型已经完成快速推理",
                    max_candidates=5,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                    request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                )

        self.assertEqual(payload["candidateMode"], "base-completion-branches")
        self.assertEqual(payload["candidates"], ["速度来源诊断", "方式上下文管理", "结果候选排序"])
        self.assertEqual([item["rank"] for item in payload["candidateScores"]], [1, 2, 3])
        self.assertEqual(
            [item["source"] for item in payload["candidateScores"]],
            ["seed:速度", "seed:方式", "seed:结果"],
        )
        self.assertEqual(payload["timing"]["logitsMs"], 18)
        self.assertEqual(payload["timing"]["branchCount"], 3)
        self.assertEqual(payload["timing"]["decodeMode"], "shared-prefill-batch")
        self.assertTrue(payload["timing"]["sharedPrefill"])
        self.assertEqual(payload["timing"]["batchCalls"], 1)
        self.assertEqual([item["maxTokens"] for item in payload["timing"]["branches"]], [6, 6, 6])
        self.assertEqual(calls["batch_generate"], 1)
        self.assertEqual(calls["batch_prompts"], [[101], [102], [103]])
        self.assertEqual(calls["generate_step"], 0)
        prefill.assert_called_once()

    def test_base_completion_batches_extra_seeds_to_replace_malformed_branches(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=["太", "来源诊断", "上下文管理", "补齐质量", "稍后再看", "保留结果"]
        )
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion"},
        ):
            engine = MlxLmEngine("fake-minimind", profile_id="minimind_ime_v2")
            with patch.object(
                engine,
                "prefill_base_completion_logits",
                return_value={
                    "candidateScores": [
                        {"text": "结果", "tokenId": 101, "logprob": -0.1},
                        {"text": "速度", "tokenId": 102, "logprob": -0.2},
                        {"text": "方式", "tokenId": 103, "logprob": -0.3},
                        {"text": "继续", "tokenId": 104, "logprob": -0.4},
                        {"text": "晚", "tokenId": 105, "logprob": -0.5},
                        {"text": "先", "tokenId": 106, "logprob": -0.6},
                    ],
                    "elapsedMs": 12,
                    "promptCache": {"shared": True},
                    "sharedPrefill": True,
                },
            ):
                payload = engine.predict(
                    current_input="",
                    recent_context="模型上下文需要继续优化",
                    max_candidates=3,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                    request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                )

        self.assertEqual(payload["candidates"], ["方式上下文管理", "速度来源诊断", "继续补齐质量"])
        self.assertEqual(payload["timing"]["branchCount"], 4)
        self.assertTrue(payload["timing"]["qualityReranked"])
        self.assertGreater(payload["timing"]["contextDomainTermCount"], 0)
        self.assertEqual(calls["batch_generate"], 1)
        self.assertEqual(len(calls["batch_prompts"]), 4)

    def test_domain_context_plans_relevant_seed_before_low_information_seed(self) -> None:
        seeds = [
            {"text": "安排"},
            {"text": "就"},
            {"text": "词"},
            {"text": "下"},
            {"text": "候"},
            {"text": "读"},
        ]

        indexes = _initial_base_completion_seed_indexes(
            seeds,
            recent_context="模型上下文的预测候选不合理",
            display_limit=3,
        )

        self.assertEqual(indexes, [0, 2, 3, 4])

    def test_base_completion_batch_unavailable_falls_back_to_sequential_branches(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=["候选排序", "来源诊断", "上下文管理"]
        )
        delattr(modules["mlx_lm.generate"], "batch_generate")
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion"},
        ):
            engine = MlxLmEngine("fake-minimind", profile_id="minimind_ime_v2")
            with patch.object(
                engine,
                "prefill_base_completion_logits",
                return_value={
                    "candidates": ["结果", "速度", "方式"],
                    "candidateScores": [
                        {"text": "结果", "tokenId": 101, "logprob": -0.1},
                        {"text": "速度", "tokenId": 102, "logprob": -0.2},
                        {"text": "方式", "tokenId": 103, "logprob": -0.3},
                    ],
                    "elapsedMs": 18,
                    "promptCache": {"shared": True},
                    "sharedPrefill": True,
                },
            ):
                payload = engine.predict(
                    current_input="",
                    recent_context="本地模型已经完成快速推理",
                    max_candidates=3,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                    request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                )

        self.assertEqual(payload["candidates"], ["速度来源诊断", "方式上下文管理", "结果候选排序"])
        self.assertEqual(payload["timing"]["decodeMode"], "sequential-fallback")
        self.assertEqual(calls["generate_step"], 3)

    def test_base_completion_empty_prompt_never_calls_mlx_generate_step(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="不应生成")
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion"},
        ):
            payload = MlxLmEngine("fake-minimind").predict(
                current_input="",
                recent_context="",
                max_candidates=3,
                max_tokens=8,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
            )

        self.assertEqual(payload["candidateMode"], "base-completion-empty-prompt")
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["timing"]["skippedReason"], "empty_prompt")
        self.assertEqual(calls["generate_step"], 0)

    def test_base_completion_empty_stream_never_calls_mlx_generate_step(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="不应生成")
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion"},
        ):
            text = "".join(
                MlxLmEngine("fake-minimind").stream_text(
                    current_input="",
                    recent_context="",
                    max_candidates=3,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                    request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                )
            )

        self.assertEqual(text, "")
        self.assertEqual(calls["generate_step"], 0)

    def test_startup_warmup_compiles_prediction_path_and_is_visible_in_health(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=["候选排序", "来源诊断", "上下文管理", "补齐结果"]
        )
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_PROMPT_MODE": "base-completion", "RAG_IME_MLX_WARMUP": "1"},
        ):
            engine = MlxLmEngine("fake-minimind", profile_id="minimind_ime_v2")
            status = engine.warmup(max_tokens=8, temperature=0.15, top_p=0.85)

        self.assertTrue(status["completed"])
        self.assertTrue(status["ok"])
        self.assertGreaterEqual(status["candidateCount"], 1)
        self.assertEqual(engine.health()["warmup"], status)

    def test_startup_warmup_can_be_disabled_without_running_prediction(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text="unused")
        with patch.dict(sys.modules, modules), patch.dict(
            os.environ,
            {"RAG_IME_MLX_WARMUP": "0"},
        ):
            engine = MlxLmEngine("fake-minimind", profile_id="minimind_ime_v2")
            with patch.object(engine, "predict") as predict:
                status = engine.warmup(max_tokens=8, temperature=0.15, top_p=0.85)

        self.assertTrue(status["completed"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["skippedReason"], "disabled")
        predict.assert_not_called()

    def test_normalized_request_keeps_prediction_request_type_and_rime_candidates(self) -> None:
        request = _normalize_prediction_request(
            {
                "model": "fake-mlx-qwen",
                "currentInput": "sj",
                "recentContext": "我想",
                "requestType": "rime-reorder",
                "rimeCandidates": ["设计", "手机", "设计", ""],
                "contextFingerprint": "ctx123",
                "rimeCandidateCount": 2,
                "rimeCandidatesFingerprint": "rime123",
            },
            default_model="fake-mlx-qwen",
        )

        self.assertEqual(request["request_type"], "rime_reorder")
        self.assertEqual(request["rime_candidates"], ("设计", "手机"))
        self.assertEqual(request["request_metadata"]["contextFingerprint"], "ctx123")
        self.assertEqual(request["request_metadata"]["rimeCandidateCount"], 2)
        self.assertEqual(request["request_metadata"]["rimeCandidatesFingerprint"], "rime123")

    def test_normalized_request_collapses_repeated_tail_context(self) -> None:
        request = _normalize_prediction_request(
            {
                "model": "fake-mlx-qwen",
                "currentInput": "继续继续下一步继续完善一下继续完善一下继续完善一下",
                "recentContext": "我们继续完善一下继续完善一下继续完善一下",
            },
            default_model="fake-mlx-qwen",
        )

        self.assertEqual(request["current_input"], "继续继续下一步继续完善一下")
        self.assertEqual(request["recent_context"], "我们继续完善一下")

    def test_normalized_request_accepts_snake_case_probe_payloads(self) -> None:
        request = _normalize_prediction_request(
            {
                "model": "fake-mlx-qwen",
                "current_input": "我们继续",
                "recent_context": "今天测试输入法连续预测",
                "max_candidates": 1,
                "max_tokens": 8,
                "top_p": 0.85,
                "request_type": "post_commit_completion",
                "rime_candidates": ["继续完善"],
            },
            default_model="fake-mlx-qwen",
        )

        self.assertEqual(request["current_input"], "我们继续")
        self.assertEqual(request["recent_context"], "今天测试输入法连续预测")
        self.assertEqual(request["max_candidates"], 1)
        self.assertEqual(request["max_tokens"], 8)
        self.assertEqual(request["request_type"], "post_commit_completion")
        self.assertEqual(request["rime_candidates"], ("继续完善",))

    def test_prompt_mode_env_can_force_base_completion(self) -> None:
        model_info = {
            "architecture": "Qwen3_5ForConditionalGeneration",
            "modelType": "qwen3_5",
            "hasChatTemplate": False,
        }

        with patch.dict(os.environ, {"RAG_IME_MLX_PROMPT_MODE": "base-completion"}):
            self.assertTrue(_is_base_completion_model("fake-qwen35-ime", model_info))

        with patch.dict(os.environ, {"RAG_IME_MLX_PROMPT_MODE": "chat-json"}):
            self.assertFalse(_is_base_completion_model("fake-qwen35-ime-base", model_info))

    def test_dynamic_prompt_includes_request_type_and_rime_candidates(self) -> None:
        prompt = _build_mlx_dynamic_prompt(
            current_input="sj",
            recent_context="我想",
            max_candidates=3,
            request_type="pinyin_constrained_prediction",
            rime_candidates=("设计", "手机"),
        )

        self.assertIn("请求类型: pinyin_constrained_prediction", prompt)
        self.assertIn("Rime候选: 设计 / 手机", prompt)
        self.assertIn("拼音约束", prompt)
        self.assertIn("硬约束: 每个候选必须以这些 Rime 候选之一开头: 设计 / 手机", prompt)
        self.assertIn("只能输出 Rime候选 原文或它们的序号", _build_mlx_dynamic_prompt(
            current_input="sj",
            recent_context="我想",
            max_candidates=2,
            request_type="rime_reorder",
            rime_candidates=("设计", "手机"),
        ))
        self.assertIn("不要做拼音转汉字", _build_mlx_dynamic_prompt(
            current_input="",
            recent_context="我想",
            max_candidates=2,
            request_type="no_input_prediction",
        ))

    def test_chat_prompt_uses_qwen_non_thinking_assistant_prefix(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text='["跑通输入法","优化候选排序"]')
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想",
                max_candidates=2,
                max_tokens=12,
                temperature=0.15,
                top_p=0.85,
            )

        prompt = calls["prompts"][-1]
        self.assertIn(QWEN_NON_THINKING_ASSISTANT_PREFIX, prompt)
        self.assertNotIn("/no_think", prompt)
        self.assertNotIn("把流程跑通", prompt)
        self.assertNotIn("接入本地记忆", prompt)
        self.assertNotIn("验证 LLM 候选", prompt)
        self.assertEqual(payload["candidates"], ["跑通输入法", "优化候选排序"])

    def test_engine_uses_loaded_prompt_cache_for_streaming_generation(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text='["缓存候选","输入法"]')
        with patch.dict(sys.modules, modules):
            engine = MlxLmEngine("fake-qwen", enable_prompt_cache=True, prompt_cache_max_kv_size=4096)
            text = "".join(
                engine.stream_text(
                    current_input="RAG 输入法",
                    recent_context="本地记忆",
                    max_candidates=2,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                )
            )

        status = engine.prompt_cache_status()
        self.assertEqual(text, '["缓存候选","输入法"]')
        self.assertTrue(status["prepared"])
        self.assertTrue(status["usedForGeneration"])
        self.assertTrue(status["cacheFileReady"])
        self.assertEqual(status["maxKvSize"], 4096)
        self.assertEqual(status["hits"], 1)
        self.assertEqual(status["misses"], 0)
        self.assertEqual(calls["load_prompt_cache"], 1)
        self.assertEqual(calls["stream_generate"], 0)
        self.assertGreaterEqual(calls["generate_step"], 2)

    def test_engine_predict_prefers_next_token_logits_candidates(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text='["JSON候选"]',
            logits_tokens=["输入法候选", "本地记忆", "优化候选排序"],
        )
        with patch.dict(sys.modules, modules):
            engine = MlxLmEngine("fake-qwen")
            payload = engine.predict(
                current_input="现在",
                recent_context="本地记忆输入法",
                max_candidates=3,
                max_tokens=8,
                temperature=0.15,
                top_p=0.85,
            )

        self.assertEqual(payload["candidateMode"], "next-token-logits")
        self.assertEqual(payload["candidates"], ["输入法候选", "本地记忆", "优化候选排序"])
        self.assertEqual(payload["rawText"], "输入法候选 本地记忆 优化候选排序")
        self.assertEqual(payload["timing"]["candidateMode"], "next-token-logits")
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertEqual(payload["candidateScores"][0]["text"], "输入法候选")
        self.assertIn("probability", payload["candidateScores"][0])
        self.assertIn("latencyTrace", payload)
        self.assertEqual(payload["latencyTrace"]["requestType"], "generic_prediction")
        self.assertEqual(payload["latencyTrace"]["candidateCount"], 3)

    def test_engine_json_fallback_candidateizes_sentence_output(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text="我想设计一个候选展示方式，并补充来源诊断。")
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="我想",
                recent_context="我想",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertEqual(payload["candidates"][:3], ["设计", "设计一个", "设计一个候选"])
        self.assertNotIn("我想", "".join(payload["candidates"]))

    def test_no_input_prediction_uses_continuation_branches_when_logits_are_weak(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "跑通输入流程 优化候选排序 补齐来源诊断",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["跑通输入流程", "优化候选排序", "补齐来源诊断"])
        self.assertEqual([item["text"] for item in payload["candidateScores"]], payload["candidates"])
        self.assertEqual(payload["candidateScores"][0]["source"], "space-list")
        self.assertEqual(payload["timing"]["candidateMode"], "continuation-branches")
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertEqual([item["label"] for item in payload["timing"]["branches"]], ["space-list"])
        self.assertEqual(calls["sampler_calls"], 1)
        self.assertGreaterEqual(calls["sampler_max_tokens"][0], 12)
        self.assertIn("候选之间用单个空格分隔", calls["prompts"][-1])
        self.assertNotIn("输出 3 个候选 JSON 数组", calls["prompts"][-1])

    def test_no_input_prediction_uses_seeded_sequence_fork_for_top_logits_seeds(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "候选排序",
                "来源诊断",
                "上下文管理",
            ],
            logits_tokens=["优化", "补齐", "重建"],
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想把输入法候选质量再往上提一点",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "seeded-sequence-fork")
        self.assertEqual(payload["candidates"], ["优化候选排序", "补齐来源诊断", "重建上下文管理"])
        self.assertEqual([item["mode"] for item in payload["candidateScores"]], [
            "seeded-sequence-fork",
            "seeded-sequence-fork",
            "seeded-sequence-fork",
        ])
        self.assertEqual([item["seedText"] for item in payload["candidateScores"]], ["优化", "补齐", "重建"])
        self.assertEqual([item["seedTokenId"] for item in payload["candidateScores"]], [1000, 1001, 1002])
        self.assertEqual([item["branchRank"] for item in payload["candidateScores"]], [1, 2, 3])
        self.assertEqual([item["branchCount"] for item in payload["candidateScores"]], [3, 3, 3])
        self.assertEqual([item["label"] for item in payload["timing"]["branches"]], ["seed:优化", "seed:补齐", "seed:重建"])
        self.assertEqual([item["seedTokenId"] for item in payload["timing"]["branches"]], [1000, 1001, 1002])
        self.assertEqual([item["branchRank"] for item in payload["timing"]["branches"]], [1, 2, 3])
        self.assertTrue(payload["timing"]["kvFork"])
        self.assertTrue(payload["timing"]["sequenceFork"])
        self.assertEqual(payload["timing"]["fallbackReason"], "")
        self.assertEqual(payload["timing"]["seedReplayReason"], "top_logits_seed_sequence_fork")
        self.assertTrue(all(item["cacheForkSupported"] for item in payload["timing"]["branches"]))
        self.assertEqual(calls["sampler_calls"], 3)
        self.assertIn("种子候选", calls["prompts"][1])

    def test_seeded_sequence_fork_falls_back_to_prompt_replay_when_clone_fails(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "候选排序",
                "来源诊断",
                "上下文管理",
            ],
            logits_tokens=["优化", "补齐", "重建"],
        )
        with patch.dict(sys.modules, modules), patch(
            "rag_ime.mlx_predictor_server.deepcopy",
            side_effect=RuntimeError("clone failed"),
        ):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想把输入法候选质量再往上提一点",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "seeded-prompt-replay")
        self.assertFalse(payload["timing"]["kvFork"])
        self.assertFalse(payload["timing"]["sequenceFork"])
        self.assertEqual(payload["timing"]["fallbackReason"], "cache_clone_unsupported")
        self.assertEqual(calls["sampler_calls"], 3)

    def test_engine_health_exposes_selected_model_profile(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["质量候选"]')
        with patch.dict(sys.modules, modules):
            health = MlxLmEngine("fake-qwen", profile_id="qwen3_17b_ime_quality").health()

        self.assertEqual(health["modelProfile"]["id"], "qwen3_17b_ime_quality")
        self.assertEqual(health["modelProfile"]["lane"], "quality")
        self.assertTrue(health["modelProfile"]["appendOnly"])
        self.assertFalse(health["modelProfile"]["resident"])

    def test_engine_loads_local_tokenizers_backend_qwen_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            model_dir.joinpath("tokenizer.json").write_text("{}", encoding="utf-8")
            model_dir.joinpath("tokenizer_config.json").write_text(
                json.dumps({"tokenizer_class": "TokenizersBackend", "eos_token": "<|im_end|>"}),
                encoding="utf-8",
            )
            model_dir.joinpath("config.json").write_text(
                json.dumps({"model_type": "qwen3_5", "text_config": {"model_type": "qwen3_5_text"}}),
                encoding="utf-8",
            )

            mlx_lm = types.ModuleType("mlx_lm")

            def load(_model_id):
                raise ValueError("Tokenizer class TokenizersBackend does not exist")

            mlx_lm.load = load
            utils = types.ModuleType("mlx_lm.utils")
            utils.load_model = lambda path, lazy=False: ({"path": str(path), "lazy": lazy}, {"model_type": "qwen3_5"})

            tokenizers = types.ModuleType("tokenizers")

            class _FakeBackendTokenizer:
                @staticmethod
                def from_file(_path):
                    return _FakeBackendTokenizer()

                def encode(self, text):
                    return types.SimpleNamespace(ids=[ord(char) for char in text])

                def decode(self, ids):
                    return "".join(chr(int(item)) for item in ids)

                def token_to_id(self, token):
                    return 248046 if token == "<|im_end|>" else None

            tokenizers.Tokenizer = _FakeBackendTokenizer

            with patch.dict(sys.modules, {
                "mlx_lm": mlx_lm,
                "mlx_lm.utils": utils,
                "tokenizers": tokenizers,
            }):
                engine = MlxLmEngine(str(model_dir))

        self.assertEqual(engine.tokenizer.encode("你好"), [20320, 22909])
        self.assertEqual(engine.tokenizer.decode([20320, 22909]), "你好")
        self.assertEqual(engine.tokenizer.eos_token_id, 248046)

    def test_seeded_sequence_fork_explores_top_three_even_when_display_limit_is_one(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "候选排序",
                "来源诊断",
                "上下文管理",
            ],
            logits_tokens=["优化", "补齐", "重建"],
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想把输入法候选质量再往上提一点",
                max_candidates=1,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "seeded-sequence-fork")
        self.assertEqual(payload["candidates"], ["优化候选排序"])
        self.assertEqual(payload["timing"]["seedReplayBranchCount"], 3)
        self.assertEqual(payload["timing"]["seedReplayDisplayedCount"], 1)
        self.assertEqual(payload["timing"]["displayCandidateLimit"], 1)
        self.assertEqual([item["seedText"] for item in payload["timing"]["branches"]], ["优化", "补齐", "重建"])
        self.assertEqual(calls["sampler_calls"], 3)

    def test_no_input_seeded_sequence_fork_backfills_underfilled_seed_candidates(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "候选排序",
                "",
                "来源诊断",
                "补齐状态追踪 完成前台验证",
            ],
            logits_tokens=["优化", "补齐", "重建"],
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想把输入法候选质量再往上提一点",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "seeded-sequence-fork")
        self.assertEqual(payload["candidates"], ["优化候选排序", "重建来源诊断", "补齐状态追踪"])
        self.assertEqual([item["mode"] for item in payload["candidateScores"]], [
            "seeded-sequence-fork",
            "seeded-sequence-fork",
            "continuation-branches",
        ])
        self.assertTrue(payload["timing"]["underfilled"])
        self.assertEqual(payload["timing"]["seededCandidateCount"], 2)
        self.assertEqual(payload["timing"]["fallbackCandidateMode"], "continuation-branches")
        self.assertEqual(payload["timing"]["filledByFallbackCount"], 1)
        self.assertEqual(calls["sampler_calls"], 4)

    def test_no_input_prediction_does_not_use_hardcoded_domain_fallback(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "真实模型候选 优化上下文 连续预测",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="Felix3322/Wisdom-Weasel 需要参考上下文管理，删除后按实际输入预测",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["优化上下文", "连续预测"])
        self.assertNotIn("对照源码实现", payload["candidates"])
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertEqual(payload["timing"]["branches"][0]["label"], "space-list")

    def test_empty_hot_request_uses_continuation_branches_when_json_output_is_empty(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                '["M=HOT"]',
                "补充排序 稳定显示",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="RAG memory 候选应该先稳定出现，模型候选随后",
                max_candidates=2,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type="ime_hot",
            )

        self.assertEqual(payload["requestType"], "ime_hot")
        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["补充排序", "稳定显示"])
        self.assertEqual(payload["timing"]["fallbackReason"], "json_generation_empty_for_empty_input")

    def test_empty_hot_request_uses_rime_fallback_when_model_still_empty(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                '["M=HOT"]',
                "RAG memory",
                "RAG memory",
                "RAG memory",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="RAG memory 候选应该先稳定出现，模型候选随后",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type="ime_hot",
                rime_candidates=("补充", "排序", "状态"),
            )

        self.assertEqual(payload["candidateMode"], "rime-candidate-fallback")
        self.assertEqual(payload["candidates"], ["补充", "排序", "状态"])
        self.assertEqual([item["source"] for item in payload["candidateScores"]], [
            "rime-fallback",
            "rime-fallback",
            "rime-fallback",
        ])
        self.assertTrue(payload["timing"]["rimeFallback"])

    def test_empty_hot_request_backfills_underfilled_model_candidates_with_rime(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                '["M=HOT"]',
                "稳定显示",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="这个输入法目前最影响体验的是",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type="ime_hot",
                rime_candidates=("稳定性", "候选", "显示"),
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["稳定显示", "稳定性", "候选"])
        self.assertTrue(payload["timing"]["rimeBackfill"])
        self.assertEqual(payload["timing"]["rimeBackfillCount"], 2)

    def test_json_generation_backfills_underfilled_hot_rime_candidates(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["稳定性 / 候选 / 显示')
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="这个输入法目前最影响体验的是",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type="ime_hot",
                rime_candidates=("稳定性", "候选", "显示"),
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertEqual(payload["candidates"], ["稳定性", "显示", "候选"])
        self.assertTrue(payload["timing"]["rimeBackfill"])

    def test_post_commit_completion_uses_single_short_fast_path(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="马上优化。")
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="为什么本机推理加速后还这么慢",
                max_candidates=3,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
            )

        self.assertEqual(payload["candidateMode"], "realtime-post-commit")
        self.assertEqual(payload["candidates"], ["马上优化"])
        self.assertEqual(payload["timing"]["branchCount"], 0)
        self.assertEqual(payload["timing"]["maxTokens"], 12)
        self.assertEqual(calls["generate_step"], 1)
        self.assertEqual(calls["sampler_max_tokens"], [12])
        self.assertNotIn("直接从候选文本开始", calls["prompts"][0])

    def test_ime_post_commit_fast_path_does_not_backfill_rime_candidates(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="马上处理。")
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="参考这个实现",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_IME_POST_COMMIT,
                rime_candidates=("参考", "实现", "优化"),
            )

        self.assertEqual(payload["candidateMode"], "realtime-post-commit")
        self.assertEqual(payload["candidates"], ["马上处理"])
        self.assertEqual(payload["requestType"], PREDICTION_REQUEST_IME_POST_COMMIT)
        self.assertEqual(calls["sampler_max_tokens"], [12])

    def test_ime_post_commit_fast_path_uses_single_rime_fallback_when_model_empty(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="接下来")
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="这个输入法目前最影响体验的是",
                max_candidates=3,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_IME_POST_COMMIT,
                rime_candidates=("稳定性", "候选", "显示"),
            )

        self.assertEqual(payload["candidateMode"], "realtime-post-commit")
        self.assertEqual(payload["candidates"], ["稳定性"])
        self.assertEqual(payload["timing"]["branchCount"], 0)
        self.assertEqual(calls["generate_step"], 1)

    def test_no_input_prediction_falls_back_to_single_branch_when_space_list_is_empty(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "接下来",
                "补齐来源诊断。",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["补齐来源诊断"])
        self.assertEqual([item["label"] for item in payload["timing"]["branches"]], ["space-list", "lead"])
        self.assertEqual(calls["sampler_calls"], 2)
        self.assertIn("候选之间用单个空格分隔", calls["prompts"][1])
        self.assertIn("补全:", calls["prompts"][-1])

    def test_no_input_lead_branch_splits_bad_prefixed_model_sentence(self) -> None:
        candidates = _branch_continuation_candidates(
            "预测：\n基于预测优先的 RAG 输入法，将候选词库与生成模型深度耦合，实现输入时即时生成",
            current_input="",
            recent_context="我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
            max_candidate_chars=24,
            max_candidates=5,
        )

        self.assertEqual(candidates, ["将候选词库与生成模型深度耦合", "实现输入时即时生成"])

    def test_no_input_prediction_fills_partial_model_candidates(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "接下来",
                "预测：\n基于预测优先的 RAG 输入法，将候选词预测为输入框中的文本，并自动完成后续文本",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
                max_candidates=5,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(
            payload["candidates"],
            ["将候选词预测为输入框中的文本", "并自动完成后续文本"],
        )
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")

    def test_no_input_prediction_splits_single_model_continuation_when_many_requested(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "方案",
                "以优化用户决策",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想设计一个候选展示方式",
                max_candidates=5,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(
            payload["candidates"],
            ["以优化用户决策", "优化用户决策", "用户决策"],
        )
        self.assertNotIn("优化", payload["candidates"])
        self.assertNotIn("用户", payload["candidates"])
        self.assertGreaterEqual(len(payload["candidates"]), 3)
        self.assertEqual(payload["timing"]["branches"][-1]["label"], "model-output-splits")
        self.assertFalse(payload["timing"]["fallbackJson"])

    def test_no_input_prediction_filters_prompt_fragments_and_connector_words(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "接下来",
                "预测：RAG\n基于预测优先的 RAG 输入法能显著提升输入效率，通过智能预测用户意图，减少重复输入，同时",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
                max_candidates=5,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        joined = "\n".join(payload["candidates"])
        self.assertNotIn("预测：R", joined)
        self.assertNotIn("同时", payload["candidates"])
        self.assertEqual(
            payload["candidates"],
            ["能显著提升输入效率", "通过智能预测用户意图", "减少重复输入"],
        )
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")

    def test_no_input_prediction_filters_meta_description_without_domain_fallback(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "您正在阅读关于“中国”的说明性文本。",
                "您尝试了多种技术栈，需要进一步调整模型配置。",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我输入依旧没有 LLM 和 RAG 以及记忆",
                max_candidates=2,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], ["进一步调整模型配置"])
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")
        self.assertNotIn("您正在阅读", "".join(payload["candidates"]))
        self.assertNotIn("你正在输入", "".join(payload["candidates"]))

    def test_no_input_prediction_filters_short_fragments_without_project_fallback(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "方案",
                "我设",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想设计一个候选展示方式",
                max_candidates=2,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidates"], [])
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")

    def test_no_input_prediction_rejects_short_intent_fragments_and_continues_branching(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "方案",
                "我打算设",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="我想设计一个候选展示方式",
                max_candidates=5,
                max_tokens=32,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], [])
        self.assertEqual([item["label"] for item in payload["timing"]["branches"]], ["space-list", "lead"])
        self.assertEqual(calls["sampler_calls"], 2)
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")

    def test_no_input_prediction_filters_felix_meta_question_without_domain_fallback(self) -> None:
        modules, _calls = _fake_mlx_modules(
            generated_text=[
                "你正在看Felix的3322号项目吗",
                "您正在查看这个项目的实现。",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="",
                recent_context="Felix3322/Wisdom-Weasel 预测和上下文管理要考虑删除后的实际输入",
                max_candidates=5,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )

        self.assertEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(payload["candidates"], [])
        self.assertFalse(payload["timing"]["fallbackJson"])
        self.assertNotEqual(payload["timing"]["branches"][-1]["label"], "domain-fallback")
        self.assertNotIn("你正在看", "".join(payload["candidates"]))

    def test_pinyin_constrained_prediction_does_not_use_free_continuation_branches(self) -> None:
        modules, calls = _fake_mlx_modules(
            generated_text=[
                "设计一个候选展示方式。",
                "接入本地记忆。",
            ]
        )
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="sj",
                recent_context="我想",
                max_candidates=3,
                max_tokens=16,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_PINYIN_CONSTRAINED,
                rime_candidates=("设计", "手机"),
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertNotEqual(payload["candidateMode"], "continuation-branches")
        self.assertEqual(calls["sampler_calls"], 1)

    def test_engine_rime_reorder_fallback_stays_inside_rime_pool(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text="[2, 1]")
        with patch.dict(sys.modules, modules):
            payload = MlxLmEngine("fake-qwen").predict(
                current_input="sj",
                recent_context="我想",
                max_candidates=3,
                max_tokens=8,
                temperature=0.15,
                top_p=0.85,
                request_type=PREDICTION_REQUEST_RIME_REORDER,
                rime_candidates=("手机", "设计", "世界"),
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertEqual(payload["candidates"], ["设计", "手机"])

    def test_base_model_uses_plain_completion_prefix_not_chat_prompt(self) -> None:
        modules, calls = _fake_mlx_modules(generated_text="需要把输入法流程跑通。")
        with tempfile.TemporaryDirectory(prefix="Qwen3-0.6B-Base-") as tmp, patch.dict(sys.modules, modules):
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3ForCausalLM"],
                        "model_type": "qwen3",
                        "hidden_size": 1024,
                        "num_hidden_layers": 28,
                    }
                ),
                encoding="utf-8",
            )
            engine = MlxLmEngine(str(model_dir))
            payload = engine.predict(
                current_input="我现在这个候选词根本不像 LLM 输出的，都",
                recent_context="历史参考(禁止复读): 补后端测试 当前上下文: 我现在这个候选词根本不像 LLM 输出的，都",
                max_candidates=3,
                max_tokens=12,
                temperature=0.05,
                top_p=0.8,
            )

        self.assertEqual(payload["candidateMode"], "base-completion")
        self.assertEqual(payload["candidates"], ["需要把输入法流程跑通"])
        prompt = calls["prompts"][-1]
        self.assertIn("我现在这个候选词根本不像 LLM 输出的，都", prompt)
        self.assertNotIn("<|im_start|>", prompt)
        self.assertNotIn("已上屏上下文", prompt)
        self.assertNotIn("补后端测试", prompt)

    def test_qwen3_chat_template_model_filters_prompt_example_leaks(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["把流程跑通","接入本地记忆","上屏文字","当前拼音或参考候选","接龙"]')
        with tempfile.TemporaryDirectory(prefix="Qwen3-0.6B-4bit-") as tmp, patch.dict(sys.modules, modules):
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3ForCausalLM"],
                        "model_type": "qwen3",
                        "hidden_size": 1024,
                        "num_hidden_layers": 28,
                    }
                ),
                encoding="utf-8",
            )
            (model_dir / "tokenizer_config.json").write_text(
                json.dumps({"chat_template": "{% if enable_thinking is false %}<think></think>{% endif %}"}),
                encoding="utf-8",
            )
            payload = MlxLmEngine(str(model_dir)).predict(
                current_input="",
                recent_context="我想",
                max_candidates=5,
                max_tokens=12,
                temperature=0.15,
                top_p=0.85,
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["timing"]["candidateMode"], "json-generation")

    def test_stream_decode_skips_replacement_character_intermediate_chunks(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text="验证候选")
        with patch.dict(sys.modules, modules):
            engine = MlxLmEngine("fake-qwen")
            real_decode = engine.tokenizer.decode

            def decode(tokens):
                if len(tokens) == 2:
                    return "验\ufffd"
                return real_decode(tokens)

            engine.tokenizer.decode = decode
            text = "".join(
                engine.stream_text(
                    current_input="",
                    recent_context="测试",
                    max_candidates=1,
                    max_tokens=8,
                    temperature=0.15,
                    top_p=0.85,
                )
            )

        self.assertEqual(text, "验证候选")

    def test_stream_generation_stops_before_chat_template_echo(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["本地记忆"]<|im_end|>\n<|endoftext|>Human: 请继续')
        with patch.dict(sys.modules, modules):
            text = "".join(
                MlxLmEngine("fake-qwen").stream_text(
                    current_input="",
                    recent_context="我想",
                    max_candidates=1,
                    max_tokens=48,
                    temperature=0.15,
                    top_p=0.85,
                )
            )

        self.assertEqual(text, '["本地记忆"]')
        self.assertNotIn("<|im_end|>", text)
        self.assertNotIn("Human:", text)

    def test_health_reports_prepared_prompt_cache_without_claiming_generation_use(self) -> None:
        server, thread = _start_fake_server()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            _stop_server(server, thread)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["promptCache"]["enabled"])
        self.assertTrue(payload["promptCache"]["prepared"])
        self.assertFalse(payload["promptCache"]["usedForGeneration"])
        self.assertEqual(payload["promptCache"]["stablePrefixTokens"], 5)
        self.assertEqual(payload["promptCache"]["reason"], "prepared_only_streaming_generation_not_cached_yet")

    def test_engine_health_reports_local_text_only_model_info(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["本地"]')
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-model-") as tmp, patch.dict(sys.modules, modules):
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3ForCausalLM"],
                        "model_type": "qwen3",
                        "hidden_size": 1024,
                        "intermediate_size": 3072,
                        "num_attention_heads": 16,
                        "num_hidden_layers": 28,
                        "num_key_value_heads": 8,
                        "vocab_size": 151936,
                        "quantization": {"bits": 4, "group_size": 64},
                    }
                ),
                encoding="utf-8",
            )
            payload = MlxLmEngine(str(model_dir)).health()

        info = payload["modelInfo"]
        self.assertTrue(info["localPath"])
        self.assertTrue(info["configPresent"])
        self.assertTrue(info["textOnly"])
        self.assertFalse(info["hasVisionConfig"])
        self.assertEqual(info["architecture"], "Qwen3ForCausalLM")
        self.assertEqual(info["vocabSize"], 151936)
        self.assertEqual(info["quantization"]["bits"], 4)
        self.assertEqual(len(payload["modelFingerprint"].removeprefix("sha256:")), 64)
        self.assertTrue(payload["capabilities"]["textOnlyModel"])
        self.assertTrue(payload["capabilities"]["seededPromptReplay"])
        self.assertTrue(payload["capabilities"]["kvFork"])
        self.assertTrue(payload["capabilities"]["sequenceFork"])
        self.assertTrue(payload["capabilities"]["continuationBranches"])

    def test_engine_health_flags_local_vision_language_model(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["本地"]')
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-model-") as tmp, patch.dict(sys.modules, modules):
            model_dir = Path(tmp)
            (model_dir / "model.safetensors").write_bytes(b"fake")
            (model_dir / "config.json").write_text(
                json.dumps(
                    {
                        "architectures": ["Qwen3_5ForConditionalGeneration"],
                        "model_type": "qwen3_5",
                        "text_config": {
                            "model_type": "qwen3_5_text",
                            "hidden_size": 1024,
                            "num_hidden_layers": 24,
                            "vocab_size": 248320,
                        },
                        "vision_config": {"model_type": "qwen3_5", "hidden_size": 768},
                        "quantization": {"bits": 4, "group_size": 64},
                    }
                ),
                encoding="utf-8",
            )
            payload = MlxLmEngine(str(model_dir)).health()

        info = payload["modelInfo"]
        self.assertFalse(info["textOnly"])
        self.assertTrue(info["hasVisionConfig"])
        self.assertEqual(info["modelType"], "qwen3_5")
        self.assertEqual(info["textModelType"], "qwen3_5_text")
        self.assertEqual(info["vocabSize"], 248320)
        self.assertFalse(payload["capabilities"]["textOnlyModel"])

    def test_predict_stream_includes_prompt_cache_status_on_done_event(self) -> None:
        server, thread = _start_fake_server()
        try:
            body = json.dumps(
                {
                    "model": "fake-mlx-qwen",
                    "currentInput": "RAG 输入法",
                    "recentContext": "调试上下文",
                    "maxCandidates": 2,
                    "maxTokens": 8,
                    "stream": True,
                    "requestType": "pinyin_constrained_prediction",
                    "rimeCandidates": ["本地记忆", "输入法"],
                    "contextFingerprint": "ctx123456789abcd",
                    "currentInputFingerprint": "input1234567890",
                    "stablePrefixHash": "prefix123456789",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/predict-stream",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                events = [json.loads(line.decode("utf-8")) for line in response if line.strip()]
        finally:
            _stop_server(server, thread)

        self.assertEqual(events[0]["delta"], '["本地记忆"')
        candidate_events = [item for item in events if item.get("event") == "candidate_delta"]
        self.assertGreaterEqual(len(candidate_events), 1)
        self.assertEqual(candidate_events[0]["candidate"], "本地记忆")
        self.assertTrue(events[-1]["done"])
        self.assertEqual(events[-1]["candidates"], ["本地记忆", "输入法候选"])
        self.assertIn("latencyTrace", events[-1])
        self.assertEqual(events[-1]["requestType"], "pinyin_constrained_prediction")
        self.assertTrue(events[-1]["promptCache"]["prepared"])
        self.assertFalse(events[-1]["promptCache"]["usedForGeneration"])
        self.assertEqual(events[-1]["requestMeta"]["contextFingerprint"], "ctx123456789abcd")
        self.assertEqual(events[-1]["requestMeta"]["stablePrefixHash"], "prefix123456789")

    def test_predict_stream_write_stops_cleanly_when_client_closes(self) -> None:
        handler_cls = make_mlx_predictor_handler(_FakeMlxEngine())
        handler = handler_cls.__new__(handler_cls)
        handler.wfile = _BrokenPipeWriter()

        self.assertFalse(handler._write_json_line({"delta": "本地"}))

    def test_predict_returns_stable_error_json_instead_of_empty_reply(self) -> None:
        server, thread = _start_fake_server(_RaisingMlxEngine())
        try:
            body = json.dumps(
                {
                    "model": "fake-mlx-qwen",
                    "current_input": "我们继续",
                    "recent_context": "今天测试输入法连续预测",
                    "max_candidates": 1,
                    "request_type": "post_commit_completion",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/predict",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            _stop_server(server, thread)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidateMode"], "error")
        self.assertEqual(payload["requestType"], "post_commit_completion")
        self.assertEqual(payload["error"], "ValueError")
        self.assertIn("latencyTrace", payload)


def _start_fake_server(engine=None):
    handler = make_mlx_predictor_handler(engine or _FakeMlxEngine())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


class _FakeToken:
    def __init__(self, value: int):
        self.value = value

    def item(self) -> int:
        return self.value


class _FakeTokenizer:
    def __init__(self, decode_map: dict[int, str] | None = None) -> None:
        self.decode_map = decode_map or {}
        self.eos_token_id = 0
        self.eos_token_ids = {0}

    def encode(self, text: str):
        return [ord(char) for char in text]

    def decode(self, tokens):
        values = [int(token) for token in tokens]
        if len(values) == 1 and values[0] in self.decode_map:
            return self.decode_map[values[0]]
        return "".join(chr(value) for value in values)


class _FakeStreamResponse:
    def __init__(self, text: str):
        self.text = text


def _fake_mlx_modules(*, generated_text: str | list[str], logits_tokens: list[str] | None = None):
    calls = {
        "batch_generate": 0,
        "batch_prompts": [],
        "batch_prompt_caches": [],
        "generate_step": 0,
        "load_prompt_cache": 0,
        "stream_generate": 0,
        "prompts": [],
        "sampler_max_tokens": [],
        "sampler_calls": 0,
    }
    generated_texts = generated_text if isinstance(generated_text, list) else [generated_text]
    logits_token_ids = {
        token: 1000 + index for index, token in enumerate(logits_tokens or [])
    }
    tokenizer = _FakeTokenizer({token_id: token for token, token_id in logits_token_ids.items()})

    mlx_lm = types.ModuleType("mlx_lm")

    def load(model_id: str):
        return {"model_id": model_id}, tokenizer

    def stream_generate(*args, **kwargs):
        calls["stream_generate"] += 1
        yield _FakeStreamResponse("fallback")

    mlx_lm.load = load
    mlx_lm.stream_generate = stream_generate

    generate = types.ModuleType("mlx_lm.generate")

    def batch_generate(model, tokenizer, prompts, prompt_caches=None, max_tokens=128, **kwargs):
        calls["batch_generate"] += 1
        calls["batch_prompts"] = [list(prompt) for prompt in prompts]
        calls["batch_prompt_caches"] = list(prompt_caches or [])
        texts = [
            generated_texts[min(index, len(generated_texts) - 1)]
            for index in range(len(prompts))
        ]
        stats = types.SimpleNamespace(
            prompt_tokens=0,
            prompt_time=0.0,
            generation_tokens=sum(len(text) for text in texts),
            generation_time=0.001,
            peak_memory=0.0,
        )
        return types.SimpleNamespace(texts=texts, stats=stats)

    def generate_step(prompt, model, max_tokens: int, prompt_cache=None, sampler=None):
        calls["generate_step"] += 1
        prompt_text = "".join(chr(int(token)) for token in prompt) if isinstance(prompt, list) else ""
        calls["prompts"].append(prompt_text)
        if sampler is None and "直接从候选文本开始" in prompt_text and logits_tokens:
            logprobs = _fake_logprobs([logits_token_ids[token] for token in logits_tokens])
            yield _FakeToken(logits_token_ids[logits_tokens[0]]), logprobs
            return
        if sampler is None:
            yield _FakeToken(0), None
            return
        calls["sampler_max_tokens"].append(max_tokens)
        sampler_index = calls["sampler_calls"]
        calls["sampler_calls"] += 1
        text = generated_texts[min(sampler_index, len(generated_texts) - 1)]
        for char in text:
            yield _FakeToken(ord(char)), None

    generate.generate_step = generate_step
    generate.batch_generate = batch_generate

    cache = types.ModuleType("mlx_lm.models.cache")

    def make_prompt_cache(model, **kwargs):
        return {"model": model, "kwargs": kwargs}

    def save_prompt_cache(file_name: str, cache_obj, metadata=None):
        with open(file_name, "wb") as handle:
            handle.write(b"fake-cache")

    def load_prompt_cache(file_name: str):
        calls["load_prompt_cache"] += 1
        return {"loaded": file_name}

    cache.make_prompt_cache = make_prompt_cache
    cache.save_prompt_cache = save_prompt_cache
    cache.load_prompt_cache = load_prompt_cache

    models = types.ModuleType("mlx_lm.models")
    models.cache = cache

    sample_utils = types.ModuleType("mlx_lm.sample_utils")

    def make_sampler(temp: float, top_p: float, top_k: int = 0):
        return {"temp": temp, "top_p": top_p, "top_k": top_k}

    sample_utils.make_sampler = make_sampler

    mlx = types.ModuleType("mlx")
    core = types.ModuleType("mlx.core")
    core.array = lambda tokens: list(tokens)
    mlx.core = core

    return (
        {
            "mlx_lm": mlx_lm,
            "mlx_lm.generate": generate,
            "mlx_lm.models": models,
            "mlx_lm.models.cache": cache,
            "mlx_lm.sample_utils": sample_utils,
            "mlx": mlx,
            "mlx.core": core,
        },
        calls,
    )


def _fake_logprobs(token_ids: list[int]) -> list[float]:
    logprobs = [-20.0] * (max(token_ids) + 1)
    for rank, token_id in enumerate(token_ids):
        logprobs[token_id] = -0.05 - rank
    return logprobs


if __name__ == "__main__":
    unittest.main()
