#!/usr/bin/env python3
"""Verify the host-private Enterprise RAG qrels-v2 fixed point without Provider calls."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_rag_agent_ablation import (  # noqa: E402
    _sha256_json,
    _validate_answer_evidence_qrels,
)


RESEARCH = ROOT.parent / "paw-vertical-research" / "enterprise-rag-eval-lab"
PREPARED = RESEARCH / "artifacts" / "smoke-v1" / "host" / "prepared.json"
RETRIEVAL = RESEARCH / "results" / "validation-bge-qwen3-rerank-v1.json"
AUDIT_INPUT = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-qrels-independent-v2-candidate-blind-input-20260904.v1.json"
)
QRELS_V1 = ROOT / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-v1.json"
QRELS_V2 = ROOT / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-v2.json"
STANDARD_V2 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.v2.json"
)

EXPECTED_QRELS_V1_FILE_SHA256 = (
    "95ca80c5cf33eb30f905825d0c65e33ae164322bc6bec0f245663159641ac8d1"
)
EXPECTED_QRELS_V2_FILE_SHA256 = (
    "b0b081c4a0ecbced1c589b69126de555a0f1b8815c508e1f4eb269adce608428"
)
EXPECTED_STANDARD_V2_FILE_SHA256 = (
    "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if QRELS_V2.stat().st_mode & 0o077:
        raise AssertionError("host-private qrels-v2 permissions are too broad")
    if _file_sha256(QRELS_V1) != EXPECTED_QRELS_V1_FILE_SHA256:
        raise AssertionError("immutable qrels-v1 file hash drifted")
    if _file_sha256(QRELS_V2) != EXPECTED_QRELS_V2_FILE_SHA256:
        raise AssertionError("qrels-v2 file hash drifted")
    if _file_sha256(STANDARD_V2) != EXPECTED_STANDARD_V2_FILE_SHA256:
        raise AssertionError("answer-evidence Standard v2 file hash drifted")

    prepared = _read_json(PREPARED)
    retrieval = _read_json(RETRIEVAL)
    audit_input = _read_json(AUDIT_INPUT)
    qrels = _read_json(QRELS_V2)
    standard = _read_json(STANDARD_V2)

    if qrels.get("answerEvidenceStandard") != standard:
        raise AssertionError("qrels-v2 does not embed the published Standard v2")
    unsigned_standard = {
        key: value for key, value in standard.items() if key != "manifestSha256"
    }
    if standard.get("manifestSha256") != _sha256_json(unsigned_standard):
        raise AssertionError("answer-evidence Standard v2 manifest hash drifted")

    raw_documents = prepared.get("documents")
    raw_questions = audit_input.get("questions")
    if not isinstance(raw_documents, list) or not isinstance(raw_questions, list):
        raise AssertionError("frozen evaluation inputs are malformed")
    documents = {
        str(item["documentId"]): str(item["text"])
        for item in raw_documents
        if isinstance(item, dict)
    }
    retrieval_dataset = retrieval.get("dataset")
    if not isinstance(retrieval_dataset, dict):
        raise AssertionError("frozen retrieval dataset identity is malformed")
    prepared_artifact_sha256 = _file_sha256(PREPARED)
    if retrieval.get("sourcePreparedSha256") != prepared_artifact_sha256:
        raise AssertionError("frozen prepared artifact hash drifted")
    case_ids = set(qrels.get("caseIds") or [])
    selected_cases = []
    for question in raw_questions:
        if not isinstance(question, dict) or question.get("queryId") not in case_ids:
            continue
        facts = question.get("requiredFacts")
        if not isinstance(facts, list):
            raise AssertionError("candidate-blind required facts are malformed")
        selected_cases.append(
            {
                "queryId": question["queryId"],
                "answerFacts": [
                    fact["description"]
                    for fact in facts
                    if isinstance(fact, dict)
                ],
            }
        )
    private_qrels, stats = _validate_answer_evidence_qrels(
        qrels,
        selected_cases=selected_cases,
        document_text_by_id=documents,
        prepared_source_sha256=str(retrieval_dataset.get("sourceSha256") or ""),
        prepared_artifact_sha256=prepared_artifact_sha256,
        evaluation_split="validation",
        chunking_config=dict(retrieval["chunking"]),
    )
    expected_stats = {
        "factCount": 9,
        "verifiedFactCount": 9,
        "unavailableFactCount": 0,
        "supportGroupCount": 14,
        "evidenceBindingCount": 14,
    }
    if stats != expected_stats:
        raise AssertionError(
            f"qrels-v2 verification counts drifted: {stats!r}"
        )
    if set(private_qrels) != case_ids:
        raise AssertionError("qrels-v2 verified case set drifted")
    if standard.get("unbiasedPromotionClaimAllowed") is not False:
        raise AssertionError("unbiased promotion claim must remain forbidden")
    if standard.get("heldOutOpened") is not False:
        raise AssertionError("Held-out must remain unopened")

    print(
        json.dumps(
            {
                "event": "ENTERPRISE_RAG_ANSWER_EVIDENCE_STANDARD_V2_OK",
                "providerCalls": 0,
                "heldOutOpened": False,
                "unbiasedPromotionClaimAllowed": False,
                **expected_stats,
                "chunkCount": standard["chunkManifest"]["chunkCount"],
                "chunkManifestSha256": standard["chunkManifest"][
                    "manifestSha256"
                ],
                "standardManifestSha256": standard["manifestSha256"],
                "qrelsManifestSha256": qrels["manifestSha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
