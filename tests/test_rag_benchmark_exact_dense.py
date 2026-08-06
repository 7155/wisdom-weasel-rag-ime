from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.knowledge_library.dense import SqliteDenseIndex
from rag_ime.rag_benchmark_exact_dense import BenchmarkExactDenseIndex


class _CountingProvider:
    fingerprint = "counting-exact-v1"

    def __init__(self) -> None:
        self.query_calls = 0

    def embed(self, text: str) -> list[float]:
        if "alpha" in text:
            return [1.0, 0.0]
        if "beta" in text:
            return [0.0, 1.0]
        return [1.0, 1.0]

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self.embed(text)


class BenchmarkExactDenseIndexTests(unittest.TestCase):
    def test_exact_scan_is_stable_scoped_and_caches_query_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = _CountingProvider()
            index = BenchmarkExactDenseIndex(Path(temporary) / "knowledge.sqlite", provider)
            index.replace_document(
                "doc-alpha",
                [
                    {
                        "id": "chunk-alpha",
                        "base_id": "base-a",
                        "content": "alpha",
                    }
                ],
            )
            index.replace_document(
                "doc-beta",
                [
                    {
                        "id": "chunk-beta",
                        "base_id": "base-b",
                        "content": "beta",
                    }
                ],
            )

            first = index.search("alpha query", base_ids=(), limit=2)
            second = index.search("alpha query", base_ids=(), limit=2)
            scoped = index.search("alpha query", base_ids=("base-b",), limit=2)

            self.assertEqual(first, second)
            self.assertEqual(first[0][0], "chunk-alpha")
            self.assertEqual(scoped, [("chunk-beta", 0.0)])
            self.assertEqual(provider.query_calls, 1)
            status = index.status()
            self.assertTrue(status["benchmarkDeterministicExact"])
            self.assertTrue(status["benchmarkMatrixCached"])
            self.assertEqual(status["benchmarkQueryCacheEntries"], 1)

            reference = SqliteDenseIndex(
                Path(temporary) / "knowledge.sqlite",
                _CountingProvider(),
            ).search("alpha query", base_ids=(), limit=2)
            self.assertEqual(
                [chunk_id for chunk_id, _score in first],
                [chunk_id for chunk_id, _score in reference],
            )
            for (_chunk_id, actual), (_reference_id, expected) in zip(first, reference):
                self.assertAlmostEqual(actual, expected, places=12)


if __name__ == "__main__":
    unittest.main()
