from __future__ import annotations

import json
import time
import unittest
from urllib.error import HTTPError

import rag_ime.deepseek_completion as deepseek_completion_module
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
        self.assertEqual(user_payload["contextPacket"], {})
        self.assertEqual(user_payload["outputFormat"]["candidate"], "短候选")
        self.assertEqual(user_payload["maxChars"], 24)
        self.assertIn("4~24", messages[0]["content"])
        self.assertEqual(user_payload["evidencePack"][0]["surfaceHints"], ["BM25加向量召回"])

    def test_deepseek_completion_respects_custom_candidate_length_budget(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", max_chars=12)
        )
        user_payload = json.loads(messages[1]["content"])

        self.assertIn("4 到 12", user_payload["task"])
        self.assertIn("以“候选=”开头", messages[0]["content"])
        self.assertNotIn("你生成的实际候选", messages[0]["content"])
        self.assertNotIn("候选=你的候选", messages[1]["content"])

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

    def test_deepseek_completion_parses_candidate_json_object(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"schemaVersion":"rag-ime.smart-rag-candidates.v1","candidates":[{"surfaceText":"上下文包优化","insertText":"上下文包优化"}]}'),
                "data: [DONE]\n",
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["上下文包优化"])

    def test_deepseek_completion_accepts_plain_short_candidate(self) -> None:
        provider = _provider([_sse_delta("RAG输入法优化\n"), "data: [DONE]\n"])

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["RAG输入法优化"])
        self.assertEqual(deltas[0].metadata["parseMode"], "content")

    def test_deepseek_completion_parses_candidate_assignment_content(self) -> None:
        provider = _provider([_sse_delta("候选=修复LLM显示。\n"), "data: [DONE]\n"])

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="输入法")))

        self.assertEqual([item.text for item in deltas], ["修复LLM显示"])
        self.assertEqual(deltas[0].metadata["parseMode"], "content")

    def test_active_rag_exposes_progressive_text_before_candidate_finishes(self) -> None:
        provider = _provider(
            [
                _sse_delta("候选=流式"),
                _sse_delta("内容逐步返回。"),
                "data: [DONE]\n",
            ]
        )
        partials: list[str] = []

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法", max_chars=120),
                on_text_delta=partials.append,
            )
        )

        self.assertEqual(partials, ["流式", "流式内容逐步返回。"])
        self.assertEqual([item.text for item in deltas], ["流式内容逐步返回"])

    def test_deepseek_completion_falls_back_to_reasoning_candidate_json(self) -> None:
        provider = _provider(
            [
                _sse_reasoning('推理中。我的回答应该是一行JSON：{"candidate":"优化生成链路","role":"phrase"}。'),
                "data: [DONE]\n",
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["优化生成链路"])
        self.assertEqual(deltas[0].metadata["parseMode"], "reasoning_fallback")

    def test_deepseek_completion_extracts_reasoning_candidate_assignment(self) -> None:
        provider = _provider([_sse_reasoning("候选=修复DeepSeek输出。"), "data: [DONE]\n"])

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="输出修复")))

        self.assertEqual([item.text for item in deltas], ["修复DeepSeek输出"])
        self.assertEqual(deltas[0].metadata["parseMode"], "reasoning_fallback")

    def test_deepseek_completion_rejects_ascii_placeholder_assignment(self) -> None:
        provider = _provider([_sse_reasoning("候选=XXX。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="LLM没有输出，现在只要一个框")
            )
        )

        self.assertEqual([item.text for item in deltas], ["修复LLM输出"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_active_rag_request_fallback_can_return_paragraph(self) -> None:
        provider = _provider([_sse_reasoning("候选=XXX。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="Ctrl+Enter不行，DeepSeek没输出，LLM不显示",
                    selected_text="DeepSeek 输出我希望是一段话",
                    max_chars=120,
                )
            )
        )

        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")
        self.assertGreaterEqual(len(deltas[0].text), 40)
        self.assertLessEqual(len(deltas[0].text), 120)
        self.assertIn("一段完整正文", deltas[0].text)

    def test_deepseek_completion_rejects_chinese_placeholder_assignment(self) -> None:
        provider = _provider([_sse_reasoning("候选=你的候选。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_format_prefix_as_candidate(self) -> None:
        provider = _provider([_sse_reasoning("最终输出格式是“候选=”。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_angle_placeholder_candidate(self) -> None:
        provider = _provider([_sse_reasoning("最终输出应为候选=<候选内容>。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_generic_prompt_candidate_content(self) -> None:
        provider = _provider([_sse_delta("的候选短语\n"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_repeated_candidate_word_content(self) -> None:
        provider = _provider([_sse_delta("候选的流式候选\n"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_reasoning_notebook_list_fragment(self) -> None:
        provider = _provider([_sse_reasoning("Notebook有三条： 1. LLM显示问题。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_reasoning_analysis_sentence(self) -> None:
        provider = _provider([_sse_reasoning("我在分析，等。所以主题是RAG输入法。用户写了需求。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_rejects_context_packet_field_leak(self) -> None:
        provider = _provider([_sse_reasoning("- oneRing: 只有一个事件:"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果")
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_deepseek_completion_prompt_can_include_context_packet_for_non_active_scenes(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="editor",
                current_context="正在测试 ContextPacket",
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "currentInput": {"committedTail": "正在测试 ContextPacket"},
                    "notebook": {"items": [{"summary": "Smart RAG 使用 Notebook"}]},
                },
            )
        )
        user_payload = json.loads(messages[1]["content"])

        self.assertEqual(user_payload["contextPacket"]["schemaVersion"], "rag-ime.smart-context-packet.v1")
        self.assertIn("CurrentInput > OneRing > Timeline > Notebook", messages[0]["content"])

    def test_active_rag_prompt_uses_compact_evidence_hints(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="正在测试 ContextPacket",
                evidence_pack=({"surfaceHints": ["生成按钮稳定显示"], "tags": ["RAG", "输入法"]},),
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "notebook": {"items": [{"summary": "很长的 Notebook"}]},
                },
            )
        )
        user_payload = json.loads(messages[1]["content"])

        self.assertEqual(user_payload["contextPacket"]["schemaVersion"], "rag-ime.smart-context-packet.v1")
        self.assertIn("生成按钮稳定显示", user_payload["evidenceHints"])
        self.assertNotIn("候选是“短候选”", messages[0]["content"])
        self.assertIn("以“候选=”开头", messages[0]["content"])
        self.assertIn("currentInput", messages[0]["content"])
        self.assertIn("selectedText 在 insert_after_selection/append_at_cursor 场景只是光标前文本锚点", messages[0]["content"])
        self.assertIn("禁止以“例如”“比如”“可以描述”", messages[0]["content"])
        self.assertIn("不要以“例如/比如/可以描述/当用户输入/系统会”开头", user_payload["task"])
        self.assertEqual(user_payload["placement"], "insert_after_selection")

    def test_active_rag_rejects_explanatory_example_paragraph(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "候选=例如，可以描述如何将离线整理的 DeepSeek 结果通过流式候选机制实时展示在 Squirrel 输入法候选栏中。",
                    }
                }
            ]
        }
        provider = _provider([json.dumps(payload, ensure_ascii=False)])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    selected_text="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    evidence_pack=({"surfaceHints": ["RAG 输入法真实历史整理摘要"], "tags": ["RAG", "输入法"]},),
                    max_candidates=1,
                    max_chars=120,
                )
            )
        )

        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")
        self.assertFalse(deltas[0].text.startswith("例如"))
        self.assertNotIn("可以描述", deltas[0].text)

    def test_active_rag_strips_example_prefix_from_real_paragraph(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "候选=例如在测试中，我注意到 RAG 记忆能有效补全上下文，让 DeepSeek 生成更贴合当前场景的说明。",
                    }
                }
            ]
        }
        provider = _provider([json.dumps(payload, ensure_ascii=False)])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    selected_text="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    max_candidates=1,
                    max_chars=120,
                )
            )
        )

        self.assertEqual(deltas[0].metadata["parseMode"], "content")
        self.assertEqual(deltas[0].text, "在测试中，我注意到 RAG 记忆能有效补全上下文，让 DeepSeek 生成更贴合当前场景的说明")

    def test_active_rag_allows_product_terms_in_real_paragraph(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "候选=例如在测试中，DeepSeek 会结合近期整理的流式候选和真实 Squirrel/Rime 链路，生成一段连贯的说明文字。",
                    }
                }
            ]
        }
        provider = _provider([json.dumps(payload, ensure_ascii=False)])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    selected_text="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    max_candidates=1,
                    max_chars=120,
                )
            )
        )

        self.assertEqual(deltas[0].metadata["parseMode"], "content")
        self.assertIn("Squirrel/Rime 链路", deltas[0].text)

    def test_active_rag_paragraph_allows_candidate_quality_terms(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "候选=可以结合近期整理的 DeepSeek 离线数据和流式候选机制，在真实 Squirrel/Rime 链路上验证候选质量，并用于面试展示。",
                    }
                }
            ]
        }
        provider = _provider([json.dumps(payload, ensure_ascii=False)])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    selected_text="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    max_candidates=1,
                    max_chars=120,
                )
            )
        )

        self.assertEqual(deltas[0].metadata["parseMode"], "content")
        self.assertIn("流式候选机制", deltas[0].text)

    def test_active_rag_fallback_handles_llm_display_and_rag_context(self) -> None:
        provider = _provider([_sse_reasoning("候选=XXX。"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="LLM不显示，RAG能命中，并且DeepSeek需要根据笔记本预测",
                    selected_text="LLM不显示",
                    max_candidates=3,
                )
            )
        )

        self.assertIn("修复LLM显示", [item.text for item in deltas])

    def test_active_rag_request_fallback_prioritizes_current_context_over_old_evidence(self) -> None:
        provider = _provider([_sse_delta("的候选短语\n"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法需要让RAG能命中，并且DeepSeek根据记忆笔记本和当前输入上下文预测",
                    selected_text="DeepSeek生成",
                    evidence_pack=(
                        {
                            "evidencePreview": "历史问题：LLM不显示、模型没输出。",
                            "surfaceHints": ["修复LLM显示"],
                            "tags": ["LLM", "RAG"],
                        },
                    ),
                    max_candidates=1,
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["接入RAG上下文"])

    def test_active_rag_request_fallback_handles_interview_showcase_intent(self) -> None:
        provider = _provider([_sse_delta("的候选短语\n"), "data: [DONE]\n"])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法 RAG 面试展示怎么讲，候选怎么体现记忆和历史整理",
                    max_candidates=1,
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["RAG 输入法面试展示主线"])

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

    def test_active_rag_allows_keyword_reuse_without_exact_echo(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"生成按钮优化","role":"phrase"}\\n'),
                _sse_delta('{"candidate":"DeepSeek生成按钮和RAG记忆上下文","role":"phrase"}\\n'),
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="今天测试 DeepSeek 生成按钮和 RAG 记忆上下文",
                    selected_text="DeepSeek 生成按钮和 RAG 记忆上下文",
                    max_candidates=2,
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["生成按钮优化"])

    def test_deepseek_completion_timeout_returns_partial_candidates(self) -> None:
        provider = _provider(
            [
                _sse_delta('{"candidate":"DeepSeek流式补全","role":"phrase"}\\n'),
                TimeoutError("slow stream"),
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["DeepSeek流式补全"])

    def test_deepseek_completion_timeout_keeps_reasoning_fallback_candidate(self) -> None:
        provider = _provider(
            [
                _sse_reasoning('已经想好一行JSON：{"candidate":"修复生成链路","role":"phrase"}。'),
                TimeoutError("slow stream"),
            ]
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法")))

        self.assertEqual([item.text for item in deltas], ["修复生成链路"])
        self.assertEqual(deltas[0].metadata["parseMode"], "reasoning_fallback")

    def test_active_rag_empty_remote_content_has_governed_request_fallback(self) -> None:
        provider = _provider([])

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法需要稳定显示 DeepSeek 生成结果",
                    selected_text="生成按钮优化",
                    evidence_pack=({"surfaceHints": ["生成按钮稳定显示"], "tags": ["RAG", "输入法"]},),
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定生成按钮"])
        self.assertEqual(deltas[0].metadata["parseMode"], "request_fallback")

    def test_post_commit_empty_remote_content_has_no_request_fallback(self) -> None:
        provider = _provider([])

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法")))

        self.assertEqual(deltas, [])

    def test_deepseek_completion_reasoning_fallback_ignores_prompt_placeholder(self) -> None:
        provider = _provider(
            [
                _sse_reasoning(
                    '提示里有JSON格式{"candidate":"短候选","role":"phrase"}。'
                    '可能的候选：比如“，所以”。可能的候选：比如“生成按钮显示优化”。我决定生成“提升按钮稳定性”。'
                ),
                TimeoutError("slow stream"),
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="按钮不稳定", max_candidates=2)
            )
        )

        self.assertEqual([item.text for item in deltas], ["提升按钮稳定性", "生成按钮显示优化"])
        self.assertTrue(all(item.metadata["parseMode"] == "reasoning_fallback" for item in deltas))

    def test_active_rag_reasoning_fallback_extracts_short_considered_candidate(self) -> None:
        provider = _provider(
            [
                _sse_reasoning('考虑：“生成按钮稳定显示” 是参考中的一部分，但更适合做候选。'),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法需要稳定显示 DeepSeek 生成结果",
                    selected_text="生成按钮优化",
                    evidence_pack=({"surfaceHints": ["RAG 输入法生成按钮稳定显示"]},),
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["生成按钮稳定显示"])

    def test_reasoning_fallback_ignores_prompt_json_arrays_before_examples(self) -> None:
        provider = _provider(
            [
                _sse_reasoning(
                    '输入是 {"evidenceHints":["RAG 输入法生成按钮稳定显示","输入法 RAG"]}。'
                    '例如：“稳定显示生成按钮”或者“RAG输入法优化”。'
                ),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法需要稳定显示 DeepSeek 生成结果",
                    selected_text="生成按钮优化",
                    evidence_pack=({"surfaceHints": ["RAG 输入法生成按钮稳定显示"]},),
                    max_candidates=2,
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定显示生成按钮"])

    def test_reasoning_fallback_rejects_prompt_field_name_fragments(self) -> None:
        provider = _provider(
            [
                _sse_reasoning('候选是 selectedText 是。比如“生成按钮稳定显示”。'),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", selected_text="生成按钮优化")
            )
        )

        self.assertEqual([item.text for item in deltas], ["生成按钮稳定显示"])

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

    def test_deepseek_default_transport_uses_direct_no_proxy_opener_and_scene_budget(self) -> None:
        class FakeDirectOpener:
            def __init__(self) -> None:
                self.calls: list[tuple[object, float | None]] = []
                self.body: dict[str, object] = {}

            def open(self, request, timeout=None):
                self.calls.append((request, timeout))
                self.body = json.loads(request.data.decode("utf-8"))
                return _FakeResponse([_sse_delta('{"candidate":"直连低延迟","role":"phrase"}\\n')])

        fake = FakeDirectOpener()
        original = deepseek_completion_module._DIRECT_DEEPSEEK_OPENER
        try:
            deepseek_completion_module._DIRECT_DEEPSEEK_OPENER = fake
            provider = DeepSeekV4FlashCompletionProvider(
                DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
                enforce_runtime_flags=False,
            )

            deltas = list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", latency_budget_ms=1234)
                )
            )
        finally:
            deepseek_completion_module._DIRECT_DEEPSEEK_OPENER = original

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(int(fake.body["max_tokens"]), 1024)
        self.assertEqual(fake.body["reasoning_effort"], "low")
        self.assertTrue(fake.body["stream"])
        self.assertEqual(fake.calls[0][1], 1.234)

    def test_deepseek_stream_body_respects_config_stream_flag(self) -> None:
        fake = _BodyCaptureOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
                stream=True,
            ),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="输入法")))

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertTrue(fake.body["stream"])

    def test_deepseek_reasoning_stream_respects_wall_clock_budget(self) -> None:
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
                stream=True,
            ),
            urlopen=lambda request, timeout: _SlowReasoningResponse(
                [
                    _sse_reasoning('已经想好一行JSON：{"candidate":"预算内候选","role":"phrase"}。'),
                    _sse_reasoning("后面还在继续长思考。"),
                ],
                delay_seconds=0.12,
            ),
            enforce_runtime_flags=False,
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", latency_budget_ms=100)
            )
        )

        self.assertEqual([item.text for item in deltas], ["预算内候选"])
        self.assertEqual(deltas[0].metadata["parseMode"], "reasoning_fallback")

    def test_deepseek_max_tokens_can_be_limited_for_low_thinking_scene(self) -> None:
        fake = _BodyCaptureOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
                max_tokens=48,
            ),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="输入法")))

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertLessEqual(int(fake.body["max_tokens"]), 48)

    def test_active_rag_completion_uses_explicit_large_token_cap(self) -> None:
        fake = _BodyCaptureOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
                max_tokens=96,
                active_rag_max_tokens=1024,
            ),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", max_candidates=3)
            )
        )

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertEqual(int(fake.body["max_tokens"]), 1024)
        self.assertEqual(fake.body["reasoning_effort"], "low")

    def test_active_rag_completion_can_be_explicitly_limited_without_touching_hot_path_cap(self) -> None:
        fake = _BodyCaptureOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
                max_tokens=96,
                active_rag_max_tokens=512,
            ),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="输入法")))

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertEqual(int(fake.body["max_tokens"]), 512)

    def test_deepseek_completion_retries_without_reasoning_effort_when_gateway_rejects_it(self) -> None:
        fake = _RetryWithoutReasoningOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="输入法")))

        self.assertEqual([item.text for item in deltas], ["低思考候选"])
        self.assertEqual(len(fake.bodies), 2)
        self.assertEqual(fake.bodies[0]["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", fake.bodies[1])

    def test_active_rag_request_fallback_exposes_gateway_error_reason(self) -> None:
        fake = _AlwaysHttpErrorOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果",
                )
            )
        )

        self.assertEqual([item.text for item in deltas], ["稳定DeepSeek生成"])
        self.assertEqual(deltas[0].metadata["fallbackReason"], "http_403:bad_response_status_code")


