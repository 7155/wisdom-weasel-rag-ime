"""Bounded task comparisons through the resident Pi Session owner.

Pi owns every Agent/Tool turn, settlement and cancellation. This adapter only
selects frozen resources, admits finite task turns and evaluates final text
against labels never sent to the tested Session. Missing resource telemetry
remains unverified even when the task answer passes its ground-truth check.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import sqlite3
import math
from collections.abc import Callable, Mapping
from pathlib import Path

from .agent_lab.golden_pi import AgentLabGoldenPiExecutor, GoldenPiCallError, normalize_golden_usage
from .agent_prompt_settings import default_prompt_settings
from .agent_tool_ids import READONLY_TOOL_PROFILE
from .db import sqlite_connection
from .trace_optimization_versions import canonical, digest, now_ms
from .trace_runtime import build_eval_run, build_trace_envelope, make_span

SCENE_ID = "trace-optimization-pi"
_CONTEXT = "rag-ime.trace-optimization-pi-call.v1"
_TOOLS = {"workspace_read", "workspace_search"}
_KINDS = {"skill", "prompt", "workflow"}


def _text(value: object, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{name} must be bounded text")
    return value


def normalize_pi_plan(plan: Mapping) -> dict:
    allowed = {"executionKind", "title", "model", "allowedTools", "cases", "timeoutSeconds", "maxTaskTurns"}
    if not isinstance(plan, Mapping) or set(plan) - allowed or plan.get("executionKind") != "pi_session":
        raise ValueError("Unsupported Pi execution plan")
    model = plan.get("model")
    if not isinstance(model, Mapping) or set(model) != {"provider", "model", "thinkingLevel"}:
        raise ValueError("Pi plan requires an explicit fixed model and thinking level")
    model = {key: _text(value, key, 160) for key, value in model.items()}
    if model["thinkingLevel"] not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Unsupported Pi thinking level")
    tools = plan.get("allowedTools")
    if not isinstance(tools, list) or any(not isinstance(tool, str) or tool not in _TOOLS for tool in tools) or len(set(tools)) != len(tools):
        raise ValueError("Pi task comparison permits only frozen workspace read/search tools")
    cases = plan.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        raise ValueError("Pi plan requires 1 to 32 cases")
    normalized_cases, ids = [], set()
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != {"caseId", "input", "expectedText"}:
            raise ValueError("Pi cases require caseId, input and a host-only expectedText")
        identifier = _text(case["caseId"], "caseId", 120)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", identifier) or identifier in ids:
            raise ValueError("Pi case IDs must be unique metadata tokens")
        ids.add(identifier)
        normalized_cases.append({"caseId": identifier, "input": _text(case["input"], "case input", 16000), "expectedText": _text(case["expectedText"], "expectedText", 16000)})
    timeout, turns = plan.get("timeoutSeconds", 300), plan.get("maxTaskTurns")
    if type(timeout) is not int or not 1 <= timeout <= 900:
        raise ValueError("Pi timeoutSeconds must be between 1 and 900")
    if type(turns) is not int or not 1 <= turns <= 64 or turns < 2 * len(cases):
        raise ValueError("maxTaskTurns must cover both executions and be at most 64")
    return {"executionKind": "pi_session", "title": _text(plan.get("title", "Pi task comparison"), "title", 240), "model": model, "allowedTools": sorted(tools), "cases": normalized_cases, "timeoutSeconds": timeout, "maxTaskTurns": turns}


def controls_for_plan(plan: Mapping) -> dict[str, str]:
    value = normalize_pi_plan(plan["plan"])
    return {"inputState": "sha256:" + digest([{key: row[key] for key in ("caseId", "input")} for row in value["cases"]]), "evaluator": "pi-exact-text:" + str(plan["contentSha256"]), "qualityPolicy": "all-frozen-cases-pass.v1", "permissions": "readonly:" + digest(value["allowedTools"]), "environment": "sha256:" + digest({"adapter": "trace-pi-v1", "platform": platform.platform(), "model": value["model"], "timeoutSeconds": value["timeoutSeconds"], "maxTaskTurns": value["maxTaskTurns"]})}


def _skill(entry_text: str) -> tuple[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)(.*)$", entry_text, flags=re.S)
    if match is None:
        raise ValueError("Skill entry must have valid SKILL.md frontmatter")
    name = re.search(r"^name:\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\s*$", match[1], flags=re.M)
    if name is None:
        raise ValueError("Skill frontmatter must declare one exact routable name")
    return name[1], match[2].strip()


def _steps(kind: str, entry_text: str) -> list[str]:
    if kind != "workflow":
        return [""]
    value = json.loads(entry_text)
    if not isinstance(value, Mapping) or set(value) != {"steps"} or not isinstance(value["steps"], list) or not 1 <= len(value["steps"]) <= 4:
        raise ValueError("Workflow candidate must be executable JSON with 1 to 4 Pi task steps")
    result = []
    for step in value["steps"]:
        if not isinstance(step, Mapping) or set(step) != {"instruction"}:
            raise ValueError("Workflow steps require a bounded instruction")
        result.append(_text(step["instruction"], "workflow instruction", 8000))
    return result


class _TaskPiExecutor(AgentLabGoldenPiExecutor):
    """Reuse durable exact-request settlement; only resource preparation differs."""
    def _prepare(self, request_id: str, model_json: str, prompt: str, provider: str, model_id: str, thinking: str) -> sqlite3.Row:
        context = json.loads(model_json).get("traceOptimizationTask", {})
        if context.get("schemaVersion") != _CONTEXT:
            raise ValueError("Pi comparison call lacks its host binding")
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM agent_lab_golden_model_calls WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous["model_json"] != model_json or previous["prompt"] != prompt:
                    raise GoldenPiCallError("Pi comparison request identity changed", interrupted=False)
                return previous
            session_id = str(context.get("sessionId") or "")
            if session_id:
                prior = conn.execute("SELECT model_json FROM agent_lab_golden_model_calls WHERE session_id=? ORDER BY created_at_ms LIMIT 1", (session_id,)).fetchone()
                binding = json.loads(prior[0]).get("traceOptimizationTask", {}) if prior else {}
                if any(binding.get(key) != context.get(key) for key in ("jobId", "candidateId", "caseId", "role", "workspaceRoot")):
                    raise ValueError("Workflow step cannot reuse another task Session")
            else:
                session = self.sessions.create(title="Trace · Pi task evaluation", mode="coordinator", model_profile=f"{provider}/{model_id}", thinking_level=thinking, tool_profile_version=READONLY_TOOL_PROFILE, execution_mode="read_only", project_context_enabled=False, pi_skills_enabled=bool(context["skillIds"]), codex_skills_enabled=False, workspace_roots=[context["workspaceRoot"]], surface_kind="extension_app", owner_app_id="extension:trace-agent", surface_key="optimization.eval." + digest(request_id)[:32], _connection=conn)
                session_id = str(session["id"])
                self.sessions.set_runtime_policy(session_id, mode="coordinator", tool_profile_version=READONLY_TOOL_PROFILE, execution_mode="read_only", allowed_tools=context["allowedTools"], project_context_enabled=False, pi_skills_enabled=bool(context["skillIds"]), codex_skills_enabled=False, workspace_roots=[context["workspaceRoot"]], connection=conn)
            conn.execute("INSERT INTO agent_lab_golden_model_calls(request_id,session_id,model_json,prompt,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?)", (request_id, session_id, model_json, prompt, now_ms(), now_ms()))
            return conn.execute("SELECT * FROM agent_lab_golden_model_calls WHERE request_id=?", (request_id,)).fetchone()


class TraceOptimizationPiAdapter:
    def __init__(self, db_path: str | Path, *, versions, candidates, traces, evals, sessions, runtime: Callable):
        self.db_path = Path(db_path)
        self.versions, self.candidates, self.traces, self.evals = versions, candidates, traces, evals
        self.sessions, self.runtime = sessions, runtime

    def session_policy(self, session: Mapping) -> dict | None:
        """No policy is inferred from an App label or a model-written Session."""
        session_id = str(session.get("id") or session.get("sessionId") or "")
        if not session_id:
            return None
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("SELECT model_json FROM agent_lab_golden_model_calls WHERE session_id=? ORDER BY created_at_ms,request_id LIMIT 1", (session_id,)).fetchone()
        context = json.loads(row[0]).get("traceOptimizationTask", {}) if row else {}
        if context.get("schemaVersion") != _CONTEXT:
            return None
        return {"skillIds": list(context["skillIds"]), "promptSettings": dict(context["promptSettings"]), "candidateSkillPaths": list(context["candidateSkillPaths"])}

    def _entry(self, version: Mapping) -> str:
        return (Path(version["snapshotPath"]) / version["entryPath"]).read_text(encoding="utf-8")

    def prepare(self, spec: Mapping, job_id: str) -> dict:
        if not isinstance(spec, Mapping) or set(spec) != {"candidateId", "role"} or spec["role"] not in {"baseline", "candidate"}:
            raise ValueError("Pi execution requires candidateId and baseline/candidate role")
        candidate = self.candidates.get_candidate(spec["candidateId"])
        if candidate is None or candidate["targetKind"] not in _KINDS:
            raise ValueError("Pi adapter supports registered Skill, prompt and workflow candidates")
        contract = candidate["comparisonContract"]
        plan = self.versions.get_plan(contract["caseSetRef"])
        value = normalize_pi_plan(plan["plan"])
        versions = [self.versions.get(candidate[key]) for key in ("parentVersionRef", "candidateVersionRef")]
        if plan["reportId"] != candidate["reportId"] or any(version["reportId"] != candidate["reportId"] or version["targetKind"] != candidate["targetKind"] or version["targetRef"] != candidate["targetRef"] for version in versions):
            raise ValueError("Pi resources must belong to this report and exact candidate target")
        if set(contract["caseIds"]) != {row["caseId"] for row in value["cases"]} or contract["controls"] != controls_for_plan(plan):
            raise ValueError("Pi execution differs from its frozen cases or controls")
        if len(contract["declaredChanges"]) != 1 or contract["qualityGates"] != [{"metricId": "accuracy", "minimum": 1}]:
            raise ValueError("Pi task comparison requires one target change and all frozen cases passing")
        step_counts = [len(_steps(candidate["targetKind"], self._entry(version))) for version in versions]
        if len(value["cases"]) * sum(step_counts) > value["maxTaskTurns"]:
            raise ValueError("Both baseline and candidate task turns exceed the frozen budget")
        if candidate["targetKind"] == "skill":
            names = [_skill(self._entry(version))[0] for version in versions]
            if names[0] != names[1]:
                raise ValueError("Skill comparison must preserve the exact trigger name")
        if candidate["targetKind"] == "prompt" and any(len(self._entry(version)) > 8000 for version in versions):
            raise ValueError("Prompt candidate exceeds the per-Session prompt settings limit")
        identity = {"candidateId": candidate["candidateId"], "role": spec["role"], "comparisonContractSha256": candidate["comparisonContractSha256"]}
        return {"publicSpec": {"traceOptimization": identity, "evaluationKind": "pi_session_task", "caseCount": len(value["cases"]), "maxTaskTurns": value["maxTaskTurns"]}, "privateInput": {**identity, "jobId": job_id, "versionRef": candidate["parentVersionRef"] if spec["role"] == "baseline" else candidate["candidateVersionRef"], "planRef": plan["planRef"]}}

    def _materialize(self, private: Mapping, version: Mapping, case_id: str) -> tuple[Path, dict]:
        root = self.db_path.parent / "TraceOptimizationPiTasks" / digest([private["jobId"], case_id])
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        entry_text = self._entry(version)
        settings, skill_ids, paths = default_prompt_settings(), [], []
        if version["targetKind"] == "skill":
            name, _ = _skill(entry_text)
            target = root / ".pi" / "skills" / name
            if not target.exists():
                shutil.copytree(version["snapshotPath"], target)
            if version["entryPath"] != "SKILL.md":
                raise ValueError("Skill entryPath must be SKILL.md at the resource root")
            for path, fingerprint in version["manifest"].items():
                if hashlib.sha256((target / path).read_bytes()).hexdigest() != fingerprint:
                    raise ValueError("Materialized Skill changed after source registration")
            skill_ids, paths = [name], [str(target)]
        elif version["targetKind"] == "prompt":
            settings["systemInstructions"] = entry_text.strip()
        return root, {"skillIds": skill_ids, "candidateSkillPaths": paths, "promptSettings": settings}

    def _loaded(self, runtime, context: Mapping, result: Mapping, version: Mapping, model: Mapping) -> tuple[dict, dict, int, list[dict]]:
        debug = runtime.debug_context(result["sessionId"], result["turnId"])
        record = debug.get("context") if isinstance(debug, Mapping) else None
        if not isinstance(record, Mapping) or record.get("schemaVersion") != "rag-ime.context-inspection.v2" or record.get("clientMessageId") != result["receipt"]["requestId"]:
            raise ValueError("Pi did not retain the exact task's resource inspection")
        selected = record.get("model", {})
        if selected.get("provider") != model["provider"] or selected.get("id") != model["model"]:
            raise ValueError("Actual Pi model differs from the frozen plan")
        options = record.get("systemPromptOptions")
        if not isinstance(options, Mapping) or not isinstance(options.get("customPrompt"), str):
            raise ValueError("Actual Pi prompt composition is unavailable")
        custom = options["customPrompt"]
        instructions = context["promptSettings"]["systemInstructions"]
        if instructions and (instructions not in custom or instructions not in str(record.get("systemPrompt", ""))):
            raise ValueError("The candidate prompt was not present in the actual Pi context")
        normalized_prompt = custom.replace(context["workspaceRoot"], "<evaluation-workspace>")
        if instructions:
            normalized_prompt = normalized_prompt.replace(instructions, "<candidate-instructions>")
        if options.get("contextFiles"):
            raise ValueError("Unexpected project context entered the evaluated task")
        schemas = record.get("toolSchemas")
        if not isinstance(schemas, list):
            raise ValueError("Actual Pi tool schemas are unavailable")
        normalized_schemas = sorted(schemas, key=lambda row: str(row.get("name", "")))
        catalog = record.get("skillCatalog")
        if not isinstance(catalog, list) or {row.get("name") for row in catalog} != set(context["skillIds"]):
            raise ValueError("Pi loaded an unexpected Skill catalog")
        loaded = {"tool": "sha256:" + digest(normalized_schemas), "skill": "none:skill", "prompt": "sha256:" + digest(normalized_prompt), "workflow": "single-turn:v1", "model": "sha256:" + digest(dict(model))}
        if version["targetKind"] == "skill":
            name, body = _skill(self._entry(version))
            body_hash = hashlib.sha256(body.encode()).hexdigest()
            if not any(row.get("schemaVersion") == "rag-ime.skill-load.v1" and row.get("name") == name and row.get("contentRevision") == body_hash for row in record.get("loadedSkillReceipts", [])):
                raise ValueError("Pi has no actual skill_load receipt for this exact Skill content")
        loaded[version["targetKind"]] = version["versionRef"]
        fixed = {"basePrompt": "sha256:" + digest(normalized_prompt), "toolSchemas": loaded["tool"], "promptAdditions": "sha256:" + digest(options.get("appendSystemPrompt", ""))}
        requests = record.get("providerRequestReceipts")
        calls = record.get("modelCalls")
        complete_usage = []
        if isinstance(requests, list) and requests and isinstance(calls, list) and len(requests) == len(calls):
            for call in calls:
                if not isinstance(call, Mapping) or not call.get("completedAtMs") or not isinstance(call.get("assistantMessage"), Mapping):
                    complete_usage = []
                    break
                complete_usage.append(normalize_golden_usage(call["assistantMessage"].get("usage")))
        return loaded, fixed, len(requests) if isinstance(requests, list) else 0, complete_usage

    def execute(self, private_input: Mapping, observer, cancelled: Callable[[], bool]) -> dict:
        candidate = self.candidates.get_candidate(private_input["candidateId"])
        version = self.versions.get(private_input["versionRef"])
        plan = self.versions.get_plan(private_input["planRef"])
        value = normalize_pi_plan(plan["plan"])
        if controls_for_plan(plan) != candidate["comparisonContract"]["controls"]:
            raise ValueError("Pi execution environment changed since admission")
        executor = _TaskPiExecutor(self.db_path, sessions=self.sessions, runtime=self.runtime, timeout_seconds=value["timeoutSeconds"])
        runtime = self.runtime()
        identity = {key: private_input[key] for key in ("candidateId", "role", "comparisonContractSha256")}
        cases, all_usage, gaps, versions_seen, fixed_seen = [], [], [], [], []
        provider_requests, task_turns = 0, 0
        execution = {**identity, "controls": candidate["comparisonContract"]["controls"], "loadedVersions": {}, "cases": cases}
        try:
            for case in value["cases"]:
                if cancelled():
                    return self._result("cancelled", execution, all_usage, provider_requests, task_turns, gaps)
                root, policy = self._materialize(private_input, version, case["caseId"])
                context = {"schemaVersion": _CONTEXT, "jobId": private_input["jobId"], "candidateId": candidate["candidateId"], "role": private_input["role"], "caseId": case["caseId"], "workspaceRoot": str(root), "allowedTools": value["allowedTools"], **policy}
                session_id, final, spans = "", None, []
                started = now_ms()
                for index, instruction in enumerate(_steps(version["targetKind"], self._entry(version))):
                    request_id = "trace-pi:" + digest([private_input["jobId"], case["caseId"], index])
                    context["sessionId"] = session_id
                    model = {**value["model"], "traceOptimizationTask": dict(context)}
                    prompt = case["input"] if index == 0 else "Continue the same task using the previous results."
                    if instruction:
                        prompt = instruction + "\n\n" + prompt
                    if policy["skillIds"]:
                        prompt = "Load the Skill " + policy["skillIds"][0] + " using skill_load, then perform this task.\n\n" + prompt
                    # ExpectedText is deliberately absent from all Session,
                    # workspace, model and prompt inputs.
                    def on_session(current_id, expected_policy=policy):
                        observer.bind_session(current_id, cancel=lambda: runtime.abort(current_id))
                        opened = runtime.ensure(current_id)
                        resource = opened.get("resourceSnapshot", {})
                        if resource.get("skillRefs") != expected_policy["skillIds"] or resource.get("promptSettings") != expected_policy["promptSettings"]:
                            raise GoldenPiCallError("Pi did not freeze the requested task resource policy", interrupted=False)
                    observer.progress(f"{private_input['role']} · {case['caseId']} · Pi step {index + 1}")
                    final = executor.complete(request_id=request_id, model=model, prompt=prompt, on_session=on_session, cancelled=cancelled, on_progress=lambda _: None)
                    session_id = final["sessionId"]
                    observer.bind_session(session_id, final["turnId"], cancel=lambda current=session_id: runtime.abort(current))
                    task_turns += 1
                    turn_usage = {"requestId": request_id, "finalMessageUsage": final.get("usage", {}), "providerRequestsComplete": False, "providerRequestUsage": []}
                    all_usage.append(turn_usage)
                    try:
                        loaded, fixed, count, request_usage = self._loaded(runtime, context, final, version, value["model"])
                        turn_usage.update(providerRequestsComplete=bool(request_usage), providerRequestUsage=request_usage)
                        versions_seen.append(loaded); fixed_seen.append(fixed); provider_requests += count
                        execution["loadedVersions"] = loaded
                        execution["fixedContextFingerprints"] = fixed
                        marker = {**identity, "controls": execution["controls"], "loadedVersions": loaded, "fixedContextFingerprints": fixed}
                        spans.append(make_span(span_id="span:pi:" + digest(request_id)[:32], name="trace.optimization.execution", started_at_ms=started, ended_at_ms=now_ms(), attributes={"traceOptimization": marker}))
                    except (ValueError, KeyError) as error:
                        gaps.append(str(error))
                if final is None:
                    raise ValueError("Pi workflow produced no terminal task")
                key = digest([private_input["jobId"], case["caseId"]])[:32]
                trace_id, eval_id = "trace:pi-optimization:" + key, "eval:pi-optimization:" + key
                trace = build_trace_envelope(trace_id=trace_id, source_kind="agent", input_text=case["input"], binding={"sessionId": session_id, "turnId": final["turnId"], "runId": private_input["jobId"], "caseId": case["caseId"]}, spans=spans, status="completed", created_at_ms=started, updated_at_ms=now_ms()).to_dict()
                self.traces.persist(trace)
                evaluation = build_eval_run(eval_run_id=eval_id, trace_ids=[trace_id], mode="ground_truth", truth_kind="frozen", metrics={"accuracy": float(final["text"].strip() == case["expectedText"].strip())}, dataset_id="trace-pi-frozen-task", label_revision=plan["contentSha256"], suite_binding={"suiteId": plan["planRef"], "suiteRevision": plan["contentSha256"]}, input_trace_fingerprint=trace["input"]["fingerprint"], now_ms=now_ms()).to_dict()
                self.evals.persist(evaluation)
                cases.append({"caseId": case["caseId"], "traceId": trace_id, "evalRunId": eval_id})
        except GoldenPiCallError as error:
            if error.completion and error.completion.get("usage"):
                all_usage.append({"finalMessageUsage": error.completion["usage"], "providerRequestsComplete": False, "providerRequestUsage": []})
            gaps.append(str(error))
            return self._result("cancelled" if cancelled() else "interrupted" if error.interrupted else "failed", execution, all_usage, provider_requests, task_turns, gaps)
        if any(item != versions_seen[0] for item in versions_seen) or any(item != fixed_seen[0] for item in fixed_seen):
            gaps.append("Pi resources changed across frozen cases or workflow steps")
        if gaps:
            # Preserve real Eval/Trace results, but omit comparison authority
            # when any required loaded-version evidence is incomplete.
            execution["loadedVersions"] = {}
        return self._result("completed", execution, all_usage, provider_requests, task_turns, gaps)

    @staticmethod
    def _result(status: str, execution: dict, observed_usage: list, provider_requests: int, task_turns: int, gaps: list[str]) -> dict:
        requests = [usage for item in observed_usage for usage in item["providerRequestUsage"]]
        amounts = [item.get("estimatedCostUsd", item.get("costUsd")) for item in requests]
        complete = bool(amounts) and all(item["providerRequestsComplete"] for item in observed_usage) and all(type(amount) in {int, float} and math.isfinite(amount) and amount >= 0 for amount in amounts)
        refs = [item["evalRunId"] for item in execution["cases"]]
        execution["usage"] = {"totalCost": sum(amounts) if complete else None, "currency": "USD" if complete else "", "complete": complete, "receiptRefs": refs if complete else []}
        return {"status": status, "evaluationKind": "pi_session_task", "summary": f"Pi task turns: {task_turns}; settled cases: {len(execution['cases'])}; resource evidence: {'incomplete' if gaps else 'recorded'}", "traceOptimization": execution, "evidenceGaps": list(dict.fromkeys(gaps)), "observedProviderRequests": provider_requests, "taskTurns": task_turns, "budgetUnit": "pi_task_turn_admission", "usage": observed_usage}
