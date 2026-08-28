from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from examples.vertical_agents.sgg.agent import build_sgg_trace
from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.trace_runtime import EvidenceRef, build_trace_envelope, make_span
from rag_ime.trace_store import TraceStore
from rag_ime.vertical_sandbox_connector import VerticalSandboxConnectorService
from rag_ime.vertical_agent_suite import evaluate_vertical_agent_case_trace


class VerticalSandboxConnectorTests(unittest.TestCase):
    def test_host_connector_returns_sandbox_trace_eval_chain(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        now_ms = 1_800_000_000_000

        traces: list[dict[str, object]] = []

        def execute(prepared):
            run_id = prepared.command.split("--run-id", 1)[1].strip()
            trace = build_sgg_trace(run_id=run_id)
            traces.append(trace)
            return {
                "schemaVersion": "rag-ime.workspace-command-receipt.v1",
                "mutationApplied": False,
                "validationSucceeded": True,
                "summary": "命令执行完成，退出码 0",
                "commandSha256": "0" * 64,
                "cwd": str(repository_root),
                "exitCode": 0,
                "durationMs": 7,
                "timedOut": False,
                "outputLimited": False,
                "networkAllowed": False,
                "sourceReadOnly": True,
                "temporaryWritesDiscarded": True,
                "output": json.dumps(trace, ensure_ascii=False, separators=(",", ":")),
                "outputBytes": 1,
                "undoAvailable": False,
            }

        with tempfile.TemporaryDirectory(prefix="paw-vertical-connector-") as temporary:
            eval_store = EvalRunStore(Path(temporary) / "eval.sqlite")
            trace_store = TraceStore(Path(temporary) / "trace.sqlite")
            connector = VerticalSandboxConnectorService(
                eval_store=eval_store,
                trace_store=trace_store,
                workspace_harness=WorkspaceHarness(executor=execute),
                repository_root=repository_root,
                now_ms=lambda: now_ms,
            )

            result = connector.execute(
                "session:demo",
                "run",
                {"suiteId": "sgg", "suiteRevision": "fixture-v2"},
            )

            stored_trace = trace_store.get(result["traceId"])
            self.assertEqual(
                stored_trace["binding"],
                {
                    "sessionId": "session:demo",
                    "sourceLoopId": traces[0]["binding"]["sourceLoopId"],
                },
            )
            self.assertIsNotNone(eval_store.get(result["evalRunId"]))

            second = connector.execute(
                "session:demo",
                "run",
                {"suiteId": "sgg", "suiteRevision": "fixture-v2"},
            )
            self.assertNotEqual(result["sandboxRunId"], second["sandboxRunId"])
            self.assertNotEqual(result["traceId"], second["traceId"])
            self.assertNotEqual(result["evalRunId"], second["evalRunId"])
            self.assertEqual(connector.sandbox_store.count(), 2)

        self.assertEqual(result["sandboxRun"]["traceIds"], [result["traceId"]])
        self.assertEqual(result["sandboxRun"]["evalRunIds"], [result["evalRunId"]])
        self.assertEqual(result["sandboxRun"]["policy"]["network"], "blocked")
        self.assertTrue(result["sandboxRun"]["policy"]["productionWriteBlocked"])
        self.assertEqual(result["metrics"], {"f1": 1.0, "precision": 1.0, "recall": 1.0})
        self.assertEqual(
            result["authority"],
            {
                "connector": "pi_package",
                "execution": "paw_host",
                "trace": "TraceStore",
                "evaluation": "EvalRunStore",
            },
        )

    def test_host_connector_resolves_a_non_sgg_manifest_fixture(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        now_ms = 1_800_000_000_000
        captured: dict[str, object] = {}

        def process_runner(manifest, **kwargs):
            captured.update(
                {
                    "appId": manifest["appId"],
                    "fixtureId": kwargs["fixture_id"],
                    "command": kwargs["command"],
                }
            )
            fixture = manifest["fixtures"][0]
            truth = fixture["truth"]["requiredEvidenceIds"]
            spans = tuple(
                make_span(
                    span_id=f"span:zhanggui:{index}",
                    name=name,
                    started_at_ms=now_ms + index,
                    ended_at_ms=now_ms + index + 1,
                )
                for index, name in enumerate(manifest["traceRequirements"]["requiredSpanNames"])
            )
            evidence = tuple(
                EvidenceRef(
                    str(evidence_id),
                    "memory" if str(evidence_id).startswith("memory:") else "knowledge",
                    str(
                        manifest["selfTest"]["memory"]["sourceRef"]
                        if str(evidence_id).startswith("memory:")
                        else fixture["ragEvidence"]["sourceRef"]
                    ),
                    source_lane=(
                        "fixture_memory"
                        if str(evidence_id).startswith("memory:")
                        else str(fixture["ragEvidence"]["sourceLane"])
                    ),
                    evidence_stage=(
                        "memory_recall"
                        if str(evidence_id).startswith("memory:")
                        else "retrieval_output"
                    ),
                )
                for evidence_id in truth
            )
            trace = build_trace_envelope(
                trace_id="trace:vertical:zhanggui-wenshu:custom-process:test",
                source_kind="vertical_agent",
                input_text=str(manifest["selfTest"]["query"]),
                binding={"sourceLoopId": "vertical-custom-process:zhanggui:test"},
                spans=spans,
                evidence=evidence,
                now_ms=now_ms,
            ).to_dict()
            evaluated = evaluate_vertical_agent_case_trace(
                manifest,
                trace,
                eval_store=kwargs["eval_store"],
                trace_store=kwargs["trace_store"],
                fixture_id=str(kwargs["fixture_id"]),
                now_ms=kwargs["now_ms"],
            )
            return {
                "processReceipt": {
                    "exitCode": 0,
                    "durationMs": 1,
                    "timedOut": False,
                    "outputLimited": False,
                    "networkAllowed": False,
                    "sourceReadOnly": True,
                },
                **evaluated,
            }

        with tempfile.TemporaryDirectory(prefix="paw-vertical-connector-registry-") as temporary:
            root = Path(temporary)
            connector = VerticalSandboxConnectorService(
                eval_store=EvalRunStore(root / "eval.sqlite"),
                trace_store=TraceStore(root / "trace.sqlite"),
                workspace_harness=WorkspaceHarness(executor=lambda prepared: {}),
                process_runner=process_runner,
                repository_root=repository_root,
                now_ms=lambda: now_ms,
            )

            result = connector.execute(
                "session:demo",
                "run",
                {"suiteId": "zhanggui-wenshu", "suiteRevision": "fixture-v2"},
            )

        self.assertEqual(captured["appId"], "zhanggui-wenshu")
        self.assertEqual(captured["fixtureId"], "order-summary-answer")
        self.assertIn(
            "examples/vertical_agents/zhanggui-wenshu/agent.py",
            str(captured["command"]),
        )
        self.assertEqual(result["suite"], {"suiteId": "zhanggui-wenshu", "suiteRevision": "fixture-v2"})
        self.assertEqual(result["sandboxRun"]["policy"]["network"], "blocked")


if __name__ == "__main__":
    unittest.main()
