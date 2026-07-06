from __future__ import annotations

import unittest

from rag_ime.prediction_status import PredictionStatusState, build_prediction_status_rows, prediction_status_row


class PredictionStatusTests(unittest.TestCase):
    def test_status_row_has_no_selection_key(self) -> None:
        row = prediction_status_row(rag_pending=True, model_pending=True, waiting_ms=480, latest_generation=17)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.source_type, "status")
        self.assertEqual(row.selection_action, "none")
        self.assertEqual(row.label, "")
        self.assertEqual(row.insert_text, "")
        self.assertEqual(row.metadata["candidateOrdinal"], 0)
        self.assertIsNone(row.metadata["selectionKey"])
        self.assertFalse(row.metadata["isSelectable"])
        self.assertTrue(row.metadata["isStatus"])
        self.assertEqual(row.display_lane, "post_commit_status")

    def test_status_row_is_visible_immediately_after_commit(self) -> None:
        row = prediction_status_row(rag_pending=True, model_pending=False, waiting_ms=0, latest_generation=1)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("RAG", row.text)

    def test_model_pending_text_is_specific(self) -> None:
        row = prediction_status_row(rag_pending=False, model_pending=True, waiting_ms=700, latest_generation=2)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("LLM", row.text)

    def test_rag_ready_model_pending_text_is_append_phase(self) -> None:
        row = prediction_status_row(
            rag_pending=False,
            model_pending=True,
            waiting_ms=1200,
            latest_generation=3,
            rag_state="ready",
            model_state="pending",
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("RAG 已返回", row.text)
        self.assertIn("LLM", row.text)

    def test_build_prediction_status_rows_hides_diagnostics_by_default(self) -> None:
        rows = build_prediction_status_rows(
            PredictionStatusState(
                rag_state="stale_dropped",
                model_state="pending",
                waiting_ms=30,
                trigger="rime_candidate_commit",
                stale_drop_reason="input_generation_changed",
            )
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("旧响应已丢弃", rows[0].text)
        self.assertNotIn("input_generation_changed", rows[0].text)


if __name__ == "__main__":
    unittest.main()
