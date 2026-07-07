from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from rag_ime.cli import main
from rag_ime.predictor import (
    CooldownPredictionProvider,
    MlxPredictionConfig,
    MlxPredictionServiceProvider,
    NullPredictionProvider,
    OllamaPredictionProvider,
    OpenAICompatiblePredictionConfig,
    OpenAICompatiblePredictionProvider,
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_RIME_REORDER,
    PREDICTION_REQUEST_SELECTED_TEXT_RAG,
    PredictionBenchmarkCase,
    benchmark_prediction_provider,
    build_selected_text_rag_prompt,
    doctor_prediction_provider,
    parse_ime_prediction_candidates,
    parse_prediction_candidates,
    parse_selected_text_rag_candidates,
    prediction_provider_from_env,
    prediction_provider_status,
    _filter_repeated_input_candidates,
    _filter_low_value_ime_candidates,
    _finalize_mlx_payload_candidates,
    _parse_streaming_prediction_candidates,
)


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}
    captured_headers: dict[str, str] = {}
    response_content = "本地记忆 输入法候选 RAG上下文 本地记忆"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps(
            {"data": [{"id": "Qwen3-0.6B"}, {"id": "Qwen3-1.7B"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOpenAIHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        _MockOpenAIHandler.captured_headers = {key: value for key, value in self.headers.items()}
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": _MockOpenAIHandler.response_content,
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps(
            {"models": [{"name": "qwen3.5:0.8b"}, {"name": "qwen2.5:0.5b"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOllamaHandler.captured_path = self.path
        _MockOllamaHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "本地记忆 输入法候选 RAG候选",
                },
                "done": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []
    captured_payloads: list[dict[str, object]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps(
            {"models": [{"name": "qwen3.5:0.8b"}, {"name": "qwen3.5:2b"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockOllamaMatrixHandler.seen_models.append(model)
        _MockOllamaMatrixHandler.captured_payloads.append(payload)
        content = '["本地记忆","输入法候选"]' if model == "qwen3.5:0.8b" else '["无关候选"]'
        body = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "done": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaStreamingHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOllamaStreamingHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        chunks = [
            {"message": {"role": "assistant", "content": '["本地记忆"'}},
            {"message": {"role": "assistant", "content": ',"输入法候选"]'}, "done": True},
        ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaStreamingMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []
    captured_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockOllamaStreamingMatrixHandler.seen_models.append(model)
        _MockOllamaStreamingMatrixHandler.captured_payloads.append(payload)
        if model == "qwen3.5:0.8b-mlx":
            chunks = [
                {"message": {"role": "assistant", "content": '["本地记忆"'}},
                {"message": {"role": "assistant", "content": ',"输入法候选"]'}, "done": True},
            ]
        else:
            chunks = [
                {"message": {"role": "assistant", "content": '["'}, "done": True},
            ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaEmptyStreamingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        body = json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode("utf-8") + b"\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaUnparsedStreamingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        chunks = [
            {"message": {"role": "assistant", "content": '["'}},
            {"message": {"role": "assistant", "content": ""}, "done": True},
        ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockMlxHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}
    health_payload: dict[str, object] = {}
    stream_chunks: list[dict[str, object]] | None = None

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "mlx-qwen3.5-0.8b"}]}, ensure_ascii=False).encode("utf-8")
        elif self.path == "/health":
            payload = _MockMlxHandler.health_payload or {
                "ok": True,
                "provider": "mlx-lm",
                "model": "mlx-qwen3.5-0.8b",
                "modelLoaded": True,
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockMlxHandler.captured_path = self.path
        _MockMlxHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/predict-stream":
            chunks = _MockMlxHandler.stream_chunks or [
                {"delta": '["本地记忆"'},
                {"delta": ',"输入法候选"]'},
                {"done": True, "candidates": ["本地记忆", "输入法候选"], "totalMs": 19},
            ]
            body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return
        if self.path != "/predict":
            self.send_error(404)
            return
        body = json.dumps(
            {
                "ok": True,
                "candidates": ["本地记忆", "输入法候选", "RAG上下文"],
                "rawText": '["本地记忆","输入法候选","RAG上下文"]',
                "candidateMode": "next-token-logits",
                "candidateScores": [{"text": "本地记忆", "tokenId": 42, "probability": 0.42}],
                "totalMs": 17,
                "promptCache": {"enabled": False},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockCompletionHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockCompletionHandler.captured_path = self.path
        _MockCompletionHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(
            {
                "choices": [
                    {"text": "<think>分析过程不应该进入候选</think>\n本地记忆"},
                    {"text": "输入法候选"},
                    {"text": "RAG上下文"},
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockModelMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockModelMatrixHandler.seen_models.append(model)
        content = "本地记忆 输入法候选" if model == "qwen3.5:0.8b" else "无关候选"
        body = json.dumps(
            {"choices": [{"message": {"content": content}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class PredictionProviderTests(unittest.TestCase):
    def test_parse_prediction_candidates_deduplicates_and_limits(self) -> None:
        parsed = parse_prediction_candidates("1. 本地记忆  本地记忆，RAG候选 / 输出法; 这是一个非常非常非常长的候选短语", max_candidates=3)
        self.assertEqual(parsed, ["本地记忆", "RAG候选", "输出法"])

    def test_parse_prediction_candidates_strips_thinking_and_json(self) -> None:
        parsed = parse_prediction_candidates(
            '<think>先分析一下</think> ["本地记忆", "RAG候选", "输入法候选"]',
            max_candidates=3,
        )
        self.assertEqual(parsed, ["本地记忆", "RAG候选", "输入法候选"])

    def test_parse_prediction_candidates_extracts_qwen_json_before_special_tokens(self) -> None:
        parsed = parse_prediction_candidates(
            '<think>\n\n</think>\n\n["现在", "现状"]<|im_end|>\n<|endoftext|><|im_start|>user\n',
            max_candidates=3,
        )
        self.assertEqual(parsed, ["现在", "现状"])

    def test_parse_prediction_candidates_extracts_unfinished_qwen_json_strings(self) -> None:
        parsed = parse_prediction_candidates(
            '<think>\n\n</think>\n\n["接入本地记忆","验证 LLM 候选","预测流程完成","部署 RAG 组件',
            max_candidates=4,
        )
        self.assertEqual(parsed, ["接入本地记忆", "验证 LLM 候选", "预测流程完成"])

    def test_selected_text_rag_prompt_mentions_ime_candidate_constraints(self) -> None:
        prompt = build_selected_text_rag_prompt(
            selected_text="候选一会弹出，一会输入几个字后又不预测",
            evidence_items=("trigger policy 和 sidecar latency 是排查入口",),
            max_candidates=3,
        )

        self.assertIn("输入法 Active RAG", prompt)
        self.assertIn("只输出 JSON 字符串数组", prompt)
        self.assertIn("不要解释", prompt)
        self.assertIn("不要输出 Markdown", prompt)
        self.assertIn("不要复读选区原文", prompt)

    def test_selected_text_rag_parser_accepts_json_candidates(self) -> None:
        parsed = parse_selected_text_rag_candidates(
            '["候选消失排查路径","本地优先","根据上述可以继续"]',
            selected_text="候选一会弹出，一会输入几个字后又不预测",
            max_candidates=3,
        )

        self.assertEqual(parsed, ["候选消失排查路径", "本地优先"])

    def test_selected_text_rag_parser_accepts_line_candidates(self) -> None:
        parsed = parse_selected_text_rag_candidates(
            "1. 候选显示状态机\n2. StableCandidateSnapshot\n3. 不要解释",
            selected_text="我想优化候选栏",
            max_candidates=3,
        )

        self.assertEqual(parsed, ["候选显示状态机", "StableCandidateSnapshot"])

    def test_selected_text_rag_filters_generic_filler_and_prompt_echo(self) -> None:
        parsed = parse_selected_text_rag_candidates(
            '["RAG","输入法候选","不要解释","选区 RAG 助手","候选稳定"]',
            selected_text="选区 RAG 助手会不会偷读我选中的内容",
            max_candidates=5,
        )

        self.assertEqual(parsed, ["候选稳定"])

    def test_ime_parser_routes_selected_text_rag_request(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["候选一会弹出，一会输入几个字后又不预测","候选消失排查路径"]',
            current_input="候选一会弹出，一会输入几个字后又不预测",
            request_type=PREDICTION_REQUEST_SELECTED_TEXT_RAG,
            max_candidates=2,
        )

        self.assertEqual(parsed, ["候选消失排查路径"])

    def test_parse_ime_prediction_candidates_turns_sentence_into_short_continuations(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "我想设计一个候选展示方式，并补充来源诊断。",
            current_input="我想",
            recent_context="我想",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=4,
        )

        self.assertEqual(parsed[:4], ["设计", "设计一个", "设计一个候选", "设计一个候选展示"])
        self.assertNotIn("我想", "".join(parsed))
        self.assertTrue(all(2 <= len(item) <= 16 for item in parsed))

    def test_parse_ime_prediction_candidates_skips_explanation_and_uses_numbered_items(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "好的，我给出候选：1. 设计一个候选展示方式 2. 接入本地记忆 3. 优化候选排序",
            current_input="我想",
            recent_context="我想",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed, ["设计一个候选展示方式", "优化候选排序"])

    def test_parse_ime_prediction_candidates_skips_filler_clause_before_useful_continuation(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "好的，我会继续优化候选排序，并补齐来源诊断。",
            current_input="",
            recent_context="这个输入法现在需要",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed[:3], ["优化", "优化候选", "优化候选排序"])

    def test_parse_ime_prediction_candidates_strips_analysis_preface(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "基于上述分析，我们开始整理项目文档",
            current_input="",
            recent_context="现在完整整理本项目，包括文档、进度和反馈问题",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed, [])
        self.assertNotIn("基于", "".join(parsed))
        self.assertNotIn("我们开始", "".join(parsed))

    def test_parse_ime_prediction_candidates_filters_prompt_example_leaks(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["预测优先个人记忆输入法", "个人记忆输入法预测", "把流程跑通", "接入本地记忆"]',
            current_input="",
            recent_context="我想做一个预测优先的个人记忆输入法",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=4,
        )

        self.assertEqual(parsed, [])

    def test_parse_ime_prediction_candidates_rejects_project_prompt_examples(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["优化 MLX 小模型候选","接入本地记忆","验证 LLM 候选","调试流程"]<|im_end|>',
            current_input="",
            recent_context="我想把这个输入法流程跑通，接入本地记忆和 RAG，优化 MLX 小模型候选。",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=4,
        )

        self.assertEqual(parsed, [])

    def test_parse_ime_prediction_candidates_filters_context_echoes(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["我想","我想的","补齐来源诊断"]',
            current_input="",
            recent_context="我想",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed, ["补齐来源诊断"])

    def test_parse_ime_prediction_candidates_trims_context_prefix_overlap(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["建议采用分层架构", "建议增加缓存机制"]',
            current_input="",
            recent_context="我觉得这个模块建议",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed, ["采用分层架构", "增加缓存机制"])
        self.assertFalse(any(item.startswith("建议") for item in parsed))

    def test_parse_ime_prediction_candidates_filters_context_reorder_echoes(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["今天继续使用输入", "我们开始"]',
            current_input="",
            recent_context="今天我们继续调输入法",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=3,
        )

        self.assertEqual(parsed, ["我们开始"])

    def test_parse_ime_prediction_candidates_filters_incomplete_short_fragments(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["将进入下", "讨论Felix的", "开始描述Feli", "我们开始"]',
            current_input="",
            recent_context="这个输入法的核心流程已经跑通，接下来",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=4,
        )

        self.assertEqual(parsed, ["我们开始"])

    def test_parse_ime_prediction_candidates_keeps_complete_medium_continuation(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "接下来，我将开始分析 Felix 生命周期中的关键节点。",
            current_input="",
            recent_context="我已经看完 Felix 的候选生命周期，下一步",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=1,
        )

        self.assertEqual(parsed, ["开始分析Felix生命周期中的关键节点"])

    def test_parse_ime_prediction_candidates_rejects_model_field_names(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["今天","candidate","cand","Model de","想...Mode","上屏文字","当前拼音或参考候选","接龙","继续吃饭"]',
            current_input="",
            recent_context="今天晚上我们去吃",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=9,
        )

        self.assertEqual(parsed, ["继续吃饭"])

    def test_parse_ime_prediction_candidates_filters_single_topic_debug_word(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["调试","优化候选排序"]',
            current_input="",
            recent_context="这个输入法预测感觉随机，需要",
            request_type=PREDICTION_REQUEST_NO_INPUT,
            max_candidates=2,
        )

        self.assertEqual(parsed, ["优化候选排序"])

    def test_parse_ime_prediction_candidates_keeps_rime_reorder_inside_pool(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '我建议顺序是 [2, 1]，不要输出 "随便发挥"',
            request_type=PREDICTION_REQUEST_RIME_REORDER,
            rime_candidates=("手机", "设计", "世界"),
            max_candidates=3,
        )

        self.assertEqual(parsed, ["设计", "手机"])

    def test_parse_ime_prediction_candidates_filters_mojibake_and_splits_rime_concat(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["设计手机世界数据", "验证 LLM �选", "设计一个手机应用"]',
            current_input="sj",
            request_type="pinyin_constrained_prediction",
            rime_candidates=("设计", "手机", "世界", "数据"),
            max_candidates=5,
        )

        self.assertEqual(parsed[:4], ["设计", "手机", "世界", "数据"])
        self.assertNotIn("验证 LLM �选", parsed)

    def test_parse_ime_prediction_candidates_falls_back_when_mlx_returns_pinyin_only(self) -> None:
        parsed = parse_ime_prediction_candidates(
            "[xiàng]",
            current_input="xiang",
            recent_context="我",
            request_type=PREDICTION_REQUEST_PINYIN_CONSTRAINED,
            rime_candidates=("想", "先", "向"),
            max_candidates=5,
        )

        self.assertEqual(parsed[:3], ["想继续", "想一下", "想看看"])
        self.assertTrue(all(len(item) >= 2 for item in parsed))

    def test_pinyin_fallback_candidates_carry_full_pinyin_metadata(self) -> None:
        provider = MlxPredictionServiceProvider(
            MlxPredictionConfig(
                base_url="http://127.0.0.1:9",
                model="unused",
            )
        )
        provider._predict_payload = lambda **_: {  # type: ignore[method-assign]
            "ok": True,
            "rawText": "[xiàng]",
            "candidates": ["想继续", "想一下"],
            "requestType": PREDICTION_REQUEST_PINYIN_CONSTRAINED,
        }

        predictions = provider.predict(
            current_input="xiang",
            recent_context="我",
            request_type=PREDICTION_REQUEST_PINYIN_CONSTRAINED,
            rime_candidates=("想", "先", "向"),
            max_candidates=3,
        )

        self.assertEqual([item.text for item in predictions], ["想继续", "想一下"])
        self.assertEqual(predictions[0].metadata["full_pinyin"][0], "xiang")

    def test_parse_ime_prediction_candidates_keeps_ascii_rime_candidates_for_code_lane(self) -> None:
        parsed = parse_ime_prediction_candidates(
            '["model", "module", "memory", "mlx"]',
            current_input="model",
            recent_context="这个输入法主要服务 vibe coding",
            request_type=PREDICTION_REQUEST_PINYIN_CONSTRAINED,
            rime_candidates=("model", "module", "memory", "mlx"),
            max_candidates=4,
        )

        self.assertEqual(parsed, ["module", "memory", "mlx"])

    def test_openai_compatible_provider_returns_short_ranked_predictions(self) -> None:
        _MockOpenAIHandler.response_content = "本地记忆 输入法候选 RAG上下文 本地记忆"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="Qwen3-0.6B",
                    timeout_s=1.0,
                    max_tokens=8,
                    provider_name="mock-qwen",
                    extra_body={"seed": 7, "chat_template_kwargs": {"enable_thinking": False}},
                    extra_headers={"X-RAG-IME-Test": "extra-header"},
                )
            )
            predictions = provider.predict(
                current_input="rag",
                recent_context="输入法需要本地记忆和候选预测",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.assertEqual([item.text for item in predictions], ["本地记忆", "RAG上下文"])
        self.assertEqual(predictions[0].provider_name, "mock-qwen")
        self.assertGreaterEqual(predictions[0].latency_ms, 0)
        self.assertEqual(_MockOpenAIHandler.captured_payload["model"], "Qwen3-0.6B")
        self.assertEqual(_MockOpenAIHandler.captured_payload["seed"], 7)
        self.assertEqual(_MockOpenAIHandler.captured_payload["chat_template_kwargs"], {"enable_thinking": False})
        captured_headers = {key.lower(): value for key, value in _MockOpenAIHandler.captured_headers.items()}
        self.assertEqual(captured_headers["x-rag-ime-test"], "extra-header")
        messages = _MockOpenAIHandler.captured_payload["messages"]
        self.assertIn("只输出候选词", messages[0]["content"])
        self.assertLessEqual(_MockOpenAIHandler.captured_payload["max_tokens"], 8)
        self.assertEqual(predictions[0].metadata["profile"], "custom")
        request_meta = predictions[0].metadata["requestMeta"]
        self.assertEqual(request_meta["contextChars"], len("输入法需要本地记忆和候选预测"))
        self.assertEqual(len(request_meta["contextFingerprint"]), 16)
        self.assertEqual(len(request_meta["currentInputFingerprint"]), 16)
        self.assertEqual(len(request_meta["stablePrefixHash"]), 16)
        self.assertNotIn("contextFingerprint", _MockOpenAIHandler.captured_payload)

    def test_openai_compatible_provider_sends_pinyin_constrained_request_context(self) -> None:
        _MockOpenAIHandler.response_content = "设计 手机 世界 数据"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="quality-ime",
                    timeout_s=1.0,
                    max_tokens=12,
                    provider_name="mock-quality",
                )
            )
            predictions = provider.predict(
                current_input="sj",
                recent_context="我准备调试输入法",
                max_candidates=4,
                request_type=PREDICTION_REQUEST_PINYIN_CONSTRAINED,
                rime_candidates=("设计", "手机", "世界", "数据"),
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual([item.text for item in predictions], ["设计", "手机", "世界", "数据"])
        messages = _MockOpenAIHandler.captured_payload["messages"]
        self.assertIn("拼音/前缀约束预测", messages[0]["content"])
        self.assertIn("当前拼音或前缀: sj", messages[1]["content"])
        self.assertIn("Rime候选: 设计、手机、世界、数据", messages[1]["content"])
        self.assertEqual(predictions[0].metadata["request_type"], PREDICTION_REQUEST_PINYIN_CONSTRAINED)
        self.assertEqual(predictions[0].metadata["rime_candidates"], ["设计", "手机", "世界", "数据"])
        self.assertEqual(predictions[0].metadata["requestMeta"]["rimeCandidateCount"], 4)

    def test_openai_compatible_provider_reorders_only_rime_candidates(self) -> None:
        _MockOpenAIHandler.response_content = "手机 工具 随机词 设计"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="quality-ime",
                    timeout_s=1.0,
                    max_tokens=12,
                    provider_name="mock-quality",
                )
            )
            predictions = provider.predict(
                current_input="sj",
                recent_context="我准备调试输入法",
                max_candidates=3,
                request_type=PREDICTION_REQUEST_RIME_REORDER,
                rime_candidates=("设计", "手机", "世界"),
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual([item.text for item in predictions], ["手机", "设计"])
        messages = _MockOpenAIHandler.captured_payload["messages"]
        self.assertIn("只允许重排给定 Rime 候选", messages[0]["content"])
        self.assertIn("请只从 Rime候选 中选出并重排", messages[1]["content"])
        self.assertNotIn("随机词", [item.text for item in predictions])
        self.assertEqual(predictions[0].metadata["request_type"], PREDICTION_REQUEST_RIME_REORDER)

    def test_completion_prompt_mode_uses_prefix_completion_endpoint(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="qwen-base",
                    prompt_mode="completion",
                    timeout_s=1.0,
                    max_tokens=4,
                    provider_name="mock-completion",
                )
            )
            predictions = provider.predict(
                current_input="输入法",
                recent_context="本地记忆",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.assertEqual([item.text for item in predictions], ["本地记忆", "RAG上下文"])
        self.assertEqual(_MockCompletionHandler.captured_path, "/v1/completions")
        self.assertEqual(_MockCompletionHandler.captured_payload["model"], "qwen-base")
        self.assertEqual(_MockCompletionHandler.captured_payload["prompt"], "本地记忆输入法")
        self.assertEqual(_MockCompletionHandler.captured_payload["n"], 3)
        self.assertNotIn("messages", _MockCompletionHandler.captured_payload)
        self.assertEqual(predictions[0].metadata["prompt_mode"], "completion")
        self.assertEqual(predictions[0].metadata["requestMeta"]["stablePrefixHash"], "")

    def test_env_can_disable_qwen_thinking_without_hand_written_json(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_DISABLE_THINKING": "1",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7,"chat_template_kwargs":{"foo":"bar"}}',
            }
        )

        self.assertIsInstance(provider, CooldownPredictionProvider)
        config = provider.config
        self.assertEqual(
            config.extra_body,
            {
                "seed": 7,
                "chat_template_kwargs": {
                    "foo": "bar",
                    "enable_thinking": False,
                },
            },
        )

    def test_instant_profile_sets_fast_no_thinking_defaults(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7}',
            }
        )

        self.assertIsInstance(provider, CooldownPredictionProvider)
        config = provider.config
        self.assertEqual(config.profile, "instant")
        self.assertEqual(config.prompt_mode, "chat")
        self.assertEqual(config.timeout_s, 0.35)
        self.assertEqual(config.max_tokens, 8)
        self.assertEqual(config.temperature, 0.15)
        self.assertEqual(config.top_p, 0.85)
        self.assertEqual(
            config.extra_body,
            {
                "seed": 7,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )

    def test_prediction_provider_status_reports_configured_model_lane(self) -> None:
        null_status = prediction_provider_status(prediction_provider_from_env({}))
        self.assertFalse(null_status["configured"])
        self.assertEqual(null_status["providerName"], "NullPredictionProvider")

        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7}',
            }
        )
        status = prediction_provider_status(provider)

        self.assertTrue(status["configured"])
        self.assertEqual(status["providerName"], "local-openai-compatible")
        self.assertEqual(status["providerProfile"], "instant")
        self.assertEqual(status["promptMode"], "chat")
        self.assertEqual(status["baseUrl"], "http://127.0.0.1:8000")
        self.assertEqual(status["model"], "Qwen3-0.6B")
        self.assertEqual(status["timeoutMs"], 350)
        self.assertIn("chat_template_kwargs", status["extraBodyKeys"])
        self.assertIn("seed", status["extraBodyKeys"])
        self.assertEqual(status["modelProfile"]["id"], "qwen3_06b_ime_hot")
        self.assertEqual(status["modelProfile"]["lane"], "hot")
        self.assertFalse(status["capabilities"]["streaming"])
        self.assertTrue(status["cooldown"]["enabled"])

    def test_local_resident_predictor_stream_first_defaults_match_lane(self) -> None:
        ollama_provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8767",
                "RAG_IME_PREDICTOR_MODEL": "local-small-ime",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
            }
        )
        mlx_provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8767",
                "RAG_IME_PREDICTOR_MODEL": "local-small-ime",
                "RAG_IME_PREDICTOR_PROFILE": "qwen3_06b_ime_hot",
            }
        )

        ollama_status = prediction_provider_status(ollama_provider)
        mlx_status = prediction_provider_status(mlx_provider)

        self.assertTrue(ollama_status["configured"])
        self.assertTrue(ollama_status["streamFirstCandidate"])
        self.assertTrue(mlx_status["configured"])
        self.assertFalse(mlx_status["streamFirstCandidate"])

    def test_model_env_file_does_not_configure_realtime_predictor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://x1api.top/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=deepseek-chat",
                    ]
                ),
                encoding="utf-8",
            )
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_MODEL_ENV": str(env_path),
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )

        self.assertIsInstance(provider, NullPredictionProvider)

    def test_prediction_provider_can_use_explicit_predictor_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "RAG_IME_PREDICTOR_PROVIDER=openai-compatible",
                        "RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000",
                        "RAG_IME_PREDICTOR_API_KEY=secret-value",
                        "RAG_IME_PREDICTOR_MODEL=local-proxy-model",
                    ]
                ),
                encoding="utf-8",
            )
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_ENV": str(env_path),
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )

        self.assertIsInstance(provider, OpenAICompatiblePredictionProvider)
        assert isinstance(provider, OpenAICompatiblePredictionProvider)
        self.assertEqual(provider.config.base_url, "http://127.0.0.1:8000")
        self.assertEqual(provider.config.model, "local-proxy-model")
        self.assertEqual(provider.config.api_key, "secret-value")

    def test_explicit_x1api_predictor_env_is_rejected_for_realtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "RAG_IME_PREDICTOR_PROVIDER=openai-compatible",
                        "RAG_IME_PREDICTOR_BASE_URL=https://x2app.top/v1",
                        "RAG_IME_PREDICTOR_API_KEY=secret-value",
                        "RAG_IME_PREDICTOR_MODEL=gpt-series-model",
                    ]
                ),
                encoding="utf-8",
            )
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_ENV": str(env_path),
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )

        self.assertIsInstance(provider, NullPredictionProvider)

    def test_remote_openai_compatible_predictor_url_is_rejected_for_realtime(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "https://api.openai.com/v1",
                "RAG_IME_PREDICTOR_API_KEY": "secret-value",
                "RAG_IME_PREDICTOR_MODEL": "gpt-series-model",
                "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
            }
        )

        self.assertIsInstance(provider, NullPredictionProvider)

    def test_legacy_x1api_model_env_does_not_configure_realtime_predictor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "API_BASE_URL=https://x2app.top/v1",
                        "API_KEY=secret-value",
                        "MODEL=gpt-5.5",
                    ]
                ),
                encoding="utf-8",
            )
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_MODEL_ENV": str(env_path),
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )

        self.assertIsInstance(provider, NullPredictionProvider)

    def test_env_can_disable_prediction_failure_cooldown(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
            }
        )

        self.assertIsInstance(provider, OpenAICompatiblePredictionProvider)

    def test_ollama_provider_uses_native_chat_with_thinking_disabled(self) -> None:
        _MockOllamaHandler.captured_path = ""
        _MockOllamaHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "0",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            self.assertIsInstance(provider, OllamaPredictionProvider)
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockOllamaHandler.captured_path, "/api/chat")
        self.assertFalse(_MockOllamaHandler.captured_payload["think"])
        self.assertEqual(_MockOllamaHandler.captured_payload["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockOllamaHandler.captured_payload["options"]["num_predict"], 24)
        self.assertEqual(predictions[0].text, "本地记忆")
        self.assertEqual(predictions[0].provider_name, "local-ollama")
        request_meta = predictions[0].metadata["requestMeta"]
        self.assertEqual(request_meta["contextChars"], len("用户正在写本地记忆输入法"))
        self.assertEqual(len(request_meta["contextFingerprint"]), 16)
        self.assertEqual(len(request_meta["stablePrefixHash"]), 16)

    def test_ollama_provider_can_return_first_streamed_candidate(self) -> None:
        _MockOllamaStreamingHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b-mlx",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual([item.text for item in predictions], ["本地记忆"])
        self.assertTrue(_MockOllamaStreamingHandler.captured_payload["stream"])
        self.assertEqual(_MockOllamaStreamingHandler.captured_payload["keep_alive"], -1)
        self.assertIn("只输出一个最可能", _MockOllamaStreamingHandler.captured_payload["messages"][0]["content"])
        self.assertNotIn("JSON 字符串数组", _MockOllamaStreamingHandler.captured_payload["messages"][0]["content"])
        self.assertTrue(predictions[0].metadata["stream_first_candidate"])
        self.assertIsInstance(predictions[0].metadata["first_candidate_ms"], int)
        self.assertEqual(len(predictions[0].metadata["requestMeta"]["contextFingerprint"]), 16)
        status = prediction_provider_status(provider)
        self.assertTrue(status["streamFirstCandidate"])

    def test_streaming_plain_text_parser_waits_for_usable_candidate(self) -> None:
        self.assertEqual(_parse_streaming_prediction_candidates("本", max_candidates=1), [])
        self.assertEqual(_parse_streaming_prediction_candidates("本地", max_candidates=1), [])
        self.assertEqual(_parse_streaming_prediction_candidates("本地记忆", max_candidates=1), ["本地记忆"])
        self.assertEqual(_parse_streaming_prediction_candidates("R", max_candidates=1), [])
        self.assertEqual(_parse_streaming_prediction_candidates("RAG", max_candidates=1), ["RAG"])
        self.assertEqual(
            _parse_streaming_prediction_candidates(
                "<think>\n\n</think>\n\n记忆<|im_end|>\n<|endoftext|><|im_start|>user\n你是",
                max_candidates=1,
            ),
            [],
        )

    def test_mlx_payload_preserves_rime_backfill_candidates(self) -> None:
        payload = {
            "candidates": ["稳定性", "显示", "候选"],
            "candidateScores": [
                {"text": "稳定性", "source": "rime-backfill", "mode": "rime-candidate-backfill"},
                {"text": "显示", "source": "rime-backfill", "mode": "rime-candidate-backfill"},
                {"text": "候选", "source": "rime-backfill", "mode": "rime-candidate-backfill"},
            ],
        }

        self.assertEqual(
            _finalize_mlx_payload_candidates(payload, payload["candidates"], "", max_items=3),
            ["稳定性", "显示", "候选"],
        )

    def test_prediction_filter_removes_repeated_current_input_tokens(self) -> None:
        self.assertEqual(
            _filter_repeated_input_candidates(["RAG", "候选展示"], "RAG 输入法"),
            ["候选展示"],
        )
        self.assertEqual(
            _filter_repeated_input_candidates(["PROJECT", "背景记忆"], "PROJECT_MEMORY_BLOCK"),
            ["背景记忆"],
        )

    def test_prediction_filter_keeps_choices_from_rime_candidate_list(self) -> None:
        self.assertEqual(
            _filter_repeated_input_candidates(["现在", "现状"], "现在 限制 现状"),
            ["现在", "现状"],
        )

    def test_prediction_filter_removes_low_value_filler_candidates(self) -> None:
        self.assertEqual(
            _filter_low_value_ime_candidates(
                [
                    "嗯",
                    "推荐",
                    "啊",
                    "呃",
                    "和",
                    "嗯嗯",
                    "当前",
                    "测试流程",
                    "假设需要测试",
                    "分析当前情况",
                    "当前问题",
                    "LLM",
                    "接入",
                    "RAG",
                    "后文候选",
                    "模型候选",
                    "你正在输入一个已经上屏的文本",
                    "你正在看Felix的3322号项目吗",
                    "您正在查看这个项目的实现",
                    "用户正在尝试使用LLM和RAG来构建记忆",
                    "Model de",
                    "想...Mode",
                    "候选展示方式",
                ]
            ),
            ["推荐", "候选展示方式"],
        )

    def test_mlx_provider_uses_resident_prediction_service(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "0",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            self.assertIsInstance(provider, MlxPredictionServiceProvider)
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
                request_type="pinyin_constrained_prediction",
                rime_candidates=("输入法", "音法", "英法"),
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockMlxHandler.captured_path, "/predict")
        self.assertEqual(_MockMlxHandler.captured_payload["model"], "mlx-qwen3.5-0.8b")
        self.assertEqual(_MockMlxHandler.captured_payload["maxCandidates"], 3)
        self.assertEqual(_MockMlxHandler.captured_payload["maxTokens"], 24)
        self.assertEqual(_MockMlxHandler.captured_payload["requestType"], "pinyin_constrained_prediction")
        self.assertEqual(_MockMlxHandler.captured_payload["rimeCandidates"], ["输入法", "音法", "英法"])
        self.assertEqual(_MockMlxHandler.captured_payload["rimeCandidateCount"], 3)
        self.assertEqual(len(_MockMlxHandler.captured_payload["rimeCandidatesFingerprint"]), 16)
        self.assertEqual(_MockMlxHandler.captured_payload["contextChars"], len("用户正在写本地记忆输入法"))
        self.assertEqual(len(_MockMlxHandler.captured_payload["contextFingerprint"]), 16)
        self.assertEqual(len(_MockMlxHandler.captured_payload["stablePrefixHash"]), 16)
        self.assertEqual([item.text for item in predictions], ["本地记忆", "RAG上下文"])
        self.assertEqual(predictions[0].provider_name, "local-mlx")
        self.assertEqual(predictions[0].latency_ms, 17)
        self.assertEqual(predictions[0].metadata["candidate_mode"], "next-token-logits")
        self.assertEqual(predictions[0].metadata["candidate_scores"][0]["tokenId"], 42)
        self.assertEqual(predictions[0].metadata["prompt_cache"], {"enabled": False})
        self.assertEqual(predictions[0].metadata["request_type"], "pinyin_constrained_prediction")
        self.assertEqual(predictions[0].metadata["rime_candidates"], ["输入法", "音法", "英法"])
        self.assertEqual(predictions[0].metadata["requestMeta"]["requestType"], "pinyin_constrained_prediction")
        self.assertEqual(
            predictions[0].metadata["requestMeta"]["contextFingerprint"],
            _MockMlxHandler.captured_payload["contextFingerprint"],
        )
        status = prediction_provider_status(provider)
        self.assertTrue(status["capabilities"]["streaming"])
        self.assertTrue(status["capabilities"]["residentModel"])
        self.assertFalse(status["capabilities"]["promptCache"])
        self.assertFalse(status["capabilities"]["seededPromptReplay"])
        self.assertFalse(status["capabilities"]["kvFork"])
        self.assertFalse(status["capabilities"]["sequenceFork"])

    def test_mlx_provider_status_can_probe_prompt_cache_runtime_capability(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {
            "ok": True,
            "provider": "mlx-lm",
            "model": "mlx-qwen3.5-0.8b",
            "modelLoaded": True,
            "promptCache": {
                "enabled": True,
                "prepared": True,
                "cacheFileReady": True,
                "usedForGeneration": True,
                "hits": 3,
                "misses": 0,
            },
            "capabilities": {
                "streaming": True,
                "residentModel": True,
                "promptCache": True,
                "seededPromptReplay": True,
                "kvFork": False,
                "sequenceFork": False,
                "batchCandidates": False,
                "serverTiming": True,
            },
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            status = prediction_provider_status(provider, probe_capabilities=True)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            _MockMlxHandler.health_payload = {}
            _MockMlxHandler.stream_chunks = None

        self.assertTrue(status["capabilityProbe"]["ok"])
        self.assertTrue(status["capabilities"]["promptCache"])
        self.assertTrue(status["capabilities"]["seededPromptReplay"])
        self.assertFalse(status["capabilities"]["kvFork"])
        self.assertFalse(status["capabilities"]["sequenceFork"])
        self.assertFalse(status["capabilities"]["batchCandidates"])
        self.assertEqual(status["capabilityProbe"]["promptCache"]["hits"], 3)

    def test_mlx_provider_status_exposes_text_only_model_info(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {
            "ok": True,
            "provider": "mlx-lm",
            "model": "mlx-qwen3-0.6b-4bit",
            "modelLoaded": True,
            "modelInfo": {
                "modelId": "/models/qwen3-0.6b-4bit",
                "localPath": True,
                "textOnly": True,
                "hasVisionConfig": False,
                "architecture": "Qwen3ForCausalLM",
                "vocabSize": 151936,
            },
            "capabilities": {
                "streaming": True,
                "residentModel": True,
                "textOnlyModel": True,
                "batchCandidates": True,
                "logitsTopK": True,
            },
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3-0.6b-4bit",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            status = prediction_provider_status(provider, probe_capabilities=True)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            _MockMlxHandler.health_payload = {}

        self.assertTrue(status["capabilityProbe"]["ok"])
        self.assertTrue(status["capabilities"]["textOnlyModel"])
        self.assertTrue(status["capabilities"]["logitsTopK"])
        self.assertEqual(status["modelInfo"]["architecture"], "Qwen3ForCausalLM")
        self.assertTrue(status["modelInfo"]["textOnly"])

    def test_cli_predictor_status_can_probe_mlx_runtime_capabilities(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {
            "ok": True,
            "provider": "mlx-lm",
            "model": "mlx-qwen3.5-0.8b",
            "modelLoaded": True,
            "promptCache": {
                "enabled": True,
                "prepared": True,
                "cacheFileReady": True,
                "usedForGeneration": True,
            },
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(["--core-mode", "fixture", "predictor-status", "--probe-capabilities"])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            _MockMlxHandler.health_payload = {}

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["capabilityProbe"]["ok"])
        self.assertTrue(report["capabilities"]["promptCache"])

    def test_mlx_failed_capability_probe_clears_runtime_capabilities(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:9",
                "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_TIMEOUT_MS": "100",
                "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
            }
        )

        status = prediction_provider_status(provider, probe_capabilities=True)

        self.assertFalse(status["capabilityProbe"]["ok"])
        self.assertFalse(status["capabilities"]["streaming"])
        self.assertFalse(status["capabilities"]["residentModel"])
        self.assertFalse(status["capabilities"]["promptCache"])

    def test_mlx_provider_can_return_first_streamed_candidate(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockMlxHandler.captured_path, "/predict-stream")
        self.assertTrue(_MockMlxHandler.captured_payload["stream"])
        self.assertEqual(len(_MockMlxHandler.captured_payload["contextFingerprint"]), 16)
        self.assertEqual([item.text for item in predictions], ["本地记忆"])
        self.assertTrue(predictions[0].metadata["stream_first_candidate"])
        self.assertIsInstance(predictions[0].metadata["first_candidate_ms"], int)
        self.assertEqual(
            predictions[0].metadata["requestMeta"]["contextFingerprint"],
            _MockMlxHandler.captured_payload["contextFingerprint"],
        )
        status = prediction_provider_status(provider)
        self.assertTrue(status["streamFirstCandidate"])

    def test_mlx_stream_first_candidate_does_not_fallback_to_slow_predict_when_empty(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {}
        _MockMlxHandler.stream_chunks = [
            {"delta": "想"},
            {"done": True, "candidates": [], "totalMs": 19},
        ]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="",
                recent_context="我想",
                max_candidates=3,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            _MockMlxHandler.stream_chunks = None

        self.assertEqual(predictions, [])

    def test_mlx_stream_first_candidate_preserves_rime_candidate(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        _MockMlxHandler.health_payload = {}
        _MockMlxHandler.stream_chunks = [
            {"delta": "稳定性", "elapsedMs": 18},
            {"event": "candidate_delta", "candidate": "稳定性", "index": 0, "elapsedMs": 18},
            {"done": True, "candidates": ["稳定性"], "totalMs": 19},
        ]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="",
                recent_context="这个输入法目前最影响体验的是",
                max_candidates=3,
                request_type=PREDICTION_REQUEST_NO_INPUT,
                rime_candidates=("稳定性", "候选", "显示"),
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
            _MockMlxHandler.stream_chunks = None

        self.assertEqual([item.text for item in predictions], ["稳定性"])
        self.assertTrue(predictions[0].metadata["stream_first_candidate"])
        self.assertEqual(_MockMlxHandler.captured_path, "/predict-stream")

    def test_prediction_cooldown_skips_repeat_failures(self) -> None:
        class FailingProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="failing-provider",
                profile="instant",
            )

            def __init__(self) -> None:
                self.calls = 0
                self.last_error = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.calls += 1
                self.last_error = "timeout"
                return []

        delegate = FailingProvider()
        provider = CooldownPredictionProvider(delegate, cooldown_ms=1000, failure_latency_ms=1)

        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(delegate.calls, 1)
        status = prediction_provider_status(provider)
        self.assertTrue(status["cooldown"]["active"])
        self.assertEqual(status["cooldown"]["failureCount"], 1)
        self.assertEqual(status["cooldown"]["skippedCount"], 1)
        self.assertEqual(status["cooldown"]["lastError"], "timeout")

    def test_prediction_cooldown_does_not_skip_after_empty_success(self) -> None:
        class EmptyProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="empty-provider",
                profile="instant",
            )

            def __init__(self) -> None:
                self.calls = 0
                self.last_error = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.calls += 1
                time.sleep(0.003)
                self.last_error = ""
                return []

        delegate = EmptyProvider()
        provider = CooldownPredictionProvider(delegate, cooldown_ms=1000, failure_latency_ms=1)

        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(delegate.calls, 2)
        status = prediction_provider_status(provider)
        self.assertFalse(status["cooldown"]["active"])
        self.assertEqual(status["cooldown"]["failureCount"], 0)
        self.assertEqual(status["cooldown"]["skippedCount"], 0)

    def test_predictor_doctor_reports_cooldown_after_failed_probe(self) -> None:
        class FailingProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="doctor-failing-provider",
                profile="instant",
            )

            def __init__(self) -> None:
                self.last_error = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.last_error = "timeout"
                return []

        provider = CooldownPredictionProvider(FailingProvider(), cooldown_ms=1000, failure_latency_ms=1)
        report = doctor_prediction_provider(provider, latency_budget_ms=1000)

        self.assertFalse(report["ready"])
        self.assertTrue(report["status"]["cooldown"]["active"])
        self.assertEqual(report["status"]["cooldown"]["lastError"], "timeout")

    def test_cli_predictor_status_reports_env_configuration(self) -> None:
        stdout = io.StringIO()
        with patch.dict(
            os.environ,
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
            },
            clear=False,
        ):
            with redirect_stdout(stdout):
                code = main(["--core-mode", "fixture", "predictor-status"])

        self.assertEqual(code, 0)
        status = json.loads(stdout.getvalue())
        self.assertTrue(status["configured"])
        self.assertEqual(status["providerProfile"], "instant")
        self.assertEqual(status["model"], "Qwen3-0.6B")

    def test_predictor_doctor_reports_unconfigured_lane(self) -> None:
        report = doctor_prediction_provider(prediction_provider_from_env({}))

        self.assertEqual(report["schemaVersion"], "rag-ime.predictor-doctor.v1")
        self.assertFalse(report["ready"])
        self.assertFalse(report["summary"]["endpointReachable"])
        self.assertFalse(report["status"]["configured"])
        self.assertEqual(report["checks"]["modelsEndpoint"]["reason"], "not_configured")
        self.assertFalse(report["checks"]["prediction"]["hasCandidates"])
        self.assertIn("RAG_IME_PREDICTOR_PROVIDER", report["nextActions"][0])

    def test_cli_predictor_doctor_checks_models_and_short_prediction(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-doctor",
                            "--case",
                            "RAG 输入法",
                            "--latency-budget-ms",
                            "1000",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ready"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["ok"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["configuredModelFound"])
        self.assertEqual(report["checks"]["modelsEndpoint"]["modelCount"], 2)
        self.assertTrue(report["checks"]["prediction"]["hasCandidates"])
        self.assertEqual(report["checks"]["prediction"]["candidates"][0], "本地记忆")
        self.assertIn("localRunners", report)

    def test_cli_predictor_doctor_checks_ollama_tags_and_short_prediction(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-doctor",
                            "--case",
                            "RAG 输入法",
                            "--latency-budget-ms",
                            "1000",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"]["providerName"], "local-ollama")
        self.assertEqual(report["status"]["promptMode"], "ollama-chat")
        self.assertTrue(report["checks"]["modelsEndpoint"]["ok"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["configuredModelFound"])
        self.assertEqual(report["checks"]["prediction"]["candidates"][0], "本地记忆")

    def test_prediction_benchmark_reports_latency_budget(self) -> None:
        class FakeProvider:
            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                return [
                    type(
                        "Prediction",
                        (),
                        {
                            "text": f"{current_input}候选",
                            "latency_ms": 12,
                            "provider_name": "fake-fast",
                        },
                    )()
                ][:max_candidates]

        report = benchmark_prediction_provider(
            FakeProvider(),
            [PredictionBenchmarkCase(current_input="RAG 输入法")],
            max_candidates=2,
            latency_budget_ms=50,
        )
        self.assertEqual(report["schemaVersion"], "rag-ime.predict-benchmark.v1")
        self.assertEqual(report["providerName"], "fake-fast")
        self.assertEqual(report["providerProfile"], "none")
        self.assertTrue(report["providerConfigured"])
        self.assertEqual(report["summary"]["caseCount"], 1)
        self.assertTrue(report["summary"]["allWithinBudget"])
        self.assertTrue(report["summary"]["hasCandidates"])
        self.assertEqual(report["cases"][0]["candidates"], ["RAG 输入法候选"])

    def test_prediction_benchmark_uses_configured_name_without_candidates(self) -> None:
        class EmptyConfiguredProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="configured-empty",
                profile="instant",
            )

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                return []

        report = benchmark_prediction_provider(
            EmptyConfiguredProvider(),
            [PredictionBenchmarkCase(current_input="RAG 输入法")],
            max_candidates=2,
            latency_budget_ms=50,
        )

        self.assertEqual(report["providerName"], "configured-empty")
        self.assertEqual(report["providerProfile"], "instant")
        self.assertTrue(report["providerConfigured"])
        self.assertFalse(report["summary"]["hasCandidates"])

    def test_cli_eval_prediction_reports_quality_and_latency(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-prediction-eval-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(
                    os.environ,
                    {
                        "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                        "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                        "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    },
                    clear=False,
                ):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/prediction.sqlite",
                                "eval-prediction",
                                "--cases-file",
                                cases_file,
                                "--max-candidates",
                                "3",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.codex-history-eval.v1")
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["metrics"]["top1Accuracy"], 1.0)
        self.assertEqual(report["prediction"]["providerName"], "local-openai-compatible")
        self.assertTrue(report["prediction"]["providerConfigured"])
        self.assertEqual(report["prediction"]["maxCandidates"], 3)
        self.assertEqual(report["prediction"]["overBudgetCount"], 0)
        self.assertEqual(report["prediction"]["totalCandidates"], 2)
        self.assertEqual(report["latency"]["caseCount"], 1)
        self.assertEqual(report["cases"][0]["topSurfaces"][0], "本地记忆")

    def test_cli_eval_model_matrix_compares_qwen_tags(self) -> None:
        _MockModelMatrixHandler.seen_models = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockModelMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-model-matrix-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(os.environ, {"RAG_IME_PREDICTOR_TIMEOUT_MS": "1000"}, clear=False):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/matrix.sqlite",
                                "eval-model-matrix",
                                "--cases-file",
                                cases_file,
                                "--base-url",
                                f"http://127.0.0.1:{server.server_port}",
                                "--models",
                                "qwen3.5:0.8b,qwen3.5:2b",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.model-matrix-eval.v1")
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertEqual(report["models"][0]["passed"], 1)
        self.assertEqual(report["models"][1]["passed"], 0)
        self.assertNotIn("cases", report["models"][0])
        self.assertEqual(report["models"][1]["failedCaseIds"], ["local-memory-prediction"])
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockModelMatrixHandler.seen_models, ["qwen3.5:0.8b", "qwen3.5:2b"])

    def test_cli_eval_model_matrix_can_use_native_ollama_provider(self) -> None:
        _MockOllamaMatrixHandler.seen_models = []
        _MockOllamaMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-ollama-matrix-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(os.environ, {"RAG_IME_PREDICTOR_TIMEOUT_MS": "1000"}, clear=False):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/matrix.sqlite",
                                "eval-model-matrix",
                                "--cases-file",
                                cases_file,
                                "--provider",
                                "ollama",
                                "--base-url",
                                f"http://127.0.0.1:{server.server_port}/v1",
                                "--models",
                                "qwen3.5:0.8b,qwen3.5:2b",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.model-matrix-eval.v1")
        self.assertEqual(report["provider"], "ollama")
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertEqual(report["models"][0]["passed"], 1)
        self.assertEqual(report["models"][1]["passed"], 0)
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockOllamaMatrixHandler.seen_models, ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertTrue(all(payload["think"] is False for payload in _MockOllamaMatrixHandler.captured_payloads))

    def test_cli_predictor_ttft_measures_streaming_first_chunk(self) -> None:
        _MockOllamaStreamingHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--recent-context",
                            "用户正在写本地记忆输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.predictor-ttft.v1")
        self.assertTrue(report["supported"])
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertTrue(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["cases"][0]["candidateCount"], 1)
        self.assertEqual(report["cases"][0]["candidates"][0], "本地记忆")
        self.assertIsInstance(report["cases"][0]["firstChunkMs"], int)
        self.assertIsInstance(report["cases"][0]["firstCandidateMs"], int)
        self.assertIsInstance(report["summary"]["p50FirstCandidateMs"], int)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 0)
        self.assertTrue(_MockOllamaStreamingHandler.captured_payload["stream"])
        self.assertFalse(_MockOllamaStreamingHandler.captured_payload["think"])
        self.assertEqual(_MockOllamaStreamingHandler.captured_payload["keep_alive"], -1)

    def test_cli_bench_ime_ttfc_runs_streaming_model_matrix_from_cases_file(self) -> None:
        _MockOllamaStreamingMatrixHandler.seen_models = []
        _MockOllamaStreamingMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-ttfc-cases-") as tmp:
                cases_file = os.path.join(tmp, "ime-ttfc-cases.jsonl")
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "short-context",
                                "currentInput": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    handle.write(
                        json.dumps(
                            {
                                "id": "no-expected-terms",
                                "query": "Squirrel 候选",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "bench-ime-ttfc",
                            "--cases-file",
                            cases_file,
                            "--provider",
                            "ollama",
                            "--base-url",
                            f"http://127.0.0.1:{server.server_port}",
                            "--models",
                            "qwen3.5:0.8b-mlx,qwen3.5:2b-mlx",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                            "--include-cases",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.ime-ttfc-benchmark.v1")
        self.assertEqual(report["repeat"]["baseCaseCount"], 2)
        self.assertEqual(report["repeat"]["effectiveCaseCount"], 2)
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b-mlx", "qwen3.5:2b-mlx"])
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b-mlx")
        self.assertTrue(report["models"][0]["summary"]["hasFirstCandidate"])
        self.assertEqual(report["models"][0]["cases"][0]["caseId"], "short-context")
        self.assertEqual(report["models"][0]["cases"][1]["caseId"], "no-expected-terms")
        self.assertEqual(
            _MockOllamaStreamingMatrixHandler.seen_models,
            ["qwen3.5:0.8b-mlx", "qwen3.5:0.8b-mlx", "qwen3.5:2b-mlx", "qwen3.5:2b-mlx"],
        )
        self.assertTrue(all(payload["stream"] for payload in _MockOllamaStreamingMatrixHandler.captured_payloads))
        self.assertTrue(all(payload["think"] is False for payload in _MockOllamaStreamingMatrixHandler.captured_payloads))

    def test_cli_bench_ime_ttfc_can_warm_model_without_scoring_warmup(self) -> None:
        _MockOllamaStreamingMatrixHandler.seen_models = []
        _MockOllamaStreamingMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-ttfc-warmup-") as tmp:
                cases_file = os.path.join(tmp, "ime-ttfc-cases.jsonl")
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "short-context",
                                "currentInput": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "bench-ime-ttfc",
                            "--cases-file",
                            cases_file,
                            "--provider",
                            "ollama",
                            "--base-url",
                            f"http://127.0.0.1:{server.server_port}",
                            "--models",
                            "qwen3.5:0.8b-mlx",
                            "--warmup-runs",
                            "2",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["warmupRuns"], 2)
        self.assertEqual(report["repeat"]["effectiveCaseCount"], 1)
        self.assertEqual(report["models"][0]["warmup"]["sampleCount"], 2)
        self.assertEqual(report["models"][0]["summary"]["sampleCount"], 1)
        self.assertEqual(
            _MockOllamaStreamingMatrixHandler.seen_models,
            ["qwen3.5:0.8b-mlx", "qwen3.5:0.8b-mlx", "qwen3.5:0.8b-mlx"],
        )

    def test_cli_quality_gate_can_require_model_ttfc(self) -> None:
        _MockOllamaStreamingMatrixHandler.seen_models = []
        _MockOllamaStreamingMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-quality-ttfc-") as tmp:
                db_path = os.path.join(tmp, "quality.sqlite")
                with redirect_stdout(io.StringIO()):
                    seed_code = main(["--db-path", db_path, "seed-demo", "--reset"])
                self.assertEqual(seed_code, 0)

                eval_cases_file = os.path.join(tmp, "quality-cases.jsonl")
                with open(eval_cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "agent-hook",
                                "query": "首次运行自动注入背景记忆",
                                "expectedTerms": ["PROJECT_MEMORY_BLOCK"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    handle.write(
                        json.dumps(
                            {
                                "id": "memory-actions",
                                "query": "本地记忆 action 如何支持 pin downrank delete",
                                "expectedTerms": ["pin", "downrank", "delete"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                ttfc_cases_file = os.path.join(tmp, "ttfc-cases.jsonl")
                with open(ttfc_cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "ttfc-short",
                                "currentInput": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    gate_code = main(
                        [
                            "--db-path",
                            db_path,
                            "quality-gate",
                            "--cases-file",
                            eval_cases_file,
                            "--min-rag-pass-rate",
                            "1",
                            "--min-sidecar-pass-rate",
                            "1",
                            "--force-side-candidates",
                            "--require-suggestion-cache",
                            "--require-model-ttfc",
                            "--model-ttfc-cases-file",
                            ttfc_cases_file,
                            "--model-ttfc-provider",
                            "ollama",
                            "--model-ttfc-base-url",
                            f"http://127.0.0.1:{server.server_port}",
                            "--model-ttfc-models",
                            "qwen3.5:0.8b-mlx,qwen3.5:2b-mlx",
                            "--model-ttfc-repeat",
                            "1",
                            "--model-ttfc-latency-budget-ms",
                            "200",
                            "--max-model-ttfc-p95-ms",
                            "200",
                            "--max-model-ttfc-over-budget-rate",
                            "0",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(gate_code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["passed"])
        self.assertTrue(report["thresholds"]["requireModelTtfc"])
        self.assertEqual(report["modelTtfc"]["winner"]["model"], "qwen3.5:0.8b-mlx")
        check_names = {item["name"] for item in report["checks"]}
        self.assertIn("model-ttfc-supported", check_names)
        self.assertIn("model-ttfc-first-candidate", check_names)
        self.assertIn("model-ttfc-p95-first-candidate", check_names)
        self.assertIn("model-ttfc-over-budget-rate", check_names)
        self.assertTrue(all(item["passed"] for item in report["checks"] if item["name"].startswith("model-ttfc-")))
        self.assertEqual(
            _MockOllamaStreamingMatrixHandler.seen_models,
            ["qwen3.5:0.8b-mlx", "qwen3.5:2b-mlx"],
        )

    def test_cli_quality_gate_can_require_multiple_model_candidates(self) -> None:
        _MockOpenAIHandler.response_content = "本地记忆\n上下文管理\n连续预测"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-quality-model-count-") as tmp:
                db_path = os.path.join(tmp, "quality.sqlite")
                with redirect_stdout(io.StringIO()):
                    seed_code = main(["--db-path", db_path, "seed-demo", "--reset"])
                self.assertEqual(seed_code, 0)

                eval_cases_file = os.path.join(tmp, "quality-cases.jsonl")
                with open(eval_cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "agent-hook",
                                "query": "首次运行自动注入背景记忆",
                                "expectedTerms": ["PROJECT_MEMORY_BLOCK"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                with patch.dict(
                    os.environ,
                    {
                        "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                        "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                        "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                        "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                    },
                    clear=False,
                ):
                    pass_stdout = io.StringIO()
                    with redirect_stdout(pass_stdout):
                        pass_code = main(
                            [
                                "--db-path",
                                db_path,
                                "quality-gate",
                                "--cases-file",
                                eval_cases_file,
                                "--min-rag-pass-rate",
                                "0",
                                "--min-sidecar-pass-rate",
                                "0",
                                "--force-side-candidates",
                                "--require-suggestion-cache",
                                "--require-model-candidate-count",
                                "3",
                            ]
                        )
                    self.assertEqual(pass_code, 0)
                    pass_report = json.loads(pass_stdout.getvalue())
                    self.assertTrue(pass_report["passed"])
                    self.assertEqual(pass_report["thresholds"]["requireModelCandidateCount"], 3)
                    self.assertEqual(pass_report["modelCandidateCount"]["minCandidateCount"], 3)
                    pass_checks = {item["name"]: item for item in pass_report["checks"]}
                    self.assertTrue(pass_checks["model-candidate-count"]["passed"])

                    _MockOpenAIHandler.response_content = "唯一候选"
                    fail_stdout = io.StringIO()
                    with redirect_stdout(fail_stdout):
                        fail_code = main(
                            [
                                "--db-path",
                                db_path,
                                "quality-gate",
                                "--cases-file",
                                eval_cases_file,
                                "--min-rag-pass-rate",
                                "0",
                                "--min-sidecar-pass-rate",
                                "0",
                                "--force-side-candidates",
                                "--require-suggestion-cache",
                                "--require-model-candidate-count",
                                "3",
                            ]
                        )
                    self.assertEqual(fail_code, 1)
                    fail_report = json.loads(fail_stdout.getvalue())
                    self.assertFalse(fail_report["passed"])
                    fail_checks = {item["name"]: item for item in fail_report["checks"]}
                    self.assertFalse(fail_checks["model-candidate-count"]["passed"])
                    self.assertEqual(fail_checks["model-candidate-count"]["actualMinCandidateCount"], 1)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_cli_predictor_ttft_counts_missing_first_chunk_as_over_budget(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaEmptyStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["summary"]["hasFirstChunk"])
        self.assertFalse(report["summary"]["allWithinBudget"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 1)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 1)
        self.assertEqual(report["summary"]["failureCount"], 1)
        self.assertEqual(report["summary"]["overBudgetCount"], 1)
        self.assertTrue(report["cases"][0]["overBudget"])

    def test_cli_predictor_ttft_uses_first_parsed_candidate_for_budget(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaUnparsedStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertFalse(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 0)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 1)
        self.assertEqual(report["summary"]["overBudgetCount"], 1)
        self.assertTrue(report["cases"][0]["overBudget"])

    def test_cli_predictor_ttft_supports_mlx_streaming_service(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["supported"])
        self.assertEqual(report["providerName"], "local-mlx")
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertTrue(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 0)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 0)
        self.assertEqual(report["cases"][0]["candidateCount"], 1)
        self.assertEqual(report["cases"][0]["candidates"][0], "本地记忆")
        self.assertEqual(_MockMlxHandler.captured_path, "/predict-stream")
        self.assertTrue(_MockMlxHandler.captured_payload["stream"])


if __name__ == "__main__":
    unittest.main()
