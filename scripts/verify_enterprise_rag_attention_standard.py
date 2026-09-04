#!/usr/bin/env python3
"""Build and verify the candidate-aware qst_0474/F1 r6 successor.

The audit is post-Validation and Luna-prompt-v4-candidate-aware. It appends one
exact cited attention-kernel binding to F1 without changing the other eight
facts, any frozen candidate, the Runner, Prompt, dataset, Provider, or Judge.
All three comparison scores are recomputed offline through the existing exact
citation-token-to-document/chunk seam.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
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
from scripts.verify_enterprise_rag_private_support_standard import (  # noqa: E402
    ANSWER_KEY,
    AUDIT_INPUT,
    PREPARED,
    QRELS_R5,
    RETRIEVAL,
    STANDARD_R5,
    _answer_key_case,
    _assert_frozen_hashes as _assert_r5_frozen_hashes,
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
)


RUNNER = ROOT / "scripts/run_rag_agent_ablation.py"
RESCORER = ROOT / "scripts/rescore_enterprise_rag_answer_evidence.py"
R5_VERIFIER = ROOT / "scripts/verify_enterprise_rag_private_support_standard.py"
LUNA_PROMPT_V4_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-coverage-balanced-v4-r4-20260904.json"
)
LUNA_MODEL_ONLY_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-model-only-v19-r4-20260904.json"
)
SOL_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-sol-max-frozen-v19-r4-20260904.json"
)
AUDIT_R6 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-attention-r6-audit-20260905.v1.json"
)
STANDARD_R6 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-attention-r6.json"
)
QRELS_R6 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-attention-r6.json"
)
RECEIPT_R6 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-attention-r6-calibration-20260905.v1.json"
)

EXPECTED_FILE_SHA256 = {
    RUNNER: "e90af777b337374d750c7a994f78d7cf28770faf33d15ea7f7672ab16ef781e4",
    RESCORER: "8f098d410d8b443e91a40f7a9a96b69fb25c69b0c688b5b8245c81f0b297954b",
    R5_VERIFIER: "5319d94edb722b21bd52afcc78a489c6c239e620f3468abed8c800ad216f5c85",
    STANDARD_R5: "363926b1fe9797adc6b67019be03a6a147d6bdfa4d3dbfd6fc71a61a004f1e42",
    QRELS_R5: "26e37c922f9676758d3a0b29c4b2f743156f017fe68b3645afe089e3855dad8e",
    LUNA_PROMPT_V4_REPORT: "f7a4443c41b6738f9fdb8b5831d65d91a7ac7de71c54c3fd4c76e8b0d8edc252",
    LUNA_MODEL_ONLY_REPORT: "e46cf24687170bb768e8ae9cfe434a199f8b1c2be550b328f42b02b151192dd4",
    SOL_REPORT: "667ca9403f70dca05b0d2cf4864ef21e6dce610f4c939656efae64fce1a95671",
}

AUDIT_ID = "enterprise-rag-answer-evidence-luna-candidate-aware-attention-audit-r6-20260905"
STANDARD_ID = "enterprise-rag-answer-evidence-validation-candidate-aware-attention-r6-20260905"
RUN_ID = "enterprise-rag-answer-evidence-standard-candidate-aware-attention-r6-calibration-20260905"
CALIBRATION_LABEL = "post-validation-calibrated"
QUERY_ID = "qst_0474"
FACT_ID = "F1"
EVALUATION_CASE_ID = "case-01"
GROUP_ID = "G2-attention-r6"
SUPPORT_LABEL = "runtime_fused_attention_candidate_equivalent"
DOCUMENT_ID = "dsid_84502e86ba9c43eebb344017fa1d07dc"
DOCUMENT_SHA256 = "ac3c14bdb1223e1fad4e5eedadc4f601ab7db5976eab22a452e1124e298bb695"
CHUNK_ORDINAL = 3
CHUNK_SHA256 = "53384cced10bc0ce04b74df22f99296e80278091b6f6916a6a5fde6266a61261"
SOURCE_CHUNK_ID = "bafc587ca9765377ba09c79570c617c7"
CITATION_TOKEN = "K22"
QUOTE_SHA256 = "b8b8a4eab801430074cf0519a181e15e163912c477f7ab6bb3cf412eb9a616df"
QUESTION_SHA256 = "89e6ddb5e2e7ecb7e397a6165e841e7dba2d78904cb47e9d1d53497dcee9973f"
REFERENCE_ANSWER_SHA256 = "8c90bf2018419dfa4c6fc5ac44b10674e7a301dfc7d680064f50a4737f4ee288"
FACT_SHA256 = "4e0e4213d4032c8fc2d6ee62cf5ffe735cbd5d5347b999b84ab735417808c8c1"
JUDGE_RUBRIC_FACT_SHA256 = "12839168c109859c15b5b4f2ee3f2572d05b48df6236c21b61ee6e15f42167f2"
CANDIDATE_ANSWER_SHA256 = "9b9f1cde55a82008ef29a92dae0ec8de44b600f00caa325c08397f707c583588"
LUNA_MODEL = "openai-codex/gpt-5.6-luna"
SOL_MODEL = "openai-codex/gpt-5.6-sol"


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _json_file_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _assert_frozen_inputs() -> None:
    _assert_r5_frozen_hashes()
    for path, expected in EXPECTED_FILE_SHA256.items():
        observed = _file_sha256(path)
        if observed != expected:
            raise AssertionError(f"frozen input drifted: {_relative(path)}: {observed}")


def _audit_question() -> dict[str, Any]:
    matches = [
        item
        for item in _read_json(AUDIT_INPUT).get("questions") or []
        if isinstance(item, dict) and item.get("queryId") == QUERY_ID
    ]
    if len(matches) != 1:
        raise AssertionError("frozen audit input omitted qst_0474")
    return matches[0]


def _audit_fact(question: Mapping[str, object]) -> dict[str, Any]:
    matches = [
        item
        for item in question.get("requiredFacts") or []
        if isinstance(item, dict) and item.get("factId") == FACT_ID
    ]
    if len(matches) != 1:
        raise AssertionError("frozen audit input omitted qst_0474/F1")
    return matches[0]


def _judge_rubric_fact(report: Mapping[str, object]) -> str:
    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen Luna Judge is missing")
    for rubric in judge.get("caseRubrics") or []:
        if not isinstance(rubric, Mapping) or rubric.get("caseId") != EVALUATION_CASE_ID:
            continue
        for fact in rubric.get("requiredFacts") or []:
            if isinstance(fact, Mapping) and fact.get("factId") == FACT_ID:
                description = str(fact.get("description") or "")
                if _text_sha256(description) != JUDGE_RUBRIC_FACT_SHA256:
                    raise AssertionError("frozen Luna Judge F1 rubric drifted")
                return description
    raise AssertionError("frozen Luna Judge omitted qst_0474/F1")


def _prepared_document() -> dict[str, str]:
    matches = [
        item
        for item in _read_json(PREPARED).get("documents") or []
        if isinstance(item, Mapping) and item.get("documentId") == DOCUMENT_ID
    ]
    if len(matches) != 1:
        raise AssertionError("frozen attention document is not unique")
    item = matches[0]
    text = str(item.get("text") or "")
    if _text_sha256(text) != DOCUMENT_SHA256:
        raise AssertionError("frozen attention document drifted")
    return {
        "text": text,
        "sourceType": str(item.get("source") or ""),
        "title": str(item.get("title") or ""),
    }


def _exact_quote(document_text: str, chunk_text: str) -> str:
    matches = [
        line.strip()
        for line in document_text.splitlines()
        if line.strip() and _text_sha256(line.strip()) == QUOTE_SHA256
    ]
    if len(matches) != 1 or matches[0] not in chunk_text:
        raise AssertionError("frozen attention quote is not unique inside exact chunk")
    return matches[0]


def _candidate_evidence(report: Mapping[str, object]) -> dict[str, object]:
    lanes = report.get("lanes")
    if not isinstance(lanes, list):
        raise AssertionError("frozen Luna lanes are malformed")
    agentic = next(
        (item for item in lanes if isinstance(item, Mapping) and item.get("lane") == "agentic"),
        None,
    )
    score = agentic.get("score") if isinstance(agentic, Mapping) else None
    if not isinstance(score, Mapping):
        raise AssertionError("frozen Luna Agentic score is missing")
    answer_case = next(
        (
            item
            for item in score.get("answerCases") or []
            if isinstance(item, Mapping) and item.get("queryId") == QUERY_ID
        ),
        None,
    )
    if not isinstance(answer_case, Mapping):
        raise AssertionError("frozen Luna qst_0474 answer case is missing")
    if answer_case.get("answerSha256") != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen Luna qst_0474 answer hash drifted")

    ledger = agentic.get("gatewayLedger") if isinstance(agentic, Mapping) else None
    raw_items = ledger.get("items") if isinstance(ledger, Mapping) else None
    if not isinstance(raw_items, list):
        raise AssertionError("frozen Luna citation ledger is missing")
    matching_tokens: set[str] = set()
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
                if hit.get("chunkId") != SOURCE_CHUNK_ID:
                    raise AssertionError("frozen Luna K22 runtime chunk identity drifted")
                matching_tokens.add(str(hit.get("citationRef") or ""))
    cited_tokens = {str(item) for item in answer_case.get("citationTokens") or []}
    matching_tokens.discard("")
    if matching_tokens & cited_tokens != {CITATION_TOKEN}:
        raise AssertionError("frozen Luna candidate does not uniquely cite K22 chunk 3")
    if DOCUMENT_ID not in {str(item) for item in answer_case.get("citations") or []}:
        raise AssertionError("frozen Luna citation projection omitted K22 document")

    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen Luna Judge projection is missing")
    candidate_by_lane = {
        str(item.get("lane") or ""): str(item.get("candidateId") or "")
        for item in judge.get("candidateMapping") or []
        if isinstance(item, Mapping)
    }
    candidate_id = candidate_by_lane.get("agentic", "")
    answer = ""
    evidence_ids: set[str] = set()
    chunk_texts: list[str] = []
    for evidence_case in judge.get("evidenceCases") or []:
        if not isinstance(evidence_case, Mapping) or evidence_case.get("caseId") != EVALUATION_CASE_ID:
            continue
        for candidate in evidence_case.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("candidateId") == candidate_id:
                answer = str(candidate.get("answer") or "")
                evidence_ids = {str(item) for item in candidate.get("evidenceIds") or []}
        for evidence in evidence_case.get("evidenceDocuments") or []:
            if not isinstance(evidence, Mapping):
                continue
            text = str(evidence.get("text") or "")
            if _text_sha256(text) == CHUNK_SHA256:
                if str(evidence.get("evidenceId") or "") not in evidence_ids:
                    raise AssertionError("exact attention chunk was not retained for Luna candidate")
                chunk_texts.append(text)
    if _text_sha256(answer) != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen Luna candidate body/hash binding drifted")
    if len(chunk_texts) != 1:
        raise AssertionError("frozen Luna cited attention chunk is not unique")
    return {
        "lane": "agentic",
        "model": LUNA_MODEL,
        "queryId": QUERY_ID,
        "evaluationCaseId": EVALUATION_CASE_ID,
        "answer": answer,
        "answerSha256": CANDIDATE_ANSWER_SHA256,
        "citationToken": CITATION_TOKEN,
        "citationTokenSha256": _text_sha256(CITATION_TOKEN),
        "documentId": DOCUMENT_ID,
        "chunkOrdinal": CHUNK_ORDINAL,
        "runtimeChunkId": SOURCE_CHUNK_ID,
        "chunkText": chunk_texts[0],
        "chunkSha256": CHUNK_SHA256,
    }


def _equivalent_binding(
    document: Mapping[str, str], candidate: Mapping[str, object]
) -> dict[str, object]:
    chunk_text = str(candidate.get("chunkText") or "")
    quote = _exact_quote(str(document["text"]), chunk_text)
    return {
        "chunkOrdinal": CHUNK_ORDINAL,
        "chunkSha256": CHUNK_SHA256,
        "documentId": DOCUMENT_ID,
        "documentSha256": DOCUMENT_SHA256,
        "quote": quote,
        "quoteSha256": QUOTE_SHA256,
        "sourceType": document["sourceType"],
        "title": document["title"],
    }


def _proposal(binding: Mapping[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "paw.enterprise-rag-attention-qrels-proposal.v1",
        "predecessorQrelsFileSha256": EXPECTED_FILE_SHA256[QRELS_R5],
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
    question = _audit_question()
    fact = _audit_fact(question)
    answer_key = _answer_key_case(QUERY_ID)
    report = _read_json(LUNA_PROMPT_V4_REPORT)
    rubric_fact = _judge_rubric_fact(report)
    candidate = _candidate_evidence(report)
    document = _prepared_document()
    binding = _equivalent_binding(document, candidate)
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
            raise AssertionError(f"frozen qst_0474/F1 {key} drifted")
    proposal = _proposal(binding)
    prior_f1 = _fact(_read_json(QRELS_R5), QUERY_ID, FACT_ID)
    public_candidate = dict(candidate)
    public_candidate.pop("chunkText", None)
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-attention-luna-candidate-aware-audit.v1",
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
            "auditInputFileSha256": _file_sha256(AUDIT_INPUT),
            "answerKeyFileSha256": _file_sha256(ANSWER_KEY),
            "preparedFileSha256": _file_sha256(PREPARED),
            "retrievalFileSha256": _file_sha256(RETRIEVAL),
            "sourceReportFileSha256": EXPECTED_FILE_SHA256[LUNA_PROMPT_V4_REPORT],
            "standardR5FileSha256": EXPECTED_FILE_SHA256[STANDARD_R5],
            "qrelsR5FileSha256": EXPECTED_FILE_SHA256[QRELS_R5],
        },
        "frozenSemanticUnit": semantic_unit,
        "predecessorF1": {
            "supportGroupMode": prior_f1["supportGroupMode"],
            "supportGroupCount": len(prior_f1["supportGroups"]),
            "supportLabels": [
                str(item.get("supportLabel") or "")
                for item in prior_f1["supportGroups"]
                if isinstance(item, Mapping)
            ],
        },
        "sourceCandidate": public_candidate,
        "acceptedEquivalentBinding": binding,
        "semanticAssessment": {
            "verdict": "equivalent",
            "equivalenceLimitedToFact": f"{QUERY_ID}/{FACT_ID}",
            "directChunkSupport": True,
            "unsupportedAnswerExpansion": False,
            "reasoning": [
                "The exact cited chunk names a concrete optimized attention-kernel path.",
                "The same chunk states the kernel fallback represented in the frozen candidate wording.",
                "The narrower cited mechanism directly satisfies this one high-level fact without crediting another fact.",
            ],
        },
        "proposal": proposal,
        "proposalSha256": _sha256_json(proposal),
        "claimBoundary": [
            "This audit inspected the frozen Luna prompt-v4 candidate, citations, and cited chunk, so it is not candidate blind.",
            "Only qst_0474/F1 receives one exact equivalent support group; the other eight facts remain object-identical to r5.",
            "This post-Validation calibration cannot support unbiased promotion or model-quality improvement claims.",
            "No Provider or Judge was called, no candidate was rerun, and Held-out remains unopened.",
        ],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_standard(audit: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(_read_json(STANDARD_R5))
    value["standardId"] = STANDARD_ID
    value["calibrationLabel"] = CALIBRATION_LABEL
    value["candidateBlind"] = False
    value["heldOutOpened"] = False
    value["unbiasedPromotionClaimAllowed"] = False
    value["calibrationSource"] = {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _json_file_sha256(audit),
        "proposalSha256": audit["proposalSha256"],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_qrels(
    standard: Mapping[str, object], audit: Mapping[str, object]
) -> dict[str, object]:
    previous = _read_json(QRELS_R5)
    value = copy.deepcopy(previous)
    value["candidateOf"] = {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R5],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }
    value["answerEvidenceStandard"] = copy.deepcopy(dict(standard))
    value["standardManifestSha256"] = standard["manifestSha256"]
    value["candidateBlindProposalSha256"] = audit["proposalSha256"]
    f1 = _fact(value, QUERY_ID, FACT_ID)
    if f1.get("supportGroupMode") != "any" or len(f1.get("supportGroups") or []) != 1:
        raise AssertionError("r5 qst_0474/F1 predecessor shape drifted")
    f1["supportGroups"].append(copy.deepcopy(audit["proposal"]["appendSupportGroup"]))
    value["counts"] = {
        "caseCount": 2,
        "factCount": 9,
        "supportGroupCount": 20,
        "evidenceBindingCount": 20,
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _validated_qrels(
    qrels: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, int]]:
    retrieval = _read_json(RETRIEVAL)
    retrieval_dataset = retrieval.get("dataset")
    if not isinstance(retrieval_dataset, Mapping):
        raise AssertionError("frozen retrieval dataset is malformed")
    return _validate_answer_evidence_qrels(
        qrels,
        selected_cases=_selected_cases(_read_json(AUDIT_INPUT), set(qrels["caseIds"])),
        document_text_by_id=_prepared_documents(),
        prepared_source_sha256=str(retrieval_dataset.get("sourceSha256") or ""),
        prepared_artifact_sha256=_file_sha256(PREPARED),
        evaluation_split="validation",
        chunking_config=dict(retrieval["chunking"]),
    )


def _exact_rescore(
    *,
    report_path: Path,
    expected_model: str,
    private_qrels: Mapping[str, object],
    stats: Mapping[str, int],
) -> dict[str, object]:
    report = _read_json(report_path)
    conditions = report.get("conditions")
    if (
        report.get("schemaVersion") != "rag-ime.rag-agent-ablation-run.v1"
        or not isinstance(conditions, Mapping)
        or conditions.get("model") != expected_model
        or report.get("formalAcceptanceEligible") is not False
        or report.get("formalAcceptancePassed") is not False
        or report.get("heldOutAuthorization", {}).get("authorized") is not False
    ):
        raise AssertionError(f"frozen report identity/claim boundary drifted: {_relative(report_path)}")
    judge = report.get("answerJudge")
    if (
        not isinstance(judge, Mapping)
        or judge.get("retrievalQrelAccess") is not False
        or judge.get("judgeFeedbackToAgent") is not False
        or judge.get("candidateCitedEvidenceAccessAfterGeneration") is not True
    ):
        raise AssertionError(f"frozen Judge isolation boundary drifted: {_relative(report_path)}")
    lanes = copy.deepcopy(report["lanes"])
    _apply_answer_only_judgments(
        lanes,
        cases=_source_cases(report),
        answer_judge=judge,
        answer_case_manifest={"_privateEvidenceQrels": dict(private_qrels)},
    )
    for lane in lanes:
        score = lane.get("score")
        hard_evidence = score.get("hardEvidence") if isinstance(score, Mapping) else None
        hard_gates = lane.get("hardGates")
        if not isinstance(hard_evidence, Mapping) or not isinstance(hard_gates, dict):
            raise AssertionError("rescored lane gates are malformed")
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
        raise AssertionError("exact covered facts disagree with Runner metric")
    return {
        "coveredFactIds": covered_fact_ids,
        "coveredFactCount": len(covered_fact_ids),
        "factCount": stats["factCount"],
        "citationFactCoverage": metric,
        "decision": str(decision.get("decision") or ""),
        "failedHardGates": list(decision.get("failedHardGates") or []),
        "sourceReportSha256": str(report.get("reportSha256") or ""),
    }


def _comparison_payload(
    *,
    report_path: Path,
    model: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scorerContract": "exact-citation-token-to-document-chunk-ordinal",
        "sourceReportPath": _relative(report_path),
        "sourceReportFileSha256": EXPECTED_FILE_SHA256[report_path],
        "sourceReportSha256": after["sourceReportSha256"],
        "model": model,
        "lane": "agentic",
        "beforeCoveredFactCount": before["coveredFactCount"],
        "coveredFactCount": after["coveredFactCount"],
        "factCount": after["factCount"],
        "citationFactCoverage": after["citationFactCoverage"],
        "decision": after["decision"],
        "failedHardGates": after["failedHardGates"],
    }


def _build_receipt(
    *,
    audit: Mapping[str, object],
    standard: Mapping[str, object],
    qrels: Mapping[str, object],
    prompt_before: Mapping[str, object],
    prompt_after: Mapping[str, object],
    model_only_before: Mapping[str, object],
    model_only_after: Mapping[str, object],
    sol_before: Mapping[str, object],
    sol_after: Mapping[str, object],
) -> dict[str, object]:
    newly_covered = sorted(
        set(prompt_after["coveredFactIds"]) - set(prompt_before["coveredFactIds"])
    )
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-answer-evidence-attention-calibration.v1",
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
            "auditReceiptFileSha256": _json_file_sha256(audit),
            "auditReceiptManifestSha256": audit["manifestSha256"],
            "candidateCitationsAccessed": True,
            "questionReferenceFactsAccessed": True,
            "heldOutAccessed": False,
        },
        "predecessor": {
            "standardR5FileSha256": EXPECTED_FILE_SHA256[STANDARD_R5],
            "standardR5ManifestSha256": _read_json(STANDARD_R5)["manifestSha256"],
            "qrelsR5FileSha256": EXPECTED_FILE_SHA256[QRELS_R5],
            "qrelsR5ManifestSha256": _read_json(QRELS_R5)["manifestSha256"],
        },
        "standard": {
            "path": _relative(STANDARD_R6),
            "schemaVersion": standard["schemaVersion"],
            "standardId": standard["standardId"],
            "fileSha256": _json_file_sha256(standard),
            "manifestSha256": standard["manifestSha256"],
        },
        "qrels": {
            "scope": "host-only",
            "path": _relative(QRELS_R6),
            "schemaVersion": qrels["schemaVersion"],
            "fileSha256": _json_file_sha256(qrels),
            "manifestSha256": qrels["manifestSha256"],
            "factCount": 9,
            "supportGroupCount": 20,
            "evidenceBindingCount": 20,
        },
        "calibrationDelta": {
            "operator": "append_exact_runtime_fused_attention_equivalent",
            "changedFacts": [f"{QUERY_ID}/{FACT_ID}"],
            "supportGroupModeBefore": "any",
            "supportGroupModeAfter": "any",
            "addedExactBindings": 1,
            "otherFactBindingsAdded": 0,
            "newlyCoveredFacts": newly_covered,
        },
        "lunaPromptV4Rescore": _comparison_payload(
            report_path=LUNA_PROMPT_V4_REPORT,
            model=LUNA_MODEL,
            before=prompt_before,
            after=prompt_after,
        ),
        "lunaModelOnlyControl": _comparison_payload(
            report_path=LUNA_MODEL_ONLY_REPORT,
            model=LUNA_MODEL,
            before=model_only_before,
            after=model_only_after,
        ),
        "solControl": _comparison_payload(
            report_path=SOL_REPORT,
            model=SOL_MODEL,
            before=sol_before,
            after=sol_after,
        ),
        "implementation": {
            "runnerPath": _relative(RUNNER),
            "runnerFileSha256": _file_sha256(RUNNER),
            "rescorerPath": _relative(RESCORER),
            "rescorerFileSha256": _file_sha256(RESCORER),
            "predecessorVerifierPath": _relative(R5_VERIFIER),
            "predecessorVerifierFileSha256": _file_sha256(R5_VERIFIER),
            "verifierPath": _relative(Path(__file__)),
            "verifierFileSha256": _file_sha256(Path(__file__)),
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
            "command": "python3 scripts/verify_enterprise_rag_attention_standard.py",
            "result": "ENTERPRISE_RAG_ATTENTION_STANDARD_R6_OK",
        },
        "claimBoundary": [
            "This receipt proves one append-only post-Validation candidate-aware Standard/qrels binding and deterministic offline comparison.",
            "Only qst_0474/F1 receives one exact equivalent group; no other fact is newly credited.",
            "The frozen Luna prompt-v4 candidate reaches 9/9 and Keep; both model controls remain below the citation gate and Reject.",
            "This is not an unbiased promotion or model-quality improvement result.",
            "No Provider or Judge was called, no candidate was rerun, and Held-out remains unopened.",
        ],
    }
    value["receiptSha256"] = _self_hash(value, field="receiptSha256")
    return value


def _assert_append_only_delta(
    previous: Mapping[str, object], revised: Mapping[str, object]
) -> None:
    observed_changes: set[tuple[str, str]] = set()
    for query_id, fact_count in (("qst_0474", 5), ("qst_0477", 4)):
        for index in range(1, fact_count + 1):
            fact_id = f"F{index}"
            before = _fact(previous, query_id, fact_id)
            after = _fact(revised, query_id, fact_id)
            if before != after:
                observed_changes.add((query_id, fact_id))
            if (query_id, fact_id) != (QUERY_ID, FACT_ID) and before != after:
                raise AssertionError(f"r6 changed out-of-scope fact {query_id}/{fact_id}")
    if observed_changes != {(QUERY_ID, FACT_ID)}:
        raise AssertionError(f"r6 changed the wrong fact set: {observed_changes!r}")
    before_f1 = _fact(previous, QUERY_ID, FACT_ID)
    after_f1 = _fact(revised, QUERY_ID, FACT_ID)
    before_groups = before_f1.get("supportGroups")
    after_groups = after_f1.get("supportGroups")
    before_static = {key: value for key, value in before_f1.items() if key != "supportGroups"}
    after_static = {key: value for key, value in after_f1.items() if key != "supportGroups"}
    if (
        before_static != after_static
        or before_f1.get("supportGroupMode") != "any"
        or not isinstance(before_groups, list)
        or not isinstance(after_groups, list)
        or before_groups != after_groups[:-1]
        or len(after_groups) != len(before_groups) + 1
    ):
        raise AssertionError("r6 F1 delta is not one append-only alternative")
    appended = after_groups[-1]
    if (
        not isinstance(appended, Mapping)
        or appended.get("groupId") != GROUP_ID
        or appended.get("supportLabel") != SUPPORT_LABEL
        or len(appended.get("evidence") or []) != 1
    ):
        raise AssertionError("r6 F1 appended group drifted")
    binding = appended["evidence"][0]
    expected = {
        "documentId": DOCUMENT_ID,
        "documentSha256": DOCUMENT_SHA256,
        "chunkOrdinal": CHUNK_ORDINAL,
        "chunkSha256": CHUNK_SHA256,
        "quoteSha256": QUOTE_SHA256,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise AssertionError("r6 F1 exact binding drifted")


def _assert_comparisons(
    prompt_before: Mapping[str, object],
    prompt_after: Mapping[str, object],
    model_only_before: Mapping[str, object],
    model_only_after: Mapping[str, object],
    sol_before: Mapping[str, object],
    sol_after: Mapping[str, object],
) -> None:
    changed = set(prompt_after["coveredFactIds"]) - set(prompt_before["coveredFactIds"])
    if (
        prompt_before["coveredFactCount"] != 8
        or prompt_after["coveredFactCount"] != 9
        or prompt_after["factCount"] != 9
        or changed != {f"{QUERY_ID}/{FACT_ID}"}
        or prompt_after["decision"] != "keep"
    ):
        raise AssertionError("r6 Luna prompt-v4 exact comparison drifted")
    if (
        model_only_before["coveredFactIds"] != model_only_after["coveredFactIds"]
        or model_only_after["coveredFactCount"] != 8
        or model_only_after["factCount"] != 9
        or model_only_after["decision"] != "reject"
    ):
        raise AssertionError("r6 Luna model-only control drifted")
    if (
        sol_before["coveredFactIds"] != sol_after["coveredFactIds"]
        or sol_after["coveredFactCount"] != 7
        or sol_after["factCount"] != 9
        or sol_after["decision"] != "reject"
    ):
        raise AssertionError("r6 Sol control drifted")


def _build_bundle() -> dict[Path, dict[str, object]]:
    _assert_frozen_inputs()
    audit = _build_audit()
    standard = _build_standard(audit)
    qrels = _build_qrels(standard, audit)
    previous = _read_json(QRELS_R5)
    _assert_append_only_delta(previous, qrels)
    prior_private, prior_stats = _validated_qrels(previous)
    revised_private, revised_stats = _validated_qrels(qrels)
    prompt_before = _exact_rescore(
        report_path=LUNA_PROMPT_V4_REPORT,
        expected_model=LUNA_MODEL,
        private_qrels=prior_private,
        stats=prior_stats,
    )
    prompt_after = _exact_rescore(
        report_path=LUNA_PROMPT_V4_REPORT,
        expected_model=LUNA_MODEL,
        private_qrels=revised_private,
        stats=revised_stats,
    )
    model_only_before = _exact_rescore(
        report_path=LUNA_MODEL_ONLY_REPORT,
        expected_model=LUNA_MODEL,
        private_qrels=prior_private,
        stats=prior_stats,
    )
    model_only_after = _exact_rescore(
        report_path=LUNA_MODEL_ONLY_REPORT,
        expected_model=LUNA_MODEL,
        private_qrels=revised_private,
        stats=revised_stats,
    )
    sol_before = _exact_rescore(
        report_path=SOL_REPORT,
        expected_model=SOL_MODEL,
        private_qrels=prior_private,
        stats=prior_stats,
    )
    sol_after = _exact_rescore(
        report_path=SOL_REPORT,
        expected_model=SOL_MODEL,
        private_qrels=revised_private,
        stats=revised_stats,
    )
    _assert_comparisons(
        prompt_before,
        prompt_after,
        model_only_before,
        model_only_after,
        sol_before,
        sol_after,
    )
    receipt = _build_receipt(
        audit=audit,
        standard=standard,
        qrels=qrels,
        prompt_before=prompt_before,
        prompt_after=prompt_after,
        model_only_before=model_only_before,
        model_only_after=model_only_after,
        sol_before=sol_before,
        sol_after=sol_after,
    )
    return {
        AUDIT_R6: audit,
        STANDARD_R6: standard,
        QRELS_R6: qrels,
        RECEIPT_R6: receipt,
    }


def _write_bundle(bundle: Mapping[Path, Mapping[str, object]]) -> None:
    for path, expected in bundle.items():
        if path.exists() and _read_json(path) != dict(expected):
            raise AssertionError(f"append-only r6 artifact already differs: {_relative(path)}")
    for path, value in bundle.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(
            stat.S_IRUSR | stat.S_IWUSR
            if path in {AUDIT_R6, QRELS_R6}
            else stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
        )


def _verify(bundle: Mapping[Path, Mapping[str, object]]) -> dict[str, object]:
    for path, expected in bundle.items():
        if _read_json(path) != dict(expected):
            raise AssertionError(f"r6 artifact drifted: {_relative(path)}")
    if QRELS_R6.stat().st_mode & 0o077 or AUDIT_R6.stat().st_mode & 0o077:
        raise AssertionError("host-private r6 artifacts have overly broad permissions")
    audit = _read_json(AUDIT_R6)
    standard = _read_json(STANDARD_R6)
    qrels = _read_json(QRELS_R6)
    receipt = _read_json(RECEIPT_R6)
    if audit.get("manifestSha256") != _self_hash(audit):
        raise AssertionError("r6 audit self-hash drifted")
    if standard.get("manifestSha256") != _self_hash(standard):
        raise AssertionError("r6 Standard self-hash drifted")
    if qrels.get("manifestSha256") != _self_hash(qrels):
        raise AssertionError("r6 qrels self-hash drifted")
    if receipt.get("receiptSha256") != _self_hash(receipt, field="receiptSha256"):
        raise AssertionError("r6 public receipt self-hash drifted")
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
        raise AssertionError("r6 candidate/Held-out/unbiased boundary drifted")
    if audit.get("semanticAssessment", {}).get("verdict") != "equivalent":
        raise AssertionError("r6 semantic equivalence audit did not pass")
    if standard.get("calibrationSource") != {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT_R6),
        "proposalSha256": audit["proposalSha256"],
    }:
        raise AssertionError("r6 Standard audit binding drifted")
    if qrels.get("answerEvidenceStandard") != standard:
        raise AssertionError("r6 qrels does not embed its public Standard")
    previous = _read_json(QRELS_R5)
    if qrels.get("candidateOf") != {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R5],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }:
        raise AssertionError("r6 qrels is not a direct r5 successor")
    if qrels.get("candidateBlindProposalSha256") != audit.get("proposalSha256"):
        raise AssertionError("r6 qrels proposal binding drifted")
    _assert_append_only_delta(previous, qrels)
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
        raise AssertionError("r6 public safety declaration drifted")
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
            raise AssertionError("r6 public artifact contains a private evidence body")
    prompt = receipt["lunaPromptV4Rescore"]
    model_only = receipt["lunaModelOnlyControl"]
    sol = receipt["solControl"]
    if (
        prompt.get("beforeCoveredFactCount") != 8
        or prompt.get("coveredFactCount") != 9
        or prompt.get("decision") != "keep"
        or model_only.get("coveredFactCount") != 8
        or model_only.get("decision") != "reject"
        or sol.get("coveredFactCount") != 7
        or sol.get("decision") != "reject"
        or receipt.get("calibrationDelta", {}).get("newlyCoveredFacts")
        != [f"{QUERY_ID}/{FACT_ID}"]
    ):
        raise AssertionError("r6 public comparison receipt drifted")
    return {
        "event": "ENTERPRISE_RAG_ATTENTION_STANDARD_R6_OK",
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "candidateBlind": False,
        "candidateAware": True,
        "auditAware": True,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        "factCount": 9,
        "supportGroupCount": 20,
        "evidenceBindingCount": 20,
        "lunaPromptV4CoveredFactCount": 9,
        "lunaPromptV4Decision": "keep",
        "lunaModelOnlyCoveredFactCount": 8,
        "lunaModelOnlyDecision": "reject",
        "solCoveredFactCount": 7,
        "solDecision": "reject",
        "newlyCoveredFacts": [f"{QUERY_ID}/{FACT_ID}"],
        "standardFileSha256": _file_sha256(STANDARD_R6),
        "standardManifestSha256": standard["manifestSha256"],
        "qrelsFileSha256": _file_sha256(QRELS_R6),
        "qrelsManifestSha256": qrels["manifestSha256"],
        "auditFileSha256": _file_sha256(AUDIT_R6),
        "auditManifestSha256": audit["manifestSha256"],
        "receiptFileSha256": _file_sha256(RECEIPT_R6),
        "receiptSha256": receipt["receiptSha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the deterministic append-only r6 audit, Standard, qrels, and receipt",
    )
    args = parser.parse_args()
    bundle = _build_bundle()
    if args.write:
        _write_bundle(bundle)
    print(json.dumps(_verify(bundle), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
