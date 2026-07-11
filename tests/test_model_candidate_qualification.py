from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.minimind_quality_gate import (
    PROMOTION_QUALITY_CHECK_NAMES,
    QUALITY_SCHEMA_VERSION,
    audit_completion_dataset,
)
from rag_ime.model_candidate_qualification import (
    finalize_model_candidate_qualification,
    prepare_model_candidate_plan,
)
from scripts.minimind_retraining import _verify_raw_capture_evidence, _verify_runtime_checkpoint


ROOT = Path(__file__).resolve().parents[1]


class ModelCandidateQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="model-candidate-qualification-")
        self.root = Path(self.tmp.name)
        self.model = self.root / "candidate model"
        self.model.mkdir()
        (self.model / "config.json").write_text('{"architectures":["Qwen3ForCausalLM"]}', encoding="utf-8")
        (self.model / "model.safetensors").write_bytes(b"candidate weights")
        (self.model / "tokenizer.json").write_text('{"version":"1"}', encoding="utf-8")
        self.plan_path = self.root / "candidate-plan.json"
        self.plan = prepare_model_candidate_plan(
            model_path=self.model,
            model_id="minimind-ime-v3-candidate",
            profile="minimind_ime_v3",
            dataset_root=ROOT / "dataset" / "minimind_completion_v3_public",
            output_path=self.plan_path,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prepare_is_inactive_and_does_not_touch_live_registry(self) -> None:
        self.assertFalse(self.plan["inactiveRegistryEntry"]["active"])
        self.assertEqual(self.plan["inactiveRegistryEntry"]["lane"], "candidate")
        self.assertFalse(self.plan["activeModelMutationAllowed"])
        self.assertIn("--checkpoint-path", self.plan["commands"]["rawGate"])
        self.assertIn("--raw-capture-report", self.plan["commands"]["rawGate"])
        self.assertIn("--endpoint", self.plan["commands"]["rawCapture"])
        self.assertNotIn("--base-url", self.plan["commands"]["rawCapture"])
        raw_gate_tokens = shlex.split(self.plan["commands"]["rawGate"])
        self.assertEqual(
            Path(raw_gate_tokens[raw_gate_tokens.index("--checkpoint-path") + 1]),
            self.model.resolve(),
        )
        self.assertEqual(set(self.plan["requiredChecks"]), PROMOTION_QUALITY_CHECK_NAMES)
        for command in self.plan["commands"].values():
            syntax = subprocess.run(["sh", "-n", "-c", command], capture_output=True, text=True, check=False)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertFalse((self.root / "models.json").exists())

    def test_finalize_requires_both_fingerprint_bound_quality_stages_and_foreground_for_activation(self) -> None:
        raw = self._quality("raw_model_output")
        production = self._quality("production_candidate")
        raw_path = self._write("raw.json", raw)
        production_path = self._write("production.json", production)

        report = finalize_model_candidate_qualification(
            plan_path=self.plan_path,
            raw_quality_path=raw_path,
            production_quality_path=production_path,
            output_path=self.root / "qualification.json",
        )

        self.assertTrue(report["backendQualified"], report)
        self.assertFalse(report["activationEligible"])
        self.assertFalse(report["activeModelMutated"])
        self.assertEqual(report["registryAction"], "none")

        foreground = self._write(
            "foreground.json",
            {
                "passed": True,
                "strictSoakPassed": True,
                "modelFingerprint": self.plan["artifact"]["fingerprint"],
                "datasetFingerprint": self.plan["dataset"]["fingerprint"],
            },
        )
        accepted = finalize_model_candidate_qualification(
            plan_path=self.plan_path,
            raw_quality_path=raw_path,
            production_quality_path=production_path,
            foreground_evidence_path=foreground,
            output_path=self.root / "qualification-with-foreground.json",
        )
        self.assertTrue(accepted["activationEligible"])
        self.assertEqual(accepted["nextAction"], "manual_review_then_explicit_registry_activation")

    def test_artifact_change_or_wrong_stage_fingerprint_fails_closed(self) -> None:
        raw = self._quality("raw_model_output")
        raw["checkpointFingerprint"] = "sha256:wrong"
        production = self._quality("production_candidate")
        report = finalize_model_candidate_qualification(
            plan_path=self.plan_path,
            raw_quality_path=self._write("raw.json", raw),
            production_quality_path=self._write("production.json", production),
            output_path=self.root / "qualification.json",
        )
        self.assertFalse(report["backendQualified"])
        self.assertIn("evidence_binding_mismatch", {item["id"] for item in report["issues"]})

        (self.model / "model.safetensors").write_bytes(b"changed weights")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            finalize_model_candidate_qualification(
                plan_path=self.plan_path,
                raw_quality_path=self.root / "raw.json",
                production_quality_path=self.root / "production.json",
                output_path=self.root / "second.json",
            )

    def test_finalize_rejects_synthetic_all_check_or_missing_runtime_evidence(self) -> None:
        raw = self._quality("raw_model_output")
        raw["checks"] = [{"name": "all", "actual": 1.0, "expected": 1.0, "operator": ">=", "passed": True}]
        raw.pop("rawCaptureEvidence")
        report = finalize_model_candidate_qualification(
            plan_path=self.plan_path,
            raw_quality_path=self._write("raw-incomplete.json", raw),
            production_quality_path=self._write("production.json", self._quality("production_candidate")),
            output_path=self.root / "incomplete.json",
        )

        issue_ids = {item["id"] for item in report["issues"]}
        self.assertFalse(report["backendQualified"])
        self.assertIn("quality_checks_missing", issue_ids)
        self.assertIn("runtime_evidence_mismatch", issue_ids)

    def test_runtime_and_raw_capture_evidence_bind_the_same_artifact(self) -> None:
        model_path = str(self.model)

        class _Provider:
            config = SimpleNamespace(model=model_path)

            @staticmethod
            def capability_probe():
                return {
                    "ok": True,
                    "modelLoaded": True,
                    "model": model_path,
                    "providerName": "local-mlx",
                }

        runtime = _verify_runtime_checkpoint(_Provider(), self.model)
        self.assertTrue(runtime["verified"])

        raw_path = self.root / "raw-evidence.jsonl"
        raw_path.write_text('{"prefix":"测试","candidates":["继续"]}\n', encoding="utf-8")
        raw_sha = "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()
        capture_path = self._write(
            "raw-capture.json",
            {
                "verified": True,
                "checkpoint": self.plan["candidateId"],
                "checkpointFingerprint": self.plan["artifact"]["fingerprint"],
                "datasetFingerprint": self.plan["dataset"]["fingerprint"],
                "runtimeModel": str(self.model.resolve()),
                "rawOutputSha256": raw_sha,
            },
        )
        evidence = _verify_raw_capture_evidence(
            capture_report_path=capture_path,
            raw_output_path=raw_path,
            checkpoint=self.plan["candidateId"],
            checkpoint_path=self.model,
            dataset_fingerprint=self.plan["dataset"]["fingerprint"],
        )
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["rawOutputSha256"], raw_sha)

    def _quality(self, stage: str) -> dict[str, object]:
        dataset = audit_completion_dataset(ROOT / "dataset" / "minimind_completion_v3_public")
        payload: dict[str, object] = {
            "schemaVersion": QUALITY_SCHEMA_VERSION,
            "evaluationStage": stage,
            "checkpoint": self.plan["candidateId"],
            "checkpointFingerprint": self.plan["artifact"]["fingerprint"],
            "checkpointPath": self.plan["artifact"]["path"],
            "datasetFingerprint": dataset["datasetFingerprint"],
            "gatePassed": True,
            "promotionEligible": True,
            "semanticScorer": {"configured": True},
            "checks": [
                {"name": name, "actual": 1.0, "expected": 1.0, "operator": ">=", "passed": True}
                for name in sorted(PROMOTION_QUALITY_CHECK_NAMES)
            ],
            "summary": {"continuousTabPassRate": 1.0, "p95LatencyMs": 80},
        }
        evidence_field = "rawCaptureEvidence" if stage == "raw_model_output" else "runtimeModelEvidence"
        payload[evidence_field] = {
            "verified": True,
            "checkpoint": self.plan["candidateId"],
            "checkpointFingerprint": self.plan["artifact"]["fingerprint"],
            "datasetFingerprint": dataset["datasetFingerprint"],
        }
        return payload

    def _write(self, name: str, payload: dict[str, object]) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
