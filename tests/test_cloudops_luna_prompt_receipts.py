from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import unittest

from rag_ime.contracts.json_schema import validate_contract


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "interview-metrics" / "runs"
MODEL_ONLY = RUNS / "cloudops-luna-max-alert-first-model-only-case-projection-20260904.r1.json"
CANDIDATE = RUNS / "cloudops-luna-max-owner-mechanism-prompt-case-projection-20260904.r5.json"
COMPARISON = RUNS / "cloudops-sol-to-luna-owner-mechanism-prompt-20260904.r1.json"
PATH_SEARCH = RUNS / "agent-lab-optimal-path-cloudops-luna-prompt-20260904.v1.json"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_hash(value: dict[str, object]) -> str:
    payload = deepcopy(value)
    payload.pop("receiptSha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CloudOpsLunaPromptReceiptTests(unittest.TestCase):
    def test_public_run_projections_keep_only_case_scores_and_sealed_evidence(self) -> None:
        model_only = _read(MODEL_ONLY)
        candidate = _read(CANDIDATE)

        self.assertEqual(model_only["schemaVersion"], "paw.cloudops-case-score-projection.v1")
        self.assertEqual(candidate["schemaVersion"], "paw.cloudops-case-score-projection.v1")
        self.assertEqual(model_only["metrics"], {
            "AnswerCoverage": 1.0,
            "CA": 0.9166666666666666,
            "FA": 0.8333333333333334,
            "JRA": 0.75,
            "Top3JRA": 0.9166666666666666,
        })
        self.assertEqual(candidate["metrics"], {
            "AnswerCoverage": 1.0,
            "CA": 1.0,
            "FA": 0.9166666666666666,
            "JRA": 0.9166666666666666,
            "Top3JRA": 1.0,
        })
        self.assertEqual(len(model_only["tasks"]), 12)
        self.assertEqual(len(candidate["tasks"]), 12)
        self.assertEqual(candidate["signals"]["toolCalls"], 130)
        self.assertEqual(candidate["signals"]["failedToolCalls"], 0)

        for receipt in (model_only, candidate):
            serialized = json.dumps(receipt, ensure_ascii=False)
            self.assertNotIn(".rag-ime-data", serialized)
            self.assertNotIn("/Volumes/", serialized)
            self.assertNotIn("/Users/", serialized)
            for task in receipt["tasks"]:
                self.assertEqual(set(task), {"taskId", "taskSucceeded", "terminalEvent", "verifier"})
                self.assertNotIn("rank1", task)
            evidence = receipt["evidence"]
            self.assertRegex(evidence["sourceArtifactSha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(evidence["terminalRecordSha256"], r"^[a-f0-9]{64}$")

    def test_three_stage_receipt_binds_files_and_preserves_causal_decisions(self) -> None:
        receipt = _read(COMPARISON)
        self.assertEqual(receipt["schemaVersion"], "paw.cloudops-model-prompt-optimization-receipt.v1")
        self.assertEqual(receipt["receiptSha256"], _sealed_hash(receipt))
        self.assertEqual(receipt["factorChain"][0]["changed"], ["model"])
        self.assertEqual(receipt["factorChain"][0]["decision"], "reject")
        self.assertEqual(receipt["factorChain"][1]["changed"], ["prompt"])
        self.assertEqual(receipt["factorChain"][1]["decision"], "keep")

        stages = {stage["stage"]: stage for stage in receipt["comparison"]["stages"]}
        self.assertEqual(stages["sol_baseline"]["costUsd"], "4.568166")
        self.assertEqual(stages["luna_model_only"]["costUsd"], "0.33593112")
        self.assertEqual(stages["luna_prompt_adapted"]["costUsd"], "0.27613024")
        self.assertEqual(stages["luna_prompt_adapted"]["CA"], 1.0)
        self.assertEqual(stages["luna_prompt_adapted"]["FA"], 0.9166666666666666)
        self.assertEqual(stages["luna_prompt_adapted"]["JRA"], 0.9166666666666666)
        self.assertEqual(stages["luna_prompt_adapted"]["Top3JRA"], 1.0)

        cost = receipt["comparison"]["costComparisons"]
        with localcontext() as context:
            context.prec = 80
            sol_to_final = (Decimal("4.568166") - Decimal("0.27613024")) / Decimal("4.568166") * 100
            model_to_final = (Decimal("0.33593112") - Decimal("0.27613024")) / Decimal("0.33593112") * 100
            ratio = Decimal("4.568166") / Decimal("0.27613024")
        self.assertLess(
            abs(Decimal(cost["solToPromptAdapted"]["decreasePercent"]) - sol_to_final),
            Decimal("1e-58"),
        )
        self.assertLess(
            abs(Decimal(cost["solToPromptAdapted"]["costRatio"]) - ratio),
            Decimal("1e-58"),
        )
        self.assertLess(
            abs(Decimal(cost["modelOnlyToPromptAdapted"]["decreasePercent"]) - model_to_final),
            Decimal("1e-58"),
        )

        for evidence in receipt["evidence"].values():
            self.assertEqual(evidence["runFileSha256"], _sha256(ROOT / evidence["runRef"]))
            self.assertEqual(evidence["costFileSha256"], _sha256(ROOT / evidence["costRef"]))
            cost_receipt = _read(ROOT / evidence["costRef"])
            self.assertEqual(cost_receipt["authority"], "runtime_cost_reconciled")
            self.assertEqual(cost_receipt["billing"]["status"], "not_provided")
            self.assertEqual(evidence["costReceiptSha256"], cost_receipt["receiptSha256"])
            self.assertEqual(cost_receipt["receiptSha256"], _sealed_hash(cost_receipt))

        self.assertFalse(receipt["comparison"]["providerBillAvailable"])
        self.assertEqual(receipt["comparison"]["costAuthority"], "runtime_cost_reconciled")
        self.assertIn("Validation", " ".join(receipt["claimBoundary"]))
        self.assertIn("not a Provider bill", " ".join(receipt["claimBoundary"]))

    def test_optimal_path_is_contract_valid_and_keeps_prompt_candidate(self) -> None:
        receipt = _read(PATH_SEARCH)
        validate_contract(receipt, "agent-lab-path-search.v1.json")
        self.assertEqual(
            [(step["nodeId"], step["decision"]) for step in receipt["selectedPath"]],
            [
                ("cloudops-sol-alert-first-r7", "baseline"),
                ("cloudops-luna-model-only-r1", "reject"),
                ("cloudops-luna-owner-mechanism-r5", "keep"),
            ],
        )
        self.assertEqual(receipt["claim"]["status"], "best_known")
        selected = receipt["candidates"][-1]
        self.assertEqual(selected["status"], "eligible")
        self.assertEqual(selected["metrics"]["qualityGatePassed"], 1.0)
        self.assertEqual(selected["metrics"]["apiCostUsd"], 0.27613024)
        frozen_hash = hashlib.sha256(json.dumps(
            receipt["frozenControls"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self.assertEqual(receipt["baseline"]["frozenControlHash"], frozen_hash)
        self.assertTrue(all(
            candidate["frozenControlHash"] == frozen_hash
            for candidate in receipt["candidates"]
        ))


if __name__ == "__main__":
    unittest.main()
