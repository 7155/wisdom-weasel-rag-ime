from __future__ import annotations

import unittest

from rag_ime.models import InputSuggestion, ModelPrediction, RimeCandidate, RimeContextSnapshot
from rag_ime.prediction_first import (
    InputMode,
    infer_input_mode,
    merge_prediction_first_candidates,
    prediction_candidate_matches_prefix,
    build_candidate_pool,
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
        )

        self.assertEqual(result.mode, InputMode.PREFIX_CONSTRAINED_COMPOSING)
        self.assertEqual(result.pinyin_prefix, "sj")
        self.assertTrue(result.policy["rimeCompositionOwnedByRime"])
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["设计输入法状态机", "设计一个候选展示方式", "把这个项目整理成面试亮点"],
        )
        self.assertEqual(
            [item.source_type for item in result.display_candidates],
            ["model", "rag", "model"],
        )
        self.assertEqual([item.label for item in result.display_candidates], ["1", "2", "3"])
        self.assertEqual(result.policy["sideInserted"], 3)
        self.assertEqual(result.policy["prefixMatchedSideInserted"], 2)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 0)
        self.assertEqual(result.display_candidates[0].display_lane, "model")
        self.assertEqual(result.display_candidates[2].display_lane, "model")
        self.assertEqual(result.display_candidates[1].metadata["candidate_mode"], "prefix_constrained_composing")

    def test_prefix_constrained_composition_uses_unmatched_llm_before_wanxiang_when_available(self) -> None:
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

        self.assertEqual([item.text for item in result.display_candidates], ["把这个项目整理成面试亮点"])
        self.assertEqual([item.source_type for item in result.display_candidates], ["model"])
        self.assertEqual(result.policy["sideInserted"], 1)
        self.assertEqual(result.policy["prefixMatchedSideInserted"], 0)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 0)

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
        self.assertEqual(result.display_candidates[1].text, "继续调试候选")
        self.assertEqual(result.policy["rawCommitInserted"], 1)
        self.assertEqual(result.policy["sideInserted"], 1)
        self.assertEqual(result.policy["wanxiangFallbackCount"], 0)

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

    def test_post_commit_prediction_prioritizes_rag_memory_before_llm(self) -> None:
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
        self.assertEqual([item.source_type for item in result.display_candidates], ["rag", "memory", "model"])
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["把这个项目整理成面试项目", "高频实时场景里的个人记忆系统", "做一个本地 RAG 输入法"],
        )
        self.assertFalse(result.policy["rimeCompositionOwnedByRime"])

    def test_candidate_pool_keeps_rag_memory_and_model_as_separate_lanes(self) -> None:
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

        self.assertEqual([item.source_type for item in pool.prediction_order()[:3]], ["rag", "memory", "model"])

    def test_mode_inference_distinguishes_anchor_prefix_and_post_commit(self) -> None:
        self.assertEqual(
            infer_input_mode(RimeContextSnapshot(session_id="s", request_seq=1, preedit="wx")),
            InputMode.ANCHOR_COMPOSING,
        )
        self.assertEqual(
            infer_input_mode(
                RimeContextSnapshot(session_id="s", request_seq=2, preedit="sj", committed_context="我想")
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


if __name__ == "__main__":
    unittest.main()
