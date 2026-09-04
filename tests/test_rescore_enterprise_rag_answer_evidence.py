from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.rescore_enterprise_rag_answer_evidence import (
    DEFAULT_OUTPUT,
    OBSOLETE_RECEIPT,
    _build_receipt,
    _rescore_lanes,
)


ROOT = Path(__file__).resolve().parents[1]
QRELS = (
    ROOT
    / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-citation-revision-r3.json"
)
STANDARD = (
    ROOT
    / "eval/interview-metrics/enterprise-rag-answer-evidence-standard.validation-candidate-citation-revision-r3.json"
)
REPORTS = {
    "sol": ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-sol-max-frozen-v19-r4-20260904.json",
    "luna_model_only": ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-model-only-v19-r4-20260904.json",
    "luna_prompt_v4": ROOT
    / ".rag-ime-data/eval/results/validation-answer-evidence-luna-max-coverage-balanced-v4-r4-20260904.json",
}
EXPECTED_AGENTIC_CITATION_FACTS = {
    "sol": 5,
    "luna_model_only": 6,
    "luna_prompt_v4": 6,
}
RECEIPTS = {
    "sol": ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-sol-max-frozen-v19-r4-candidate-citation-r3-exact-offline-rescore-20260905.v1.json",
    "luna_model_only": ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-model-only-v19-r4-candidate-citation-r3-exact-offline-rescore-20260905.v1.json",
    "luna_prompt_v4": ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-coverage-balanced-v4-r4-candidate-citation-r3-exact-offline-rescore-20260905.v1.json",
}


def _source_report(*, cited_ordinal: int = 3) -> dict[str, object]:
    judgments = []
    lanes = []
    for lane in ("baseline", "skill", "tuned", "agentic"):
        judgments.append(
            {
                "lane": lane,
                "evaluationCaseId": "case-01",
                "correct": True,
                "reasonCode": "correct",
                "coveredFactIds": ["F1"],
                "hasUnsupportedMaterial": False,
            }
        )
        lanes.append(
            {
                "lane": lane,
                "hardGates": {"citationResolution": False},
                "costs": {"latencyMs": 1.0, "tokens": 2.0, "toolCalls": 1.0},
                "gatewayLedger": {
                    "items": [
                        {
                            "operation": "search",
                            "ok": True,
                            "args": {"evaluationCaseId": "case-01"},
                            "resultSummary": {
                                "hits": [
                                    {
                                        "citationRef": "K1",
                                        "externalDocumentId": "doc-new",
                                        "ordinal": cited_ordinal,
                                    }
                                ]
                            },
                        }
                    ]
                },
                "score": {
                    "agentMetrics": {
                        "highLevelFactCoverage": 1.0,
                        "citationFactCoverage": 0.0,
                        "answerableCitationSupportRate": 0.0,
                        "highLevelAnswerCorrectnessRate": 1.0,
                        "infoNotFoundAbstentionRecall": 1.0,
                        "answerJudgeCorrectnessRate": 1.0,
                        "answerSuccessRate": 1.0,
                        "citationSuccessRate": 0.0,
                        "agentSuccessRate": 0.5,
                    },
                    "metricDenominators": {
                        "answerableCitationCases": 1,
                        "highLevelCases": 1,
                        "infoNotFoundCases": 1,
                        "protocolCases": 2,
                    },
                    "hardEvidence": {
                        "citationResolution": True,
                        "factCitationCoverage": False,
                    },
                    "answerCases": [
                        {
                            "queryId": "q-answer",
                            "evaluationCaseId": "case-01",
                            "abstentionExpected": False,
                            "abstained": False,
                            "abstentionCorrect": True,
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citationTokens": ["K1"],
                            "citations": ["doc-new"],
                        },
                        {
                            "queryId": "q-none",
                            "evaluationCaseId": "case-02",
                            "abstentionExpected": True,
                            "abstained": True,
                            "abstentionCorrect": True,
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citationTokens": [],
                            "citations": [],
                        },
                    ],
                },
            }
        )
    return {
        "answerJudge": {
            "judgments": judgments,
            "caseRubrics": [
                {
                    "caseId": "case-01",
                    "requiredFacts": [{"factId": "F1", "description": "one fact"}],
                }
            ],
        },
        "lanes": lanes,
    }


def _cases() -> list[dict[str, object]]:
    return [
        {
            "queryId": "q-answer",
            "evaluationCaseId": "case-01",
            "abstentionExpected": False,
        },
        {
            "queryId": "q-none",
            "evaluationCaseId": "case-02",
            "abstentionExpected": True,
        },
    ]


