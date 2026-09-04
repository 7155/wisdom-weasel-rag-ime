#!/usr/bin/env python3
"""Rescore one frozen Validation RAG report with exact citation-chunk qrels.

The command is deliberately offline. It reuses one hash-bound candidate report
and its accepted frozen Judge result, then calls the current production runner's
answer-only scorer. It never opens a Session, calls a Provider/Judge, or writes
the source report, qrels, or Standard. The output is an append-only public-safe
receipt containing hashes, counts, metrics, and explicit claim boundaries.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_rag_agent_ablation import (  # noqa: E402
    LANES,
    _answer_only_cited_chunk_keys,
    _apply_answer_only_judgments,
    _build_candidate_decision,
    _sha256_json,
)


DEFAULT_SOURCE_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-coverage-balanced-v4-r4-20260904.json"
)
DEFAULT_QRELS = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
DEFAULT_STANDARD = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-coverage-balanced-v4-r4-candidate-citation-r3-exact-offline-rescore-20260905.v1.json"
)
DEFAULT_RUN_ID = (
    "enterprise-rag-answer-evidence-luna-max-coverage-balanced-v4-r4-"
    "candidate-citation-r3-exact-offline-rescore-20260905"
)
OBSOLETE_RECEIPT = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-standard-v2-offline-rescore-20260904.v1.json"
)

SCHEMA_VERSION = "paw.enterprise-rag-answer-evidence-exact-offline-rescore.v2"
SOURCE_REPORT_SCHEMA_VERSION = "rag-ime.rag-agent-ablation-run.v1"
STANDARD_SCHEMA_VERSION = "rag-ime.rag-answer-evidence-standard.v2"
QRELS_SCHEMA_VERSION = "rag-ime.rag-answer-evidence-qrels.v2"
COST_RECEIPT_SCHEMA_VERSION = "rag-ime.agent-lab-cost-receipt.v1"

QUALITY_METRICS = (
    "answerJudgeCorrectnessRate",
    "answerSuccessRate",
    "highLevelFactCoverage",
    "citationFactCoverage",
    "answerableCitationSupportRate",
    "abstentionAccuracy",
    "abstentionF1",
    "infoNotFoundAbstentionRecall",
    "citationResolutionRate",
    "toolSuccessRate",
    "outputProtocolRate",
    "agentSuccessRate",
)
QRELS_OWNED_METRICS = frozenset(
    {
        "citationFactCoverage",
        "answerableCitationSupportRate",
        "citationSuccessRate",
        "agentSuccessRate",
    }
)
IMMUTABLE_CASE_FIELDS = (
    "queryId",
    "evaluationCaseId",
    "slice",
    "abstentionExpected",
    "abstained",
    "abstentionCorrect",
    "answerSha256",
    "citationTokens",
    "citations",
    "unresolvedCitations",
    "citationEvaluable",
    "citationResolution",
    "toolSuccess",
    "answerJudgeCorrect",
    "answerJudgeReasonCode",
    "answerFactCoverage",
    "answerSuccess",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {_path_label(path)}")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_label(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    return os.path.relpath(resolved, ROOT)


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _require_sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def _verify_self_hash(
    value: Mapping[str, object],
    *,
    field: str,
    label: str,
) -> str:
    claimed = _require_sha256(value.get(field), label=f"{label} {field}")
    unsigned = {str(key): item for key, item in value.items() if key != field}
    if _sha256_json(unsigned) != claimed:
        raise ValueError(f"{label} self-hash drifted")
    return claimed


def _report_cases_and_evidence(
    report: Mapping[str, object],
) -> tuple[
    list[dict[str, object]],
    dict[str, object],
    dict[str, tuple[str, ...]],
]:
    if report.get("schemaVersion") != SOURCE_REPORT_SCHEMA_VERSION:
        raise ValueError("source report schema is unsupported")
    _verify_self_hash(report, field="reportSha256", label="source report")
    evaluation = _require_mapping(
        report.get("evaluation"), label="source report evaluation"
    )
    if (
        evaluation.get("mode") != "answer-only"
        or evaluation.get("split") != "validation"
        or evaluation.get("heldOutLabelsInPrompt") is not False
        or evaluation.get("formalAcceptanceEligible") is not False
        or report.get("formalAcceptanceEligible") is not False
        or report.get("formalAcceptancePassed") is not False
    ):
        raise ValueError("source report is not closed Validation-only evidence")
    held_out = _require_mapping(
        report.get("heldOutAuthorization"),
        label="source report Held-out authorization",
    )
    if held_out.get("authorized") is not False:
        raise ValueError("source report consumed Held-out authority")

    query_ids = [str(item) for item in evaluation.get("caseIds") or []]
    case_ids = [str(item) for item in evaluation.get("caseAliases") or []]
    if (
        not query_ids
        or len(query_ids) != len(case_ids)
        or len(set(query_ids)) != len(query_ids)
        or len(set(case_ids)) != len(case_ids)
        or any(not item for item in query_ids + case_ids)
    ):
        raise ValueError("source report case identities are invalid")

    raw_lanes = _require_sequence(report.get("lanes"), label="source report lanes")
    lane_by_name = {
        str(item.get("lane") or ""): item
        for item in raw_lanes
        if isinstance(item, Mapping)
    }
    if set(lane_by_name) != set(LANES) or len(raw_lanes) != len(LANES):
        raise ValueError("source report must contain exactly four RAG lanes")

    baseline_score = _require_mapping(
        lane_by_name[LANES[0]].get("score"), label="baseline score"
    )
    baseline_cases = _require_sequence(
        baseline_score.get("answerCases"), label="baseline answer cases"
    )
    if len(baseline_cases) != len(case_ids):
        raise ValueError("source report answer-case denominator drifted")
    cases: list[dict[str, object]] = []
    for index, raw_case in enumerate(baseline_cases):
        answer_case = _require_mapping(raw_case, label="baseline answer case")
        if (
            str(answer_case.get("queryId") or "") != query_ids[index]
            or str(answer_case.get("evaluationCaseId") or "") != case_ids[index]
        ):
            raise ValueError("source report answer-case order drifted")
        cases.append(
            {
                "queryId": query_ids[index],
                "evaluationCaseId": case_ids[index],
                "abstentionExpected": answer_case.get("abstentionExpected") is True,
            }
        )

    output_bindings: list[dict[str, object]] = []
    cited_chunk_bindings: list[dict[str, object]] = []
    score_case_by_lane_id: dict[tuple[str, str], Mapping[str, object]] = {}
    citation_token_count = 0
    for lane_name in LANES:
        lane = lane_by_name[lane_name]
        score = _require_mapping(lane.get("score"), label=f"{lane_name} score")
        answer_cases = _require_sequence(
            score.get("answerCases"), label=f"{lane_name} answer cases"
        )
        if len(answer_cases) != len(cases):
            raise ValueError(f"{lane_name} answer-case denominator drifted")
        _require_mapping(lane.get("usage"), label=f"{lane_name} usage")
        _require_mapping(lane.get("costs"), label=f"{lane_name} costs")
        for index, raw_case in enumerate(answer_cases):
            answer_case = _require_mapping(
                raw_case, label=f"{lane_name} answer case"
            )
            expected = cases[index]
            case_id = str(answer_case.get("evaluationCaseId") or "")
            query_id = str(answer_case.get("queryId") or "")
            if (
                case_id != expected["evaluationCaseId"]
                or query_id != expected["queryId"]
                or (answer_case.get("abstentionExpected") is True)
                != expected["abstentionExpected"]
            ):
                raise ValueError(f"{lane_name} answer-case identity drifted")
            tokens = [
                str(item).strip()
                for item in _require_sequence(
                    answer_case.get("citationTokens"),
                    label=f"{lane_name} citation tokens",
                )
            ]
            cited_documents = [
                str(item).strip()
                for item in _require_sequence(
                    answer_case.get("citations"),
                    label=f"{lane_name} citations",
                )
            ]
            unresolved = [
                str(item).strip()
                for item in _require_sequence(
                    answer_case.get("unresolvedCitations"),
                    label=f"{lane_name} unresolved citations",
                )
            ]
            if (
                any(not item for item in tokens + cited_documents + unresolved)
                or len(tokens) != len(set(tokens))
                or len(cited_documents) != len(set(cited_documents))
                or len(unresolved) != len(set(unresolved))
            ):
                raise ValueError("source report citation identities are invalid")
            exact_chunks = sorted(_answer_only_cited_chunk_keys(lane, answer_case))
            if (
                tokens
                and answer_case.get("citationResolution") is True
                and not exact_chunks
            ):
                raise ValueError("resolved source citations have no exact chunk bindings")
            for document_id, chunk_ordinal in exact_chunks:
                cited_chunk_bindings.append(
                    {
                        "lane": lane_name,
                        "caseId": case_id,
                        "documentIdSha256": hashlib.sha256(
                            document_id.encode("utf-8")
                        ).hexdigest(),
                        "chunkOrdinal": chunk_ordinal,
                    }
                )
            score_case_by_lane_id[(lane_name, case_id)] = answer_case
            output_bindings.append(
                {
                    "lane": lane_name,
                    "caseId": case_id,
                    "queryId": query_id,
                    "answerSha256": _require_sha256(
                        answer_case.get("answerSha256"),
                        label=f"{lane_name}/{case_id} answer hash",
                    ),
                    "abstained": answer_case.get("abstained") is True,
                    "citationTokenCount": len(tokens),
                    "exactCitedChunkCount": len(exact_chunks),
                }
            )
            citation_token_count += len(tokens)

    judge = _require_mapping(report.get("answerJudge"), label="source Judge")
    if (
        judge.get("accepted") is not True
        or judge.get("schemaVersion") != "rag-ime.rag-answer-judge.v4"
        or judge.get("terminalEvent") != "turn_completed"
        or judge.get("retrievalQrelAccess") is not False
        or judge.get("judgeFeedbackToAgent") is not False
        or judge.get("candidateCitedEvidenceAccessAfterGeneration") is not True
    ):
        raise ValueError("source Judge evidence is incomplete or not isolated")
    mappings = _require_sequence(
        judge.get("candidateMapping"), label="Judge candidate mapping"
    )
    lane_by_candidate: dict[str, str] = {}
    for raw_mapping in mappings:
        mapping = _require_mapping(raw_mapping, label="Judge candidate mapping")
        candidate_id = str(mapping.get("candidateId") or "")
        lane_name = str(mapping.get("lane") or "")
        if (
            not candidate_id
            or candidate_id in lane_by_candidate
            or lane_name not in LANES
        ):
            raise ValueError("Judge candidate mapping is invalid")
        lane_by_candidate[candidate_id] = lane_name
    if set(lane_by_candidate.values()) != set(LANES):
        raise ValueError("Judge candidate mapping omitted a lane")

    rubrics = _require_sequence(judge.get("caseRubrics"), label="Judge rubrics")
    rubric_facts: dict[str, tuple[str, ...]] = {}
    for raw_rubric in rubrics:
        rubric = _require_mapping(raw_rubric, label="Judge rubric")
        case_id = str(rubric.get("caseId") or "")
        facts = _require_sequence(
            rubric.get("requiredFacts"), label="Judge required facts"
        )
        fact_ids = tuple(
            str(
                _require_mapping(item, label="Judge required fact").get("factId")
                or ""
            )
            for item in facts
        )
        if (
            not case_id
            or case_id in rubric_facts
            or not fact_ids
            or any(not item for item in fact_ids)
            or len(fact_ids) != len(set(fact_ids))
        ):
            raise ValueError("Judge rubric is invalid")
        rubric_facts[case_id] = fact_ids
    expected_judge_cases = {
        str(item["evaluationCaseId"])
        for item in cases
        if item["abstentionExpected"] is False
    }
    if set(rubric_facts) != expected_judge_cases:
        raise ValueError("Judge rubric case set drifted")

    judgments = _require_sequence(judge.get("judgments"), label="Judge judgments")
    judgment_bindings: list[dict[str, object]] = []
    seen_judgments: set[tuple[str, str]] = set()
    for raw_judgment in judgments:
        judgment = _require_mapping(raw_judgment, label="Judge judgment")
        lane_name = str(judgment.get("lane") or "")
        case_id = str(judgment.get("evaluationCaseId") or "")
        candidate_id = str(judgment.get("candidateId") or "")
        key = (lane_name, case_id)
        covered = tuple(str(item) for item in judgment.get("coveredFactIds") or [])
        if (
            key in seen_judgments
            or case_id not in expected_judge_cases
            or lane_by_candidate.get(candidate_id) != lane_name
            or not set(covered).issubset(set(rubric_facts[case_id]))
            or str(judgment.get("answerSha256") or "")
            != str(score_case_by_lane_id[key].get("answerSha256") or "")
        ):
            raise ValueError("Judge judgment does not bind the frozen candidate")
        seen_judgments.add(key)
        judgment_bindings.append(
            {
                "lane": lane_name,
                "caseId": case_id,
                "answerSha256": str(judgment.get("answerSha256") or ""),
                "correct": judgment.get("correct") is True,
                "coveredFactIds": list(covered),
                "hasUnsupportedMaterial": judgment.get("hasUnsupportedMaterial")
                is True,
            }
        )
    if len(seen_judgments) != len(expected_judge_cases) * len(LANES):
        raise ValueError("Judge judgment denominator is incomplete")

    return cases, {
        "laneCaseRecordCount": len(output_bindings),
        "candidateCitationTokenCount": citation_token_count,
        "exactCitedChunkBindingCount": len(cited_chunk_bindings),
        "exactCitedChunkBindingSetSha256": _sha256_json(cited_chunk_bindings),
        "candidateOutputBindingCount": len(output_bindings),
        "candidateOutputSetSha256": _sha256_json(output_bindings),
        "judgeJudgmentCount": len(judgment_bindings),
        "judgeJudgmentSetSha256": _sha256_json(judgment_bindings),
    }, rubric_facts


def _private_qrels_from_artifact(
    *,
    qrels: Mapping[str, object],
    standard: Mapping[str, object],
    source_cases: Sequence[Mapping[str, object]],
    rubric_facts: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, object], dict[str, int]]:
    if standard.get("schemaVersion") != STANDARD_SCHEMA_VERSION:
        raise ValueError("answer-evidence Standard schema is unsupported")
    if qrels.get("schemaVersion") != QRELS_SCHEMA_VERSION:
        raise ValueError("answer-evidence qrels schema is unsupported")
    _verify_self_hash(standard, field="manifestSha256", label="Standard")
    _verify_self_hash(qrels, field="manifestSha256", label="qrels")
    if qrels.get("answerEvidenceStandard") != standard:
        raise ValueError("qrels does not embed the supplied Standard")
    if qrels.get("standardManifestSha256") != standard.get("manifestSha256"):
        raise ValueError("qrels Standard manifest binding drifted")
    if (
        standard.get("evaluationScope") != "validation-development-only"
        or standard.get("calibrationLabel") != "post-validation-calibrated"
        or standard.get("candidateBlind") is not False
        or standard.get("heldOutOpened") is not False
        or standard.get("unbiasedPromotionClaimAllowed") is not False
        or qrels.get("evaluationSplit") != "validation"
        or qrels.get("scope") != "host-only"
        or qrels.get("calibrationLabel") != "post-validation-calibrated"
        or qrels.get("unbiasedPromotionClaimAllowed") is not False
    ):
        raise ValueError("Standard/qrels calibration claim boundary drifted")
    standard_chunking = _require_mapping(
        standard.get("chunking"), label="Standard chunking"
    )
    if qrels.get("chunkingConfigSha256") != standard_chunking.get("configSha256"):
        raise ValueError("qrels chunking configuration binding drifted")
    standard_corpus = _require_mapping(
        standard.get("corpus"), label="Standard corpus"
    )
    if qrels.get("preparedSourceSha256") != standard_corpus.get(
        "preparedSourceSha256"
    ):
        raise ValueError("qrels prepared-source binding drifted")
    chunk_manifest = _require_mapping(
        standard.get("chunkManifest"), label="Standard chunk manifest"
    )
    if int(chunk_manifest.get("chunkCount") or 0) <= 0:
        raise ValueError("Standard chunk manifest is empty")
    _require_sha256(
        chunk_manifest.get("manifestSha256"),
        label="Standard chunk manifest hash",
    )

    high_level_cases = {
        str(item.get("queryId") or ""): str(item.get("evaluationCaseId") or "")
        for item in source_cases
        if item.get("abstentionExpected") is False
    }
    qrel_case_ids = [str(item) for item in qrels.get("caseIds") or []]
    if set(qrel_case_ids) != set(high_level_cases) or len(qrel_case_ids) != len(
        high_level_cases
    ):
        raise ValueError("qrels do not match the frozen high-level cases")

    raw_cases = _require_sequence(qrels.get("cases"), label="qrels cases")
    if len(raw_cases) != len(high_level_cases):
        raise ValueError("qrels case denominator drifted")
    private_qrels: dict[str, object] = {}
    fact_count = 0
    support_group_count = 0
    evidence_binding_count = 0
    for raw_case in raw_cases:
        case = _require_mapping(raw_case, label="qrels case")
        query_id = str(case.get("queryId") or "")
        if not query_id or query_id in private_qrels or query_id not in high_level_cases:
            raise ValueError("qrels contain an unknown or duplicate case")
        raw_facts = _require_sequence(case.get("facts"), label="qrels facts")
        expected_fact_ids = rubric_facts[high_level_cases[query_id]]
        fact_ids = tuple(
            str(
                _require_mapping(item, label="qrels fact").get("factId") or ""
            )
            for item in raw_facts
        )
        if fact_ids != expected_fact_ids:
            raise ValueError("qrels fact denominator/order drifted from frozen Judge")
        normalized_facts: list[dict[str, object]] = []
        for raw_fact in raw_facts:
            fact = _require_mapping(raw_fact, label="qrels fact")
            if fact.get("availability") != "verified":
                raise ValueError("exact offline rescore requires verified qrel facts")
            mode = str(fact.get("supportGroupMode") or "")
            if mode not in {"all", "any"}:
                raise ValueError("qrels support-group mode is invalid")
            raw_groups = _require_sequence(
                fact.get("supportGroups"), label="qrels support groups"
            )
            if not raw_groups:
                raise ValueError("verified qrel fact has no support groups")
            normalized_groups: list[dict[str, object]] = []
            seen_group_ids: set[str] = set()
            for raw_group in raw_groups:
                group = _require_mapping(raw_group, label="qrels support group")
                group_id = str(group.get("groupId") or "")
                if not group_id or group_id in seen_group_ids:
                    raise ValueError("qrels support group ID is invalid")
                seen_group_ids.add(group_id)
                raw_evidence = _require_sequence(
                    group.get("evidence"), label="qrels exact evidence"
                )
                if not raw_evidence:
                    raise ValueError("qrels support group has no exact evidence")
                evidence: list[dict[str, object]] = []
                document_ids: list[str] = []
                seen_keys: set[tuple[str, int]] = set()
                for raw_binding in raw_evidence:
                    binding = _require_mapping(
                        raw_binding, label="qrels exact evidence binding"
                    )
                    document_id = str(binding.get("documentId") or "").strip()
                    chunk_ordinal = binding.get("chunkOrdinal")
                    if (
                        not document_id
                        or isinstance(chunk_ordinal, bool)
                        or not isinstance(chunk_ordinal, int)
                        or chunk_ordinal < 0
                    ):
                        raise ValueError("qrels exact evidence binding is invalid")
                    key = (document_id, chunk_ordinal)
                    if key in seen_keys:
                        raise ValueError("qrels contain duplicate exact evidence")
                    seen_keys.add(key)
                    _require_sha256(
                        binding.get("documentSha256"),
                        label="qrels evidence document hash",
                    )
                    _require_sha256(
                        binding.get("chunkSha256"),
                        label="qrels evidence chunk hash",
                    )
                    quote = str(binding.get("quote") or "")
                    quote_hash = _require_sha256(
                        binding.get("quoteSha256"),
                        label="qrels evidence quote hash",
                    )
                    if not quote or hashlib.sha256(quote.encode("utf-8")).hexdigest() != quote_hash:
                        raise ValueError("qrels evidence quote hash drifted")
                    if document_id not in document_ids:
                        document_ids.append(document_id)
                    evidence.append(
                        {
                            "documentId": document_id,
                            "chunkOrdinal": chunk_ordinal,
                        }
                    )
                    evidence_binding_count += 1
                normalized_groups.append(
                    {
                        "groupId": group_id,
                        "documentIds": document_ids,
                        "evidence": evidence,
                    }
                )
                support_group_count += 1
            normalized_facts.append(
                {
                    "factId": str(fact.get("factId") or ""),
                    "supportGroupMode": mode,
                    "supportGroups": normalized_groups,
                }
            )
            fact_count += 1
        private_qrels[query_id] = {"facts": normalized_facts}

    counts = _require_mapping(qrels.get("counts"), label="qrels counts")
    expected_counts = {
        "caseCount": len(private_qrels),
        "factCount": fact_count,
        "supportGroupCount": support_group_count,
        "evidenceBindingCount": evidence_binding_count,
    }
    if any(int(counts.get(key) or -1) != value for key, value in expected_counts.items()):
        raise ValueError("qrels declared counts drifted")
    return private_qrels, {
        "factCount": fact_count,
        "verifiedFactCount": fact_count,
        "unavailableFactCount": 0,
        "supportGroupCount": support_group_count,
        "evidenceBindingCount": evidence_binding_count,
    }


def _rescore_lanes(
    *,
    source_report: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
    private_qrels: Mapping[str, object],
) -> list[dict[str, Any]]:
    """Call the production answer-only scorer without mutating frozen input."""

    lanes = copy.deepcopy(list(source_report.get("lanes") or []))
    _apply_answer_only_judgments(
        lanes,
        cases=list(cases),
        answer_judge=_require_mapping(
            source_report.get("answerJudge"), label="source Judge"
        ),
        answer_case_manifest={"_privateEvidenceQrels": dict(private_qrels)},
    )
    for lane in lanes:
        score = _require_mapping(lane.get("score"), label="rescored lane score")
        hard_evidence = _require_mapping(
            score.get("hardEvidence"), label="rescored hard evidence"
        )
        hard_gates = lane.get("hardGates")
        if not isinstance(hard_gates, dict):
            raise ValueError("rescored lane hard gates are missing")
        hard_gates["citationResolution"] = bool(
            hard_evidence.get("citationResolution") is True
            and hard_evidence.get("factCitationCoverage") is True
        )
    return lanes


def _quality_projection(lane: Mapping[str, object]) -> dict[str, object]:
    score = _require_mapping(lane.get("score"), label="lane score")
    metrics = _require_mapping(score.get("agentMetrics"), label="lane metrics")
    denominators = _require_mapping(
        score.get("metricDenominators"), label="metric denominators"
    )
    citation_fact_count = int(denominators.get("citationFacts") or 0)
    high_level_fact_count = int(denominators.get("highLevelFacts") or 0)
    high_level_cases = int(denominators.get("highLevelCases") or 0)
    info_not_found_cases = int(denominators.get("infoNotFoundCases") or 0)
    projected = {key: metrics.get(key) for key in QUALITY_METRICS}
    projected["counts"] = {
        "highLevelFactsCovered": int(
            round(
                float(metrics.get("highLevelFactCoverage") or 0.0)
                * high_level_fact_count
            )
        ),
        "highLevelFactCount": high_level_fact_count,
        "citationFactsCovered": int(
            round(
                float(metrics.get("citationFactCoverage") or 0.0)
                * citation_fact_count
            )
        ),
        "citationFactCount": citation_fact_count,
        "answerableCitationCasesSupported": int(
            round(
                float(metrics.get("answerableCitationSupportRate") or 0.0)
                * high_level_cases
            )
        ),
        "answerableCaseCount": high_level_cases,
        "infoNotFoundCasesCorrect": int(
            round(
                float(metrics.get("infoNotFoundAbstentionRecall") or 0.0)
                * info_not_found_cases
            )
        ),
        "infoNotFoundCaseCount": info_not_found_cases,
    }
    hard_gates = _require_mapping(lane.get("hardGates"), label="lane hard gates")
    projected["citationHardGate"] = hard_gates.get("citationResolution") is True
    return projected


def _assert_rescore_scope(
    before: Sequence[Mapping[str, object]],
    after: Sequence[Mapping[str, object]],
) -> dict[str, list[str]]:
    before_by_lane = {str(item.get("lane") or ""): item for item in before}
    after_by_lane = {str(item.get("lane") or ""): item for item in after}
    if set(before_by_lane) != set(LANES) or set(after_by_lane) != set(LANES):
        raise ValueError("rescore lane set drifted")
    changed_metrics: dict[str, list[str]] = {}
    for lane_name in LANES:
        old = before_by_lane[lane_name]
        new = after_by_lane[lane_name]
        if old.get("costs") != new.get("costs") or old.get("usage") != new.get(
            "usage"
        ):
            raise ValueError("offline rescore changed source usage")
        old_score = _require_mapping(old.get("score"), label="source score")
        new_score = _require_mapping(new.get("score"), label="rescored score")
        old_cases = _require_sequence(
            old_score.get("answerCases"), label="source cases"
        )
        new_cases = _require_sequence(
            new_score.get("answerCases"), label="rescored cases"
        )
        if len(old_cases) != len(new_cases):
            raise ValueError("offline rescore changed the case denominator")
        for old_case, new_case in zip(old_cases, new_cases, strict=True):
            old_case = _require_mapping(old_case, label="source case")
            new_case = _require_mapping(new_case, label="rescored case")
            if any(
                old_case.get(key) != new_case.get(key)
                for key in IMMUTABLE_CASE_FIELDS
            ):
                raise ValueError(
                    "offline rescore changed a frozen semantic/candidate field"
                )
        old_metrics = _require_mapping(
            old_score.get("agentMetrics"), label="source metrics"
        )
        new_metrics = _require_mapping(
            new_score.get("agentMetrics"), label="rescored metrics"
        )
        names = sorted(
            key
            for key in set(old_metrics) | set(new_metrics)
            if old_metrics.get(key) != new_metrics.get(key)
        )
        if not set(names).issubset(QRELS_OWNED_METRICS):
            raise ValueError("offline rescore changed a non-qrels metric")
        old_gates = _require_mapping(old.get("hardGates"), label="source hard gates")
        new_gates = _require_mapping(new.get("hardGates"), label="rescored hard gates")
        changed_gates = {
            key
            for key in set(old_gates) | set(new_gates)
            if old_gates.get(key) != new_gates.get(key)
        }
        if not changed_gates.issubset({"citationResolution"}):
            raise ValueError("offline rescore changed a non-qrels hard gate")
        changed_metrics[lane_name] = names
    return changed_metrics


def _companion_cost_receipt_path(source_report_path: Path) -> Path | None:
    prefix = "validation-answer-evidence-"
    stem = source_report_path.stem
    if not stem.startswith(prefix):
        return None
    match = re.fullmatch(r"(.+)-(r[0-9]+)-([0-9]{8})", stem[len(prefix) :])
    if match is None:
        return None
    descriptor, revision, date = match.groups()
    return (
        ROOT
        / "eval/interview-metrics/runs"
        / f"agent-lab-cost-enterprise-rag-{descriptor}-{date}.{revision}.v1.json"
    )


def _cost_source_reference(
    *,
    source_report: Mapping[str, object],
    source_report_path: Path,
    lane_name: str,
) -> dict[str, object]:
    lane = next(
        (
            item
            for item in source_report.get("lanes") or []
            if isinstance(item, Mapping) and item.get("lane") == lane_name
        ),
        None,
    )
    if not isinstance(lane, Mapping):
        raise ValueError(f"source report omitted {lane_name} lane")
    usage = _require_mapping(lane.get("usage"), label=f"{lane_name} usage")
    result: dict[str, object] = {
        "scope": "lane-source-usage-plus-full-run-cost-receipt",
        "sourceReportPath": _path_label(source_report_path),
        "sourceReportFileSha256": _file_sha256(source_report_path),
        "laneSelector": f"lane={lane_name}",
        "laneUsageSha256": _sha256_json(usage),
        "laneUsageSource": str(usage.get("usageSource") or ""),
        "laneProviderRequestCount": int(usage.get("providerRequestCount") or 0),
        "laneTotalTokens": int(usage.get("totalTokens") or 0),
    }
    cost_path = _companion_cost_receipt_path(source_report_path)
    if cost_path is None or not cost_path.is_file():
        result.update(
            {
                "sourceUsageRef": (
                    f"report-sha256:{_file_sha256(source_report_path)}#lane={lane_name}/usage"
                ),
                "companionCostReceiptAvailable": False,
            }
        )
        return result

    cost = _read_json(cost_path)
    if (
        cost.get("schemaVersion") != COST_RECEIPT_SCHEMA_VERSION
        or cost.get("authority") != "runtime_cost_reconciled"
    ):
        raise ValueError("companion cost receipt authority is unsupported")
    cost_receipt_sha256 = _verify_self_hash(
        cost, field="receiptSha256", label="companion cost receipt"
    )
    cost_usage = _require_mapping(cost.get("usage"), label="cost receipt usage")
    runtime_cost = _require_mapping(
        cost.get("runtimeCostReceipt"), label="Runtime cost receipt"
    )
    if cost_usage.get("sourceSha256") != runtime_cost.get("sourceSha256"):
        raise ValueError("companion cost receipt source binding drifted")
    agent_config = _require_mapping(
        source_report.get("agentConfig"), label="source Agent config"
    )
    pricing = _require_mapping(
        cost.get("pricingIdentity"), label="cost receipt pricing identity"
    )
    expected_model = str(agent_config.get("model") or "").split("/", 1)[-1]
    if (
        pricing.get("model") != expected_model
        or pricing.get("provider") != agent_config.get("provider")
    ):
        raise ValueError("companion cost receipt model/provider binding drifted")
    report_total_tokens = sum(
        int(
            _require_mapping(item.get("usage"), label="lane usage").get(
                "totalTokens"
            )
            or 0
        )
        for item in source_report.get("lanes") or []
        if isinstance(item, Mapping)
    ) + int(
        _require_mapping(source_report.get("answerJudge"), label="source Judge").get(
            "tokens"
        )
        or 0
    )
    cost_total_tokens = sum(
        int(cost_usage.get(key) or 0)
        for key in ("uncachedInputTokens", "cachedInputTokens", "outputTokens")
    )
    if report_total_tokens != cost_total_tokens:
        raise ValueError("companion cost receipt usage does not bind the source report")
    estimate = _require_mapping(cost.get("estimate"), label="cost estimate")
    billing = _require_mapping(cost.get("billing"), label="cost billing boundary")
    result.update(
        {
            "sourceUsageRef": str(cost_usage.get("sourceRef") or ""),
            "sourceUsageSha256": str(cost_usage.get("sourceSha256") or ""),
            "companionCostReceiptAvailable": True,
            "companionCostReceipt": {
                "path": _path_label(cost_path),
                "fileSha256": _file_sha256(cost_path),
                "receiptSha256": cost_receipt_sha256,
                "authority": str(cost.get("authority") or ""),
                "pricingSourceSha256": str(pricing.get("sourceSha256") or ""),
                "pricingSourceUrl": str(pricing.get("sourceUrl") or ""),
                "estimatedTotalCostUsd": str(estimate.get("totalCostUsd") or ""),
                "providerBillStatus": str(billing.get("status") or ""),
                "scope": "full-four-lane-run-plus-frozen-judge",
            },
        }
    )
    if not str(result["sourceUsageRef"]).startswith("runtime-cost:"):
        raise ValueError("companion cost receipt lacks a stable Runtime source ref")
    return result


def _historical_scorer_correction(run_id: str) -> dict[str, object]:
    old = _read_json(OBSOLETE_RECEIPT)
    old_contract = _require_mapping(
        old.get("scorerContract"), label="obsolete receipt scorer contract"
    )
    if old_contract.get("candidateSupportMatchGranularity") != "document-id-membership":
        raise ValueError("historical scorer correction target no longer matches")
    return {
        "obsoleteReceipt": {
            "path": _path_label(OBSOLETE_RECEIPT),
            "fileSha256": _file_sha256(OBSOLETE_RECEIPT),
            "receiptSha256": _verify_self_hash(
                old, field="receiptSha256", label="obsolete receipt"
            ),
        },
        "preservedAsHistory": True,
        "supersededScope": "candidate-citation scoring methodology",
        "supersededByRunId": run_id,
        "documentIdMembershipScorerObsolete": True,
        "replacementScorer": (
            "exact-citation-token-to-document-id-and-chunk-ordinal"
        ),
    }


def _build_receipt(
    *,
    run_id: str,
    source_report_path: Path,
    qrels_path: Path,
    standard_path: Path,
) -> dict[str, object]:
    source_report = _read_json(source_report_path)
    qrels = _read_json(qrels_path)
    standard = _read_json(standard_path)
    if qrels_path.stat().st_mode & 0o077:
        raise ValueError("host-private qrels permissions are too broad")

    source_cases, evidence, rubric_facts = _report_cases_and_evidence(source_report)
    private_qrels, qrels_stats = _private_qrels_from_artifact(
        qrels=qrels,
        standard=standard,
        source_cases=source_cases,
        rubric_facts=rubric_facts,
    )
    source_lanes = [
        dict(item)
        for item in _require_sequence(
            source_report.get("lanes"), label="source report lanes"
        )
        if isinstance(item, Mapping)
    ]
    rescored_lanes = _rescore_lanes(
        source_report=source_report,
        cases=source_cases,
        private_qrels=private_qrels,
    )
    changed_metrics = _assert_rescore_scope(source_lanes, rescored_lanes)
    before_by_lane = {str(item.get("lane") or ""): item for item in source_lanes}
    after_by_lane = {str(item.get("lane") or ""): item for item in rescored_lanes}
    before_decision = _build_candidate_decision(source_lanes)
    after_decision = _build_candidate_decision(rescored_lanes)
    source_decision = _require_mapping(
        source_report.get("candidateDecision"), label="source candidate decision"
    )
    if (
        source_decision.get("decision") != before_decision.get("decision")
        or source_decision.get("failedHardGates")
        != before_decision.get("failedHardGates")
    ):
        raise ValueError("source report candidate decision no longer reproduces")

    results: dict[str, object] = {}
    for lane_name in LANES:
        cost_reference = _cost_source_reference(
            source_report=source_report,
            source_report_path=source_report_path,
            lane_name=lane_name,
        )
        results[lane_name] = {
            "qualityBefore": _quality_projection(before_by_lane[lane_name]),
            "qualityAfter": _quality_projection(after_by_lane[lane_name]),
            "changedMetrics": changed_metrics[lane_name],
            "sourceUsageReference": cost_reference,
            "terminalEvent": str(after_by_lane[lane_name].get("terminalEvent") or ""),
        }

    agentic_after = _require_mapping(
        results["agentic"], label="Agentic rescore result"
    )
    agentic_quality = _require_mapping(
        agentic_after.get("qualityAfter"), label="Agentic quality"
    )
    agentic_counts = _require_mapping(
        agentic_quality.get("counts"), label="Agentic quality counts"
    )
    agentic_result = {
        "lane": "agentic",
        "exactCitationFactsCovered": int(
            agentic_counts.get("citationFactsCovered") or 0
        ),
        "citationFactCount": int(agentic_counts.get("citationFactCount") or 0),
        "exactCitationFactCoverage": agentic_quality.get("citationFactCoverage"),
        "highLevelFactsCovered": int(
            agentic_counts.get("highLevelFactsCovered") or 0
        ),
        "highLevelFactCount": int(agentic_counts.get("highLevelFactCount") or 0),
        "answerJudgeCorrectnessRate": agentic_quality.get(
            "answerJudgeCorrectnessRate"
        ),
        "infoNotFoundAbstentionRecall": agentic_quality.get(
            "infoNotFoundAbstentionRecall"
        ),
        "toolSuccessRate": agentic_quality.get("toolSuccessRate"),
        "outputProtocolRate": agentic_quality.get("outputProtocolRate"),
        "decision": str(after_decision.get("decision") or ""),
        "failedHardGates": list(after_decision.get("failedHardGates") or []),
        "costSourceReference": agentic_after["sourceUsageReference"],
    }
    metrics_unchanged = all(not names for names in changed_metrics.values())
    decisions_unchanged = before_decision == after_decision
    command = (
        "python3 scripts/rescore_enterprise_rag_answer_evidence.py "
        f"--source-report {_path_label(source_report_path)} "
        f"--answer-evidence-qrels {_path_label(qrels_path)} "
        f"--standard {_path_label(standard_path)} "
        "--output <new-append-only-receipt.json> "
        f"--run-id {run_id}"
    )
    receipt: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "status": "passed",
        "evaluationScope": "validation-development-only",
        "calibrationLabel": "post-validation-calibrated",
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "heldOutOpened": False,
        "formalAcceptanceEligible": False,
        "formalAcceptancePassed": False,
        "unbiasedPromotionClaimAllowed": False,
        "sourceEvidence": {
            "frozenCandidateReport": {
                "path": _path_label(source_report_path),
                "fileSha256": _file_sha256(source_report_path),
                "reportSha256": str(source_report.get("reportSha256") or ""),
                "model": str(
                    _require_mapping(
                        source_report.get("agentConfig"), label="source Agent config"
                    ).get("model")
                    or ""
                ),
            },
            "evidenceSufficiency": evidence,
        },
        "standard": {
            "path": _path_label(standard_path),
            "schemaVersion": str(standard.get("schemaVersion") or ""),
            "standardId": str(standard.get("standardId") or ""),
            "fileSha256": _file_sha256(standard_path),
            "manifestSha256": str(standard.get("manifestSha256") or ""),
            "chunkCount": int(
                _require_mapping(
                    standard.get("chunkManifest"), label="Standard chunk manifest"
                ).get("chunkCount")
                or 0
            ),
            "chunkManifestSha256": str(
                _require_mapping(
                    standard.get("chunkManifest"), label="Standard chunk manifest"
                ).get("manifestSha256")
                or ""
            ),
        },
        "qrels": {
            "scope": "host-only",
            "path": _path_label(qrels_path),
            "schemaVersion": str(qrels.get("schemaVersion") or ""),
            "fileSha256": _file_sha256(qrels_path),
            "manifestSha256": str(qrels.get("manifestSha256") or ""),
            "standardManifestSha256": str(
                qrels.get("standardManifestSha256") or ""
            ),
            **qrels_stats,
        },
        "scorerContract": {
            "runnerPath": "scripts/run_rag_agent_ablation.py",
            "runnerFileSha256": _file_sha256(
                ROOT / "scripts/run_rag_agent_ablation.py"
            ),
            "runnerFunctions": [
                "_answer_only_cited_chunk_keys",
                "_apply_answer_only_judgments",
                "_build_candidate_decision",
            ],
            "rescoreScriptPath": "scripts/rescore_enterprise_rag_answer_evidence.py",
            "rescoreScriptFileSha256": _file_sha256(Path(__file__)),
            "method": "reuse-frozen-judge-and-production-exact-chunk-scorer-v2",
            "qrelBindingInputGranularity": "document-id-and-chunk-ordinal",
            "candidateSupportMatchGranularity": (
                "exact-citation-token-to-document-id-and-chunk-ordinal"
            ),
            "candidateCitationTokenRequired": True,
            "candidateChunkOrdinalRequired": True,
            "supportGroupModes": ["all", "any"],
            "qrelsOwnedMetrics": sorted(QRELS_OWNED_METRICS),
            "legacyV1DocumentIdFixtureCompatible": True,
        },
        "historicalScorerCorrection": _historical_scorer_correction(run_id),
        "resultsByLane": results,
        "agenticResult": agentic_result,
        "rescoreDecision": {
            "status": (
                "validation-quality-pass"
                if after_decision.get("accepted") is True
                else "rejected"
            ),
            "sourceCandidateDecision": str(before_decision.get("decision") or ""),
            "rescoredCandidateDecision": str(after_decision.get("decision") or ""),
            "failedHardGates": list(after_decision.get("failedHardGates") or []),
            "metricsUnchanged": metrics_unchanged,
            "decisionUnchanged": decisions_unchanged,
            "qrelsRevisionIsModelImprovement": False,
        },
        "qualityComparability": {
            "sameFrozenCandidateBeforeAfter": True,
            "semanticJudgeReusedNotRerun": True,
            "qrelsDependentMetricsDeterministicallyComparable": True,
            "modelQualityImprovementClaimAllowed": False,
            "qrelBindingsRevalidatedAgainstCorpusInThisCommand": False,
            "qrelBindingAuthority": (
                "hash-bound post-validation Standard/qrels artifact accepted by its "
                "dedicated corpus verifier"
            ),
        },
        "costComparability": {
            "sourceUsageCopiedFromHashBoundRun": True,
            "sourceUsageRemeasured": False,
            "qrelsRevisionChangesSourceUsage": False,
            "offlineRescoreProviderCalls": 0,
            "offlineRescoreProviderTokens": 0,
            "offlineRescoreProviderBilledUsd": 0,
            "latencyRole": "diagnostic-only",
        },
        "publicSafety": {
            "containsQuestions": False,
            "containsReferenceAnswers": False,
            "containsCandidateAnswers": False,
            "containsFactBodies": False,
            "containsQrelsBody": False,
            "containsEvidenceQuotes": False,
            "containsPrivateTranscripts": False,
            "containsCandidateSourceIds": False,
        },
        "claimBoundary": [
            "This is a deterministic offline rescore of frozen Validation output; no candidate, Provider, or Judge was rerun.",
            "Candidate support is resolved from each cited token to the exact retrieved document and chunk ordinal before matching exact qrel evidence.",
            "The Standard/qrels revision is post-Validation calibrated and candidate-aware, so this receipt cannot authorize an unbiased promotion or formal acceptance claim.",
            "The older document-ID-membership receipt remains immutable history but its scorer methodology is obsolete and superseded for current comparisons.",
            "Held-out remains unopened; cost and latency are copied references to frozen source evidence and are not remeasured.",
        ],
        "reproduction": {
            "command": command,
            "explicitInputs": [
                "source-report",
                "answer-evidence-qrels",
                "standard",
                "output",
                "run-id",
            ],
            "writesOriginalRunArtifacts": False,
            "existingDifferentOutputFailsClosed": True,
        },
    }
    receipt["receiptSha256"] = _sha256_json(receipt)
    return receipt


def _write_or_verify(path: Path, value: Mapping[str, object]) -> str:
    path = path.expanduser().resolve(strict=False)
    if path.exists():
        current = _read_json(path)
        if current != dict(value):
            raise ValueError(
                "output receipt already exists with different content; refusing to overwrite"
            )
        return "verified"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return "written"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT)
    parser.add_argument(
        "--answer-evidence-qrels", type=Path, default=DEFAULT_QRELS
    )
    parser.add_argument("--standard", type=Path, default=DEFAULT_STANDARD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_report_path = args.source_report.expanduser().resolve(strict=True)
    qrels_path = args.answer_evidence_qrels.expanduser().resolve(strict=True)
    standard_path = args.standard.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    forbidden_outputs = {
        source_report_path,
        qrels_path,
        standard_path,
        OBSOLETE_RECEIPT.resolve(strict=True),
    }
    if output in forbidden_outputs:
        raise ValueError(
            "offline rescore output cannot overwrite an input or obsolete history receipt"
        )
    run_id = str(args.run_id or "").strip()
    if not run_id:
        raise ValueError("offline rescore run ID is required")
    receipt = _build_receipt(
        run_id=run_id,
        source_report_path=source_report_path,
        qrels_path=qrels_path,
        standard_path=standard_path,
    )
    action = _write_or_verify(output, receipt)
    print(
        json.dumps(
            {
                "event": "ENTERPRISE_RAG_ANSWER_EVIDENCE_EXACT_OFFLINE_RESCORE_OK",
                "action": action,
                "output": _path_label(output),
                "receiptSha256": receipt["receiptSha256"],
                "providerCalls": 0,
                "judgeCalls": 0,
                "heldOutOpened": False,
                "unbiasedPromotionClaimAllowed": False,
                "agenticExactCitationFactsCovered": receipt["agenticResult"][
                    "exactCitationFactsCovered"
                ],
                "agenticCitationFactCount": receipt["agenticResult"][
                    "citationFactCount"
                ],
                "decision": receipt["agenticResult"]["decision"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
