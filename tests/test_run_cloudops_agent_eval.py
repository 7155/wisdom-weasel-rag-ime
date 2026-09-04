from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_ime.agent_artifacts import AgentArtifactStore
from rag_ime.cloudops_benchmark_agent import CloudOpsBenchmarkGateway, CloudOpsBlindSuite
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.pi_runtime import _tools_for_session
from rag_ime.sandbox_run_store import SandboxRunStore
from rag_ime.trace_store import TraceStore
from scripts.run_cloudops_agent_eval import (
    _CloudOpsContextProjectionGateway,
    _assert_expected_runtime,
    _batch_prompt,
    _candidate_runtime_config,
    _cost_optimization_comparison,
    _normalize_trial_id,
    _numeric_usage,
    _public_host_invocation,
    _sum_usage,
    _token_usage,
    _validated_score,
    run_cloudops_agent_eval,
)
from tests.test_cloudops_benchmark_agent import _answer, _write_fixture


@dataclass
class _Event:
    event_type: str
    turn_id: str
    payload: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {"eventType": self.event_type, "turnId": self.turn_id, **self.payload}


class _Events:
    def __init__(self, owner: "_FakeAgentService") -> None:
        self.owner = owner

    def replay(self, session_id: str):
        return list(self.owner.event_rows.get(session_id, [])), False


class _FakeAgentService:
    def __init__(self, gateway: CloudOpsBenchmarkGateway) -> None:
        self.gateway = gateway
        self.events = _Events(self)
        self.created: list[str] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.lifecycle_calls: list[tuple[str, str]] = []
        self.event_rows: dict[str, list[_Event]] = {}
        self.manifest_provider = None

    def bind_tool_manifest_provider(self, provider) -> None:
        self.manifest_provider = provider

    def create_session(self, payload: dict[str, object]) -> dict[str, object]:
        session_id = f"agent:cloudops:{len(self.created) + 1}"
        self.created.append(session_id)
        self.lifecycle_calls.append(("create", session_id))
        return {"session": {"id": session_id, **payload}}

    def update_session(self, session_id: str, payload: dict[str, object]) -> None:
        self.updated.append((session_id, dict(payload)))
        self.lifecycle_calls.append(("update", session_id))

    def select_thinking_level(self, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.lifecycle_calls.append(("select", session_id))
        return {
            "ok": True,
            "sessionId": session_id,
            "thinkingLevel": payload["level"],
        }

    def ensure_runtime(self, payload: dict[str, object]) -> dict[str, object]:
        self.lifecycle_calls.append(("ensure", str(payload["sessionId"])))
        return {
            "ok": True,
            "sessionId": payload["sessionId"],
            "state": {
                "model": {"provider": "openai-codex", "id": "gpt-5.6-sol"},
                "thinkingLevel": "",
            },
        }

    def prompt(self, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.lifecycle_calls.append(("prompt", session_id))
        turn_id = f"turn:{session_id.rsplit(':', 1)[-1]}"
        indexed = self._call(session_id, turn_id, "index")["result"]
        answers = []
        for case in indexed["cases"]:
            case_id = str(case["caseId"])
            listed = self._call(session_id, turn_id, "list", caseId=case_id, limit=1)["result"]
            self._call(
                session_id,
                turn_id,
                "read",
                caseId=case_id,
                cacheKey=listed["items"][0]["cacheKey"],
            )
            answers.append(_answer(case_id))
        self._call(session_id, turn_id, "submit", answers=answers)
        self.event_rows[session_id] = [
            _Event("turn_started", turn_id, {"createdAtMs": 100}),
            _Event(
                "turn_completed",
                turn_id,
                {"createdAtMs": 200, "usage": {"input": 10, "output": 5, "totalTokens": 15}},
            ),
        ]
        return {"ok": True, "turnId": turn_id}

    def abort(self, session_id: str) -> None:
        raise AssertionError(f"unexpected abort: {session_id}")

    def _call(self, session_id: str, turn_id: str, operation: str, **args: object):
        return self.gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session_id,
                "tool": "cloudops_benchmark",
                "toolCallId": f"tool:{session_id}:{operation}:{len(self.gateway.ledger(session_id=session_id)['items'])}",
                "sourceLoopId": turn_id,
                "args": {"op": operation, **args},
            }
        )