def _provider(chunks: list[object]) -> DeepSeekV4FlashCompletionProvider:
    return DeepSeekV4FlashCompletionProvider(
        DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
        urlopen=lambda request, timeout: _FakeResponse(chunks),
        enforce_runtime_flags=False,
    )


def _sse_delta(content: str) -> str:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n"


def _sse_reasoning(content: str) -> str:
    payload = {"choices": [{"delta": {"content": None, "reasoning_content": content}}]}
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


class _SlowReasoningResponse(_FakeResponse):
    def __init__(self, chunks: list[object], *, delay_seconds: float):
        super().__init__(chunks)
        self.delay_seconds = delay_seconds

    def __iter__(self):
        for chunk in self.chunks:
            time.sleep(self.delay_seconds)
            if isinstance(chunk, BaseException):
                raise chunk
            yield str(chunk).encode("utf-8")


class _BodyCaptureOpener:
    def __init__(self) -> None:
        self.body: dict[str, object] = {}

    def open(self, request, timeout=None):
        _ = timeout
        self.body = json.loads(request.data.decode("utf-8"))
        return _FakeResponse([_sse_delta('{"candidate":"直连低延迟","role":"phrase"}\\n')])


class _RetryWithoutReasoningOpener:
    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []

    def open(self, request, timeout=None):
        _ = timeout
        body = json.loads(request.data.decode("utf-8"))
        self.bodies.append(body)
        if "reasoning_effort" in body:
            raise HTTPError(
                request.full_url,
                400,
                "unsupported reasoning_effort",
                hdrs={},
                fp=None,
            )
        return _FakeResponse([_sse_delta('{"candidate":"低思考候选","role":"phrase"}\\n')])


class _AlwaysHttpErrorOpener:
    def open(self, request, timeout=None):
        _ = timeout
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs={},
            fp=_FakeErrorBody(b'{"error":{"message":"openai_error","code":"bad_response_status_code"}}'),
        )


class _FakeErrorBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, size=-1) -> bytes:
        _ = size
        return self.payload

    def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
