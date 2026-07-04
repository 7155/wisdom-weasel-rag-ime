from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.memory_generator import (
    VcpRebuildMemoryGenerator,
    _build_openai_url,
    _parse_generated_memory_items,
)


class MemoryGeneratorTests(unittest.TestCase):
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
