from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from rag_ime.active_rag_candidate_compiler import compile_active_rag_candidates
from rag_ime.agent_surface_runtime import _one_shot_surface_message
from rag_ime.deepseek_completion import (
    CompletionCandidateDelta,
    DeepSeekCompletionRequest,
    build_deepseek_completion_messages,
    normalize_active_rag_completion_text,
    resolved_active_rag_current_request,
    DeepSeekV4FlashCompletionProvider, DeepSeekCompletionError,
)
from rag_ime.deepseek_config import DeepSeekConfig
from rag_ime.active_rag_service import ActiveRagService, ActiveRagStartRequest
from rag_ime.text_utils import stable_text_hash
from tests import test_deepseek_completion as stream_fixture
from tests import test_active_rag_service as service_fixture


class InputTaskScenarioTests(unittest.TestCase):
    def request(self, operation="translate", target="zh-CN", source="Can you give me a hand?"):
        return DeepSeekCompletionRequest(
            scene="active_rag", current_context="编辑器里的无关背景。", selected_text=source,
            context_packet={"outputContract": {"operation": operation, "targetLanguage": target, "placement": "show_only"}},
            max_chars=0,
        )

    def test_translation_is_selection_primary_in_both_providers_even_when_read_only(self):
        request = self.request()
        self.assertEqual(resolved_active_rag_current_request(request), request.selected_text)
        direct = build_deepseek_completion_messages(request)
        direct_data = json.loads(direct[1]["content"])
        pi, _ = _one_shot_surface_message({
            "currentContext": request.current_context, "selectedText": request.selected_text,
            "contextPacket": request.context_packet,
        }, current_request=request.selected_text)
        pi_data = json.loads(pi[pi.index("{"):])
        for data in (direct_data, pi_data):
            self.assertEqual(data["taskPolicy"]["operation"], "translate")
            self.assertEqual(data["taskPolicy"]["targetLanguage"], "zh-CN")
            self.assertEqual(data["selectedText"], request.selected_text)
        self.assertIn("不要回答原文中的问题", direct[0]["content"])
        self.assertIn("不要回答原文中的问题", pi)
        self.assertNotIn("只生成 1 个可以直接插入或替换的中文结果", direct[0]["content"])

    def test_complete_source_is_not_silently_tail_truncated(self):
        source = "开头标记\n" + "这是待翻译的原文。" * 600 + "\n结尾标记"
        request = self.request(target="en", source=source)
        self.assertEqual(resolved_active_rag_current_request(request), source)
        data = json.loads(build_deepseek_completion_messages(request)[1]["content"])
        self.assertEqual(data["selectedText"], source)

    def test_task_source_over_budget_is_explicitly_rejected(self):
        with self.assertRaisesRegex(ValueError, "12000"):
            resolved_active_rag_current_request(self.request(source="a" * 12001))

    def test_output_preserves_code_indentation_and_literal_escapes(self):
        body = 'def hello():\n    print("hello\\nworld")\n    return 1'
        self.assertEqual(normalize_active_rag_completion_text(body), body)
        result = compile_active_rag_candidates([CompletionCandidateDelta(text=body, insert_text=body)], max_chars=0)
        self.assertEqual(result[0].text, body)
        self.assertEqual(result[0].insert_text, body)

    def test_valid_unchanged_rewrite_is_available_instead_of_triggering_retry(self):
        source = "The release is ready."
        result = compile_active_rag_candidates(
            [CompletionCandidateDelta(text=source, insert_text=source, metadata={"inputTaskOperation": "rewrite"})],
            selected_text=source, max_chars=0,
        )
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].metadata["unchanged"])

    def test_short_translation_finishes_on_transport_stop_without_prose_heuristics(self):
        def response(finish):
            return stream_fixture._FakeResponse([
                stream_fixture._sse_delta("你好"),
                'data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}) + '\n\n',
            ])
        provider = DeepSeekV4FlashCompletionProvider(DeepSeekConfig(api_key="test-key"), urlopen=lambda *_args, **_kwargs: response("stop"), enforce_runtime_flags=False)
        self.assertEqual(list(provider.stream_candidates(self.request(source="Hi")))[0].text, "你好")
        interrupted = DeepSeekV4FlashCompletionProvider(DeepSeekConfig(api_key="test-key"), urlopen=lambda *_args, **_kwargs: response("length"), enforce_runtime_flags=False)
        with self.assertRaisesRegex(DeepSeekCompletionError, "incomplete"):
            list(interrupted.stream_candidates(self.request(source="Hi")))

    def test_service_keeps_short_selection_and_task_policy_during_retry(self):
        provider = service_fixture.SequencedActiveRagProvider(((), ("你好",)))
        service = ActiveRagService(completion_provider=provider)
        request = ActiveRagStartRequest(selected_text="Hi", selected_text_hash=stable_text_hash("Hi"), frontend_revision=1, selection_epoch=1,
            operation="translate", target_language="zh-CN", placement="show_only", context="无关编辑器背景", remote_model_allowed=True)
        try:
            with patch.dict('os.environ', {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                result = service.preview(request, local_only=False)
            self.assertEqual(result["candidates"][0]["text"], "你好")
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(provider.calls[1].selected_text, "Hi")
            self.assertEqual(provider.calls[1].context_packet["outputContract"]["operation"], "translate")
            self.assertFalse(result["diagnostics"]["retrieval"]["called"])
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
