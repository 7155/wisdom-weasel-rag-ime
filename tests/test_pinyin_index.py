from __future__ import annotations

import unittest

from rag_ime.pinyin_index import build_pinyin_metadata, pinyin_prefixes, pinyin_search_document, text_initials


class PinyinIndexTests(unittest.TestCase):
    def test_builds_initials_for_local_phrase_memory(self) -> None:
        metadata = build_pinyin_metadata("设计一个候选展示方式")

        self.assertEqual(metadata["initials"], "sjyghxzsfs")
        self.assertIn("sjyghxzsfs", metadata["pinyin_prefixes"])
        self.assertIn("sj", metadata["pinyin_prefixes"])
        self.assertIn("hx", metadata["pinyin_prefixes"])

    def test_keeps_ascii_technical_tokens_searchable(self) -> None:
        self.assertEqual(text_initials("Qwen RAG 输入法"), "qwenragsrf")
        prefixes = pinyin_prefixes("Qwen RAG 输入法")

        self.assertIn("qwen", prefixes)
        self.assertIn("rag", prefixes)
        self.assertIn("srf", prefixes)

    def test_search_document_contains_initials_for_sqlite_fts(self) -> None:
        document = pinyin_search_document("设计一个候选展示方式", "输入法候选")

        self.assertIn("sjyghxzsfs", document.split())
        self.assertIn("sj", document.split())
        self.assertIn("hx", document.split())


if __name__ == "__main__":
    unittest.main()
