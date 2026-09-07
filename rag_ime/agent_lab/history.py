"""Import existing public experiment evidence without re-running or rescoring it."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping

from .projects import AgentLabProjectConflict, AgentLabProjectValidationError

SCENES = (
    ("enterpriseops", "企业客户支持", {"enterprise-customer-support", "agent-evaluation-cost"}),
    ("enterprise-rag", "企业知识库问答", {"enterprise-knowledge-retrieval"}),
    ("cloudops", "云上事故诊断", {"cloudops-incident-diagnosis"}),
    ("memory", "长期记忆整理", {"memory-maintenance", "personal-memory-and-rag"}),
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


def prepare_history_import(value: Mapping, experiments: list[dict]) -> dict:
    if set(value) != {"sceneId", "sourceHash"}:
        raise AgentLabProjectValidationError("请选择已有实验集合及其来源版本。")
    collection = next((row for row in history_collections(experiments) if row["sceneId"] == value["sceneId"]), None)
    if collection is None:
        raise AgentLabProjectValidationError("这组已有实验暂时不可读取，请重新读取。")
    if collection["sourceHash"] != value["sourceHash"]:
        raise AgentLabProjectConflict("已有实验来源已更新，请重新读取后导入。")
    records = collection["records"]
    rows, metrics = [], []
    narrative = [f"# {collection['title']} · 已有实验", "",
                 "这些记录来自迁移前的实验。导入没有运行模型、重新评分或改变历史结论。", "",
                 "## 当前保留的对照", ""]
    ordered = sorted(records, key=lambda row: (row.get("projectionState") != "current", -row["importedAtMs"]))
    for row in ordered:
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
                {"title": "原始评测记录", "kind": "experiment_snapshot", "view": "json", "content": {
                    "schemaVersion": "paw.lab-imported-experiments.v1", "sourceHash": collection["sourceHash"],
                    "executionPerformed": False, "experiments": records}},
            ]}
