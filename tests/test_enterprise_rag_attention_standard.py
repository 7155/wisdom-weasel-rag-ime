from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD_R5 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-private-support-r5.json"
)
QRELS_R5 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-private-support-r5.json"
)
STANDARD_R6 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-attention-r6.json"
)
QRELS_R6 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-attention-r6.json"
)
AUDIT_R6 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-attention-r6-audit-20260905.v1.json"
)
RECEIPT_R6 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-attention-r6-calibration-20260905.v1.json"
)


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fact(qrels: dict[str, object], query_id: str, fact_id: str) -> dict[str, object]:
    for case in qrels.get("cases") or []:
        if not isinstance(case, dict) or case.get("queryId") != query_id:
            continue
        for fact in case.get("facts") or []:
            if isinstance(fact, dict) and fact.get("factId") == fact_id:
                return fact
    raise AssertionError(f"missing fact: {query_id}/{fact_id}")


class EnterpriseRagAttentionStandardTests(unittest.TestCase):
    def test_r6_is_one_append_only_exact_attention_binding(self) -> None:
        before = _read(QRELS_R5)
        after = _read(QRELS_R6)
        standard = _read(STANDARD_R6)

        self.assertEqual("post-validation-calibrated", standard["calibrationLabel"])
        self.assertFalse(standard["candidateBlind"])
        self.assertFalse(standard["heldOutOpened"])
        self.assertFalse(standard["unbiasedPromotionClaimAllowed"])
        self.assertEqual(standard, after["answerEvidenceStandard"])
        self.assertEqual(standard["manifestSha256"], after["standardManifestSha256"])
        self.assertEqual(
            {
                "fileSha256": _sha256(QRELS_R5),
                "manifestSha256": before["manifestSha256"],
                "schemaVersion": before["schemaVersion"],
            },
            after["candidateOf"],
        )

        changed: set[tuple[str, str]] = set()
        for query_id, count in (("qst_0474", 5), ("qst_0477", 4)):
            for index in range(1, count + 1):
                fact_id = f"F{index}"
                prior = _fact(before, query_id, fact_id)
                revised = _fact(after, query_id, fact_id)
                if prior != revised:
                    changed.add((query_id, fact_id))
                if (query_id, fact_id) != ("qst_0474", "F1"):
                    self.assertEqual(prior, revised)
        self.assertEqual({("qst_0474", "F1")}, changed)

        prior_f1 = _fact(before, "qst_0474", "F1")
        revised_f1 = _fact(after, "qst_0474", "F1")
        self.assertEqual("any", prior_f1["supportGroupMode"])
        self.assertEqual("any", revised_f1["supportGroupMode"])
        self.assertEqual(prior_f1["supportGroups"], revised_f1["supportGroups"][:-1])
        appended = revised_f1["supportGroups"][-1]
        self.assertEqual("runtime_fused_attention_candidate_equivalent", appended["supportLabel"])
        self.assertEqual(1, len(appended["evidence"]))
        evidence = appended["evidence"][0]
        self.assertEqual("dsid_84502e86ba9c43eebb344017fa1d07dc", evidence["documentId"])
        self.assertEqual(3, evidence["chunkOrdinal"])
        self.assertEqual(
            "53384cced10bc0ce04b74df22f99296e80278091b6f6916a6a5fde6266a61261",
            evidence["chunkSha256"],
        )
        self.assertEqual(20, after["counts"]["supportGroupCount"])
        self.assertEqual(20, after["counts"]["evidenceBindingCount"])

    def test_receipt_keeps_candidate_aware_boundary_and_exact_comparison(self) -> None:
        audit = _read(AUDIT_R6)
        receipt = _read(RECEIPT_R6)

        self.assertFalse(receipt["candidateBlind"])
        self.assertTrue(receipt["candidateAware"])
        self.assertTrue(receipt["auditAware"])
        self.assertEqual(0, receipt["providerCalls"])
        self.assertEqual(0, receipt["judgeCalls"])
        self.assertEqual(0, receipt["candidateRuns"])
        self.assertFalse(receipt["heldOutOpened"])
        self.assertFalse(receipt["formalAcceptanceEligible"])
        self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
        self.assertEqual(["qst_0474/F1"], receipt["calibrationDelta"]["changedFacts"])
        self.assertEqual(0, receipt["calibrationDelta"]["otherFactBindingsAdded"])
        self.assertEqual(8, receipt["lunaPromptV4Rescore"]["beforeCoveredFactCount"])
        self.assertEqual(9, receipt["lunaPromptV4Rescore"]["coveredFactCount"])
        self.assertEqual("keep", receipt["lunaPromptV4Rescore"]["decision"])
        self.assertEqual(8, receipt["lunaModelOnlyControl"]["coveredFactCount"])
        self.assertEqual("reject", receipt["lunaModelOnlyControl"]["decision"])
        self.assertEqual(7, receipt["solControl"]["coveredFactCount"])
        self.assertEqual("reject", receipt["solControl"]["decision"])
        for key, value in receipt["publicSafety"].items():
            if key.startswith("contains"):
                self.assertFalse(value, key)

        serialized_public = json.dumps([_read(STANDARD_R6), receipt], ensure_ascii=False)
        for body in (
            audit["frozenSemanticUnit"]["question"],
            audit["frozenSemanticUnit"]["referenceAnswer"],
            audit["frozenSemanticUnit"]["fact"],
            audit["frozenSemanticUnit"]["judgeRubricFact"],
            audit["acceptedEquivalentBinding"]["quote"],
            audit["sourceCandidate"]["answer"],
        ):
            self.assertNotIn(body, serialized_public)

    def test_dedicated_verifier_recomputes_all_three_controls(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/verify_enterprise_rag_attention_standard.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ENTERPRISE_RAG_ATTENTION_STANDARD_R6_OK", payload["event"])
        self.assertEqual(0, payload["providerCalls"])
        self.assertEqual(9, payload["lunaPromptV4CoveredFactCount"])
        self.assertEqual("keep", payload["lunaPromptV4Decision"])
        self.assertEqual(8, payload["lunaModelOnlyCoveredFactCount"])
        self.assertEqual(7, payload["solCoveredFactCount"])
        self.assertEqual(["qst_0474/F1"], payload["newlyCoveredFacts"])


if __name__ == "__main__":
    unittest.main()
