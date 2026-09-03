from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_rcaeval_incident_eval import (
    FAULTY_WINDOW_ROWS,
    FROZEN_VALIDATION_CONTRACT,
    FROZEN_VALIDATION_CONTRACT_SHA256,
    NORMAL_WINDOW_ROWS,
    PROFILE_CONFIGS,
    _reserve_held_out_consumption,
    _verify_private_evaluation_receipt,
    _verify_held_out_current_binding,
    build_case_manifest,
    compute_official_metrics,
    evaluate_promotion_gate,
    fuse_rankings_rrf,
    sha256_json,
    select_re1_validation_cases,
    validate_re1_grid,
    run_rcaeval_incident_eval,
    validate_split_authorization,
)


ROOT = Path(__file__).resolve().parents[1]


class RunRcaEvalIncidentEvalTests(unittest.TestCase):
    def test_validation_filters_re1_before_repetition_and_selects_150_cases(self) -> None:
        rows = [
            {"case": "re2-ob-1", "suite": "RE2", "repetition": 1},
            {"case": "re1-ob-3", "suite": "RE1", "repetition": 3},
            {"case": "re1-ob-2", "suite": "RE1", "repetition": 2},
            {"case": "re1-ob-1", "suite": "RE1", "repetition": 1},
        ]

        selected = select_re1_validation_cases(rows)

        self.assertEqual(["re1-ob-1", "re1-ob-2"], [row["case"] for row in selected])

        grid = [
            {
                "case": f"re1-{system}-{service}-{fault}-{repetition}",
                "suite": "RE1",
                "repetition": repetition,
                "system": system,
                "fault": fault,
            }
            for system in ("ob", "ss", "tt")
            for service in ("a", "b", "c", "d", "e")
            for fault in ("cpu", "mem", "disk", "delay", "loss")
            for repetition in range(1, 6)
        ]
        self.assertEqual(150, len(select_re1_validation_cases(grid)))

    def test_held_out_requires_matching_promotion_gate_and_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "held.?out"):
            validate_split_authorization("held-out")

        mismatched = {
            "schemaVersion": "paw.rcaeval-promotion.v1",
            "validationContractSha256": "0" * 64,
            "heldOutAuthorized": True,
        }
        with self.assertRaisesRegex(ValueError, "contract"):
            validate_split_authorization("held-out", promotion_receipt=mismatched)

        with self.assertRaisesRegex(ValueError, "binding"):
            validate_split_authorization(
                "held-out",
                promotion_receipt={
                    "schemaVersion": "paw.rcaeval-promotion.v1",
                    "validationContractSha256": FROZEN_VALIDATION_CONTRACT_SHA256,
                    "heldOutAuthorized": True,
                    "decision": "keep",
                },
            )

        validate_split_authorization(
            "held-out", promotion_receipt=self._matching_promotion_receipt()
        )

    def _matching_promotion_receipt(self) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schemaVersion": "paw.rcaeval-promotion.v1",
            "validationContractSha256": FROZEN_VALIDATION_CONTRACT_SHA256,
            "heldOutAuthorized": True,
            "decision": "keep",
            "validationReportSha256": "1" * 64,
            "validationBaselinePrivateSha256": "a" * 64,
            "validationCandidatePrivateSha256": "b" * 64,
            "validationCaseManifestSha256": "2" * 64,
            "datasetIndexSha256": "3" * 64,
            "datasetSnapshotSha256": "6" * 64,
            "sourceRevision": "4" * 40,
            "sourceSha256": "5" * 64,
            "runnerSha256": "7" * 64,
            "environmentSha256": "8" * 64,
            "candidateProfile": "rrf-v2",
            "candidateConfigSha256": sha256_json(PROFILE_CONFIGS["rrf-v2"]),
            "validationMetrics": {
                "service.AC@1": 0.7,
                "service.AC@3": 0.9,
                "service.AC@5": 0.97,
                "fineGrained.AC@1": 0.17,
                "fineGrained.AC@3": 0.33,
                "fineGrained.AC@5": 0.38,
            },
            "promotionGate": {
                "passed": True,
                "primaryServiceAc1StrictImprovement": True,
                "noRegressionAcrossSixMetrics": True,
                "failedCasePolicyPassed": True,
            },
            "oneShotId": "rcaeval-re1-heldout:" + "9" * 24,
            "heldOutConsumed": False,
        }
        receipt["promotionReceiptSha256"] = sha256_json(receipt)
        return receipt

    def test_held_out_rejects_candidate_or_gate_binding_drift(self) -> None:
        receipt = self._matching_promotion_receipt()
        receipt["candidateProfile"] = "baro"
        with self.assertRaisesRegex(ValueError, "binding"):
            validate_split_authorization("held-out", promotion_receipt=receipt)

    def test_held_out_rejects_existing_output_or_consumption_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rcaeval-heldout-guard-") as temporary:
            root = Path(temporary)
            output = root / "held-out.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target output"):
                run_rcaeval_incident_eval(
                    data_root=root / "missing-data",
                    source_root=root / "missing-source",
                    output=output,
                    split="held-out",
                    profile="rrf-v2",
                    promotion_receipt=self._matching_promotion_receipt(),
                )

            consumption = root / "consumed.json"
            receipt = self._matching_promotion_receipt()
            _reserve_held_out_consumption(consumption, document=receipt)
            with self.assertRaisesRegex(ValueError, "already reserved"):
                _reserve_held_out_consumption(consumption, document=receipt)

        receipt = self._matching_promotion_receipt()
        receipt["heldOutConsumed"] = True
        with self.assertRaisesRegex(ValueError, "binding"):
            validate_split_authorization("held-out", promotion_receipt=receipt)

    def test_rrf_profile_is_frozen_and_deterministic(self) -> None:
        fused = fuse_rankings_rrf(
            {
                "baro": ["a", "b", "c"],
                "nsigma": ["c", "b", "d"],
            }
        )

        self.assertEqual(["c", "b", "d", "a"], fused)
        self.assertEqual(10, FROZEN_VALIDATION_CONTRACT["profiles"]["rrf-v1"]["rrfK"])
        self.assertEqual(
            {"baro": 0.25, "nsigma": 0.75},
            FROZEN_VALIDATION_CONTRACT["profiles"]["rrf-v1"]["weights"],
        )
        self.assertEqual(3, FROZEN_VALIDATION_CONTRACT["profiles"]["rrf-v2"]["rrfK"])
        self.assertEqual(
            {"baro": 0.35, "nsigma": 0.65},
            FROZEN_VALIDATION_CONTRACT["profiles"]["rrf-v2"]["weights"],
        )
        self.assertEqual(600, NORMAL_WINDOW_ROWS)
        self.assertEqual(600, FAULTY_WINDOW_ROWS)

        with self.assertRaisesRegex(ValueError, "finite"):
            fuse_rankings_rrf(
                {"baro": ["a"], "nsigma": ["b"]},
                weights={"baro": float("nan"), "nsigma": 0.75},
            )

    def test_official_metrics_count_failed_case_as_zero_for_both_levels(self) -> None:
        records = [
            {
                "case": "one",
                "system": "ob",
                "fault": "cpu",
                "rootCauseService": "cartservice",
                "ranked": ["cartservice_cpu", "frontend_cpu"],
                "status": "ok",
            },
            {
                "case": "two",
                "system": "ob",
                "fault": "mem",
                "rootCauseService": "adservice",
                "ranked": [],
                "status": "error",
            },
        ]

        metrics = compute_official_metrics(records)

        self.assertEqual(2, metrics["caseCount"])
        self.assertEqual(1, metrics["failedCaseCount"])
        self.assertEqual(0.5, metrics["service"]["AC@1"])
        self.assertEqual(0.5, metrics["service"]["AC@3"])
        self.assertEqual(0.5, metrics["fineGrained"]["AC@1"])
        self.assertEqual(0.5, metrics["fineGrained"]["AC@3"])
        self.assertEqual(0.5, metrics["bySystem"]["ob"]["service"]["AC@1"])
        self.assertEqual(1.0, metrics["byFault"]["cpu"]["fineGrained"]["AC@1"])
        self.assertEqual(0.0, metrics["byFault"]["mem"]["fineGrained"]["AC@1"])

    def test_private_evaluator_receipt_is_recomputed_not_trusted(self) -> None:
        cases = [
            {
                "case": "one",
                "system": "ob",
                "fault": "cpu",
                "rootCauseService": "cartservice",
                "ranked": ["cartservice_cpu"],
                "status": "ok",
            }
        ]
        metrics = compute_official_metrics(cases)
        receipt: dict[str, object] = {
            "schemaVersion": "paw.rcaeval-private-evaluation.v1",
            "profile": "baro",
            "caseResults": cases,
            "metrics": metrics,
        }
        receipt["privateEvaluationSha256"] = sha256_json(receipt)

        _verify_private_evaluation_receipt(receipt, public_metrics=metrics)

        forged = json.loads(json.dumps(receipt))
        forged["metrics"]["service"]["AC@1"] = 0.0
        forged["privateEvaluationSha256"] = sha256_json(
            {key: value for key, value in forged.items() if key != "privateEvaluationSha256"}
        )
        with self.assertRaisesRegex(ValueError, "recomputed"):
            _verify_private_evaluation_receipt(forged, public_metrics=metrics)

    def test_service_projection_deduplicates_the_full_node_ranking(self) -> None:
        records = [
            {
                "case": "one",
                "system": "ob",
                "fault": "cpu",
                "rootCauseService": "truth",
                "ranked": [
                    "other_cpu",
                    "other_mem",
                    "other_latency",
                    "truth_cpu",
                ],
                "status": "ok",
            }
        ]

        metrics = compute_official_metrics(records)

        # RCAEval main.py deduplicates services before the AC@k slice.  The
        # full node ranking must therefore survive until scoring.
        self.assertEqual(1.0, metrics["service"]["AC@3"])

    def test_exact_re1_grid_rejects_a_missing_service_fault_cell(self) -> None:
        rows = [
            {
                "case": f"re1-{system}-{service}-{fault}-{repetition}",
                "suite": "RE1",
                "system": system,
                "root_cause_service": service,
                "fault": fault,
                "repetition": repetition,
            }
            for system, services in {
                "ob": ("adservice", "cartservice", "checkoutservice", "currencyservice", "productcatalogservice"),
                "ss": ("carts", "catalogue", "orders", "payment", "user"),
                "tt": ("ts-auth-service", "ts-order-service", "ts-route-service", "ts-train-service", "ts-travel-service"),
            }.items()
            for service in services
            for fault in ("cpu", "mem", "disk", "delay", "loss")
            for repetition in (1, 2)
        ]

        validate_re1_grid(rows, split="validation")
        with self.assertRaisesRegex(ValueError, "grid"):
            validate_re1_grid(rows[:-1], split="validation")

    def test_current_held_out_binding_rejects_source_or_index_drift(self) -> None:
        receipt = self._matching_promotion_receipt()
        _verify_held_out_current_binding(
            receipt,
            dataset_snapshot_sha256="6" * 64,
            source_revision="4" * 40,
            source_sha256="5" * 64,
            runner_sha256="7" * 64,
            environment_sha256="8" * 64,
            profile="rrf-v2",
        )

        with self.assertRaisesRegex(ValueError, "dataset snapshot"):
            _verify_held_out_current_binding(
                receipt,
                dataset_snapshot_sha256="0" * 64,
                source_revision="4" * 40,
                source_sha256="5" * 64,
                runner_sha256="7" * 64,
                environment_sha256="8" * 64,
                profile="rrf-v2",
            )

    def test_promotion_gate_requires_strict_service_ac1_and_no_metric_regression(self) -> None:
        baseline = {
            "service": {"AC@1": 0.68, "AC@3": 0.90, "AC@5": 0.96},
            "fineGrained": {"AC@1": 0.17, "AC@3": 0.32, "AC@5": 0.35},
        }
        candidate = {
            "service": {"AC@1": 0.73, "AC@3": 0.92, "AC@5": 0.97},
            "fineGrained": {"AC@1": 0.17, "AC@3": 0.33, "AC@5": 0.38},
        }

        gate = evaluate_promotion_gate(baseline, candidate)

        self.assertTrue(gate["passed"])
        self.assertTrue(gate["primaryServiceAc1StrictImprovement"])
        self.assertTrue(gate["noRegressionAcrossSixMetrics"])

        regressed = dict(candidate)
        regressed["fineGrained"] = {**candidate["fineGrained"], "AC@5": 0.34}
        self.assertFalse(evaluate_promotion_gate(baseline, regressed)["passed"])

    def test_case_manifest_is_canonical_and_binds_replay_identifiers(self) -> None:
        rows = [
            {"case": "b", "suite": "RE1", "repetition": 2},
            {"case": "a", "suite": "RE1", "repetition": 1},
        ]

        manifest = build_case_manifest(rows)

        self.assertEqual(["a", "b"], manifest["caseIds"])
        self.assertEqual(2, manifest["caseCount"])
        self.assertRegex(manifest["caseManifestSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["replayCohortId"], r"^replay:rcaeval:re1-validation-")

    def test_case_manifest_is_profile_independent(self) -> None:
        rows = [
            {"case": "b", "suite": "RE1", "repetition": 2},
            {"case": "a", "suite": "RE1", "repetition": 1},
        ]

        baseline = build_case_manifest(rows)
        candidate = build_case_manifest(rows)

        self.assertEqual(baseline["caseManifestSha256"], candidate["caseManifestSha256"])
        self.assertEqual(baseline["replayCohortId"], candidate["replayCohortId"])
        self.assertNotIn("profile", baseline)

    def test_cli_help_does_not_import_runtime_dependencies(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_rcaeval_incident_eval.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--data-root", completed.stdout)
        self.assertIn("--source-root", completed.stdout)
        self.assertIn("held-out", completed.stdout)


if __name__ == "__main__":
    unittest.main()
