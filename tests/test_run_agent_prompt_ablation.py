from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_agent_prompt_ablation.py"
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "agent_prompt_ablation"
    / "managed-work-ablation.v1.json"
)
SPEC = importlib.util.spec_from_file_location(
    "run_agent_prompt_ablation",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _provider_observation(
    *,
    scenario_id: str,
    variant: str = "A",
    run_index: int = 1,
    run_ordinal: int | None = None,
    output_tokens: int = 12,
) -> dict[str, object]:
    fixture = RUNNER.load_fixture(FIXTURE)
    scenario = RUNNER._scenario_map(fixture)[scenario_id]
    variant_metrics = RUNNER._variant(fixture, variant)["metrics"]
    fixed_layers_sha = "f" * 64
    compiled_prompt_sha = RUNNER._sha256_json(
        {
            "fixedLayersSha256": fixed_layers_sha,
            "managedWorkLayerSha256": variant_metrics["sha256"],
        }
    )
    with tempfile.TemporaryDirectory() as raw:
        workspace_hash = RUNNER._materialize_workspace(
            scenario,
            Path(raw),
        )
    started_at_ms = 1_785_196_800_000
    tool_trace = [
        {
            "sequence": index,
            "toolCallId": f"call-{index}",
            "tool": item["tool"],
            "operation": item["operation"],
            "arguments": item["arguments"],
            "result": {"ok": True},
            "startedAtMs": started_at_ms + 10 * index,
            "finishedAtMs": started_at_ms + 10 * index + 2,
            "rawEvents": [
                {"type": "tool_started"},
                {"type": "tool_finished"},
            ],
        }
        for index, item in enumerate(
            RUNNER._expected_tool_projection(scenario),
            start=1,
        )
    ]
    return {
        "schemaVersion": RUNNER.OBSERVATION_SCHEMA_VERSION,
        "scenarioId": scenario_id,
        "variant": variant,
        "runOrdinal": run_ordinal or run_index,
        "model": "gpt-test",
        "reasoningEffort": "medium",
        "runIndex": run_index,
        "startedAt": RUNNER._iso_utc(started_at_ms),
        "firstActionLatencyMs": 37,
        "timingReceipt": {
            "startedAtMs": started_at_ms,
            "firstActionAtMs": started_at_ms + 37,
        },
        "toolTrace": tool_trace,
        "output": "fixture output",
        "assertions": [
            {
                "id": f"acceptance-{index}",
                "passed": True,
                "evidence": text,
            }
            for index, text in enumerate(
                scenario["acceptanceEvidence"],
                start=1,
            )
        ],
        "metrics": {
            "forbiddenBehaviorCount": 0,
            "outputTokens": output_tokens,
            "systemPromptTokens": variant_metrics["estimatedTokens"],
            "roomPingPongTurns": 0,
        },
        "providerReceipt": {
            "invoked": True,
            "source": "product_session_events",
            "acceptance": {
                "accepted": True,
                "turnId": f"turn-{run_index}",
                "systemPromptSha256": compiled_prompt_sha,
            },
            "completion": {
                "event": "message_completed",
                "usage": {
                    "input": 200,
                    "output": output_tokens,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 200 + output_tokens,
                },
            },
        },
        "promptReceipt": {
            "invoked": True,
            "managedWorkLayerSha256": variant_metrics["sha256"],
            "fixedLayersSha256": fixed_layers_sha,
            "compiledSystemPromptSha256": compiled_prompt_sha,
            "estimatedManagedWorkTokens": variant_metrics["estimatedTokens"],
        },
        "isolationReceipt": {
            "stateScope": "fresh-subprocess-session-context-epoch",
            "processId": 10_000 + run_index,
            "sessionId": f"session-{variant}-{run_index}",
            "contextEpoch": 1,
            "workspaceStateSha256": workspace_hash,
        },
    }


def _kernel_observation(
    *,
    variant: str = "K",
) -> dict[str, object]:
    fixture = RUNNER.load_fixture(FIXTURE)
    scenario_id = "room.cancelled-generation-rejects-late-write"
    scenario = RUNNER._scenario_map(fixture)[scenario_id]
    with tempfile.TemporaryDirectory() as raw:
        workspace_hash = RUNNER._materialize_workspace(
            scenario,
            Path(raw),
        )
    started_at_ms = 1_785_196_800_000
    return {
        "schemaVersion": RUNNER.OBSERVATION_SCHEMA_VERSION,
        "scenarioId": scenario_id,
        "variant": variant,
        "runOrdinal": 1,
        "model": "not-invoked",
        "reasoningEffort": "not-invoked",
        "runIndex": 1,
        "startedAt": RUNNER._iso_utc(started_at_ms),
        "firstActionLatencyMs": 0,
        "timingReceipt": {
            "startedAtMs": started_at_ms,
            "firstActionAtMs": started_at_ms,
        },
        "toolTrace": [],
        "output": "",
        "assertions": [
            {
                "id": f"acceptance-{index}",
                "passed": True,
                "evidence": text,
            }
            for index, text in enumerate(
                scenario["acceptanceEvidence"],
                start=1,
            )
        ],
        "metrics": {
            "forbiddenBehaviorCount": 0,
            "outputTokens": 0,
            "systemPromptTokens": 0,
            "roomPingPongTurns": 0,
        },
        "providerReceipt": {
            "invoked": False,
            "source": "kernel_pre_dispatch",
            "reason": "cancel generation fence rejected the late result before any follow-up Provider dispatch",
        },
        "promptReceipt": {
            "invoked": False,
            "reason": "kernel_pre_dispatch",
        },
        "isolationReceipt": {
            "stateScope": "fresh-subprocess-session-context-epoch",
            "processId": 20_000,
            "workspaceStateSha256": workspace_hash,
        },
    }


class PromptAblationRunnerTests(unittest.TestCase):
    def test_dry_run_is_balanced_isolated_and_explicitly_not_provider_run(
        self,
    ) -> None:
        report = RUNNER.build_dry_run_plan(
            FIXTURE,
            runs_per_variant=1,
            scenario_ids=[
                "session.authorized-action-produces-evidence",
                "room.cancelled-generation-rejects-late-write",
            ],
        )

        self.assertEqual(report["status"], "designed-not-provider-run")
        self.assertEqual(len(report["plannedRuns"]), 3)
        self.assertEqual(len(report["aggregateTemplates"]), 3)
        self.assertEqual(report["perRun"], [])
        self.assertEqual(report["aggregate"], [])
        fixture = RUNNER.load_fixture(FIXTURE)
        required = set(fixture["reportSchema"]["perRunRequired"])
        for record in report["plannedRuns"]:
            with self.subTest(
                scenario=record["scenarioId"],
                variant=record["variant"],
            ):
                self.assertLessEqual(required, record.keys())
                self.assertEqual(record["status"], "planned-not-run")
                self.assertFalse(record["providerReceipt"]["invoked"])
                self.assertNotEqual(
                    record["workerReceipt"]["pid"],
                    os.getpid(),
                )
                self.assertEqual(
                    record["workerReceipt"]["stateScope"],
                    "fresh-subprocess-temporary-workspace",
                )
        provider = next(
            record
            for record in report["plannedRuns"]
            if record["scenarioId"].startswith("session.authorized-action")
        )
        kernel = next(
            record
            for record in report["plannedRuns"]
            if record["scenarioId"].startswith("room.cancelled")
        )
        self.assertTrue(provider["providerReceipt"]["expected"])
        self.assertFalse(kernel["providerReceipt"]["expected"])
        self.assertEqual(kernel["variant"], "K")
        self.assertEqual(kernel["metrics"]["systemPromptTokens"], 0)
        self.assertEqual(
            kernel["providerReceipt"]["executionLayer"],
            "kernel_pre_dispatch",
        )
        for scenario_id in {
            record["scenarioId"] for record in report["plannedRuns"]
        }:
            ordered = sorted(
                (
                    record
                    for record in report["plannedRuns"]
                    if record["scenarioId"] == scenario_id
                ),
                key=lambda record: record["runOrdinal"],
            )
            actual = [record["variant"] for record in ordered]
            if scenario_id.startswith("room.cancelled"):
                self.assertEqual(actual, ["K"])
            else:
                self.assertEqual(
                    actual,
                    RUNNER._balanced_order(scenario_id, 1),
                )

    def test_observation_preserves_exact_receipts_and_aggregates_metrics(
        self,
    ) -> None:
        observation = _provider_observation(
            scenario_id="session.authorized-action-produces-evidence",
        )
        report = RUNNER.build_observed_report(
            [observation],
            FIXTURE,
            allow_partial=True,
        )

        self.assertEqual(report["status"], "observed-partial")
        self.assertEqual(len(report["perRun"]), 1)
        record = report["perRun"][0]
        self.assertEqual(
            record["providerReceipt"],
            observation["providerReceipt"],
        )
        self.assertEqual(record["toolTrace"], observation["toolTrace"])
        self.assertTrue(record["metrics"]["taskSuccess"])
        self.assertTrue(record["metrics"]["toolTraceExactMatch"])
        self.assertEqual(record["firstActionLatencyMs"], 37)
        self.assertEqual(
            record["metrics"]["toolTraceSha256"],
            RUNNER._sha256_json(observation["toolTrace"]),
        )
        aggregate = report["aggregate"][0]
        self.assertEqual(aggregate["runCount"], 1)
        self.assertEqual(aggregate["taskSuccessRate"], 1.0)
        self.assertEqual(aggregate["toolTraceExactMatchRate"], 1.0)
        self.assertEqual(aggregate["meanFirstActionLatencyMs"], 37.0)
        self.assertEqual(aggregate["meanOutputTokens"], 12.0)
        self.assertEqual(aggregate["meanSystemPromptTokens"], 549.0)

    def test_kernel_pre_dispatch_requires_no_provider_and_no_tool_trace(
        self,
    ) -> None:
        report = RUNNER.build_observed_report(
            [_kernel_observation()],
            FIXTURE,
            allow_partial=True,
        )
        record = report["perRun"][0]

        self.assertFalse(record["providerReceipt"]["invoked"])
        self.assertEqual(record["executionLayer"], "kernel_pre_dispatch")
        self.assertEqual(record["toolTrace"], [])
        self.assertEqual(report["aggregate"][0]["roomPingPongTurns"], 0)

    def test_provider_scenario_rejects_a_fabricated_skipped_receipt(
        self,
    ) -> None:
        observation = _provider_observation(
            scenario_id="session.memory-candidate-on-demand-excludes-transient-noise",
        )
        observation["providerReceipt"] = {
            "invoked": False,
            "source": "kernel_pre_dispatch",
        }

        with self.assertRaisesRegex(
            RUNNER.AblationReportError,
            "disagrees with providerInvocationExpected",
        ):
            RUNNER.build_observed_report(
                [observation],
                FIXTURE,
                allow_partial=True,
            )

    def test_provider_scenario_rejects_an_unbound_prompt_variant(self) -> None:
        observation = _provider_observation(
            scenario_id="session.authorized-action-produces-evidence",
        )
        observation["promptReceipt"]["managedWorkLayerSha256"] = "0" * 64

        with self.assertRaisesRegex(
            RUNNER.AblationReportError,
            "managed-work layer does not match",
        ):
            RUNNER.build_observed_report(
                [observation],
                FIXTURE,
                allow_partial=True,
            )

    def test_provider_scenario_rejects_prompt_not_accepted_by_provider(
        self,
    ) -> None:
        observation = _provider_observation(
            scenario_id="session.authorized-action-produces-evidence",
        )
        observation["providerReceipt"]["acceptance"][
            "systemPromptSha256"
        ] = "1" * 64

        with self.assertRaisesRegex(
            RUNNER.AblationReportError,
            "did not bind the compiled system Prompt",
        ):
            RUNNER.build_observed_report(
                [observation],
                FIXTURE,
                allow_partial=True,
            )

    def test_kernel_scenario_rejects_provider_or_tool_activity(self) -> None:
        observation = _kernel_observation()
        observation["toolTrace"] = [
            {
                "tool": "room_post",
                "operation": "post",
                "arguments": {},
            }
        ]

        with self.assertRaisesRegex(
            RUNNER.AblationReportError,
            "must have an empty toolTrace",
        ):
            RUNNER.build_observed_report(
                [observation],
                FIXTURE,
                allow_partial=True,
            )

    def test_observations_reject_model_drift_between_a_and_b(self) -> None:
        scenario_id = (
            "session.progressive-disclosure-loads-exact-skill-and-tools"
        )
        variant_a = _provider_observation(
            scenario_id=scenario_id,
            variant="A",
            run_index=1,
            run_ordinal=1,
        )
        variant_b = _provider_observation(
            scenario_id=scenario_id,
            variant="B",
            run_index=1,
            run_ordinal=2,
        )
        variant_b["model"] = "different-model"

        with self.assertRaisesRegex(
            RUNNER.AblationReportError,
            "model or reasoning effort changed",
        ):
            RUNNER.build_observed_report(
                [variant_a, variant_b],
                FIXTURE,
                allow_partial=True,
            )

    def test_cli_dry_run_writes_machine_readable_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report_path = Path(raw) / "report.json"
            exit_code = RUNNER.main(
                [
                    "--dry-run",
                    "--scenario",
                    "goal.authorized-evidence-producing-continuation",
                    "--runs-per-variant",
                    "1",
                    "--output",
                    str(report_path),
                ]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(report["plannedRuns"]), 2)
        self.assertEqual(
            {record["variant"] for record in report["plannedRuns"]},
            {"A", "B"},
        )
        self.assertTrue(
            all(
                record["providerReceipt"]["status"] == "not-run"
                for record in report["plannedRuns"]
            )
        )


if __name__ == "__main__":
    unittest.main()
