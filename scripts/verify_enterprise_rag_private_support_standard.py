#!/usr/bin/env python3
"""Build and verify the candidate-aware qst_0477/F3 r5 successor.

The audit is post-Validation and Sol-candidate-aware.  It appends one exact
Private platform-fee-plus-support binding to F3 without changing the other
eight facts, the frozen candidate, the Runner, Prompt v5, or dataset content.
All scoring is offline through the existing exact cited-chunk seam.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_rag_agent_ablation import (  # noqa: E402
    _answer_only_cited_chunk_keys,
    _apply_answer_only_judgments,
    _build_candidate_decision,
    _sha256_json,
    _validate_answer_evidence_qrels,
)
from scripts.verify_enterprise_rag_revenue_category_standard import (  # noqa: E402
    ANSWER_KEY,
    AUDIT_INPUT,
    PREPARED,
    QRELS_R3,
    QRELS_R4,
    QRELS_V2,
    RETRIEVAL,
    STANDARD_R3,
    STANDARD_R4,
    STANDARD_V2,
    _answer_key_case,
    _audit_question,
    _covered_facts,
    _fact,
    _file_sha256,
    _prepared_documents,
    _read_json,
    _relative,
    _selected_cases,
    _self_hash,
    _source_cases,
    _text_sha256,
    _write_json,
)


RUNNER = ROOT / "scripts/run_rag_agent_ablation.py"
R4_VERIFIER = ROOT / "scripts/verify_enterprise_rag_revenue_category_standard.py"
SOURCE_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-sol-max-frozen-v19-r4-20260904.json"
)
AUDIT_R5 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-private-support-r5-audit-20260905.v1.json"
)
STANDARD_R5 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-private-support-r5.json"
)
QRELS_R5 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-private-support-r5.json"
)
RECEIPT_R5 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-private-support-r5-calibration-20260905.v1.json"
)

EXPECTED_FILE_SHA256 = {
    RUNNER: "e90af777b337374d750c7a994f78d7cf28770faf33d15ea7f7672ab16ef781e4",
    R4_VERIFIER: "42e139a434eec802a7996009833045465ba4d489534069ab5523500cb9586f71",
    PREPARED: "833641681e44b1f1490249ced863568a48723b7ca4995628e17493d333bc6f96",
    ANSWER_KEY: "1bae86e7ee403ca4eacc48b06496aa820aeaaf4595a0e1a8c2c6a18057bd8b9f",
    RETRIEVAL: "3d4ebe22ff765ef403aec723e6d76b5cfddf3ce55dbc8f8b08e9932573a5bc0a",
    AUDIT_INPUT: "4f0cbae5798ff0849fb1d5109ab459a4398ef1e5a929c457df5b591cb92d3117",
    SOURCE_REPORT: "667ca9403f70dca05b0d2cf4864ef21e6dce610f4c939656efae64fce1a95671",
    STANDARD_V2: "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7",
    QRELS_V2: "b0b081c4a0ecbced1c589b69126de555a0f1b8815c508e1f4eb269adce608428",
    STANDARD_R3: "a8dcd8a37d2e599e07b4882d4e1df354835658a546f1c08ff71d109ebedf5e50",
    QRELS_R3: "4a02e4948a593d87d845739e5dcb60d61c33b6216da217ed79b3b9c4dc55d46d",
    STANDARD_R4: "0d6155f9055c6a47b7b311d57c0f05ba4436c4769b2f336ee3e8cba06ad35dc9",
    QRELS_R4: "6e29c0ab058f2293b5e9e5e7b9b4f4309c3b58c47199f9d30afa97ec96752719",
}

AUDIT_ID = "enterprise-rag-answer-evidence-sol-candidate-aware-private-support-audit-r5-20260905"
STANDARD_ID = "enterprise-rag-answer-evidence-validation-candidate-aware-private-support-r5-20260905"
RUN_ID = "enterprise-rag-answer-evidence-standard-candidate-aware-private-support-r5-calibration-20260905"
CALIBRATION_LABEL = "post-validation-calibrated"
MODEL = "openai-codex/gpt-5.6-sol"
QUERY_ID = "qst_0477"
FACT_ID = "F3"
EVALUATION_CASE_ID = "case-02"
GROUP_ID = "G2-private-support-r5"
SUPPORT_LABEL = "private_platform_support_candidate_equivalent"
DOCUMENT_ID = "dsid_dbd29f9393f149fbb696c9a5614dc875"
DOCUMENT_SHA256 = "ffe908543aab45da3d65964fa305102edff748f1338025fa7d0ec6a7885c2274"
CHUNK_ORDINAL = 0
CHUNK_SHA256 = "a293fde74c5dd33cbbf5668a76db8ad01cef24a6952a42f57bb89e77759f66b1"
QUOTE_SHA256 = "8a44532317f92eeffa273876749c1897f4a4457f8112909f73d934fee675f880"
QUESTION_SHA256 = "63c0d62a667cfe0a74258f1fa75e3e72339c599622d6b311d676512684a849d3"
REFERENCE_ANSWER_SHA256 = "f6d241af865e26a041d74aeed2bbc3a880db594c8b2cfb484da4084963372044"
FACT_SHA256 = "ea70d7131b919eca45223588ec790af5097b2a5dd8349c8f30711de22339aa59"
JUDGE_RUBRIC_FACT_SHA256 = "0465f8a550d10c011ec214b9a5f05b640cf22b6af0039888219158608466e7cb"
CANDIDATE_ANSWER_SHA256 = "30bf964de2dd97ec006dfca9ca36832e7a1800911468ab294a1565716ccd2902"

EXPECTED_R4_COVERED_FACTS = {
    "qst_0474/F2",
    "qst_0474/F3",
    "qst_0474/F4",
    "qst_0477/F1",
    "qst_0477/F2",
    "qst_0477/F4",
}
EXPECTED_R5_COVERED_FACTS = EXPECTED_R4_COVERED_FACTS | {"qst_0477/F3"}


def _assert_frozen_hashes() -> None:
    for path, expected in EXPECTED_FILE_SHA256.items():
        observed = _file_sha256(path)
        if observed != expected:
            raise AssertionError(f"frozen input drifted: {_relative(path)}: {observed}")


def _audit_fact(question: Mapping[str, object]) -> dict[str, Any]:
    matches = [
        item
        for item in question.get("requiredFacts") or []
        if isinstance(item, dict) and item.get("factId") == FACT_ID
    ]
    if len(matches) != 1:
        raise AssertionError("frozen audit input omitted qst_0477/F3")
    return matches[0]


def _judge_rubric_fact(report: Mapping[str, object]) -> str:
    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen Sol Judge is missing")
    for rubric in judge.get("caseRubrics") or []:
        if not isinstance(rubric, Mapping) or rubric.get("caseId") != EVALUATION_CASE_ID:
            continue
        for fact in rubric.get("requiredFacts") or []:
            if isinstance(fact, Mapping) and fact.get("factId") == FACT_ID:
                description = str(fact.get("description") or "")
                if _text_sha256(description) != JUDGE_RUBRIC_FACT_SHA256:
                    raise AssertionError("frozen Sol Judge F3 rubric drifted")
                return description
    raise AssertionError("frozen Sol Judge omitted qst_0477/F3")


def _exact_quote(document_text: str) -> str:
    candidates: list[str] = []
    for line in document_text.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        candidates.append(normalized)
        if normalized.startswith("- "):
            candidates.append(normalized.removeprefix("- "))
    matches = [item for item in candidates if _text_sha256(item) == QUOTE_SHA256]
    if len(matches) != 1:
        raise AssertionError("frozen Private/support quote is not unique")
    return matches[0]


def _equivalent_binding(documents: Mapping[str, str]) -> dict[str, object]:
    document_text = documents.get(DOCUMENT_ID)
    if document_text is None or _text_sha256(document_text) != DOCUMENT_SHA256:
        raise AssertionError("frozen Private/support document drifted")
    source_binding = _fact(_read_json(QRELS_R4), QUERY_ID, "F1")[
        "supportGroups"
    ][0]["evidence"][0]
    if (
        source_binding.get("documentId") != DOCUMENT_ID
        or source_binding.get("chunkOrdinal") != CHUNK_ORDINAL
        or source_binding.get("chunkSha256") != CHUNK_SHA256
    ):
        raise AssertionError("r4 K1 chunk metadata drifted")
    return {
        "chunkOrdinal": CHUNK_ORDINAL,
        "chunkSha256": CHUNK_SHA256,
        "documentId": DOCUMENT_ID,
        "documentSha256": DOCUMENT_SHA256,
        "quote": _exact_quote(document_text),
        "quoteSha256": QUOTE_SHA256,
        "sourceType": source_binding["sourceType"],
        "title": source_binding["title"],
    }


def _candidate_evidence(report: Mapping[str, object]) -> dict[str, object]:
    lanes = report.get("lanes")
    if not isinstance(lanes, list):
        raise AssertionError("frozen Sol lanes are malformed")
    agentic = next(
        (item for item in lanes if isinstance(item, Mapping) and item.get("lane") == "agentic"),
        None,
    )
    score = agentic.get("score") if isinstance(agentic, Mapping) else None
    if not isinstance(score, Mapping):
        raise AssertionError("frozen Sol Agentic score is missing")
    answer_case = next(
        (
            item
            for item in score.get("answerCases") or []
            if isinstance(item, Mapping) and item.get("queryId") == QUERY_ID
        ),
        None,
    )
    if not isinstance(answer_case, Mapping):
        raise AssertionError("frozen Sol qst_0477 answer case is missing")
    if answer_case.get("answerSha256") != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen Sol qst_0477 answer hash drifted")

    matching_tokens: set[str] = set()
    ledger = agentic.get("gatewayLedger") if isinstance(agentic, Mapping) else None
    raw_items = ledger.get("items") if isinstance(ledger, Mapping) else None
    if not isinstance(raw_items, list):
        raise AssertionError("frozen Sol citation ledger is missing")
    for item in raw_items:
        if not isinstance(item, Mapping) or item.get("operation") != "search" or item.get("ok") is not True:
            continue
        args = item.get("args")
        summary = item.get("resultSummary")
        if (
            not isinstance(args, Mapping)
            or args.get("evaluationCaseId") != EVALUATION_CASE_ID
            or not isinstance(summary, Mapping)
        ):
            continue
        for hit in summary.get("hits") or []:
            if not isinstance(hit, Mapping):
                continue
            if hit.get("externalDocumentId") == DOCUMENT_ID and hit.get("ordinal") == CHUNK_ORDINAL:
                matching_tokens.add(str(hit.get("citationRef") or ""))
    cited_tokens = {str(item) for item in answer_case.get("citationTokens") or []}
    matching_tokens.discard("")
    cited_matches = matching_tokens & cited_tokens
    if len(cited_matches) != 1:
        raise AssertionError("frozen Sol candidate does not uniquely cite K1 chunk 0")
    citation_token = next(iter(cited_matches))
    if DOCUMENT_ID not in {str(item) for item in answer_case.get("citations") or []}:
        raise AssertionError("frozen Sol citation projection omitted K1 document")

    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen Sol Judge projection is missing")
    candidate_by_lane = {
        str(item.get("lane") or ""): str(item.get("candidateId") or "")
        for item in judge.get("candidateMapping") or []
        if isinstance(item, Mapping)
    }
    candidate_id = candidate_by_lane.get("agentic", "")
    answer = ""
    for evidence_case in judge.get("evidenceCases") or []:
        if not isinstance(evidence_case, Mapping) or evidence_case.get("caseId") != EVALUATION_CASE_ID:
            continue
        for candidate in evidence_case.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("candidateId") == candidate_id:
                answer = str(candidate.get("answer") or "")
    if _text_sha256(answer) != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen Sol candidate body/hash binding drifted")
    return {
        "lane": "agentic",
        "model": MODEL,
        "queryId": QUERY_ID,
        "evaluationCaseId": EVALUATION_CASE_ID,
        "answer": answer,
        "answerSha256": CANDIDATE_ANSWER_SHA256,
        "citationToken": citation_token,
        "citationTokenSha256": _text_sha256(citation_token),
        "documentId": DOCUMENT_ID,
        "chunkOrdinal": CHUNK_ORDINAL,
    }


def _proposal(binding: Mapping[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "paw.enterprise-rag-private-support-qrels-proposal.v1",
        "predecessorQrelsFileSha256": EXPECTED_FILE_SHA256[QRELS_R4],
        "changedFacts": [f"{QUERY_ID}/{FACT_ID}"],
        "supportGroupMode": {"before": "any", "after": "any"},
        "appendSupportGroup": {
            "groupId": GROUP_ID,
            "supportLabel": SUPPORT_LABEL,
            "evidence": [dict(binding)],
        },
        "otherFactBindingsAdded": 0,
    }


def _build_audit() -> dict[str, object]:
    documents = _prepared_documents()
    question = _audit_question()
    fact = _audit_fact(question)
    answer_key = _answer_key_case(QUERY_ID)
    report = _read_json(SOURCE_REPORT)
    rubric_fact = _judge_rubric_fact(report)
    binding = _equivalent_binding(documents)
    candidate = _candidate_evidence(report)
    audit_facts = [
        str(item.get("description") or "")
        for item in question.get("requiredFacts") or []
        if isinstance(item, Mapping)
    ]
    if answer_key.get("answerFacts") != audit_facts:
        raise AssertionError("frozen answer key and audit fact lists disagree")
    semantic_unit = {
        "queryId": QUERY_ID,
        "question": str(question.get("question") or ""),
        "questionSha256": QUESTION_SHA256,
        "referenceAnswer": str(answer_key.get("goldAnswer") or ""),
        "referenceAnswerSha256": REFERENCE_ANSWER_SHA256,
        "factId": FACT_ID,
        "fact": str(fact.get("description") or ""),
        "factSha256": FACT_SHA256,
        "judgeRubricFact": rubric_fact,
        "judgeRubricFactSha256": JUDGE_RUBRIC_FACT_SHA256,
    }
    for key, expected in (
        ("question", QUESTION_SHA256),
        ("referenceAnswer", REFERENCE_ANSWER_SHA256),
        ("fact", FACT_SHA256),
    ):
        if _text_sha256(str(semantic_unit[key])) != expected:
            raise AssertionError(f"frozen qst_0477/F3 {key} drifted")
    proposal = _proposal(binding)
    prior_f3 = _fact(_read_json(QRELS_R4), QUERY_ID, FACT_ID)
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-private-support-sol-candidate-aware-audit.v1",
        "auditId": AUDIT_ID,
        "auditedAt": "2026-09-05",
        "evaluationScope": "validation-development-only",
        "calibrationLabel": CALIBRATION_LABEL,
        "candidateBlind": False,
        "candidateAware": True,
        "auditAware": True,
        "candidateCitationsAccessed": True,
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        "frozenInputs": {
            "auditInputFileSha256": EXPECTED_FILE_SHA256[AUDIT_INPUT],
            "answerKeyFileSha256": EXPECTED_FILE_SHA256[ANSWER_KEY],
            "preparedFileSha256": EXPECTED_FILE_SHA256[PREPARED],
            "retrievalFileSha256": EXPECTED_FILE_SHA256[RETRIEVAL],
            "sourceReportFileSha256": EXPECTED_FILE_SHA256[SOURCE_REPORT],
            "standardV2FileSha256": EXPECTED_FILE_SHA256[STANDARD_V2],
            "qrelsV2FileSha256": EXPECTED_FILE_SHA256[QRELS_V2],
            "standardR3FileSha256": EXPECTED_FILE_SHA256[STANDARD_R3],
            "qrelsR3FileSha256": EXPECTED_FILE_SHA256[QRELS_R3],
            "standardR4FileSha256": EXPECTED_FILE_SHA256[STANDARD_R4],
            "qrelsR4FileSha256": EXPECTED_FILE_SHA256[QRELS_R4],
        },
        "frozenSemanticUnit": semantic_unit,
        "predecessorF3": {
            "supportGroupMode": prior_f3["supportGroupMode"],
            "supportGroupCount": len(prior_f3["supportGroups"]),
            "supportLabels": [
                str(item.get("supportLabel") or "")
                for item in prior_f3["supportGroups"]
                if isinstance(item, Mapping)
            ],
        },
        "sourceCandidate": candidate,
        "acceptedEquivalentBinding": binding,
        "semanticAssessment": {
            "verdict": "equivalent",
            "factScoringUnit": "private_deployment_platform_or_licensing_fee_plus_support",
            "candidateChunkClaim": "private_platform_fee_plus_support",
            "equivalenceLimitedToFact": f"{QUERY_ID}/{FACT_ID}",
            "reasoning": [
                "The frozen F3 asks for Private-deployment licensing and support revenue, not a specific contract label.",
                "The frozen Sol Judge rubric explicitly treats licensing fees and platform fees plus support as the same F3 unit.",
                "The candidate-cited exact K1 chunk directly lists Private platform fee plus support in revenue-recognition scope.",
                "The source is an independently sufficient exact alternative for F3; no other fact requires a new binding.",
            ],
        },
        "proposal": proposal,
        "proposalSha256": _sha256_json(proposal),
        "claimBoundary": [
            "This audit inspected the frozen Sol candidate answer, citations, and cited chunk, so it is not candidate blind.",
            "Only qst_0477/F3 receives one equivalent exact support group; the other eight facts remain object-identical to r4.",
            "This post-Validation calibration cannot support unbiased promotion or model-quality improvement claims.",
            "No Provider or Judge was called, no candidate was rerun, and Held-out remains unopened.",
        ],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_standard(audit: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(_read_json(STANDARD_R4))
    value["standardId"] = STANDARD_ID
    value["calibrationLabel"] = CALIBRATION_LABEL
    value["candidateBlind"] = False
    value["calibrationSource"] = {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT_R5),
        "proposalSha256": audit["proposalSha256"],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_qrels(
    standard: Mapping[str, object], audit: Mapping[str, object]
) -> dict[str, object]:
    previous = _read_json(QRELS_R4)
    value = copy.deepcopy(previous)
    value["candidateOf"] = {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R4],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }
    value["answerEvidenceStandard"] = dict(standard)
    value["standardManifestSha256"] = standard["manifestSha256"]
    value["candidateBlindProposalSha256"] = audit["proposalSha256"]
    f3 = _fact(value, QUERY_ID, FACT_ID)
    if f3.get("supportGroupMode") != "any" or len(f3.get("supportGroups") or []) != 1:
        raise AssertionError("r4 qst_0477/F3 predecessor shape drifted")
    f3["supportGroups"].append(copy.deepcopy(audit["proposal"]["appendSupportGroup"]))
    value["counts"] = {
        "caseCount": 2,
        "factCount": 9,
        "supportGroupCount": 19,
        "evidenceBindingCount": 19,
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _exact_sol_rescore(qrels: Mapping[str, object]) -> dict[str, object]:
    documents = _prepared_documents()
    retrieval = _read_json(RETRIEVAL)
    retrieval_dataset = retrieval.get("dataset")
    if not isinstance(retrieval_dataset, Mapping):
        raise AssertionError("frozen retrieval dataset is malformed")
    private_qrels, stats = _validate_answer_evidence_qrels(
        qrels,
        selected_cases=_selected_cases(_read_json(AUDIT_INPUT), set(qrels["caseIds"])),
        document_text_by_id=documents,
        prepared_source_sha256=str(retrieval_dataset.get("sourceSha256") or ""),
        prepared_artifact_sha256=EXPECTED_FILE_SHA256[PREPARED],
        evaluation_split="validation",
        chunking_config=dict(retrieval["chunking"]),
    )
    report = _read_json(SOURCE_REPORT)
    if (
        report.get("schemaVersion") != "rag-ime.rag-agent-ablation-run.v1"
        or report.get("conditions", {}).get("model") != MODEL
        or report.get("formalAcceptanceEligible") is not False
        or report.get("formalAcceptancePassed") is not False
        or report.get("heldOutAuthorization", {}).get("authorized") is not False
    ):
        raise AssertionError("frozen Sol report identity/claim boundary drifted")
    judge = report.get("answerJudge")
    if (
        not isinstance(judge, Mapping)
        or judge.get("retrievalQrelAccess") is not False
        or judge.get("judgeFeedbackToAgent") is not False
        or judge.get("candidateCitedEvidenceAccessAfterGeneration") is not True
    ):
        raise AssertionError("frozen Sol Judge isolation boundary drifted")
    lanes = copy.deepcopy(report["lanes"])
    _apply_answer_only_judgments(
        lanes,
        cases=_source_cases(report),
        answer_judge=judge,
        answer_case_manifest={"_privateEvidenceQrels": private_qrels},
    )
    for lane in lanes:
        score = lane.get("score")
        hard_evidence = score.get("hardEvidence") if isinstance(score, Mapping) else None
        hard_gates = lane.get("hardGates")
        if not isinstance(hard_evidence, Mapping) or not isinstance(hard_gates, dict):
            raise AssertionError("rescored Sol lane gates are malformed")
        hard_gates["citationResolution"] = bool(
            hard_evidence.get("citationResolution") is True
            and hard_evidence.get("factCitationCoverage") is True
        )
    agentic = next(item for item in lanes if item.get("lane") == "agentic")
    score = agentic["score"]
    covered_fact_ids: list[str] = []
    for answer_case in score["answerCases"]:
        query_id = str(answer_case.get("queryId") or "")
        qrel_case = private_qrels.get(query_id)
        if not isinstance(qrel_case, Mapping):
            continue
        cited_chunks = _answer_only_cited_chunk_keys(agentic, answer_case)
        covered_fact_ids.extend(
            f"{query_id}/{fact_id}"
            for fact_id in _covered_facts(qrel_case, cited_chunks)
        )
    covered_fact_ids.sort()
    decision = _build_candidate_decision(lanes)
    metric = float(score["agentMetrics"]["citationFactCoverage"])
    if abs(metric - (len(covered_fact_ids) / stats["factCount"])) > 1e-12:
        raise AssertionError("Sol exact covered facts disagree with Runner metric")
    return {
        "qrelsStats": stats,
        "coveredFactIds": covered_fact_ids,
        "coveredFactCount": len(covered_fact_ids),
        "factCount": stats["factCount"],
        "citationFactCoverage": metric,
        "decision": str(decision.get("decision") or ""),
        "failedHardGates": list(decision.get("failedHardGates") or []),
        "sourceReportSha256": str(report.get("reportSha256") or ""),
    }


def _build_receipt(
    *,
    audit: Mapping[str, object],
    standard: Mapping[str, object],
    qrels: Mapping[str, object],
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    newly_covered = sorted(set(after["coveredFactIds"]) - set(before["coveredFactIds"]))
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-answer-evidence-private-support-calibration.v1",
        "runId": RUN_ID,
        "status": "passed",
        "evaluationScope": "validation-development-only",
        "calibrationLabel": CALIBRATION_LABEL,
        "candidateBlind": False,
        "candidateAware": True,
        "auditAware": True,
        "localOnly": True,
        "uploaded": False,
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "heldOutOpened": False,
        "formalAcceptanceEligible": False,
        "formalAcceptancePassed": False,
        "unbiasedPromotionClaimAllowed": False,
        "auditBoundary": {
            "auditId": AUDIT_ID,
            "auditReceiptFileSha256": _file_sha256(AUDIT_R5),
            "auditReceiptManifestSha256": audit["manifestSha256"],
            "candidateCitationsAccessed": True,
            "questionReferenceFactsAccessed": True,
            "heldOutAccessed": False,
        },
        "sourceCandidate": {
            "path": _relative(SOURCE_REPORT),
            "fileSha256": EXPECTED_FILE_SHA256[SOURCE_REPORT],
            "reportSha256": after["sourceReportSha256"],
            "model": MODEL,
            "lane": "agentic",
            "answerSha256": CANDIDATE_ANSWER_SHA256,
        },
        "predecessor": {
            "standardR4FileSha256": EXPECTED_FILE_SHA256[STANDARD_R4],
            "standardR4ManifestSha256": _read_json(STANDARD_R4)["manifestSha256"],
            "qrelsR4FileSha256": EXPECTED_FILE_SHA256[QRELS_R4],
            "qrelsR4ManifestSha256": _read_json(QRELS_R4)["manifestSha256"],
        },
        "standard": {
            "path": _relative(STANDARD_R5),
            "schemaVersion": standard["schemaVersion"],
            "standardId": standard["standardId"],
            "fileSha256": _file_sha256(STANDARD_R5),
            "manifestSha256": standard["manifestSha256"],
        },
        "qrels": {
            "scope": "host-only",
            "path": _relative(QRELS_R5),
            "schemaVersion": qrels["schemaVersion"],
            "fileSha256": _file_sha256(QRELS_R5),
            "manifestSha256": qrels["manifestSha256"],
            "factCount": 9,
            "supportGroupCount": 19,
            "evidenceBindingCount": 19,
        },
        "calibrationDelta": {
            "operator": "append_exact_private_platform_support_equivalent",
            "changedFacts": [f"{QUERY_ID}/{FACT_ID}"],
            "supportGroupModeBefore": "any",
            "supportGroupModeAfter": "any",
            "addedExactBindings": 1,
            "otherFactBindingsAdded": 0,
            "newlyCoveredFacts": newly_covered,
        },
        "frozenSolCandidateRescore": {
            "scorerContract": "exact-citation-token-to-document-chunk-ordinal",
            "runnerPath": _relative(RUNNER),
            "runnerFileSha256": _file_sha256(RUNNER),
            "supportVerifierPath": _relative(R4_VERIFIER),
            "supportVerifierFileSha256": _file_sha256(R4_VERIFIER),
            "verifierPath": _relative(Path(__file__)),
            "verifierFileSha256": _file_sha256(Path(__file__)),
            "measurementStatus": "post-validation-sol-candidate-aware",
            "beforeCoveredFactCount": before["coveredFactCount"],
            "coveredFactCount": after["coveredFactCount"],
            "factCount": after["factCount"],
            "citationFactCoverage": after["citationFactCoverage"],
            "decision": after["decision"],
            "failedHardGates": after["failedHardGates"],
        },
        "publicSafety": {
            "containsQuestions": False,
            "containsReferenceAnswers": False,
            "containsFactBodies": False,
            "containsEvidenceQuotes": False,
            "containsQrelsBody": False,
            "containsCandidateAnswers": False,
            "containsPrivateTranscripts": False,
        },
        "verification": {
            "command": "python3 scripts/verify_enterprise_rag_private_support_standard.py",
            "result": "ENTERPRISE_RAG_PRIVATE_SUPPORT_STANDARD_R5_OK",
        },
        "claimBoundary": [
            "This receipt proves an append-only post-Validation candidate-aware Standard/qrels fixed point and offline Sol rescore.",
            "Only qst_0477/F3 receives one exact equivalent group; no other fact is newly credited.",
            "The frozen Sol candidate rises from 6/9 to 7/9 citation facts and remains Reject.",
            "This is not an unbiased promotion or model-quality improvement result.",
            "No Provider or Judge was called, no candidate was rerun, and Held-out remains unopened.",
        ],
    }
    value["receiptSha256"] = _self_hash(value, field="receiptSha256")
    return value


def _assert_only_f3_changed(
    previous: Mapping[str, object], revised: Mapping[str, object]
) -> None:
    changes: set[tuple[str, str]] = set()
    for query_id, fact_count in (("qst_0474", 5), ("qst_0477", 4)):
        for index in range(1, fact_count + 1):
            fact_id = f"F{index}"
            before = _fact(previous, query_id, fact_id)
            after = _fact(revised, query_id, fact_id)
            if before != after:
                changes.add((query_id, fact_id))
            if (query_id, fact_id) != (QUERY_ID, FACT_ID) and before != after:
                raise AssertionError(f"r5 changed out-of-scope fact {query_id}/{fact_id}")
    if changes != {(QUERY_ID, FACT_ID)}:
        raise AssertionError(f"r5 changed the wrong fact set: {changes!r}")
    before_f3 = _fact(previous, QUERY_ID, FACT_ID)
    after_f3 = _fact(revised, QUERY_ID, FACT_ID)
    before_groups = before_f3.get("supportGroups")
    after_groups = after_f3.get("supportGroups")
    if (
        before_f3.get("supportGroupMode") != "any"
        or after_f3.get("supportGroupMode") != "any"
        or not isinstance(before_groups, list)
        or not isinstance(after_groups, list)
        or before_groups != after_groups[:-1]
        or len(after_groups) != len(before_groups) + 1
    ):
        raise AssertionError("r5 F3 delta is not one append-only alternative")
    appended = after_groups[-1]
    if (
        not isinstance(appended, Mapping)
        or appended.get("groupId") != GROUP_ID
        or appended.get("supportLabel") != SUPPORT_LABEL
        or len(appended.get("evidence") or []) != 1
    ):
        raise AssertionError("r5 F3 appended group drifted")
    binding = appended["evidence"][0]
    expected = {
        "documentId": DOCUMENT_ID,
        "documentSha256": DOCUMENT_SHA256,
        "chunkOrdinal": CHUNK_ORDINAL,
        "chunkSha256": CHUNK_SHA256,
        "quoteSha256": QUOTE_SHA256,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise AssertionError("r5 F3 exact binding drifted")


def _write_artifacts() -> None:
    _assert_frozen_hashes()
    audit = _build_audit()
    _write_json(AUDIT_R5, audit, private=True)
    standard = _build_standard(audit)
    _write_json(STANDARD_R5, standard)
    qrels = _build_qrels(standard, audit)
    _write_json(QRELS_R5, qrels, private=True)
    before = _exact_sol_rescore(_read_json(QRELS_R4))
    after = _exact_sol_rescore(qrels)
    if set(before["coveredFactIds"]) != EXPECTED_R4_COVERED_FACTS:
        raise AssertionError("r4 frozen Sol exact coverage drifted")
    if set(after["coveredFactIds"]) != EXPECTED_R5_COVERED_FACTS:
        raise AssertionError("r5 frozen Sol exact coverage drifted")
    if after["decision"] != "reject":
        raise AssertionError("r5 frozen Sol candidate must remain Reject")
    _write_json(
        RECEIPT_R5,
        _build_receipt(
            audit=audit,
            standard=standard,
            qrels=qrels,
            before=before,
            after=after,
        ),
    )


def _verify() -> dict[str, object]:
    _assert_frozen_hashes()
    if QRELS_R5.stat().st_mode & 0o077 or AUDIT_R5.stat().st_mode & 0o077:
        raise AssertionError("host-private r5 artifacts have overly broad permissions")
    previous = _read_json(QRELS_R4)
    audit = _read_json(AUDIT_R5)
    standard = _read_json(STANDARD_R5)
    qrels = _read_json(QRELS_R5)
    receipt = _read_json(RECEIPT_R5)
    if audit.get("manifestSha256") != _self_hash(audit):
        raise AssertionError("r5 audit self-hash drifted")
    if standard.get("manifestSha256") != _self_hash(standard):
        raise AssertionError("r5 Standard self-hash drifted")
    if qrels.get("manifestSha256") != _self_hash(qrels):
        raise AssertionError("r5 qrels self-hash drifted")
    if receipt.get("receiptSha256") != _self_hash(receipt, field="receiptSha256"):
        raise AssertionError("r5 public receipt self-hash drifted")
    if (
        audit.get("candidateBlind") is not False
        or audit.get("candidateAware") is not True
        or audit.get("candidateCitationsAccessed") is not True
        or standard.get("candidateBlind") is not False
        or standard.get("heldOutOpened") is not False
        or standard.get("unbiasedPromotionClaimAllowed") is not False
        or receipt.get("providerCalls") != 0
        or receipt.get("judgeCalls") != 0
        or receipt.get("candidateRuns") != 0
        or receipt.get("heldOutOpened") is not False
        or receipt.get("unbiasedPromotionClaimAllowed") is not False
    ):
        raise AssertionError("r5 candidate/Held-out/unbiased boundary drifted")
    if audit.get("semanticAssessment", {}).get("verdict") != "equivalent":
        raise AssertionError("r5 semantic equivalence audit did not pass")
    if standard.get("calibrationSource") != {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT_R5),
        "proposalSha256": audit["proposalSha256"],
    }:
        raise AssertionError("r5 Standard audit binding drifted")
    if qrels.get("answerEvidenceStandard") != standard:
        raise AssertionError("r5 qrels does not embed its public Standard")
    if qrels.get("candidateOf") != {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R4],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }:
        raise AssertionError("r5 qrels is not a direct r4 successor")
    if qrels.get("candidateBlindProposalSha256") != audit.get("proposalSha256"):
        raise AssertionError("r5 qrels proposal binding drifted")
    _assert_only_f3_changed(previous, qrels)

    before = _exact_sol_rescore(previous)
    after = _exact_sol_rescore(qrels)
    if set(before["coveredFactIds"]) != EXPECTED_R4_COVERED_FACTS:
        raise AssertionError("r4 exact Sol covered-fact set drifted")
    if set(after["coveredFactIds"]) != EXPECTED_R5_COVERED_FACTS:
        raise AssertionError("r5 exact Sol covered-fact set drifted")
    if set(after["coveredFactIds"]) - set(before["coveredFactIds"]) != {f"{QUERY_ID}/{FACT_ID}"}:
        raise AssertionError("r5 newly credited more than qst_0477/F3")
    if after["coveredFactCount"] != 7 or after["factCount"] != 9 or after["decision"] != "reject":
        raise AssertionError("r5 frozen Sol verdict drifted")
    rescored = receipt.get("frozenSolCandidateRescore")
    if not isinstance(rescored, Mapping):
        raise AssertionError("r5 public receipt omitted frozen Sol rescore")
    if (
        rescored.get("beforeCoveredFactCount") != 6
        or rescored.get("coveredFactCount") != 7
        or rescored.get("factCount") != 9
        or rescored.get("decision") != "reject"
        or rescored.get("runnerFileSha256") != _file_sha256(RUNNER)
        or rescored.get("supportVerifierFileSha256") != _file_sha256(R4_VERIFIER)
        or rescored.get("verifierFileSha256") != _file_sha256(Path(__file__))
    ):
        raise AssertionError("r5 public exact-rescore binding drifted")
    if receipt.get("calibrationDelta", {}).get("newlyCoveredFacts") != [f"{QUERY_ID}/{FACT_ID}"]:
        raise AssertionError("r5 public receipt overcredits facts")
    if any(
        receipt.get("publicSafety", {}).get(key) is not False
        for key in (
            "containsQuestions",
            "containsReferenceAnswers",
            "containsFactBodies",
            "containsEvidenceQuotes",
            "containsQrelsBody",
            "containsCandidateAnswers",
            "containsPrivateTranscripts",
        )
    ):
        raise AssertionError("r5 public safety declaration drifted")
    serialized_public = json.dumps([standard, receipt], ensure_ascii=False)
    for body in (
        audit["frozenSemanticUnit"]["question"],
        audit["frozenSemanticUnit"]["referenceAnswer"],
        audit["frozenSemanticUnit"]["fact"],
        audit["frozenSemanticUnit"]["judgeRubricFact"],
        audit["acceptedEquivalentBinding"]["quote"],
        audit["sourceCandidate"]["answer"],
    ):
        if body in serialized_public:
            raise AssertionError("r5 public artifact contains a private evidence body")
    stats = after["qrelsStats"]
    return {
        "event": "ENTERPRISE_RAG_PRIVATE_SUPPORT_STANDARD_R5_OK",
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "candidateBlind": False,
        "candidateAware": True,
        "auditAware": True,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        **stats,
        "frozenSolCoveredFactCount": 7,
        "frozenSolFactCount": 9,
        "frozenSolDecision": "reject",
        "newlyCoveredFacts": [f"{QUERY_ID}/{FACT_ID}"],
        "standardFileSha256": _file_sha256(STANDARD_R5),
        "standardManifestSha256": standard["manifestSha256"],
        "qrelsFileSha256": _file_sha256(QRELS_R5),
        "qrelsManifestSha256": qrels["manifestSha256"],
        "auditFileSha256": _file_sha256(AUDIT_R5),
        "auditManifestSha256": audit["manifestSha256"],
        "receiptFileSha256": _file_sha256(RECEIPT_R5),
        "receiptSha256": receipt["receiptSha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the deterministic append-only r5 audit, Standard, qrels, and receipt",
    )
    args = parser.parse_args()
    if args.write:
        _write_artifacts()
    print(json.dumps(_verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
