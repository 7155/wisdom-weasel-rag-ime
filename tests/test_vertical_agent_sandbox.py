from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from rag_ime.eval_run_store import EvalRunStore
from rag_ime.vertical_agent_harness import VerticalHarnessError, load_builtin_manifests
from rag_ime.vertical_agent_sandbox import (
    _prepare_workspace,
    _retrieval_scores,
    run_vertical_agent_self_test,
)


class VerticalAgentSandboxSelfTestTests(unittest.TestCase):
    def test_public_vertical_examples_execute_real_offline_retrieval_trace_eval_chain(self) -> None:
        manifests = load_builtin_manifests()
        with tempfile.TemporaryDirectory(prefix="vertical-agent-self-test-") as tmp:
            workspace = Path(tmp)
            for app_id, manifest in manifests.items():
                with self.subTest(app_id=app_id):
                    result = run_vertical_agent_self_test(manifest, workspace / app_id)

                    self.assertEqual(app_id, result["appId"])
                    self.assertEqual(1, result["importedCount"])
                    self.assertEqual(1, result["retrieval"]["hitCount"])
                    self.assertEqual(0, result["providerCalls"])
                    self.assertTrue(result["productionWriteBlocked"])

                    trace = result["trace"]
                    self.assertEqual("completed", trace["status"])
                    self.assertEqual(
                        ["agent.input", "rag.retrieve", "memory.recall", "agent.answer"],
                        [span["name"] for span in trace["spans"]],
                    )
                    knowledge = next(item for item in trace["evidence"] if item["sourceKind"] == "knowledge")
                    memory = next(item for item in trace["evidence"] if item["sourceKind"] == "memory")
                    self.assertEqual("retrieval_output", knowledge["evidenceStage"])
                    self.assertEqual("sandbox_knowledge", knowledge["sourceLane"])
                    self.assertEqual("memory_recall", memory["evidenceStage"])
                    self.assertEqual("fixture_memory", memory["sourceLane"])

                    receipt = result["memoryReceipt"]
                    self.assertEqual("fixture", receipt["producerKind"])
                    self.assertEqual("memory_recall", receipt["evidenceStage"])
                    self.assertTrue(receipt["summaryFingerprint"].startswith("sha256:"))
                    self.assertNotIn("text", receipt)
                    self.assertNotIn("prompt", receipt)

                    self.assertTrue(result["traceVerification"]["verified"])
                    eval_run = result["evalRun"]
                    self.assertEqual("ground_truth", eval_run["mode"])
                    self.assertEqual("ground_truth", eval_run["metricAuthority"])
                    self.assertEqual(
                        {"suiteId": app_id, "suiteRevision": manifest["suiteRevision"]},
                        eval_run["suiteBinding"],
                    )
                    self.assertEqual({"precision": 1.0, "recall": 1.0, "f1": 1.0}, eval_run["metrics"])
                    self.assertEqual(
                        eval_run,
                        EvalRunStore(workspace / app_id / "eval.sqlite").get(eval_run["evalRunId"]),
                    )

                    sandbox_run = result["sandboxRun"]
                    self.assertEqual([trace["traceId"]], sandbox_run["traceIds"])
                    self.assertEqual([eval_run["evalRunId"]], sandbox_run["evalRunIds"])
                    self.assertTrue(sandbox_run["policy"]["productionWriteBlocked"])
                    self.assertEqual("blocked", sandbox_run["policy"]["network"])
                    self.assertEqual(
                        f"workspace-binding:{app_id}:self-test",
                        sandbox_run["policy"]["workspaceBindingId"],
                    )
                    self.assertTrue(sandbox_run["policy"]["workspaceFingerprint"].startswith("sha256:"))
                    self.assertNotIn("workspaceRoot", sandbox_run["policy"])
                    self.assertNotIn("workspaceRoot", result)
                    artifacts = workspace / app_id / "artifacts"
                    trace_artifact = json.loads((artifacts / "trace.json").read_text(encoding="utf-8"))
                    sandbox_artifact = json.loads((artifacts / "sandbox-run.json").read_text(encoding="utf-8"))
                    receipt_artifact = json.loads(
                        (artifacts / "memory-recall-fixture-receipt.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(trace, trace_artifact)
                    self.assertEqual(sandbox_run, sandbox_artifact)
                    self.assertEqual(receipt, receipt_artifact)
                    self.assertEqual(sandbox_run["traceIds"], [trace_artifact["traceId"]])
                    self.assertEqual(sandbox_run["evalRunIds"], [eval_run["evalRunId"]])

    def test_trace_and_eval_ids_are_stable_across_isolated_runs(self) -> None:
        manifest = load_builtin_manifests()["sgg"]
        with tempfile.TemporaryDirectory(prefix="vertical-agent-stable-") as tmp:
            first = run_vertical_agent_self_test(manifest, Path(tmp) / "first")
            second = run_vertical_agent_self_test(manifest, Path(tmp) / "second")

        self.assertEqual(first["trace"]["traceId"], second["trace"]["traceId"])
        self.assertEqual(first["evalRun"]["evalRunId"], second["evalRun"]["evalRunId"])
        self.assertNotEqual(first["runId"], second["runId"])

    def test_workspace_must_be_an_empty_real_isolated_leaf(self) -> None:
        manifest = load_builtin_manifests()["sgg"]
        with tempfile.TemporaryDirectory(prefix="vertical-agent-workspace-") as tmp:
            parent = Path(tmp)
            nonempty = parent / "nonempty"
            nonempty.mkdir()
            (nonempty / "sentinel").write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(VerticalHarnessError, "must be empty"):
                run_vertical_agent_self_test(manifest, nonempty)

            real_leaf = parent / "empty"
            real_leaf.mkdir()
            self.assertEqual(real_leaf.resolve(), _prepare_workspace(real_leaf))

            symlink_leaf = parent / "link"
            symlink_leaf.symlink_to(real_leaf, target_is_directory=True)
            with self.assertRaisesRegex(VerticalHarnessError, "may not be a symlink"):
                run_vertical_agent_self_test(manifest, symlink_leaf)

    def test_missing_scores_stay_absent_and_numeric_edge_values_are_preserved(self) -> None:
        self.assertEqual({}, _retrieval_scores({}))
        self.assertEqual({}, _retrieval_scores({"score": None}))
        self.assertEqual({"retrieval": 0.0}, _retrieval_scores({"score": 0}))
        self.assertEqual({"retrieval": -2.5}, _retrieval_scores({"score": -2.5}))
        for value in (True, "0.5", math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(VerticalHarnessError):
                _retrieval_scores({"score": value})


if __name__ == "__main__":
    unittest.main()
