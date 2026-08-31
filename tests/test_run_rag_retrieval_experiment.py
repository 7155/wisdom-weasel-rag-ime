from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_rag_retrieval_experiment import (
    DEFAULT_CANDIDATES,
    RERANK_BASE_CANDIDATES,
    _reranker_acceptance_passes,
)


ROOT = Path(__file__).resolve().parents[1]


class RunRagRetrievalExperimentTests(unittest.TestCase):
    def test_reranker_matrix_includes_the_current_equal_weight_hybrid_winner(self) -> None:
        current_winner = DEFAULT_CANDIDATES[2]

        self.assertIn(current_winner, RERANK_BASE_CANDIDATES)

    def test_reranker_gate_accepts_used_fingerprint_bound_persistent_cache(self) -> None:
        cached = {
            "configured": True,
            "calls": 3,
            "scoredPairs": 0,
            "cacheHits": 120,
            "persistentCacheLoadedEntries": 40,
            "scoreCacheEntries": 40,
            "errorCount": 0,
            "fallbackCount": 0,
        }
        self.assertTrue(_reranker_acceptance_passes(cached))
        self.assertFalse(
            _reranker_acceptance_passes(
                {**cached, "cacheHits": 0}
            )
        )
        self.assertFalse(
            _reranker_acceptance_passes(
                {**cached, "persistentCacheLoadedEntries": 0}
            )
        )

    def test_cli_runs_product_index_and_writes_local_numeric_receipt(self) -> None:
        documents = [
            {
                "documentId": f"doc-{index}",
                "title": f"Document {index}",
                "text": f"unique evidence term-{index} answer-{index}",
                "source": "fixture",
            }
            for index in range(20)
        ]
        cases = []
        splits: dict[str, list[str]] = {
            "train": [],
            "validation": [],
            "held_out": [],
        }
        for index in range(15):
            split = ("train", "validation", "held_out")[index // 5]
            query_id = f"q-{index}"
            splits[split].append(query_id)
            cases.append(
                {
                    "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                    "system": "knowledge",
                    "queryId": query_id,
                    "query": f"term-{index} answer-{index}",
                    "split": split,
                    "slice": "basic" if index % 2 == 0 else "semantic",
                    "relevant": {f"doc-{index}": 1.0},
                    "retrievalEvaluable": True,
                }
            )
        source_sha256 = hashlib.sha256(b"fixture").hexdigest()
        prepared = {
            "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
            "manifest": {
                "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
                "benchmarkId": "cli-retrieval-fixture",
                "system": "knowledge",
                "tool": "knowledge",
                "sourceUrl": "https://example.org/retrieval-fixture",
                "version": "v1",
                "sourceSha256": source_sha256,
                "licenseReference": "https://example.org/license",
                "corpusIncluded": False,
                "splits": splits,
            },
            "adapter": {"name": "fixture"},
            "documents": documents,
            "cases": cases,
        }

        with tempfile.TemporaryDirectory(prefix="rag-ime-retrieval-cli-") as temporary:
            root = Path(temporary)
            source = root / "prepared.json"
            output = root / "output" / "report.json"
            sandbox = root / "sandbox"
            source.write_text(json.dumps(prepared), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_rag_retrieval_experiment.py"),
                    "--prepared",
                    str(source),
                    "--sandbox-root",
                    str(sandbox),
                    "--output",
                    str(output),
                    "--embedding-provider",
                    "local-hash",
                    "--embedding-dimensions",
                    "96",
                    "--dense-backend",
                    "sqlite-exact",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            remaining_runs = list(sandbox.glob("run-*"))
            validation_output = root / "output" / "validation-only.json"
            validation_completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_rag_retrieval_experiment.py"),
                    "--prepared",
                    str(source),
                    "--sandbox-root",
                    str(root / "validation-sandbox"),
                    "--output",
                    str(validation_output),
                    "--evaluation-scope",
                    "validation-only",
                    "--distractor-limit",
                    "3",
                    "--chunk-strategy",
                    "markdown",
                    "--chunk-size",
                    "600",
                    "--chunk-overlap",
                    "80",
                    "--embedding-provider",
                    "local-hash",
                    "--embedding-dimensions",
                    "96",
                    "--dense-backend",
                    "sqlite-exact",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                0,
                validation_completed.returncode,
                validation_completed.stderr + validation_completed.stdout,
            )
            validation_report = json.loads(
                validation_output.read_text(encoding="utf-8")
            )

        self.assertEqual("completed", report["status"])
        self.assertTrue(report["localOnly"])
        self.assertFalse(report["uploaded"])
        self.assertEqual(20, report["corpus"]["documentCount"])
        self.assertEqual(5, report["validationSelection"]["validationQueryCount"])
        self.assertFalse(report["validationSelection"]["heldOutLabelsObserved"])
        self.assertEqual(
            5,
            report["heldOut"]["productionLexicalFloor"]["metrics"]["queryCount"],
        )
        self.assertEqual(
            5,
            report["heldOut"]["strongNaiveDenseBaseline"]["metrics"]["queryCount"],
        )
        self.assertIn(
            "absoluteDelta",
            report["comparison"]["productionLexicalFloorToTuned"]["mrr"],
        )
        self.assertIn(
            "absoluteDelta",
            report["comparison"]["strongNaiveDenseToTuned"]["mrr"],
        )
        self.assertEqual(64, len(report["reportSha256"]))
        self.assertIn(
            "absoluteDelta",
            report["validationComparison"]["strongNaiveDenseToWinner"]["mrr"],
        )
        self.assertEqual([], remaining_runs)
        self.assertEqual("validation-only", validation_report["evaluationScope"])
        self.assertIsNone(validation_report["heldOut"])
        self.assertIsNone(validation_report["comparison"])
        self.assertTrue(
            validation_report["hardGates"][
                "heldOutMetricsSuppressedDuringChunkSelection"
            ]
        )
        self.assertEqual("markdown", validation_report["chunking"]["strategy"])
        self.assertEqual(600, validation_report["chunking"]["size"])
        self.assertEqual(80, validation_report["chunking"]["overlap"])
        self.assertEqual(18, validation_report["corpus"]["documentCount"])
        self.assertEqual(
            "selected-split-qrels-plus-deterministic-distractors",
            validation_report["corpus"]["selection"]["method"],
        )
        self.assertTrue(
            validation_report["hardGates"]["corpusFrozenBeforeCandidateEvaluation"]
        )
        self.assertTrue(validation_report["hardGates"]["qrelsNotPassedToRetriever"])
        self.assertTrue(
            validation_report["hardGates"]["memoryMutationNotPerformed"]
        )

    def test_cli_rejects_semantic_run_when_no_dense_vectors_were_built(self) -> None:
        documents = [
            {
                "documentId": f"doc-{index}",
                "title": f"Document {index}",
                "text": f"exact evidence term-{index}",
                "source": "fixture",
            }
            for index in range(3)
        ]
        splits = {
            "train": ["q-0"],
            "validation": ["q-1"],
            "held_out": ["q-2"],
        }
        prepared = {
            "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
            "manifest": {
                "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
                "benchmarkId": "missing-dense-runtime-fixture",
                "system": "knowledge",
                "tool": "knowledge",
                "sourceUrl": "https://example.org/missing-dense-runtime",
                "version": "v1",
                "sourceSha256": hashlib.sha256(b"missing-dense").hexdigest(),
                "licenseReference": "https://example.org/license",
                "corpusIncluded": False,
                "splits": splits,
            },
            "adapter": {"name": "fixture"},
            "documents": documents,
            "cases": [
                {
                    "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                    "system": "knowledge",
                    "queryId": f"q-{index}",
                    "query": f"term-{index}",
                    "split": ("train", "validation", "held_out")[index],
                    "slice": "basic",
                    "relevant": {f"doc-{index}": 1.0},
                    "retrievalEvaluable": True,
                }
                for index in range(3)
            ],
        }

        with tempfile.TemporaryDirectory(prefix="rag-ime-missing-dense-") as temporary:
            root = Path(temporary)
            source = root / "prepared.json"
            output = root / "report.json"
            source.write_text(json.dumps(prepared), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_rag_retrieval_experiment.py"),
                    "--prepared",
                    str(source),
                    "--sandbox-root",
                    str(root / "sandbox"),
                    "--output",
                    str(output),
                    "--embedding-provider",
                    "mlx-bert",
                    "--embedding-model",
                    str(root / "missing-model"),
                    "--dense-backend",
                    "sqlite-exact",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertNotEqual(0, completed.returncode, completed.stdout)
        self.assertIn("semantic dense runtime is not ready", completed.stderr)


if __name__ == "__main__":
    unittest.main()
