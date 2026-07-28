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

    def test_matrix_covers_five_agent_two_goal_and_two_room_scenarios(self) -> None:
        scenarios = self.matrix["scenarios"]
        by_surface = {
            surface: [item for item in scenarios if item["surface"] == surface]
            for surface in ("single_agent", "goal", "room")
        }

        self.assertEqual(len(by_surface["single_agent"]), 5)
        self.assertEqual(len(by_surface["goal"]), 2)
        self.assertEqual(len(by_surface["room"]), 2)
        self.assertEqual(
            {item["id"] for item in scenarios},
            {
                "single-agent.project-summary-five-lines",
                "single-agent.readme-typo-minimal-change",
                "single-agent.date-environment-injection",
                "single-agent.commit-checks-git-boundary",
                "single-agent.event-loop-explanation-no-files",
                "goal.authorized-evidence-producing-continuation",
                "goal.no-progress-stops-with-blocked-proposal",
                "room.child-returned-is-not-parent-accepted",
                "room.notice-does-not-create-polite-ping-pong",
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

    def test_no_tool_explanation_and_room_interaction_invariants_are_explicit(self) -> None:
        scenarios = {item["id"]: item for item in self.matrix["scenarios"]}
        explanation = scenarios["single-agent.event-loop-explanation-no-files"]
        returned = scenarios["room.child-returned-is-not-parent-accepted"]
        no_ping_pong = scenarios["room.notice-does-not-create-polite-ping-pong"]

        self.assertEqual(explanation["allowedTools"], [])
        self.assertEqual(explanation["expectedCalls"], [])
        self.assertNotIn(
            "room_commit",
            [call["tool"] for call in returned["expectedCalls"]],
        )
        self.assertTrue(
            any(
                "returned" in behavior and "parentAccepted" in behavior
                for behavior in returned["forbiddenBehavior"]
            )
        )
        self.assertEqual(no_ping_pong["expectedCalls"], [])
        self.assertEqual(no_ping_pong["executionLayer"], "kernel_pre_dispatch")
        self.assertFalse(no_ping_pong["providerInvocationExpected"])
        self.assertTrue(
            all(
                scenario["providerInvocationExpected"]
                for scenario in scenarios.values()
                if scenario is not no_ping_pong
            )
        )
        self.assertTrue(
            any(
                metric["name"] == "room_ping_pong_turns"
                and metric["target"] == "0"
                for metric in no_ping_pong["metrics"]
            )
        )

    def test_report_schema_is_sufficient_for_paired_provider_runs(self) -> None:
        report = self.matrix["reportSchema"]
        self.assertIn("toolTrace", report["perRunRequired"])
        self.assertIn("providerReceipt", report["perRunRequired"])
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


if __name__ == "__main__":
    unittest.main()
