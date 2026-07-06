from __future__ import annotations

import json
import unittest

from rag_ime.deepseek_completion import (
    DeepSeekCompletionRequest,
    DeepSeekV4FlashCompletionProvider,
    build_deepseek_completion_messages,
)
from rag_ime.deepseek_config import DeepSeekConfig


class DeepSeekCompletionTests(unittest.TestCase):
    def test_deepseek_completion_builds_json_prompt(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="post_commit",
                current_context="正在整理 RAG 输入法",
                evidence_pack=({"surfaceHints": ["BM25加向量召回"], "tags": ["RAG"]},),
            )
        )

        self.assertIn("JSON Lines", messages[0]["content"])
        self.assertIn("不要 Markdown", messages[0]["content"])
        user_payload = json.loads(messages[1]["content"])
        self.assertEqual(user_payload["scene"], "post_commit")
        self.assertEqual(user_payload["outputFormat"]["candidate"], "短候选")
        self.assertEqual(user_payload["evidencePack"][0]["surfaceHints"], ["BM25加向量召回"])

    def test_deepseek_completion_parses_streaming_json_lines(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"BM25加向量召回","role":"phrase"}\\n'),
                _sse_delta('{"candidate":"TagMemo语义解锁","role":"phrase"}\\n'),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法", max_candidates=3)
            )
        )

        self.assertEqual([item.text for item in deltas], ["BM25加向量召回", "TagMemo语义解锁"])
        self.assertTrue(all(item.source_lane == "deepseek_v4_flash" for item in deltas))

    def test_deepseek_completion_filters_generic_filler(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"下一步可以进行","role":"phrase"}\\n'),
                _sse_delta('{"candidate":"DeepSeek流式补全","role":"phrase"}\\n'),
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["DeepSeek流式补全"])

    def test_deepseek_completion_filters_raw_history_echo(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"这是历史原句直接复读","role":"phrase"}\\n'),
                _sse_delta('{"candidate":"Daily Book时间记忆","role":"phrase"}\\n'),
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="post_commit",
                    current_context="这是历史原句直接复读，需要被过滤",
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["Daily Book时间记忆"])

    def test_deepseek_completion_timeout_returns_partial_candidates(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"DeepSeek流式补全","role":"phrase"}\\n'),
                TimeoutError("slow stream"),
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["DeepSeek流式补全"])

    def test_deepseek_completion_redacts_evidence_pack_by_default(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="editor",
                current_context="key sk-1234567890abcdef",
                evidence_pack=(
                    {
                        "rawText": "不要出现这个原文 sk-abcdef1234567890",
                        "evidencePreview": "/Users/undo/private/file.txt user@example.com",
                        "surfaceHints": ["真实候选"],
                    },
                ),
            )
        )
        prompt_blob = "\n".join(item["content"] for item in messages)

        self.assertNotIn("sk-1234567890abcdef", prompt_blob)
        self.assertNotIn("sk-abcdef1234567890", prompt_blob)
        self.assertNotIn("/Users/undo/private/file.txt", prompt_blob)
        self.assertNotIn("user@example.com", prompt_blob)
        self.assertNotIn("不要出现这个原文", prompt_blob)
        self.assertIn("[REDACTED_SECRET]", prompt_blob)


def _provider(chunks: list[object]) -> DeepSeekV4FlashCompletionProvider:
    return DeepSeekV4FlashCompletionProvider(
        DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
        urlopen=lambda request, timeout: _FakeResponse(chunks),
        enforce_runtime_flags=False,
    )


def _sse_delta(content: str) -> str:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n"


class _FakeResponse:
    def __init__(self, chunks: list[object]):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield str(chunk).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