class RescoreEnterpriseRagAnswerEvidenceTests(unittest.TestCase):
    def test_exact_scorer_requires_the_cited_chunk_not_document_membership(self) -> None:
        source = _source_report(cited_ordinal=3)
        original = copy.deepcopy(source)
        exact_qrels = {
            "q-answer": {
                "facts": [
                    {
                        "factId": "F1",
                        "supportGroupMode": "any",
                        "supportGroups": [
                            {
                                "groupId": "G1",
                                "documentIds": ["doc-new"],
                                "evidence": [
                                    {"documentId": "doc-new", "chunkOrdinal": 4}
                                ],
                            }
                        ],
                    }
                ]
            }
        }

        wrong_chunk = _rescore_lanes(
            source_report=source,
            cases=_cases(),
            private_qrels=exact_qrels,
        )
        self.assertEqual(original, source)
        for lane in wrong_chunk:
            self.assertEqual(
                0.0, lane["score"]["agentMetrics"]["citationFactCoverage"]
            )
            self.assertFalse(lane["score"]["hardEvidence"]["factCitationCoverage"])

        exact_qrels["q-answer"]["facts"][0]["supportGroups"][0]["evidence"][
            0
        ]["chunkOrdinal"] = 3
        matching_chunk = _rescore_lanes(
            source_report=source,
            cases=_cases(),
            private_qrels=exact_qrels,
        )
        for lane in matching_chunk:
            self.assertEqual(
                1.0, lane["score"]["agentMetrics"]["citationFactCoverage"]
            )
            self.assertTrue(lane["score"]["hardEvidence"]["factCitationCoverage"])

    def test_legacy_v1_document_id_fixture_remains_compatible(self) -> None:
        legacy_qrels = {
            "q-answer": {
                "facts": [
                    {
                        "factId": "F1",
                        "supportGroupMode": "any",
                        "supportGroups": [
                            {"groupId": "G1", "documentIds": ["doc-new"]}
                        ],
                    }
                ]
            }
        }

        rescored = _rescore_lanes(
            source_report=_source_report(),
            cases=_cases(),
            private_qrels=legacy_qrels,
        )

        for lane in rescored:
            self.assertEqual(
                1.0, lane["score"]["agentMetrics"]["citationFactCoverage"]
            )
            self.assertEqual(
                {"latencyMs": 1.0, "tokens": 2.0, "toolCalls": 1.0},
                lane["costs"],
            )

    def test_three_frozen_r4_reports_rescore_with_exact_runner_contract(self) -> None:
        for label, report in REPORTS.items():
            with self.subTest(label=label):
                receipt = _build_receipt(
                    run_id=f"test-{label}",
                    source_report_path=report,
                    qrels_path=QRELS,
                    standard_path=STANDARD,
                )

                self.assertEqual(
                    "paw.enterprise-rag-answer-evidence-exact-offline-rescore.v2",
                    receipt["schemaVersion"],
                )
                self.assertEqual(0, receipt["providerCalls"])
                self.assertEqual(0, receipt["judgeCalls"])
                self.assertFalse(receipt["heldOutOpened"])
                self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
                self.assertEqual(
                    hashlib.sha256(report.read_bytes()).hexdigest(),
                    receipt["sourceEvidence"]["frozenCandidateReport"][
                        "fileSha256"
                    ],
                )
                self.assertEqual(
                    hashlib.sha256(QRELS.read_bytes()).hexdigest(),
                    receipt["qrels"]["fileSha256"],
                )
                self.assertEqual(
                    hashlib.sha256(STANDARD.read_bytes()).hexdigest(),
                    receipt["standard"]["fileSha256"],
                )
                self.assertEqual(
                    "exact-citation-token-to-document-id-and-chunk-ordinal",
                    receipt["scorerContract"]["candidateSupportMatchGranularity"],
                )
                self.assertTrue(
                    receipt["scorerContract"]["candidateChunkOrdinalRequired"]
                )
                self.assertEqual(
                    EXPECTED_AGENTIC_CITATION_FACTS[label],
                    receipt["agenticResult"]["exactCitationFactsCovered"],
                )
                self.assertEqual(9, receipt["agenticResult"]["citationFactCount"])
                self.assertEqual("reject", receipt["agenticResult"]["decision"])
                self.assertTrue(
                    receipt["agenticResult"]["costSourceReference"][
                        "sourceUsageRef"
                    ].startswith("runtime-cost:")
                )
                self.assertTrue(
                    receipt["historicalScorerCorrection"][
                        "documentIdMembershipScorerObsolete"
                    ]
                )
                self.assertEqual(
                    str(OBSOLETE_RECEIPT.relative_to(ROOT)),
                    receipt["historicalScorerCorrection"]["obsoleteReceipt"][
                        "path"
                    ],
                )

    def test_checked_in_receipts_are_self_hashed_and_public_safe(self) -> None:
        forbidden_keys = {
            "answer",
            "cases",
            "citationTokens",
            "citations",
            "documentId",
            "evidence",
            "judgments",
            "quote",
        }

        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value).union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value))
            return set()

        for label, path in RECEIPTS.items():
            with self.subTest(label=label):
                receipt = json.loads(path.read_text(encoding="utf-8"))
                claimed = receipt.pop("receiptSha256")
                actual = hashlib.sha256(
                    json.dumps(
                        receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
                self.assertEqual(actual, claimed)
                self.assertFalse(forbidden_keys.intersection(keys(receipt)))
                self.assertEqual(
                    EXPECTED_AGENTIC_CITATION_FACTS[label],
                    receipt["agenticResult"]["exactCitationFactsCovered"],
                )
                self.assertEqual("post-validation-calibrated", receipt["calibrationLabel"])
                self.assertEqual(0, receipt["providerCalls"])
                self.assertEqual(0, receipt["judgeCalls"])
                self.assertFalse(receipt["heldOutOpened"])
                self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])

    def test_cli_accepts_only_explicit_current_inputs_and_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            command = [
                sys.executable,
                "scripts/rescore_enterprise_rag_answer_evidence.py",
                "--source-report",
                str(REPORTS["luna_prompt_v4"]),
                "--answer-evidence-qrels",
                str(QRELS),
                "--standard",
                str(STANDARD),
                "--output",
                str(output),
                "--run-id",
                "test-explicit-current-inputs",
            ]
            first = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, check=False
            )
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("written", json.loads(first.stdout)["action"])
            second = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, check=False
            )
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual("verified", json.loads(second.stdout)["action"])
            self.assertNotEqual(OBSOLETE_RECEIPT, DEFAULT_OUTPUT)
            self.assertNotEqual(OBSOLETE_RECEIPT.resolve(), DEFAULT_OUTPUT.resolve())


if __name__ == "__main__":
    unittest.main()
