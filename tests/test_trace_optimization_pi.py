from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_lab.trials import AgentLabTrialStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.trace_store import TraceStore
from rag_ime.trace_optimization_pi import TraceOptimizationPiAdapter, controls_for_plan, normalize_pi_plan
from rag_ime.trace_optimization_versions import digest


class Runtime:
    def __init__(self, sessions):
        self.sessions = sessions
        self.adapter = None
        self.calls, self.aborts = [], []
        self.loaded_evidence = True
        self.stop = False

    def ensure(self, session_id):
        policy = self.adapter.session_policy(self.sessions.get(session_id))
        return {"resourceSnapshot": {"skillRefs": policy["skillIds"], "promptSettings": policy["promptSettings"], "candidateSkillPaths": policy["candidateSkillPaths"]}}

    def set_model(self, session_id, *, provider, model_id):
        return {"selected": {"provider": provider, "id": model_id}}

    def set_thinking_level(self, session_id, *, level):
        return {"thinkingLevel": level}

    def prompt(self, session_id, text, *, images, client_message_id):
        turn = "turn:" + str(len(self.calls))
        self.calls.append({"sessionId": session_id, "turnId": turn, "prompt": text, "requestId": client_message_id})
        return {"accepted": True, "turnId": turn}

    def await_turn_settled(self, session_id, turn_id, *, client_message_id, timeout_seconds):
        return {"schemaVersion": "rag-ime.pi-turn-settlement.v1", "sessionId": session_id, "turnId": turn_id, "clientMessageId": client_message_id, "runtimeSessionId": "pi:fixture", "receipt": {"schemaVersion": "pi.agent-settled.v2", "sessionId": "pi:fixture", "receiptId": "settlement:" + turn_id, "disposition": "completed", "aborted": False, "pendingOperations": 0, "finalMessage": {"role": "assistant", "content": [{"type": "text", "text": "host-only expected answer"}], "usage": {"input": 10, "output": 3}}}}

    def abort(self, session_id):
        self.aborts.append(session_id)

    def debug_context(self, session_id, turn_id):
        if not self.loaded_evidence:
            return {"available": False, "context": None}
        session = self.sessions.get(session_id)
        policy = self.adapter.session_policy(session)
        call = next(row for row in self.calls if row["sessionId"] == session_id and row["turnId"] == turn_id)
        custom = "Fixed product rules\n" + policy["promptSettings"]["systemInstructions"]
        receipts = []
        for path in policy["candidateSkillPaths"]:
            body = (Path(path) / "SKILL.md").read_text().split("---", 2)[-1].strip()
            receipts.append({"schemaVersion": "rag-ime.skill-load.v1", "name": policy["skillIds"][0], "contentRevision": hashlib.sha256(body.encode()).hexdigest()})
        return {"available": True, "context": {"schemaVersion": "rag-ime.context-inspection.v2", "clientMessageId": call["requestId"], "model": {"provider": "fixture", "id": "fixture"}, "systemPrompt": custom, "systemPromptOptions": {"customPrompt": custom, "contextFiles": [], "appendSystemPrompt": ""}, "toolSchemas": [], "skillCatalog": [{"name": name} for name in policy["skillIds"]], "loadedSkillReceipts": receipts, "providerRequestReceipts": [{"index": 1}], "modelCalls": []}}


class PiAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "test.sqlite"
        self.sessions = AgentSessionStore(self.db)
        self.sessions.initialize()
        self.traces, self.evals = TraceStore(self.db), EvalRunStore(self.db)
        self.runtime = Runtime(self.sessions)
        self.observer = SimpleNamespace(progress=lambda message: None, bind_session=lambda *args, **kwargs: None)

    def adapter(self, kind="prompt", before="Use the original method", after="Use the concise method", *, turns=8):
        versions = {}
        for ref, content in [("version:before", before), ("version:after", after)]:
            directory = self.root / ref.replace(":", "-")
            directory.mkdir(exist_ok=True)
            entry = "SKILL.md" if kind == "skill" else "workflow.json" if kind == "workflow" else "prompt.md"
            (directory / entry).write_text(content)
            versions[ref] = {"versionRef": ref, "reportId": "report:one", "targetKind": kind, "targetRef": kind + ":example", "snapshotPath": str(directory), "entryPath": entry, "manifest": {entry: hashlib.sha256(content.encode()).hexdigest()}}
        plan_value = normalize_pi_plan({"executionKind": "pi_session", "model": {"provider": "fixture", "model": "fixture", "thinkingLevel": "high"}, "allowedTools": [], "cases": [{"caseId": "one", "input": "Solve the task using the selected method.", "expectedText": "host-only expected answer"}], "timeoutSeconds": 30, "maxTaskTurns": turns})
        plan = {"planRef": "plan:one", "reportId": "report:one", "contentSha256": digest(plan_value), "plan": plan_value}
        contract = {"caseSetRef": plan["planRef"], "caseIds": ["one"], "controls": controls_for_plan(plan), "qualityGates": [{"metricId": "accuracy", "minimum": 1}], "declaredChanges": [{"kind": kind, "targetRef": kind + ":example", "beforeVersionRef": "version:before", "afterVersionRef": "version:after"}], "costMetric": ""}
        candidate = {"candidateId": "candidate:one", "reportId": "report:one", "targetKind": kind, "targetRef": kind + ":example", "parentVersionRef": "version:before", "candidateVersionRef": "version:after", "comparisonContract": contract, "comparisonContractSha256": digest(contract)}
        adapter = TraceOptimizationPiAdapter(self.db, versions=SimpleNamespace(get=versions.__getitem__, get_plan=lambda ref: plan), candidates=SimpleNamespace(get_candidate=lambda ref: candidate), traces=self.traces, evals=self.evals, sessions=self.sessions, runtime=lambda: self.runtime)
        self.runtime.adapter = adapter
        return adapter

    def execute(self, adapter, role="candidate", cancelled=lambda: False):
        prepared = adapter.prepare({"candidateId": "candidate:one", "role": role}, "job:" + role)
        return adapter.execute(prepared["privateInput"], self.observer, cancelled)

    def test_prompt_runs_real_session_owner_and_keeps_labels_out_of_all_model_inputs(self):
        adapter = self.adapter()
        result = self.execute(adapter)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["traceOptimization"]["loadedVersions"]["prompt"], "version:after")
        self.assertEqual(self.evals.list()[0]["metrics"], {"accuracy": 1.0})
        self.assertEqual(len(self.runtime.calls), 1)
        self.assertTrue(all("host-only expected answer" not in row["prompt"] for row in self.runtime.calls))
        with sqlite3.connect(self.db) as conn:
            inputs = conn.execute("SELECT prompt,model_json FROM agent_lab_golden_model_calls").fetchall()
        self.assertNotIn("host-only expected answer", json.dumps(inputs))
        self.assertFalse(result["traceOptimization"]["usage"]["complete"])
        session = self.sessions.get(self.runtime.calls[0]["sessionId"])
        self.assertFalse(session["projectContextEnabled"])
        self.assertEqual(adapter.session_policy(session)["promptSettings"]["systemInstructions"], "Use the concise method")
        other = self.sessions.create(title="Unbound", owner_app_id="extension:trace-agent", surface_kind="extension_app", surface_key="optimization.eval.spoof")
        self.assertIsNone(adapter.session_policy(other))

    def test_skill_requires_actual_content_load_receipt(self):
        adapter = self.adapter("skill", "---\nname: example\n---\nOriginal steps", "---\nname: example\n---\nBetter steps")
        result = self.execute(adapter)
        self.assertEqual(result["traceOptimization"]["loadedVersions"]["skill"], "version:after")
        self.assertIn("skill_load", self.runtime.calls[0]["prompt"])
        self.runtime.loaded_evidence = False
        result = self.execute(adapter, "baseline")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["traceOptimization"]["loadedVersions"], {})
        self.assertTrue(result["evidenceGaps"])

    def test_workflow_uses_same_pi_session_for_its_finite_steps_and_budget_counts_both_roles(self):
        original = json.dumps({"steps": [{"instruction": "Solve directly"}]})
        candidate = json.dumps({"steps": [{"instruction": "Inspect the task"}, {"instruction": "Conclude from the previous step"}]})
        adapter = self.adapter("workflow", original, candidate, turns=3)
        result = self.execute(adapter)
        self.assertEqual(result["taskTurns"], 2)
        self.assertEqual(len({row["sessionId"] for row in self.runtime.calls}), 1)
        self.assertEqual(result["traceOptimization"]["loadedVersions"]["workflow"], "version:after")
        adapter = self.adapter("workflow", original, candidate, turns=2)
        with self.assertRaisesRegex(ValueError, "budget"):
            adapter.prepare({"candidateId": "candidate:one", "role": "candidate"}, "job:new")

    def test_cancel_after_admission_aborts_the_same_pi_session(self):
        adapter = self.adapter()
        result = self.execute(adapter, cancelled=lambda: bool(self.runtime.calls))
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.runtime.aborts, [self.runtime.calls[0]["sessionId"]])
        self.assertEqual(self.evals.list(), [])


class PiPlanTests(unittest.TestCase):
    def test_frozen_plan_has_task_turn_budget_and_no_model_score_input(self):
        plan = normalize_pi_plan({"executionKind": "pi_session", "model": {"provider": "fixture", "model": "fixture", "thinkingLevel": "high"}, "allowedTools": [], "cases": [{"caseId": "one", "input": "Question", "expectedText": "Answer"}], "timeoutSeconds": 30, "maxTaskTurns": 4})
        self.assertEqual(plan["maxTaskTurns"], 4)
        with self.assertRaises(ValueError):
            normalize_pi_plan({**plan, "maxModelRequests": 4})
        with self.assertRaises(ValueError):
            normalize_pi_plan({**plan, "allowedTools": ["memory_read"]})


if __name__ == "__main__":
    unittest.main()