class _NoSubmissionService(_FakeAgentService):
    def prompt(self, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        turn_id = "turn:no-submit"
        self.event_rows[session_id] = [_Event("turn_completed", turn_id, {"createdAtMs": 200})]
        return {"ok": True, "turnId": turn_id}


class RunCloudOpsAgentEvalTests(unittest.TestCase):
    def test_observation_id_projection_changes_only_public_tool_addressing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloudops-projection-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 5)]
            _write_fixture(root, case_ids)
            suite = CloudOpsBlindSuite(
                root / "blind",
                batches={"batch-1": case_ids},
            )
            gateway = _CloudOpsContextProjectionGateway(
                CloudOpsBenchmarkGateway(suite, max_reads_per_case=4),
                context_projection="observation-id-v1",
            )
            gateway.bind_session(
                "session-1",
                batch_id="batch-1",
                workflow_profile="baseline-v1",
            )

            manifest = gateway.runtime_manifests({"id": "session-1"})[0]
            read_schema = next(
                item
                for item in manifest["parameters"]["oneOf"]
                if item["properties"]["op"]["const"] == "read"
            )
            self.assertIn("observationId", read_schema["required"])
            self.assertNotIn("cacheKey", read_schema["properties"])

            listed = gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": "session-1",
                    "tool": "cloudops_benchmark",
                    "toolCallId": "tool:list:1",
                    "sourceLoopId": "turn:1",
                    "args": {"op": "list", "caseId": case_ids[0], "limit": 1},
                }
            )["result"]
            descriptor = listed["items"][0]
            self.assertNotIn("cacheKey", descriptor)
            self.assertRegex(descriptor["observationId"], r"^obs_[0-9a-f]{24}$")

            read = gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": "session-1",
                    "tool": "cloudops_benchmark",
                    "toolCallId": "tool:read:1",
                    "sourceLoopId": "turn:1",
                    "args": {
                        "op": "read",
                        "caseId": case_ids[0],
                        "observationId": descriptor["observationId"],
                    },
                }
            )["result"]
            self.assertEqual("pod restarted twice", read["observation"])
            self.assertNotIn("cacheKey", read)
            self.assertGreater(
                gateway.projection_summary()["sourceChars"],
                gateway.projection_summary()["projectedChars"],
            )
            self.assertEqual(
                _batch_prompt("batch-1", tuple(case_ids), workflow_profile="baseline-v1"),
                _batch_prompt("batch-1", tuple(case_ids), workflow_profile="baseline-v1"),
            )

    def test_cost_comparison_requires_same_quality_and_three_nonincreasing_categories(self) -> None:
        baseline = {
            "suiteSha256": "a" * 64,
            "contractSha256": "b" * 64,
            "batchPlanSha256": "c" * 64,
            "caseCount": 12,
            "workflowProfile": "baseline-v1",
            "thinkingLevel": "max",
            "contextProjection": "standard-v1",
            "runtimeIdentity": {
                "runtimeVersion": "runtime-1",
                "piVersion": "0.84.2",
                "protocolVersion": "v2",
                "manifestSha256": "d" * 64,
                "entrypointSha256": "e" * 64,
                "nodeSha256": "f" * 64,
                "extensionSha256": "1" * 64,
                "provider": "openai-codex",
                "model": "gpt-5.6-sol",
            },
            "metrics": {"AnswerCoverage": 1.0, "CA": 1.0, "FA": 0.8333, "JRA": 0.8333, "Top3JRA": 0.8333},
            "usage": {"available": True, "input": 100, "cacheRead": 50, "output": 30, "cacheWrite": 0, "totalTokens": 180},
        }
        candidate = {
            **baseline,
            "contextProjection": "observation-id-v1",
            "usage": {"available": True, "input": 90, "cacheRead": 50, "output": 29, "cacheWrite": 0, "totalTokens": 169},
        }

        comparison = _cost_optimization_comparison(baseline, candidate)

        self.assertEqual("keep", comparison["decision"])
        self.assertTrue(comparison["qualityGatePassed"])
        self.assertTrue(comparison["costGatePassed"])
        no_factor = {
            **candidate,
            "contextProjection": "standard-v1",
        }
        self.assertEqual(
            "reject",
            _cost_optimization_comparison(baseline, no_factor)["decision"],
        )
        workflow_candidate = {
            **baseline,
            "workflowProfile": "quality-bounded-v3",
            "usage": {"available": True, "input": 80, "cacheRead": 40, "output": 20},
        }
        workflow_comparison = _cost_optimization_comparison(
            baseline,
            workflow_candidate,
        )
        self.assertEqual("keep", workflow_comparison["decision"])
        self.assertEqual("bounded_diagnostic_prompt_contract", workflow_comparison["singleVariable"])
        alert_first_candidate = {
            **baseline,
            "workflowProfile": "alert-first-v5",
            "usage": {"available": True, "input": 80, "cacheRead": 40, "output": 20},
        }
        self.assertEqual(
            "keep",
            _cost_optimization_comparison(baseline, alert_first_candidate)["decision"],
        )
        two_factor_candidate = {
            **workflow_candidate,
            "contextProjection": "observation-id-v1",
        }
        self.assertEqual(
            "reject",
            _cost_optimization_comparison(baseline, two_factor_candidate)["decision"],
        )
        regressed = {**candidate, "usage": {**candidate["usage"], "output": 31}}
        self.assertEqual(
            "reject",
            _cost_optimization_comparison(baseline, regressed)["decision"],
        )
        missing = {**candidate, "usage": {"available": False}}
        self.assertEqual(
            "reject",
            _cost_optimization_comparison(baseline, missing)["decision"],
        )

    def test_evidence_search_profile_requires_network_counterevidence_for_performance_cases(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="evidence-search-v1",
        )

        self.assertIn("search", prompt)
        self.assertIn("network evidence", prompt)
        self.assertIn("Empty application logs", prompt)
        self.assertIn("do not distinguish", prompt)

    def test_evidence_search_v2_localizes_component_before_cause_and_bounds_exploration(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="evidence-search-v2",
        )

        self.assertIn("localize the fault object first", prompt)
        self.assertIn("Do not promote an app or pod fault to a node", prompt)
        self.assertIn("at most two distinct search calls per case", prompt)
        self.assertIn("one list fallback", prompt)
        self.assertIn("six exact observation reads", prompt)
        self.assertIn("closest competing diagnosis", prompt)

    def test_observation_id_profile_keeps_v3_reasoning_contract_and_changes_only_tool_addressing(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="observation-id-v1",
        )

        self.assertIn("localize the fault object first", prompt)
        self.assertIn("at most two distinct search calls per case", prompt)
        self.assertIn("Use observationId returned by list or search", prompt)
        self.assertNotIn("GetAlerts", prompt)

    def test_quality_bounded_v3_requires_direct_and_counter_evidence_with_a_fixed_budget(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="quality-bounded-v3",
        )

        self.assertIn("at least five and at most eight exact observation reads", prompt)
        self.assertIn("direct root-cause evidence", prompt)
        self.assertIn("counterevidence against the closest alternative", prompt)
        self.assertIn("at most three list pages", prompt)
        self.assertIn("smallest valid submit JSON", prompt)

        with tempfile.TemporaryDirectory(prefix="cloudops-prompt-contract-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 5)]
            _write_fixture(root, case_ids)
            suite = CloudOpsBlindSuite(root / "blind", batches={"batch-1": case_ids})
            gateway = _CloudOpsContextProjectionGateway(CloudOpsBenchmarkGateway(suite))
            binding = gateway.bind_session(
                "session-1",
                batch_id="batch-1",
                workflow_profile="quality-bounded-v3",
            )
            operations = {
                item["properties"]["op"]["const"]
                for item in gateway.runtime_manifests({"id": "session-1"})[0]["parameters"]["oneOf"]
            }
            self.assertEqual("baseline-v1", binding["workflowProfile"])
            self.assertNotIn("search", operations)

    def test_quality_staged_v4_keeps_baseline_tools_and_requires_category_specific_causal_checks(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="quality-staged-v4",
        )

        self.assertIn("whole batch", prompt)
        self.assertIn("gateway route configuration", prompt)
        self.assertIn("earliest affected leaf", prompt)
        self.assertIn("image identity", prompt)
        self.assertIn("caller/callee values", prompt)
        self.assertIn("smallest valid submit JSON", prompt)

        with tempfile.TemporaryDirectory(prefix="cloudops-staged-prompt-contract-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 5)]
            _write_fixture(root, case_ids)
            suite = CloudOpsBlindSuite(root / "blind", batches={"batch-1": case_ids})
            gateway = _CloudOpsContextProjectionGateway(CloudOpsBenchmarkGateway(suite))
            binding = gateway.bind_session(
                "session-1",
                batch_id="batch-1",
                workflow_profile="quality-staged-v4",
            )
            operations = {
                item["properties"]["op"]["const"]
                for item in gateway.runtime_manifests({"id": "session-1"})[0]["parameters"]["oneOf"]
            }
            self.assertEqual("baseline-v1", binding["workflowProfile"])
            self.assertNotIn("search", operations)

    def test_alert_first_v5_localizes_performance_before_image_comparison_and_caps_prose(self) -> None:
        prompt = _batch_prompt(
            "batch-3",
            (
                "trainticket/service/1",
                "trainticket/service/2",
                "trainticket/performance/1",
                "trainticket/performance/2",
            ),
            workflow_profile="alert-first-v5",
        )

        self.assertIn("first read the GetAlerts observation", prompt)
        self.assertIn("Do not use pod age, image pull events, or image identity to localize", prompt)
        self.assertIn("dependency observations", prompt)
        self.assertIn("compact four-row evidence ledger", prompt)
        self.assertIn("55 words", prompt)

        with tempfile.TemporaryDirectory(prefix="cloudops-alert-first-contract-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 5)]
            _write_fixture(root, case_ids)
            suite = CloudOpsBlindSuite(root / "blind", batches={"batch-1": case_ids})
            gateway = _CloudOpsContextProjectionGateway(CloudOpsBenchmarkGateway(suite))
            binding = gateway.bind_session(
                "session-1",
                batch_id="batch-1",
                workflow_profile="alert-first-v5",
            )
            operations = {
                item["properties"]["op"]["const"]
                for item in gateway.runtime_manifests({"id": "session-1"})[0]["parameters"]["oneOf"]
            }
            self.assertEqual("baseline-v1", binding["workflowProfile"])
            self.assertNotIn("search", operations)

    def test_trial_id_is_a_bounded_basename_not_a_path(self) -> None:
        self.assertEqual("cloudops-run.v1", _normalize_trial_id("cloudops-run.v1"))
        for value in ("", "../escape", "/absolute", "nested/path", "bad value"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "trial id"):
                _normalize_trial_id(value)

    def test_eval_session_exposes_no_ordinary_runtime_tools(self) -> None:
        session = {
            "mode": "assistant",
            "executionMode": "read_only",
            "toolProfileVersion": "subagent-readonly-v1",
            "toolAllowlistMode": "explicit",
            "allowedTools": [],
            "workspaceRoots": [],
        }
        self.assertEqual(
            (),
            _tools_for_session(
                (
                    "overview",
                    "memory",
                    "knowledge",
                    "runtime",
                    "agents",
                    "workspace_read",
                    "workspace_search",
                    "workspace_shell",
                ),
                session,
            ),
        )

    def test_runtime_identity_gate_rejects_model_route_drift(self) -> None:
        receipt = {
            "state": {
                "model": {"provider": "openai-codex", "id": "gpt-5.6-luna"},
                "thinkingLevel": "max",
            }
        }

        with self.assertRaisesRegex(RuntimeError, "model route drifted"):
            _assert_expected_runtime(
                receipt,
                provider="openai-codex",
                model="gpt-5.6-sol",
                thinking_level="max",
            )

    def test_public_host_invocation_redacts_every_host_path(self) -> None:
        args = SimpleNamespace(
            trial_id="cloudops-public-1",
            provider="openai-codex",
            model="gpt-5.6-sol",
            thinking="max",
            transport="spool",
            timeout_seconds=900.0,
            max_reads_per_case=40,
            workflow_profile="evidence-search-v1",
            runtime_candidate=Path("/private/runtime-candidate"),
            blind_root=Path("/private/blind"),
            gold=Path("/private/host/gold.json"),
            scorer=Path("/private/host/score_answers.py"),
            source_agent_config=Path("/private/agent/config"),
            private_root=Path("/private/run"),
            output=Path("/private/run/report.json"),
        )

        invocation = _public_host_invocation(args, transport="spool-file-v1")
        encoded = json.dumps(invocation, sort_keys=True)

        self.assertEqual("paw.cloudops-host-invocation.v1", invocation["schemaVersion"])
        self.assertEqual("cloudops-public-1", invocation["trialId"])
        self.assertEqual("spool-file-v1", invocation["transport"])
        self.assertEqual("evidence-search-v1", invocation["workflowProfile"])
        self.assertEqual(64, len(invocation["commandSha256"]))
        self.assertNotIn("argv", invocation)
        self.assertNotIn("/private", encoded)
        self.assertNotIn("gold.json", encoded)
        self.assertNotIn("score_answers.py", encoded)

    def test_cli_help_is_directly_executable_from_repository_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_cloudops_agent_eval.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--runtime-candidate", completed.stdout)

    def test_candidate_runtime_factory_is_explicit_isolated_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloudops-runtime-config-") as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            candidate.mkdir()
            executable = candidate / "runtime-host" / "cli.mjs"
            executable.parent.mkdir()
            executable.write_text("export {};", encoding="utf-8")
            extension = candidate / "runtime-host" / "extension-placeholder.mjs"
            extension.write_text("export {};", encoding="utf-8")
            node = candidate / "bin" / "node"
            node.parent.mkdir()
            node.write_text("node", encoding="utf-8")
            source_config = root / "source-config"
            source_config.mkdir()
            for name in ("auth.json", "models.json", "models-store.json", "settings.json"):
                (source_config / name).write_text("{}", encoding="utf-8")
            installation = SimpleNamespace(
                executable=executable,
                extension_path=extension,
                node_executable=str(node),
                pi_version="0.84.2",
                protocol_version="2",
                tools=("overview", "workspace_read"),
                runtime_version="candidate-v1",
                manifest_sha256="a" * 64,
            )
            with patch(
                "scripts.run_cloudops_agent_eval.snapshot_managed_pi_runtime_payload",
                return_value=installation,
            ):
                config, identity = _candidate_runtime_config(
                    candidate,
                    run_root=root / "run",
                    source_agent_config=source_config,
                    provider="openai-codex",
                    model="gpt-5.6-sol",
                    tool_gateway_url="http://127.0.0.1:1234/api/agent/tool/execute",
                    tool_gateway_token="token",
                )

            self.assertEqual(executable, config.executable)
            self.assertEqual("openai-codex", config.provider)
            self.assertEqual("gpt-5.6-sol", config.model)
            self.assertEqual("2", config.protocol_version)
            self.assertEqual("a" * 64, identity["manifestSha256"])
            self.assertEqual("candidate-v1", identity["runtimeVersion"])
            self.assertFalse(identity["installActionPerformed"])
            self.assertNotIn("installedStateChanged", identity)
            self.assertEqual(
                {"auth.json", "models.json", "models-store.json", "settings.json"},
                {path.name for path in config.agent_dir.iterdir()},
            )

    def test_three_by_four_real_session_orchestration_persists_receipt_chain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloudops-runner-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 13)]
            _write_fixture(root, case_ids)
            batches = {
                "batch-1": case_ids[0:4],
                "batch-2": case_ids[4:8],
                "batch-3": case_ids[8:12],
            }
            suite = CloudOpsBlindSuite(root / "blind", batches=batches)
            gateway = CloudOpsBenchmarkGateway(suite)
            service = _FakeAgentService(gateway)
            database = root / "observability.sqlite"
            trace_store = TraceStore(database)
            eval_store = EvalRunStore(database)
            sandbox_store = SandboxRunStore(database)
            artifacts = AgentArtifactStore(database, root=root / "artifacts")
            scorer_calls: list[tuple[Path, list[dict[str, object]]]] = []
            gold_path = root / "host" / "gold.json"
            gold_path.parent.mkdir()
            gold_path.write_text("host only", encoding="utf-8")

            def score_host_only(path: Path, answers: list[dict[str, object]]) -> dict[str, object]:
                self.assertEqual(gold_path.resolve(), path)
                self.assertEqual([], [item for item in gateway.ledger()["items"] if str(path) in json.dumps(item)])
                scorer_calls.append((path, answers))
                return {
                    "aggregate": {
                        "cases": 12,
                        "answered": 12,
                        "AnswerCoverage": 1.0,
                        "CA": 1.0,
                        "FA": 0.9166666666666666,
                        "JRA": 0.9166666666666666,
                        "Top3JRA": 1.0,
                    },
                    "perCase": [
                        {"case_id": case_id, "JRA": 0 if case_id == case_ids[4] else 1}
                        for case_id in case_ids
                    ],
                    "process": {"MC": 0.8, "EOC": 0.7, "EE": 0.6, "authority": "diagnostic"},
                }

            report = run_cloudops_agent_eval(
                suite=suite,
                gateway=gateway,
                service=service,
                trial_id="cloudops-test-1",
                gold_path=gold_path,
                score_host_only=score_host_only,
                trace_store=trace_store,
                eval_store=eval_store,
                sandbox_store=sandbox_store,
                artifact_store=artifacts,
                now_ms=lambda: 1_700_000_000_000,
                timeout_seconds=1,
                runtime_identity={
                    "provider": "openai-codex",
                    "model": "gpt-5.6-sol",
                },
            )

            self.assertEqual(3, len(service.created))
            self.assertEqual(1, len(scorer_calls))
            self.assertEqual("completed", report["status"])
            self.assertEqual(0.9166666666666666, report["metrics"]["JRA"])
            self.assertEqual(4, len(report["traceIds"]))
            self.assertEqual(4, len(report["evalRunIds"]))
            self.assertEqual(3, report["signals"]["batchCount"])
            self.assertEqual(30, report["signals"]["toolCalls"])
            self.assertEqual(0, report["signals"]["searchCalls"])
            self.assertEqual(3, len(report["batches"]))
            self.assertEqual(
                ["turn_completed", "turn_completed", "turn_completed"],
                [item["terminalEvent"] for item in report["batches"]],
            )
            self.assertTrue(all(item["answerCount"] == 4 for item in report["batches"]))
            self.assertTrue(all(item["toolCalls"] == 10 for item in report["batches"]))
            self.assertTrue(all("assignedCaseIds" not in item for item in report["batches"]))
            self.assertEqual(64, len(report["batchPlanSha256"]))
            self.assertTrue(str(report["replayCohort"]["configFingerprint"]).startswith("sha256:"))
            self.assertEqual(0.8, report["processSignals"]["MC"])
            self.assertTrue(report["usage"]["available"])
            self.assertEqual("baseline-v1", report["workflowProfile"])
            self.assertIsNotNone(sandbox_store.get(report["sandboxRunId"]))
            self.assertTrue(all(not gateway.runtime_manifests({"id": session}) for session in service.created))
            self.assertTrue(
                all(
                    payload["toolAllowlistMode"] == "explicit"
                    and payload["allowedTools"] == []
                    for _session_id, payload in service.updated
                )
            )
            for session_id in service.created:
                self.assertEqual(
                    [
                        ("ensure", session_id),
                        ("select", session_id),
                        ("prompt", session_id),
                    ],
                    [
                        call
                        for call in service.lifecycle_calls
                        if call[1] == session_id and call[0] in {"ensure", "select", "prompt"}
                    ],
                )

            aggregate_eval = eval_store.get(report["aggregateEvalRunId"])
            self.assertEqual({"accuracy": 0.9166666666666666}, aggregate_eval["metrics"])
            aggregate_trace = trace_store.get(report["aggregateTraceId"])
            sandbox = sandbox_store.get(report["sandboxRunId"])
            self.assertEqual("allowlisted", sandbox["policy"]["network"])
            self.assertEqual(
                aggregate_trace["input"]["fingerprint"],
                sandbox["replayCohort"]["inputFingerprint"],
            )
            records = artifacts.lifecycle_records(
                owner_kind="connector_run",
                owner_id="cloudops-test-1",
                artifact_kind="cloudops_eval",
            )
            event_types = [record["eventType"] for record in records]
            self.assertEqual(3, event_types.count("batch_started"))
            self.assertEqual(3, event_types.count("batch_completed"))
            self.assertIn("trial_completed", event_types)
            terminal_record = next(record for record in records if record["eventType"] == "trial_completed")
            self.assertEqual(12, len(terminal_record["payload"]["answers"]))
            self.assertTrue(terminal_record["payload"]["usage"]["available"])
            self.assertEqual(12, len(terminal_record["payload"]["perCase"]))
            self.assertEqual(set(case_ids), {item["case_id"] for item in terminal_record["payload"]["perCase"]})

            public = json.dumps(report, sort_keys=True)
            self.assertNotIn(str(root), public)
            self.assertNotIn("gold.json", public)
            self.assertNotIn("host only", public)

    def test_failed_batch_unbinds_session_and_persists_failed_sandbox_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloudops-runner-fail-") as temporary:
            root = Path(temporary)
            case_ids = [f"demo/runtime/{index}" for index in range(1, 13)]
            _write_fixture(root, case_ids)
            suite = CloudOpsBlindSuite(
                root / "blind",
                batches={
                    "batch-1": case_ids[0:4],
                    "batch-2": case_ids[4:8],
                    "batch-3": case_ids[8:12],
                },
            )
            gateway = CloudOpsBenchmarkGateway(suite)
            service = _NoSubmissionService(gateway)
            database = root / "observability.sqlite"
            gold_path = root / "host" / "gold.json"
            gold_path.parent.mkdir()
            gold_path.write_text("host only", encoding="utf-8")
            sandbox_store = SandboxRunStore(database)

            with self.assertRaisesRegex(RuntimeError, "canonical submission"):
                run_cloudops_agent_eval(
                    suite=suite,
                    gateway=gateway,
                    service=service,
                    trial_id="cloudops-failed-1",
                    gold_path=gold_path,
                    score_host_only=lambda _path, _answers: self.fail("scorer must not run"),
                    trace_store=TraceStore(database),
                    eval_store=EvalRunStore(database),
                    sandbox_store=sandbox_store,
                    artifact_store=AgentArtifactStore(database, root=root / "artifacts"),
                    now_ms=lambda: 1_700_000_000_000,
                    timeout_seconds=1,
                )

            self.assertFalse(gateway.runtime_manifests({"id": service.created[0]}))
            failed = sandbox_store.get("sandbox:cloudops:cloudops-failed-1")
            self.assertEqual("failed", failed["status"])
            self.assertEqual("allowlisted", failed["policy"]["network"])

    def test_score_contract_rejects_missing_nonfinite_and_duplicate_case_metrics(self) -> None:
        cases = ("demo/runtime/1", "demo/runtime/2")
        valid = {
            "aggregate": {
                "AnswerCoverage": 1.0,
                "CA": 1.0,
                "FA": 0.5,
                "JRA": 0.5,
                "Top3JRA": 1.0,
            },
            "perCase": [
                {"case_id": "demo/runtime/1", "JRA": 1.0},
                {"case_id": "demo/runtime/2", "JRA": 0.0},
            ],
        }
        metrics, per_case = _validated_score(valid, case_ids=cases)
        self.assertEqual(0.5, metrics["JRA"])
        self.assertEqual(set(cases), set(per_case))

        for bad in (
            {**valid, "aggregate": {key: value for key, value in valid["aggregate"].items() if key != "JRA"}},
            {**valid, "aggregate": {**valid["aggregate"], "JRA": float("nan")}},
            {**valid, "perCase": [valid["perCase"][0], valid["perCase"][0]]},
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(RuntimeError, "scorer"):
                _validated_score(bad, case_ids=cases)

    def test_usage_absence_stays_unknown_instead_of_becoming_zero(self) -> None:
        self.assertEqual({"available": False}, _token_usage([]))
        self.assertEqual(
            {"available": False},
            _token_usage(
                [{"usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0}}]
            ),
        )
        self.assertEqual(
            {"available": False},
            _sum_usage([{"usage": {"available": False}}]),
        )
        self.assertIsNone(_numeric_usage({"available": False}))
        projected = _token_usage(
            [{"usage": {"input": 3, "output": 2, "cacheRead": 5, "totalTokens": 10}}]
        )
        self.assertTrue(projected["available"])
        self.assertEqual(10, projected["totalTokens"])

    def test_nested_runtime_usage_and_token_named_fields_are_projected(self) -> None:
        self.assertEqual(
            {
                "available": True,
                "input": 7,
                "output": 3,
                "cacheRead": 11,
                "cacheWrite": 2,
                "totalTokens": 23,
            },
            _token_usage([
                {
                    "eventType": "provider_request_completed",
                    "payload": {
                        "usage": {
                            "inputTokens": 7,
                            "outputTokens": 3,
                            "cacheReadTokens": 11,
                            "cacheWriteTokens": 2,
                            "totalTokens": 23,
                        }
                    },
                }
            ]),
        )


if __name__ == "__main__":
    unittest.main()
