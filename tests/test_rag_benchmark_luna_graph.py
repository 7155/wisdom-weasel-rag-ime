from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.activity_timeline_evaluation import LunaStructuredRun
from rag_ime.knowledge_library.graph_extractors import GraphExtractionInput
from rag_ime.rag_benchmark_luna_graph import (
    LUNA_GRAPH_MODEL,
    LUNA_GRAPH_THINKING,
    LunaKnowledgeGraphExtractor,
)


class LunaKnowledgeGraphExtractorTests(unittest.TestCase):
    def test_structured_luna_output_is_normalized_against_exact_chunk_evidence(self) -> None:
        calls: list[dict[str, object]] = []

        def run(**kwargs):
            calls.append(dict(kwargs))
            return LunaStructuredRun(
                phase="knowledge-graph-extraction",
                model=LUNA_GRAPH_MODEL,
                thinking=LUNA_GRAPH_THINKING,
                command=("codex",),
                elapsed_seconds=0.25,
                exit_code=0,
                prompt_sha256="prompt",
                schema_sha256="schema",
                output_sha256="output",
                stdout_sha256="stdout",
                stderr_sha256="stderr",
                output={
                    "schemaVersion": "rag-ime.rag-benchmark-luna-graph.v1",
                    "chunks": [
                        {
                            "chunkId": "chunk-1",
                            "topics": ["北斗项目"],
                            "entities": [
                                {"name": "北斗项目", "type": "项目", "evidence": "北斗项目"},
                                {"name": "林岚", "type": "人员", "evidence": "林岚"},
                                {"name": "张三", "type": "人员", "evidence": "张三"},
                            ],
                            "relations": [
                                {
                                    "source": "林岚",
                                    "target": "北斗项目",
                                    "type": "审批",
                                    "evidence": "北斗项目的差旅审批人是林岚",
                                    "confidence": 0.95,
                                }
                            ],
                        }
                    ],
                },
            )

        with tempfile.TemporaryDirectory() as temporary:
            extractor = LunaKnowledgeGraphExtractor(
                Path(temporary) / "artifacts",
                codex_bin=sys.executable,
                structured_runner=run,
            )
            result = extractor.extract(
                [
                    GraphExtractionInput(
                        chunk_id="chunk-1",
                        document_id="doc-1",
                        content_hash="hash-1",
                        heading="差旅制度",
                        content="北斗项目的差旅审批人是林岚，报销期限为三十天。",
                    )
                ]
            )["chunk-1"]

        self.assertEqual(1, len(calls))
        self.assertEqual(["北斗项目", "林岚"], [item.name for item in result.entities])
        self.assertEqual(1, len(result.relations))
        self.assertEqual("审批", result.relations[0].relation_type)
        self.assertNotIn("张三", [item.name for item in result.entities])


if __name__ == "__main__":
    unittest.main()
