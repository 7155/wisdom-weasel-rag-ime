"""Trace App composition over existing reports, Lab jobs and Pi resources."""
from __future__ import annotations

import logging
from pathlib import Path
from threading import RLock
from typing import Mapping

from .agent_lab.optimization_knowledge import AgentLabOptimizationKnowledge
from .agent_lab.projects import AgentLabProjectStore
from .agent_lab.trials import TERMINAL_STATES
from .db import sqlite_connection
from .trace_optimization_execution import SCENE_ID, TraceOptimizationCommandAdapter, controls_for_plan
from .trace_optimization_pi import (
    SCENE_ID as PI_SCENE_ID, TraceOptimizationPiAdapter, controls_for_plan as pi_controls_for_plan,
)
from .trace_optimization_versions import digest, now_ms, text

_LOG = logging.getLogger(__name__)


class TraceOptimizationApplication:
    def __init__(self, agent) -> None:
        self.agent = agent
        self._mutation_lock = RLock()
        self.db_path = agent.sessions.db_path
        self.versions = agent.trace_optimization_versions
        self.candidates = agent.trace_optimizations
        self.projects = AgentLabProjectStore(self.db_path, scope_id="trace-optimization")
        self.knowledge = AgentLabOptimizationKnowledge(
            self.projects,
            receipt_reader=lambda kind, identifier: self.candidates.get_comparison(identifier)
            if kind == "trace_optimization_comparison" else None,
        )
        adapter = TraceOptimizationCommandAdapter(versions=self.versions, candidates=self.candidates,
                    traces=agent.trace_store, evals=agent.eval_runs,
                    workspace_harness=agent.background_jobs.workspace_harness)
        agent._eval_lab_trial_adapters[SCENE_ID] = adapter
        self.pi_adapter = TraceOptimizationPiAdapter(self.db_path, versions=self.versions, candidates=self.candidates,
            traces=agent.trace_store, evals=agent.eval_runs, sessions=agent.sessions, runtime=lambda: agent.runtime)
        agent._eval_lab_trial_adapters[PI_SCENE_ID] = self.pi_adapter
        if agent._eval_lab_trial_application is not None:
            agent._eval_lab_trial_application.adapters[SCENE_ID] = adapter
            agent._eval_lab_trial_application.adapters[PI_SCENE_ID] = self.pi_adapter

    def session_policy(self, session: Mapping) -> dict | None:
        return self.pi_adapter.session_policy(session)

    def ensure_project(self, roots: list[str]) -> str:
        canonical_roots = sorted({str(Path(root).expanduser().resolve()) for root in roots if root != "/"})
        title = "Trace · " + (", ".join(Path(root).name for root in canonical_roots)[:160] or "通用工作经验")
        response = self.projects.command({"action": "create", "expectedRevision": 0,
            "clientRequestId": "trace-workspace:" + digest(canonical_roots),
            "input": {"title": title, "description": "该工作区的 Agent 诊断、候选验证与可复用方法。"}})
        return response["project"]["projectId"]

    def report(self, report_id: str) -> dict:
        report = self.agent.trace_diagnostic_reports.get(report_id)
        if report is None:
            raise KeyError(report_id)
        return report

    def roots(self, report: Mapping) -> list[str]:
        return self.agent._trace_diagnostic_project_roots(report["targets"])

    def capabilities(self) -> dict:
        items, unavailable = [], []
        extension_service = self.agent._trace_optimization_extensions
        if extension_service is not None:
            try:
                inventory = extension_service.skills_list()
                if inventory.get("runtimeAvailable") is False:
                    unavailable.append("当前安装资源目录不可用；项目 Skill 可按实际发现结果查看。")
                for item in inventory.get("items", []):
                    items.append({"id": str(item.get("skillId") or item.get("id") or item.get("name")),
                        "name": str(item.get("name") or item.get("id")), "kind": "skill", "status": "installed",
                        "version": str(item.get("digest") or item.get("contentSha256") or item.get("version") or ""),
                        "summary": str(item.get("description") or ""),
                        "capabilityKeys": list(item.get("capabilityKeys") or [])})
            except Exception:
                unavailable.append("Skill 目录暂时不可用。")
        else:
            unavailable.append("尚未连接 Pi Package 资源目录。")
        reader = self.agent._trace_optimization_capability_reader
        if reader is not None:
            try:
                items.extend(reader())
            except Exception:
                unavailable.append("工具目录暂时不可用。")
        for version in self.versions.list():
            items.append({"id": version["versionRef"], "name": version["targetRef"], "kind": version["targetKind"],
                          "status": "candidate", "version": version["versionRef"], "summary": "已保存源码版本；是否采用以评测与应用回执为准。"})
        return {"ok": True, "items": items, "unavailable": unavailable}

    def library(self, payload: Mapping) -> dict:
        if set(payload) - {"projectId", "query", "patternId", "revision", "offset"}:
            raise ValueError("unsupported optimization library query")
        projects = [{"projectId": item["projectId"], "title": item["title"]} for item in self.projects.read()["items"]]
        project_id = str(payload.get("projectId") or "")
        result = {"ok": True, "projects": projects, "projectId": project_id, "patterns": [], "truncated": False}
        if not project_id:
            return result
        packet = self.knowledge.query(project_id, query=str(payload.get("query") or ""), limit=24)
        result["patterns"] = [{"patternId": item.get("patternId") or item["artifactId"], "revision": item["revision"],
            "title": item["title"], "summary": item["summary"], "status": item.get("knowledgeStatus", "observed"),
            "componentRef": item.get("scope", {}).get("componentRef", ""),
            "evidenceCount": len(item.get("evidenceRefs", item.get("evidenceIds", [])))} for item in packet["patterns"]]
        result.update(truncated=packet["truncated"], attempts=packet["attempts"])
        if payload.get("patternId"):
            revision = int(payload["revision"]) if payload.get("revision") else None
            result["pattern"] = self.knowledge.read(project_id, str(payload["patternId"]), revision=revision,
                offset=int(payload.get("offset") or 0))
        return result

    def read(self, report_id: str, payload: Mapping) -> dict:
        self.reconcile(report_id)
        report = self.report(report_id)
        project_id = report.get("optimizationProjectId", "")
        if payload.get("patternId"):
            return self.knowledge.read(project_id, str(payload["patternId"]),
                revision=int(payload["revision"]) if payload.get("revision") else None,
                offset=int(payload.get("offset") or 0))
        packet = self.knowledge.query(project_id, query=str(payload.get("query") or "")) if project_id else {"patterns": [], "attempts": []}
        return {"ok": True, "report": report, "knowledge": packet, "jobs": self.jobs(report_id)}

    def command(self, report_id: str, payload: Mapping) -> dict:
        if set(payload) - {"operation", "command", "clientRequestId", "input", "candidateId", "action"}:
            raise ValueError("unsupported Trace optimization command fields")
        report = self.report(report_id)
        operation = str(payload.get("operation") or payload.get("command") or "")
        value = payload.get("input", {})
        if not isinstance(value, Mapping):
            raise ValueError("optimization command input must be an object")
        request_id = text(payload.get("clientRequestId"), "clientRequestId", 240)
        project_id = report.get("optimizationProjectId", "")
        if operation == "register_version":
            kind = value.get("targetKind")
            if kind not in report.get("intent", {}).get("focusAreas", []):
                raise ValueError("registered change is outside this report's focus")
            return self.versions.register(report_id, value, roots=self.roots(report))
        if operation == "register_plan":
            return self.versions.register_plan(report_id, value, roots=self.roots(report))
        if operation == "prepare_candidate":
            before = self.versions.get(str(value.get("parentVersionRef") or ""))
            after = self.versions.get(str(value.get("candidateVersionRef") or ""))
            plan = self.versions.get_plan(str(value.get("planRef") or ""))
            if {before["reportId"], after["reportId"], plan["reportId"]} != {report_id}:
                raise ValueError("candidate resources belong to another report")
            if (before["targetKind"], before["targetRef"]) != (after["targetKind"], after["targetRef"]):
                raise ValueError("baseline and candidate must refer to the same component")
            proposal = {"targetKind": after["targetKind"], "targetRef": after["targetRef"],
                "parentVersionRef": before["versionRef"], "candidateVersionRef": after["versionRef"],
                "findingIds": list(value.get("findingIds", [])), "evidenceIds": list(value.get("evidenceIds", [])),
                "historicalPatternRefs": list(value.get("historicalPatternRefs", [])),
                "summary": str(value.get("summary") or ""), "expectedEffect": str(value.get("expectedEffect") or ""),
                "actualDiffRef": "trace-diff:" + digest([before["versionRef"], after["versionRef"]]),
                "comparisonContract": {"caseSetRef": plan["planRef"], "caseIds": [case["caseId"] for case in plan["plan"]["cases"]],
                    "controls": pi_controls_for_plan(plan) if plan["plan"].get("executionKind") == "pi_session" else controls_for_plan(plan), "declaredChanges": [{"kind": after["targetKind"], "targetRef": after["targetRef"],
                        "beforeVersionRef": before["versionRef"], "afterVersionRef": after["versionRef"]}],
                    "qualityGates": [{"metricId": "accuracy", "minimum": 1.0}],
                    "costMetric": "totalCost" if value.get("compareCost") is True and plan["plan"].get("executionKind") == "pi_session" else ""}}
            return self.candidates.propose(report_id, client_request_id=request_id, proposal=proposal)
        if operation == "propose":
            for name in ("parentVersionRef", "candidateVersionRef"):
                ref = self.versions.get(str(value.get(name) or ""))
                if ref["reportId"] != report_id:
                    raise ValueError("candidate version belongs to another report")
            return self.candidates.propose(report_id, client_request_id=request_id, proposal=value)
        if operation == "save_pattern":
            if set(value) - {"pattern", "patternId", "expectedRevision", "expectedPatternRevision"}:
                raise ValueError("invalid pattern command")
            return self.knowledge.save_pattern(project_id, value["pattern"],
                expected_revision=value.get("expectedRevision"), client_request_id=request_id,
                evidence_context=report, pattern_id=str(value.get("patternId") or ""),
                expected_pattern_revision=value.get("expectedPatternRevision", 0))
        if operation in {"prepare_distillation", "save_distillation"}:
            if report.get("intent", {}).get("mode") != "distill":
                raise ValueError("start a distillation task before extracting new capabilities")
            catalog = self.capabilities()
            capabilities = [{"kind": item["kind"], "id": item["id"], "version": item["version"],
                "summary": item["summary"], "capabilityKeys": item.get("capabilityKeys", [])}
                for item in catalog["items"] if item["status"] == "installed"]
            packet = self.knowledge.prepare_distillation(project_id, inspection=report, capabilities=capabilities)
            if catalog["unavailable"]:
                packet["inventoryComplete"] = False
            if operation == "prepare_distillation":
                return {**packet, "unavailableCatalogs": catalog["unavailable"]}
            outcome = self.knowledge.evaluate_distillation(packet, list(value.get("proposals", [])),
                capabilities=capabilities if not catalog["unavailable"] else None)
            for suggestion in outcome["items"]:
                proposed_kind = {"new_tool": "tool", "new_skill": "skill"}.get(suggestion["outcome"])
                if proposed_kind and proposed_kind not in report["intent"]["focusAreas"]:
                    raise ValueError("distilled capability is outside the user's selected focus")
            bindings = value.get("candidateBindings", {})
            if not isinstance(bindings, Mapping) or set(bindings) - {item["suggestionId"] for item in outcome["items"]}:
                raise ValueError("distillation candidate bindings must name current suggestions")
            for suggestion in outcome["items"]:
                suggestion["candidateIds"] = bindings.get(suggestion["suggestionId"], [])
            saved = self.agent.trace_diagnostic_reports.record_distillation(report_id,
                expected_revision=report["revision"], distillation=outcome)
            self.record_distillation(saved)
            return saved
        candidate_id = str(payload.get("candidateId") or value.get("candidateId") or "")
        candidate = self.candidates.get_candidate(candidate_id)
        if not candidate or candidate["reportId"] != report_id:
            raise ValueError("candidate does not belong to this report")
        if operation == "run_candidate" or (operation == "candidate_action" and payload.get("action") == "run_candidate"):
            self.start(candidate, request_id)
            return self.report(report_id)
        if operation == "cancel_candidate":
            for pair in self.jobs(report_id):
                if pair["candidateId"] == candidate_id:
                    for role in ("baseline", "candidate"):
                        if pair[role]["state"] not in TERMINAL_STATES:
                            self.agent.eval_lab_trial_cancel({"jobId": pair[role]["jobId"]})
            self.reconcile(report_id)
            return self.report(report_id)
        if operation == "compare":
            comparison = self.candidates.record_validation(candidate_id, client_request_id=request_id,
                baseline_trial_id=str(value.get("baselineTrialId") or ""), candidate_trial_id=str(value.get("candidateTrialId") or ""))
            self.record_outcome(candidate, comparison)
            return comparison
        if operation == "candidate_action":
            action = str(payload.get("action") or "")
            with self._mutation_lock:
                if action == "keep_original":
                    self.candidates.bind_application(candidate_id, client_request_id=request_id, action=action)
                else:
                    from .trace_optimization_installation import apply_trace_candidate
                    apply_trace_candidate(versions=self.versions, candidates=self.candidates,
                        extensions=self.agent._trace_optimization_extensions, candidate=candidate,
                        action=action, client_request_id=request_id)
            return self.report(report_id)
        raise ValueError("unsupported optimization operation")

    def start(self, candidate: Mapping, request_id: str) -> None:
        with self._mutation_lock:
            self._start(candidate, request_id)

    def _start(self, candidate: Mapping, request_id: str) -> None:
        with sqlite_connection(self.db_path) as conn:
            previous = conn.execute("SELECT candidate_id FROM trace_optimization_run_pairs WHERE request_id=?", (request_id,)).fetchone()
        if previous:
            if previous[0] != candidate["candidateId"]:
                raise ValueError("run request identity conflict")
            return
        candidate = self.candidates.get_candidate(candidate["candidateId"])
        if "run_candidate" not in candidate["availableActions"]:
            raise ValueError("candidate has no registered execution path")
        plan = self.versions.get_plan(candidate["comparisonContract"]["caseSetRef"])
        scene_id = PI_SCENE_ID if plan["plan"].get("executionKind") == "pi_session" else SCENE_ID
        # The Lab's durable admission prevents a repeat request from re-running.
        ids = {}
        try:
            for role in ("baseline", "candidate"):
                response = self.agent.eval_lab_trial_start({"clientRequestId": "trace-run:" + digest([request_id, role]),
                    "sceneId": scene_id, "spec": {"candidateId": candidate["candidateId"], "role": role}})
                ids[role] = response["job"]["jobId"]
        except Exception:
            # A failed second admission must not leave the first execution
            # running after the UI receives an error. Durable Lab IDs remain.
            for job_id in ids.values():
                self.agent.eval_lab_trial_cancel({"jobId": job_id})
            raise
        with sqlite_connection(self.db_path) as conn:
            previous = conn.execute("SELECT candidate_id,baseline_job_id,candidate_job_id FROM trace_optimization_run_pairs WHERE request_id=?", (request_id,)).fetchone()
            if previous and tuple(previous) != (candidate["candidateId"], ids["baseline"], ids["candidate"]):
                raise ValueError("run request identity conflict")
            conn.execute("INSERT OR IGNORE INTO trace_optimization_run_pairs VALUES(?,?,?,?,?,?,?)",
                (request_id, candidate["reportId"], candidate["candidateId"], ids["baseline"], ids["candidate"], "", now_ms()))

    def jobs(self, report_id: str) -> list[dict]:
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute("SELECT candidate_id,baseline_job_id,candidate_job_id,comparison_id FROM trace_optimization_run_pairs WHERE report_id=? ORDER BY created_at_ms DESC LIMIT 50", (report_id,)).fetchall()
        return [{"candidateId": row[0], "baseline": self.agent._trial_store().read(row[1])["job"],
                 "candidate": self.agent._trial_store().read(row[2])["job"], "comparisonId": row[3]} for row in rows]

    def reconcile(self, report_id: str) -> None:
        for row in self.jobs(report_id):
            if row["comparisonId"]:
                comparison = self.candidates.get_comparison(row["comparisonId"])
                if comparison:
                    self.record_outcome(self.candidates.get_candidate(row["candidateId"]), comparison)
                continue
            if row["baseline"]["state"] not in TERMINAL_STATES or row["candidate"]["state"] not in TERMINAL_STATES:
                continue
            candidate = self.candidates.get_candidate(row["candidateId"])
            comparison = self.candidates.record_validation(row["candidateId"],
                client_request_id="trace-comparison:" + digest([row["baseline"]["jobId"], row["candidate"]["jobId"]]),
                baseline_trial_id=row["baseline"]["jobId"], candidate_trial_id=row["candidate"]["jobId"])
            with sqlite_connection(self.db_path) as conn:
                conn.execute("UPDATE trace_optimization_run_pairs SET comparison_id=? WHERE baseline_job_id=? AND candidate_job_id=?",
                    (comparison["comparisonId"], row["baseline"]["jobId"], row["candidate"]["jobId"]))
            self.record_outcome(candidate, comparison)

    def record_report(self, report: Mapping) -> None:
        if not report.get("optimizationProjectId") or report.get("status") != "completed":
            return
        try:
            self.knowledge.record_report(report)
            self.record_distillation(report)
        except Exception:
            _LOG.warning("Trace report persisted; optimization knowledge consolidation needs retry", exc_info=True)

    def record_distillation(self, report: Mapping) -> None:
        for suggestion in report.get("distillation", {}).get("items", []):
            if suggestion["outcome"] == "no_change":
                continue
            refs = suggestion["evidenceIds"]
            rows = {item["evidenceId"]: item for item in report["inspection"]["evidence"]}
            observations = [{"statement": str(rows[ref].get("summary") or "本次选定来源中的可回溯记录")[:2000], "evidenceIds": [ref]} for ref in refs[:16]]
            self.knowledge.save_pattern(report["optimizationProjectId"],
                {"title": suggestion["title"], "summary": suggestion["reason"][:1000],
                 "scope": {"componentRef": (suggestion["existingCapabilityIds"] or [""])[0]},
                 "symptoms": suggestion["capabilityNeeds"][:24], "observations": observations,
                 "hypotheses": [{"statement": suggestion["reason"][:2000], "evidenceIds": refs[:16],
                     "uncertainty": "从工作记录提取的方法草稿；效果仍以实际候选验证为准。"}]},
                expected_revision=None, client_request_id="distillation:" + digest([report["reportId"], suggestion]),
                evidence_context=report)

    def record_outcome(self, candidate: Mapping, comparison: Mapping) -> None:
        if not candidate.get("optimizationProjectId"):
            return
        try:
            self.knowledge.record_outcome(candidate["optimizationProjectId"],
                {"kind": "trace_optimization_comparison", "id": comparison["comparisonId"]}, candidate_context=candidate)
        except Exception:
            _LOG.warning("Trace comparison persisted; optimization knowledge consolidation needs retry", exc_info=True)
