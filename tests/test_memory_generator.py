from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.memory_compiler import compiler_generator_from_env
from rag_ime.memory_generator import (
    VcpRebuildMemoryGenerator,
    _build_openai_url,
    _core_optimization_max_tokens,
    default_vcp_rebuild_env_path,
    _extract_json_object,
    _parse_generated_lexicon_phrases,
    _parse_generated_memory_items,
    _parse_suggested_hidden_events,
)


class MemoryGeneratorTests(unittest.TestCase):
    def test_default_generator_env_requires_an_explicit_provider_path(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_MEMORY_GENERATOR_ENV": "",
                "RAG_IME_MODEL_ENV": "",
                "RAG_IME_X1API_ENV": "",
                "RAG_IME_VCP_REBUILD_ENV": "",
            },
            clear=False,
        ):
            self.assertIsNone(default_vcp_rebuild_env_path())

    def test_parse_generated_memory_items_filters_noise_and_secrets(self) -> None:
        raw = """
        ```json
        {
          "memories": [
            {"text": "用户希望 RAG 输入法参考 Wisdom-Weasel 的连续预测交互", "tags": ["preference", "ime"], "importance": 0.9, "reason": "稳定项目要求"},
            {"text": "现在用不了，需要真实生效", "tags": ["complaint"], "importance": 0.5},
            {"text": "API_KEY 是 sk-xxx", "tags": ["secret"], "importance": 1.0}
          ]
        }
        ```
        """

        items = _parse_generated_memory_items(raw, max_items=5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].text, "用户希望 RAG 输入法参考 Wisdom-Weasel 的连续预测交互")
        self.assertIn("preference", items[0].tags)

    def test_build_openai_url_accepts_base_with_or_without_v1(self) -> None:
        self.assertEqual(
            _build_openai_url("https://example.com", "/chat/completions"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            _build_openai_url("https://example.com/v1", "/chat/completions"),
            "https://example.com/v1/chat/completions",
        )

    def test_from_env_path_reads_vcp_rebuild_settings_without_printing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "API_BASE_URL=https://example.com/v1",
                        "API_KEY=secret-value",
                        "MODEL=gpt-test",
                        "UPSTREAM_WIRE_API=responses",
                        "REQUEST_TIMEOUT_SECONDS=12",
                    ]
                ),
                encoding="utf-8",
            )

            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)

        self.assertEqual(generator.config.model, "gpt-test")
        self.assertEqual(generator.config.upstream_wire_api, "responses")
        self.assertEqual(generator.config.request_timeout_seconds, 12)

    def test_from_env_path_accepts_x1api_style_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://x1api.top/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=deepseek-chat",
                        "RAG_IME_AI_WIRE_API=chat_completions",
                        "RAG_IME_AI_THINKING=disabled",
                        "RAG_IME_AI_RESPONSE_FORMAT=json_object",
                    ]
                ),
                encoding="utf-8",
            )

            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)

        self.assertEqual(generator.config.api_base_url, "https://x1api.top/v1")
        self.assertEqual(generator.config.model, "deepseek-chat")
        self.assertEqual(generator.config.api_key, "secret-value")
        self.assertEqual(generator.config.chat_thinking_type, "disabled")
        self.assertEqual(generator.config.response_format, "json_object")
        self.assertEqual(generator.provider_name, "x1api")

    def test_model_request_uses_gateway_friendly_user_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://api.example.com/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=deepseek-v4-flash",
                        "RAG_IME_AI_WIRE_API=chat_completions",
                    ]
                ),
                encoding="utf-8",
            )
            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)
            captured = {}

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"choices":[{"message":{"content":"{\\"memories\\":[]}"}}]}'

            def fake_urlopen(request, timeout):
                captured["user_agent"] = request.get_header("User-agent")
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return FakeResponse()

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                report = generator.generate(text="测试离线整理模型", max_items=1)

        self.assertEqual(report.provider, "model-api")
        self.assertEqual(captured["user_agent"], "rag-ime/1.0 curl-compatible")

    def test_chat_completion_payload_can_disable_thinking_and_force_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://api.example.com/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=deepseek-v4-flash",
                        "RAG_IME_AI_WIRE_API=chat_completions",
                        "RAG_IME_AI_THINKING=disabled",
                        "RAG_IME_AI_RESPONSE_FORMAT=json_object",
                    ]
                ),
                encoding="utf-8",
            )
            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)
            captured = {}

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"choices":[{"message":{"content":"{\\"memories\\":[]}"}}]}'

            def fake_urlopen(request, timeout):
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return FakeResponse()

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                generator.generate(text="测试离线整理模型", max_items=1)

        self.assertEqual(captured["payload"]["thinking"], {"type": "disabled"})
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})

    def test_core_optimization_uses_larger_budget_for_large_diffs(self) -> None:
        self.assertGreaterEqual(
            _core_optimization_max_tokens(max_memories=8, max_lexicon_phrases=24, max_hide_suggestions=40),
            7000,
        )

    def test_optimize_core_metadata_reports_finish_and_cache_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://api.example.com/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=deepseek-v4-flash",
                        "RAG_IME_AI_WIRE_API=chat_completions",
                        "RAG_IME_AI_RESPONSE_FORMAT=json_object",
                    ]
                ),
                encoding="utf-8",
            )
            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return (
                        b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"memories\\":[]}"}}],'
                        b'"usage":{"prompt_cache_hit_tokens":12,"prompt_cache_miss_tokens":34,'
                        b'"prompt_tokens":46,"completion_tokens":5,"total_tokens":51}}'
                    )

            with patch("urllib.request.urlopen", return_value=FakeResponse()):
                report = generator.optimize_core(snapshot={"recentEvents": []})

        self.assertEqual(report.metadata["finishReason"], "stop")
        self.assertEqual(report.metadata["prompt_cache_hit_tokens"], 12)
        self.assertEqual(report.metadata["prompt_cache_miss_tokens"], 34)

    def test_from_env_path_canonicalizes_x2app_to_current_x1api_endpoint(self) -> None:
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

            generator = VcpRebuildMemoryGenerator.from_env_path(env_path)

        self.assertEqual(generator.provider_name, "x1api")
        self.assertEqual(generator.config.api_base_url, "https://x1api.top/v1")

    def test_compiler_generator_accepts_x1top_alias_for_offline_gpt_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "X1API_BASE_URL=https://x1api.top/v1",
                        "X1API_API_KEY=secret-value",
                        "X1API_MODEL=gpt-5.5",
                    ]
                ),
                encoding="utf-8",
            )

            generator = compiler_generator_from_env(
                env_path=env_path,
                provider="x1top",
            )

        self.assertEqual(generator.provider_name, "x1api")
        self.assertEqual(generator.config.model, "gpt-5.5")

    def test_parse_core_optimization_payload(self) -> None:
        raw = """
        {
          "memories": [
            {"text":"用户是四川人，输入法默认开启四川常见模糊音。","tags":["dialect"],"importance":0.9}
          ],
          "lexiconPhrases": [
            {"text":"高频词自动优化","tags":["ime"],"weight":0.8,"reason":"项目常用词"},
            {"text":"API_KEY 是 sk-xxx","tags":["secret"],"weight":1.0}
          ],
          "hideEventIds": [
            {"eventId": 12, "reason": "旧候选回灌"}
          ]
        }
        """
        payload = _extract_json_object(raw)

        memories = _parse_generated_memory_items(raw, max_items=3)
        phrases = _parse_generated_lexicon_phrases(payload, max_items=3)
        hidden = _parse_suggested_hidden_events(payload, max_items=3)

        self.assertEqual([item.text for item in memories], ["用户是四川人，输入法默认开启四川常见模糊音。"])
        self.assertEqual([item.text for item in phrases], ["高频词自动优化"])
        self.assertEqual(hidden[0].event_id, 12)
