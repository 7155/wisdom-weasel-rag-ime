from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag_ime.embeddings import (
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
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
        index = min(type(self).call_count - 1, len(type(self).embeddings) - 1)
        body = json.dumps(
            {
                "data": [
                    {
                        "embedding": type(self).embeddings[index],
                    }
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
