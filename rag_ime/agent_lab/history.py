"""Import existing public experiment evidence without re-running or rescoring it."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping

from .projects import AgentLabProjectConflict, AgentLabProjectValidationError

SCENES = (
    ("enterpriseops", "企业客户支持", {"enterprise-customer-support"}),
    ("enterprise-rag", "企业知识库问答", {"enterprise-knowledge-retrieval"}),
    ("trace-agent", "Trace Agent 诊断", {"agent-runtime-diagnosis-and-repair"}),
    ("cloudops", "云上事故诊断", {"cloudops-incident-diagnosis"}),
    ("memory", "长期记忆整理", {"memory-maintenance", "personal-memory-and-rag"}),
    ("model-cost", "模型成本门禁", {"agent-evaluation-cost"}),
)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def history_collections(experiments: list[dict]) -> list[dict]:
    collections = []
    for scene_id, title, verticals in SCENES:
        records = sorted((copy.deepcopy(row) for row in experiments if row.get("vertical") in verticals),
                         key=lambda row: (row["importedAtMs"], row["experimentId"]))
        if not records:
            continue
        collections.append({"sceneId": scene_id, "title": title, "sourceHash": _hash(records),
                            "experimentCount": len(records),
                            "datasetIds": sorted({row["dataset"]["datasetId"] for row in records}),
                            "latestEvidenceAtMs": max(row["importedAtMs"] for row in records),
                            "records": records})
    return collections


def public_history_collections(experiments: list[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if key != "records"}
            for row in history_collections(experiments)]


def _causal_previous(records: list[Mapping], row: Mapping) -> Mapping | None:
    """Return the immediate historical parent recorded by ``supersededBy``.

    The ledger can contain branches (for example model-only and prompt-only
    candidates).  A timestamp is not enough to establish causality, so prefer
    the explicit successor link and only use a deterministic fallback when an
    old record omitted it.
    """
    experiment_id = row.get("experimentId", "")
    parent = next((candidate for candidate in records
                   if candidate.get("supersededBy") == experiment_id), None)
    if parent is not None:
        return parent
    # Legacy records may have no link.  Keep the projection readable without
    # claiming a causal relation that the source did not record.
    return None


def _failure_evidence(row: Mapping, previous: Mapping | None) -> list[dict]:
    """Project only source-backed failure signals for the causal card."""
    evidence = []
    if previous is not None:
        comparison = previous.get("comparison", {})
        evidence.extend({"kind": "metric", "source": "previous_candidate",
                         "metric": delta.get("metric", ""),
                         "baseline": delta.get("before"), "candidate": delta.get("after"),
                         "delta": delta.get("delta")}
                        for delta in comparison.get("metricDeltas", []))
        evidence.extend({"kind": "output", "source": "previous_candidate",
                         "caseId": item.get("caseId", ""),
                         "before": item.get("before", ""), "after": item.get("after", "")}
                        for item in comparison.get("outputComparisons", []))
        evidence.extend({"kind": "open_gap", "source": "previous_record",
                         "detail": gap} for gap in previous.get("openGaps", []))
    # Current open gaps remain useful even when this is the first recorded
    # experiment; they are explicitly marked as gaps rather than failures.
    evidence.extend({"kind": "open_gap", "source": "current_record",
                     "detail": gap} for gap in row.get("openGaps", []))
    return evidence


def _stepwise_record(row: Mapping, previous: Mapping | None = None) -> dict:
    """Project the ledger into a readable experiment recipe without rerunning it.

    The source snapshot remains authoritative.  This projection deliberately
    keeps Prompt/tool/workflow changes and their evidence beside the measured
    effect so a user can understand *why* a candidate changed and what the
    result does (and does not) prove.
    """
    factors = copy.deepcopy(row.get("factors", []))
    steps = []
    for number, factor in enumerate(factors, 1):
        steps.append({"step": number, "layer": factor.get("name", "unknown"),
                      "before": factor.get("before", ""), "after": factor.get("after", ""),
                      "reason": factor.get("reason", "")})
    return {
        "experimentId": row.get("experimentId", ""), "title": row.get("title", ""),
        "status": row.get("status", ""), "decision": row.get("comparison", {}).get("decision", "unknown"),
        "comparedTo": previous.get("experimentId", "") if previous else "",
        "previousDecision": previous.get("comparison", {}).get("decision", "") if previous else "",
        "whyContinue": ("；".join(step["reason"] for step in steps if step["reason"]) if previous else
                         "这是本实验链的起始对照；后续修改必须基于可核查的失败证据。"),
        "continuation": {"fromExperimentId": previous.get("experimentId", "") if previous else "",
                         "fromDecision": previous.get("comparison", {}).get("decision", "") if previous else "",
                         "decisionReason": row.get("comparison", {}).get("decisionReason", ""),
                         "failureEvidence": _failure_evidence(row, previous)},
        "steps": steps,
        "promptChanges": [step for step in steps if step["layer"] in {"prompt", "system_prompt"}],
        "toolChanges": [step for step in steps if step["layer"] in {"tool", "tool_contract"}],
        "workflowChanges": [step for step in steps if step["layer"] in {"workflow", "execution_policy"}],
        "modelChanges": [step for step in steps if step["layer"] == "model"],
        "skillAndContextChanges": [step for step in steps if step["layer"] in {"skill", "context", "memory", "rag"}],
        "assetChanges": copy.deepcopy(row.get("createdOrModifiedAssets", [])),
        "recommendations": copy.deepcopy(row.get("recommendations", [])),
        "frozenControls": copy.deepcopy(row.get("frozenControls", [])),
        "baseline": copy.deepcopy(row.get("baseline", {})),
        "candidate": copy.deepcopy(row.get("candidate", {})),
        "effect": copy.deepcopy(row.get("comparison", {})),
        "metricDeltas": copy.deepcopy(row.get("comparison", {}).get("metricDeltas", [])),
        "effectStatus": row.get("effectStatus", "unknown"),
        "allowedClaim": row.get("claim", {}).get("allowed", ""),
        "forbiddenClaim": row.get("claim", {}).get("forbidden", ""),
        "evidenceRefs": sorted(set(row.get("baseline", {}).get("evidenceRefs", []) +
                                   row.get("candidate", {}).get("evidenceRefs", []))),
    }


def prepare_history_import(value: Mapping, experiments: list[dict]) -> dict:
    if set(value) != {"sceneId", "sourceHash"}:
        raise AgentLabProjectValidationError("请选择已有实验集合及其来源版本。")
    collection = next((row for row in history_collections(experiments) if row["sceneId"] == value["sceneId"]), None)
    if collection is None:
        raise AgentLabProjectValidationError("这组已有实验暂时不可读取，请重新读取。")
    if collection["sourceHash"] != value["sourceHash"]:
        raise AgentLabProjectConflict("已有实验来源已更新，请重新读取后导入。")
    records = collection["records"]
    rows, metrics, stepwise = [], [], []
    narrative = [f"# {collection['title']} · 已有实验", "",
                 "这些记录来自迁移前的实验。导入没有运行模型、重新评分或改变历史结论。", "",
                 "## 当前保留的对照", ""]
    # Preserve source order deterministically while resolving each card's
    # direct parent from the ledger's explicit supersededBy edge.
    ordered = sorted(records, key=lambda row: (row.get("importedAtMs", 0), row.get("experimentId", "")))
    for row in ordered:
        previous = _causal_previous(records, row)
        dataset = row["dataset"]
        rows.append({"experiment": row["title"], "dataset": dataset["datasetId"], "split": dataset["split"],
                     "cases": dataset["caseCount"], "decision": row["comparison"]["decision"],
                     "state": "当前对照" if row.get("projectionState") == "current" else "历史记录",
                     "reason": row["comparison"]["decisionReason"]})
        if row.get("projectionState") == "current":
            for metric in sorted(set(row["baseline"]["metrics"]) | set(row["candidate"]["metrics"])):
                metrics.append({"experiment": row["title"], "metric": metric,
                                "baseline": row["baseline"]["metrics"].get(metric),
                                "candidate": row["candidate"]["metrics"].get(metric)})
        stepwise.append(_stepwise_record(row, previous))
        narrative.extend([f"### {row['title']}", "", row["businessProblem"], "",
                          f"数据：{dataset['datasetId']}；分组：{dataset['split']}；任务数：{dataset['caseCount']}。", "",
                          f"判定：{row['comparison']['decision']}。{row['comparison']['decisionReason']}", ""])
        for factor in row["factors"]:
            narrative.extend([f"- {factor['name']}：{factor['before']} → {factor['after']}。{factor['reason']}"])
        narrative.extend(["", f"可支持的结论：{row['claim']['allowed']}", "",
                          f"结论范围：{row['claim']['forbidden']}", "",
                          f"原始实验：`{row['experimentId']}`；来源版本：`{row['revisionSha256']}`。", ""])
        refs = list(dict.fromkeys(row["baseline"]["evidenceRefs"] + row["candidate"]["evidenceRefs"]))
        narrative.extend([f"- `{ref}`" for ref in refs]); narrative.append("")
    return {"sceneId": collection["sceneId"], "sourceHash": collection["sourceHash"],
            "experimentCount": len(records), "project": {"title": collection["title"],
                "description": f"继续{collection['title']}的已有评测与优化。保留原数据、评分规则、基线、候选和失败记录；新的运行单独保存，使用实际质量与成本证据判断改动。"},
            "artifacts": [
                {"title": "实验总览", "kind": "experiment_history", "view": "table", "content": {
                    "caption": "迁移前的实验记录；本次导入没有重新运行。详细指标、改动与证据在相邻成果中。",
                    "columns": [{"key": key, "label": label} for key, label in
                                (("experiment", "实验"), ("state", "记录范围"), ("dataset", "数据集"),
                                 ("split", "分组"), ("cases", "任务数"), ("decision", "结论"), ("reason", "依据"))],
                    "rows": rows}},
                {"title": "指标对照", "kind": "experiment_history", "view": "table", "content": {
                    "caption": "当前保留对照的原始指标。apiCostUsd 是报告内估算，不是账单；latencyMs 为毫秒，耗时不单独决定采用。空值表示原报告未提供。",
                    "columns": [{"key": key, "label": label} for key, label in
                                (("experiment", "实验"), ("metric", "原始指标"), ("baseline", "基线"), ("candidate", "候选"))],
                    "rows": metrics}},
                {"title": "改动与结论", "kind": "experiment_history", "view": "markdown", "content": "\n".join(narrative)},
                {"title": "逐步实验卡", "kind": "experiment_steps", "view": "json", "content": {
                    "schemaVersion": "paw.lab-experiment-steps.v1",
                    "caption": "按原始回执整理的执行步骤、Prompt/工具/Workflow 改动与效果；没有在导入时重新执行。",
                    "experiments": stepwise}},
                {"title": "实验链", "kind": "experiment_chain", "view": "table", "content": {
                    "caption": "相邻实验之间的真实对照关系；空的对照对象表示该记录是链的起点。",
                    "columns": [{"key": key, "label": label} for key, label in
                                (("experiment", "本轮实验"), ("experimentId", "实验 ID"),
                                 ("comparedTo", "直接对照"), ("decision", "本轮判定"),
                                 ("whyContinue", "继续原因"), ("failureEvidence", "失败证据"),
                                 ("metricDeltas", "指标变化"))],
                    "rows": [{"experiment": item["title"], "experimentId": item["experimentId"],
                              "comparedTo": item["comparedTo"] or "起始对照",
                              "decision": item["decision"], "whyContinue": item["whyContinue"],
                              "failureEvidence": item["continuation"]["failureEvidence"],
                              "metricDeltas": item["metricDeltas"]} for item in stepwise]}},
                {"title": "原始评测记录", "kind": "experiment_snapshot", "view": "json", "content": {
                    "schemaVersion": "paw.lab-imported-experiments.v1", "sourceHash": collection["sourceHash"],
                    "executionPerformed": False, "experiments": records}},
            ]}
