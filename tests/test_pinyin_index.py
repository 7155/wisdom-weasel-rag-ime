from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from rag_ime.pinyin_index import fuzzy_pinyin_variants, pinyin_search_document, pinyin_search_terms


@contextmanager
def _patched_env(**updates: str):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class PinyinIndexTests(unittest.TestCase):
    def test_sichuan_mild_fuzzy_variants_cover_common_pairs(self) -> None:
        self.assertIn("sijie", fuzzy_pinyin_variants("shijie"))
        self.assertIn("shijie", fuzzy_pinyin_variants("sijie"))
        self.assertIn("chen", fuzzy_pinyin_variants("cheng"))
        self.assertIn("qing", fuzzy_pinyin_variants("qin"))
        self.assertIn("yong", fuzzy_pinyin_variants("yon"))
        self.assertNotIn("lian", fuzzy_pinyin_variants("nian"))
        self.assertNotIn("fua", fuzzy_pinyin_variants("hua"))

    def test_fuzzy_pairs_can_be_controlled_by_runtime_settings_env(self) -> None:
        with _patched_env(
            RAG_IME_PINYIN_FUZZY_S_SH="0",
            RAG_IME_PINYIN_FUZZY_ONG_ON="0",
            RAG_IME_PINYIN_FUZZY_N_L="1",
        ):
            self.assertNotIn("sijie", fuzzy_pinyin_variants("shijie"))
            self.assertNotIn("yong", fuzzy_pinyin_variants("yon"))
            self.assertIn("lian", fuzzy_pinyin_variants("nian"))

    def test_phrase_search_document_includes_full_pinyin_and_fuzzy_forms(self) -> None:
        document = set(pinyin_search_document("输入法 世界 设计").split())

        self.assertIn("shurufa", document)
        self.assertIn("surufa", document)
        self.assertIn("shijie", document)
        self.assertIn("sijie", document)
        self.assertIn("sheji", document)
        self.assertIn("seji", document)

    def test_search_terms_distinguish_exact_and_fuzzy_for_rerank(self) -> None:
        terms = pinyin_search_terms("世界 设计")

        self.assertEqual(terms["shijie"], "exact")
        self.assertEqual(terms["sheji"], "exact")
        self.assertEqual(terms["sijie"], "fuzzy")
        self.assertEqual(terms["seji"], "fuzzy")


if __name__ == "__main__":
    unittest.main()
