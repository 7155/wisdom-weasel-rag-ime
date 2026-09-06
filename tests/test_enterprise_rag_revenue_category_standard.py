from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.frozen_rag_replay import frozen_source_sha256, run_frozen_standard_verifier


ROOT = Path(__file__).resolve().parents[1]
STANDARD_V2 = ROOT / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.v2.json"
STANDARD_R3 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
QRELS_R3 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
STANDARD_R4 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-revenue-category-r4.json"
)
QRELS_R4 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-revenue-category-r4.json"
)
AUDIT_R4 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-revenue-category-r4-audit-20260905.v1.json"
)
RECEIPT_R4 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-revenue-category-r4-calibration-20260905.v1.json"
)

EXPECTED_STANDARD_V2_FILE_SHA256 = (
    "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7"
)
EXPECTED_STANDARD_R3_FILE_SHA256 = (
    "a8dcd8a37d2e599e07b4882d4e1df354835658a546f1c08ff71d109ebedf5e50"
)
EXPECTED_QRELS_R3_FILE_SHA256 = (
    "4a02e4948a593d87d845739e5dcb60d61c33b6216da217ed79b3b9c4dc55d46d"
)
EXPECTED_CATEGORY_BINDING = {
    "documentId": "dsid_dbd29f9393f149fbb696c9a5614dc875",
    "documentSha256": "ffe908543aab45da3d65964fa305102edff748f1338025fa7d0ec6a7885c2274",
    "chunkOrdinal": 0,
    "chunkSha256": "a293fde74c5dd33cbbf5668a76db8ad01cef24a6952a42f57bb89e77759f66b1",
    "quoteSha256": "38a228147d677434dd15d2f341475a6f7d476d85ab7468cb6bc4937caccf2363",
}


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


