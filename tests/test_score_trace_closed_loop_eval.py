from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from scripts.score_trace_closed_loop_eval import score_trace_closed_loop


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "eval" / "trace-agent" / "closed-loop-v1"
MANIFEST = SUITE / "public-manifest.json"
SCHEMA = SUITE / "public-manifest.schema.json"


def _gold() -> dict[str, object]:
    return {
        "schemaVersion": "paw.trace-closed-loop-host-gold.v1",
        "suiteId": "paw-trace-closed-loop-historical-replay-v1",
        "cases": [
            {
                "caseId": "PI-CODEX-WIRE-001",
                "acceptableFirstFailingSpanIds": [
                    "span:provider-http-400",
                    "span:provider-websocket-400",
                ],
                "rootOwner": "pi_openai_codex_provider_adapter",
                "targetLayer": "tool",
                "requiredEvidenceGroups": [
                    ["evidence:pi:request-field"],
                    ["evidence:pi:provider-error"],
                    ["evidence:pi:ab-completion"],
                ],
                "validEvidenceIds": [
                    "evidence:pi:request-field",
                    "evidence:pi:provider-error",
                    "evidence:pi:ab-completion",
                ],
                "supportedConclusionCodes": [
                    "unsupported-field-causes-provider-rejection",
                    "candidate-not-installed",
                ],
                "repair": {
                    "eligible": True,
                    "successful": True,
                    "regression": False,
                    "decision": "Keep",
                },
            },
            {
                "caseId": "TRACE-SKILL-ENV-001",
                "acceptableFirstFailingSpanIds": [
                    "span:report-finalize-schema-rejection"
                ],
                "rootOwner": "trace_agent_diagnostics_skill",
                "targetLayer": "skill",
                "requiredEvidenceGroups": [
                    ["evidence:skill:rejection"],
                    ["evidence:skill:completed-report"],
                ],
                "validEvidenceIds": [
                    "evidence:skill:rejection",
                    "evidence:skill:completed-report",
                ],
                "supportedConclusionCodes": ["skill-envelope-under-specified"],
                "repair": {
                    "eligible": True,
                    "successful": True,
                    "regression": False,
                    "decision": "Keep",
                },
            },
            {
                "caseId": "CLOUDOPS-OBS-ID-001",
                "acceptableFirstFailingSpanIds": [
                    "span:tool-read-cache-key-miss"
                ],
                "rootOwner": "cloudops_observation_address_contract",
                "targetLayer": "tool",
                "requiredEvidenceGroups": [
                    ["evidence:obs:before-failure"],
                    ["evidence:obs:after-tool-success"],
                    ["evidence:obs:quality-regression"],
                ],
                "validEvidenceIds": [
                    "evidence:obs:before-failure",
                    "evidence:obs:after-tool-success",
                    "evidence:obs:quality-regression",
                ],
                "supportedConclusionCodes": [
                    "short-id-clears-addressing-failure",
                    "quality-regressed",
                ],
                "repair": {
                    "eligible": True,
                    "successful": True,
                    "regression": True,
                    "decision": "Reject",
                },
            },
        ],
    }


def _predictions() -> dict[str, object]:
    return {
        "schemaVersion": "paw.trace-closed-loop-predictions.v1",
        "suiteId": "paw-trace-closed-loop-historical-replay-v1",
        "cases": [
            {
                "caseId": "PI-CODEX-WIRE-001",
                "firstFailingSpanId": "span:provider-http-400",
                "rootOwner": "pi_openai_codex_provider_adapter",
                "targetLayer": "tool",
                "evidenceRefs": [
                    "evidence:pi:request-field",
                    "evidence:pi:provider-error",
                    "evidence:pi:ab-completion",
                    "evidence:noise",
                ],
                "conclusionCodes": [
                    "unsupported-field-causes-provider-rejection",
                    "unsupported-installed-claim",
                ],
                "repairAssessment": {
                    "successful": True,
                    "regression": False,
                    "decision": "Keep",
                },
            },
            {
                "caseId": "TRACE-SKILL-ENV-001",
                "firstFailingSpanId": "span:wrong",
                "rootOwner": "trace_report_runtime",
                "targetLayer": "skill",
                "evidenceRefs": ["evidence:skill:rejection"],
                "conclusionCodes": ["skill-envelope-under-specified"],
                "repairAssessment": {
                    "successful": False,
                    "regression": False,
                    "decision": "Reject",
                },
            },
            {
                "caseId": "CLOUDOPS-OBS-ID-001",
                "firstFailingSpanId": "span:tool-read-cache-key-miss",
                "rootOwner": "cloudops_observation_address_contract",
                "targetLayer": "tool",
                "evidenceRefs": [
                    "evidence:obs:before-failure",
                    "evidence:obs:after-tool-success",
                    "evidence:obs:quality-regression",
                ],
                "conclusionCodes": [
                    "short-id-clears-addressing-failure",
                    "quality-regressed",
                ],
                "repairAssessment": {
                    "successful": True,
                    "regression": True,
                    "decision": "Reject",
                },
            },
        ],
    }


