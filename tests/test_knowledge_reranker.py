from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.knowledge_library.rerank import (
    MlxQwen3KnowledgeReranker,
    knowledge_reranker_from_env,
    knowledge_reranker_profile_sha256,
)


class _FakeRuntime:
    def __init__(self, _path: Path, _instruction: str, _max_length: int) -> None:
        self.closed = 0

    def score(self, _query: str, document: str) -> float:
        if "直接证据" in document:
            return 0.9
        if "次要" in document:
            return 0.4
        return 0.1

    def close_batch(self) -> None:
        self.closed += 1


class KnowledgeRerankerTests(unittest.TestCase):
    def test_worker_factory_is_disabled_by_default_and_uses_explicit_model_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-reranker-factory-") as temporary:
            root = Path(temporary)
            model = root / "model"
            model.mkdir()
            for name in (
                "config.json",
                "generation_config.json",
                "model.safetensors",
                "model.safetensors.index.json",
                "tokenizer.json",
                "tokenizer_config.json",
            ):
                (model / name).write_bytes((name + "\n").encode("utf-8"))

            self.assertIsNone(knowledge_reranker_from_env(root, environ={}))
            reranker = knowledge_reranker_from_env(
                root,
                environ={
                    "RAG_IME_KNOWLEDGE_RERANK_PROVIDER": "mlx-qwen3-reranker",
                    "RAG_IME_KNOWLEDGE_RERANK_MODEL_PATH": str(model),
                    "RAG_IME_KNOWLEDGE_RERANK_MODEL_REVISION": "fixture-revision",
                },
            )

            self.assertIsNotNone(reranker)
            status = reranker.status()
            self.assertTrue(status["configured"])
            self.assertIn("fixture-revision", status["modelReference"])
            self.assertFalse(status["subagentSubstitute"])

            first_profile = knowledge_reranker_profile_sha256(
                environ={
                    "RAG_IME_KNOWLEDGE_RERANK_PROVIDER": "mlx-qwen3-reranker",
                    "RAG_IME_KNOWLEDGE_RERANK_MODEL_PATH": str(model),
                }
            )
            changed_profile = knowledge_reranker_profile_sha256(
                environ={
                    "RAG_IME_KNOWLEDGE_RERANK_PROVIDER": "mlx-qwen3-reranker",
                    "RAG_IME_KNOWLEDGE_RERANK_MODEL_PATH": str(model),
                    "RAG_IME_KNOWLEDGE_RERANK_INSTRUCTION": "changed instruction",
                }
            )
            self.assertNotEqual(first_profile, changed_profile)

    def test_reranks_bounded_unique_candidates_and_records_stage_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-reranker-") as temporary:
            model = Path(temporary)
            for name in (
                "config.json",
                "generation_config.json",
                "model.safetensors",
                "model.safetensors.index.json",
                "tokenizer.json",
                "tokenizer_config.json",
            ):
                (model / name).write_bytes((name + "\n").encode("utf-8"))
            reranker = MlxQwen3KnowledgeReranker(
                model,
                model_revision="fixture-revision",
                runtime_factory=_FakeRuntime,
            )
            candidates = [
                {"externalDocumentId": "noise", "content": "无关内容"},
                {"externalDocumentId": "answer", "content": "这里有直接证据"},
                {"externalDocumentId": "secondary", "content": "次要材料"},
                {"externalDocumentId": "answer", "content": "重复直接证据"},
            ]

            ranked = reranker.rerank("问题", candidates, limit=2)
            cached = reranker.rerank("问题", candidates, limit=2)

        self.assertEqual(["answer", "secondary"], [item["externalDocumentId"] for item in ranked])
        self.assertEqual(2, ranked[0]["rerankOriginalRank"])
        self.assertEqual(1, ranked[0]["rerankRank"])
        self.assertEqual(ranked, cached)
        status = reranker.status()
        self.assertTrue(status["configured"])
        self.assertTrue(status["independentStage"])
        self.assertFalse(status["subagentSubstitute"])
        self.assertEqual(2, status["calls"])
        self.assertEqual(3, status["scoredPairs"])
        self.assertEqual(3, status["cacheHits"])
        self.assertEqual(0, status["fallbackCount"])
        self.assertEqual(0, status["errorCount"])
        self.assertIn("fixture-revision", status["modelReference"])

    def test_missing_model_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-reranker-missing-") as temporary:
            reranker = MlxQwen3KnowledgeReranker(
                Path(temporary),
                runtime_factory=_FakeRuntime,
            )
            self.assertFalse(reranker.status()["configured"])
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                reranker.rerank(
                    "问题",
                    [{"documentId": "doc", "content": "证据"}],
                    limit=1,
                )

    def test_hash_only_score_cache_reuses_scores_across_instances(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-reranker-cache-") as temporary:
            model = Path(temporary) / "model"
            model.mkdir()
            for name in (
                "config.json",
                "generation_config.json",
                "model.safetensors",
                "model.safetensors.index.json",
                "tokenizer.json",
                "tokenizer_config.json",
            ):
                (model / name).write_bytes((name + "\n").encode("utf-8"))
            cache = Path(temporary) / "private-cache" / "scores.json"
            first = MlxQwen3KnowledgeReranker(
                model,
                cache_path=cache,
                runtime_factory=_FakeRuntime,
            )
            candidates = [{"chunkId": "chunk-1", "content": "这里有直接证据"}]
            first.rerank("问题", candidates, limit=1)
            second = MlxQwen3KnowledgeReranker(
                model,
                cache_path=cache,
                runtime_factory=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("cache hit must not initialize the MLX runtime")
                ),
            )
            ranked = second.rerank("问题", candidates, limit=1)

            self.assertEqual("chunk-1", ranked[0]["chunkId"])
            self.assertEqual(0, second.status()["scoredPairs"])
            self.assertEqual(1, second.status()["cacheHits"])
            self.assertEqual(1, second.status()["persistentCacheLoadedEntries"])
            payload = cache.read_text(encoding="utf-8")
            self.assertNotIn("问题", payload)
            self.assertNotIn("直接证据", payload)


if __name__ == "__main__":
    unittest.main()
