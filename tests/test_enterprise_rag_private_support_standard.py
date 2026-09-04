from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD_V2 = ROOT / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.v2.json"
STANDARD_R3 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
STANDARD_R4 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-revenue-category-r4.json"
)
QRELS_R3 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
QRELS_R4 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-revenue-category-r4.json"
)
STANDARD_R5 = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-aware-private-support-r5.json"
)
QRELS_R5 = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-private-support-r5.json"
)
AUDIT_R5 = (
    ROOT
    / ".rag-ime-data/eval/host/enterprise-rag-answer-evidence-candidate-aware-private-support-r5-audit-20260905.v1.json"
)
RECEIPT_R5 = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-standard-candidate-aware-private-support-r5-calibration-20260905.v1.json"
)

EXPECTED_IMMUTABLE_HASHES = {
    STANDARD_V2: "ba8c135e3d1ef845f3a333a2259003703769adeca6fa517cb7decc9098d417f7",
    STANDARD_R3: "a8dcd8a37d2e599e07b4882d4e1df354835658a546f1c08ff71d109ebedf5e50",
    QRELS_R3: "4a02e4948a593d87d845739e5dcb60d61c33b6216da217ed79b3b9c4dc55d46d",
    STANDARD_R4: "0d6155f9055c6a47b7b311d57c0f05ba4436c4769b2f336ee3e8cba06ad35dc9",
    QRELS_R4: "6e29c0ab058f2293b5e9e5e7b9b4f4309c3b58c47199f9d30afa97ec96752719",
}
EXPECTED_PRIVATE_SUPPORT_BINDING = {
    "documentId": "dsid_dbd29f9393f149fbb696c9a5614dc875",
    "documentSha256": "ffe908543aab45da3d65964fa305102edff748f1338025fa7d0ec6a7885c2274",
    "chunkOrdinal": 0,
    "chunkSha256": "a293fde74c5dd33cbbf5668a76db8ad01cef24a6952a42f57bb89e77759f66b1",
    "quoteSha256": "8a44532317f92eeffa273876749c1897f4a4457f8112909f73d934fee675f880",
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


class EnterpriseRagPrivateSupportStandardTests(unittest.TestCase):
    def test_r5_is_a_direct_r4_successor_appending_only_f3_support(self) -> None:
        for path, expected in EXPECTED_IMMUTABLE_HASHES.items():
            self.assertEqual(expected, _sha256(path), path)

        prior_standard = _read(STANDARD_R4)
        prior_qrels = _read(QRELS_R4)
        standard = _read(STANDARD_R5)
        qrels = _read(QRELS_R5)

        self.assertEqual("post-validation-calibrated", standard["calibrationLabel"])
        self.assertFalse(standard["candidateBlind"])
        self.assertFalse(standard["heldOutOpened"])
        self.assertFalse(standard["unbiasedPromotionClaimAllowed"])
        self.assertIn("private-support", standard["calibrationSource"]["auditId"])
        self.assertEqual(standard, qrels["answerEvidenceStandard"])
        self.assertEqual(standard["manifestSha256"], qrels["standardManifestSha256"])
        self.assertEqual(
            {
                "fileSha256": EXPECTED_IMMUTABLE_HASHES[QRELS_R4],
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
                if (query_id, fact_id) != ("qst_0477", "F3"):
                    self.assertEqual(before, after)

        self.assertEqual({("qst_0477", "F3")}, changed)
        before_f3 = _fact(prior_qrels, "qst_0477", "F3")
        after_f3 = _fact(qrels, "qst_0477", "F3")
        self.assertEqual("any", before_f3["supportGroupMode"])
        self.assertEqual("any", after_f3["supportGroupMode"])
        self.assertEqual(before_f3["supportGroups"], after_f3["supportGroups"][:-1])
        appended = after_f3["supportGroups"][-1]
        self.assertEqual(
            "private_platform_support_candidate_equivalent",
            appended["supportLabel"],
        )
        self.assertEqual(1, len(appended["evidence"]))
        for key, value in EXPECTED_PRIVATE_SUPPORT_BINDING.items():
            self.assertEqual(value, appended["evidence"][0][key])
        self.assertEqual(19, qrels["counts"]["supportGroupCount"])
        self.assertEqual(19, qrels["counts"]["evidenceBindingCount"])
        self.assertNotEqual(prior_standard["manifestSha256"], standard["manifestSha256"])

    def test_public_receipt_is_safe_and_preserves_candidate_aware_boundary(self) -> None:
        audit = _read(AUDIT_R5)
        standard = _read(STANDARD_R5)
        receipt = _read(RECEIPT_R5)

        self.assertFalse(receipt["candidateBlind"])
        self.assertTrue(receipt["candidateAware"])
        self.assertTrue(receipt["auditAware"])
        self.assertTrue(audit["candidateAware"])
        self.assertEqual(0, receipt["providerCalls"])
        self.assertEqual(0, receipt["judgeCalls"])
        self.assertEqual(0, receipt["candidateRuns"])
        self.assertFalse(receipt["heldOutOpened"])
        self.assertFalse(receipt["formalAcceptanceEligible"])
        self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
        self.assertEqual("openai-codex/gpt-5.6-sol", receipt["sourceCandidate"]["model"])
        self.assertEqual(["qst_0477/F3"], receipt["calibrationDelta"]["changedFacts"])
        self.assertEqual(0, receipt["calibrationDelta"]["otherFactBindingsAdded"])
        self.assertEqual(6, receipt["frozenSolCandidateRescore"]["beforeCoveredFactCount"])
        self.assertEqual(7, receipt["frozenSolCandidateRescore"]["coveredFactCount"])
        self.assertEqual(9, receipt["frozenSolCandidateRescore"]["factCount"])
        self.assertEqual("reject", receipt["frozenSolCandidateRescore"]["decision"])
        self.assertEqual(
            "exact-citation-token-to-document-chunk-ordinal",
            receipt["frozenSolCandidateRescore"]["scorerContract"],
        )
        for key, value in receipt["publicSafety"].items():
            if key.startswith("contains"):
                self.assertFalse(value, key)

        serialized_public = json.dumps([standard, receipt], ensure_ascii=False)
        for body in (
            audit["frozenSemanticUnit"]["question"],
            audit["frozenSemanticUnit"]["referenceAnswer"],
            audit["frozenSemanticUnit"]["fact"],
            audit["frozenSemanticUnit"]["judgeRubricFact"],
            audit["acceptedEquivalentBinding"]["quote"],
            audit["sourceCandidate"]["answer"],
        ):
            self.assertNotIn(body, serialized_public)

    def test_dedicated_verifier_recomputes_frozen_sol_offline(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/verify_enterprise_rag_private_support_standard.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("ENTERPRISE_RAG_PRIVATE_SUPPORT_STANDARD_R5_OK", payload["event"])
        self.assertEqual(0, payload["providerCalls"])
        self.assertEqual(7, payload["frozenSolCoveredFactCount"])
        self.assertEqual(9, payload["frozenSolFactCount"])
        self.assertEqual("reject", payload["frozenSolDecision"])
        self.assertEqual(["qst_0477/F3"], payload["newlyCoveredFacts"])


if __name__ == "__main__":
    unittest.main()