class TraceClosedLoopScorerTests(unittest.TestCase):
    def test_public_manifest_is_strict_safe_and_contains_required_attribution(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        Draft202012Validator(schema).validate(manifest)
        self.assertTrue(manifest["notAgentInput"])
        self.assertEqual(
            {
                "PI-CODEX-WIRE-001",
                "TRACE-SKILL-ENV-001",
                "CLOUDOPS-OBS-ID-001",
            },
            {case["caseId"] for case in manifest["cases"]},
        )
        for case in manifest["cases"]:
            for field in (
                "detectedBy",
                "proposedBy",
                "authorizedBy",
                "implementedBy",
                "verifiedBy",
                "targetLayer",
                "before",
                "finding",
                "candidateChange",
                "after",
                "delta",
                "decision",
            ):
                self.assertIn(field, case)

        serialized = json.dumps(manifest, ensure_ascii=False)
        for forbidden in (
            "/Volumes/",
            "/Users/",
            "/private/",
            "SELECT ",
            ".jsonl",
            "acceptableFirstFailingSpanIds",
            "requiredEvidenceGroups",
            "validEvidenceIds",
            '"rootOwner"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_public_manifest_schema_rejects_private_paths_and_raw_query_text(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        private_path = copy.deepcopy(manifest)
        private_path["cases"][0]["before"]["summary"] = (
            "Read /Volumes/private/agent/sessions/source.jsonl"
        )
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(private_path)

        raw_query = copy.deepcopy(manifest)
        raw_query["cases"][0]["finding"]["summary"] = (
            "SELECT secret FROM host_private_gold"
        )
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(raw_query)

    def test_scores_all_required_metrics_with_explicit_denominators(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        result = score_trace_closed_loop(manifest, _gold(), _predictions())

        self.assertEqual(3, result["caseCount"])
        self.assertEqual(
            {"correct": 2, "total": 3, "accuracy": 2 / 3},
            result["firstFailingSpan"],
        )
        self.assertEqual(
            {"correct": 2, "total": 3, "accuracy": 2 / 3},
            result["rootOwner"],
        )
        self.assertEqual(7, result["evidence"]["validPredictedRefs"])
        self.assertEqual(8, result["evidence"]["predictedRefs"])
        self.assertEqual(7, result["evidence"]["hitRequiredGroups"])
        self.assertEqual(8, result["evidence"]["requiredGroups"])
        self.assertEqual(0.875, result["evidence"]["precision"])
        self.assertEqual(0.875, result["evidence"]["recall"])
        self.assertEqual(0.875, result["evidence"]["f1"])
        self.assertEqual(
            {"unsupported": 1, "total": 5, "rate": 0.2},
            result["unsupportedConclusions"],
        )
        self.assertEqual(1.0, result["repair"]["actualSuccessRate"])
        self.assertEqual(2 / 3, result["repair"]["assessmentAccuracy"])
        self.assertEqual(1 / 3, result["regression"]["actualRate"])
        self.assertEqual(1.0, result["regression"]["detectionAccuracy"])
        self.assertEqual(2 / 3, result["decision"]["accuracy"])
        self.assertEqual(1 / 3, result["diagnosticCaseSuccess"]["rate"])

    def test_scorer_fails_closed_on_case_or_suite_drift(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        predictions = _predictions()
        predictions["cases"] = list(predictions["cases"])[1:]
        with self.assertRaisesRegex(ValueError, "case IDs"):
            score_trace_closed_loop(manifest, _gold(), predictions)

        gold = _gold()
        gold["suiteId"] = "drifted"
        with self.assertRaisesRegex(ValueError, "suiteId"):
            score_trace_closed_loop(manifest, gold, _predictions())

    def test_cli_writes_a_public_score_without_copying_host_gold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gold = root / "gold.json"
            predictions = root / "predictions.json"
            output = root / "score.json"
            gold.write_text(json.dumps(_gold()), encoding="utf-8")
            predictions.write_text(json.dumps(_predictions()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/score_trace_closed_loop_eval.py",
                    "--manifest",
                    str(MANIFEST),
                    "--host-gold",
                    str(gold),
                    "--predictions",
                    str(predictions),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            score = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("paw.trace-closed-loop-score.v1", score["schemaVersion"])
            serialized = json.dumps(score)
            self.assertNotIn("acceptableFirstFailingSpanIds", serialized)
            self.assertNotIn("requiredEvidenceGroups", serialized)
            self.assertNotIn(str(gold), serialized)


if __name__ == "__main__":
    unittest.main()
