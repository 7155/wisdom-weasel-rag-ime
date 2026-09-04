from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.contracts.json_schema import ContractValidationError, validate_contract
from rag_ime.agent_lab_experiments import AgentLabExperimentStore
from rag_ime.eval_lab import EvalLabProjection

from tests.test_agent_lab_experiment_store import _experiment


class EvalLabProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-eval-lab-")
        self.db_path = Path(self.tmp.name) / "paw.sqlite"
        self.store = AgentSessionStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _snapshot(self, *, index: int, succeeded: bool, passed: int, total: int) -> str:
        session = self.store.create(
            title=f"EnterpriseOps CSM · Task {index}",
            model_profile="openai-codex/gpt-5.6-sol",
            thinking_level="high",
            tool_profile_version="subagent-readonly-v1",
            execution_mode="read_only",
            evaluation_snapshot=True,
            created_at_ms=100 + index,
        )
        session_id = str(session["id"])
        self.store.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=f"private-pi-{index}",
            transcript_ref=f"/private/machine/session-{index}.jsonl",
            binding_state="prepared",
            metadata={
                "evaluationSnapshot": {
                    "schemaVersion": "rag-ime.evaluation-snapshot.v1",
                    "runId": "enterpriseops-validation-v1",
                    "suiteId": "enterpriseops-csm",
                    "split": "validation",
                    "workflowProfile": "baseline-v1",
                    "sourceDatabaseSha256": "a" * 64,
                    "sourceReportSha256": "b" * 64,
                    "sourceTranscriptSha256": str(index) * 64,
                    "taskAlias": f"Task {index}",
                    "taskIndex": index,
                    "taskIdSha256": "c" * 64,
                    "taskSucceeded": succeeded,
                    "terminalEvent": "turn_completed",
                    "verifier": {
                        "passed": passed,
                        "total": total,
                        "passRate": passed / total,
                    },
                    "toolCalls": 4 + index,
                    "failedToolCalls": 0,
                    "latencyMs": 500.0 + index,
                }
            },
            updated_at_ms=200 + index,
        )
        self.store.set_status(session_id, "idle", updated_at_ms=300 + index)
        return session_id

    def test_groups_snapshot_sessions_into_sanitized_runs(self) -> None:
        first = self._snapshot(index=1, succeeded=True, passed=11, total=11)
        second = self._snapshot(index=2, succeeded=False, passed=3, total=5)
        ordinary = self.store.create(title="普通会话")

        payload = EvalLabProjection(self.db_path).list_runs()

        validate_contract(payload, "eval-lab-run-list.v1.json")
        self.assertEqual(payload["total"], 1)
        run = payload["items"][0]
        self.assertEqual(run["runId"], "enterpriseops-validation-v1")
        self.assertEqual(run["taskCount"], 2)
        self.assertEqual(run["taskSuccessCount"], 1)
        self.assertEqual(run["verifierPassCount"], 14)
        self.assertEqual(run["verifierCount"], 16)
        self.assertEqual(run["toolCalls"], 11)
        self.assertEqual(
            {item["sessionId"] for item in run["tasks"]},
            {first, second},
        )
        self.assertNotIn(str(ordinary["id"]), str(payload))
        self.assertNotIn("private-pi", str(payload))
        self.assertNotIn("/private/machine", str(payload))
        self.assertNotIn("taskIdSha256", str(payload))

    def test_explanation_is_strictly_validated_and_rejects_unknown_fields(self) -> None:
        self._snapshot(index=1, succeeded=True, passed=1, total=1)
        payload = EvalLabProjection(self.db_path).list_runs()
        task = payload["items"][0]["tasks"][0]
        task["explanation"] = {
            "caseId": "case-opaque",
            "businessRequest": {"normalizedText": "请更新客户案例。"},
            "agentOutcome": {"normalizedSummary": "已完成请求。"},
            "acceptance": {
                "passed": 1,
                "total": 1,
                "items": [
                    {
                        "id": "verifier-1",
                        "label": "Verifier 1",
                        "status": "pass",
                        "failureOwner": None,
                        "explanation": "验收项通过。",
                    }
                ],
            },
        }
        validate_contract(payload, "eval-lab-run-list.v1.json")

        invalid = deepcopy(payload)
        invalid["items"][0]["tasks"][0]["explanation"]["rawTranscript"] = "must not pass"
        with self.assertRaises(ContractValidationError):
            validate_contract(invalid, "eval-lab-run-list.v1.json")

    def test_includes_latest_versioned_experiments_without_manufacturing_sessions(self) -> None:
        self._snapshot(index=1, succeeded=True, passed=1, total=1)
        AgentLabExperimentStore(self.db_path).persist(_experiment())

        payload = EvalLabProjection(self.db_path).list_runs()

        validate_contract(payload, "eval-lab-run-list.v1.json")
        self.assertEqual(payload["experimentTotal"], 1)
        self.assertEqual(
            payload["experiments"][0]["experimentId"],
            "enterprise-rag.retrieval-selection.v1",
        )
        self.assertEqual(payload["experiments"][0]["evaluationKind"], "rag_retrieval")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["taskCount"], 1)

    def test_optional_source_ledger_read_through_keeps_external_db_current(self) -> None:
        ledger_path = (
            Path(__file__).resolve().parents[1]
            / "eval/interview-metrics/agent-experiments.v1.json"
        )
        payload = EvalLabProjection(
            self.db_path,
            source_ledger_path=ledger_path,
        ).list_runs()
        validate_contract(payload, "eval-lab-run-list.v1.json")
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["experimentTotal"], len(ledger["experiments"]))
        experiment_ids = {item["experimentId"] for item in payload["experiments"]}
        self.assertIn("agent-lab.model-cost.luna-max-validation.v1", experiment_ids)
        self.assertIn("trace-agent.closed-loop-historical-replay.v1", experiment_ids)

    def test_projects_optimal_path_receipt_without_exposing_raw_evidence(self) -> None:
        payload = EvalLabProjection(
            self.db_path,
            source_ledger_path=Path(__file__).resolve().parents[1]
            / "eval/interview-metrics/agent-experiments.v1.json",
        ).list_runs()
        validate_contract(payload, "eval-lab-run-list.v1.json")
        self.assertEqual(payload["pathSearchTotal"], 4)
        search = payload["pathSearches"][0]
        self.assertEqual(
            search["selectedNodeId"], "cloudops-luna-owner-mechanism-r5"
        )
        self.assertEqual(search["claimStatus"], "best_known")
        self.assertEqual(len(search["candidates"]), 3)
        self.assertEqual(search["candidates"][0]["changedFactor"], "baseline")
        self.assertEqual(
            search["candidates"][0]["nodeId"], "cloudops-sol-alert-first-r7"
        )
        self.assertEqual(search["candidates"][1]["status"], "rejected")
        self.assertEqual(
            search["candidates"][1]["nodeId"],
            "cloudops-luna-model-only-r1",
        )
        self.assertEqual(search["candidates"][2]["status"], "eligible")
        self.assertEqual(
            search["candidates"][2]["nodeId"], search["selectedNodeId"]
        )
        self.assertIn("质量与可靠性硬门失败", search["candidates"][1]["reason"])
        enterprise = payload["pathSearches"][1]
        self.assertEqual(
            enterprise["selectedNodeId"], "enterpriseops-luna-prompt-r7"
        )
        self.assertEqual(enterprise["claimStatus"], "best_known")
        previous = payload["pathSearches"][2]
        self.assertEqual(previous["selectedNodeId"], "sol-max-controlled-20260903")
        self.assertEqual(previous["claimStatus"], "insufficient_evidence")
        historical = payload["pathSearches"][3]
        self.assertEqual(historical["selectedNodeId"], "sol-state-contract")
        self.assertEqual(historical["claimStatus"], "best_known")
        self.assertNotIn("evidenceRefs", str(search))


if __name__ == "__main__":
    unittest.main()
