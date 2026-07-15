from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.knowledge_library import KnowledgeConflictError, KnowledgeLibraryConfig, KnowledgeLibraryService


class KnowledgeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-graph-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = KnowledgeLibraryService(
            KnowledgeLibraryConfig(self.root / "Knowledge", chunk_chars=200, chunk_overlap_chars=20)
        )
        self.addCleanup(self.service.close)
        self.base = self.service.create_base("Research graph")
        source = self.root / "retrieval.md"
        source.write_text(
            "# Retrieval Architecture\n\n"
            "RAG connects the Agent Runtime with a Vector Store and SQLite.\n\n"
            "## Evidence Pipeline\n\n"
            "The Agent Runtime cites source chunks. `MinerU` extracts PDF tables.\n\n"
            + "Vector Store evidence remains traceable to SQLite chunks. " * 8,
            encoding="utf-8",
        )
        self.document = self.service.import_document(self.base["id"], source)

    def test_rebuild_uses_real_document_chunks_and_keeps_graph_isolated(self) -> None:
        rebuilt = self.service.rebuild_knowledge_graph(
            self.base["id"], expected_revision=0
        )
        self.assertTrue(rebuilt["ok"])
        self.assertEqual("ready", rebuilt["status"])

        graph = self.service.knowledge_graph(
            self.base["id"], limit=200, depth=5, exclude_chunks=False
        )
        validate_contract(graph, "knowledge-graph.v1.json")
        self.assertEqual("ready", graph["status"])
        self.assertEqual(1, graph["stats"]["documentCount"])
        self.assertEqual(self.document["chunkCount"], graph["stats"]["chunkCount"])
        kinds = {node["kind"] for node in graph["nodes"]}
        self.assertTrue({"document", "chunk", "topic", "entity", "term"}.issubset(kinds))
        self.assertTrue(any(edge["kind"] == "contains" for edge in graph["edges"]))
        self.assertTrue(any(edge["kind"] == "mentions" for edge in graph["edges"]))
        self.assertTrue(any(edge["kind"] == "next" for edge in graph["edges"]))
        for node in graph["nodes"]:
            if node["kind"] in {"entity", "term"}:
                self.assertIn(self.document["documentId"], node["documentIds"])
            else:
                self.assertEqual(self.document["documentId"], node.get("documentId"))
                self.assertEqual("retrieval.md", node.get("documentName"))

        table_names = {
            str(row["name"])
            for row in self.service.store.all("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("knowledge_graph_nodes", table_names)
        self.assertFalse(any(name.startswith("memory_") for name in table_names))

    def test_query_focus_bfs_filters_and_revision_conflict(self) -> None:
        self.service.rebuild_knowledge_graph(self.base["id"], expected_revision=0)
        queried = self.service.knowledge_graph(
            self.base["id"], query="SQLite", limit=10, depth=2
        )
        self.assertTrue(any("SQLite" in node["label"] for node in queried["nodes"]))
        focus = next(node["id"] for node in queried["nodes"] if "SQLite" in node["label"])
        neighborhood = self.service.knowledge_graph(
            self.base["id"], focus_id=focus, limit=10, depth=1, exclude_chunks=True
        )
        self.assertTrue(any(node["id"] == focus for node in neighborhood["nodes"]))
        self.assertFalse(any(node["kind"] == "chunk" for node in neighborhood["nodes"]))
        self.assertLessEqual(len(neighborhood["nodes"]), 10)

        terms = self.service.knowledge_graph(
            self.base["id"], kinds=("term",), limit=10, depth=2
        )
        self.assertTrue(terms["nodes"])
        self.assertEqual({"term"}, {node["kind"] for node in terms["nodes"]})
        with self.assertRaises(KnowledgeConflictError):
            self.service.rebuild_knowledge_graph(self.base["id"], expected_revision=0)

    def test_graph_becomes_stale_when_document_revision_changes(self) -> None:
        self.service.store.update_document(self.document["documentId"], {"status": "stale"})
        rebuilt = self.service.rebuild_knowledge_graph(self.base["id"], expected_revision=0)
        self.assertEqual("stale", rebuilt["status"])
        stale_graph = self.service.knowledge_graph(self.base["id"])
        self.assertEqual("stale", stale_graph["status"])
        self.assertEqual(1, stale_graph["stats"]["pendingDocumentCount"])
        self.assertTrue(stale_graph["nodes"])

        self.service.retry_document(self.document["documentId"], parser_mode="builtin")
        self.assertEqual("stale", self.service.knowledge_graph(self.base["id"])["status"])

    def test_shared_entities_merge_across_documents_and_partial_rebuild_preserves_others(self) -> None:
        second_source = self.root / "second.md"
        second_source.write_text("# Second\n\nRAG and SQLite support another Agent Runtime.", encoding="utf-8")
        second = self.service.import_document(self.base["id"], second_source)
        self.service.rebuild_knowledge_graph(self.base["id"], expected_revision=0)

        graph = self.service.knowledge_graph(
            self.base["id"], query="RAG", depth=2, limit=30
        )
        rag_nodes = [node for node in graph["nodes"] if node["label"] == "RAG"]
        self.assertEqual(1, len(rag_nodes))
        self.assertEqual(
            {self.document["documentId"], second["documentId"]},
            set(rag_nodes[0]["documentIds"]),
        )

        partial = self.service.rebuild_knowledge_graph(
            self.base["id"],
            expected_revision=1,
            document_ids=(self.document["documentId"],),
        )
        self.assertEqual(2, partial["revision"])
        self.assertEqual(2, self.service.knowledge_graph(self.base["id"])["stats"]["documentCount"])


if __name__ == "__main__":
    unittest.main()
