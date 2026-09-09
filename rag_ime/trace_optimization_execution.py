"""One registered Lab adapter executes frozen, local task fixtures.

The existing WorkspaceHarness owns process execution. Each case gets a fresh
copy of the registered component, and Host stdout comparison creates the Eval.
This adapter makes no model call and makes no claim about unseen model tasks.
"""
from __future__ import annotations

import platform
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from .agent_workspace import WorkspaceHarness
from .trace_runtime import build_eval_run, build_trace_envelope, make_span
from .trace_optimization_versions import TraceOptimizationVersionStore, canonical, command_entry, digest, now_ms

SCENE_ID = "trace-optimization-command"


def controls_for_plan(plan: Mapping) -> dict[str, str]:
    return {
        "inputState": "sha256:" + digest([{key: item[key] for key in ("caseId", "input")} for item in plan["plan"]["cases"]]),
        "evaluator": "trace-exact-stdout:" + plan["contentSha256"],
        "qualityPolicy": "all-frozen-cases-pass.v1",
        "permissions": "workspace-harness.network-blocked.v1",
        "environment": "sha256:" + digest({"platform": platform.platform(), "python": platform.python_version()}),
    }


class TraceOptimizationCommandAdapter:
    def __init__(self, *, versions: TraceOptimizationVersionStore, candidates, traces, evals,
                 workspace_harness: WorkspaceHarness) -> None:
        self.versions, self.candidates = versions, candidates
        self.traces, self.evals, self.workspace = traces, evals, workspace_harness

    def prepare(self, spec: Mapping, job_id: str) -> dict:
        if set(spec) != {"candidateId", "role"} or spec["role"] not in {"baseline", "candidate"}:
            raise ValueError("Trace fixture needs candidateId and baseline/candidate role")
        candidate = self.candidates.get_candidate(spec["candidateId"])
        if not candidate:
            raise KeyError(spec["candidateId"])
        contract = candidate["comparisonContract"]
        plan = self.versions.get_plan(contract["caseSetRef"])
        if plan["reportId"] != candidate["reportId"]:
            raise ValueError("execution plan belongs to another report")
        if set(contract["caseIds"]) != {case["caseId"] for case in plan["plan"]["cases"]}:
            raise ValueError("candidate case set differs from frozen execution plan")
        if contract["controls"] != controls_for_plan(plan):
            raise ValueError("candidate controls differ from the actual fixture runner")
        if contract["qualityGates"] != [{"metricId": "accuracy", "minimum": 1.0}] or contract["costMetric"]:
            raise ValueError("local task fixtures require every case to pass and do not measure model cost")
        if len(contract["declaredChanges"]) != 1:
            raise ValueError("the local fixture adapter supports one component intervention")
        version = self.versions.get(candidate["parentVersionRef"] if spec["role"] == "baseline" else candidate["candidateVersionRef"])
        if version["reportId"] != candidate["reportId"]:
            raise ValueError("candidate version belongs to another report")
        if any(command_entry(case["command"]) not in version["manifest"] for case in plan["plan"]["cases"]):
            raise ValueError("execution plan must execute a file contained in the frozen component")
        binding = {"candidateId": candidate["candidateId"], "role": spec["role"],
                   "comparisonContractSha256": candidate["comparisonContractSha256"]}
        return {"publicSpec": {"traceOptimization": binding, "caseCount": len(plan["plan"]["cases"]),
                               "evaluationKind": "frozen_local_task_fixture"},
                "privateInput": {"jobId": job_id, "candidateId": candidate["candidateId"],
                                 "versionRef": version["versionRef"], "planRef": plan["planRef"], **binding}}

    def execute(self, private_input: Mapping, observer, cancelled) -> dict:
        candidate = self.candidates.get_candidate(private_input["candidateId"])
        version = self.versions.get(private_input["versionRef"])
        plan = self.versions.get_plan(private_input["planRef"])
        controls = controls_for_plan(plan)
        if controls != candidate["comparisonContract"]["controls"]:
            raise ValueError("execution environment changed since admission")
        loaded = {kind: "not-used:local-command" for kind in ("tool", "skill", "prompt", "workflow", "model")}
        loaded[candidate["targetKind"]] = version["versionRef"]
        identity = {key: private_input[key] for key in ("candidateId", "role", "comparisonContractSha256")}
        identity.update(controls=controls, loadedVersions=loaded)
        cases = []
        passed = 0
        for case in plan["plan"]["cases"]:
            if cancelled():
                return {"status": "cancelled", "traceOptimization": {**identity, "cases": cases, "usage": _usage()},
                        "summary": "运行已停止；未完成的案例不计为通过。"}
            observer.progress(f"{private_input['role']} · 正在运行 {case['caseId']}")
            with tempfile.TemporaryDirectory(prefix="paw-trace-fixture-") as directory:
                root = Path(directory) / "component"
                shutil.copytree(version["snapshotPath"], root)
                argv = [part.replace("{version}", str(root)) for part in case["command"]]
                command = shlex.join(["env", "PAW_TRACE_INPUT=" + canonical(case["input"]), *argv])
                prepared = self.workspace.prepare_command(
                    {"mode": "coordinator", "workspaceRoots": [str(root)], "executionMode": "workspace_managed", "toolProfileVersion": "control-center-v1"},
                    {"command": command, "cwd": str(root), "timeoutSeconds": plan["plan"]["timeoutSeconds"], "allowNetwork": False},
                )
                started = now_ms()
                receipt = self.workspace.execute_cancellable(prepared, cancelled)
                ended = now_ms()
            if cancelled():
                return {"status": "cancelled", "traceOptimization": {**identity, "cases": cases, "usage": _usage()},
                        "summary": "已停止正在执行的任务；未完成案例不计为通过。"}
            success = (receipt.get("exitCode") == 0 and not receipt.get("timedOut")
                       and not receipt.get("outputLimited") and receipt.get("output", "").strip() == case["expectedStdout"].strip())
            passed += int(success)
            key = digest([private_input["jobId"], case["caseId"]])[:32]
            trace_id, eval_id = "trace:optimization:" + key, "eval:optimization:" + key
            span = make_span(span_id="span:optimization:" + key, name="trace.optimization.execution",
                             started_at_ms=started, ended_at_ms=ended, status="completed" if receipt.get("exitCode") == 0 else "failed",
                             attributes={"traceOptimization": identity})
            trace = build_trace_envelope(trace_id=trace_id, source_kind="agent", input_text=canonical(case["input"]),
                                         binding={"caseId": case["caseId"]}, spans=[span], status="completed",
                                         created_at_ms=started, updated_at_ms=ended).to_dict()
            self.traces.persist(trace)
            evaluation = build_eval_run(eval_run_id=eval_id, trace_ids=[trace_id], mode="ground_truth", truth_kind="frozen",
                                        metrics={"accuracy": float(success)}, dataset_id="trace-local-task-fixture",
                                        label_revision=plan["contentSha256"],
                                        suite_binding={"suiteId": plan["planRef"], "suiteRevision": plan["contentSha256"]},
                                        input_trace_fingerprint=trace["input"]["fingerprint"],
                                        started_at_ms=started, completed_at_ms=ended, elapsed_ms=ended-started,
                                        now_ms=started, updated_at_ms=ended).to_dict()
            self.evals.persist(evaluation)
            cases.append({"caseId": case["caseId"], "traceId": trace_id, "evalRunId": eval_id})
        return {"status": "completed", "summary": f"冻结任务检查：{passed}/{len(cases)} 通过。",
                "evaluationKind": "frozen_local_task_fixture",
                "traceOptimization": {**identity, "cases": cases, "usage": _usage()}}


def _usage() -> dict:
    # No model was called. This is not a measured end-to-end operating cost.
    return {"totalCost": None, "currency": "", "complete": False, "receiptRefs": []}
