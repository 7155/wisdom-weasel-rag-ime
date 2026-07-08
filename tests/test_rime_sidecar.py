from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.adapter import InputMethodAdapter
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputSuggestion, ModelPrediction
from rag_ime.rime_sidecar import (
    build_rime_sidecar_response,
    clear_model_prediction_holdover_cache,
    clear_prediction_manager_cache,
    clear_refresh_debounce_cache,
    filter_post_commit_model_completions,
    key_policy_for_prediction_session,
    record_rime_side_candidate_selection,
    wait_for_model_prediction_lane_idle,
)


class RecordingPredictionProvider:
    def __init__(self, predictions: list[str] | None = None, *, sleep_s: float = 0.0) -> None:
        self.predictions = predictions or ["真实输入链路跑通", "v1 范围收缩", "候选质量验收"]
        self.sleep_s = sleep_s
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> list[ModelPrediction]:
        self.calls += 1
        self.requests.append(dict(kwargs))
        if self.sleep_s > 0:
            time.sleep(self.sleep_s)
        max_candidates = int(kwargs.get("max_candidates") or 5)
        return [
            ModelPrediction(
                text=text,
                rank=index,
                provider_name="v1-contract-model",
                latency_ms=int(self.sleep_s * 1000),
                confidence=0.9,
            )
            for index, text in enumerate(self.predictions, start=1)
        ][:max_candidates]


class CuratedMemoryCore:
    def __init__(self, suggestions: list[InputSuggestion] | None = None) -> None:
        self.suggestions = suggestions or []
        self.calls = 0
        self.last_current_input = ""
        self.last_recent_context = ""

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        self.calls += 1
        self.last_current_input = current_input
        self.last_recent_context = recent_context
        return self.suggestions[:top_k]

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        return "历史输入只能给模型上下文，不能直接污染 RAG 候选"


def _memory(
    suggestion_id: str,
    text: str,
    *,
    source_type: str = "memory",
    accepted_count: int = 0,
    confidence: float = 0.92,
) -> InputSuggestion:
    return InputSuggestion(
        suggestion_id=suggestion_id,
        surface_text=text,
        suggestion_type="phrase",
        source_event_id=abs(hash(suggestion_id)) % 100000,
        evidence_preview="v1 contract fixture",
        confidence=confidence,
        metadata={
            "source_type": source_type,
            "state": {"accepted_count": accepted_count},
        },
    )


