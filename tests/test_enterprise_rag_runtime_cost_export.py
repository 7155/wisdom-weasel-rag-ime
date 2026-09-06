from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_agent_lab_cost_receipt_from_runtime_db import _pricing
from scripts.run_rag_agent_ablation import main


ROOT = Path(__file__).resolve().parents[1]
PRICING = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "openai-codex-runtime-pricing-20260904.v1.json"
)


class EnterpriseRagRuntimeCostExportTests(unittest.TestCase):
    def test_frozen_pricing_contains_only_the_two_openai_codex_models(self) -> None:
        raw = json.loads(PRICING.read_text(encoding="utf-8"))
        models = raw["gpt"]["models"]

        self.assertEqual(
            ["gpt-5.6-luna", "gpt-5.6-sol"],
            [item["id"] for item in models],
        )
        self.assertEqual(
            {"openai-codex"},
            {item["provider"] for item in models},
        )
        self.assertNotIn("x1top", json.dumps(raw, sort_keys=True))
        self.assertEqual(
            {
                "uncachedInputUsd": "0.2",
                "cachedInputUsd": "0.02",
                "outputUsd": "1.2",
            },
            _pricing(PRICING, "gpt-5.6-luna")["rates"],
        )
        self.assertEqual(
            {
                "uncachedInputUsd": "5",
                "cachedInputUsd": "0.5",
                "outputUsd": "30",
            },
            _pricing(PRICING, "gpt-5.6-sol")["rates"],
        )

    def test_selected_model_is_frozen_into_run_and_exact_cost_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-cost-export-") as temporary:
            root = Path(temporary)
            prepared = root / "prepared.json"
            retrieval = root / "retrieval.json"
            pricing = root / "pricing.json"
            source_config = root / "source-config"
            runtime = root / "runtime"
            private_root = root / "private"
            output = root / "report.json"
            cost_output = root / "cost.json"
            for path in (prepared, retrieval, pricing):
                path.write_text("{}\n", encoding="utf-8")
            source_config.mkdir()
            runtime.mkdir()

            observed: dict[str, object] = {}

            def fake_run(run_root: Path, **kwargs: object) -> dict[str, object]:
                (run_root / "agent.sqlite").write_bytes(b"runtime-db")
                observed["evaluation_model"] = kwargs.get("evaluation_model")
                return {"passed": True, "reportSha256": "a" * 64}

            def fake_cost_main(argv: list[str]) -> int:
                all_models = "--all-models" in argv
                valued = [argument for argument in argv if argument != "--all-models"]
                arguments = dict(zip(valued[::2], valued[1::2], strict=True))
                observed["all_models"] = all_models
                runtime_db = Path(arguments["--runtime-db"])
                self.assertTrue(runtime_db.is_file())
                observed.update(arguments)
                Path(arguments["--output"]).write_text(
                    json.dumps({"authority": "runtime_cost_reconciled"}) + "\n",
                    encoding="utf-8",
                )
                return 0

            with patch("scripts.run_rag_agent_ablation._run", side_effect=fake_run), patch(
                "scripts.build_agent_lab_cost_receipt_from_runtime_db.main",
                side_effect=fake_cost_main,
            ):
                result = main(
                    [
                        "--prepared",
                        str(prepared),
                        "--retrieval-report",
                        str(retrieval),
                        "--output",
                        str(output),
                        "--private-root",
                        str(private_root),
                        "--source-agent-config",
                        str(source_config),
                        "--pi-runtime-payload",
                        str(runtime),
                        "--cost-receipt-output",
                        str(cost_output),
                        "--pricing-config",
                        str(pricing),
                        "--pricing-published-date",
                        "2026-09-04",
                        "--cost-run-id",
                        "matched-stage-1",
                        "--model-override",
                        "gpt-5.6-luna",
                    ]
                )

            self.assertEqual(0, result)
            self.assertEqual("gpt-5.6-luna", observed["evaluation_model"])
            # The default Judge remains Sol; the receipt must include its
            # cost together with the selected Luna candidate's cost.
            self.assertTrue(observed["all_models"])
            self.assertNotIn("--model", observed)
            self.assertEqual("matched-stage-1", observed["--run-id"])
            self.assertEqual(str(pricing.resolve()), observed["--pricing-config"])
            self.assertEqual(str(cost_output.resolve()), observed["--output"])
            self.assertEqual(
                "runtime_cost_reconciled",
                json.loads(cost_output.read_text(encoding="utf-8"))["authority"],
            )

    def test_preflight_failure_skips_cost_export_when_runtime_db_was_never_created(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-cost-preflight-") as temporary:
            root = Path(temporary)
            prepared = root / "prepared.json"
            retrieval = root / "retrieval.json"
            pricing = root / "pricing.json"
            source_config = root / "source-config"
            runtime = root / "runtime"
            output = root / "report.json"
            cost_output = root / "cost.json"
            for path in (prepared, retrieval, pricing):
                path.write_text("{}\n", encoding="utf-8")
            source_config.mkdir()
            runtime.mkdir()

            report = {
                "passed": False,
                "reportSha256": "b" * 64,
                "preflight": {
                    "accepted": False,
                    "stage": "embedding_or_reranker_setup",
                },
            }
            with patch(
                "scripts.run_rag_agent_ablation._run",
                return_value=report,
            ), patch(
                "scripts.build_agent_lab_cost_receipt_from_runtime_db.main",
                side_effect=AssertionError("cost exporter must not run"),
            ) as cost_main:
                result = main(
                    [
                        "--prepared",
                        str(prepared),
                        "--retrieval-report",
                        str(retrieval),
                        "--output",
                        str(output),
                        "--source-agent-config",
                        str(source_config),
                        "--pi-runtime-payload",
                        str(runtime),
                        "--cost-receipt-output",
                        str(cost_output),
                        "--pricing-config",
                        str(pricing),
                        "--pricing-published-date",
                        "2026-09-04",
                    ]
                )

            self.assertEqual(1, result)
            cost_main.assert_not_called()
            self.assertTrue(output.is_file())
            self.assertFalse(cost_output.exists())

    def test_zero_provider_runtime_failure_keeps_primary_report_without_cost_export(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-cost-zero-provider-") as temporary:
            root = Path(temporary)
            prepared = root / "prepared.json"
            retrieval = root / "retrieval.json"
            pricing = root / "pricing.json"
            source_config = root / "source-config"
            runtime = root / "runtime"
            output = root / "report.json"
            cost_output = root / "cost.json"
            for path in (prepared, retrieval, pricing):
                path.write_text("{}\n", encoding="utf-8")
            source_config.mkdir()
            runtime.mkdir()

            def fake_run(run_root: Path, **_: object) -> dict[str, object]:
                (run_root / "agent.sqlite").write_bytes(b"runtime-db-without-usage")
                return {
                    "passed": False,
                    "scoreEligible": False,
                    "reportSha256": "c" * 64,
                    "completedLaneEvidence": [
                        {
                            "lane": "baseline",
                            "runtimeFailureCategory": "turn_failed",
                            "usage": {"providerRequestCount": 0},
                        }
                    ],
                }

            with patch(
                "scripts.run_rag_agent_ablation._run",
                side_effect=fake_run,
            ), patch(
                "scripts.build_agent_lab_cost_receipt_from_runtime_db.main",
                side_effect=AssertionError("cost exporter must not run"),
            ) as cost_main:
                result = main(
                    [
                        "--prepared",
                        str(prepared),
                        "--retrieval-report",
                        str(retrieval),
                        "--output",
                        str(output),
                        "--source-agent-config",
                        str(source_config),
                        "--pi-runtime-payload",
                        str(runtime),
                        "--cost-receipt-output",
                        str(cost_output),
                        "--pricing-config",
                        str(pricing),
                        "--pricing-published-date",
                        "2026-09-04",
                    ]
                )

            self.assertEqual(1, result)
            cost_main.assert_not_called()
            self.assertTrue(output.is_file())
            self.assertFalse(cost_output.exists())


if __name__ == "__main__":
    unittest.main()
