from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.eval_run_store import EvalRunStore
from rag_ime.trace_store import TraceStore
from rag_ime.vertical_agent_harness import load_builtin_manifests
from rag_ime.vertical_agent_process import run_external_vertical_agent_process


def _seatbelt_can_apply_profile() -> bool:
    executable = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not executable.is_file():
        return False
    completed = subprocess.run(
        [str(executable), "-p", "(version 1)(allow default)", "/usr/bin/true"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


@unittest.skipUnless(
    _seatbelt_can_apply_profile(),
    "requires a process allowed to apply the macOS sandbox-exec profile",
)
class VerticalAgentProcessTests(unittest.TestCase):
    def test_real_sgg_process_verifies_and_persists_trace_then_eval(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        manifest = load_builtin_manifests()["sgg"]
        session = {
            "id": "agent:vertical-process-test",
            "mode": "coordinator",
            "workspaceRoots": [str(repository_root)],
            "executionMode": "read_only",
            "toolProfileVersion": "subagent-readonly-v1",
        }

        with tempfile.TemporaryDirectory(prefix="vertical-process-") as tmp:
            root = Path(tmp)
            result = run_external_vertical_agent_process(
                manifest,
                session=session,
                source_session_id=str(session["id"]),
                command=(
                    "PYTHONPATH=. python3 examples/vertical_agents/sgg/agent.py "
                    "--run-id process-test"
                ),
                cwd=repository_root,
                eval_store=EvalRunStore(root / "eval.sqlite"),
                trace_store=TraceStore(root / "trace.sqlite"),
                fixture_id="sales-ledger-answer",
                now_ms=1_800_000_000_000,
            )

            receipt = result["processReceipt"]
            self.assertEqual(receipt["schemaVersion"], "rag-ime.workspace-command-receipt.v1")
            self.assertEqual(receipt["exitCode"], 0)
            self.assertFalse(receipt["timedOut"])
            self.assertFalse(receipt["outputLimited"])
            self.assertFalse(receipt["networkAllowed"])
            self.assertTrue(receipt["sourceReadOnly"])

            trace = json.loads(receipt["output"])
            self.assertEqual(result["verification"]["verified"], True)
            self.assertEqual(result["traceId"], trace["traceId"])
            self.assertEqual(result["traceId"], "trace:vertical:sgg:custom-process:process-test")
            answer_span = next(
                span for span in trace["spans"] if span["name"] == "agent.answer"
            )
            self.assertEqual(answer_span["attributes"]["producerKind"], "custom_process")

            trace_store = TraceStore(root / "trace.sqlite")
            eval_store = EvalRunStore(root / "eval.sqlite")
            expected_trace = dict(trace)
            expected_trace["binding"] = {
                **trace["binding"],
                "sessionId": session["id"],
            }
            self.assertEqual(trace_store.get(result["traceId"]), expected_trace)
            eval_run = eval_store.get(result["evalRunId"])
            self.assertIsNotNone(eval_run)
            assert eval_run is not None
            self.assertEqual(eval_run["traceIds"], [trace["traceId"]])
            self.assertEqual(
                eval_run["suiteBinding"],
                {"suiteId": "sgg", "suiteRevision": "fixture-v2"},
            )
            self.assertEqual(
                set(result),
                {"processReceipt", "traceId", "evalRunId", "verification"},
            )


if __name__ == "__main__":
    unittest.main()
