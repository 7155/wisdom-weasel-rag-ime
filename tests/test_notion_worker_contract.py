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
        worker_readme = (ROOT / "integrations" / "notion-worker" / "README.md").read_text(encoding="utf-8")
        route_source = (ROOT / "rag_ime" / "notion_knowledge.py").read_text(encoding="utf-8")
        workbench_source = (ROOT / "rag_ime" / "knowledge_workbench.py").read_text(encoding="utf-8")

        self.assertIn("不得修改 `query_id`、`context_hash` 或 `generation`", instructions)
        self.assertIn("HTTP 202", worker_readme)
        self.assertIn('"submitConfigured"', route_source)
        self.assertIn('"pollConfigured"', route_source)
        self.assertIn('"stale_dropped"', workbench_source)


if __name__ == "__main__":
    unittest.main()
