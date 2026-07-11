from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NotionWorkerContractTests(unittest.TestCase):
    def test_worker_uses_signed_idempotent_async_queue_contract(self) -> None:
        source = (ROOT / "integrations" / "notion-worker" / "src" / "index.ts").read_text(encoding="utf-8")

        self.assertIn('worker.webhook("enqueueKnowledgeQuery"', source)
        self.assertIn('headers["x-rag-ime-signature"]', source)
        self.assertIn("crypto.timingSafeEqual", source)
        self.assertIn("notion.dataSources.query", source)
        self.assertIn('property: "query_id", title: { equals: query.queryId }', source)
        self.assertIn("notion.pages.create", source)
        for field in (
            "query_id",
            "question",
            "context",
            "context_hash",
            "generation",
            "project",
            "mode",
            "status",
            "answer",
            "sources",
            "created_at",
        ):
            self.assertIn(f"{field}:", source)
        self.assertNotIn("worker.webhook(\"getKnowledgeQuery", source)

    def test_agent_instructions_preserve_stale_result_keys(self) -> None:
        instructions = (ROOT / "integrations" / "notion-worker" / "custom-agent-instructions.md").read_text(
            encoding="utf-8"
        )
        docs = (ROOT / "docs" / "notion-personal-knowledge.md").read_text(encoding="utf-8")

        self.assertIn("不得修改 `query_id`、`context_hash` 或 `generation`", instructions)
        self.assertIn("HTTP 202", docs)
        self.assertIn("submitConfigured", docs)
        self.assertIn("pollConfigured", docs)
        self.assertIn("stale_dropped", docs)


if __name__ == "__main__":
    unittest.main()
