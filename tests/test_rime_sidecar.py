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
    ) -> dict[str, object]:
        return {
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

        self.assertEqual(actual_core.last_current_input, "先把")
        self.assertNotIn("我想彻底整理项目，先把", surfaces)
        self.assertIn("真实输入链路跑通", surfaces)
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

        self.assertFalse(any("019f1228" in item for item in surfaces))
        self.assertFalse(any("sessionId" in item for item in surfaces))
        self.assertIn("候选质量验收", surfaces)
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

    def test_v1_memory_display_candidate_exposes_source_reason(self) -> None:
        _, follow_up, _, _ = self._prime_post_commit(
            core=CuratedMemoryCore([_memory("good:1", "真实输入链路跑通", accepted_count=2)]),
            predictor=RecordingPredictionProvider(["候选质量验收"]),
        )
        memory_candidates = [item for item in follow_up["displayCandidates"] if item["sourceType"] == "memory"]

        self.assertTrue(memory_candidates)
        self.assertEqual(memory_candidates[0]["metadata"]["sourceReason"], "accepted_memory")

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
