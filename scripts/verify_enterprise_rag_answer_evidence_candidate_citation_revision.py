#!/usr/bin/env python3
"""Build or verify the post-Validation candidate-citation qrels revision.

The revision is intentionally append-only and offline.  It records only three
exact candidate-cited chunks that a post-run audit confirmed as equivalent
support for qst_0474/F2, F3, and F5.  It does not alter Standard v2, does not
open Held-out, and cannot be used as an unbiased promotion result.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_rag_agent_ablation import (  # noqa: E402
    _sha256_json,
    _validate_answer_evidence_qrels,
)


RESEARCH = ROOT.parent / "paw-vertical-research" / "enterprise-rag-eval-lab"
PREPARED = RESEARCH / "artifacts/smoke-v1/host/prepared.json"
RETRIEVAL = RESEARCH / "results/validation-bge-qwen3-rerank-v1.json"
AUDIT_INPUT = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-qrels-independent-v2-candidate-blind-input-20260904.v1.json"
)
QRELS_V2 = ROOT / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-v2.json"
STANDARD_V2 = ROOT / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.v2.json"
SOURCE_REPORT = (
    ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-coverage-balanced-v4-r4-20260904.json"
)
AUDIT = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-citation-revision-r3-audit-20260905.v1.json"
)
STANDARD = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
QRELS = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
RECEIPT = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-citation-revision-r3-calibration-20260905.v1.json"
)

EXPECTED_QRELS_V2_FILE_SHA256 = (
    "b0b081c4a0ecbced1c589b69126de555a0f1b8815c508e1f4eb269adce608428"
)
EXPECTED_STANDARD_V2_FILE_SHA256 = (
    "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7"
)
EXPECTED_SOURCE_REPORT_FILE_SHA256 = (
    "f7a4443c41b6738f9fdb8b5831d65d91a7ac7de71c54c3fd4c76e8b0d8edc252"
)
STANDARD_ID = (
    "enterprise-rag-answer-evidence-validation-candidate-citation-revision-r3-20260905"
)
AUDIT_ID = "enterprise-rag-answer-evidence-candidate-citation-exact-audit-r3-20260905"
CALIBRATION_LABEL = "post-validation-calibrated"

ADDITIONS: tuple[dict[str, object], ...] = (
    {
        "queryId": "qst_0474",
        "factId": "F2",
        "citationToken": "K3",
        "groupId": "G2-candidate-citation-r3",
        "supportLabel": "runtime_continuous_batching_candidate_cited_equivalent",
        "documentId": "dsid_e22f3cff77dd4fd3bee54fa8c4a99aac",
        "documentSha256": "025d8bb3058170d22925a97c69cc1e31457932aa189336ed65336fd14ad9627d",
        "chunkOrdinal": 3,
        "chunkSha256": "4e170501b9197220876472e219ce78d55df7701e866d5bea18c07b8b4a900c97",
        "quote": "- Managed cloud endpoints (major cloud providers): emphasize model-level optimizations (KV cache, continuous batching) and transparent unit economics vs opaque managed prices.",
        "sourceType": "google_drive",
        "title": "Triage tension map: ML, backend, platform talk tracks",
    },
    {
        "queryId": "qst_0474",
        "factId": "F3",
        "citationToken": "K3",
        "groupId": "G2-candidate-citation-r3",
        "supportLabel": "runtime_kv_management_candidate_cited_equivalent",
        "documentId": "dsid_e22f3cff77dd4fd3bee54fa8c4a99aac",
        "documentSha256": "025d8bb3058170d22925a97c69cc1e31457932aa189336ed65336fd14ad9627d",
        "chunkOrdinal": 3,
        "chunkSha256": "4e170501b9197220876472e219ce78d55df7701e866d5bea18c07b8b4a900c97",
        "quote": "- Managed cloud endpoints (major cloud providers): emphasize model-level optimizations (KV cache, continuous batching) and transparent unit economics vs opaque managed prices.",
        "sourceType": "google_drive",
        "title": "Triage tension map: ML, backend, platform talk tracks",
    },
    {
        "queryId": "qst_0474",
        "factId": "F5",
        "citationToken": "K27",
        "groupId": "G3-candidate-citation-r3",
        "supportLabel": "kernel_selection_arch_sequence_hardware_candidate_cited_equivalent",
        "documentId": "dsid_94b0d0306935482d820e38d0bd986139",
        "documentSha256": "074b6093f6aa5fd9ad288817e33005ceb067e5abdf84a37af89008461ddee8e1",
        "chunkOrdinal": 2,
        "chunkSha256": "65d11ed6ef3300b58a94c4b9c4c14e5324d73b3798de54dfc4ce602da3d9813b",
        "quote": "- Feature signals: (1) model family/architecture (Llama/Mistral/Qwen/Gemma/variants), (2) seq bucket / regime hints, (3) GPU SKU.",
        "sourceType": "google_drive",
        "title": "Runtime 1.21 Launch Brief (Draft) — Kernel Auto-Selection v2 + Rollout Plan",
    },
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _self_hash(value: Mapping[str, object], field: str = "manifestSha256") -> str:
    return _sha256_json({key: item for key, item in value.items() if key != field})


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
    raise AssertionError(f"missing qrel fact: {query_id}/{fact_id}")


def _binding(addition: Mapping[str, object]) -> dict[str, object]:
    quote = str(addition["quote"])
    return {
        "chunkOrdinal": addition["chunkOrdinal"],
        "chunkSha256": addition["chunkSha256"],
        "documentId": addition["documentId"],
        "documentSha256": addition["documentSha256"],
        "quote": quote,
        "quoteSha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "sourceType": addition["sourceType"],
        "title": addition["title"],
    }


def _proposal() -> list[dict[str, object]]:
    return [
        {
            "queryId": item["queryId"],
            "factId": item["factId"],
            "citationToken": item["citationToken"],
            "groupId": item["groupId"],
            "supportLabel": item["supportLabel"],
            "evidence": _binding(item),
        }
        for item in ADDITIONS
    ]


def _build_audit() -> dict[str, object]:
    source = _read_json(SOURCE_REPORT)
    proposal = _proposal()
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-candidate-citation-exact-audit.v1",
        "auditId": AUDIT_ID,
        "evaluatedAt": "2026-09-05",
        "evaluationScope": "validation-development-only",
        "candidateBlind": False,
        "candidateCitationsAccessed": True,
        "providerCalls": 0,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        "sourceCandidate": {
            "path": os.path.relpath(SOURCE_REPORT, ROOT),
            "fileSha256": _file_sha256(SOURCE_REPORT),
            "reportSha256": source.get("reportSha256"),
            "lane": "agentic",
            "queryId": "qst_0474",
        },
        "proposalSha256": _sha256_json(proposal),
        "acceptedBindings": proposal,
        "rejectedCalibration": [
            {
                "queryId": "qst_0474",
                "factId": "F1",
                "citationToken": "K18",
                "documentId": "dsid_9044f930b59d4b5cb505b1a014ef70ea",
                "chunkOrdinal": 2,
                "chunkSha256": "ee501ad257e707a6e6fc52f3e3d7cd4767810d3191b763446c84c37262772940",
                "reasonCode": "cited_chunk_truncated_before_material_claim",
            },
            {
                "queryId": "qst_0477",
                "factId": "F3",
                "reasonCode": "candidate_citation_not_independently_accepted_for_fact",
            },
            {
                "queryId": "qst_0477",
                "factId": "F4",
                "reasonCode": "candidate_citation_not_independently_accepted_for_fact",
            },
        ],
        "claimBoundary": [
            "The audit inspected the frozen candidate's citation tokens and cited chunks, so it was not candidate blind.",
            "Only qst_0474/F2, F3, and F5 received equivalent exact bindings; F1 and qst_0477/F3-F4 remain unsupported under this revision.",
            "This post-Validation calibration cannot support an unbiased promotion or model-quality improvement claim.",
        ],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_standard(audit: Mapping[str, object]) -> dict[str, object]:
    previous = _read_json(STANDARD_V2)
    value = copy.deepcopy(previous)
    value["standardId"] = STANDARD_ID
    value["calibrationLabel"] = CALIBRATION_LABEL
    value["candidateBlind"] = False
    value["calibrationSource"] = {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT),
        "proposalSha256": audit["proposalSha256"],
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_qrels(standard: Mapping[str, object], audit: Mapping[str, object]) -> dict[str, object]:
    previous = _read_json(QRELS_V2)
    value = copy.deepcopy(previous)
    value["candidateOf"] = {
        "fileSha256": _file_sha256(QRELS_V2),
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }
    value["answerEvidenceStandard"] = dict(standard)
    value["standardManifestSha256"] = standard["manifestSha256"]
    value["candidateBlindProposalSha256"] = audit["proposalSha256"]
    for addition in ADDITIONS:
        raw_fact = _fact(value, str(addition["queryId"]), str(addition["factId"]))
        raw_fact["supportGroups"].append(
            {
                "evidence": [_binding(addition)],
                "groupId": addition["groupId"],
                "supportLabel": addition["supportLabel"],
            }
        )
    value["counts"] = {
        "caseCount": 2,
        "factCount": 9,
        "supportGroupCount": 17,
        "evidenceBindingCount": 17,
    }
    value["manifestSha256"] = _self_hash(value)
    return value


def _build_receipt(
    *, audit: Mapping[str, object], standard: Mapping[str, object], qrels: Mapping[str, object]
) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": "paw.enterprise-rag-answer-evidence-standard-candidate-citation-calibration.v1",
        "runId": "enterprise-rag-answer-evidence-standard-candidate-citation-revision-r3-calibration-20260905",
        "status": "passed",
        "evaluationScope": "validation-development-only",
        "calibrationLabel": CALIBRATION_LABEL,
        "candidateBlind": False,
        "localOnly": True,
        "uploaded": False,
        "providerCalls": 0,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        "auditBoundary": {
            "auditId": AUDIT_ID,
            "auditReceiptFileSha256": _file_sha256(AUDIT),
            "auditReceiptManifestSha256": audit["manifestSha256"],
            "candidateCitationsAccessed": True,
            "heldOutAccessed": False,
        },
        "standard": {
            "path": os.path.relpath(STANDARD, ROOT),
            "schemaVersion": standard["schemaVersion"],
            "standardId": standard["standardId"],
            "fileSha256": _file_sha256(STANDARD),
            "manifestSha256": standard["manifestSha256"],
            "baseStandardV2FileSha256": _file_sha256(STANDARD_V2),
        },
        "qrels": {
            "scope": "host-only",
            "path": os.path.relpath(QRELS, ROOT),
            "schemaVersion": qrels["schemaVersion"],
            "fileSha256": _file_sha256(QRELS),
            "manifestSha256": qrels["manifestSha256"],
            "baseQrelsV2FileSha256": _file_sha256(QRELS_V2),
            "factCount": 9,
            "supportGroupCount": 17,
            "evidenceBindingCount": 17,
        },
        "calibrationDelta": {
            "operator": "append_equivalent_exact_candidate_cited_binding",
            "addedExactBindings": 3,
            "changedFacts": ["qst_0474/F2", "qst_0474/F3", "qst_0474/F5"],
            "unchangedFailedFacts": ["qst_0474/F1", "qst_0477/F3", "qst_0477/F4"],
        },
        "frozenCandidateRescore": {
            "sourceReportPath": os.path.relpath(SOURCE_REPORT, ROOT),
            "sourceReportFileSha256": _file_sha256(SOURCE_REPORT),
            "sourceReportSha256": _read_json(SOURCE_REPORT)["reportSha256"],
            "scorerContract": "exact-citation-token-to-document-chunk-ordinal",
            "measurementStatus": "calibrated-upper-bound",
            "coveredFactCount": 6,
            "factCount": 9,
            "citationFactCoverage": 6 / 9,
            "decision": "reject",
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
            "command": "python3 scripts/verify_enterprise_rag_answer_evidence_candidate_citation_revision.py",
            "result": "ENTERPRISE_RAG_CANDIDATE_CITATION_REVISION_R3_OK",
        },
        "claimBoundary": [
            "This receipt proves an append-only Validation qrels/Standard fixed point, not a model-quality improvement or production result.",
            "The audit accessed the frozen candidate's citations; this revision is post-Validation calibration and cannot support unbiased promotion.",
            "The three new exact bindings raise the frozen candidate's calibrated upper bound only to 6/9, so the candidate remains Reject.",
            "qst_0474/F1 and qst_0477/F3-F4 were not added; no Provider was called and Held-out remains unopened.",
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
    if _file_sha256(QRELS_V2) != EXPECTED_QRELS_V2_FILE_SHA256:
        raise AssertionError("immutable qrels-v2 file hash drifted")
    if _file_sha256(STANDARD_V2) != EXPECTED_STANDARD_V2_FILE_SHA256:
        raise AssertionError("immutable Standard v2 file hash drifted")
    if _file_sha256(SOURCE_REPORT) != EXPECTED_SOURCE_REPORT_FILE_SHA256:
        raise AssertionError("frozen candidate source report hash drifted")
    audit = _build_audit()
    _write_json(AUDIT, audit, private=True)
    standard = _build_standard(audit)
    _write_json(STANDARD, standard)
    qrels = _build_qrels(standard, audit)
    _write_json(QRELS, qrels, private=True)
    receipt = _build_receipt(audit=audit, standard=standard, qrels=qrels)
    _write_json(RECEIPT, receipt)


def _selected_cases(audit_input: Mapping[str, object], case_ids: set[str]) -> list[dict[str, object]]:
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


def _validate_with_runner(
    qrels: Mapping[str, object],
    *,
    documents: Mapping[str, str],
    prepared_artifact_sha256: str,
    prepared_source_sha256: str,
    chunking: Mapping[str, object],
    selected_cases: list[Mapping[str, object]],
) -> dict[str, int]:
    """Prove the production runner accepts the truthful candidate-aware revision."""

    _, stats = _validate_answer_evidence_qrels(
        qrels,
        selected_cases=selected_cases,
        document_text_by_id=documents,
        prepared_source_sha256=prepared_source_sha256,
        prepared_artifact_sha256=prepared_artifact_sha256,
        evaluation_split="validation",
        chunking_config=chunking,
    )
    return stats


def _verify() -> dict[str, object]:
    if _file_sha256(QRELS_V2) != EXPECTED_QRELS_V2_FILE_SHA256:
        raise AssertionError("immutable qrels-v2 file hash drifted")
    if _file_sha256(STANDARD_V2) != EXPECTED_STANDARD_V2_FILE_SHA256:
        raise AssertionError("immutable Standard v2 file hash drifted")
    if _file_sha256(SOURCE_REPORT) != EXPECTED_SOURCE_REPORT_FILE_SHA256:
        raise AssertionError("frozen candidate source report hash drifted")
    if QRELS.stat().st_mode & 0o077 or AUDIT.stat().st_mode & 0o077:
        raise AssertionError("host-private revision permissions are too broad")

    previous = _read_json(QRELS_V2)
    standard = _read_json(STANDARD)
    qrels = _read_json(QRELS)
    audit = _read_json(AUDIT)
    receipt = _read_json(RECEIPT)
    if standard.get("manifestSha256") != _self_hash(standard):
        raise AssertionError("revision Standard self-hash drifted")
    if qrels.get("manifestSha256") != _self_hash(qrels):
        raise AssertionError("revision qrels self-hash drifted")
    if audit.get("manifestSha256") != _self_hash(audit):
        raise AssertionError("candidate citation audit self-hash drifted")
    if receipt.get("receiptSha256") != _self_hash(receipt, field="receiptSha256"):
        raise AssertionError("public calibration receipt self-hash drifted")
    if standard.get("candidateBlind") is not False or audit.get("candidateCitationsAccessed") is not True:
        raise AssertionError("candidate access boundary is not truthful")
    if standard.get("unbiasedPromotionClaimAllowed") is not False or standard.get("heldOutOpened") is not False:
        raise AssertionError("revision claim boundary drifted")
    if qrels.get("answerEvidenceStandard") != standard:
        raise AssertionError("qrels does not embed the revision Standard")
    if qrels.get("candidateOf") != {
        "fileSha256": EXPECTED_QRELS_V2_FILE_SHA256,
        "manifestSha256": previous["manifestSha256"],
        "schemaVersion": previous["schemaVersion"],
    }:
        raise AssertionError("revision does not append directly to qrels-v2")
    if standard.get("calibrationSource") != {
        "auditId": AUDIT_ID,
        "auditReceiptSha256": _file_sha256(AUDIT),
        "proposalSha256": audit["proposalSha256"],
    }:
        raise AssertionError("revision Standard audit binding drifted")

    expected_changed = {(str(item["queryId"]), str(item["factId"])) for item in ADDITIONS}
    observed_changed: set[tuple[str, str]] = set()
    for query_id, fact_count in (("qst_0474", 5), ("qst_0477", 4)):
        for index in range(1, fact_count + 1):
            fact_id = f"F{index}"
            old_fact = _fact(previous, query_id, fact_id)
            new_fact = _fact(qrels, query_id, fact_id)
            if old_fact["supportGroups"] == new_fact["supportGroups"]:
                continue
            observed_changed.add((query_id, fact_id))
            if old_fact["supportGroups"] != new_fact["supportGroups"][:-1]:
                raise AssertionError("revision rewrote existing support rather than appending")
    if observed_changed != expected_changed:
        raise AssertionError(f"unexpected revised fact set: {observed_changed!r}")
    for addition in ADDITIONS:
        fact = _fact(qrels, str(addition["queryId"]), str(addition["factId"]))
        expected_group = {
            "evidence": [_binding(addition)],
            "groupId": addition["groupId"],
            "supportLabel": addition["supportLabel"],
        }
        if fact["supportGroups"][-1] != expected_group:
            raise AssertionError("candidate-cited exact binding drifted")

    prepared = _read_json(PREPARED)
    retrieval = _read_json(RETRIEVAL)
    documents = {
        str(item["documentId"]): str(item["text"])
        for item in prepared.get("documents") or []
        if isinstance(item, Mapping)
    }
    retrieval_dataset = retrieval.get("dataset")
    if not isinstance(retrieval_dataset, Mapping):
        raise AssertionError("frozen retrieval dataset is malformed")
    stats = _validate_with_runner(
        qrels,
        documents=documents,
        prepared_artifact_sha256=_file_sha256(PREPARED),
        prepared_source_sha256=str(retrieval_dataset.get("sourceSha256") or ""),
        chunking=dict(retrieval["chunking"]),
        selected_cases=_selected_cases(_read_json(AUDIT_INPUT), set(qrels["caseIds"])),
    )
    if stats != {
        "factCount": 9,
        "verifiedFactCount": 9,
        "unavailableFactCount": 0,
        "supportGroupCount": 17,
        "evidenceBindingCount": 17,
    }:
        raise AssertionError(f"revision verification counts drifted: {stats!r}")
    if receipt["frozenCandidateRescore"] != {
        **receipt["frozenCandidateRescore"],
        "coveredFactCount": 6,
        "factCount": 9,
        "citationFactCoverage": 6 / 9,
        "decision": "reject",
    }:
        raise AssertionError("calibrated frozen-candidate boundary drifted")

    return {
        "event": "ENTERPRISE_RAG_CANDIDATE_CITATION_REVISION_R3_OK",
        "runnerAcceptedCandidateAwareStandard": True,
        "providerCalls": 0,
        "heldOutOpened": False,
        "unbiasedPromotionClaimAllowed": False,
        **stats,
        "frozenCandidateCoveredFactCount": 6,
        "frozenCandidateFactCount": 9,
        "standardManifestSha256": standard["manifestSha256"],
        "qrelsManifestSha256": qrels["manifestSha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh deterministic revision artifacts")
    args = parser.parse_args()
    if args.write:
        _write_artifacts()
    print(json.dumps(_verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
