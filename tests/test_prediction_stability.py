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

    def test_candidate_ordinals_do_not_change_during_progressive_update(self) -> None:
        state = StablePanelState()
        anchors = _anchors()
        first, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(
                _candidate("继续预测", "model", source_index=0),
                _candidate("整理 RAG 记忆", "rag", source_index=0),
            ),
            now_ms=1000,
        )

        updated, _, diag = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(
                _candidate("继续预测", "model", source_index=0),
                _candidate("整理 RAG 记忆", "rag", source_index=0),
                _candidate("补一个后续预测", "model", source_index=1),
            ),
            now_ms=1200,
            progressive_update=True,
            max_visible_candidates=5,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(updated)
        self.assertEqual(diag["action"], "progressive_append")
        self.assertEqual(updated.snapshot_id, first.snapshot_id)
        self.assertEqual([item.text for item in updated.candidates[:2]], ["继续预测", "整理 RAG 记忆"])
        self.assertEqual([item.text for item in updated.candidates], ["继续预测", "整理 RAG 记忆", "补一个后续预测"])
        self.assertEqual(diag["preservedOrdinalCount"], 2)
        self.assertEqual(diag["appendedCandidateCount"], 1)

    def test_progressive_update_can_append_but_not_reorder_visible_candidates(self) -> None:
        state = StablePanelState()
        anchors = _anchors()
        first, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(
                _candidate("先显示 RAG", "rag", source_index=0),
                _candidate("第二个记忆", "memory", source_index=0),
            ),
            now_ms=1000,
        )

        replaced, _, diag = render_stable_prediction_panel(
            state=state,
            anchors=anchors,
            mode="post_commit_predicting",
            fresh_candidates=(
                _candidate("模型回来后想排第一", "model", source_index=0),
                _candidate("先显示 RAG", "rag", source_index=0),
                _candidate("第二个记忆", "memory", source_index=0),
            ),
            now_ms=1300,
            progressive_update=True,
            max_visible_candidates=5,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(replaced)
        self.assertEqual(diag["action"], "progressive_replace")
        self.assertNotEqual(replaced.snapshot_id, first.snapshot_id)
        self.assertEqual([item.text for item in replaced.candidates], ["模型回来后想排第一", "先显示 RAG", "第二个记忆"])
        self.assertEqual(diag["preservedOrdinalCount"], 0)

    def test_prefix_filter_removes_only_incompatible_holdover_candidates(self) -> None:
        state = StablePanelState()
        first, state, _ = render_stable_prediction_panel(
            state=state,
            anchors=_anchors(mode="prefix_constrained_composing", semantic_query="s 世界", pinyin_prefix="s"),
            mode="prefix_constrained_composing",
            fresh_candidates=(
                _candidate("设计输入法状态机", "model", source_index=0, initials="sjsrfztj"),
                _candidate("输入候选", "model", source_index=1, initials="srhx"),
                _candidate("手机", "rime", source_index=0),
            ),
            now_ms=1000,
        )

        filtered, _, diag = render_stable_prediction_panel(
            state=state,
            anchors=_anchors(mode="prefix_constrained_composing", semantic_query="sj 世界", pinyin_prefix="sj"),
            mode="prefix_constrained_composing",
            fresh_candidates=(),
            rag_lane={"called": True, "suggestionCount": 0},
            model_lane={"called": True, "predictionCount": 0},
            now_ms=1300,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(filtered)
        self.assertEqual(diag["action"], "prefix_filter")
        self.assertEqual(diag["prefixRemovedCandidateCount"], 1)
        self.assertEqual(diag["prefixKeptSideCandidateCount"], 1)
        self.assertNotEqual(filtered.snapshot_id, first.snapshot_id)
        self.assertEqual([item.text for item in filtered.candidates], ["设计输入法状态机", "手机"])


def _anchors(
    *,
    mode: str = "post_commit_predicting",
    semantic_query: str = "继续 输入法",
    selection_epoch: int = 1,
    pinyin_prefix: str = "sj",
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
        stable_short_pinyin_prefix=pinyin_prefix,
    )


def _candidate(
    text: str,
    source_type: str,
    *,
    source_index: int = 0,
    initials: str = "",
) -> SideCandidateDisplayItem:
    return SideCandidateDisplayItem(
        label="1",
        text=text,
        insert_text=text,
        source_type=source_type,
        selection_action="commit_side_candidate",
        source_index=source_index,
        metadata={"initials": initials} if initials else {},
    )


if __name__ == "__main__":
    unittest.main()
