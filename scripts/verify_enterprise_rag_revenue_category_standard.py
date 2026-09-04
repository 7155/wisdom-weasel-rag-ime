#!/usr/bin/env python3
"""Build and verify the post-Validation qst_0477/F4 category revision.

The revision is deliberately candidate-aware and append-only.  It leaves the
frozen question, reference answer, required facts, candidate output, runner,
and the v2/r3 artifacts unchanged.  It changes only the qst_0477/F4 evidence
operator from an exhaustive conjunction of examples to category alternatives,
then appends the frozen candidate-cited category chunk.  Verification and
rescoring are offline and make zero Provider or Judge calls.
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


RUNNER = ROOT / "scripts/run_rag_agent_ablation.py"
RESEARCH = ROOT.parent / "paw-vertical-research" / "enterprise-rag-eval-lab"
PREPARED = RESEARCH / "artifacts/smoke-v1/host/prepared.json"
ANSWER_KEY = RESEARCH / "artifacts/smoke-v1/host/validation/answer-key.jsonl"
RETRIEVAL = RESEARCH / "results/validation-bge-qwen3-rerank-v1.json"
AUDIT_INPUT = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-qrels-independent-v2-candidate-blind-input-20260904.v1.json"
)
SOURCE_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-coverage-balanced-v4-r4-20260904.json"
)
STANDARD_V2 = ROOT / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.v2.json"
QRELS_V2 = ROOT / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-v2.json"
STANDARD_R3 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
QRELS_R3 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
AUDIT_R4 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-revenue-category-r4-audit-20260905.v1.json"
)
STANDARD_R4 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-revenue-category-r4.json"
)
QRELS_R4 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-revenue-category-r4.json"
)
RECEIPT_R4 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-revenue-category-r4-calibration-20260905.v1.json"
)

EXPECTED_FILE_SHA256 = {
    PREPARED: "833641681e44b1f1490249ced863568a48723b7ca4995628e17493d333bc6f96",
    ANSWER_KEY: "1bae86e7ee403ca4eacc48b06496aa820aeaaf4595a0e1a8c2c6a18057bd8b9f",
    RETRIEVAL: "3d4ebe22ff765ef403aec723e6d76b5cfddf3ce55dbc8f8b08e9932573a5bc0a",
    AUDIT_INPUT: "4f0cbae5798ff0849fb1d5109ab459a4398ef1e5a929c457df5b591cb92d3117",
    SOURCE_REPORT: "f7a4443c41b6738f9fdb8b5831d65d91a7ac7de71c54c3fd4c76e8b0d8edc252",
    STANDARD_V2: "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7",
    QRELS_V2: "b0b081c4a0ecbced1c589b69126de555a0f1b8815c508e1f4eb269adce608428",
    STANDARD_R3: "a8dcd8a37d2e599e07b4882d4e1df354835658a546f1c08ff71d109ebedf5e50",
    QRELS_R3: "4a02e4948a593d87d845739e5dcb60d61c33b6216da217ed79b3b9c4dc55d46d",
}

AUDIT_ID = "enterprise-rag-answer-evidence-candidate-aware-revenue-category-audit-r4-20260905"
STANDARD_ID = "enterprise-rag-answer-evidence-validation-candidate-aware-revenue-category-r4-20260905"
RUN_ID = "enterprise-rag-answer-evidence-standard-candidate-aware-revenue-category-r4-calibration-20260905"
CALIBRATION_LABEL = "post-validation-calibrated"
QUERY_ID = "qst_0477"
FACT_ID = "F4"
EVALUATION_CASE_ID = "case-02"
CATEGORY_GROUP_ID = "G4-revenue-category-r4"
CATEGORY_SUPPORT_LABEL = "paid_add_ons_category"
CATEGORY_DOCUMENT_ID = "dsid_dbd29f9393f149fbb696c9a5614dc875"
CATEGORY_DOCUMENT_SHA256 = "ffe908543aab45da3d65964fa305102edff748f1338025fa7d0ec6a7885c2274"
CATEGORY_CHUNK_ORDINAL = 0
CATEGORY_CHUNK_SHA256 = "a293fde74c5dd33cbbf5668a76db8ad01cef24a6952a42f57bb89e77759f66b1"
CATEGORY_QUOTE_SHA256 = "38a228147d677434dd15d2f341475a6f7d476d85ab7468cb6bc4937caccf2363"
QUESTION_SHA256 = "63c0d62a667cfe0a74258f1fa75e3e72339c599622d6b311d676512684a849d3"
REFERENCE_ANSWER_SHA256 = "f6d241af865e26a041d74aeed2bbc3a880db594c8b2cfb484da4084963372044"
FACT_SHA256 = "efa409791077b93114b3ed15b347c78b46b6154a8b650adb6c14276013083ed6"
JUDGE_RUBRIC_FACT_SHA256 = "c46b6e363df6b074bb654ab99d672f51ac9909695c4a3865468743ad52fe605b"
CANDIDATE_ANSWER_SHA256 = "ad7eeb6aafbb00ed5da7403c2461e63161f701dc4d642894efb12d13de842597"

EXPECTED_R3_COVERED_FACTS = {
    "qst_0474/F2",
    "qst_0474/F3",
    "qst_0474/F4",
    "qst_0474/F5",
    "qst_0477/F1",
    "qst_0477/F2",
}
EXPECTED_R4_COVERED_FACTS = EXPECTED_R3_COVERED_FACTS | {"qst_0477/F4"}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _self_hash(value: Mapping[str, object], *, field: str = "manifestSha256") -> str:
    return _sha256_json({key: item for key, item in value.items() if key != field})


def _relative(path: Path) -> str:
    return os.path.relpath(path, ROOT)


def _assert_frozen_file_hashes() -> None:
    for path, expected in EXPECTED_FILE_SHA256.items():
        observed = _file_sha256(path)
        if observed != expected:
            raise AssertionError(f"frozen input drifted: {_relative(path)}: {observed}")


def _fact(qrels: Mapping[str, object], query_id: str, fact_id: str) -> dict[str, Any]:
    raw_cases = qrels.get("cases")
    if not isinstance(raw_cases, list):
        raise AssertionError("qrels cases are malformed")
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or raw_case.get("queryId") != query_id:
            continue
        for raw_fact in raw_case.get("facts") or []:
            if isinstance(raw_fact, dict) and raw_fact.get("factId") == fact_id:
                return raw_fact
    raise AssertionError(f"missing fact: {query_id}/{fact_id}")


def _prepared_documents() -> dict[str, str]:
    prepared = _read_json(PREPARED)
    documents = {
        str(item["documentId"]): str(item["text"])
        for item in prepared.get("documents") or []
        if isinstance(item, Mapping)
    }
    if len(documents) != 5101:
        raise AssertionError("frozen prepared document denominator drifted")
    return documents


def _answer_key_case(query_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for line in ANSWER_KEY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict) and value.get("queryId") == query_id:
            matches.append(value)
    if len(matches) != 1:
        raise AssertionError(f"frozen answer key case is not unique: {query_id}")
    return matches[0]


def _audit_question() -> dict[str, Any]:
    audit_input = _read_json(AUDIT_INPUT)
    matches = [
        item
        for item in audit_input.get("questions") or []
        if isinstance(item, dict) and item.get("queryId") == QUERY_ID
    ]
    if len(matches) != 1:
        raise AssertionError("candidate-blind audit input omitted qst_0477")
    return matches[0]


def _audit_fact(question: Mapping[str, object]) -> dict[str, Any]:
    matches = [
        item
        for item in question.get("requiredFacts") or []
        if isinstance(item, dict) and item.get("factId") == FACT_ID
    ]
    if len(matches) != 1:
        raise AssertionError("frozen audit input omitted qst_0477/F4")
    return matches[0]


def _judge_rubric_fact(report: Mapping[str, object]) -> str:
    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen answer Judge is missing")
    for rubric in judge.get("caseRubrics") or []:
        if not isinstance(rubric, Mapping) or rubric.get("caseId") != EVALUATION_CASE_ID:
            continue
        for fact in rubric.get("requiredFacts") or []:
            if isinstance(fact, Mapping) and fact.get("factId") == FACT_ID:
                description = str(fact.get("description") or "")
                if _text_sha256(description) != JUDGE_RUBRIC_FACT_SHA256:
                    raise AssertionError("frozen Judge F4 rubric drifted")
                return description
    raise AssertionError("frozen Judge omitted qst_0477/F4")


def _category_quote(document_text: str) -> str:
    candidates: list[str] = []
    for line in document_text.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        candidates.append(normalized)
        if normalized.startswith("- "):
            candidates.append(normalized.removeprefix("- "))
    matches = [item for item in candidates if _text_sha256(item) == CATEGORY_QUOTE_SHA256]
    if len(matches) != 1:
        raise AssertionError("frozen category quote is not unique")
    return matches[0]


def _category_binding(documents: Mapping[str, str]) -> dict[str, object]:
    document_text = documents.get(CATEGORY_DOCUMENT_ID)
    if document_text is None or _text_sha256(document_text) != CATEGORY_DOCUMENT_SHA256:
        raise AssertionError("frozen category document drifted")
    prior = _fact(_read_json(QRELS_R3), QUERY_ID, "F1")
    source_binding = prior["supportGroups"][0]["evidence"][0]
    if (
        source_binding.get("documentId") != CATEGORY_DOCUMENT_ID
        or source_binding.get("chunkOrdinal") != CATEGORY_CHUNK_ORDINAL
        or source_binding.get("chunkSha256") != CATEGORY_CHUNK_SHA256
    ):
        raise AssertionError("r3 category-document metadata binding drifted")
    quote = _category_quote(document_text)
    return {
        "chunkOrdinal": CATEGORY_CHUNK_ORDINAL,
        "chunkSha256": CATEGORY_CHUNK_SHA256,
        "documentId": CATEGORY_DOCUMENT_ID,
        "documentSha256": CATEGORY_DOCUMENT_SHA256,
        "quote": quote,
        "quoteSha256": CATEGORY_QUOTE_SHA256,
        "sourceType": source_binding["sourceType"],
        "title": source_binding["title"],
    }


def _candidate_evidence(report: Mapping[str, object]) -> dict[str, object]:
    lanes = report.get("lanes")
    if not isinstance(lanes, list):
        raise AssertionError("frozen candidate lanes are malformed")
    agentic = next(
        (item for item in lanes if isinstance(item, Mapping) and item.get("lane") == "agentic"),
        None,
    )
    if not isinstance(agentic, Mapping):
        raise AssertionError("frozen Agentic lane is missing")
    score = agentic.get("score")
    if not isinstance(score, Mapping):
        raise AssertionError("frozen Agentic score is missing")
    answer_case = next(
        (
            item
            for item in score.get("answerCases") or []
            if isinstance(item, Mapping) and item.get("queryId") == QUERY_ID
        ),
        None,
    )
    if not isinstance(answer_case, Mapping):
        raise AssertionError("frozen Agentic qst_0477 case is missing")
    if answer_case.get("answerSha256") != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen Agentic qst_0477 answer hash drifted")

    matching_tokens: set[str] = set()
    ledger = agentic.get("gatewayLedger")
    raw_items = ledger.get("items") if isinstance(ledger, Mapping) else None
    if not isinstance(raw_items, list):
        raise AssertionError("frozen Agentic citation ledger is missing")
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
            if (
                hit.get("externalDocumentId") == CATEGORY_DOCUMENT_ID
                and hit.get("ordinal") == CATEGORY_CHUNK_ORDINAL
            ):
                matching_tokens.add(str(hit.get("citationRef") or ""))
    cited_tokens = {str(item) for item in answer_case.get("citationTokens") or []}
    matching_tokens.discard("")
    if len(matching_tokens & cited_tokens) != 1:
        raise AssertionError("frozen candidate does not uniquely cite the category chunk")
    citation_token = next(iter(matching_tokens & cited_tokens))
    if CATEGORY_DOCUMENT_ID not in {str(item) for item in answer_case.get("citations") or []}:
        raise AssertionError("frozen candidate citation projection omitted the category document")

    judge = report.get("answerJudge")
    if not isinstance(judge, Mapping):
        raise AssertionError("frozen Judge projection is missing")
    candidate_by_lane = {
        str(item.get("lane") or ""): str(item.get("candidateId") or "")
        for item in judge.get("candidateMapping") or []
        if isinstance(item, Mapping)
    }
    candidate_id = candidate_by_lane.get("agentic", "")
    candidate_answer = ""
    for evidence_case in judge.get("evidenceCases") or []:
        if not isinstance(evidence_case, Mapping) or evidence_case.get("caseId") != EVALUATION_CASE_ID:
            continue
        for candidate in evidence_case.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("candidateId") == candidate_id:
                candidate_answer = str(candidate.get("answer") or "")
    if _text_sha256(candidate_answer) != CANDIDATE_ANSWER_SHA256:
        raise AssertionError("frozen candidate body does not match its authoritative hash")
    return {
        "lane": "agentic",
        "queryId": QUERY_ID,
        "evaluationCaseId": EVALUATION_CASE_ID,
        "answer": candidate_answer,
        "answerSha256": CANDIDATE_ANSWER_SHA256,
        "citationToken": citation_token,
        "citationTokenSha256": _text_sha256(citation_token),
        "documentId": CATEGORY_DOCUMENT_ID,
        "chunkOrdinal": CATEGORY_CHUNK_ORDINAL,
    }


def _proposal(binding: Mapping[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "paw.enterprise-rag-revenue-category-qrels-proposal.v1",
        "predecessorQrelsFileSha256": EXPECTED_FILE_SHA256[QRELS_R3],
        "changedFacts": [f"{QUERY_ID}/{FACT_ID}"],
        "supportGroupMode": {"before": "all", "after": "any"},
        "appendSupportGroup": {
            "groupId": CATEGORY_GROUP_ID,
            "supportLabel": CATEGORY_SUPPORT_LABEL,
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
    binding = _category_binding(documents)
    candidate = _candidate_evidence(report)
    reference_facts = answer_key.get("answerFacts")
    audit_facts = [
        str(item.get("description") or "")
        for item in question.get("requiredFacts") or []
        if isinstance(item, Mapping)
    ]
    if reference_facts != audit_facts:
        raise AssertionError("frozen reference and audit fact lists disagree")
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
    if (
        _text_sha256(semantic_unit["question"]) != QUESTION_SHA256
        or _text_sha256(semantic_unit["referenceAnswer"]) != REFERENCE_ANSWER_SHA256
        or _text_sha256(semantic_unit["fact"]) != FACT_SHA256
    ):
        raise AssertionError("frozen qst_0477/F4 semantic unit drifted")
    proposal = _proposal(binding)
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-revenue-category-candidate-aware-audit.v1",
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
        },
        "frozenSemanticUnit": semantic_unit,
        "predecessorF4": {
            "supportGroupMode": _fact(_read_json(QRELS_R3), QUERY_ID, FACT_ID)[
                "supportGroupMode"
            ],
            "supportGroupCount": len(
                _fact(_read_json(QRELS_R3), QUERY_ID, FACT_ID)["supportGroups"]
            ),
            "supportLabels": [
                str(item.get("supportLabel") or "")
                for item in _fact(_read_json(QRELS_R3), QUERY_ID, FACT_ID)[
                    "supportGroups"
                ]
                if isinstance(item, Mapping)
            ],
        },
        "sourceCandidate": candidate,
        "acceptedCategoryBinding": binding,
        "semanticAssessment": {
            "verdict": "overconstrained",
            "questionScoringUnit": "revenue_stream_category",
            "factScoringUnit": "paid_add_ons_category",
            "referenceExamplesAreExhaustivePredicates": False,
            "priorAllModeTests": "all_three_non_exhaustive_examples",
            "requiredMode": "any",
            "reasoning": [
                "The question asks for four revenue-stream categories, so F4 is one category-level scoring unit.",
                "The frozen reference and fact introduce retention, compliance, and premium SLA as non-exhaustive examples of add-ons.",
                "The frozen Judge rubric independently reduces F4 to paid add-ons such as compliance or support packages.",
                "The candidate-cited exact chunk directly names compliance/support add-ons as separately sold SKUs.",
                "Requiring all three example groups scores exhaustive example citation coverage rather than support for the paid-add-ons category.",
            ],
        },
        "proposal": proposal,
        "proposalSha256": _sha256_json(proposal),
        "claimBoundary": [
            "This audit inspected the frozen candidate answer, citations, and cited chunk, so it is not candidate blind.",
            "The proposed successor changes only qst_0477/F4 and cannot support an unbiased promotion claim.",
            "The proposed category binding is exact to the frozen document chunk; no new fact, candidate answer, Runner behavior, Prompt, or dataset content is introduced.",
            "No Provider or Judge was called and Held-out remains unopened.",
        ],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_standard(audit: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(_read_json(STANDARD_R3))
    value["standardId"] = STANDARD_ID
    value["calibrationLabel"] = CALIBRATION_LABEL
    value["candidateBlind"] = False
    value["calibrationSource"] = {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT_R4),
        "proposalSha256": audit["proposalSha256"],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_qrels(
    standard: Mapping[str, object], audit: Mapping[str, object]
) -> dict[str, object]:
    previous = _read_json(QRELS_R3)
    value = copy.deepcopy(previous)
    value["candidateOf"] = {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R3],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }
    value["answerEvidenceStandard"] = dict(standard)
    value["standardManifestSha256"] = standard["manifestSha256"]
    value["candidateBlindProposalSha256"] = audit["proposalSha256"]
    f4 = _fact(value, QUERY_ID, FACT_ID)
    if f4.get("supportGroupMode") != "all" or len(f4.get("supportGroups") or []) != 3:
        raise AssertionError("r3 qst_0477/F4 predecessor shape drifted")
    f4["supportGroupMode"] = "any"
    f4["supportGroups"].append(copy.deepcopy(audit["proposal"]["appendSupportGroup"]))
    value["counts"] = {
        "caseCount": 2,
        "factCount": 9,
        "supportGroupCount": 18,
        "evidenceBindingCount": 18,
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _selected_cases(
    audit_input: Mapping[str, object], case_ids: set[str]
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for question in audit_input.get("questions") or []:
        if not isinstance(question, Mapping) or question.get("queryId") not in case_ids:
            continue
        selected.append(
            {
                "queryId": question["queryId"],
                "answerFacts": [
                    fact["description"]
                    for fact in question.get("requiredFacts") or []
                    if isinstance(fact, Mapping)
                ],
            }
        )
    return selected


def _source_cases(report: Mapping[str, object]) -> list[dict[str, object]]:
    lanes = report.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise AssertionError("frozen source report lanes are missing")
    baseline = next(
        (item for item in lanes if isinstance(item, Mapping) and item.get("lane") == "baseline"),
        None,
    )
    score = baseline.get("score") if isinstance(baseline, Mapping) else None
    answer_cases = score.get("answerCases") if isinstance(score, Mapping) else None
    if not isinstance(answer_cases, list):
        raise AssertionError("frozen baseline answer cases are missing")
    return [
        {
            "queryId": str(item.get("queryId") or ""),
            "evaluationCaseId": str(item.get("evaluationCaseId") or ""),
            "abstentionExpected": item.get("abstentionExpected") is True,
        }
        for item in answer_cases
        if isinstance(item, Mapping)
    ]


def _covered_facts(
    qrel_case: Mapping[str, object], cited_chunk_keys: set[tuple[str, int]]
) -> list[str]:
    covered: list[str] = []
    for fact in qrel_case.get("facts") or []:
        if not isinstance(fact, Mapping):
            raise AssertionError("normalized qrel fact is malformed")
        group_matches: list[bool] = []
        for group in fact.get("supportGroups") or []:
            if not isinstance(group, Mapping):
                raise AssertionError("normalized qrel support group is malformed")
            evidence_keys = {
                (str(item.get("documentId") or ""), int(item.get("chunkOrdinal")))
                for item in group.get("evidence") or []
                if isinstance(item, Mapping)
            }
            group_matches.append(bool(cited_chunk_keys & evidence_keys))
        mode = str(fact.get("supportGroupMode") or "")
        supported = all(group_matches) if mode == "all" else any(group_matches)
        if supported:
            covered.append(str(fact.get("factId") or ""))
    return covered


def _exact_rescore(qrels: Mapping[str, object]) -> dict[str, object]:
    documents = _prepared_documents()
    retrieval = _read_json(RETRIEVAL)
    retrieval_dataset = retrieval.get("dataset")
    if not isinstance(retrieval_dataset, Mapping):
        raise AssertionError("frozen retrieval dataset is malformed")
    selected_cases = _selected_cases(_read_json(AUDIT_INPUT), set(qrels["caseIds"]))
    private_qrels, stats = _validate_answer_evidence_qrels(
        qrels,
        selected_cases=selected_cases,
        document_text_by_id=documents,
        prepared_source_sha256=str(retrieval_dataset.get("sourceSha256") or ""),
        prepared_artifact_sha256=EXPECTED_FILE_SHA256[PREPARED],
        evaluation_split="validation",
        chunking_config=dict(retrieval["chunking"]),
    )
    report = _read_json(SOURCE_REPORT)
    if (
        report.get("schemaVersion") != "rag-ime.rag-agent-ablation-run.v1"
        or report.get("formalAcceptanceEligible") is not False
        or report.get("formalAcceptancePassed") is not False
        or report.get("heldOutAuthorization", {}).get("authorized") is not False
    ):
        raise AssertionError("frozen source report claim boundary drifted")
    judge = report.get("answerJudge")
    if (
        not isinstance(judge, Mapping)
        or judge.get("retrievalQrelAccess") is not False
        or judge.get("judgeFeedbackToAgent") is not False
        or judge.get("candidateCitedEvidenceAccessAfterGeneration") is not True
    ):
        raise AssertionError("frozen Judge isolation boundary drifted")
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
            raise AssertionError("rescored lane gates are malformed")
        hard_gates["citationResolution"] = bool(
            hard_evidence.get("citationResolution") is True
            and hard_evidence.get("factCitationCoverage") is True
        )
    agentic = next(item for item in lanes if item.get("lane") == "agentic")
    agentic_score = agentic["score"]
    covered_fact_ids: list[str] = []
    for answer_case in agentic_score["answerCases"]:
        query_id = str(answer_case.get("queryId") or "")
        qrel_case = private_qrels.get(query_id)
        if not isinstance(qrel_case, Mapping):
            continue
        cited_chunk_keys = _answer_only_cited_chunk_keys(agentic, answer_case)
        covered_fact_ids.extend(
            f"{query_id}/{fact_id}"
            for fact_id in _covered_facts(qrel_case, cited_chunk_keys)
        )
    covered_fact_ids.sort()
    decision = _build_candidate_decision(lanes)
    metric = float(agentic_score["agentMetrics"]["citationFactCoverage"])
    if abs(metric - (len(covered_fact_ids) / stats["factCount"])) > 1e-12:
        raise AssertionError("exact covered-fact projection disagrees with runner metric")
    return {
        "qrelsStats": stats,
        "coveredFactIds": covered_fact_ids,
        "coveredFactCount": len(covered_fact_ids),
        "factCount": stats["factCount"],
        "citationFactCoverage": metric,
        "decision": str(decision.get("decision") or ""),
        "failedHardGates": list(decision.get("failedHardGates") or []),
        "sourceReportSha256": str(report.get("reportSha256") or ""),
        "sourceAnswerSha256": CANDIDATE_ANSWER_SHA256,
    }


def _build_receipt(
    *,
    audit: Mapping[str, object],
    standard: Mapping[str, object],
    qrels: Mapping[str, object],
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    newly_covered = sorted(
        set(after["coveredFactIds"]) - set(before["coveredFactIds"])
    )
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-answer-evidence-revenue-category-calibration.v1",
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
            "auditReceiptFileSha256": _file_sha256(AUDIT_R4),
            "auditReceiptManifestSha256": audit["manifestSha256"],
            "candidateCitationsAccessed": True,
            "questionReferenceFactsAccessed": True,
            "heldOutAccessed": False,
        },
        "predecessor": {
            "standardR3FileSha256": EXPECTED_FILE_SHA256[STANDARD_R3],
            "standardR3ManifestSha256": _read_json(STANDARD_R3)["manifestSha256"],
            "qrelsR3FileSha256": EXPECTED_FILE_SHA256[QRELS_R3],
            "qrelsR3ManifestSha256": _read_json(QRELS_R3)["manifestSha256"],
        },
        "standard": {
            "path": _relative(STANDARD_R4),
            "schemaVersion": standard["schemaVersion"],
            "standardId": standard["standardId"],
            "fileSha256": _file_sha256(STANDARD_R4),
            "manifestSha256": standard["manifestSha256"],
        },
        "qrels": {
            "scope": "host-only",
            "path": _relative(QRELS_R4),
            "schemaVersion": qrels["schemaVersion"],
            "fileSha256": _file_sha256(QRELS_R4),
            "manifestSha256": qrels["manifestSha256"],
            "factCount": 9,
            "supportGroupCount": 18,
            "evidenceBindingCount": 18,
        },
        "calibrationDelta": {
            "operator": "align_f4_to_paid_add_ons_category",
            "changedFacts": [f"{QUERY_ID}/{FACT_ID}"],
            "supportGroupModeBefore": "all",
            "supportGroupModeAfter": "any",
            "addedExactBindings": 1,
            "otherFactBindingsAdded": 0,
            "newlyCoveredFacts": newly_covered,
        },
        "frozenCandidateRescore": {
            "sourceReportPath": _relative(SOURCE_REPORT),
            "sourceReportFileSha256": EXPECTED_FILE_SHA256[SOURCE_REPORT],
            "sourceReportSha256": after["sourceReportSha256"],
            "sourceAnswerSha256": CANDIDATE_ANSWER_SHA256,
            "lane": "agentic",
            "scorerContract": "exact-citation-token-to-document-chunk-ordinal",
            "runnerPath": _relative(RUNNER),
            "runnerFileSha256": _file_sha256(RUNNER),
            "verifierPath": _relative(Path(__file__)),
            "verifierFileSha256": _file_sha256(Path(__file__)),
            "measurementStatus": "post-validation-candidate-aware",
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
            "command": "python3 scripts/verify_enterprise_rag_revenue_category_standard.py",
            "result": "ENTERPRISE_RAG_REVENUE_CATEGORY_STANDARD_R4_OK",
        },
        "claimBoundary": [
            "This receipt proves an append-only post-Validation Standard/qrels fixed point and offline rescore, not a model-quality improvement or production result.",
            "The audit accessed the frozen candidate and its cited chunk, so candidateBlind is false and unbiased promotion remains forbidden.",
            "Only qst_0477/F4 changes: the scorer now measures the paid-add-ons category rather than mandatory citation of all listed examples.",
            "The exact frozen Luna v4 candidate rises from 6/9 to 7/9 citation facts and remains Reject; no other fact is newly credited.",
            "No Provider or Judge was called, no candidate was rerun, and Held-out remains unopened.",
        ],
    }
    value["receiptSha256"] = _self_hash(value, field="receiptSha256")
    return value


def _write_json(path: Path, value: Mapping[str, object], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_artifacts() -> None:
    _assert_frozen_file_hashes()
    audit = _build_audit()
    _write_json(AUDIT_R4, audit, private=True)
    standard = _build_standard(audit)
    _write_json(STANDARD_R4, standard)
    qrels = _build_qrels(standard, audit)
    _write_json(QRELS_R4, qrels, private=True)
    before = _exact_rescore(_read_json(QRELS_R3))
    after = _exact_rescore(qrels)
    if set(before["coveredFactIds"]) != EXPECTED_R3_COVERED_FACTS:
        raise AssertionError("r3 frozen-candidate exact coverage drifted")
    if set(after["coveredFactIds"]) != EXPECTED_R4_COVERED_FACTS:
        raise AssertionError("r4 frozen-candidate exact coverage drifted")
    if after["decision"] != "reject":
        raise AssertionError("r4 frozen candidate must remain Reject")
    receipt = _build_receipt(
        audit=audit,
        standard=standard,
        qrels=qrels,
        before=before,
        after=after,
    )
    _write_json(RECEIPT_R4, receipt)


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
                raise AssertionError(f"r4 changed an out-of-scope fact: {query_id}/{fact_id}")
    if observed_changes != {(QUERY_ID, FACT_ID)}:
        raise AssertionError(f"r4 changed the wrong fact set: {observed_changes!r}")
    before_f4 = _fact(previous, QUERY_ID, FACT_ID)
    after_f4 = _fact(revised, QUERY_ID, FACT_ID)
    if before_f4.get("supportGroupMode") != "all" or after_f4.get("supportGroupMode") != "any":
        raise AssertionError("qst_0477/F4 category operator delta drifted")
    before_groups = before_f4.get("supportGroups")
    after_groups = after_f4.get("supportGroups")
    if (
        not isinstance(before_groups, list)
        or not isinstance(after_groups, list)
        or before_groups != after_groups[:-1]
        or len(after_groups) != len(before_groups) + 1
    ):
        raise AssertionError("qst_0477/F4 support-group delta is not append-only")
    appended = after_groups[-1]
    if (
        not isinstance(appended, Mapping)
        or appended.get("groupId") != CATEGORY_GROUP_ID
        or appended.get("supportLabel") != CATEGORY_SUPPORT_LABEL
        or len(appended.get("evidence") or []) != 1
    ):
        raise AssertionError("qst_0477/F4 category group drifted")
    binding = appended["evidence"][0]
    expected = {
        "documentId": CATEGORY_DOCUMENT_ID,
        "documentSha256": CATEGORY_DOCUMENT_SHA256,
        "chunkOrdinal": CATEGORY_CHUNK_ORDINAL,
        "chunkSha256": CATEGORY_CHUNK_SHA256,
        "quoteSha256": CATEGORY_QUOTE_SHA256,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise AssertionError("qst_0477/F4 exact category binding drifted")


def _verify() -> dict[str, object]:
    _assert_frozen_file_hashes()
    if QRELS_R4.stat().st_mode & 0o077 or AUDIT_R4.stat().st_mode & 0o077:
        raise AssertionError("host-private r4 artifacts have overly broad permissions")
    previous = _read_json(QRELS_R3)
    audit = _read_json(AUDIT_R4)
    standard = _read_json(STANDARD_R4)
    qrels = _read_json(QRELS_R4)
    receipt = _read_json(RECEIPT_R4)
    if audit.get("manifestSha256") != _self_hash(audit):
        raise AssertionError("r4 audit self-hash drifted")
    if standard.get("manifestSha256") != _self_hash(standard):
        raise AssertionError("r4 Standard self-hash drifted")
    if qrels.get("manifestSha256") != _self_hash(qrels):
        raise AssertionError("r4 qrels self-hash drifted")
    if receipt.get("receiptSha256") != _self_hash(receipt, field="receiptSha256"):
        raise AssertionError("r4 public receipt self-hash drifted")
    if (
        audit.get("candidateBlind") is not False
        or audit.get("candidateAware") is not True
        or audit.get("auditAware") is not True
        or audit.get("candidateCitationsAccessed") is not True
        or standard.get("candidateBlind") is not False
        or standard.get("heldOutOpened") is not False
        or standard.get("unbiasedPromotionClaimAllowed") is not False
        or receipt.get("providerCalls") != 0
        or receipt.get("heldOutOpened") is not False
        or receipt.get("unbiasedPromotionClaimAllowed") is not False
    ):
        raise AssertionError("r4 candidate/Held-out/unbiased claim boundary drifted")
    if standard.get("calibrationSource") != {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT_R4),
        "proposalSha256": audit["proposalSha256"],
    }:
        raise AssertionError("r4 Standard audit binding drifted")
    if qrels.get("answerEvidenceStandard") != standard:
        raise AssertionError("r4 qrels does not embed the public Standard")
    if qrels.get("candidateOf") != {
        "fileSha256": EXPECTED_FILE_SHA256[QRELS_R3],
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }:
        raise AssertionError("r4 qrels is not a direct r3 successor")
    if qrels.get("candidateBlindProposalSha256") != audit.get("proposalSha256"):
        raise AssertionError("r4 qrels proposal binding drifted")
    _assert_append_only_delta(previous, qrels)

    before = _exact_rescore(previous)
    after = _exact_rescore(qrels)
    if set(before["coveredFactIds"]) != EXPECTED_R3_COVERED_FACTS:
        raise AssertionError("r3 exact covered-fact set drifted")
    if set(after["coveredFactIds"]) != EXPECTED_R4_COVERED_FACTS:
        raise AssertionError("r4 exact covered-fact set drifted")
    if set(after["coveredFactIds"]) - set(before["coveredFactIds"]) != {f"{QUERY_ID}/{FACT_ID}"}:
        raise AssertionError("r4 credited more than the category fact")
    if after["coveredFactCount"] != 7 or after["factCount"] != 9 or after["decision"] != "reject":
        raise AssertionError("r4 frozen-candidate verdict drifted")
    if receipt.get("frozenCandidateRescore", {}).get("coveredFactCount") != 7:
        raise AssertionError("r4 public receipt coverage drifted")
    if (
        receipt.get("frozenCandidateRescore", {}).get("runnerFileSha256")
        != _file_sha256(RUNNER)
        or receipt.get("frozenCandidateRescore", {}).get("verifierFileSha256")
        != _file_sha256(Path(__file__))
    ):
        raise AssertionError("r4 exact scorer implementation binding drifted")
    if receipt.get("calibrationDelta", {}).get("newlyCoveredFacts") != [f"{QUERY_ID}/{FACT_ID}"]:
        raise AssertionError("r4 public receipt overcredits facts")
    if any(receipt.get("publicSafety", {}).get(key) is not False for key in (
        "containsQuestions",
        "containsReferenceAnswers",
        "containsFactBodies",
        "containsEvidenceQuotes",
        "containsQrelsBody",
        "containsCandidateAnswers",
        "containsPrivateTranscripts",
    )):
        raise AssertionError("r4 public receipt safety declaration drifted")
    serialized_public_artifacts = json.dumps([standard, receipt], ensure_ascii=False)
    for private_body in (
        audit["frozenSemanticUnit"]["question"],
        audit["frozenSemanticUnit"]["referenceAnswer"],
        audit["frozenSemanticUnit"]["fact"],
        audit["frozenSemanticUnit"]["judgeRubricFact"],
        audit["acceptedCategoryBinding"]["quote"],
        audit["sourceCandidate"]["answer"],
    ):
        if private_body in serialized_public_artifacts:
            raise AssertionError("r4 public artifact contains a private evidence body")
    stats = after["qrelsStats"]
    return {
        "event": "ENTERPRISE_RAG_REVENUE_CATEGORY_STANDARD_R4_OK",
        "providerCalls": 0,
        "judgeCalls": 0,
        "candidateRuns": 0,
        "candidateBlind": False,
        "candidateAware": True,
        "auditAware": True,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        **stats,
        "frozenCandidateCoveredFactCount": 7,
        "frozenCandidateFactCount": 9,
        "frozenCandidateDecision": "reject",
        "newlyCoveredFacts": [f"{QUERY_ID}/{FACT_ID}"],
        "standardFileSha256": _file_sha256(STANDARD_R4),
        "standardManifestSha256": standard["manifestSha256"],
        "qrelsFileSha256": _file_sha256(QRELS_R4),
        "qrelsManifestSha256": qrels["manifestSha256"],
        "auditFileSha256": _file_sha256(AUDIT_R4),
        "auditManifestSha256": audit["manifestSha256"],
        "receiptFileSha256": _file_sha256(RECEIPT_R4),
        "receiptSha256": receipt["receiptSha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the deterministic append-only r4 audit, Standard, qrels, and receipt",
    )
    args = parser.parse_args()
    if args.write:
        _write_artifacts()
    print(json.dumps(_verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
