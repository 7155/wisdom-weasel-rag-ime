from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.authorized_blog_corpus import SCHEMA_VERSION as BLOG_CORPUS_SCHEMA_VERSION
from rag_ime.minimind_experiment import prepare_minimind_experiment


ROOT = Path(__file__).resolve().parents[1]


class MiniMindExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="minimind-experiment-")
        self.root = Path(self.tmp.name)
        self.causal_manifest = self.root / "causal-manifest.json"
        self.causal_manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": BLOG_CORPUS_SCHEMA_VERSION,
                    "corpusFingerprint": "sha256:causal",
                    "trainingContract": {"rowShape": {"text": "string"}, "chatFieldsAllowed": False},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_demo_plan_keeps_causal_sft_and_ranking_as_separate_phases(self) -> None:
        report = prepare_minimind_experiment(
            causal_manifest_path=self.causal_manifest,
            completion_dataset_root=ROOT / "dataset" / "minimind_completion_v3_public",
            output_root=self.root / "out",
            base_checkpoint="minimind-ime-v2-q8",
            base_checkpoint_fingerprint="sha256:" + "1" * 64,
            tokenizer_fingerprint="sha256:" + "2" * 64,
            purpose="demo",
        )

        self.assertTrue(report["ok"])
        self.assertFalse(report["promotionEligible"])
        self.assertFalse(report["trainingExecuted"])
        self.assertEqual(
            [phase["id"] for phase in report["phases"]],
            ["a0-causal-adaptation", "a0-suffix-sft", "a1-ranking-ab"],
        )
        self.assertEqual(report["phases"][0]["input"], "inputs.causalCorpus")
        self.assertTrue(report["phases"][1]["prefixLossMasked"])
        self.assertEqual(report["exportPairCounts"]["sft"], {"train": 24, "val": 15, "test": 18})

    def test_public_regression_seed_cannot_prepare_production_plan(self) -> None:
        with self.assertRaisesRegex(ValueError, "productionTrainingReady"):
            prepare_minimind_experiment(
                causal_manifest_path=self.causal_manifest,
                completion_dataset_root=ROOT / "dataset" / "minimind_completion_v3_public",
                output_root=self.root / "out",
                base_checkpoint="minimind-ime-v2-q8",
                base_checkpoint_fingerprint="sha256:" + "1" * 64,
                tokenizer_fingerprint="sha256:" + "2" * 64,
                purpose="production",
            )

    def test_rejects_chat_shaped_causal_manifest(self) -> None:
        payload = json.loads(self.causal_manifest.read_text(encoding="utf-8"))
        payload["trainingContract"]["rowShape"] = {"messages": "array"}
        self.causal_manifest.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "text-only"):
            prepare_minimind_experiment(
                causal_manifest_path=self.causal_manifest,
                completion_dataset_root=ROOT / "dataset" / "minimind_completion_v3_public",
                output_root=self.root / "out",
                base_checkpoint="minimind-ime-v2-q8",
                base_checkpoint_fingerprint="sha256:" + "1" * 64,
                tokenizer_fingerprint="sha256:" + "2" * 64,
            )
