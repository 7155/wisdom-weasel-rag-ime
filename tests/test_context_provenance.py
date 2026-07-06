from __future__ import annotations

import unittest

from rag_ime.context_provenance import committed_source, selected_text_identity, source_confidence


class ContextProvenanceTests(unittest.TestCase):
    def test_source_confidence_is_explicit_and_ordered(self) -> None:
        self.assertEqual(source_confidence("rime_composition"), 1.0)
        self.assertGreater(source_confidence("ime_commit_ledger"), source_confidence("clipboard_fallback"))
        self.assertEqual(source_confidence("unknown"), 0.0)

    def test_committed_source_defaults_to_ime_ledger_when_text_exists(self) -> None:
        self.assertEqual(committed_source(committed_context="已经输入", commit_text_preview=""), "ime_commit_ledger")
        self.assertEqual(committed_source(committed_context="", commit_text_preview=""), "unknown")

    def test_selected_text_identity_uses_hash_and_chars(self) -> None:
        text_hash, chars = selected_text_identity("  选中文本  ")

        self.assertTrue(text_hash.startswith("sha256:"))
        self.assertEqual(chars, 4)


if __name__ == "__main__":
    unittest.main()

