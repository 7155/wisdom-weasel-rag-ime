from __future__ import annotations

import unittest
from unittest.mock import patch

from rag_ime.models import InputSuggestion, ModelPrediction, RimeCandidate, RimeContextSnapshot
from rag_ime.prediction_first import (
    InputMode,
    PredictionSessionPhase,
    prediction_session_to_payload,
    infer_input_mode,
    merge_prediction_first_candidates,
    prediction_candidate_matches_prefix,
    build_candidate_pool,
    resolve_prediction_session,
)


class PredictionFirstTests(unittest.TestCase):
    def test_anchor_composing_keeps_wanxiang_rime_in_control(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=1,
            raw_input="wx",
            preedit="wx",
            committed_context="",
            candidates=(
                RimeCandidate(text="我想", label="1", comment="wanxiang", index=0),
                RimeCandidate(text="微信", label="2", comment="wanxiang", index=1),
            ),
            max_visible_candidates=5,
            max_side_candidates=5,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(text="做一个本地 RAG 输入法", rank=1, provider_name="mock", latency_ms=1)
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="把这个项目整理成面试项目",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="memory",
                    confidence=0.9,
                )
            ],
        )

        self.assertEqual(result.mode, InputMode.ANCHOR_COMPOSING)
        self.assertTrue(result.policy["rimeCompositionOwnedByRime"])
        self.assertEqual([item.text for item in result.display_candidates], ["我想", "微信"])
        self.assertEqual([item.source_type for item in result.display_candidates], ["rime", "rime"])
        self.assertEqual(result.policy["sideInserted"], 0)
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.ANCHOR_COMPOSING)
        self.assertTrue(session.candidate_panel_visible)
        self.assertFalse(session.prediction_panel_visible)
        self.assertTrue(session.should_clear_prediction_panel)
        self.assertEqual(session.selection_scope, "rime")

    def test_prefix_constrained_composition_keeps_llm_rag_before_wanxiang_fallback(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=2,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            candidates=(
                RimeCandidate(text="手机", label="1", comment="wanxiang", index=0),
                RimeCandidate(text="世界", label="2", comment="wanxiang", index=1),
            ),
            max_visible_candidates=5,
            max_side_candidates=3,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="设计输入法状态机",
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=30,
                    confidence=0.8,
                    metadata={"initials": "sjsrfztj"},
                ),
                ModelPrediction(
                    text="把这个项目整理成面试亮点",
                    rank=2,
                    provider_name="qwen-mlx",
                    latency_ms=30,
                    confidence=0.9,
                    metadata={"initials": "bz gxm zlc msld"},
                ),
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="设计一个候选展示方式",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="用户之前讨论候选展示",
                    confidence=0.94,
                    metadata={
                        "insert_text": "设计一个候选展示方式",
                        "source_type": "rag",
                        "initials": "sjyg hxzsfs",
                    },
                ),
                InputSuggestion(
                    suggestion_id="rag-2",
                    surface_text="把本地记忆注入 Agent 首次运行上下文",
                    suggestion_type="rag",
                    source_event_id=2,
                    evidence_preview="不匹配 sj",
                    confidence=0.99,
                    metadata={"initials": "bbdjy zr agent scyx sxw"},
                ),
            ],
            mode=InputMode.PREFIX_CONSTRAINED_COMPOSING,
        )

        self.assertEqual(result.mode, InputMode.PREFIX_CONSTRAINED_COMPOSING)
        self.assertEqual(result.pinyin_prefix, "sj")
        self.assertTrue(result.policy["rimeCompositionOwnedByRime"])
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["设计输入法状态机", "手机", "世界"],
        )
        self.assertEqual(
            [item.source_type for item in result.display_candidates],
            ["model", "rime", "rime"],
        )
        self.assertEqual([item.label for item in result.display_candidates], ["1", "2", "3"])
        self.assertEqual(result.policy["sideInserted"], 1)
        self.assertEqual(result.policy["prefixMatchedSideInserted"], 1)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 2)
        self.assertEqual(result.policy["wanxiangReserve"], 2)
        self.assertEqual(result.display_candidates[0].display_lane, "model")
        self.assertEqual(result.display_candidates[0].metadata["candidate_mode"], "prefix_constrained_composing")
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.PREFIX_CONSTRAINED)
        self.assertTrue(session.candidate_panel_visible)
        self.assertTrue(session.prediction_panel_visible)
        self.assertFalse(session.should_clear_prediction_panel)
        self.assertEqual(session.selection_scope, "mixed_prediction_first")
        self.assertTrue(session.rime_composition_owned_by_rime)

    def test_prefix_constrained_composition_falls_back_to_wanxiang_when_side_candidates_do_not_match(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=3,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            candidates=(RimeCandidate(text="手机", comment="wanxiang", index=0),),
            max_visible_candidates=5,
            max_side_candidates=3,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="把这个项目整理成面试亮点",
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=30,
                    metadata={"initials": "bz gxm zlc msld"},
                )
            ],
            suggestions=[],
        )

        self.assertEqual([item.text for item in result.display_candidates], ["手机"])
        self.assertEqual([item.source_type for item in result.display_candidates], ["rime"])
        self.assertEqual(result.policy["sideInserted"], 0)
        self.assertEqual(result.policy["prefixMatchedSideInserted"], 0)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 1)
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.ANCHOR_COMPOSING)
        self.assertTrue(session.should_clear_prediction_panel)

    def test_long_pinyin_composition_allows_semantic_side_candidates(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=34,
            raw_input="woxiangshejiyigehouxuan",
            preedit="wo xiang she ji yi ge hou xuan",
            committed_context="我正在调试 RAG 输入法，要求 LLM 和记忆真实显示",
            candidates=(
                RimeCandidate(text="我想设计一个候选", label="1", comment="wanxiang", index=0),
                RimeCandidate(text="我想设计", label="2", comment="wanxiang", index=1),
            ),
            max_visible_candidates=6,
            max_side_candidates=4,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="继续优化候选展示",
                    rank=1,
                    provider_name="x1api",
                    latency_ms=1200,
                    metadata={"initials": "jx yhhxzs"},
                )
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-long-1",
                    surface_text="设计一个候选展示方式",
                    suggestion_type="rag",
                    source_event_id=7,
                    evidence_preview="用户要求参考 Wisdom-Weasel 的候选展示",
                    confidence=0.92,
                    metadata={"source_type": "rag", "initials": "sjyg hxzsfs"},
                )
            ],
            mode=InputMode.PREFIX_CONSTRAINED_COMPOSING,
        )

        self.assertEqual(result.mode, InputMode.PREFIX_CONSTRAINED_COMPOSING)
        self.assertEqual(
            [item.source_type for item in result.display_candidates],
            ["model", "rag", "rime", "rime"],
        )
        self.assertEqual(result.policy["sideInserted"], 2)
        self.assertEqual(result.policy["prefixMatchedSideInserted"], 0)
        self.assertIn("long pinyin composition", result.policy["reason"])
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.PREFIX_CONSTRAINED)
        self.assertTrue(session.prediction_panel_visible)
        self.assertFalse(session.should_clear_prediction_panel)

    def test_prefix_constrained_raw_command_keeps_raw_commit_first(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=33,
            raw_input="git status",
            preedit="git status",
            committed_context="正在调试 Prediction-first RAG 输入法",
            candidates=(RimeCandidate(text="给他", comment="wanxiang", index=0),),
            max_visible_candidates=5,
            max_side_candidates=3,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="继续调试候选",
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=30,
                )
            ],
            suggestions=[],
            raw_commit_text="git status",
        )

        self.assertEqual(result.display_candidates[0].text, "git status")
        self.assertEqual(result.display_candidates[0].source_type, "raw_english")
        self.assertEqual([item.text for item in result.display_candidates], ["git status"])
        self.assertEqual(result.policy["rawCommitInserted"], 1)
        self.assertEqual(result.policy["sideInserted"], 0)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 0)
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.RAW_PASSTHROUGH)
        self.assertFalse(session.prediction_panel_visible)
        self.assertEqual(session.selection_scope, "raw")

    def test_prefix_constrained_composition_falls_back_to_wanxiang_only_when_side_empty(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=3,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            candidates=(RimeCandidate(text="手机", comment="wanxiang", index=0),),
            max_visible_candidates=5,
            max_side_candidates=3,
        )

        result = merge_prediction_first_candidates(snapshot=snapshot, model_predictions=[], suggestions=[])

        self.assertEqual([item.text for item in result.display_candidates], ["手机"])
        self.assertEqual([item.source_type for item in result.display_candidates], ["rime"])
        self.assertEqual(result.policy["sideInserted"], 0)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 1)
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.ANCHOR_COMPOSING)
        self.assertTrue(session.candidate_panel_visible)
        self.assertFalse(session.prediction_panel_visible)
        self.assertTrue(session.should_clear_prediction_panel)
        self.assertEqual(session.selection_scope, "rime")

    def test_post_commit_prediction_prioritizes_llm_before_rag_memory(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=4,
            committed_context="我想",
            candidates=(),
            max_visible_candidates=4,
            max_side_candidates=4,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="做一个本地 RAG 输入法",
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=30,
                    confidence=0.9,
                    metadata={"initials": "zygbd rag srf"},
                )
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="把这个项目整理成面试项目",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="用户多次提到面试亮点",
                    confidence=0.7,
                    metadata={"initials": "bzgxmzl cmsxm"},
                ),
                InputSuggestion(
                    suggestion_id="memory-1",
                    surface_text="高频实时场景里的个人记忆系统",
                    suggestion_type="phrase",
                    source_event_id=2,
                    evidence_preview="用户多次提到这个定位",
                    confidence=0.92,
                    metadata={
                        "source_type": "memory",
                        "initials": "gpsscjldgrjyxt",
                    },
                )
            ],
        )

        self.assertEqual(result.mode, InputMode.POST_COMMIT_PREDICTING)
        self.assertEqual([item.source_type for item in result.display_candidates], ["model", "rag"])
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["做一个本地 RAG 输入法", "把这个项目整理成面试项目"],
        )
        self.assertFalse(result.policy["rimeCompositionOwnedByRime"])
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        self.assertEqual(session.phase, PredictionSessionPhase.POST_COMMIT)
        self.assertTrue(session.prediction_panel_visible)
        self.assertFalse(session.should_clear_prediction_panel)
        self.assertEqual(session.selection_scope, "prediction")

    def test_model_candidates_do_not_occupy_all_side_slots_when_rag_and_rime_exist(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=47,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            candidates=(
                RimeCandidate(text="手机", label="1", comment="wanxiang", index=0),
                RimeCandidate(text="世界", label="2", comment="wanxiang", index=1),
                RimeCandidate(text="实际", label="3", comment="wanxiang", index=2),
            ),
            max_visible_candidates=8,
            max_side_candidates=5,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text=f"设计输入法模型候选{i}",
                    rank=i,
                    provider_name="qwen-mlx",
                    latency_ms=20,
                    confidence=0.9 - (i * 0.01),
                    metadata={"initials": f"sjsrfmxhx{i}"},
                )
                for i in range(1, 6)
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="设计一个候选展示方式",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="RAG should stay visible",
                    confidence=0.88,
                    metadata={"source_type": "rag", "initials": "sjyg hxzsfs"},
                ),
                InputSuggestion(
                    suggestion_id="memory-1",
                    surface_text="输入法候选弹窗要稳定",
                    suggestion_type="phrase",
                    source_event_id=2,
                    evidence_preview="memory should stay visible",
                    confidence=0.87,
                    metadata={"source_type": "memory", "initials": "sjwd hxtc ywd"},
                ),
            ],
            mode=InputMode.PREFIX_CONSTRAINED_COMPOSING,
        )

        self.assertEqual(
            [item.source_type for item in result.display_candidates],
            ["model", "model", "rag", "rime", "rime", "rime"],
        )
        self.assertEqual(result.policy["sideInserted"], 3)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 3)
        self.assertEqual(result.policy["maxModelSideCandidates"], 2)
        self.assertEqual(result.policy["ragBlockReserve"], 1)
        self.assertLessEqual([item.source_type for item in result.display_candidates].count("model"), 2)

    def test_model_only_post_commit_still_shows_multiple_predictions(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=48,
            committed_context="我想继续",
            candidates=(),
            max_visible_candidates=6,
            max_side_candidates=6,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(text=f"优化候选稳定性{i}", rank=i, provider_name="qwen-mlx", latency_ms=20)
                for i in range(1, 6)
            ],
            suggestions=[],
        )

        self.assertEqual([item.source_type for item in result.display_candidates], ["model", "model", "model"])
        self.assertEqual(result.policy["sideInserted"], 3)
        self.assertEqual(result.policy["maxModelSideCandidates"], 3)

    def test_post_commit_keeps_three_model_candidates_plus_rag(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=49,
            committed_context="明天上午开会以后",
            candidates=(),
            max_visible_candidates=8,
            max_side_candidates=5,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(text=f"模型补全{i}", rank=i, provider_name="mlx", latency_ms=20)
                for i in range(1, 5)
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="等确认以后再发",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="RAG memory",
                    confidence=0.9,
                    metadata={"source_type": "rag"},
                )
            ],
        )

        self.assertEqual(
            [item.source_type for item in result.display_candidates],
            ["model", "model", "model", "rag"],
        )
        self.assertEqual(result.policy["maxModelSideCandidates"], 3)
        self.assertEqual(result.policy["ragBlockReserve"], 1)

    def test_post_commit_hides_connector_punctuation_but_commits_it(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=49,
            committed_context="模型可能是语料问题",
            candidates=(),
            max_visible_candidates=4,
            max_side_candidates=3,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="，需要重新训练",
                    rank=1,
                    provider_name="minimind",
                    latency_ms=80,
                )
            ],
            suggestions=[],
        )

        self.assertEqual(result.display_candidates[0].text, "需要重新训练")
        self.assertEqual(result.display_candidates[0].insert_text, "，需要重新训练")

    def test_long_rag_evidence_is_not_rendered_as_candidate_text(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=45,
            committed_context="我想继续优化候选栏",
            candidates=(),
            max_visible_candidates=4,
            max_side_candidates=4,
        )
        long_surface = "这是很长的 RAG 证据说明，不应该整段塞进输入法候选栏，只能作为完整提交文本保留"

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-long-display",
                    surface_text=long_surface,
                    suggestion_type="rag",
                    source_event_id=10,
                    evidence_preview="完整证据应进入 explain UI",
                    confidence=0.9,
                    metadata={"source_type": "rag"},
                )
            ],
        )

        item = result.display_candidates[0]
        self.assertEqual(item.source_type, "rag")
        self.assertLessEqual(len(item.text), 23)
        self.assertTrue(item.text.endswith("..."))
        self.assertEqual(item.insert_text, long_surface)
        self.assertTrue(item.metadata["display_text_truncated"])
        self.assertEqual(item.metadata["full_display_text"], long_surface)
        self.assertEqual(item.metadata["display_text_limit"], 20)

    def test_composition_model_candidate_text_is_bounded_but_rime_is_original(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=46,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            candidates=(RimeCandidate(text="世界世界世界世界世界世界世界", comment="wanxiang", index=0),),
            max_visible_candidates=5,
            max_side_candidates=3,
        )
        long_model = "设计输入法状态机并继续优化候选显示稳定性"

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text=long_model,
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=20,
                    confidence=0.9,
                    metadata={"initials": "sjsrfztjbjxyhhxxswdx"},
                )
            ],
            suggestions=[],
            mode=InputMode.PREFIX_CONSTRAINED_COMPOSING,
        )

        model_item = result.display_candidates[0]
        rime_item = result.display_candidates[1]
        self.assertEqual(model_item.source_type, "model")
        self.assertLessEqual(len(model_item.text), 19)
        self.assertTrue(model_item.text.endswith("..."))
        self.assertEqual(model_item.insert_text, long_model)
        self.assertEqual(model_item.metadata["display_text_limit"], 16)
        self.assertEqual(rime_item.source_type, "rime")
        self.assertEqual(rime_item.text, "世界世界世界世界世界世界世界")

    def test_post_commit_top1_guard_promotes_content_over_low_value_prediction(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=44,
            committed_context="我现在这个候选词根本不像 LLM 输出",
            candidates=(),
            max_visible_candidates=4,
            max_side_candidates=4,
        )

        result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(
                    text="根据",
                    rank=1,
                    provider_name="qwen-mlx",
                    latency_ms=20,
                    confidence=0.99,
                ),
                ModelPrediction(
                    text="补后端测试",
                    rank=2,
                    provider_name="qwen-mlx",
                    latency_ms=20,
                    confidence=0.8,
                ),
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="对照 Wisdom-Weasel 修候选生命周期",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="Felix top1 guard",
                    confidence=0.85,
                    metadata={"source_type": "rag"},
                )
            ],
        )

        self.assertEqual(result.display_candidates[0].text, "补后端测试")
        self.assertEqual(result.display_candidates[0].source_type, "model")
        self.assertEqual(result.display_candidates[0].metadata["top1_guard"], "promoted_over_low_value")
        self.assertEqual(result.display_candidates[1].text, "根据")
        self.assertEqual(result.display_candidates[1].metadata["top1_guard"], "demoted_low_value")
        self.assertTrue(result.policy["top1Guard"]["triggered"])
        self.assertEqual(result.policy["top1Guard"]["originalTop1"], "根据")
        self.assertEqual(result.policy["top1Guard"]["promotedText"], "补后端测试")

    def test_post_commit_without_live_candidates_clears_prediction_session(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=5,
            committed_context="我想做一个 Prediction-first RAG 输入法",
            candidates=(),
            max_visible_candidates=4,
            max_side_candidates=4,
            idle_ms=1500,
        )

        result = merge_prediction_first_candidates(snapshot=snapshot, model_predictions=[], suggestions=[])
        session = resolve_prediction_session(snapshot=snapshot, merge_result=result)
        payload = prediction_session_to_payload(session)

        self.assertEqual(session.phase, PredictionSessionPhase.HIDDEN)
        self.assertFalse(session.candidate_panel_visible)
        self.assertFalse(session.prediction_panel_visible)
        self.assertTrue(session.should_clear_prediction_panel)
        self.assertEqual(session.selection_scope, "none")
        self.assertEqual(payload["phase"], "hidden")
        self.assertTrue(payload["shouldClearPredictionPanel"])

    def test_candidate_pool_keeps_model_rag_memory_as_separate_lanes(self) -> None:
        pool = build_candidate_pool(
            model_predictions=[
                ModelPrediction(text="用本地 MLX 小模型续写", rank=1, provider_name="mlx", latency_ms=20)
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="memory-1",
                    surface_text="个人记忆系统",
                    suggestion_type="phrase",
                    source_event_id=2,
                    evidence_preview="",
                    confidence=0.99,
                    metadata={"source_type": "memory"},
                ),
                InputSuggestion(
                    suggestion_id="rag-1",
                    surface_text="embedding query 应该结合当前输入和上下文",
                    suggestion_type="sentence",
                    source_event_id=1,
                    evidence_preview="",
                    confidence=0.4,
                    metadata={"source_type": "rag"},
                ),
            ],
        )

        self.assertEqual([item.source_type for item in pool.prediction_order()[:3]], ["model", "rag"])

    def test_mode_inference_distinguishes_anchor_prefix_and_post_commit(self) -> None:
        self.assertEqual(
            infer_input_mode(RimeContextSnapshot(session_id="s", request_seq=1, preedit="wx")),
            InputMode.ANCHOR_COMPOSING,
        )
        self.assertEqual(
            infer_input_mode(
                RimeContextSnapshot(session_id="s", request_seq=2, preedit="sj", committed_context="我想")
            ),
            InputMode.ANCHOR_COMPOSING,
        )
        with patch.dict("os.environ", {"RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL": "1"}):
            self.assertEqual(
                infer_input_mode(
                    RimeContextSnapshot(session_id="s", request_seq=22, preedit="sj", committed_context="我想")
                ),
                InputMode.PREFIX_CONSTRAINED_COMPOSING,
            )
        self.assertEqual(
            infer_input_mode(RimeContextSnapshot(session_id="s", request_seq=3, committed_context="我想")),
            InputMode.POST_COMMIT_PREDICTING,
        )

    def test_prefix_match_uses_initials_and_full_pinyin_metadata(self) -> None:
        pool = build_candidate_pool(
            suggestions=[
                InputSuggestion(
                    suggestion_id="sug-1",
                    surface_text="设计输入法状态机",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="",
                    confidence=0.8,
                    metadata={"initials": "sjsrfztj", "full_pinyin": ["she", "ji", "shu", "ru", "fa"]},
                )
            ]
        )

        candidate = pool.rag[0]
        self.assertTrue(prediction_candidate_matches_prefix(candidate, "sj"))
        self.assertTrue(prediction_candidate_matches_prefix(candidate, "sheji"))
        self.assertFalse(prediction_candidate_matches_prefix(candidate, "wx"))

    def test_prefix_match_does_not_use_middle_sliding_window_keys(self) -> None:
        pool = build_candidate_pool(
            suggestions=[
                InputSuggestion(
                    suggestion_id="sug-1",
                    surface_text="我rag和记忆系统有很多数据诶",
                    suggestion_type="rag",
                    source_event_id=1,
                    evidence_preview="",
                    confidence=0.8,
                    metadata={"initials": "wraghjyxtyhdsje", "pinyin_prefixes": ["sj", "jy", "xt"]},
                )
            ]
        )

        candidate = pool.rag[0]
        self.assertFalse(prediction_candidate_matches_prefix(candidate, "sj"))
        self.assertTrue(prediction_candidate_matches_prefix(candidate, "wrag"))


if __name__ == "__main__":
    unittest.main()
