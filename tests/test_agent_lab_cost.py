from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from rag_ime.agent_lab_cost import AgentLabCostError, build_agent_lab_cost_receipt
from rag_ime.contracts.json_schema import ContractValidationError, validate_contract


ROOT = Path(__file__).resolve().parents[1]


def _request(
    *,
    model: str = "gpt-5.6-sol",
    rates: tuple[str, str, str] = ("4", "0.40", "20"),
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
        "pricingIdentity": {
            "pricingId": f"openai-api-{model}-2026-09-01",
            "provider": "openai",
            "model": model,
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": {
                "uncachedInputUsd": rates[0],
                "cachedInputUsd": rates[1],
                "outputUsd": rates[2],
            },
            "publishedDate": "2026-09-01",
            "sourceUrl": "https://example.com/pricing",
            "sourceSha256": "a" * 64,
        },
        "usage": {
            "available": True,
            "uncachedInputTokens": 1_000_000,
            "cachedInputTokens": 500_000,
            "outputTokens": 250_000,
            "sourceRef": "eval-run:usage-receipt",
            "sourceSha256": "b" * 64,
        },
    }


class AgentLabCostTests(unittest.TestCase):
    def test_sol_pricing_is_explicit_caller_data_and_decimal_exact(self) -> None:
        request = _request()
        before = copy.deepcopy(request)

        receipt = build_agent_lab_cost_receipt(request)

        self.assertEqual(before, request)
        self.assertEqual("pricing_estimate", receipt["authority"])
        self.assertEqual(
            {
                "uncachedInputCostUsd": "4",
                "cachedInputCostUsd": "0.2",
                "outputCostUsd": "5",
                "totalCostUsd": "9.2",
            },
            receipt["estimate"],
        )
        self.assertEqual({"status": "not_provided"}, receipt["billing"])
        self.assertRegex(receipt["receiptSha256"], r"^[a-f0-9]{64}$")
        validate_contract(receipt, "agent-lab-cost-receipt.v1.json")

    def test_luna_estimate_and_billed_receipt_remain_distinct(self) -> None:
        request = _request(
            model="gpt-5.6-luna",
            rates=("0.20", "0.02", "1.20"),
        )
        request["usage"] = {
            **request["usage"],
            "uncachedInputTokens": 250_000,
            "cachedInputTokens": 500_000,
            "outputTokens": 100_000,
        }
        request["billedReceipt"] = {
            "currency": "USD",
            "totalUsd": "0.19",
            "receiptRef": "billing:provider-receipt",
            "receiptSha256": "c" * 64,
        }

        receipt = build_agent_lab_cost_receipt(request)

        self.assertEqual("0.18", receipt["estimate"]["totalCostUsd"])
        self.assertEqual(
            {
                "status": "provided",
                "currency": "USD",
                "totalUsd": "0.19",
                "receiptRef": "billing:provider-receipt",
                "receiptSha256": "c" * 64,
            },
            receipt["billing"],
        )
        self.assertNotEqual(
            receipt["estimate"]["totalCostUsd"],
            receipt["billing"]["totalUsd"],
        )

    def test_missing_unavailable_or_all_zero_usage_is_rejected(self) -> None:
        missing = _request()
        del missing["usage"]
        unavailable = _request()
        unavailable["usage"]["available"] = False
        zero = _request()
        zero["usage"] = {
            **zero["usage"],
            "uncachedInputTokens": 0,
            "cachedInputTokens": 0,
            "outputTokens": 0,
        }

        for invalid in (missing, unavailable, zero):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AgentLabCostError):
                    build_agent_lab_cost_receipt(invalid)

    def test_request_rejects_float_rates_unknown_fields_and_bad_provenance(self) -> None:
        float_rate = _request()
        float_rate["pricingIdentity"]["rates"]["uncachedInputUsd"] = 4.0
        unknown = _request()
        unknown["claimedSavingsUsd"] = "100"
        bad_date = _request()
        bad_date["pricingIdentity"]["publishedDate"] = "2026-02-30"
        bad_url = _request()
        bad_url["pricingIdentity"]["sourceUrl"] = "file:///private/pricing.json"
        bad_hash = _request()
        bad_hash["usage"]["sourceSha256"] = "not-a-hash"

        for invalid in (float_rate, unknown, bad_date, bad_url, bad_hash):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AgentLabCostError):
                    build_agent_lab_cost_receipt(invalid)

    def test_receipt_contract_has_no_savings_or_billing_alias_escape_hatch(self) -> None:
        receipt = build_agent_lab_cost_receipt(_request())
        invalid = copy.deepcopy(receipt)
        invalid["savingsUsd"] = "1"
        with self.assertRaises(ContractValidationError):
            validate_contract(invalid, "agent-lab-cost-receipt.v1.json")

        source = (ROOT / "rag_ime" / "agent_lab_cost.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"gpt-5\.6-(?:sol|luna)", source))

    def test_receipt_identity_is_deterministic(self) -> None:
        first = build_agent_lab_cost_receipt(_request())
        second = build_agent_lab_cost_receipt(_request())
        self.assertEqual(first, second)

    def test_repository_retained_sol_receipts_are_strict_and_recomputable(self) -> None:
        expected = {
            "agent-lab-cost-enterpriseops-sol-max-compact-baseline-20260904.v1.json": "2.258372",
            "agent-lab-cost-enterpriseops-sol-max-preloaded-20260904.v1.json": "1.565709",
            "agent-lab-cost-memory-sol-max-full-json-baseline-20260904.r2.v1.json": "0.265205",
            "agent-lab-cost-memory-sol-max-concise-contract-20260904.r3.v1.json": "0.24769",
        }
        runs = ROOT / "eval" / "interview-metrics" / "runs"

        for filename, total_usd in expected.items():
            with self.subTest(filename=filename):
                receipt = json.loads((runs / filename).read_text(encoding="utf-8"))
                validate_contract(receipt, "agent-lab-cost-receipt.v1.json")
                request = {
                    "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
                    "pricingIdentity": receipt["pricingIdentity"],
                    "usage": receipt["usage"],
                }
                if receipt.get("runtimeCostReceipt") is not None:
                    request["runtimeCostReceipt"] = receipt["runtimeCostReceipt"]
                rebuilt = build_agent_lab_cost_receipt(request)
                self.assertEqual(rebuilt, receipt)
                self.assertEqual(receipt["estimate"]["totalCostUsd"], total_usd)
                self.assertEqual(receipt["billing"], {"status": "not_provided"})

    def test_decimal_serialization_does_not_round_a_valid_exact_cost(self) -> None:
        request = _request(
            rates=("0.12345678901234567890123456789012345678", "0", "0")
        )
        request["usage"] = {
            **request["usage"],
            "uncachedInputTokens": 999_999_999_999_999_999,
            "cachedInputTokens": 0,
            "outputTokens": 0,
        }

        receipt = build_agent_lab_cost_receipt(request)

        self.assertEqual(
            "123456789012.34567877777777887777777787876543210987654322",
            receipt["estimate"]["totalCostUsd"],
        )


if __name__ == "__main__":
    unittest.main()
