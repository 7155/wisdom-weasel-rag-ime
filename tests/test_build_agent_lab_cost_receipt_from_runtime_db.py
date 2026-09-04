from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_lab_cost import (
    AgentLabCostError,
    build_agent_lab_cost_receipt,
    content_addressed_pricing_id,
)
from scripts.build_agent_lab_cost_receipt_from_runtime_db import _pricing, main


class BuildAgentLabCostReceiptFromRuntimeDbTests(unittest.TestCase):
    def _lower_bound_request(self) -> dict[str, object]:
        pricing: dict[str, object] = {
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": {
                "uncachedInputUsd": "5",
                "cachedInputUsd": "0.5",
                "outputUsd": "30",
            },
            "publishedDate": "2026-09-01",
            "sourceUrl": "https://example.com/pricing",
            "sourceSha256": "a" * 64,
        }
        pricing["pricingId"] = content_addressed_pricing_id(pricing)
        return {
            "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
            "pricingIdentity": pricing,
            "usage": {
                "available": True,
                "uncachedInputTokens": 279_774,
                "cachedInputTokens": 4_586_112,
                "outputTokens": 35_356,
                "sourceRef": "public-report:cloudops-sol-baseline",
                "sourceSha256": "b" * 64,
            },
            "pricingLowerBound": {
                "sourceSha256": "a" * 64,
                "tiers": [
                    {
                        "inputTokensAbove": 272_000,
                        "rates": {
                            "uncachedInputUsd": "10",
                            "cachedInputUsd": "1",
                            "outputUsd": "45",
                        },
                    }
                ],
            },
        }

    def _runtime_fixture(
        self,
        root: Path,
        *,
        name: str,
        provider: str,
        model: str,
        rates: tuple[float, float, float],
    ) -> Path:
        transcript = root / f"{name}.jsonl"
        usage = {
            "input": 1_000,
            "cacheRead": 2_000,
            "cacheWrite": 0,
            "output": 500,
        }
        costs = {
            "input": usage["input"] * rates[0] / 1_000_000,
            "cacheRead": usage["cacheRead"] * rates[1] / 1_000_000,
            "cacheWrite": 0,
            "output": usage["output"] * rates[2] / 1_000_000,
        }
        costs["total"] = sum(costs.values())
        transcript.write_text(
            json.dumps({"type": "session", "id": name}, sort_keys=True)
            + "\n"
            + json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "provider": provider,
                        "model": model,
                        "usage": {**usage, "cost": costs},
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        database = root / f"{name}.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "CREATE TABLE agent_sessions (model_profile TEXT, session_file TEXT)"
            )
            connection.execute(
                "INSERT INTO agent_sessions VALUES (?, ?)",
                (f"{provider}/{model}", str(transcript)),
            )
            connection.execute(
                "CREATE TABLE agent_runtime_events (event_type TEXT, metrics_json TEXT)"
            )
            connection.execute(
                "INSERT INTO agent_runtime_events VALUES (?, ?)",
                (
                    "provider_request_completed",
                    json.dumps({"usage": {**usage, "totalTokens": 3_500}}),
                ),
            )
            connection.commit()
        return database

    def _pricing_fixture(
        self,
        root: Path,
        *,
        name: str,
        provider: str,
        model: str,
        rates: tuple[float, float, float],
    ) -> Path:
        path = root / f"{name}-pricing.json"
        path.write_text(
            json.dumps(
                {
                    "gpt": {
                        "models": [
                            {
                                "id": model,
                                "provider": provider,
                                "cost": {
                                    "input": rates[0],
                                    "cacheRead": rates[1],
                                    "cacheWrite": 0,
                                    "output": rates[2],
                                },
                            }
                        ]
                    }
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def _build(
        self,
        root: Path,
        *,
        name: str,
        provider: str = "openai-codex",
        model: str = "gpt-5.6-luna",
        rates: tuple[float, float, float],
    ) -> dict[str, object]:
        database = self._runtime_fixture(
            root,
            name=name,
            provider=provider,
            model=model,
            rates=rates,
        )
        pricing = self._pricing_fixture(
            root,
            name=name,
            provider=provider,
            model=model,
            rates=rates,
        )
        output = root / f"{name}-receipt.json"
        result = main(
            [
                "--runtime-db",
                str(database),
                "--pricing-config",
                str(pricing),
                "--model",
                model,
                "--run-id",
                name,
                "--published-date",
                "2026-09-01",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(0, result)
        return json.loads(output.read_text(encoding="utf-8"))

    def test_pricing_id_is_content_addressed_and_cannot_alias_different_runtime_rates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-cost-") as tmp:
            root = Path(tmp)
            discounted = self._build(
                root,
                name="discounted",
                rates=(0.2, 0.02, 1.2),
            )
            public_api = self._build(
                root,
                name="public-api",
                rates=(1, 0.1, 6),
            )

        discounted_id = discounted["pricingIdentity"]["pricingId"]
        public_api_id = public_api["pricingIdentity"]["pricingId"]
        self.assertRegex(discounted_id, r"^pricing:sha256:[a-f0-9]{64}$")
        self.assertRegex(public_api_id, r"^pricing:sha256:[a-f0-9]{64}$")
        self.assertNotEqual(discounted_id, public_api_id)

    def test_runtime_reconciled_receipt_rejects_a_non_content_addressed_pricing_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-identity-") as tmp:
            receipt = self._build(
                Path(tmp),
                name="runtime-identity",
                rates=(0.2, 0.02, 1.2),
            )

        request = {
            "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
            "pricingIdentity": {
                **receipt["pricingIdentity"],
                "pricingId": "openai-codex-api-gpt-5.6-luna-2026-09-01",
            },
            "usage": receipt["usage"],
            "runtimeCostReceipt": receipt["runtimeCostReceipt"],
        }
        with self.assertRaisesRegex(AgentLabCostError, "content-addressed"):
            build_agent_lab_cost_receipt(request)

    def test_monotonic_tiers_make_an_aggregate_base_estimate_a_lower_bound(
        self,
    ) -> None:
        request = self._lower_bound_request()

        receipt = build_agent_lab_cost_receipt(request)

        self.assertEqual("pricing_lower_bound", receipt["authority"])
        self.assertEqual(request["pricingLowerBound"], receipt["pricingLowerBound"])
        self.assertIn("lower bound", receipt["boundaries"][0])
        self.assertEqual("4.752606", receipt["estimate"]["totalCostUsd"])

    def test_lower_bound_rejects_any_tier_rate_below_the_base_rate(self) -> None:
        request = self._lower_bound_request()
        request["pricingLowerBound"]["tiers"][0]["rates"]["outputUsd"] = "29"

        with self.assertRaisesRegex(AgentLabCostError, "must not decrease"):
            build_agent_lab_cost_receipt(request)

    def test_runtime_provider_must_match_the_hashed_pricing_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-provider-") as tmp:
            root = Path(tmp)
            database = self._runtime_fixture(
                root,
                name="provider-mismatch",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            pricing = self._pricing_fixture(
                root,
                name="provider-mismatch",
                provider="openai",
                model="gpt-5.6-luna",
                rates=(1, 0.1, 6),
            )
            with self.assertRaisesRegex(SystemExit, "runtime provider.*pricing source"):
                main(
                    [
                        "--runtime-db", str(database),
                        "--pricing-config", str(pricing),
                        "--model", "gpt-5.6-luna",
                        "--run-id", "provider-mismatch",
                        "--published-date", "2026-09-01",
                        "--output", str(root / "receipt.json"),
                    ]
                )

    def test_runtime_reported_cost_must_match_the_hashed_pricing_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-cost-mismatch-") as tmp:
            root = Path(tmp)
            database = self._runtime_fixture(
                root,
                name="cost-mismatch",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            pricing = self._pricing_fixture(
                root,
                name="cost-mismatch",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(1, 0.1, 6),
            )
            with self.assertRaisesRegex(SystemExit, "Runtime cost receipt.*pricing source"):
                main(
                    [
                        "--runtime-db", str(database),
                        "--pricing-config", str(pricing),
                        "--model", "gpt-5.6-luna",
                        "--run-id", "cost-mismatch",
                        "--published-date", "2026-09-01",
                        "--output", str(root / "receipt.json"),
                    ]
                )

    def test_bundled_runtime_catalog_preserves_provider_base_rates_and_tiers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-catalog-") as tmp:
            path = Path(tmp) / "openai-codex.json"
            path.write_text(
                json.dumps(
                    {
                        "openai-codex-responses": {
                            "gpt-5.6-luna": {
                                "id": "gpt-5.6-luna",
                                "provider": "openai-codex",
                                "cost": {
                                    "input": 0.2,
                                    "cacheRead": 0.02,
                                    "cacheWrite": 0.25,
                                    "output": 1.2,
                                    "tiers": [
                                        {
                                            "inputTokensAbove": 272_000,
                                            "input": 0.4,
                                            "cacheRead": 0.04,
                                            "cacheWrite": 0.5,
                                            "output": 1.8,
                                        }
                                    ],
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            pricing = _pricing(path, "gpt-5.6-luna")

        self.assertEqual("openai-codex", pricing["provider"])
        self.assertEqual(
            {
                "uncachedInputUsd": "0.2",
                "cachedInputUsd": "0.02",
                "outputUsd": "1.2",
            },
            pricing["rates"],
        )
        self.assertEqual(272_000, pricing["tiers"][0]["inputTokensAbove"])
        self.assertEqual("0.4", pricing["tiers"][0]["rates"]["uncachedInputUsd"])

    def test_exact_per_request_cost_receipts_override_a_divergent_db_aggregate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-runtime-exact-") as tmp:
            root = Path(tmp)
            database = self._runtime_fixture(
                root,
                name="exact-runtime",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE agent_runtime_events SET metrics_json = ?",
                    (
                        json.dumps(
                            {
                                "usage": {
                                    "input": 1_123,
                                    "cacheRead": 2_456,
                                    "cacheWrite": 0,
                                    "output": 578,
                                    "totalTokens": 4_157,
                                }
                            }
                        ),
                    ),
                )
                connection.commit()
            pricing = self._pricing_fixture(
                root,
                name="exact-runtime",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            output = root / "receipt.json"

            result = main(
                [
                    "--runtime-db", str(database),
                    "--pricing-config", str(pricing),
                    "--model", "gpt-5.6-luna",
                    "--run-id", "exact-runtime",
                    "--published-date", "2026-09-01",
                    "--output", str(output),
                ]
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual("runtime_cost_reconciled", receipt["authority"])
        self.assertEqual(
            {
                "available": True,
                "uncachedInputTokens": 1_000,
                "cachedInputTokens": 2_000,
                "outputTokens": 500,
                "sourceRef": "runtime-cost:exact-runtime",
                "sourceSha256": receipt["runtimeCostReceipt"]["sourceSha256"],
            },
            receipt["usage"],
        )
        runtime_receipt = dict(receipt["runtimeCostReceipt"])
        source_sha256 = runtime_receipt.pop("sourceSha256")
        canonical = json.dumps(
            runtime_receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            source_sha256,
        )
        self.assertEqual(
            {
                "uncachedInputTokens": 1_123,
                "cachedInputTokens": 2_456,
                "outputTokens": 578,
            },
            runtime_receipt["databaseUsage"],
        )
        self.assertEqual("0.00084", runtime_receipt["reportedCostUsd"]["total"])

    def test_trial_aggregate_is_preserved_without_overriding_exact_request_costs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-trial-aggregate-") as tmp:
            root = Path(tmp)
            database = self._runtime_fixture(
                root,
                name="luna-model-only-r1",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            pricing = self._pricing_fixture(
                root,
                name="luna-model-only-r1",
                provider="openai-codex",
                model="gpt-5.6-luna",
                rates=(0.2, 0.02, 1.2),
            )
            trial_artifact = root / "cloudops_eval.jsonl"
            trial_artifact.write_text(
                json.dumps(
                    {
                        "eventType": "trial_completed",
                        "payload": {
                            "trialId": "luna-model-only-r1",
                            "usage": {
                                "available": True,
                                "input": 1_123,
                                "cacheRead": 2_456,
                                "cacheWrite": 0,
                                "output": 578,
                                "totalTokens": 4_157,
                            },
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            trial_artifact_sha256 = hashlib.sha256(
                trial_artifact.read_bytes()
            ).hexdigest()
            output = root / "receipt.json"

            result = main(
                [
                    "--runtime-db", str(database),
                    "--pricing-config", str(pricing),
                    "--model", "gpt-5.6-luna",
                    "--run-id", "luna-model-only-r1",
                    "--published-date", "2026-09-01",
                    "--trial-artifact", str(trial_artifact),
                    "--output", str(output),
                ]
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual(1_000, receipt["usage"]["uncachedInputTokens"])
        self.assertEqual("0.00084", receipt["estimate"]["totalCostUsd"])
        self.assertEqual(
            {
                "sourceRef": "agent-artifact:luna-model-only-r1:trial_completed",
                "sourceSha256": trial_artifact_sha256,
                "uncachedInputTokens": 1_123,
                "cachedInputTokens": 2_456,
                "outputTokens": 578,
            },
            receipt["runtimeCostReceipt"]["trialAggregate"],
        )

    def test_staged_runs_keep_causal_run_binding_separate_from_pricing_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-stages-") as tmp:
            root = Path(tmp)
            sol = build_agent_lab_cost_receipt(self._lower_bound_request())
            luna_model_only = self._build(
                root,
                name="cloudops-luna-model-only",
                rates=(0.2, 0.02, 1.2),
            )
            luna_prompt_adapted = self._build(
                root,
                name="cloudops-luna-prompt-adapted",
                rates=(0.2, 0.02, 1.2),
            )

        self.assertNotEqual(
            sol["pricingIdentity"]["pricingId"],
            luna_model_only["pricingIdentity"]["pricingId"],
        )
        self.assertEqual(
            luna_model_only["pricingIdentity"]["pricingId"],
            luna_prompt_adapted["pricingIdentity"]["pricingId"],
        )
        self.assertEqual(
            "runtime-cost:cloudops-luna-model-only",
            luna_model_only["usage"]["sourceRef"],
        )
        self.assertEqual(
            "runtime-cost:cloudops-luna-prompt-adapted",
            luna_prompt_adapted["usage"]["sourceRef"],
        )
        self.assertNotEqual(
            luna_model_only["runtimeCostReceipt"]["sourceSha256"],
            luna_prompt_adapted["runtimeCostReceipt"]["sourceSha256"],
        )
        self.assertEqual("pricing_lower_bound", sol["authority"])
        self.assertEqual("runtime_cost_reconciled", luna_model_only["authority"])
        self.assertEqual("runtime_cost_reconciled", luna_prompt_adapted["authority"])
        for receipt in (sol, luna_model_only, luna_prompt_adapted):
            self.assertNotIn("savingsUsd", receipt)


if __name__ == "__main__":
    unittest.main()
