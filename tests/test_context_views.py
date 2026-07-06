from __future__ import annotations

import unittest

from rag_ime.context_frame import build_current_input_frame
from rag_ime.context_views import (
    RagEvidenceItem,
    build_display_view,
    build_model_prompt_view,
    build_rag_prediction_view,
    build_rag_retrieval_view,
    build_rime_view,
)
from rag_ime.models import RimeCandidate, RimeContextSnapshot, SideCandidateDisplayItem


class ContextViewsTests(unittest.TestCase):
    def test_model_view_uses_committed_tail_not_full_history(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=1,
            commit_text_preview="继续优化候选",
            committed_context="很长历史" * 80,
        )
        frame = build_current_input_frame(snapshot, ui_mode="post_commit_prediction")

        view = build_model_prompt_view(frame)

        self.assertEqual(view.request_type, "post_commit_prediction")
        self.assertEqual(view.query, "继续优化候选")
        self.assertLessEqual(len(view.recent_context_tail), 160)
        self.assertEqual(view.max_candidates, 3)

    def test_rag_view_uses_semantic_query_and_project_scope(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=2,
            committed_context="候选展示方式",
            project="wisdom-weasel-rag-ime",
            app="TextEdit",
        )
        frame = build_current_input_frame(snapshot, ui_mode="post_commit_prediction")

        view = build_rag_retrieval_view(frame, semantic_query="候选展示", query_basis="semantic")

        self.assertEqual(view.semantic_query, "候选展示")
        self.assertEqual(view.query_basis, "semantic")
        self.assertEqual(view.project, "wisdom-weasel-rag-ime")
        self.assertIn("raw_echo", view.negative_signals)

    def test_rag_prediction_view_uses_evidence_pack_not_raw_history(self) -> None:
        snapshot = RimeContextSnapshot(session_id="s1", request_seq=3, commit_text_preview="展示方式")
        frame = build_current_input_frame(snapshot, ui_mode="post_commit_prediction")
        evidence = (
            RagEvidenceItem(
                evidence_id="e1",
                source_type="stable_memory",
                text="很长的 evidence 原文不应该直接上屏",
                summary="候选展示",
                tags=("ui",),
                memory_ids=("m1",),
                evidence_event_ids=(1,),
                score=0.8,
            ),
        )

        view = build_rag_prediction_view(frame, evidence)

        self.assertEqual(view.candidate_style, "short_ime_candidate")
        self.assertEqual(view.evidence_pack, evidence)
        self.assertEqual(view.max_candidates, 3)

    def test_composition_rime_view_keeps_rime_context(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=4,
            raw_input="chuxian",
            preedit="chuxian",
            candidates=(RimeCandidate(text="出现"), RimeCandidate(text="初显")),
            highlighted_index=1,
        )
        frame = build_current_input_frame(snapshot, ui_mode="composition_rime")

        view = build_rime_view(frame)

        self.assertEqual(view.candidates, ("出现", "初显"))
        self.assertEqual(view.highlighted_index, 1)

    def test_display_view_splits_status_rows_from_selectable_candidates(self) -> None:
        frame = build_current_input_frame(RimeContextSnapshot(session_id="s1", request_seq=5), ui_mode="post_commit_pending")
        status = SideCandidateDisplayItem(
            label="",
            text="查忆处理中…",
            insert_text="",
            source_type="status",
            selection_action="none",
            source_index=0,
            display_layout="status_row",
        )
        candidate = SideCandidateDisplayItem(
            label="1",
            text="候选稳定性",
            insert_text="候选稳定性",
            source_type="model",
            selection_action="commit_side_candidate",
            source_index=0,
        )

        view = build_display_view(frame, candidates=(status, candidate), key_policy={"numberKeys": "select_visible_candidate"})

        self.assertEqual(len(view.status_rows), 1)
        self.assertEqual(len(view.visible_candidates), 1)
        self.assertEqual(view.key_policy["numberKeys"], "select_visible_candidate")


if __name__ == "__main__":
    unittest.main()

