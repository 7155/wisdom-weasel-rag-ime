"""Bounded optimization experience in the existing Lab Project artifact store.

This is not personal Memory, business Knowledge, an Agent, or an execution
owner. Analysis is explicitly separate from source observations and immutable
host outcomes. Pi performs distillation; this service prepares its bounded
context and preserves its evidence-bound proposals.

The Project command journal authenticates managed artifact versions. A generic
``publish_artifact`` operation cannot manufacture outcome authority by copying
an artifact's kind, schema, or text. We reuse Project transactions and artifact
versions; no second database or migration is needed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from .projects import (
    AgentLabProjectConflict,
    AgentLabProjectNotFound,
    AgentLabProjectStore,
    AgentLabProjectValidationError,
    _integer,
    _json,
    _now,
    _object,
    _text,
)

SCHEMA_VERSION = "rag-ime.agent-lab-optimization-knowledge.v1"
_PATTERN_ACTION = "optimization_knowledge.pattern"
_OUTCOME_ACTION = "optimization_knowledge.outcome"
_SOURCE_KINDS = {"session", "session_event", "room_event", "observation", "trace_span", "trace_evidence", "eval_run"}
_RELATIONS = {"supports", "contradicts", "rejected", "inconclusive"}
_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _array(value: Any, label: str, maximum: int = 32) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise AgentLabProjectValidationError(f"{label}需要至多 {maximum} 项的列表。")
    return value


def _texts(value: Any, label: str, maximum: int = 32, length: int = 640) -> list[str]:
    items = [_text(item, label, length) for item in _array(value, label, maximum)]
    if len(set(items)) != len(items):
        raise AgentLabProjectValidationError(f"{label}不能重复。")
    return items


def _scope(project_id: str, value: Any) -> dict:
    value = _object(value, {"componentRef", "componentVersion", "inputClass"}, "经验适用范围")
    return {"projectId": project_id, **{key: _text(value.get(key, ""), key, 240, optional=True)
        for key in ("componentRef", "componentVersion", "inputClass")}}


def inspection_sources(context: Mapping) -> tuple[dict, dict[str, dict]]:
    """Project only whitelisted public Trace evidence, with exact snapshot refs.

    Callers supply a host-frozen report/inspection, never model tool arguments.
    Arbitrary evidence bodies, private inputs, Gold answers and memory payloads
    are not copied into the packet.
    """
    if not isinstance(context, Mapping):
        raise AgentLabProjectValidationError("需要当前报告的冻结证据。")
    inspection = context.get("inspection", context)
    if not isinstance(inspection, Mapping) or not isinstance(inspection.get("evidence"), list):
        raise AgentLabProjectValidationError("当前报告没有可读取的冻结证据。")
    snapshot_hash = _hash(dict(inspection))
    if context.get("inspectionSha256") and context["inspectionSha256"] != snapshot_hash:
        raise AgentLabProjectValidationError("冻结证据摘要与报告不一致。")
    target_rows = inspection.get("targets", [])
    if not isinstance(target_rows, list) or not 1 <= len(target_rows) <= 12:
        raise AgentLabProjectValidationError("一次经验提取需要 1 至 12 个来源。")
    targets = {}
    environment = inspection.get("environment", {})
    environment_rows = environment.get("targets", []) if isinstance(environment, Mapping) else []
    # The canonical inspection calls these rows `sources` in some revisions.
    if not environment_rows and isinstance(environment, Mapping):
        environment_rows = environment.get("sources", [])
    hashes = {item.get("targetKey"): item.get("sourceSha256", "") for item in environment_rows if isinstance(item, Mapping)}
    for item in target_rows:
        if not isinstance(item, Mapping) or item.get("kind") not in {"session", "room", "run"}:
            raise AgentLabProjectValidationError("经验来源只支持已选择的 Session、Room 或 Run。")
        identifier = _text(item.get("id"), "来源标识")
        key = f"{item['kind']}:{identifier}"
        if item.get("targetKey", key) != key or key in targets:
            raise AgentLabProjectValidationError("来源绑定无效或重复。")
        targets[key] = {"kind": item["kind"], "id": identifier, "targetKey": key,
            "sourceAvailable": bool(item.get("sourceAvailable")), "sourceSha256": hashes.get(key, ""),
            "traceIds": _texts(item.get("traceIds", []), "来源 Trace", 32, 240)}
    timeline = {item.get("evidenceId"): item for item in inspection.get("timeline", []) if isinstance(item, Mapping)}
    evidence = {}
    for item in inspection["evidence"][:512]:
        if not isinstance(item, Mapping) or item.get("sourceKind") not in _SOURCE_KINDS:
            continue
        source_ref = _text(item.get("sourceRef"), "证据引用", 640)
        if re.match(r"(?:memory|gold|knowledge_gold|personal_memory):", source_ref, re.IGNORECASE):
            continue
        key = str(item.get("targetKey") or "")
        trace_id = str(item.get("traceId") or "")
        target_keys = [key] if key in targets else [target_key for target_key, target in targets.items()
            if trace_id and trace_id in target["traceIds"]]
        if not target_keys:
            continue
        evidence_id = _text(item.get("evidenceId"), "证据标识", 640)
        if evidence_id in evidence:
            raise AgentLabProjectValidationError("冻结证据标识重复。")
        row = {"evidenceId": evidence_id, "sourceRef": source_ref, "targetKeys": target_keys,
            "sourceKind": item["sourceKind"], "sourceSha256": _hash(dict(item)),
            "status": str(item.get("status") or "")[:80],
            "summary": str(item.get("summary") or "")[:800],
            "summaryTruncated": len(str(item.get("summary") or "")) > 800,
            "role": str(timeline.get(evidence_id, {}).get("kind") or "")[:80]}
        row["authority"] = "source_statement" if item["sourceKind"] in {"session", "session_event", "room_event"} else "host_observation"
        evidence[evidence_id] = row
    anchor = {"reportId": str(context.get("reportId") or ""), "inspectionSha256": snapshot_hash,
        "targets": list(targets.values()), "sourceTruncated": bool(any(inspection.get("truncated", {}).values()))}
    return anchor, evidence


class AgentLabOptimizationKnowledge:
    def __init__(self, project_store: AgentLabProjectStore, *,
                 receipt_reader: Callable[[str, str], Mapping | None] | None = None) -> None:
        self.projects = project_store
        self.receipt_reader = receipt_reader

    @staticmethod
    def _managed_items(conn, project_id: str) -> list[dict]:
        # Read only bounded journal summaries. Full artifact contents are read
        # only by an explicit body lookup, not injected during retrieval.
        rows = conn.execute("""
            SELECT item_json FROM (
                SELECT json_extract(response_json,'$.item') AS item_json,
                    row_number() OVER (
                        PARTITION BY json_extract(response_json,'$.artifactId')
                        ORDER BY created_at_ms DESC,rowid DESC) AS rank
                FROM agent_lab_project_commands
                WHERE project_id=? AND json_extract(request_json,'$.action') IN (?,?)
            ) WHERE rank=1 LIMIT 500
        """, (project_id, _PATTERN_ACTION, _OUTCOME_ACTION))
        return [json.loads(row[0]) for row in rows if row[0]]

    def _managed_artifact(self, conn, project_id: str, artifact_id: str, revision: int | None = None) -> tuple[dict, dict]:
        args = [project_id, _PATTERN_ACTION, _OUTCOME_ACTION, artifact_id]
        condition = ""
        if revision is not None:
            condition = " AND json_extract(response_json,'$.artifactRevision')=?"
            args.append(_integer(revision, 1))
        row = conn.execute("""SELECT response_json FROM agent_lab_project_commands
            WHERE project_id=? AND json_extract(request_json,'$.action') IN (?,?)
              AND json_extract(response_json,'$.artifactId')=?""" + condition +
            " ORDER BY created_at_ms DESC,rowid DESC LIMIT 1", args).fetchone()
        if row is None:
            raise AgentLabProjectNotFound("此项目没有这份受管理的优化经验或版本。")
        receipt = json.loads(row[0])
        artifact = self.projects._artifact(conn, project_id, artifact_id, receipt["artifactRevision"])
        if _hash(artifact["content"]) != receipt["bodySha256"]:
            raise AgentLabProjectConflict("优化经验版本与持久回执不一致。")
        return artifact, receipt["item"]

    def _write(self, project_id: str, *, action: str, body: dict, index: dict,
               client_request_id: str, expected_revision: int | None = None,
               artifact_id: str = "", expected_artifact_revision: int = 0) -> dict:
        project_id = _text(project_id, "项目标识")
        client_request_id = _text(client_request_id, "请求标识")
        if expected_revision is not None:
            _integer(expected_revision, 1)
        _integer(expected_artifact_revision)
        request = {"action": action, "projectId": project_id, "expectedRevision": expected_revision,
            "artifactId": artifact_id, "expectedArtifactRevision": expected_artifact_revision, "input": body}
        request_json = _json(request)
        # Different arity from public Project commands prevents a client ID
        # collision from impersonating a managed write.
        receipt_key = _json([self.projects.scope_id, "optimization_knowledge", client_request_id])
        self.projects.initialize()
        with self.projects._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = self.projects._project(conn, project_id)
            old = conn.execute("SELECT request_json,response_json FROM agent_lab_project_commands WHERE client_request_id=?", (receipt_key,)).fetchone()
            if old:
                if old[0] != request_json:
                    raise AgentLabProjectConflict("这条优化经验回执已绑定不同内容。")
                return {**json.loads(old[1]), "replayed": True}
            if expected_revision is not None and project["revision"] != expected_revision:
                raise AgentLabProjectConflict("优化项目已经更新，请刷新后保存经验。")
            if artifact_id:
                previous, previous_index = self._managed_artifact(conn, project_id, artifact_id)
                if previous_index["entryKind"] != "pattern" or action != _PATTERN_ACTION:
                    raise AgentLabProjectValidationError("结果回执不可修改；纠正解释需要新建经验版本。")
                if previous["revision"] != expected_artifact_revision:
                    raise AgentLabProjectConflict("优化经验已经更新，请读取新版本后纠正。")
                if not body.get("correctionReason"):
                    raise AgentLabProjectValidationError("纠正经验需要说明原因。")
                body["correctsRevision"] = previous["revision"]
                request["input"] = body
                request_json = _json(request)
            self._validate_links(conn, project_id, body)
            artifact = self.projects._publish(conn, project, {
                **({"artifactId": artifact_id} if artifact_id else {}),
                "expectedArtifactRevision": expected_artifact_revision,
                "title": index["title"], "summary": index["summary"],
                "kind": "optimization_" + index["entryKind"], "view": "json", "content": body,
            })
            project["revision"] += 1
            project["updatedAtMs"] = _now()
            conn.execute("UPDATE agent_lab_projects SET revision=?,payload_json=?,updated_at_ms=? WHERE project_id=? AND scope_id=?",
                (project["revision"], _json(project), project["updatedAtMs"], project_id, self.projects.scope_id))
            identifier_key = "patternId" if index["entryKind"] == "pattern" else "outcomeId"
            item = {**index, identifier_key: artifact["artifactId"], "artifactId": artifact["artifactId"],
                "revision": artifact["revision"], "updatedAtMs": artifact["updatedAtMs"]}
            response = {"ok": True, "projectId": project_id, "projectRevision": project["revision"],
                "artifactId": artifact["artifactId"], "artifactRevision": artifact["revision"],
                "bodySha256": _hash(body), "item": item, "replayed": False}
            conn.execute("INSERT INTO agent_lab_project_commands(client_request_id,project_id,request_json,response_json,created_at_ms) VALUES(?,?,?,?,?)",
                (receipt_key, project_id, request_json, _json(response), _now()))
            return response

    def _validate_links(self, conn, project_id: str, body: Mapping) -> None:
        for link in body.get("interventions", []):
            _, outcome = self._managed_artifact(conn, project_id, link["outcomeId"])
            if outcome["entryKind"] != "outcome":
                raise AgentLabProjectValidationError("干预必须引用已持久化的结果回执。")
            relation = link["relationship"]
            if (relation == "supports" and (outcome["decision"] != "kept" or outcome["effectStatus"] != "improved")
                or relation == "contradicts" and outcome["effectStatus"] != "regressed"
                or relation == "rejected" and outcome["decision"] != "rejected"):
                raise AgentLabProjectValidationError("经验解释与已记录的干预结果不一致。")
        for link in body.get("supersedes", []):
            _, item = self._managed_artifact(conn, project_id, link["patternId"], link["revision"])
            if item["entryKind"] != "pattern":
                raise AgentLabProjectValidationError("只有经验模式可以被替代；原始结果不可撤回。")

    def save_pattern(self, project_id: str, value: Mapping, *, expected_revision: int | None,
                     client_request_id: str, evidence_context: Mapping,
                     pattern_id: str = "", expected_pattern_revision: int = 0) -> dict:
        project_id = _text(project_id, "项目标识")
        if evidence_context.get("optimizationProjectId") not in {None, "", project_id}:
            raise AgentLabProjectValidationError("当前证据属于另一个优化项目。")
        value = _object(value, {"title", "summary", "scope", "symptoms", "observations", "hypotheses",
            "counterevidence", "interventions", "correctionReason", "supersedes"}, "优化经验")
        anchor, evidence = inspection_sources(evidence_context)
        used_ids = set()
        body = {"schemaVersion": SCHEMA_VERSION, "scope": _scope(project_id, value.get("scope", {})),
            "title": _text(value.get("title"), "经验标题", 240),
            "summary": _text(value.get("summary"), "经验摘要", 1000),
            "symptoms": _texts(value.get("symptoms", []), "症状", 12, 120),
            "correctionReason": _text(value.get("correctionReason", ""), "纠正原因", 1000, optional=True),
            "correctsRevision": expected_pattern_revision if pattern_id else 0, "sourceContext": anchor}
        for field in ("observations", "hypotheses", "counterevidence"):
            body[field] = []
            for row in _array(value.get(field, []), field, 16):
                row = _object(row, {"statement", "evidenceIds", "uncertainty"} if field == "hypotheses" else {"statement", "evidenceIds"}, field)
                refs = _texts(row.get("evidenceIds", []), "当前证据", 16)
                if (field != "hypotheses" and not refs) or any(ref not in evidence for ref in refs):
                    raise AgentLabProjectValidationError("观察与反证必须引用当前冻结来源；历史经验不能冒充本次证据。")
                used_ids.update(refs)
                normalized = {"statement": _text(row.get("statement"), field, 2000), "evidenceIds": refs,
                    "authority": "analysis_hypothesis" if field == "hypotheses" else "source_observation"}
                if field == "hypotheses":
                    normalized["uncertainty"] = _text(row.get("uncertainty"), "假设的不确定性", 1000)
                body[field].append(normalized)
        if not body["observations"]:
            raise AgentLabProjectValidationError("保存模式需要至少一条有来源的观察。")
        body["evidenceRefs"] = [{key: item for key, item in evidence[evidence_id].items() if key not in {"summary", "summaryTruncated"}}
            for evidence_id in sorted(used_ids)]
        body["interventions"] = []
        counts = {key: 0 for key in sorted(_RELATIONS)}
        for row in _array(value.get("interventions", []), "已尝试的干预", 24):
            row = _object(row, {"outcomeId", "relationship", "note"}, "干预解释")
            relation = row.get("relationship")
            if not isinstance(relation, str) or relation not in _RELATIONS:
                raise AgentLabProjectValidationError("干预关系无效。")
            body["interventions"].append({"outcomeId": _text(row.get("outcomeId"), "结果标识"),
                "relationship": relation, "note": _text(row.get("note", ""), "干预说明", 1000, optional=True)})
            counts[relation] += 1
        if len({row["outcomeId"] for row in body["interventions"]}) != len(body["interventions"]):
            raise AgentLabProjectValidationError("一次干预结果只能关联一次。")
        body["supersedes"] = []
        for row in _array(value.get("supersedes", []), "被替代模式", 8):
            row = _object(row, {"patternId", "revision"}, "被替代模式")
            body["supersedes"].append({"patternId": _text(row.get("patternId"), "模式标识"), "revision": _integer(row.get("revision"), 1)})
        body["knowledgeStatus"] = "contested" if counts["contradicts"] or body["counterevidence"] else "supported" if counts["supports"] else "observed"
        index = {"entryKind": "pattern", **{key: body[key] for key in ("title", "summary", "scope", "symptoms", "knowledgeStatus", "supersedes")},
            "observationCount": len(body["observations"]), "hypothesisCount": len(body["hypotheses"]),
            "interventionCounts": counts, "sourceCount": len({key for item in body["evidenceRefs"] for key in item["targetKeys"]})}
        return self._write(project_id, action=_PATTERN_ACTION, body=body, index=index,
            client_request_id=client_request_id, expected_revision=expected_revision,
            artifact_id=pattern_id, expected_artifact_revision=expected_pattern_revision)

    def record_report(self, report: Mapping) -> dict:
        """Host-only ingestion after durable report completion; no model call."""
        project_id = _text(report.get("optimizationProjectId"), "报告的优化项目")
        if report.get("status") != "completed" or not isinstance(report.get("result"), Mapping):
            raise AgentLabProjectValidationError("只能整理已持久完成的结构化诊断报告。")
        report_id = _text(report.get("reportId"), "报告标识")
        items, skipped = [], []
        for finding in report["result"].get("findings", [])[:24]:
            if not isinstance(finding, Mapping):
                continue
            finding_id = str(finding.get("findingId") or "")
            refs = finding.get("evidenceIds", [])
            if not refs or not finding.get("observation"):
                skipped.append(finding_id)
                continue
            value = {"title": str(finding.get("observation"))[:240],
                "summary": str(finding.get("conclusion") or finding.get("observation"))[:1000], "scope": {},
                "symptoms": [str(finding.get("dimensionId") or "trace")[:120]],
                "observations": [{"statement": str(finding["observation"])[:2000], "evidenceIds": list(refs)[:16]}],
                "hypotheses": ([{"statement": str(finding["hypothesis"])[:2000], "evidenceIds": list(refs)[:16],
                    "uncertainty": "诊断解释；需要真实候选与同条件重测验证。"}] if finding.get("hypothesis") else [])}
            identity = _hash([report_id, finding_id, value])
            items.append(self.save_pattern(project_id, value, expected_revision=None,
                client_request_id="report-" + identity, evidence_context=report))
        return {"ok": True, "projectId": project_id, "items": items, "skippedFindingIds": skipped,
            "truncated": len(report["result"].get("findings", [])) > 24}

    def record_outcome(self, project_id: str, receipt_ref: Mapping, *, candidate_context: Mapping) -> dict:
        """Load a persisted owning-service receipt; never accept outcome prose.

        The reader is injected by AgentService and may only read existing
        Trace/Lab/Eval owners. Candidate context likewise comes from the frozen
        host candidate. Public tools must not expose this method.
        """
        project_id = _text(project_id, "项目标识")
        receipt_ref = _object(receipt_ref, {"kind", "id"}, "结果回执引用")
        kind = _text(receipt_ref.get("kind"), "回执类型")
        identifier = _text(receipt_ref.get("id"), "回执标识")
        if kind != "trace_optimization_comparison" or self.receipt_reader is None:
            raise AgentLabProjectValidationError("此结果回执尚未连接可信的拥有者。")
        receipt = self.receipt_reader(kind, identifier)
        if not isinstance(receipt, Mapping) or receipt.get("comparisonId") != identifier:
            raise AgentLabProjectNotFound("候选比较的持久回执不存在。")
        candidate_id = _text(candidate_context.get("candidateId"), "候选标识")
        if (receipt.get("optimizationProjectId") != project_id or candidate_context.get("optimizationProjectId") != project_id
            or receipt.get("candidateId") != candidate_id or receipt.get("reportId") != candidate_context.get("reportId")):
            raise AgentLabProjectValidationError("结果、候选和优化项目的来源绑定不一致。")
        execution = receipt.get("executionStatus")
        effect = receipt.get("effectStatus")
        decision = receipt.get("decision")
        if execution not in _TERMINAL | {"not_started"} or effect not in {"improved", "neutral", "regressed", "not_run", "unverified"} or decision not in {"kept", "rejected", "needs_validation"}:
            raise AgentLabProjectValidationError("只能保存已结算且具有明确效果边界的结果。")
        if (execution != "completed" and effect not in {"not_run", "unverified"}
            or decision == "kept" and (execution != "completed" or effect not in {"improved", "neutral"})):
            raise AgentLabProjectValidationError("回执的执行、效果与版本建议互相矛盾。")
        contract = candidate_context.get("comparisonContract", {})
        contract = dict(contract) if isinstance(contract, Mapping) else {}
        scope = _scope(project_id, {"componentRef": candidate_context.get("targetRef", ""),
            "componentVersion": candidate_context.get("parentVersionRef", ""), "inputClass": contract.get("inputClass", "")})
        summary = _text(candidate_context.get("summary"), "干预摘要", 1000)
        receipt_snapshot = {key: receipt[key] for key in ("comparisonId", "candidateId", "reportId", "optimizationProjectId",
            "executionStatus", "effectStatus", "decision", "createdAtMs") if key in receipt}
        receipt_snapshot["evidenceRefs"] = _texts(receipt.get("evidenceRefs", []), "结果证据", 1024)
        # No arbitrary result body or evaluation answers enter optimization
        # context. Hash the full immutable receipt to preserve exact provenance.
        receipt_hash = _hash({key: value for key, value in receipt.items() if key != "contentSha256"})
        if receipt.get("contentSha256") and str(receipt["contentSha256"]).removeprefix("sha256:") != receipt_hash:
            raise AgentLabProjectValidationError("结果回执的内容指纹不一致。")
        body = {"schemaVersion": SCHEMA_VERSION, "scope": scope, "candidateId": candidate_id,
            "summary": summary, "receiptRef": {"kind": kind, "id": identifier, "sha256": receipt_hash},
            "receipt": receipt_snapshot, "contextFingerprint": _hash(contract),
            "candidateVersionRef": _text(candidate_context.get("candidateVersionRef", ""), "候选版本", 240, optional=True),
            "authority": "host_receipt", "applicationStatus": "not_inferred"}
        index = {"entryKind": "outcome", "title": summary[:240], "summary": summary, "scope": scope,
            "candidateId": candidate_id, "executionStatus": execution, "effectStatus": effect,
            "decision": decision, "receiptRef": body["receiptRef"], "contextFingerprint": body["contextFingerprint"]}
        # Identity excludes receipt text: changing content for the same immutable
        # ID is a conflict, not a second experiment or silently corrected fact.
        return self._write(project_id, action=_OUTCOME_ACTION, body=body, index=index,
            client_request_id="outcome-" + _hash([project_id, kind, identifier]))

    def query(self, project_id: str, *, query: str = "", component_ref: str = "", component_version: str = "",
              input_class: str = "", context_fingerprint: str = "", limit: int = 8, max_chars: int = 12000,
              include_superseded: bool = False) -> dict:
        project_id = _text(project_id, "项目标识")
        query = _text(query, "经验检索", 500, optional=True)
        component_ref = _text(component_ref, "组件", 240, optional=True)
        component_version = _text(component_version, "组件版本", 240, optional=True)
        input_class = _text(input_class, "输入类别", 240, optional=True)
        context_fingerprint = _text(context_fingerprint, "对照条件指纹", 80, optional=True)
        limit = _integer(limit, 1, 24)
        max_chars = _integer(max_chars, 1024, 32000)
        if not isinstance(include_superseded, bool):
            raise AgentLabProjectValidationError("被替代经验的显示选项无效。")
        self.projects.initialize()
        with self.projects._connection() as conn:
            conn.execute("BEGIN")
            self.projects._project(conn, project_id)
            entries = self._managed_items(conn, project_id)
        superseded = {(link["patternId"], link["revision"]): {"patternId": item["patternId"], "revision": item["revision"]}
            for item in entries if item["entryKind"] == "pattern" for link in item.get("supersedes", [])}
        scored = []
        for item in entries:
            item = copy.deepcopy(item)
            scope = item["scope"]
            if component_ref and scope["componentRef"] not in {"", component_ref}:
                continue
            if input_class and scope["inputClass"] not in {"", input_class} and item["entryKind"] != "outcome":
                continue
            replaced_by = superseded.get((item["artifactId"], item["revision"]))
            if replaced_by:
                item["knowledgeStatus"] = "superseded"
                item["supersededBy"] = replaced_by
                if not include_superseded:
                    continue
            haystack = " ".join([item["title"], item["summary"], *item.get("symptoms", []), scope["componentRef"], scope["inputClass"]]).casefold()
            terms = query.casefold().split()
            hits = sum(term in haystack for term in terms)
            if terms and not hits:
                continue
            if item["entryKind"] == "outcome":
                changed = bool(component_version and scope["componentVersion"] and component_version != scope["componentVersion"]
                    or input_class and scope["inputClass"] and input_class != scope["inputClass"]
                    or context_fingerprint and context_fingerprint != item["contextFingerprint"])
                item["retryAssessment"] = "context_changed_reconsider" if changed else "same_context_requires_reason" if component_version or context_fingerprint or input_class else "context_unknown"
            score = hits * 10 + int(bool(component_version and scope["componentVersion"] == component_version)) * 3
            scored.append((score, item["updatedAtMs"], item["artifactId"], item))
        scored.sort(key=lambda row: row[:3], reverse=True)
        patterns = [row[-1] for row in scored if row[-1]["entryKind"] == "pattern"]
        attempts = [row[-1] for row in scored if row[-1]["entryKind"] == "outcome"]
        packet = {"ok": True, "schemaVersion": SCHEMA_VERSION, "projectId": project_id,
            "patterns": patterns[:limit], "attempts": attempts[:limit], "truncated": False,
            "omittedCounts": {"patterns": max(0, len(patterns) - limit), "attempts": max(0, len(attempts) - limit)}}
        while len(_json(packet)) > max_chars and (packet["patterns"] or packet["attempts"]):
            key = "patterns" if len(_json(packet["patterns"])) >= len(_json(packet["attempts"])) else "attempts"
            packet[key].pop()
            packet["omittedCounts"][key] += 1
        packet["truncated"] = any(packet["omittedCounts"].values())
        return packet

    def read(self, project_id: str, pattern_id: str, *, revision: int | None = None,
             max_chars: int = 12000, offset: int = 0) -> dict:
        project_id = _text(project_id, "项目标识")
        pattern_id = _text(pattern_id, "经验或结果标识")
        max_chars = _integer(max_chars, 1024, 32000)
        offset = _integer(offset, 0, 500000)
        self.projects.initialize()
        with self.projects._connection() as conn:
            conn.execute("BEGIN")
            self.projects._project(conn, project_id)
            artifact, index = self._managed_artifact(conn, project_id, pattern_id, revision)
        encoded = _json(artifact["content"])
        packet = {"ok": True, "projectId": project_id, "item": index, "body": artifact["content"],
            "bodySha256": _hash(artifact["content"]), "offset": offset, "nextOffset": None, "truncated": False}
        if offset == 0 and len(_json(packet)) <= max_chars:
            return packet
        if offset >= len(encoded):
            raise AgentLabProjectValidationError("正文读取位置超出此版本范围。")
        # In small packets keep the exact version identity, not a large summary.
        packet["item"] = {key: index[key] for key in ("artifactId", "revision", "entryKind")}
        packet["body"] = None
        take = min(len(encoded) - offset, max_chars - 500)
        while take > 0:
            packet.update(bodyText=encoded[offset:offset + take],
                nextOffset=offset + take if offset + take < len(encoded) else None, truncated=offset > 0 or offset + take < len(encoded))
            if len(_json(packet)) <= max_chars:
                return packet
            take -= max(1, (len(_json(packet)) - max_chars + 1) // 2)
        raise AgentLabProjectValidationError("正文引用超出读取预算。")

    def prepare_distillation(self, project_id: str, *, inspection: Mapping, capabilities: list[Mapping],
                             query: str = "", max_chars: int = 20000) -> dict:
        from .optimization_distillation import prepare_distillation
        return prepare_distillation(self, project_id, inspection=inspection, capabilities=capabilities,
            query=query, max_chars=max_chars)

    @staticmethod
    def evaluate_distillation(packet: Mapping, proposals: list[Mapping], *, capabilities: list[Mapping] | None = None) -> dict:
        from .optimization_distillation import evaluate_distillation
        return evaluate_distillation(packet, proposals, capabilities=capabilities)
