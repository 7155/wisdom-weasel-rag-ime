from __future__ import annotations

import unittest

from rag_ime.models import FrontendTransaction, InputSuggestion, ModelPrediction, RimeCandidate, RimeContextSnapshot
from rag_ime.prediction_first import PredictionSessionPhase
from rag_ime.prediction_manager import PredictionManager
from rag_ime.text_utils import stable_text_hash


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

    def test_prefix_composition_filters_holdover_without_reusing_source_cache(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        transaction = _composition_transaction(raw="s", panel_session_id="panel-prefix-reuse")
        manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=1,
                raw_input="s",
                preedit="s",
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=3,
                frontend_transaction=transaction,
            ),
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
                frontend_transaction=_composition_transaction(raw="sj", panel_session_id="panel-prefix-reuse"),
            ),
            now_ms=250,
        )

        self.assertFalse(result.reused_candidate_pool)
        self.assertFalse(result.candidate_pool_active)
        self.assertEqual(result.context_fingerprint, result.anchors.query_anchor)
        self.assertEqual(result.stability["action"], "soft_hold")
        self.assertEqual(result.stability["reason"], "min_visible_window")
        self.assertEqual(result.session.phase, PredictionSessionPhase.PREFIX_CONSTRAINED)
        self.assertEqual(result.session.selection_scope, "mixed_prediction_first")
        self.assertEqual(
            [item.text for item in result.display_candidates],
            ["设计输入法状态机", "设计一个候选展示方式"],
        )
        self.assertEqual([item.source_type for item in result.display_candidates], ["model", "memory"])

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

    def test_progressive_follow_up_appends_without_changing_existing_ordinals(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        first = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=1,
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=5,
            ),
            model_predictions=[_model("做一个本地 RAG 输入法", initials="zygbdragsrf")],
            now_ms=100,
        )

        second = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=5,
                progressive_follow_up=True,
            ),
            model_predictions=[
                _model("做一个本地 RAG 输入法", initials="zygbdragsrf"),
                _model("连续弹出下一个预测", rank=2, initials="lxtcxygyc"),
            ],
            now_ms=250,
        )

        self.assertIsNotNone(first.stable_snapshot)
        self.assertIsNotNone(second.stable_snapshot)
        self.assertEqual(second.stability["action"], "progressive_append")
        self.assertEqual(second.stable_snapshot.snapshot_id, first.stable_snapshot.snapshot_id)
        self.assertEqual([item.text for item in second.display_candidates], ["做一个本地 RAG 输入法", "连续弹出下一个预测"])
        self.assertEqual(second.stability["preservedOrdinalCount"], 1)
        self.assertEqual(second.stability["appendedCandidateCount"], 1)
        self.assertEqual(second.stability["replacedCandidateCount"], 0)

    def test_stale_prefix_pool_filters_incompatible_holdover_candidates(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1)
        transaction = _composition_transaction()
        first = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=1,
                raw_input="s",
                preedit="s",
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=5,
                frontend_transaction=transaction,
            ),
            model_predictions=[
                _model("设计输入法状态机", initials="sjsrfztj"),
                _model("输入候选", rank=2, initials="srhx"),
            ],
            now_ms=100,
        )

        second = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                raw_input="sj",
                preedit="sj",
                committed_context="我想",
                max_visible_candidates=5,
                max_side_candidates=5,
                frontend_transaction=transaction,
            ),
            now_ms=200,
        )

        self.assertEqual([item.text for item in first.display_candidates], ["设计输入法状态机", "输入候选"])
        self.assertFalse(second.reused_candidate_pool)
        self.assertFalse(second.candidate_pool_active)
        self.assertFalse(second.candidate_pool_stale)
        self.assertEqual(second.context_fingerprint, second.anchors.query_anchor)
        self.assertEqual(second.stability["action"], "prefix_filter")
        self.assertEqual(second.stability["prefixRemovedCandidateCount"], 1)
        self.assertEqual([item.text for item in second.display_candidates], ["设计输入法状态机"])
        self.assertEqual(second.session.phase, PredictionSessionPhase.PREFIX_CONSTRAINED)
        self.assertFalse(second.session.should_clear_prediction_panel)

    def test_same_committed_context_different_rime_top_does_not_reuse_source_cache(self) -> None:
        manager = PredictionManager(candidate_pool_ttl_ms=1200)
        first = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=1,
                raw_input="s",
                preedit="s",
                committed_context="我想",
                candidates=(RimeCandidate(text="手机", comment="wanxiang", index=0),),
                frontend_transaction=_composition_transaction(raw="s", panel_session_id="panel-rime-top"),
            ),
            model_predictions=[_model("设计输入法状态机", initials="sjsrfztj")],
            now_ms=100,
        )

        second = manager.render(
            snapshot=RimeContextSnapshot(
                session_id="s1",
                request_seq=2,
                raw_input="s",
                preedit="s",
                committed_context="我想",
                candidates=(RimeCandidate(text="世界", comment="wanxiang", index=0),),
                frontend_transaction=_composition_transaction(raw="s", panel_session_id="panel-rime-top"),
            ),
            now_ms=200,
        )

        self.assertNotEqual(first.context_fingerprint, second.context_fingerprint)
        self.assertEqual(second.context_fingerprint, second.anchors.query_anchor)
        self.assertFalse(second.reused_candidate_pool)
        self.assertFalse(second.candidate_pool_active)


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


def _composition_transaction(*, raw: str = "s", panel_session_id: str = "panel-prefix-filter") -> FrontendTransaction:
    return FrontendTransaction(
        frontend_revision=12,
        selection_epoch=3,
        front_app_bundle_id="com.apple.TextEdit",
        input_source_id="im.rime.inputmethod.Squirrel.Hans",
        composition_hash=stable_text_hash(raw),
        committed_context_hash=stable_text_hash("我想"),
        panel_session_id=panel_session_id,
    )


if __name__ == "__main__":
    unittest.main()
