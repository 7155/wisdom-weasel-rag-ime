from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.promote_enterpriseops_csm_validation import (
    PromotionError,
    promote_validation,
)


class PromoteEnterpriseOpsCsmValidationTests(unittest.TestCase):
    def test_requires_explicit_one_shot_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            output = root / "promotion.json"
            baseline.write_text(json.dumps(_report("baseline-v1", 2, 28)), encoding="utf-8")
            candidate.write_text(json.dumps(_report("state-contract-v1", 3, 31)), encoding="utf-8")

            with self.assertRaisesRegex(PromotionError, "authorize-held-out-once"):
                promote_validation(baseline, candidate, output, authorize_held_out_once=False)
            self.assertFalse(output.exists())

    def test_accepts_only_a_strict_validation_winner_and_writes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            output = root / "promotion.json"
            baseline.write_text(json.dumps(_report("baseline-v1", 2, 28)), encoding="utf-8")
            candidate.write_text(json.dumps(_report("state-contract-v1", 3, 31)), encoding="utf-8")

            receipt = promote_validation(baseline, candidate, output, authorize_held_out_once=True)
            self.assertEqual("authorized", receipt["status"])
            self.assertTrue(receipt["heldOutAuthorized"])
            self.assertEqual("state-contract-v1", receipt["winner"]["workflowProfile"])
            self.assertEqual("40ac966a", receipt["winner"]["overlaySha256"][:8])
            self.assertEqual(31, receipt["winner"]["verifierPassCount"])
            self.assertEqual(receipt["receiptSha256"], _receipt_hash(output))

    def test_rejects_candidate_without_full_validation_gate_or_shared_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            output = root / "promotion.json"
            baseline.write_text(json.dumps(_report("baseline-v1", 2, 28)), encoding="utf-8")
            failed = _report("state-contract-v1", 3, 30)
            failed["evaluationContract"]["toolCatalogSha256"] = "different"
            failed["reportSha256"] = _report_hash(failed)
            candidate.write_text(json.dumps(failed), encoding="utf-8")

            with self.assertRaisesRegex(PromotionError, "candidate"):
                promote_validation(baseline, candidate, output, authorize_held_out_once=True)
            self.assertFalse(output.exists())


def _report(profile: str, task_success_count: int, verifier_pass_count: int) -> dict[str, object]:
    report = {
        "schemaVersion": "paw.enterpriseops-csm-eval.v1",
        "status": "completed",
        "split": "validation",
        "manifest": {
            "manifestSha256": "d5ef3eb648678fd6abd92879b1a3c946ba335da32f2e26c775792fad8e038fec",
            "overlaySha256": "40ac966afefb0a71bb1f3e04560bdbf4953fac2788ce2ba90e05b86cfe26677b",
            "suiteRevision": "enterpriseops-csm-suite-v2",
            "taskCount": 3,
            "rawVerifierCount": 31,
            "taskIds": ["task-a", "task-b", "task-c"],
        },
        "evaluationContract": {
            "suiteRevision": "enterpriseops-csm-suite-v2",
            "overlaySha256": "40ac966afefb0a71bb1f3e04560bdbf4953fac2788ce2ba90e05b86cfe26677b",
            "taskManifestSha256": "d5ef3eb648678fd6abd92879b1a3c946ba335da32f2e26c775792fad8e038fec",
            "runtimeIdentitySha256": "runtime",
            "toolCatalogSha256": "catalog",
            "runnerSha256": "runner",
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "thinking": "high",
        },
        "lane": {
            "workflowProfile": profile,
            "taskCount": 3,
            "taskSuccessCount": task_success_count,
            "verifierCount": 31,
            "verifierPassCount": verifier_pass_count,
            "toolCalls": 72,
            "failedToolCalls": 0,
            "allDatabasesCleaned": True,
        },
    }
    report["reportSha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def _receipt_hash(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("receiptSha256")
    actual = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert expected == actual
    return expected


def _report_hash(report: dict[str, object]) -> str:
    payload = {key: value for key, value in report.items() if key != "reportSha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