class EnterpriseRagRevenueCategoryStandardTests(unittest.TestCase):
    @unittest.skipUnless(all(path.is_file() for path in (QRELS_R3, QRELS_R4, AUDIT_R4)), "Private RAG corpus is not bundled in public source")
    def test_r4_is_a_direct_append_only_r3_successor_changing_only_f4(self) -> None:
        self.assertEqual(EXPECTED_STANDARD_V2_FILE_SHA256, _sha256(STANDARD_V2))
        self.assertEqual(EXPECTED_STANDARD_R3_FILE_SHA256, _sha256(STANDARD_R3))
        self.assertEqual(EXPECTED_QRELS_R3_FILE_SHA256, _sha256(QRELS_R3))

        prior_standard = _read(STANDARD_R3)
        prior_qrels = _read(QRELS_R3)
        standard = _read(STANDARD_R4)
        qrels = _read(QRELS_R4)

        self.assertEqual("post-validation-calibrated", standard["calibrationLabel"])
        self.assertFalse(standard["candidateBlind"])
        self.assertFalse(standard["heldOutOpened"])
        self.assertFalse(standard["unbiasedPromotionClaimAllowed"])
        self.assertIn("revenue-category", standard["calibrationSource"]["auditId"])
        self.assertEqual(standard, qrels["answerEvidenceStandard"])
        self.assertEqual(standard["manifestSha256"], qrels["standardManifestSha256"])
        self.assertEqual(
            {
                "fileSha256": EXPECTED_QRELS_R3_FILE_SHA256,
                "manifestSha256": prior_qrels["manifestSha256"],
                "schemaVersion": prior_qrels["schemaVersion"],
            },
            qrels["candidateOf"],
        )

        changed: set[tuple[str, str]] = set()
        for query_id, fact_count in (("qst_0474", 5), ("qst_0477", 4)):
            for index in range(1, fact_count + 1):
                fact_id = f"F{index}"
                before = _fact(prior_qrels, query_id, fact_id)
                after = _fact(qrels, query_id, fact_id)
                if before != after:
                    changed.add((query_id, fact_id))
                if (query_id, fact_id) != ("qst_0477", "F4"):
                    self.assertEqual(before, after)

        self.assertEqual({("qst_0477", "F4")}, changed)
        before_f4 = _fact(prior_qrels, "qst_0477", "F4")
        after_f4 = _fact(qrels, "qst_0477", "F4")
        self.assertEqual("all", before_f4["supportGroupMode"])
        self.assertEqual("any", after_f4["supportGroupMode"])
        self.assertEqual(before_f4["supportGroups"], after_f4["supportGroups"][:-1])
        self.assertEqual("paid_add_ons_category", after_f4["supportGroups"][-1]["supportLabel"])
        self.assertEqual(1, len(after_f4["supportGroups"][-1]["evidence"]))
        binding = after_f4["supportGroups"][-1]["evidence"][0]
        for key, value in EXPECTED_CATEGORY_BINDING.items():
            self.assertEqual(value, binding[key])
        self.assertEqual(18, qrels["counts"]["supportGroupCount"])
        self.assertEqual(18, qrels["counts"]["evidenceBindingCount"])
        self.assertNotEqual(prior_standard["manifestSha256"], standard["manifestSha256"])

    def test_public_receipt_is_body_free_and_preserves_post_validation_claims(self) -> None:
        standard = _read(STANDARD_R4)
        receipt = _read(RECEIPT_R4)

        self.assertEqual(0, receipt["providerCalls"])
        self.assertEqual(0, receipt["judgeCalls"])
        self.assertEqual(0, receipt["candidateRuns"])
        self.assertFalse(receipt["candidateBlind"])
        self.assertTrue(receipt["candidateAware"])
        self.assertTrue(receipt["auditAware"])
        self.assertFalse(receipt["heldOutOpened"])
        self.assertFalse(receipt["formalAcceptanceEligible"])
        self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
        self.assertTrue(receipt["auditBoundary"]["candidateCitationsAccessed"])
        self.assertEqual(["qst_0477/F4"], receipt["calibrationDelta"]["changedFacts"])
        self.assertEqual(0, receipt["calibrationDelta"]["otherFactBindingsAdded"])
        self.assertEqual(7, receipt["frozenCandidateRescore"]["coveredFactCount"])
        self.assertEqual(9, receipt["frozenCandidateRescore"]["factCount"])
        self.assertEqual("reject", receipt["frozenCandidateRescore"]["decision"])
        self.assertEqual(
            "exact-citation-token-to-document-chunk-ordinal",
            receipt["frozenCandidateRescore"]["scorerContract"],
        )
        self.assertEqual(
            frozen_source_sha256("scripts/run_rag_agent_ablation.py"),
            receipt["frozenCandidateRescore"]["runnerFileSha256"],
        )
        self.assertEqual(
            _sha256(ROOT / "scripts/verify_enterprise_rag_revenue_category_standard.py"),
            receipt["frozenCandidateRescore"]["verifierFileSha256"],
        )
        for key, value in receipt["publicSafety"].items():
            if key.startswith("contains"):
                self.assertFalse(value, key)
        self.assertEqual(
            _read(STANDARD_R4)["calibrationSource"]["auditReceiptSha256"],
            receipt["auditBoundary"]["auditReceiptFileSha256"],
        )
        if not AUDIT_R4.is_file():
            return  # Private-body comparison requires the local corpus.
        self.assertEqual(_sha256(AUDIT_R4), receipt["auditBoundary"]["auditReceiptFileSha256"])
        audit = _read(AUDIT_R4)
        self.assertTrue(audit["candidateAware"])

        serialized = json.dumps(receipt, ensure_ascii=False)
        serialized_standard = json.dumps(standard, ensure_ascii=False)
        self.assertNotIn(audit["frozenSemanticUnit"]["question"], serialized)
        self.assertNotIn(audit["frozenSemanticUnit"]["question"], serialized_standard)
        self.assertNotIn(audit["frozenSemanticUnit"]["referenceAnswer"], serialized)
        self.assertNotIn(audit["frozenSemanticUnit"]["referenceAnswer"], serialized_standard)
        self.assertNotIn(audit["frozenSemanticUnit"]["fact"], serialized)
        self.assertNotIn(audit["frozenSemanticUnit"]["fact"], serialized_standard)
        self.assertNotIn(audit["acceptedCategoryBinding"]["quote"], serialized)
        self.assertNotIn(audit["acceptedCategoryBinding"]["quote"], serialized_standard)

    def test_dedicated_verifier_recomputes_the_frozen_candidate_offline(self) -> None:
        completed = run_frozen_standard_verifier("verify_enterprise_rag_revenue_category_standard.py")
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ENTERPRISE_RAG_REVENUE_CATEGORY_STANDARD_R4_OK", payload["event"])
        self.assertEqual(0, payload["providerCalls"])
        self.assertEqual(7, payload["frozenCandidateCoveredFactCount"])
        self.assertEqual(9, payload["frozenCandidateFactCount"])
        self.assertEqual("reject", payload["frozenCandidateDecision"])


if __name__ == "__main__":
    unittest.main()
