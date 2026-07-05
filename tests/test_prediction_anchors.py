from __future__ import annotations

import unittest

from rag_ime.models import FrontendTransaction, RimeCandidate, RimeContextSnapshot
from rag_ime.prediction_anchors import build_prediction_anchors_from_snapshot
from rag_ime.text_utils import stable_text_hash


class PredictionAnchorsTests(unittest.TestCase):
    def test_preedit_change_updates_query_not_hard_anchor(self) -> None:
        base = _snapshot(preedit="sj", raw_input="sj")
        changed = _snapshot(preedit="sja", raw_input="sja")

        first = build_prediction_anchors_from_snapshot(
            snapshot=base,
            mode="prefix_constrained_composing",
            semantic_query="设计 输入法",
            query_basis="rimeCandidates",
            stable_short_pinyin_prefix="sj",
        )
        second = build_prediction_anchors_from_snapshot(
            snapshot=changed,
            mode="prefix_constrained_composing",
            semantic_query="设计 输入法",
            query_basis="rimeCandidates",
            stable_short_pinyin_prefix="sja",
        )

        self.assertEqual(first.hard_context_anchor, second.hard_context_anchor)
        self.assertNotEqual(first.query_anchor, second.query_anchor)
        self.assertEqual(first.display_anchor, second.display_anchor)

    def test_frontend_transaction_change_updates_hard_anchor(self) -> None:
        first = build_prediction_anchors_from_snapshot(
            snapshot=_snapshot(selection_epoch=1, input_source_id="im.rime.inputmethod.Squirrel.Hans"),
            mode="post_commit_predicting",
            semantic_query="继续 输入法",
            query_basis="committedContext",
        )
        second = build_prediction_anchors_from_snapshot(
            snapshot=_snapshot(selection_epoch=2, input_source_id="com.apple.keylayout.ABC"),
            mode="post_commit_predicting",
            semantic_query="继续 输入法",
            query_basis="committedContext",
        )

        self.assertNotEqual(first.hard_context_anchor, second.hard_context_anchor)
        self.assertNotEqual(first.display_anchor, second.display_anchor)

    def test_rime_candidate_change_updates_query_not_display_anchor(self) -> None:
        first = build_prediction_anchors_from_snapshot(
            snapshot=_snapshot(candidates=(RimeCandidate(text="手机", index=0),)),
            mode="prefix_constrained_composing",
            semantic_query="sj 手机",
            query_basis="rimeCandidates",
            stable_short_pinyin_prefix="sj",
        )
        second = build_prediction_anchors_from_snapshot(
            snapshot=_snapshot(candidates=(RimeCandidate(text="世界", index=0),)),
            mode="prefix_constrained_composing",
            semantic_query="sj 世界",
            query_basis="rimeCandidates",
            stable_short_pinyin_prefix="sj",
        )

        self.assertEqual(first.hard_context_anchor, second.hard_context_anchor)
        self.assertNotEqual(first.query_anchor, second.query_anchor)
        self.assertEqual(first.display_anchor, second.display_anchor)


def _snapshot(
    *,
    preedit: str = "",
    raw_input: str = "",
    candidates: tuple[RimeCandidate, ...] = (),
    selection_epoch: int = 1,
    input_source_id: str = "im.rime.inputmethod.Squirrel.Hans",
) -> RimeContextSnapshot:
    committed = "我想设计一个稳定的输入法候选栏"
    return RimeContextSnapshot(
        session_id="squirrel-session",
        request_seq=1,
        raw_input=raw_input,
        preedit=preedit,
        committed_context=committed,
        candidates=candidates,
        frontend_transaction=FrontendTransaction(
            frontend_revision=3,
            selection_epoch=selection_epoch,
            front_app_bundle_id="com.apple.TextEdit",
            input_source_id=input_source_id,
            committed_context_hash=stable_text_hash(committed),
            composition_hash=stable_text_hash(""),
            panel_session_id="panel-1",
        ),
    )


if __name__ == "__main__":
    unittest.main()
