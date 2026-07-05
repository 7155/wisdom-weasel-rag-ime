from __future__ import annotations

import unittest

from rag_ime.models import SideCandidateDisplayItem
from rag_ime.prediction_anchors import build_prediction_anchors
from rag_ime.prediction_stability import (
    StablePanelState,
    render_stable_prediction_panel,
)


class PredictionStabilityTests(unittest.TestCase):
    def test_model_timeout_reuses_last_good_snapshot(self) -> None:
        state = StablePanelState()
        anchors = _anchors()
        first, state, first_diag = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(_candidate("继续预测", "model"),),
            trigger_decision={"shouldRefresh": True},
            rag_lane={"called": True, "suggestionCount": 0},
            model_lane={"called": True, "predictionCount": 1},
            now_ms=1000,
        )

        self.assertIsNotNone(first)
        self.assertEqual(first_diag["action"], "fresh")

        reused, state, diag = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(),
            trigger_decision={"shouldRefresh": True},
            rag_lane={"called": True, "suggestionCount": 0},
            model_lane={"called": True, "timedOut": True, "predictionCount": 0},
            now_ms=3100,
        )

        self.assertIsNotNone(reused)
        self.assertEqual(diag["action"], "reuse_last_good")
        self.assertTrue(reused.reused_last_good)
        self.assertEqual([item.text for item in reused.candidates], ["继续预测"])

    def test_empty_rag_response_soft_holds_during_min_visible_window(self) -> None:
        state = StablePanelState()
        anchors = _anchors(mode="prefix_constrained_composing")
        _, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="prefix_constrained_composing",
            fresh_candidates=(_candidate("设计输入法状态机", "memory"),),
            trigger_decision={"shouldRefresh": True},
            rag_lane={"called": True, "suggestionCount": 1},
            model_lane={"called": True, "predictionCount": 0},
            now_ms=1000,
        )

        held, _, diag = render_stable_prediction_panel(
            state=state,
            anchors=_anchors(mode="prefix_constrained_composing", semantic_query="sj 世界"),
            mode="prefix_constrained_composing",
            fresh_candidates=(),
            trigger_decision={"shouldRefresh": True},
            rag_lane={"called": True, "suggestionCount": 0},
            model_lane={"called": True, "predictionCount": 0},
            now_ms=1500,
        )

        self.assertIsNotNone(held)
        self.assertEqual(diag["action"], "soft_hold")
        self.assertEqual(held.stale_level, "holdover")

    def test_hard_anchor_change_clears_snapshot(self) -> None:
        state = StablePanelState()
        _, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=_anchors(selection_epoch=1),
            mode="post_commit_predicting",
            fresh_candidates=(_candidate("继续预测", "model"),),
            now_ms=1000,
        )

        cleared, state, diag = render_stable_prediction_panel(
            state=state,
            anchors=_anchors(selection_epoch=2),
            mode="post_commit_predicting",
            fresh_candidates=(),
            now_ms=1200,
        )

        self.assertIsNone(cleared)
        self.assertIsNone(state.last_snapshot)
        self.assertEqual(diag["action"], "hard_clear")
        self.assertEqual(diag["reason"], "hard_context_anchor_changed")

    def test_snapshot_expires_after_ttl(self) -> None:
        state = StablePanelState()
        anchors = _anchors(mode="prefix_constrained_composing")
        _, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="prefix_constrained_composing",
            fresh_candidates=(_candidate("设计输入法状态机", "model"),),
            now_ms=1000,
        )

        expired, state, diag = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="prefix_constrained_composing",
            fresh_candidates=(),
            now_ms=3301,
        )

        self.assertIsNone(expired)
        self.assertIsNone(state.last_snapshot)
        self.assertEqual(diag["action"], "soft_hide")
        self.assertEqual(diag["reason"], "snapshot_expired")


def _anchors(
    *,
    mode: str = "post_commit_predicting",
    semantic_query: str = "继续 输入法",
    selection_epoch: int = 1,
):
    return build_prediction_anchors(
        session_id="squirrel-session",
        panel_session_id="panel-1",
        front_app_bundle_id="com.apple.TextEdit",
        input_source_id="im.rime.inputmethod.Squirrel.Hans",
        selection_epoch=selection_epoch,
        committed_context_hash="sha256:context",
        composition_hash="sha256:composition",
        mode=mode,
        semantic_query=semantic_query,
        query_basis="committedContext",
        stable_short_pinyin_prefix="sj",
    )


def _candidate(text: str, source_type: str) -> SideCandidateDisplayItem:
    return SideCandidateDisplayItem(
        label="1",
        text=text,
        insert_text=text,
        source_type=source_type,
        selection_action="commit_side_candidate",
        source_index=0,
    )


if __name__ == "__main__":
    unittest.main()
