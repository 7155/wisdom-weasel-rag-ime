from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.notion_knowledge import (
    NotionAsyncKnowledgeClient,
    NotionKnowledgeConfig,
    NotionStaleResultError,
    load_notion_knowledge_config,
)


class _Response:
    def __init__(self, payload: object = None, *, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if self.payload is None:
            return b""
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class NotionKnowledgeTests(unittest.TestCase):
    def test_config_reads_env_file_without_exposing_secrets_in_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notion.env"
            path.write_text(
                "\n".join(
                    [
                        "RAG_IME_NOTION_WORKER_URL=https://www.notion.so/webhooks/worker/example",
                        "RAG_IME_NOTION_STATUS_URL=https://relay.example/queries/{query_id}",
                        "RAG_IME_NOTION_STATUS_TOKEN=secret-status",
                        "RAG_IME_NOTION_WEBHOOK_SECRET=secret-webhook",
                    ]
                ),
                encoding="utf-8",
            )
            config = load_notion_knowledge_config(path, env={})

        status = NotionAsyncKnowledgeClient(config, urlopen=lambda *_args, **_kwargs: None).route_status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["pollMode"], "status_relay")
        self.assertTrue(status["requestSigning"])
        self.assertNotIn("secret-status", json.dumps(status))
        self.assertNotIn("secret-webhook", json.dumps(status))

    def test_worker_submit_uses_local_query_id_and_hmac_signature(self) -> None:
        captured = {}
        secret = "shared-secret"

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(status=202)

        client = NotionAsyncKnowledgeClient(
            NotionKnowledgeConfig(
                worker_url="https://www.notion.so/webhooks/worker/example",
                status_url="https://relay.example/query/{query_id}",
                request_secret=secret,
            ),
            urlopen=fake_urlopen,
        )
        result = client.submit(
            query_id="q-123",
            question="回忆 RAG 设计",
            context="当前项目",
            context_hash="sha256:ctx",
            generation=7,
            project="wisdom-weasel-rag-ime",
            mode="recall",
        )

        request = captured["request"]
        body = request.data
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["httpStatus"], 202)
        self.assertEqual(payload["queryId"], "q-123")
        self.assertEqual(payload["generation"], 7)
        self.assertEqual(request.get_header("X-rag-ime-signature"), f"sha256={expected}")

    def test_status_relay_result_must_match_query_context_and_generation(self) -> None:
        responses = [
            _Response({"queryId": "q-123", "status": "running", "contextHash": "sha256:ctx", "generation": 4}),
            _Response(
                {
                    "queryId": "q-123",
                    "status": "done",
                    "answer": "Notion 中的答案",
                    "sources": [{"title": "项目笔记"}],
                    "contextHash": "sha256:ctx",
                    "generation": 4,
                }
            ),
        ]
        client = NotionAsyncKnowledgeClient(
            NotionKnowledgeConfig(status_url="https://relay.example/query/{query_id}", poll_interval_ms=1),
            urlopen=lambda *_args, **_kwargs: responses.pop(0),
            sleep=lambda _seconds: None,
        )

        result = client.poll(query_id="q-123", context_hash="sha256:ctx", generation=4, timeout_ms=500)

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["answer"], "Notion 中的答案")
        self.assertEqual(result["sources"][0]["title"], "项目笔记")

    def test_stale_status_relay_result_is_rejected(self) -> None:
        client = NotionAsyncKnowledgeClient(
            NotionKnowledgeConfig(status_url="https://relay.example/query/{query_id}"),
            urlopen=lambda *_args, **_kwargs: _Response(
                {
                    "queryId": "q-old",
                    "status": "done",
                    "answer": "迟到答案",
                    "contextHash": "sha256:old",
                    "generation": 1,
                }
            ),
            sleep=lambda _seconds: None,
        )

        with self.assertRaises(NotionStaleResultError):
            client.poll(query_id="q-new", context_hash="sha256:new", generation=2, timeout_ms=200)

    def test_direct_notion_api_poll_reads_rag_queries_properties(self) -> None:
        captured = {}
        page = {
            "properties": {
                "query_id": {"title": [{"plain_text": "q-123"}]},
                "status": {"select": {"name": "done"}},
                "answer": {"rich_text": [{"plain_text": "已整理的答案"}]},
                "sources": {"rich_text": [{"plain_text": '[{"title":"Notion 笔记"}]'}]},
                "context_hash": {"rich_text": [{"plain_text": "sha256:ctx"}]},
                "generation": {"number": 9},
                "completed_at": {"date": {"start": "2026-07-10T12:00:00Z"}},
            }
        }

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return _Response({"results": [page]})

        client = NotionAsyncKnowledgeClient(
            NotionKnowledgeConfig(api_token="notion-secret", data_source_id="data-source-id"),
            urlopen=fake_urlopen,
        )
        result = client.status(query_id="q-123")

        request = captured["request"]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.method, "POST")
        self.assertIn("/v1/data_sources/data-source-id/query", request.full_url)
        self.assertEqual(request.get_header("Notion-version"), "2026-03-11")
        self.assertEqual(body["filter"]["title"]["equals"], "q-123")
        self.assertEqual(result["answer"], "已整理的答案")
        self.assertEqual(result["generation"], 9)


if __name__ == "__main__":
    unittest.main()
