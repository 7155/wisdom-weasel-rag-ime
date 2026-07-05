from __future__ import annotations

import unittest

from rag_ime.models import InputSuggestion, ModelPrediction, RimeCandidate, RimeContextSnapshot
from rag_ime.prediction_first import PredictionSessionPhase
from rag_ime.prediction_manager import PredictionManager


class PredictionManagerTests(unittest.TestCase):
    def test_post_commit_uses_fresh_candidate_sources(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        result = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=1,
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=5,
            ),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            suggestions=[_suggestion("把这个项目整理成面试项目", source_type="rag", initials="bzgxmzlmsxm")],
            now_ms=100,
        )

        self.assertEqual(result.session.phase, PredictionSessionPhase.POST_COMMIT)
        self.assertTrue(result.session.prediction_panel_visible)
        self.assertFalse(result.reused_candidate_pool)
        self.assertTrue(result.candidate_pool_active)
        self.assertEqual([item.source_type for item in result.display_candidates[:2]], ["model", "rag"])

    def test_prefix_composition_reuses_pool_and_filters_by_pinyin(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=1, committed_context="我想"),
            model_predictions=[
                _model("设计输入法状态机", initials="sjsrfztj"),
                _model("把这个项目整理成面试亮点", rank=2, initials="bzgxmzlmsld"),
            ],
            suggestions=[_suggestion("设计一个候选展示方式", source_type="memory", initials="sjyghxzsfs")],
            now_ms=100,
        )

        result = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                raw_input="sj",
                preedit="sj",
                committed_context="我想",
                candidates=(
                    RimeCandidate(text="手机", comment="wanxiang", index=0),
                    RimeCandidate(text="世界", comment="wanxiang", index=1),
                ),
                max_visible_candidates=5,
                max_side_candidates=3,
            ),
            now_ms=250,
        )

        self.assertTrue(result.reused_candidate_pool)
        self.assertEqual(result.session.phase, PredictionSessionPhase.PREFIX_CONSTRAINED)
        self.assertEqual(result.session.selection_scope, "mixed_prediction_first")
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["设计输入法状态机", "设计一个候选展示方式", "手机", "世界"],
        )
        self.assertEqual([item.source_type for item in result.display_candidates], ["model", "memory", "rime", "rime"])

    def test_expired_pool_soft_holds_post_commit_during_min_visible_window(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=1, committed_context="我想"),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            now_ms=100,
        )

        result = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                committed_context="我想",
                idle_ms=1500,
            ),
            now_ms=1401,
        )

        self.assertTrue(result.candidate_pool_stale)
        self.assertEqual(result.stability["action"], "soft_hold")
        self.assertFalse(result.candidate_pool_active)
        self.assertEqual(result.session.phase, PredictionSessionPhase.POST_COMMIT)
        self.assertFalse(result.session.should_clear_prediction_panel)
        self.assertEqual([item.text for item in result.display_candidates], ["做一个本地 RAG 输入法"])

    def test_expired_pool_clears_after_stability_window(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=1, committed_context="我想"),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            now_ms=100,
        )

        result = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                committed_context="我想",
                idle_ms=3000,
            ),
            now_ms=2301,
        )

        self.assertTrue(result.candidate_pool_stale)
        self.assertEqual(result.stability["action"], "soft_hide")
        self.assertEqual(result.session.phase, PredictionSessionPhase.HIDDEN)
        self.assertTrue(result.session.should_clear_prediction_panel)
        self.assertEqual(result.display_candidates, ())

    def test_context_change_does_not_reuse_previous_prediction_pool(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=1, committed_context="我想"),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            now_ms=100,
        )

        result = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                committed_context="现在切换到另一个上下文",
                candidates=(RimeCandidate(text="现在", comment="wanxiang", index=0),),
            ),
            now_ms=200,
        )

        self.assertFalse(result.reused_candidate_pool)
        self.assertFalse(result.candidate_pool_active)
        self.assertEqual(result.session.phase, PredictionSessionPhase.HIDDEN)
        self.assertEqual(result.display_candidates, ())

    def test_raw_input_passthrough_does_not_reuse_prediction_pool(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=1, committed_context="我想"),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            now_ms=100,
        )

        result = manager.render(
            snapshot=RimeContextSnapshot(session_id="s1", request_seq=2, raw_input="git status", preedit="git status"),
            raw_commit_text="git status",
            now_ms=200,
        )

        self.assertFalse(result.reused_candidate_pool)
        self.assertEqual(result.session.phase, PredictionSessionPhase.RAW_PASSTHROUGH)
        self.assertFalse(result.session.prediction_panel_visible)
        self.assertTrue(result.session.should_clear_prediction_panel)
        self.assertEqual([item.text for item in result.display_candidates], ["git status"])
        self.assertEqual(result.display_candidates[0].source_type, "raw_english")


def _model(text: str, *, rank: int = 1, initials: str = "") -> ModelPrediction:
    return ModelPrediction(
        text=text,
        rank=rank,
        provider_name="mock-mlx",
        latency_ms=12,
        confidence=0.8,
        metadata={"initials": initials} if initials else {},
    )


def _suggestion(text: str, *, source_type: str, initials: str = "") -> InputSuggestion:
    return InputSuggestion(
        suggestion_id=f"{source_type}-1",
        surface_text=text,
        suggestion_type="phrase",
        source_event_id=1,
        evidence_preview="fixture",
        confidence=0.85,
        metadata={"source_type": source_type, "initials": initials},
    )


if __name__ == "__main__":
    unittest.main()