class RimeSidecarV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=1.0))
        clear_model_prediction_holdover_cache()
        clear_prediction_manager_cache()
        clear_refresh_debounce_cache()
        self.env = patch.dict(
            os.environ,
            {
                "RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION": "1",
                "RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL": "1",
                "RAG_IME_ENABLE_COMPOSING_MODEL": "0",
                "RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL": "0",
                "RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS": "150",
                "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "900",
                "RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS": "12000",
                "RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS": "250",
                "RAG_IME_POST_COMMIT_PRESENTATION_STREAM": "0",
                "RAG_IME_REFRESH_DEBOUNCE_MS": "0",
                "RAG_IME_PREDICTION_STATUS_ROW": "1",
            },
        )
        self.env.start()

    def tearDown(self) -> None:
        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=2.0))
        clear_model_prediction_holdover_cache()
        clear_prediction_manager_cache()
        clear_refresh_debounce_cache()
        self.env.stop()

    def _adapter(self, core: CuratedMemoryCore) -> InputMethodAdapter:
        return InputMethodAdapter(core)

    def _composition_payload(self, *, request_seq: int = 1) -> dict[str, object]:
        return {
            "sessionId": "v1-composition",
            "requestSeq": request_seq,
            "rawInput": "nihao",
            "preedit": "nihao",
            "rimeCandidates": [
                {"text": "你好", "label": "1", "comment": "Rime"},
                {"text": "拟好", "label": "2", "comment": "Rime"},
            ],
            "committedContext": "我刚才正在整理项目",
            "latencyBudgetMs": 900,
            "maxVisibleCandidates": 8,
            "maxSideCandidates": 5,
            "predictionFirstMerge": True,
            "frontendRevision": request_seq,
            "selectionEpoch": request_seq,
            "frontAppBundleId": "com.apple.TextEdit",
            "inputSourceId": "im.rag-ime.inputmethod.RagIme.Hans",
        }

    def _post_commit_payload(
        self,
        *,
        request_seq: int = 1,
        context: str = "我想彻底整理项目，先把",
        commit_preview: str = "先把",
        progressive_follow_up: bool = False,
        foreground: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "sessionId": "v1-post-commit",
            "requestSeq": request_seq,
            "rawInput": "",
            "preedit": "",
            "committedContext": context,
            "commitTextPreview": commit_preview,
            "latencyBudgetMs": 900,
            "maxVisibleCandidates": 8,
            "maxSideCandidates": 5,
            "predictionFirstMerge": True,
            "progressiveFollowUp": progressive_follow_up,
            "frontendRevision": 7,
            "selectionEpoch": 7,
            "frontAppBundleId": "com.apple.TextEdit",
            "inputSourceId": "im.rag-ime.inputmethod.RagIme.Hans",
            "panelSessionId": "panel-v1",
        }
        if foreground:
            payload["foregroundText"] = {
                "available": True,
                "source": "text_input_client",
                "confidence": 0.78,
                "freshnessMs": 0,
                "selectedTextHash": "",
                "selectedTextChars": 0,
                "selectedTextPreview": "",
                "surroundingBefore": context,
                "surroundingAfter": "",
                "wholeValueHash": "",
                "wholeValueChars": 0,
                "canReplaceSelection": False,
                "captureEpoch": request_seq,
                "warnings": ["text_input_client_context"],
            }
        return payload

    def _response(
        self,
        payload: dict[str, object],
        *,
        core: CuratedMemoryCore | None = None,
        predictor: RecordingPredictionProvider | None = None,
    ) -> dict[str, object]:
        actual_core = core or CuratedMemoryCore()
        return build_rime_sidecar_response(
            payload=payload,
            adapter=self._adapter(actual_core),
            core=actual_core,
            predictor=predictor or RecordingPredictionProvider(),
        )

    def _prime_post_commit(
        self,
        *,
        core: CuratedMemoryCore | None = None,
        predictor: RecordingPredictionProvider | None = None,
        context: str = "我想彻底整理项目，先把",
        commit_preview: str = "先把",
    ) -> tuple[dict[str, object], dict[str, object], RecordingPredictionProvider, CuratedMemoryCore]:
        actual_core = core or CuratedMemoryCore()
        actual_predictor = predictor or RecordingPredictionProvider()
        first = self._response(
            self._post_commit_payload(context=context, commit_preview=commit_preview),
            core=actual_core,
            predictor=actual_predictor,
        )
        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=2.0))
        follow_up = self._response(
            self._post_commit_payload(
                request_seq=2,
                context=context,
                commit_preview=commit_preview,
                progressive_follow_up=True,
            ),
            core=actual_core,
            predictor=actual_predictor,
        )
        return first, follow_up, actual_predictor, actual_core

    def test_v1_composition_model_disabled_by_default(self) -> None:
        predictor = RecordingPredictionProvider()
        response = self._response(self._composition_payload(), predictor=predictor)

        self.assertEqual(predictor.calls, 0)
        self.assertFalse(response["modelLane"]["called"])
        self.assertEqual(response["modelLane"]["skippedReason"], "model lane disabled before post-commit")
        self.assertTrue(response["predictionSession"]["rimeCompositionOwnedByRime"])
        self.assertEqual(response["predictionSession"]["selectionScope"], "rime")
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["rime", "rime"])
        self.assertEqual(response["keyPolicy"]["numberKeys"], "select_rime_candidate")

    def test_v1_accessibility_foreground_context_feeds_side_lanes(self) -> None:
        core = CuratedMemoryCore([_memory("fg:1", "真实前台文本相关候选", accepted_count=2)])
        payload = self._composition_payload(request_seq=11)
        payload["committedContext"] = "旧的输入法 ledger 不应该优先进入 side lane"
        payload["foregroundText"] = {
            "available": True,
            "source": "accessibility",
            "confidence": 0.86,
            "freshnessMs": 0,
            "selectedTextHash": "",
            "selectedTextChars": 0,
            "selectedTextPreview": "",
            "surroundingBefore": "真实前台文本 正在写输入法上下文",
            "surroundingAfter": "后面还有编辑器正文",
            "wholeValueHash": "sha256:foreground-whole-value",
            "wholeValueChars": 38,
            "canReplaceSelection": False,
            "captureEpoch": 11,
            "warnings": ["string_for_range"],
        }

        response = self._response(payload, core=core, predictor=RecordingPredictionProvider([]))
        foreground_context = response["ragLane"]["foregroundContext"]

        self.assertEqual(response["queryBasis"], "rimeCandidates")
        self.assertTrue(foreground_context["applied"])
        self.assertEqual(foreground_context["source"], "accessibility")
        self.assertEqual(foreground_context["wholeValueHash"], "sha256:foreground-whole-value")
        self.assertIn("真实前台文本", core.last_current_input)
        self.assertIn("真实前台文本", core.last_recent_context)
        self.assertNotIn("旧的输入法 ledger", core.last_recent_context)

    def test_v1_accessibility_foreground_context_can_drive_query_without_rime(self) -> None:
        core = CuratedMemoryCore([_memory("fg:2", "前台正文续写候选", accepted_count=2)])
        payload = self._post_commit_payload(request_seq=12, context="旧 ledger", commit_preview="")
        payload["progressiveFollowUp"] = True
        payload["forceSideCandidates"] = True
        payload["foregroundText"] = {
            "available": True,
            "source": "accessibility",
            "confidence": 0.86,
            "freshnessMs": 0,
            "surroundingBefore": "前台正文正在讨论 DeepSeek 生成输入法候选",
            "surroundingAfter": "",
            "wholeValueHash": "sha256:foreground-only",
            "wholeValueChars": 25,
            "canReplaceSelection": False,
            "captureEpoch": 12,
            "warnings": ["ax_value_fallback"],
        }

        response = self._response(payload, core=core, predictor=RecordingPredictionProvider([]))

        self.assertEqual(response["queryBasis"], "foregroundText")
        self.assertTrue(response["ragLane"]["foregroundContext"]["applied"])
        self.assertEqual(core.last_current_input, "前台正文正在讨论 DeepSeek 生成输入法候选")
        self.assertEqual(core.last_recent_context, "前台正文正在讨论 DeepSeek 生成输入法候选")

    def test_v1_text_input_client_context_drives_post_commit_query(self) -> None:
        core = CuratedMemoryCore([_memory("fg:3", "前台输入框续写候选", accepted_count=2)])
        payload = self._post_commit_payload(
            request_seq=13,
            context="旧 ledger 不应该进入模型",
            commit_preview="",
            foreground=False,
        )
        payload["progressiveFollowUp"] = True
        payload["forceSideCandidates"] = True
        payload["foregroundText"] = {
            "available": True,
            "source": "text_input_client",
            "confidence": 0.78,
            "freshnessMs": 0,
            "surroundingBefore": "真实输入框上下文来自 IMKTextInput",
            "surroundingAfter": "",
            "wholeValueHash": "",
            "wholeValueChars": 0,
            "canReplaceSelection": False,
            "captureEpoch": 13,
            "warnings": ["text_input_client_context"],
        }

        response = self._response(payload, core=core, predictor=RecordingPredictionProvider([]))

        self.assertEqual(response["queryBasis"], "foregroundText")
        self.assertTrue(response["triggerDecision"]["foregroundContextGate"]["allowed"])
        self.assertEqual(response["ragLane"]["foregroundContext"]["source"], "text_input_client")
        self.assertEqual(core.last_current_input, "真实输入框上下文来自 IMKTextInput")
        self.assertEqual(core.last_recent_context, "真实输入框上下文来自 IMKTextInput")

    def test_v1_post_commit_without_reliable_foreground_context_skips_side_lanes(self) -> None:
        predictor = RecordingPredictionProvider()
        core = CuratedMemoryCore([_memory("stale:1", "旧上下文候选", accepted_count=3)])
        payload = self._post_commit_payload(
            request_seq=14,
            context="旧 ledger 不可信",
            commit_preview="",
            foreground=False,
        )
        payload["forceSideCandidates"] = True
        payload["foregroundText"] = {
            "available": True,
            "source": "ime_commit_ledger",
            "confidence": 0.65,
            "freshnessMs": 0,
            "surroundingBefore": "旧 ledger 不可信",
            "surroundingAfter": "",
            "wholeValueHash": "",
            "wholeValueChars": 0,
            "canReplaceSelection": False,
            "captureEpoch": 14,
            "warnings": [],
        }

        response = self._response(payload, core=core, predictor=predictor)

        self.assertEqual(predictor.calls, 0)
        self.assertEqual(core.calls, 0)
        self.assertFalse(response["triggerDecision"]["shouldRefresh"])
        self.assertFalse(response["triggerDecision"]["foregroundContextGate"]["allowed"])
        self.assertIn("reliable foreground context required", response["triggerDecision"]["reason"])
        self.assertFalse(response["modelLane"]["called"])
        self.assertFalse(response["ragLane"]["called"])

    def test_v1_post_commit_async_first_response_under_250ms(self) -> None:
        predictor = RecordingPredictionProvider(sleep_s=0.35)
        started = time.perf_counter()
        response = self._response(self._post_commit_payload(), predictor=predictor)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        self.assertLess(elapsed_ms, 250)
        self.assertEqual(predictor.calls, 1)
        self.assertEqual(response["modelLane"]["requestType"], "post_commit_completion")
        self.assertTrue(response["modelLane"]["asyncMode"])
        self.assertTrue(response["modelLane"]["pending"])
        self.assertEqual(response["modelLane"]["firstResponseMs"], 150)
        self.assertTrue(response["progressive"]["shouldFollowUp"])
        self.assertFalse(response["predictionSession"]["shouldClearPredictionPanel"])

    def test_v1_post_commit_followup_does_not_restart_provider(self) -> None:
        predictor = RecordingPredictionProvider(sleep_s=0.4)
        core = CuratedMemoryCore([_memory("durable:1", "真实输入链路跑通", accepted_count=2)])
        first = self._response(self._post_commit_payload(), core=core, predictor=predictor)
        follow_up = self._response(
            self._post_commit_payload(request_seq=2, progressive_follow_up=True),
            core=core,
            predictor=predictor,
        )

        self.assertEqual(predictor.calls, 1)
        self.assertTrue(first["modelLane"]["pending"])
        self.assertIn(follow_up["modelLane"]["completionJobState"], {"pending", "hit"})
        self.assertEqual(follow_up["modelLane"]["requestType"], "post_commit_completion")
        self.assertEqual(follow_up["progressive"]["retryAfterMs"], 250)

    def test_v1_post_commit_completion_cache_respects_memory_bound(self) -> None:
        predictor = RecordingPredictionProvider(sleep_s=0.01)
        last_response: dict[str, object] = {}
        with patch.dict(os.environ, {"RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS": "2"}):
            for index in range(3):
                last_response = self._response(
                    self._post_commit_payload(
                        request_seq=20 + index,
                        context=f"我想整理第 {index} 段真实前台上下文",
                        commit_preview=f"第{index}段",
                    ),
                    predictor=predictor,
                )

        model_lane = last_response["modelLane"]
        self.assertEqual(model_lane["completionCacheMaxSize"], 2)
        self.assertLessEqual(model_lane["completionCacheSize"], 2)

    def test_v1_post_commit_model_candidates_not_pinyin_filtered(self) -> None:
        _, follow_up, predictor, _ = self._prime_post_commit(
            predictor=RecordingPredictionProvider(["真实输入链路跑通", "v1 范围收缩"])
        )

        self.assertEqual(predictor.requests[0]["current_input"], "")
        self.assertEqual(predictor.requests[0]["request_type"], "post_commit_completion")
        self.assertEqual(follow_up["modelLane"]["completionJobState"], "hit")
        self.assertTrue(follow_up["modelLane"]["noPinyinFilter"])
        self.assertEqual([item["text"] for item in follow_up["modelPredictions"]], ["真实输入链路跑通", "v1 范围收缩"])
        self.assertEqual(follow_up["modelLane"]["filteredPredictionCount"], 0)

    def test_v1_rag_does_not_echo_current_context(self) -> None:
        core = CuratedMemoryCore(
            [
                _memory("echo:1", "我想彻底整理项目，先把", source_type="rag"),
                _memory("good:1", "真实输入链路跑通", accepted_count=2),
            ]
        )
        _, follow_up, _, actual_core = self._prime_post_commit(core=core)
        surfaces = [item["text"] for item in follow_up["displayCandidates"]]
        rag_surfaces = [item["surfaceText"] for item in follow_up["ragCandidates"]]

        self.assertEqual(actual_core.last_current_input, "先把")
        self.assertNotIn("我想彻底整理项目，先把", surfaces)
        self.assertNotIn("我想彻底整理项目，先把", rag_surfaces)
        self.assertIn("真实输入链路跑通", rag_surfaces)
        self.assertTrue(follow_up["ragLane"]["directDisplaySuppressed"])
        self.assertEqual(follow_up["ragLane"]["displaySuggestionCount"], 0)
        self.assertGreaterEqual(follow_up["ragLane"]["filteredSuggestionCount"], 1)

    def test_v1_rag_prompt_leaks_filtered(self) -> None:
        core = CuratedMemoryCore(
            [
                _memory("leak:1", "019f1228-34de-74b3-a627-c546f091e87e 这个会话继续调试", source_type="rag"),
                _memory("leak:2", '{"sessionId":"debug","requestSeq":42}', source_type="rag"),
                _memory("good:1", "候选质量验收", accepted_count=2),
            ]
        )
        _, follow_up, _, _ = self._prime_post_commit(core=core)
        surfaces = [item["text"] for item in follow_up["displayCandidates"]]
        rag_surfaces = [item["surfaceText"] for item in follow_up["ragCandidates"]]

        self.assertFalse(any("019f1228" in item for item in surfaces))
        self.assertFalse(any("sessionId" in item for item in surfaces))
        self.assertFalse(any("019f1228" in item for item in rag_surfaces))
        self.assertFalse(any("sessionId" in item for item in rag_surfaces))
        self.assertIn("候选质量验收", rag_surfaces)
        self.assertTrue(follow_up["ragLane"]["directDisplaySuppressed"])
        self.assertGreaterEqual(follow_up["ragLane"]["filteredSuggestionCount"], 2)

    def test_v1_timeout_does_not_clear_legal_panel(self) -> None:
        response = self._response(
            self._post_commit_payload(),
            predictor=RecordingPredictionProvider(sleep_s=0.4),
        )

        self.assertEqual(response["uiMode"], "post_commit_pending")
        self.assertEqual(response["displayCandidates"][0]["sourceType"], "status")
        self.assertFalse(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertFalse(response["showDecision"]["hardClear"])
        self.assertTrue(response["progressive"]["shouldFollowUp"])

    def test_v1_post_commit_panel_exposes_active_rag_action_button(self) -> None:
        response = self._response(
            self._post_commit_payload(),
            predictor=RecordingPredictionProvider(sleep_s=0.4),
        )
        action_candidates = [item for item in response["displayCandidates"] if item["sourceType"] == "action"]

        self.assertEqual(response["uiMode"], "post_commit_pending")
        self.assertTrue(action_candidates)
        self.assertEqual(action_candidates[0]["label"], "")
        self.assertEqual(action_candidates[0]["visibleLabel"], "")
        self.assertIsNone(action_candidates[0]["selectionKey"])
        self.assertEqual(action_candidates[0]["selectionRank"], 0)
        self.assertEqual(action_candidates[0]["candidateOrdinal"], 0)
        self.assertTrue(action_candidates[0]["isSelectable"])
        self.assertEqual(action_candidates[0]["text"], "DeepSeek 生成")
        self.assertEqual(action_candidates[0]["sourceBadge"], "生成")
        self.assertEqual(action_candidates[0]["colorToken"], "modelBlue")
        self.assertEqual(action_candidates[0]["selectionAction"], "start_active_rag_from_context")
        self.assertEqual(action_candidates[0]["metadata"]["maxCandidates"], 1)
        self.assertEqual(action_candidates[0]["metadata"]["buttonRole"], "active_rag_generate")
        self.assertEqual(action_candidates[0]["metadata"]["shortcutHint"], "ctrl+enter")
        self.assertTrue(action_candidates[0]["metadata"]["numericSelectionDisabled"])
        self.assertEqual(action_candidates[0]["metadata"]["triggerPolicy"], "manual_only")
        self.assertTrue(action_candidates[0]["metadata"]["requiresExplicitSelection"])

    def test_v1_post_commit_auto_model_can_be_action_only(self) -> None:
        predictor = RecordingPredictionProvider(["不应该自动调用"])
        with patch.dict(os.environ, {"RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL": "0"}):
            response = self._response(self._post_commit_payload(), predictor=predictor)
        action_candidates = [item for item in response["displayCandidates"] if item["sourceType"] == "action"]

        self.assertEqual(predictor.calls, 0)
        self.assertTrue(action_candidates)
        self.assertFalse([item for item in response["displayCandidates"] if item["sourceType"] == "model"])
        self.assertEqual(response["predictionSession"]["phase"], "post_commit")
        self.assertFalse(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertIn("action-only fast path", response["modelLane"]["skippedReason"])

    def test_v1_post_commit_action_button_fast_path_skips_rag_and_model(self) -> None:
        predictor = RecordingPredictionProvider(["不应该自动调用"], sleep_s=0.2)
        core = CuratedMemoryCore([_memory("m-fast", "不应该进入普通候选")])
        with patch.dict(
            os.environ,
            {
                "RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL": "0",
                "RAG_IME_RAG_DIRECT_DISPLAY": "0",
            },
        ):
            response = self._response(self._post_commit_payload(), core=core, predictor=predictor)
        action_candidates = [item for item in response["displayCandidates"] if item["sourceType"] == "action"]

        self.assertEqual(core.calls, 0)
        self.assertEqual(predictor.calls, 0)
        self.assertEqual([item["text"] for item in action_candidates], ["DeepSeek 生成"])
        self.assertEqual(action_candidates[0]["label"], "")
        self.assertIsNone(action_candidates[0]["selectionKey"])
        self.assertEqual(action_candidates[0]["candidateOrdinal"], 0)
        self.assertTrue(action_candidates[0]["isSelectable"])
        self.assertIn("action-only fast path", response["ragLane"]["skippedReason"])
        self.assertIn("action-only fast path", response["modelLane"]["skippedReason"])
        self.assertFalse(response["predictionFirst"]["enabled"])

    def test_v1_post_commit_auto_model_defaults_to_visible_llm_lane(self) -> None:
        predictor = RecordingPredictionProvider(["自动LLM候选"])
        with patch.dict(os.environ, {}, clear=True):
            first = self._response(self._post_commit_payload(), predictor=predictor)
            self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=2.0))
            follow_up = self._response(
                self._post_commit_payload(request_seq=2, progressive_follow_up=True),
                predictor=predictor,
            )
        model_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "model"]

        self.assertTrue(first["progressive"]["shouldFollowUp"])
        self.assertTrue(model_candidates)
        self.assertTrue("自动LLM候选".startswith(model_candidates[0]["text"]))
        self.assertEqual(follow_up["uiMode"], "post_commit_prediction")

    def test_v1_post_commit_active_rag_action_reserves_visible_slot(self) -> None:
        payload = self._post_commit_payload()
        payload["maxVisibleCandidates"] = 1
        response = self._response(payload, predictor=RecordingPredictionProvider(sleep_s=0.4))

        self.assertEqual(len(response["displayCandidates"]), 1)
        self.assertEqual(response["displayCandidates"][0]["sourceType"], "action")
        self.assertEqual(response["displayCandidates"][0]["selectionAction"], "start_active_rag_from_context")

    def test_v1_empty_post_commit_followup_gets_demo_safe_fallback_candidate(self) -> None:
        first, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore(),
            predictor=RecordingPredictionProvider(["我的需求你没有完成"]),
            context="我的需求你没有完成",
            commit_preview="完成",
        )
        fallback_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "model"]

        self.assertEqual(first["uiMode"], "post_commit_pending")
        self.assertEqual(follow_up["uiMode"], "post_commit_prediction")
        self.assertTrue(fallback_candidates)
        self.assertEqual(fallback_candidates[0]["text"], "继续补齐需求")
        self.assertEqual(fallback_candidates[0]["selectionAction"], "commit_side_candidate")
        self.assertEqual(follow_up["modelLane"]["fallbackReason"], "demo_safe_empty_post_commit_fallback")
        self.assertEqual(follow_up["modelLane"]["fallbackCandidateCount"], 1)
        self.assertEqual(follow_up["modelPredictions"][0]["metadata"]["fallbackSource"], "post_commit_empty_result")

    def test_v1_truncated_post_commit_model_fragment_uses_demo_safe_fallback(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore(),
            predictor=RecordingPredictionProvider(["您已"]),
            context="我的需求你没有完成",
            commit_preview="完成",
        )
        model_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "model"]

        self.assertEqual([item["text"] for item in model_candidates], ["继续补齐需求"])
        self.assertEqual(follow_up["modelLane"]["fallbackReason"], "demo_safe_empty_post_commit_fallback")

    def test_v1_repeated_context_does_not_show_demo_fallback_echo(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore(),
            predictor=RecordingPredictionProvider(["您已"]),
            context="你好明天明天见继续完善一下继续完善一下继续完善一下",
            commit_preview="",
        )
        model_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "model"]

        self.assertFalse(any(item["text"].startswith("继续完善") or item["text"] == "继续" for item in model_candidates))
        self.assertNotEqual(follow_up["modelLane"].get("fallbackReason"), "demo_safe_empty_post_commit_fallback")

    def test_v1_post_commit_rag_rejects_short_context_echo_even_when_accepted(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore([_memory("echo:welcome", "欢迎", accepted_count=9)]),
            predictor=RecordingPredictionProvider([""]),
            context="你好欢迎欢迎使用继续继续完善一下欢迎继续欢迎欢迎",
            commit_preview="",
        )
        surfaces = [item["text"] for item in follow_up["displayCandidates"]]

        self.assertNotIn("欢迎", surfaces)

    def test_v1_post_commit_presentation_streams_candidate_prefixes(self) -> None:
        with patch.dict(os.environ, {"RAG_IME_POST_COMMIT_PRESENTATION_STREAM": "1"}):
            core = CuratedMemoryCore()
            predictor = RecordingPredictionProvider(["继续补齐需求"])
            first = self._response(
                self._post_commit_payload(context="我的需求你没有完成", commit_preview="完成"),
                core=core,
                predictor=predictor,
            )
            self.assertEqual(first["uiMode"], "post_commit_prediction")
            first_model_candidates = [item for item in first["displayCandidates"] if item["sourceType"] == "model"]
            self.assertEqual(first_model_candidates[0]["text"], "继续")
            self.assertTrue(first_model_candidates[0]["metadata"]["pendingPreview"])
            self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=2.0))

            streamed_surfaces: list[str] = []
            lane_states: list[str] = []
            should_follow_up: list[bool] = []
            for request_seq in (2, 3, 4):
                response = self._response(
                    self._post_commit_payload(
                        request_seq=request_seq,
                        context="我的需求你没有完成",
                        commit_preview="完成",
                        progressive_follow_up=True,
                    ),
                    core=core,
                    predictor=predictor,
                )
                model_candidates = [item for item in response["displayCandidates"] if item["sourceType"] == "model"]
                streamed_surfaces.append(model_candidates[0]["text"])
                lane_states.append(response["modelLane"]["completionJobState"])
                should_follow_up.append(response["progressive"]["shouldFollowUp"])

            self.assertEqual(streamed_surfaces, ["继续", "继续补齐", "继续补齐需求"])
            self.assertEqual(lane_states, ["streaming", "streaming", "hit"])
            self.assertEqual(should_follow_up, [True, True, False])

    def test_v1_post_commit_fallback_presentation_streams_candidate_prefixes(self) -> None:
        with patch.dict(os.environ, {"RAG_IME_POST_COMMIT_PRESENTATION_STREAM": "1"}):
            core = CuratedMemoryCore()
            predictor = RecordingPredictionProvider(["您已"])
            first = self._response(
                self._post_commit_payload(context="我的需求你没有完成", commit_preview="完成"),
                core=core,
                predictor=predictor,
            )
            self.assertEqual(first["uiMode"], "post_commit_prediction")
            first_model_candidates = [item for item in first["displayCandidates"] if item["sourceType"] == "model"]
            self.assertEqual(first_model_candidates[0]["text"], "继续")
            self.assertTrue(first_model_candidates[0]["metadata"]["pendingPreview"])
            self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=2.0))

            streamed_surfaces: list[str] = []
            lane_states: list[str] = []
            should_follow_up: list[bool] = []
            for request_seq in (2, 3, 4):
                response = self._response(
                    self._post_commit_payload(
                        request_seq=request_seq,
                        context="我的需求你没有完成",
                        commit_preview="完成",
                        progressive_follow_up=True,
                    ),
                    core=core,
                    predictor=predictor,
                )
                model_candidates = [item for item in response["displayCandidates"] if item["sourceType"] == "model"]
                streamed_surfaces.append(model_candidates[0]["text"])
                lane_states.append(response["modelLane"]["completionJobState"])
                should_follow_up.append(response["progressive"]["shouldFollowUp"])

            self.assertEqual(streamed_surfaces, ["继续", "继续补齐", "继续补齐需求"])
            self.assertEqual(lane_states, ["streaming", "streaming", "completed"])
            self.assertEqual(should_follow_up, [True, True, False])

    def test_v1_filter_post_commit_completion_rejects_truncated_fragment(self) -> None:
        from rag_ime.rime_sidecar import parse_rime_context_payload

        rime_snapshot = parse_rime_context_payload(
            self._post_commit_payload(context="我的需求你没有完成", commit_preview="完成"),
            default_project="wisdom-weasel-rag-ime",
        )
        kept = filter_post_commit_model_completions(
            [
                ModelPrediction("您已", 1, "model", 1, 0.9),
                ModelPrediction("继续补齐需求", 2, "model", 1, 0.9),
            ],
            snapshot=rime_snapshot,
            max_candidates=3,
        )

        self.assertEqual([item.text for item in kept], ["继续补齐需求"])

    def test_v1_stale_context_late_result_dropped(self) -> None:
        _, first_follow_up, _, _ = self._prime_post_commit(
            predictor=RecordingPredictionProvider(["第一段建议"]),
            context="旧上下文先写",
            commit_preview="先写",
        )
        _, second_follow_up, _, _ = self._prime_post_commit(
            predictor=RecordingPredictionProvider(["第二段建议"]),
            context="新上下文继续",
            commit_preview="继续",
        )

        self.assertNotEqual(
            first_follow_up["predictionSession"]["contextFingerprint"],
            second_follow_up["predictionSession"]["contextFingerprint"],
        )
        self.assertIn("第一段建议", [item["text"] for item in first_follow_up["modelPredictions"]])
        self.assertIn("第二段建议", [item["text"] for item in second_follow_up["modelPredictions"]])
        self.assertNotIn("第一段建议", [item["text"] for item in second_follow_up["displayCandidates"]])

    def test_v1_accept_prediction_schedules_next_prediction(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(predictor=RecordingPredictionProvider(["真实输入链路跑通"]))
        model_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "model"]
        self.assertTrue(model_candidates)
        top = model_candidates[0]

        with tempfile.TemporaryDirectory(prefix="rag-ime-v1-select-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "select.sqlite")
            core.initialize()
            result = record_rime_side_candidate_selection(
                payload={
                    "candidate": top,
                    "shownCandidates": follow_up["displayCandidates"],
                    "recentContext": "我想彻底整理项目，先把",
                    "project": "wisdom-weasel-rag-ime",
                    "frontAppBundleId": "com.apple.TextEdit",
                },
                adapter=InputMethodAdapter(core),
                core=core,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["recordedAction"] or result["recordedCommitAction"])
        self.assertEqual(follow_up["predictionSession"]["phase"], "post_commit")
        self.assertEqual(follow_up["keyPolicy"]["tab"], "accept_top_prediction")
        self.assertEqual(follow_up["keyPolicy"]["optionNumber"], "select_prediction_by_ordinal")

    def test_v1_diagnostic_filter_counts_are_stable_zero_when_nothing_filtered(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore([_memory("good:1", "真实输入链路跑通", accepted_count=2)]),
            predictor=RecordingPredictionProvider(["候选质量验收"]),
        )

        self.assertIn("filteredPredictionCount", follow_up["modelLane"])
        self.assertIn("filteredSuggestionCount", follow_up["ragLane"])
        self.assertIn("postCommitQualityFilteredCount", follow_up["ragLane"])
        self.assertEqual(follow_up["modelLane"]["filteredPredictionCount"], 0)
        self.assertEqual(follow_up["ragLane"]["filteredSuggestionCount"], 0)
        self.assertEqual(follow_up["ragLane"]["postCommitQualityFilteredCount"], 0)

    def test_v1_memory_evidence_candidate_exposes_source_reason_without_direct_display(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore([_memory("good:1", "真实输入链路跑通", accepted_count=2)]),
            predictor=RecordingPredictionProvider(["候选质量验收"]),
        )
        memory_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "memory"]
        memory_evidence = [
            item for item in follow_up["ragCandidates"] if item["metadata"].get("source_type") == "memory"
        ]

        self.assertFalse(memory_candidates)
        self.assertTrue(memory_evidence)
        self.assertEqual(memory_evidence[0]["metadata"]["sourceReason"], "accepted_memory")
        self.assertTrue(follow_up["ragLane"]["directDisplaySuppressed"])

    def test_v1_filter_post_commit_completion_rejects_context_echo(self) -> None:
        from rag_ime.rime_sidecar import parse_rime_context_payload

        rime_snapshot = parse_rime_context_payload(
            self._post_commit_payload(context="现在模型不对拼音预测，只是", commit_preview="只是"),
            default_project="wisdom-weasel-rag-ime",
        )
        kept = filter_post_commit_model_completions(
            [
                ModelPrediction("现在模型不对拼音预测，只是", 1, "model", 1, 0.9),
                ModelPrediction("上屏后短补全", 2, "model", 1, 0.9),
            ],
            snapshot=rime_snapshot,
            max_candidates=3,
        )

        self.assertEqual([item.text for item in kept], ["上屏后短补全"])
        self.assertEqual(kept[0].metadata["requestType"], "post_commit_completion")
        self.assertTrue(kept[0].metadata["noPinyinFilter"])

    def test_v1_filter_post_commit_completion_rejects_repeated_tail_echo(self) -> None:
        from rag_ime.rime_sidecar import parse_rime_context_payload

        rime_snapshot = parse_rime_context_payload(
            self._post_commit_payload(
                context="你好明天明天见继续完善一下继续完善一下继续完善一下",
                commit_preview="",
            ),
            default_project="wisdom-weasel-rag-ime",
        )
        kept = filter_post_commit_model_completions(
            [
                ModelPrediction("继续完善", 1, "model", 1, 0.9),
                ModelPrediction("换一个方向", 2, "model", 1, 0.9),
            ],
            snapshot=rime_snapshot,
            max_candidates=3,
        )

        self.assertEqual([item.text for item in kept], ["换一个方向"])

    def test_v1_key_policy_keeps_composition_numbers_for_rime(self) -> None:
        composition_policy = key_policy_for_prediction_session(
            {"phase": "anchor_composing", "inputMode": "anchor_composing", "selectionScope": "rime"}
        )
        post_commit_policy = key_policy_for_prediction_session(
            {"phase": "post_commit", "inputMode": "post_commit_predicting", "selectionScope": "prediction"}
        )

        self.assertEqual(composition_policy["numberKeys"], "select_rime_candidate")
        self.assertEqual(post_commit_policy["numberKeys"], "pass_through")
        self.assertEqual(post_commit_policy["tab"], "accept_top_prediction")
        self.assertEqual(post_commit_policy["optionNumber"], "select_prediction_by_ordinal")


if __name__ == "__main__":
    unittest.main()
