"""Read-only candidate evidence, joined through exact frozen artifact identities.

This module never runs an Agent, imports a database, applies a candidate, or
changes a score contract. The explicit export path reuses the existing exact
offline scorer; the installed read path only verifies the resulting public
receipt. A live GET never requires private files or loads a scorer.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Mapping


_EXPERIMENT_ID = "enterprise-rag.luna-prompt-v4-standard-r6.v1"
_PUBLIC_RUNS = "eval/interview-metrics/runs/"
PUBLIC_EVIDENCE_REF = f"{_PUBLIC_RUNS}agent-lab-candidate-evidence-enterprise-rag-r6.v1.json"
_REPORTS = ".rag-ime-data/eval/results/"
_HOST = ".rag-ime-data/eval/host/"
_STANDARD = "eval/interview-metrics/"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CASE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$")
_FROZEN_CONTROLS = (
    "caseIdsSha256", "datasetSplitSha256", "answerCaseSetSha256",
    "permissionSha256", "toolTransport", "skillSha256", "runtimeContractSha256",
    "evaluationSplit",
)


def project_candidate_evidence(
    experiment: Mapping[str, object], *, root: Path,
) -> dict[str, object] | None:
    if experiment.get("experimentId") != _EXPERIMENT_ID:
        return None
    try:
        receipt = _bound_json(root, PUBLIC_EVIDENCE_REF, prefix=_PUBLIC_RUNS)
        _verify_self_hash(receipt, "receiptSha256")
        expected = {
            "schemaVersion": "rag-ime.agent-lab-candidate-evidence.v1",
            "experimentId": experiment["experimentId"],
            "experimentRevisionSha256": experiment["revisionSha256"],
            "baselineRunId": _mapping(experiment.get("baseline")).get("runId"),
            "candidateRunId": _mapping(experiment.get("candidate")).get("runId"),
            "manifestSha256": _mapping(experiment.get("dataset")).get("manifestSha256"),
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ValueError("public evidence belongs to a different experiment revision")
        evidence = _mapping(receipt.get("evidence"))
        from .contracts.json_schema import load_contract, validate_contract
        validate_contract(evidence, {"$ref": "#/$defs/optimizationEvidence", "$defs": load_contract("agent-lab-experiment.v1.json")["$defs"]})
        return evidence
    except (OSError, ValueError, TypeError, KeyError):
        result = _empty_evidence(experiment)
        result["gaps"].append("公共候选证据回执缺失或不匹配此实验 revision；未生成推测 diff 或逐 Case 结果。")
        return result


def _empty_evidence(experiment: Mapping[str, object]) -> dict[str, object]:
    baseline = _mapping(experiment.get("baseline"))
    run_id = str(baseline.get("runId") or "")
    return {
        "status": "unavailable",
        "provenance": "existing_run_artifacts",
        "patch": {"status": "unavailable", "kind": "frozen_configuration", "artifactPath": "", "beforeRef": "", "afterRef": "", "unifiedDiff": "", "reason": "冻结运行配置尚不可读。"},
        "baselineTrace": _trace_binding(run_id, {}),
        "caseComparisons": [],
        "validationBoundary": {"candidateAware": True, "candidateBlind": False, "heldOutOpened": False, "unbiasedPromotionClaimAllowed": False, "costAuthority": "unavailable"},
        "gaps": [],
    }


def build_candidate_evidence(
    experiment: Mapping[str, object], *, root: Path,
) -> dict[str, object] | None:
    """Explicit offline export only; never call from a live read projection."""
    if experiment.get("experimentId") != _EXPERIMENT_ID:
        return None
    baseline = _mapping(experiment.get("baseline"))
    run_id = str(baseline.get("runId") or "")
    result = _empty_evidence(experiment)
    gaps: list[str] = []
    result["gaps"] = gaps
    try:
        before_receipt = _rescore_receipt(root, baseline)
        after_receipt = _rescore_receipt(root, _mapping(experiment.get("candidate")))
        if before_receipt["standard"] != after_receipt["standard"] or before_receipt["qrels"] != after_receipt["qrels"]:
            raise ValueError("Standard or qrels identity mismatch")
        for receipt in (before_receipt, after_receipt):
            if receipt.get("heldOutOpened") is not False or receipt.get("unbiasedPromotionClaimAllowed") is not False:
                raise ValueError("Validation boundary mismatch")
        standard_ref = _mapping(before_receipt.get("standard"))
        if standard_ref.get("manifestSha256") != _mapping(experiment.get("dataset")).get("manifestSha256"):
            raise ValueError("experiment manifest mismatch")
        authorities = {
            _mapping(_mapping(_mapping(receipt.get("agenticResult")).get("costSourceReference")).get("companionCostReceipt")).get("authority")
            for receipt in (before_receipt, after_receipt)
        }
        if authorities == {"runtime_cost_reconciled"}:
            result["validationBoundary"]["costAuthority"] = "runtime_cost_reconciled"
    except (OSError, ValueError, TypeError, KeyError):
        gaps.append("缺少匹配的 r6 原始回执，或冻结身份不一致；不生成候选对比。")
        return result

    try:
        before_report, before_ref = _source_report(root, before_receipt)
        after_report, after_ref = _source_report(root, after_receipt)
        result["patch"] = _configuration_patch(before_report, after_report, before_ref=before_ref, after_ref=after_ref)
        result["baselineTrace"] = _trace_binding(run_id, before_report)
        result["status"] = "partial"
    except (OSError, ValueError, TypeError, KeyError):
        gaps.append("本机缺少 hash-bound 冻结输出；公共汇总可读，但实际配置 diff 与逐 Case 明细暂不可用。")
        return result

    try:
        before_controls = _mapping(before_report.get("conditions"))
        after_controls = _mapping(after_report.get("conditions"))
        if any(not before_controls.get(key) or before_controls[key] != after_controls.get(key) for key in _FROZEN_CONTROLS):
            raise ValueError("frozen control drift")
        qrel_ref = _mapping(before_receipt.get("qrels"))
        standard = _bound_json(root, str(standard_ref["path"]), prefix=_STANDARD, expected_sha256=str(standard_ref["fileSha256"]))
        qrels = _bound_json(root, str(qrel_ref["path"]), prefix=_HOST, expected_sha256=str(qrel_ref["fileSha256"]))
        # The Host-only bodies stay inside the established deterministic scorer.
        # No raw question, answer, quote, document ID or qrels leaves this module.
        from scripts.rescore_enterprise_rag_answer_evidence import (
            _private_qrels_from_artifact, _report_cases_and_evidence,
            _rescore_lanes, _quality_projection, _assert_rescore_scope,
        )
        scored_cases: list[list[dict[str, object]]] = []
        for report, receipt in ((before_report, before_receipt), (after_report, after_receipt)):
            cases, _, rubric_facts = _report_cases_and_evidence(report)
            private_qrels, _ = _private_qrels_from_artifact(qrels=qrels, standard=standard, source_cases=cases, rubric_facts=rubric_facts)
            lanes = _rescore_lanes(source_report=report, cases=cases, private_qrels=private_qrels)
            _assert_rescore_scope(report["lanes"], lanes)
            lane = next(item for item in lanes if item["lane"] == "agentic")
            if _quality_projection(lane) != receipt["resultsByLane"]["agentic"]["qualityAfter"]:
                raise ValueError("current scorer does not reproduce frozen receipt")
            scored_cases.append(lane["score"]["answerCases"])
        comparisons = _case_comparisons(*scored_cases)
        if len(comparisons) != _mapping(experiment.get("dataset")).get("caseCount"):
            raise ValueError("case denominator mismatch")
        result["caseComparisons"] = comparisons
    except (OSError, ValueError, TypeError, KeyError, StopIteration, ImportError):
        gaps.append("逐 Case 重建所需的 Host 冻结证据缺失、身份不符或 scorer 不能复现原回执；未显示推测结果。")
    if result["baselineTrace"]["status"] != "bound":
        gaps.append("冻结报告只有 Session/turn 哈希，未保留可回跳的精确 Baseline Trace ID。")
    if result["caseComparisons"] and not gaps:
        result["status"] = "available"
    return result


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bound_json(root: Path, ref: str, *, prefix: str, expected_sha256: str | None = None) -> dict[str, object]:
    relative = PurePosixPath(ref)
    if not ref.startswith(prefix) or relative.is_absolute() or ".." in relative.parts or "\\" in ref or not ref.endswith(".json"):
        raise ValueError("artifact is outside the supported owner")
    owner = (root / prefix).resolve()
    path = (root / ref).resolve(strict=True)
    if not owner.is_relative_to(root.resolve()) or not path.is_relative_to(owner) or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("artifact is outside the bounded owner")
    data = path.read_bytes()
    if expected_sha256 is not None and (not _SHA256.fullmatch(expected_sha256) or hashlib.sha256(data).hexdigest() != expected_sha256):
        raise ValueError("artifact hash mismatch")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("artifact is not an object")
    return payload


def _verify_self_hash(payload: Mapping[str, object], field: str) -> None:
    claimed = str(payload.get(field) or "")
    raw = json.dumps({key: value for key, value in payload.items() if key != field}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if not _SHA256.fullmatch(claimed) or hashlib.sha256(raw.encode()).hexdigest() != claimed:
        raise ValueError("artifact self-hash mismatch")


def _rescore_receipt(root: Path, run: Mapping[str, object]) -> dict[str, object]:
    refs = run.get("evidenceRefs")
    refs = refs if isinstance(refs, list) else []
    matches = [ref for ref in refs if isinstance(ref, str) and ref.startswith(_PUBLIC_RUNS) and ref.endswith("-attention-r6-exact-offline-rescore-20260905.v1.json")]
    if len(matches) != 1:
        raise ValueError("exact rescore receipt missing")
    receipt = _bound_json(root, matches[0], prefix=_PUBLIC_RUNS)
    _verify_self_hash(receipt, "receiptSha256")
    usage = _mapping(_mapping(receipt.get("agenticResult")).get("costSourceReference"))
    if usage.get("sourceUsageRef") != f"runtime-cost:{run.get('runId')}":
        raise ValueError("receipt belongs to a different run")
    return receipt


def _source_report(root: Path, receipt: Mapping[str, object]) -> tuple[dict[str, object], str]:
    source = _mapping(_mapping(receipt.get("sourceEvidence")).get("frozenCandidateReport"))
    ref = str(source["path"])
    report = _bound_json(root, ref, prefix=_REPORTS, expected_sha256=str(source["fileSha256"]))
    _verify_self_hash(report, "reportSha256")
    if report.get("reportSha256") != source.get("reportSha256"):
        raise ValueError("frozen report identity mismatch")
    return report, ref


def _configuration_patch(before: Mapping[str, object], after: Mapping[str, object], *, before_ref: str, after_ref: str) -> dict[str, object]:
    # Actual frozen configuration values, not narrative factor summaries and
    # not a claim that a historical Git/source patch was retained.
    keys = ("model", "thinking", "promptProfile", "promptContractVersion", "agenticSupplementalLimit", "toolTransport")
    lines = [json.dumps({key: _mapping(report.get("conditions"))[key] for key in keys if key in _mapping(report.get("conditions"))}, ensure_ascii=False, indent=2, sort_keys=True).splitlines(keepends=True) for report in (before, after)]
    diff = "".join(difflib.unified_diff(*lines, fromfile="baseline/conditions.json", tofile="candidate/conditions.json", lineterm="\n"))
    return {
        "status": "available", "kind": "frozen_configuration",
        "artifactPath": f"{after_ref}#conditions", "beforeRef": f"{before_ref}#conditions", "afterRef": f"{after_ref}#conditions",
        "unifiedDiff": diff,
        "reason": "从两份 hash-bound 冻结 Run 的配置生成实际 diff；这是配置变化，未声称保留了历史源码补丁。",
    }


def _trace_binding(run_id: str, report: Mapping[str, object]) -> dict[str, object]:
    raw = report.get("traceIds")
    trace_ids = list(dict.fromkeys(item for item in raw if isinstance(item, str) and re.fullmatch(r"trace:[a-zA-Z0-9:._-]{1,200}", item)))[:32] if isinstance(raw, list) else []
    return {"runId": run_id, "status": "bound" if trace_ids else "unavailable", "traceIds": trace_ids, "reason": "冻结报告显式绑定的 Trace。" if trace_ids else "原始报告未提供精确 Trace ID；Session/turn 哈希不是 Trace 身份。"}


def _case_comparisons(before: list[dict[str, object]], after: list[dict[str, object]]) -> list[dict[str, object]]:
    def index(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
        result = {str(row.get("evaluationCaseId") or ""): row for row in rows}
        if not result or len(result) != len(rows) or len(result) > 64 or any(not _CASE_ID.fullmatch(key) for key in result):
            raise ValueError("invalid or duplicate Case identities")
        return result

    old, new = index(before), index(after)
    if old.keys() != new.keys():
        raise ValueError("Case identities changed")

    def summary(row: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(row.get("agentSuccess"), bool):
            raise ValueError("Case has no scored outcome")
        metrics: dict[str, float | int] = {}
        for key in ("agentSuccess", "answerJudgeCorrect", "citationFactCoverage", "toolSuccess", "abstentionCorrect", "abstentionExpected"):
            value = row.get(key)
            if isinstance(value, bool):
                metrics[key] = int(value)
            elif isinstance(value, (int, float)) and math.isfinite(value):
                metrics[key] = value
        return {"status": "passed" if row["agentSuccess"] else "failed", "metrics": metrics}

    rows: list[dict[str, object]] = []
    for case_id in old:
        if old[case_id].get("abstentionExpected") != new[case_id].get("abstentionExpected"):
            raise ValueError("Case meaning changed")
        rows.append({"caseId": case_id, "before": summary(old[case_id]), "after": summary(new[case_id])})
    return rows
