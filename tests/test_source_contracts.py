from __future__ import annotations

import unittest

from rag_ime.contracts.source import (
    SOURCE_BADGES,
    SOURCE_COLOR_TOKENS,
    SOURCE_MEMORY,
    SOURCE_MODEL,
    SOURCE_RAG,
    SOURCE_RAW_ENGLISH,
    SOURCE_RIME,
    SOURCE_STATUS,
    source_badge_for,
    source_color_token_for,
)
from rag_ime.rime_sidecar import candidate_color_token, candidate_source_badge


class SourceContractTests(unittest.TestCase):
    def test_v1_source_badges_and_colors_are_stable(self) -> None:
        self.assertEqual(SOURCE_BADGES[SOURCE_RIME], "词")
        self.assertEqual(SOURCE_BADGES[SOURCE_MODEL], "模")
        self.assertEqual(SOURCE_BADGES[SOURCE_RAG], "查")
        self.assertEqual(SOURCE_BADGES[SOURCE_MEMORY], "忆")
        self.assertEqual(SOURCE_BADGES[SOURCE_RAW_ENGLISH], "input")
        self.assertEqual(SOURCE_BADGES[SOURCE_STATUS], "查忆")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_RIME], "rimeOrange")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_MODEL], "modelBlue")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_RAG], "ragTeal")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_MEMORY], "memoryPurple")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_RAW_ENGLISH], "rawGray")
        self.assertEqual(SOURCE_COLOR_TOKENS[SOURCE_STATUS], "statusGray")

    def test_unknown_source_badge_falls_back_to_source_type_but_color_is_empty(self) -> None:
        self.assertEqual(source_badge_for("custom"), "custom")
        self.assertEqual(source_color_token_for("custom"), "")

    def test_rime_sidecar_keeps_runtime_badge_color_switches_around_source_contract(self) -> None:
        self.assertEqual(candidate_source_badge("model", {"RAG_IME_CANDIDATE_SOURCE_BADGES": "1"}), "模")
        self.assertEqual(candidate_source_badge("model", {"RAG_IME_CANDIDATE_SOURCE_BADGES": "0"}), "")
        self.assertEqual(candidate_color_token("rag", {"RAG_IME_CANDIDATE_SOURCE_COLORS": "1"}), "ragTeal")
        self.assertEqual(candidate_color_token("rag", {"RAG_IME_CANDIDATE_SOURCE_COLORS": "false"}), "")


if __name__ == "__main__":
    unittest.main()
