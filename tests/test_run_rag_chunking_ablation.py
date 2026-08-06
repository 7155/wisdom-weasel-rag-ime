from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RunRagChunkingAblationTests(unittest.TestCase):
    def test_cli_selects_chunks_without_candidate_heldout_metrics(self) -> None:
        documents = [
            {
                "documentId": f"doc-{index}",
                "title": f"Document {index}",
                "text": (f"# Topic {index}\n\nunique chunk evidence-{index} " * 40),
                "source": "fixture",
            }
            for index in range(12)
        ]
        splits = {"train": [], "validation": [], "held_out": []}
        cases = []
        for index in range(9):
            split = ("train", "validation", "held_out")[index // 3]
            query_id = f"q-{index}"
            splits[split].append(query_id)
            cases.append(
                {
                    "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                    "system": "knowledge",
                    "queryId": query_id,
                    "query": f"evidence-{index}",
                    "split": split,
                    "slice": "basic",
                    "relevant": {f"doc-{index}": 1.0},
                    "retrievalEvaluable": True,
                }
            )
        prepared = {
            "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
            "manifest": {
                "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
                "benchmarkId": "chunk-ablation-fixture",
                "system": "knowledge",
                "tool": "knowledge",
                "sourceUrl": "https://example.org/chunk-ablation",
                "version": "v1",
                "sourceSha256": hashlib.sha256(b"chunk-ablation").hexdigest(),
                "licenseReference": "https://example.org/license",
                "corpusIncluded": False,
                "splits": splits,
            },
            "adapter": {"name": "fixture"},
            "documents": documents,
            "cases": cases,
        }
        profiles = [
            {
                "id": "general-1200-160",
                "strategy": "general",
                "size": 1_200,
                "overlap": 160,
            },
            {
                "id": "markdown-600-80",
                "strategy": "markdown",
                "size": 600,
                "overlap": 80,
            },
        ]

        with tempfile.TemporaryDirectory(prefix="rag-ime-chunk-ablation-") as temporary:
            root = Path(temporary)
            prepared_path = root / "prepared.json"
            profiles_path = root / "profiles.json"
            output = root / "result.json"
            prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
            profiles_path.write_text(json.dumps(profiles), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_rag_chunking_ablation.py"),
                    "--prepared",
                    str(prepared_path),
                    "--profiles-json",
                    str(profiles_path),
                    "--output",
                    str(output),
                    "--work-root",
                    str(root / "work"),
                    "--max-cases-per-split",
                    "2",
                    "--distractor-limit",
                    "2",
                    "--embedding-provider",
                    "local-hash",
                    "--embedding-dimensions",
                    "64",
                    "--dense-backend",
                    "sqlite-exact",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            candidate_reports = [
                json.loads(Path(row["report"]).read_text(encoding="utf-8"))
                for row in report["candidates"]
            ]

        self.assertTrue(report["passed"])
        self.assertEqual(2, len(report["candidates"]))
        self.assertTrue(report["hardGates"]["heldOutSuppressedForEveryCandidate"])
        self.assertTrue(report["hardGates"]["heldOutRunUsesFrozenWinnerProfile"])
        self.assertTrue(report["hardGates"]["heldOutRunReproducesFrozenRetrievalConfig"])
        self.assertTrue(all(item["heldOut"] is None for item in candidate_reports))
        self.assertEqual(
            {8},
            {item["corpus"]["documentCount"] for item in candidate_reports},
        )
        self.assertEqual(2, report["selectionBudget"]["maxCasesPerSplit"])
        self.assertEqual(2, report["selectionBudget"]["distractorLimit"])
        self.assertIn("ndcgAt10", report["heldOutAcceptance"]["metrics"])
        self.assertEqual(64, len(report["reportSha256"]))


if __name__ == "__main__":
    unittest.main()
