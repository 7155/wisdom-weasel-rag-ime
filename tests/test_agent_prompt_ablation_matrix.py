from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from rag_ime.agent_core_policy import managed_goal_policy_prompt


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "agent_prompt_ablation"
    / "managed-work-ablation.v1.json"
)


class AgentPromptAblationMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_variants_freeze_the_single_prompt_variable_and_current_candidate(self) -> None:
        variable = self.matrix["variable"]
        before = variable["variantA"]
        after = variable["variantB"]
        before_prompt = "\n".join(before["promptLines"])
        after_prompt = "\n".join(after["promptLines"])

        self.assertEqual(
            self.matrix["status"],
            "designed-not-provider-run",
        )
        self.assertEqual(
            self.matrix["runProtocol"]["providerRunStatus"],
            "not-run",
        )
        self.assertEqual(after_prompt, managed_goal_policy_prompt())
        self.assertEqual(
            before["metrics"]["sha256"],
            "533365ea1d4cdae5c1dabaa6b686836a1226d3d977ff4099d1d553ee06c71c2f",
        )
        for variant, prompt in ((before, before_prompt), (after, after_prompt)):
            encoded = prompt.encode("utf-8")
            metrics = variant["metrics"]
            self.assertEqual(metrics["chars"], len(prompt))
            self.assertEqual(metrics["utf8Bytes"], len(encoded))
            self.assertEqual(metrics["estimatedTokens"], (len(encoded) + 3) // 4)
            self.assertEqual(metrics["lines"], len(prompt.splitlines()))
            self.assertEqual(
                metrics["sha256"],
                hashlib.sha256(encoded).hexdigest(),
            )
        self.assertEqual(variable["reduction"]["utf8BytesSaved"], 1002)
        self.assertEqual(variable["reduction"]["estimatedTokensSaved"], 251)
        self.assertEqual(len(variable["fixedLayers"]), 9)

    def test_matrix_covers_project_native_session_goal_and_room_regressions(self) -> None:
        scenarios = self.matrix["scenarios"]
        by_surface = {
            surface: [item for item in scenarios if item["surface"] == surface]
            for surface in ("single_agent", "goal", "room")
        }

        self.assertEqual(len(by_surface["single_agent"]), 4)
        self.assertEqual(len(by_surface["goal"]), 2)
        self.assertEqual(len(by_surface["room"]), 4)
        self.assertEqual(
            {item["id"] for item in scenarios},
            {
                "session.authorized-action-produces-evidence",
                "session.progressive-disclosure-loads-exact-skill-and-tools",
                "session.memory-candidate-on-demand-excludes-transient-noise",
                "session.memory-refresh-starts-new-context-epoch",
                "goal.authorized-evidence-producing-continuation",
                "goal.stale-evidence-cannot-settle-current-revision",
                "room.child-returned-is-not-parent-accepted",
                "room.facilitator-integrates-before-optional-review",
                "room.notice-does-not-create-polite-ping-pong",
                "room.cancelled-generation-rejects-late-write",
            },
        )
        self.assertTrue(
            all(not item["setup"]["managedWork"] for item in by_surface["single_agent"])
        )
        self.assertTrue(
            all(item["setup"]["managedWork"] for item in (*by_surface["goal"], *by_surface["room"]))
        )

    def test_every_scenario_has_an_executable_trace_and_deterministic_assertions(self) -> None:
        known_tools = {
            "workspace_read",
            "workspace_search",
            "workspace_patch",
            "workspace_shell",
            "room_state",
            "room_collaborate",
            "room_post",
            "room_commit",
            "skill_search",
            "skill_load",
            "tool_search",
            "tool_load",
            "memory_capture",
        }
        required = {
            "id",
            "surface",
            "executionLayer",
            "providerInvocationExpected",
            "setup",
            "input",
            "allowedTools",
            "expectedCalls",
            "forbiddenBehavior",
            "acceptanceEvidence",
            "metrics",
        }
        for scenario in self.matrix["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(required, required & scenario.keys())
                self.assertTrue(scenario["input"].strip())
                self.assertTrue(scenario["forbiddenBehavior"])
                self.assertTrue(scenario["acceptanceEvidence"])
                self.assertTrue(scenario["metrics"])
                self.assertTrue(scenario["nativeEvidence"])
                self.assertIn(
                    scenario["executionLayer"],
                    {"provider", "kernel_pre_dispatch"},
                )
                self.assertIsInstance(
                    scenario["providerInvocationExpected"],
                    bool,
                )
                self.assertTrue(set(scenario["allowedTools"]) <= known_tools)
                orders = [
                    int(call["order"])
                    for call in scenario["expectedCalls"]
                ]
                self.assertEqual(orders, list(range(1, len(orders) + 1)))
                for call in scenario["expectedCalls"]:
                    self.assertIn(call["tool"], scenario["allowedTools"])
                    self.assertGreaterEqual(int(call["count"]), 1)
                    self.assertIsInstance(call["arguments"], dict)

    def test_provider_and_kernel_regressions_are_explicitly_separated(self) -> None:
        scenarios = {item["id"]: item for item in self.matrix["scenarios"]}
        memory_capture = scenarios[
            "session.memory-candidate-on-demand-excludes-transient-noise"
        ]
        memory_refresh = scenarios[
            "session.memory-refresh-starts-new-context-epoch"
        ]
        stale_evidence = scenarios[
            "goal.stale-evidence-cannot-settle-current-revision"
        ]
        returned = scenarios["room.child-returned-is-not-parent-accepted"]
        no_ping_pong = scenarios["room.notice-does-not-create-polite-ping-pong"]
        facilitated = scenarios[
            "room.facilitator-integrates-before-optional-review"
        ]
        late_write = scenarios["room.cancelled-generation-rejects-late-write"]

        self.assertEqual(
            [call["tool"] for call in memory_capture["expectedCalls"]],
            ["memory_capture"],
        )
        self.assertTrue(
            any(
                "Provider 超时" in behavior
                for behavior in memory_capture["forbiddenBehavior"]
            )
        )
        returned_tools = [call["tool"] for call in returned["expectedCalls"]]
        self.assertEqual(returned_tools, ["room_state"])
        self.assertNotIn("room_collaborate", returned_tools)
        self.assertNotIn("room_commit", returned_tools)
        self.assertTrue(
            any(
                "returned" in behavior and "parentAccepted" in behavior
                for behavior in returned["forbiddenBehavior"]
            )
        )
        self.assertTrue(
            any(
                "review Dispatch" in behavior
                for behavior in returned["forbiddenBehavior"]
            )
        )
        self.assertTrue(
            any(
                metric["name"] == "review_dispatch_created"
                and metric["target"] == "false"
                for metric in returned["metrics"]
            )
        )
        self.assertEqual(facilitated["expectedCalls"], [])
        self.assertEqual(facilitated["allowedTools"], [])
        self.assertEqual(facilitated["executionLayer"], "kernel_pre_dispatch")
        self.assertFalse(facilitated["providerInvocationExpected"])
        work_item = facilitated["setup"]["workItem"]
        self.assertTrue(work_item["integrated"])
        self.assertTrue(work_item["dependenciesSettled"])
        self.assertEqual(work_item["reviewWarranted"], "pending")
        self.assertTrue(work_item["reviewerDistinct"])
        self.assertEqual(
            work_item["integrationOwner"],
            facilitated["setup"]["participants"]["facilitator"],
        )
        workspace_policy = facilitated["setup"]["workspacePolicy"]
        self.assertEqual(len(workspace_policy["writableWorkerWorkspaceReceipts"]), 2)
        self.assertTrue(workspace_policy["integrationWorkspaceReceipt"])
        self.assertTrue(
            any(
                "review Dispatch" in behavior
                for behavior in facilitated["forbiddenBehavior"]
            )
        )
        self.assertTrue(
            any(
                metric["name"] == "review_before_integration_count"
                and metric["target"] == "0"
                for metric in facilitated["metrics"]
            )
        )
        self.assertTrue(
            any(
                metric["name"] == "reporter_final_summary_count"
                and metric["target"] == "1"
                for metric in facilitated["metrics"]
            )
        )
        for deterministic in (
            memory_refresh,
            stale_evidence,
            late_write,
        ):
            self.assertEqual(deterministic["expectedCalls"], [])
            self.assertEqual(
                deterministic["executionLayer"],
                "kernel_pre_dispatch",
            )
            self.assertFalse(deterministic["providerInvocationExpected"])
            self.assertTrue(deterministic["deterministicKernelPhase"])
        self.assertEqual(no_ping_pong["expectedCalls"], [])
        self.assertEqual(no_ping_pong["executionLayer"], "provider")
        self.assertTrue(no_ping_pong["providerInvocationExpected"])
        classification = self.matrix["scenarioClassification"]
        self.assertEqual(
            set(classification["providerScored"]),
            {
                scenario_id
                for scenario_id, scenario in scenarios.items()
                if scenario["providerInvocationExpected"]
            },
        )
        self.assertEqual(
            set(classification["deterministicKernel"]),
            {
                scenario_id
                for scenario_id, scenario in scenarios.items()
                if not scenario["providerInvocationExpected"]
            },
        )
        self.assertTrue(
            any(
                metric["name"] == "room_ping_pong_turns"
                and metric["target"] == "0"
                for metric in no_ping_pong["metrics"]
            )
        )
        self.assertTrue(
            any(
                metric["name"] == "late_write_applied_count"
                and metric["target"] == "0"
                for metric in late_write["metrics"]
            )
        )

    def test_alignment_documentation_is_deferred_to_irreversible_design_approval(self) -> None:
        stages = self.matrix["deferredStages"]

        self.assertEqual(len(stages), 1)
        stage = stages[0]
        self.assertEqual(
            stage["id"],
            "alignment-and-decision.durable-documentation",
        )
        self.assertEqual(stage["status"], "deferred-not-always-on")
        self.assertIn("after source investigation", stage["activation"])
        self.assertIn("high-impact irreversible", stage["activation"])
        self.assertIn(
            "as an always-on system-prompt layer",
            stage["forbiddenActivation"],
        )

    def test_report_schema_is_sufficient_for_paired_provider_runs(self) -> None:
        report = self.matrix["reportSchema"]
        self.assertIn("toolTrace", report["perRunRequired"])
        self.assertIn("providerReceipt", report["perRunRequired"])
        self.assertIn("promptReceipt", report["perRunRequired"])
        self.assertIn("taskSuccessRate", report["aggregateRequired"])
        self.assertIn("forbiddenBehaviorRate", report["aggregateRequired"])
        self.assertIn("roomPingPongTurns", report["aggregateRequired"])
        self.assertEqual(
            self.matrix["runProtocol"]["pairedRunsPerProviderScenario"],
            5,
        )
        self.assertEqual(
            self.matrix["runProtocol"]["deterministicRunsPerKernelScenario"],
            5,
        )
        self.assertIn(
            "kernel scenarios use one K track",
            self.matrix["runProtocol"]["orderPolicy"],
        )


if __name__ == "__main__":
    unittest.main()
