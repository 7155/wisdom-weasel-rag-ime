from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.knowledge_library import KnowledgeConflictError, KnowledgeLibraryConfig, KnowledgeLibraryService
from rag_ime.knowledge_library.graph_extractors import (
    ExtractedEntity,
    ExtractedRelation,
    GraphExtraction,
    OpenAICompatibleGraphExtractor,
)
from rag_ime.deepseek_config import DeepSeekConfig


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        import json

        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.data


class _StubModelExtractor:
    mode = "model"
    fingerprint = "model:test-v1"
    configured = True

    def __init__(self, gate: threading.Event | None = None) -> None:
        self.calls = 0
        self.gate = gate
        self.config = type("Config", (), {"model": "resolved-test-model"})()

    def extract(self, inputs):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=3)
        result = {}
        for item in inputs:
            entities = []
            relations = []
            if "SQLite" in item.content and "Agent Runtime" in item.content:
                entities = [
                    ExtractedEntity("Agent Runtime", "Software", "Agent Runtime"),
                    ExtractedEntity("SQLite", "Database", "SQLite"),
                ]
                relations = [
                    ExtractedRelation("Agent Runtime", "SQLite", "stores evidence in", "Agent Runtime", 0.9)
                ]
            result[item.chunk_id] = GraphExtraction(
                item.chunk_id,
                entities=tuple(entities),
                relations=tuple(relations),
            )
        return result


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
            "[RAG](https://example.invalid/rag) connects the Agent Runtime with a \"Vector Store\" and `SQLite`.\n\n"
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

    def test_ready_graph_expands_hybrid_retrieval_with_visible_evidence(self) -> None:
        self.service.rebuild_knowledge_graph(self.base["id"], expected_revision=0)

        result = self.service.search(
            "SQLite",
            base_ids=(self.base["id"],),
            mode="hybrid",
            threshold=0.0,
            limit=10,
        )

        self.assertTrue(result["hits"])
        library = result["retrieval"]["libraries"][0]
        self.assertEqual("ready", library["graphStatus"])
        self.assertGreater(library["graphCandidates"], 0)
        graph_hits = [hit for hit in result["hits"] if hit["diagnostics"].get("graphRank")]
        self.assertTrue(graph_hits)
        self.assertEqual("weighted-rrf-graph", graph_hits[0]["diagnostics"]["fusion"])
        self.assertTrue(graph_hits[0]["diagnostics"]["graphMatches"])
        self.assertTrue(graph_hits[0]["diagnostics"]["graphPaths"])

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
        second_source.write_text(
            "# Second\n\n[RAG](https://example.invalid/rag) and `SQLite` support another Agent Runtime.",
            encoding="utf-8",
        )
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

    def test_hidden_chunks_do_not_exhaust_the_visible_graph_budget(self) -> None:
        base = self.service.create_base(
            "Large graph",
            chunking_config={"strategy": "fixed", "size": 200, "overlap": 0},
        )
        source = self.root / "large.md"
        source.write_text(
            "# Large graph\n\n" + "RAG connects Agent Runtime with `VectorStore` evidence. " * 600,
            encoding="utf-8",
        )
        document = self.service.import_document(base["id"], source)
        self.assertGreater(document["chunkCount"], 10)
        self.service.rebuild_knowledge_graph(base["id"], expected_revision=0)

        graph = self.service.knowledge_graph(
            base["id"], limit=10, depth=2, exclude_chunks=True
        )

        self.assertFalse(any(node["kind"] == "chunk" for node in graph["nodes"]))
        self.assertTrue(any(node["kind"] in {"entity", "term"} for node in graph["nodes"]))
        self.assertTrue(graph["edges"])

    def test_model_extractor_enforces_evidence_schema_and_relation_quality(self) -> None:
        import json

        response_content = {
            "chunks": [
                {
                    "chunkId": "chunk-1",
                    "topics": ["Evidence storage"],
                    "entities": [
                        {"name": "Agent Runtime", "type": "Software", "evidence": "Agent Runtime"},
                        {"name": "SQLite", "type": "Database", "evidence": "SQLite"},
                        {"name": "Neo4j", "type": "Database", "evidence": "Neo4j"},
                    ],
                    "relations": [
                        {
                            "source": "Agent Runtime",
                            "target": "SQLite",
                            "type": "stores evidence in",
                            "evidence": "Agent Runtime stores evidence in SQLite",
                            "confidence": 0.92,
                        },
                        {
                            "source": "SQLite",
                            "target": "Agent Runtime",
                            "type": "maybe related",
                            "evidence": "SQLite",
                            "confidence": 0.2,
                        },
                    ],
                }
            ]
        }
        captured_bodies: list[dict[str, object]] = []

        def model_urlopen(request, **_kwargs):
            captured_bodies.append(json.loads(request.data))
            return _JsonResponse(
                {"choices": [{"message": {"content": json.dumps(response_content)}}]}
            )

        extractor = OpenAICompatibleGraphExtractor(
            DeepSeekConfig(api_key="test", model="test-model", thinking="disabled"),
            urlopen=model_urlopen,
        )
        higher_concurrency = OpenAICompatibleGraphExtractor(
            DeepSeekConfig(api_key="test", model="test-model"),
            extraction_concurrency=3,
        )
        self.assertNotEqual(extractor.fingerprint, higher_concurrency.fingerprint)
        from rag_ime.knowledge_library.graph_extractors import GraphExtractionInput

        result = extractor.extract(
            [GraphExtractionInput("chunk-1", "doc-1", "hash", "Evidence", "Agent Runtime stores evidence in SQLite.")]
        )["chunk-1"]
        self.assertEqual(["Agent Runtime", "SQLite"], [item.name for item in result.entities])
        self.assertEqual(1, len(result.relations))
        self.assertEqual("stores evidence in", result.relations[0].relation_type)
        self.assertEqual({"type": "disabled"}, captured_bodies[0]["thinking"])
        self.assertNotIn("reasoning_effort", captured_bodies[0])
        self.assertEqual(4096, captured_bodies[0]["max_tokens"])

    def test_model_graph_cache_and_async_job_are_visible_before_completion(self) -> None:
        gate = threading.Event()
        extractor = _StubModelExtractor(gate)
        self.service.graph.extractor_factory = lambda *_args, **_kwargs: extractor
        self.service._job_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-test")

        queued = self.service.rebuild_knowledge_graph(
            self.base["id"],
            expected_revision=0,
            extractor_mode="model",
            batch_size=2,
            extraction_concurrency=2,
        )
        self.assertEqual("queued", queued["status"])
        building = self.service.knowledge_graph(self.base["id"])
        self.assertEqual("building", building["status"])
        self.assertEqual(queued["jobId"], building["jobId"])
        with self.assertRaises(KnowledgeConflictError):
            self.service.rebuild_knowledge_graph(
                self.base["id"], expected_revision=0, extractor_mode="model"
            )

        concurrency_deadline = time.time() + 1
        while time.time() < concurrency_deadline and extractor.calls < 2:
            time.sleep(0.01)
        self.assertEqual(2, extractor.calls)

        gate.set()
        deadline = time.time() + 3
        while time.time() < deadline and self.service.knowledge_graph(self.base["id"])["status"] == "building":
            time.sleep(0.02)
        built = self.service.knowledge_graph(self.base["id"], query="SQLite", depth=2)
        self.assertEqual("ready", built["status"])
        self.assertEqual("resolved-test-model", built["extractor"]["model"])
        self.assertTrue(built["extractor"]["configured"])
        self.assertEqual(2, built["extractor"]["extractionConcurrency"])
        self.assertEqual(2, built["extractor"]["effectiveExtractionConcurrency"])
        self.assertTrue(any(edge["kind"] == "relation" for edge in built["edges"]))
        overview = self.service.knowledge_graph(
            self.base["id"], limit=10, depth=2, exclude_chunks=True
        )
        self.assertTrue(any(edge["kind"] == "relation" for edge in overview["edges"]))
        self.assertFalse(any(node["kind"] == "chunk" for node in overview["nodes"]))
        first_call_count = extractor.calls

        self.service.close(wait=True)
        cached = self.service.rebuild_knowledge_graph(
            self.base["id"],
            expected_revision=1,
            extractor_mode="model",
            batch_size=2,
            extraction_concurrency=2,
        )
        self.assertEqual("ready", cached["status"])
        self.assertEqual(first_call_count, extractor.calls)
        self.assertGreater(cached["extractor"]["cachedChunkCount"], 0)
        cached_graph = self.service.knowledge_graph(self.base["id"])
        self.assertTrue(cached_graph["extractor"]["configured"])


if __name__ == "__main__":
    unittest.main()
