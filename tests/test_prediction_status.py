from __future__ import annotations

import unittest

from rag_ime.prediction_status import prediction_status_row


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

    def test_status_row_is_hidden_before_threshold(self) -> None:
        self.assertIsNone(prediction_status_row(rag_pending=True, model_pending=False, waiting_ms=80, latest_generation=1))

    def test_model_pending_text_is_specific(self) -> None:
        row = prediction_status_row(rag_pending=False, model_pending=True, waiting_ms=700, latest_generation=2)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("LLM", row.text)


if __name__ == "__main__":
    unittest.main()
