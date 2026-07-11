from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.rime_lexicon_eval import evaluate_librime_probe, load_rime_lexicon_eval


ROOT = Path(__file__).resolve().parents[1]


class RimeLexiconEvalTests(unittest.TestCase):
    def test_public_fixture_passes_matching_probe_and_checks_equivalence(self) -> None:
        fixture = load_rime_lexicon_eval(ROOT / "dataset" / "rime_lexicon_eval.v1.json")
        output = "\n".join(
            f"{case['input']}\t{case['expectedTop1']}\t候选二"
            for case in fixture["cases"]
        )

        report = evaluate_librime_probe(fixture, output)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["top1Accuracy"], 1.0)
        self.assertEqual(report["inconsistentEquivalenceGroups"], [])
        self.assertIn("standalone deployed librime", report["boundary"])

    def test_wrong_top1_and_missing_input_fail(self) -> None:
        fixture = {
            "schemaVersion": "rag-ime.rime-lexicon-eval.v1",
            "cases": [
                {"id": "a", "input": "yon", "expectedTop1": "用", "equivalenceGroup": "yong"},
                {"id": "b", "input": "yong", "expectedTop1": "用", "equivalenceGroup": "yong"},
            ],
        }

        report = evaluate_librime_probe(fixture, "yon\t永\n")

        self.assertFalse(report["ok"])
        self.assertEqual(report["top1Accuracy"], 0.0)
        self.assertEqual(report["missingInputs"], ["yong"])

    def test_fixture_rejects_duplicate_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.rime-lexicon-eval.v1",
                        "cases": [
                            {"id": "a", "input": "yong", "expectedTop1": "用"},
                            {"id": "b", "input": "yong", "expectedTop1": "永"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_rime_lexicon_eval(path)
