from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from rag_ime.embeddings import (
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
    MlxBertEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    embed_query,
    embedding_provider_from_env,
)


class _MockEmbeddingHandler(BaseHTTPRequestHandler):
    call_count = 0
    captured_payloads: list[dict[str, object]] = []
    embeddings: list[list[float]] = [[1.0, 0.0, 0.0]]

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).call_count += 1
        type(self).captured_payloads.append(payload)
        input_value = payload.get("input")
        index = min(type(self).call_count - 1, len(type(self).embeddings) - 1)
        if isinstance(input_value, list):
            vectors = type(self).embeddings[:len(input_value)]
        else:
            vectors = [type(self).embeddings[index]]
        body = json.dumps(
            {
                "data": [
                    {
                        "index": item_index,
                        "embedding": embedding,
                    }
                    for item_index, embedding in enumerate(vectors)
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class EmbeddingProviderTests(unittest.TestCase):
    def test_sentence_transformer_provider_separates_query_and_document_prefixes(self) -> None:
        provider = SentenceTransformerEmbeddingProvider(
            model="BAAI/bge-base-zh-v1.5",
            query_prefix="查询：",
            document_prefix="结果：",
            cache_size=4,
        )
        fake_model = Mock()
        fake_vector = Mock()
        fake_vector.tolist.return_value = [1.0, 0.0]
        fake_model.encode.return_value = fake_vector
        provider._model = fake_model

        self.assertEqual(embed_query(provider, "  当前输入\n上下文 "), [1.0, 0.0])
        self.assertEqual(provider.embed("  记忆片段 "), [1.0, 0.0])
        self.assertEqual(embed_query(provider, "当前输入 上下文"), [1.0, 0.0])
        self.assertEqual(fake_model.encode.call_count, 2)
        self.assertEqual(fake_model.encode.call_args_list[0].args[0], "查询：当前输入 上下文")
        self.assertEqual(fake_model.encode.call_args_list[1].args[0], "结果：记忆片段")

    def test_env_config_builds_local_bge_provider_with_safe_offline_default(self) -> None:
        provider = embedding_provider_from_env(
            {
                "RAG_IME_EMBEDDING_PROVIDER": "local-bge",
                "RAG_IME_EMBEDDING_MODEL": "BAAI/bge-base-zh-v1.5",
                "RAG_IME_EMBEDDING_CACHE_DIR": "/tmp/bge-cache",
            }
        )

        self.assertIsInstance(provider, SentenceTransformerEmbeddingProvider)
        assert isinstance(provider, SentenceTransformerEmbeddingProvider)
        self.assertTrue(provider.local_files_only)
        self.assertEqual(provider.cache_dir, "/tmp/bge-cache")
        self.assertTrue(provider.query_prefix)

    def test_env_config_builds_mlx_bge_q8_provider(self) -> None:
        provider = embedding_provider_from_env(
            {
                "RAG_IME_EMBEDDING_PROVIDER": "local-bge-mlx",
                "RAG_IME_EMBEDDING_MODEL": "/tmp/bge-mlx-q8",
                "RAG_IME_EMBEDDING_BITS": "8",
                "RAG_IME_EMBEDDING_GROUP_SIZE": "32",
            }
        )

        self.assertIsInstance(provider, MlxBertEmbeddingProvider)
        assert isinstance(provider, MlxBertEmbeddingProvider)
        self.assertEqual(provider.bits, 8)
        self.assertEqual(provider.group_size, 32)
        self.assertEqual(provider.model, "/tmp/bge-mlx-q8")
        self.assertTrue(provider.query_prefix)

    def test_mlx_provider_deduplicates_and_bounds_uncached_batches(self) -> None:
        provider = MlxBertEmbeddingProvider(
            model="/tmp/fake-mlx-bert",
            document_prefix="document: ",
            cache_size=4,
        )
        calls: list[tuple[list[str], str]] = []

        def encode_batch(texts: list[str], *, prefix: str) -> list[list[float]]:
            calls.append((list(texts), prefix))
            return [
                [float(index + 1), 1.0]
                for index, _text in enumerate(texts)
            ]

        provider._encode_uncached_batch = encode_batch  # type: ignore[method-assign]
        inputs = [f"item-{index}" for index in range(10)] + ["item-0", ""]

        first = provider.embed_many(inputs, batch_size=32)
        second = provider.embed("item-9")

        self.assertEqual([8, 2], [len(items) for items, _prefix in calls])
        self.assertTrue(all(prefix == "document: " for _items, prefix in calls))
        self.assertEqual(first[0], first[10])
        self.assertEqual([], first[11])
        self.assertEqual(first[9], second)
        self.assertEqual(2, len(calls))

    def test_openai_provider_caches_by_fingerprint_and_normalized_text(self) -> None:
        server, thread = self._start_server([[1.0, 0.0, 0.0]])
        try:
            provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                )
            )
            first = provider.embed("  RAG 输入法\n本地记忆  ")
            second = provider.embed("RAG 输入法 本地记忆")

            self.assertEqual(_MockEmbeddingHandler.call_count, 1)
            self.assertEqual(first, [1.0, 0.0, 0.0])
            self.assertEqual(second, first)
            self.assertEqual(_MockEmbeddingHandler.captured_payloads[0]["input"], "RAG 输入法 本地记忆")

            changed_provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                    extra_body={"task": "query"},
                )
            )
            self.assertNotEqual(provider.fingerprint, changed_provider.fingerprint)
            changed_provider.embed("RAG 输入法 本地记忆")

            self.assertEqual(_MockEmbeddingHandler.call_count, 2)
            self.assertEqual(_MockEmbeddingHandler.captured_payloads[1]["task"], "query")

            other_endpoint_provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port + 1}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                )
            )
            self.assertNotEqual(provider.fingerprint, other_endpoint_provider.fingerprint)
        finally:
            self._stop_server(server, thread)

    def test_openai_provider_does_not_cache_empty_vectors(self) -> None:
        server, thread = self._start_server([[], [0.0, 1.0, 0.0]])
        try:
            provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                )
            )

            self.assertEqual(provider.embed("same text"), [])
            self.assertEqual(_MockEmbeddingHandler.call_count, 1)
            self.assertEqual(provider.embed("same text"), [0.0, 1.0, 0.0])
            self.assertEqual(_MockEmbeddingHandler.call_count, 2)
            self.assertEqual(provider.embed("same text"), [0.0, 1.0, 0.0])
            self.assertEqual(_MockEmbeddingHandler.call_count, 2)
        finally:
            self._stop_server(server, thread)

    def test_openai_provider_batches_index_backfill_and_preserves_order(self) -> None:
        server, thread = self._start_server([[1.0, 0.0], [0.0, 1.0]])
        try:
            provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                )
            )

            vectors = provider.embed_many(["第一条", "第二条", "第一条"])

            self.assertEqual(_MockEmbeddingHandler.call_count, 1)
            self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
            self.assertEqual(_MockEmbeddingHandler.captured_payloads[0]["input"], ["第一条", "第二条"])
        finally:
            self._stop_server(server, thread)

    def test_openai_provider_cache_is_bounded(self) -> None:
        server, thread = self._start_server([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        try:
            provider = OpenAICompatibleEmbeddingProvider(
                OpenAICompatibleEmbeddingConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="bge-small-zh",
                    timeout_s=1.0,
                    cache_size=1,
                )
            )

            provider.embed("first")
            provider.embed("second")
            provider.embed("first")

            self.assertEqual(_MockEmbeddingHandler.call_count, 3)
        finally:
            self._stop_server(server, thread)

    def test_env_config_can_override_embedding_cache_size(self) -> None:
        provider = embedding_provider_from_env(
            {
                "RAG_IME_EMBEDDING_PROVIDER": "openai-compatible",
                "RAG_IME_EMBEDDING_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_EMBEDDING_MODEL": "bge-small-zh",
                "RAG_IME_EMBEDDING_CACHE_SIZE": "17",
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleEmbeddingProvider)
        assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
        self.assertEqual(provider.config.cache_size, 17)

    def _start_server(
        self,
        embeddings: list[list[float]],
    ) -> tuple[ThreadingHTTPServer, threading.Thread]:
        _MockEmbeddingHandler.call_count = 0
        _MockEmbeddingHandler.captured_payloads = []
        _MockEmbeddingHandler.embeddings = embeddings
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockEmbeddingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def _stop_server(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


if __name__ == "__main__":
    unittest.main()
