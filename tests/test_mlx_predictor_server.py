from __future__ import annotations

import json
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
    _build_mlx_dynamic_prompt,
    QWEN_NON_THINKING_ASSISTANT_PREFIX,
    _normalize_prediction_request,
    make_mlx_predictor_handler,
)
from rag_ime.predictor import (
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
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


class MlxPredictorServerTests(unittest.TestCase):
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
                "跑通输入流程。",
                "接入本地记忆。",
                "优化候选排序。",
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
        self.assertEqual(payload["candidates"], ["跑通输入流程", "接入本地", "优化候选排序"])
        self.assertEqual(payload["timing"]["candidateMode"], "continuation-branches")
        self.assertEqual([item["label"] for item in payload["timing"]["branches"]], ["lead", "diverse-short", "diverse-phrase"])
        self.assertEqual(calls["sampler_calls"], 3)

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

    def test_qwen3_chat_template_model_uses_chat_json_prompt_mode(self) -> None:
        modules, _calls = _fake_mlx_modules(generated_text='["把流程跑通","接入本地记忆"]')
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
                max_candidates=2,
                max_tokens=12,
                temperature=0.15,
                top_p=0.85,
            )

        self.assertEqual(payload["candidateMode"], "json-generation")
        self.assertEqual(payload["candidates"], ["把流程跑通", "接入本地记忆"])
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
        self.assertTrue(payload["capabilities"]["textOnlyModel"])
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
                    "recentContext": "本地记忆",
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
        self.assertTrue(events[-1]["done"])
        self.assertEqual(events[-1]["candidates"], ["本地记忆", "输入法候选"])
        self.assertEqual(events[-1]["requestType"], "pinyin_constrained_prediction")
        self.assertTrue(events[-1]["promptCache"]["prepared"])
        self.assertFalse(events[-1]["promptCache"]["usedForGeneration"])
        self.assertEqual(events[-1]["requestMeta"]["contextFingerprint"], "ctx123456789abcd")
        self.assertEqual(events[-1]["requestMeta"]["stablePrefixHash"], "prefix123456789")


def _start_fake_server():
    handler = make_mlx_predictor_handler(_FakeMlxEngine())
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
        "generate_step": 0,
        "load_prompt_cache": 0,
        "stream_generate": 0,
        "prompts": [],
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
        sampler_index = calls["sampler_calls"]
        calls["sampler_calls"] += 1
        text = generated_texts[min(sampler_index, len(generated_texts) - 1)]
        for char in text:
            yield _FakeToken(ord(char)), None

    generate.generate_step = generate_step

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

    def make_sampler(temp: float, top_p: float):
        return {"temp": temp, "top_p": top_p}

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
