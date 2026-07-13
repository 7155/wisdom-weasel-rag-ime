from __future__ import annotations

import json
import time
import unittest
from urllib.error import HTTPError

import rag_ime.deepseek_completion as deepseek_completion_module
from rag_ime.deepseek_completion import (
    DeepSeekCompletionError,
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
        self.assertEqual(user_payload["groundingMode"], "foreground_only")
        self.assertIn("唯一语义来源", messages[0]["content"])

    def test_active_rag_unlimited_prompt_requests_complete_multi_paragraph_output(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(scene="active_rag", current_context="请写一份完整说明", max_chars=0)
        )
        user_payload = json.loads(messages[1]["content"])

        self.assertEqual(user_payload["maxChars"], 0)
        self.assertIn("不设字符上限", user_payload["task"])
        self.assertIn("后续可以换行分段", user_payload["task"])
        self.assertNotIn("只输出一行", user_payload["task"])

    def test_active_rag_foreground_only_rejects_unrequested_character_recommendations(self) -> None:
        provider = _provider(
            [_sse_delta("候选=推荐初音未来、洛天依或绊爱作为二次元形象。\n"), "data: [DONE]\n"]
        )

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content"):
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="这里是前台上下文测试",
                        max_chars=120,
                    )
                )
            )

    def test_active_rag_foreground_only_rejects_unsupported_api_credential_diagnosis(self) -> None:
        provider = _provider(
            [_sse_delta("候选=可能是 API 密钥配置有误，建议检查认证参数。\n"), "data: [DONE]\n"]
        )

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content"):
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="语音设置要支持不同 API，生成结果也要稳定出现。",
                        max_chars=120,
                    )
                )
            )

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
        self.assertEqual([item.text for item in deltas], ["流式内容逐步返回。"])

    def test_active_rag_preserves_unlimited_multi_paragraph_stream(self) -> None:
        first = "第一段给出结论，并把当前问题的核心边界说明清楚。" * 4
        second = "第二段继续补充实现步骤、验收方式和失败恢复策略。" * 4
        provider = _provider(
            [
                _sse_delta(f"候选={first}"),
                _sse_delta(f"\n\n{second}"),
                "data: [DONE]\n",
            ]
        )
        partials: list[str] = []

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="请写完整说明", max_chars=0),
                on_text_delta=partials.append,
            )
        )

        expected = f"{first}\n\n{second}"
        self.assertGreater(len(expected), 180)
        self.assertEqual([item.text for item in deltas], [expected])
        self.assertEqual(deltas[0].insert_text, expected)
        self.assertEqual(partials[-1], expected)

    def test_active_rag_never_streams_or_returns_thinking_content(self) -> None:
        provider = _provider(
            [
                _sse_delta("候选=我需要先分析用户的真实意图，"),
                _sse_delta("再决定如何回答。\n"),
                "data: [DONE]\n",
            ]
        )
        partials: list[str] = []

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content"):
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(scene="active_rag", current_context="继续完善输入法", max_chars=120),
                    on_text_delta=partials.append,
                )
            )

        self.assertEqual(partials, [])

    def test_active_rag_never_uses_reasoning_channel_as_visible_output(self) -> None:
        reasoning_values = (
            '推理中。我的回答应该是一行JSON：{"candidate":"优化生成链路","role":"phrase"}。',
            "候选=修复生成输出。",
            "Notebook有三条：1. LLM显示问题。",
            "- oneRing: 只有一个事件:",
        )
        for reasoning in reasoning_values:
            with self.subTest(reasoning=reasoning):
                provider = _provider([_sse_reasoning(reasoning), "data: [DONE]\n"])
                with self.assertRaisesRegex(DeepSeekCompletionError, "empty_remote_content"):
                    list(
                        provider.stream_candidates(
                            DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法", max_chars=120)
                        )
                    )

    def test_active_rag_rejects_placeholder_and_prompt_leak_content(self) -> None:
        rejected_values = (
            "候选=<think>We need analyze the user request first.</think>",
            "候选=XXX。",
            "候选=你的候选。",
            "候选=<候选内容>。",
            "的候选短语",
            "候选的流式候选",
            "候选=没有有效内容，请重试。",
            "候选=未检索到有效内容。",
            "候选=无有效候选。",
        )
        for value in rejected_values:
            with self.subTest(value=value):
                provider = _provider([_sse_delta(value + "\n"), "data: [DONE]\n"])
                with self.assertRaises(DeepSeekCompletionError):
                    list(
                        provider.stream_candidates(
                            DeepSeekCompletionRequest(scene="active_rag", current_context="输入法生成结果", max_chars=120)
                        )
                    )

    def test_active_rag_rejects_meta_echo_in_reported_regression(self) -> None:
        provider = _provider(
            [
                _sse_delta(
                    "候选=我会围绕“豆包 api你看看最后会不会有改正前面流式输出的一步”继续补全当前表达，把上下文里的真实意图整理成一段可放到光标后的中文正文。\n"
                ),
                "data: [DONE]\n",
            ]
        )
        partials: list[str] = []

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content"):
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="豆包 api你看看最后会不会有改正前面流式输出的一步",
                        max_chars=160,
                    ),
                    on_text_delta=partials.append,
                )
            )

        self.assertEqual(partials, [])

    def test_active_rag_valid_direct_answer_is_insertable(self) -> None:
        provider = _provider(
            [
                _sse_delta("候选=会。开启二次识别后，最终完整结果会替换前面的临时转写，而不是继续追加。\n"),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="豆包 API 最后会不会改正前面流式输出？",
                    max_chars=120,
                )
            )
        )

        self.assertEqual(len(deltas), 1)
        self.assertTrue(deltas[0].text.startswith("会。开启二次识别后"))

    def test_active_rag_allows_local_constraint_overlap_in_a_new_answer(self) -> None:
        provider = _provider(
            [
                _sse_delta(
                    "候选=输入法前台必须保证生成中状态不闪退，生成失败时提供可重试反馈，成功结果需保留到用户主动插入、重试或关闭，确保交互反馈及时且可预测。"
                ),
                "data: [DONE]\n",
            ]
        )
        current_context = (
            "生成中状态不能闪退，生成失败必须给出可重试反馈，"
            "成功结果必须保留到用户主动插入、重试或关闭。"
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context=current_context,
                    selected_text="请总结输入法反馈的稳定性要求",
                    max_chars=180,
                )
            )
        )

        self.assertEqual(len(deltas), 1)
        self.assertIn("生成失败时提供可重试反馈", deltas[0].text)

    def test_active_rag_reuses_last_fully_governed_stream_when_trailing_meta_is_rejected(self) -> None:
        provider = _provider(
            [
                _sse_delta("候选=失败反馈应保持可见，成功结果应保留到用户主动确认。"),
                _sse_delta(" selectedText"),
                "data: [DONE]\n",
            ]
        )
        partials: list[str] = []

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="正在整理输入法交互要求",
                    max_chars=120,
                ),
                on_text_delta=partials.append,
            )
        )

        self.assertEqual(partials, ["失败反馈应保持可见，成功结果应保留到用户主动确认。"])
        self.assertEqual([item.text for item in deltas], [partials[-1]])
        self.assertEqual(deltas[0].metadata["parseMode"], "content")
        self.assertNotIn("selectedText", deltas[0].text)

    def test_active_rag_never_promotes_truncated_stream_without_final_punctuation(self) -> None:
        safe_prefix = "失败反馈保持可见且支持重试，成功结果等待用户主动确认"
        provider = _provider(
            [
                _sse_delta(f"候选={safe_prefix}"),
                _sse_delta(" selectedText"),
                "data: [DONE]\n",
            ]
        )

        partials: list[str] = []
        with self.assertRaises(DeepSeekCompletionError) as raised:
            list(provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="正在整理输入法交互要求",
                        max_chars=120,
                    ),
                    on_text_delta=partials.append,
                ))

        self.assertGreaterEqual(len(safe_prefix), 24)
        self.assertEqual(partials, [safe_prefix])
        self.assertEqual(raised.exception.diagnostics["safePartialChars"], len(safe_prefix))
        self.assertTrue(raised.exception.diagnostics["continuationAttempted"])

    def test_active_rag_rejects_incomplete_plain_stream_when_gateway_omits_protocol_marker(self) -> None:
        safe_prefix = "远程正文已经开始返回，连接中断后仍应保留给用户确认"
        provider = _provider(
            [
                _sse_delta(safe_prefix),
                TimeoutError("stream closed after content"),
            ]
        )
        partials: list[str] = []

        with self.assertRaises(DeepSeekCompletionError) as raised:
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="请生成一段可以直接插入的说明",
                        max_chars=0,
                    ),
                    on_text_delta=partials.append,
                )
            )

        self.assertEqual(partials, [safe_prefix])
        self.assertEqual(raised.exception.diagnostics["safePartialChars"], len(safe_prefix))
        self.assertTrue(raised.exception.diagnostics["continuationAttempted"])

    def test_active_rag_continues_interrupted_paragraph_to_sentence_boundary(self) -> None:
        prefix = "先检查模型请求日志，确认卡点位于远程生成还是检索阶段。如果检索正常但模型一直"
        suffix = "没有结束，就保留已返回正文并发起一次续写，直到得到完整句号。"
        opener = _SequenceOpener(
            [
                [_sse_delta(f"候选={prefix}"), _sse_finish("length"), "data: [DONE]\n"],
                [_sse_delta(suffix), _sse_finish("stop"), "data: [DONE]\n"],
            ]
        )
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key"),
            urlopen=opener.open,
            enforce_runtime_flags=False,
        )
        partials: list[str] = []

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="请检查为什么远程生成只返回半句",
                    max_chars=0,
                    latency_budget_ms=5000,
                ),
                on_text_delta=partials.append,
            )
        )

        expected = f"{prefix}{suffix}"
        self.assertEqual(partials, [prefix, expected])
        self.assertEqual([item.text for item in deltas], [expected])
        self.assertEqual(len(opener.bodies), 2)
        self.assertEqual(deltas[0].metadata["finishReason"], "stop")
        self.assertTrue(deltas[0].metadata["continuationAttempted"])
        self.assertTrue(deltas[0].metadata["continuationAdvanced"])
        self.assertTrue(deltas[0].metadata["continuationCompleted"])

    def test_active_rag_does_not_publish_tiny_plain_stream_fragment(self) -> None:
        provider = _provider([_sse_delta("先处理"), TimeoutError("stream closed")])
        partials: list[str] = []

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content") as caught:
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="请生成完整说明",
                        max_chars=0,
                    ),
                    on_text_delta=partials.append,
                )
            )

        self.assertEqual(partials, ["先处理"])
        self.assertEqual(caught.exception.diagnostics["terminalReason"], "governor_rejected_content")
        self.assertEqual(caught.exception.diagnostics["transportReason"], "timeout")
        self.assertGreaterEqual(caught.exception.diagnostics["contentChars"], 3)
        self.assertEqual(caught.exception.diagnostics["safePartialChars"], 3)
        self.assertTrue(caught.exception.diagnostics["continuationAttempted"])

    def test_active_rag_still_rejects_high_ratio_context_copy(self) -> None:
        echoed = "失败反馈应保持可见，成功结果应保留到用户主动确认。"
        provider = _provider([_sse_delta(f"候选={echoed}"), "data: [DONE]\n"])

        with self.assertRaisesRegex(DeepSeekCompletionError, "governor_rejected_content"):
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context=f"当前原句是：{echoed}",
                        max_chars=120,
                    )
                )
            )

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
        self.assertIn("问句、关键词命中或 recent_input_context", messages[0]["content"])
        self.assertIn("RAG 没有相关证据时仍要依据 currentRequest/currentContext", messages[0]["content"])
        self.assertIn("禁止把“没有有效内容”", messages[0]["content"])
        self.assertIn("不要以“例如/比如/可以描述/当用户输入/系统会”开头", user_payload["task"])
        self.assertIn("RAG 为空不妨碍完成非事实型请求", user_payload["task"])
        self.assertIn("给出具体核验动作", user_payload["task"])
        self.assertEqual(user_payload["placement"], "insert_after_selection")

    def test_active_rag_prompt_keeps_recent_inputs_as_secondary_context(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="这个如何继续",
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "currentInput": {"committedTail": "这个如何继续"},
                    "oneRing": {
                        "role": "continuity_context",
                        "maySupportIntent": True,
                        "maySupportFacts": False,
                        "events": [
                            {"textPreview": "刚才在讨论输入法如何稳定获取前台上下文"},
                            {"textPreview": "还需要把历史输入作为次级连续性信息"},
                        ],
                    },
                },
            )
        )
        user_payload = json.loads(messages[1]["content"])

        self.assertEqual(user_payload["groundingMode"], "foreground_with_history")
        self.assertEqual(
            [item["textPreview"] for item in user_payload["contextPacket"]["recentCompleteInputs"]],
            ["刚才在讨论输入法如何稳定获取前台上下文", "还需要把历史输入作为次级连续性信息"],
        )
        self.assertTrue(user_payload["contextPacket"]["recentInputPolicy"]["maySupportIntent"])
        self.assertFalse(user_payload["contextPacket"]["recentInputPolicy"]["maySupportFacts"])
        self.assertIn("当前输入优先且历史不能充当事实证据", user_payload["task"])

    def test_active_rag_keeps_explanatory_technical_paragraph(self) -> None:
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

        deltas = list(provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    selected_text="我现在测试输入法，想让 DeepSeek 根据 RAG 记忆生成一段自然的后续说明",
                    evidence_pack=({"surfaceHints": ["RAG 输入法真实历史整理摘要"], "tags": ["RAG", "输入法"]},),
                    max_candidates=1,
                    max_chars=120,
                )
            ))

        self.assertEqual(len(deltas), 1)
        self.assertIn("DeepSeek 结果通过流式候选机制", deltas[0].text)

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
        self.assertEqual(deltas[0].text, "在测试中，我注意到 RAG 记忆能有效补全上下文，让 DeepSeek 生成更贴合当前场景的说明。")

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

    def test_active_rag_long_form_allows_user_technical_terms_outside_short_allowlist(self) -> None:
        provider = _provider(
            [
                _sse_delta(
                    "候选=这条链路会让 Pi、MCP、OpenAI 和 WebSocket 保持可配置，"
                    "同时由当前上下文决定实际使用方式。"
                ),
                _sse_finish("stop"),
                "data: [DONE]\n",
            ]
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="请说明兼容服务的配置边界",
                    max_chars=0,
                )
            )
        )

        self.assertEqual(len(deltas), 1)
        self.assertIn("Pi、MCP、OpenAI 和 WebSocket", deltas[0].text)

    def test_active_rag_failure_names_the_governor_rule(self) -> None:
        provider = _provider(
            [_sse_delta("候选=我会先分析用户需要什么，再给出答案。"), _sse_finish("stop"), "data: [DONE]\n"]
        )

        with self.assertRaises(DeepSeekCompletionError) as raised:
            list(
                provider.stream_candidates(
                    DeepSeekCompletionRequest(
                        scene="active_rag",
                        current_context="请直接回答，不要描述过程",
                        max_chars=120,
                    )
                )
            )

        self.assertEqual(
            raised.exception.diagnostics["governorRejectionReason"],
            "reasoning_fragment",
        )

    def test_active_rag_rewrites_internally_broken_sentence_instead_of_appending(self) -> None:
        broken = "RAG 检索需要准确命中输入法定义的，确保最终结果完整。"
        repaired = "RAG 检索需要准确命中输入法相关记忆，并保证最终结果语义完整。"
        opener = _SequenceOpener(
            [
                [_sse_delta(f"候选={broken}"), _sse_finish("stop"), "data: [DONE]\n"],
                [_sse_delta(repaired), _sse_finish("stop"), "data: [DONE]\n"],
            ]
        )
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key"),
            urlopen=opener.open,
            enforce_runtime_flags=False,
        )
        partials: list[str] = []

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="修复生成正文里断裂的句子",
                    max_chars=0,
                    latency_budget_ms=5000,
                ),
                on_text_delta=partials.append,
            )
        )

        self.assertEqual([item.text for item in deltas], [repaired])
        self.assertEqual(partials, [broken, repaired])
        self.assertEqual(deltas[0].metadata["continuationMode"], "rewrite")
        self.assertTrue(deltas[0].metadata["continuationCompleted"])

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

    def test_active_rag_prompt_marks_question_as_answer_and_keeps_context_tail(self) -> None:
        prefix = "旧上下文。" * 220
        current_request = "豆包 API 你看看最后会不会改正前面流式输出？"
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context=prefix + current_request,
                max_chars=160,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertEqual(payload["taskMode"], "answer")
        self.assertTrue(payload["currentRequest"].endswith(current_request))
        self.assertTrue(payload["currentContext"].endswith(current_request))
        self.assertLessEqual(len(payload["currentContext"]), 4000)
        self.assertIn("直接回答 currentRequest", payload["task"])
        self.assertIn("taskMode 已由客户端确定", messages[0]["content"])

    def test_active_rag_prompt_prefers_selected_query_and_explicit_answer_intent(self) -> None:
        selected_request = "豆包 API 最后会不会改正前面的流式输出？"
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="很长的前台正文。" * 80 + selected_request,
                selected_text=selected_request,
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "currentInput": {"intent": "answer", "placement": "replace_selection"},
                    "outputContract": {"intent": "answer", "placement": "replace_selection"},
                },
                max_chars=160,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertEqual(payload["taskMode"], "answer")
        self.assertEqual(payload["currentRequest"], selected_request)

    def test_active_rag_short_anchor_uses_last_complete_context_clause(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="请把知识生成的上下文、证据和空结果恢复链路全部改正确。改正",
                selected_text="改正",
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "currentInput": {"intent": "complete", "placement": "insert_after_selection"},
                    "outputContract": {"intent": "complete", "placement": "insert_after_selection"},
                },
                max_chars=120,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertNotEqual(payload["currentRequest"], "改正")
        self.assertIn("空结果恢复链路", payload["currentRequest"])

    def test_active_rag_recovery_prompt_is_explicit_and_has_no_short_anchor(self) -> None:
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="请完成当前修复并给出可直接插入的结果。",
                selected_text="",
                recovery_mode=True,
                max_chars=120,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertTrue(payload["recoveryMode"])
        self.assertEqual(payload["selectedText"], "")
        self.assertIn("recoveryMode=true", messages[0]["content"])

    def test_active_rag_prompt_compacts_recalled_packet_text(self) -> None:
        old_memory = "不相关的旧记忆" * 200
        messages = build_deepseek_completion_messages(
            DeepSeekCompletionRequest(
                scene="active_rag",
                current_context="当前请求",
                context_packet={
                    "schemaVersion": "rag-ime.smart-context-packet.v1",
                    "currentInput": {"intent": "complete", "placement": "insert_after_selection"},
                    "oneRing": {"events": [{"text": old_memory}]},
                    "timeline": {"recentDecisions": [{"summary": old_memory}]},
                    "notebook": {"items": [{"summary": old_memory}]},
                },
                max_chars=160,
            )
        )
        payload = json.loads(messages[1]["content"])

        self.assertNotIn(old_memory, messages[1]["content"])
        self.assertEqual(
            payload["contextPacket"]["memoryCounts"],
            {"oneRing": 1, "timeline": 1, "notebook": 1, "planning": 0},
        )

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

    def test_deepseek_completion_timeout_drops_reasoning_without_fabricating_output(self) -> None:
        provider = _provider(
            [
                _sse_reasoning('已经想好一行JSON：{"candidate":"修复生成链路","role":"phrase"}。'),
                TimeoutError("slow stream"),
            ]
        )

        with self.assertRaisesRegex(DeepSeekCompletionError, "timeout"):
            list(provider.stream_candidates(DeepSeekCompletionRequest(scene="active_rag", current_context="RAG 输入法")))

    def test_active_rag_empty_remote_content_is_a_retriable_error(self) -> None:
        provider = _provider([])

        with self.assertRaisesRegex(DeepSeekCompletionError, "empty_remote_content"):
            list(provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="输入法需要稳定显示 DeepSeek 生成结果",
                    selected_text="生成按钮优化",
                    evidence_pack=({"surfaceHints": ["生成按钮稳定显示"], "tags": ["RAG", "输入法"]},),
                )
            ))

    def test_post_commit_empty_remote_content_has_no_request_fallback(self) -> None:
        provider = _provider([])

        deltas = list(provider.stream_candidates(DeepSeekCompletionRequest(scene="post_commit", current_context="RAG 输入法")))

        self.assertEqual(deltas, [])

    def test_deepseek_completion_never_uses_reasoning_examples(self) -> None:
        provider = _provider(
            [
                _sse_reasoning(
                    '提示里有JSON格式{"candidate":"短候选","role":"phrase"}。'
                    '可能的候选：比如“，所以”。可能的候选：比如“生成按钮显示优化”。我决定生成“提升按钮稳定性”。'
                ),
                TimeoutError("slow stream"),
            ]
        )

        with self.assertRaises(DeepSeekCompletionError):
            list(provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="按钮不稳定", max_candidates=2)
            ))

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
        self.assertEqual(fake.body["max_tokens"], 4096)
        self.assertEqual(fake.body["reasoning_effort"], "low")
        self.assertTrue(fake.body["stream"])
        self.assertEqual(fake.calls[0][1], 1.234)
        self.assertTrue(deltas[0].metadata["proxyBypassed"])
        self.assertEqual(deltas[0].metadata["transportMode"], "direct_no_proxy")

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

        with self.assertRaisesRegex(DeepSeekCompletionError, "budget_elapsed"):
            list(provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", latency_budget_ms=100)
            ))

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

    def test_active_rag_default_sends_large_transport_token_budget(self) -> None:
        fake = _BodyCaptureOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(
                api_base_url="https://api.example.test/v1",
                api_key="test-key",
                model="deepseek-v4-flash",
            ),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        deltas = list(
            provider.stream_candidates(
                DeepSeekCompletionRequest(scene="active_rag", current_context="输入法", max_chars=24)
            )
        )

        self.assertEqual([item.text for item in deltas], ["直连低延迟"])
        self.assertEqual(fake.body["max_tokens"], 4096)

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

    def test_active_rag_gateway_error_is_exposed_without_fake_candidate(self) -> None:
        fake = _AlwaysHttpErrorOpener()
        provider = DeepSeekV4FlashCompletionProvider(
            DeepSeekConfig(api_base_url="https://api.example.test/v1", api_key="test-key", model="deepseek-v4-flash"),
            urlopen=fake.open,
            enforce_runtime_flags=False,
        )

        with self.assertRaisesRegex(DeepSeekCompletionError, "http_403:bad_response_status_code"):
            list(provider.stream_candidates(
                DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context="RAG 输入法需要稳定显示 DeepSeek 生成结果",
                )
            ))


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


def _sse_finish(reason: str) -> str:
    payload = {"choices": [{"delta": {}, "finish_reason": reason}]}
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


class _SequenceOpener:
    def __init__(self, responses: list[list[object]]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, object]] = []

    def open(self, request, timeout=None):
        _ = timeout
        self.bodies.append(json.loads(request.data.decode("utf-8")))
        if not self.responses:
            raise AssertionError("unexpected extra DeepSeek request")
        return _FakeResponse(self.responses.pop(0))


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
