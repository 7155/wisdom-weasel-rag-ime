from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.promote_rag_agent_validation import (
    REQUIRED_HARD_GATES,
    produce_authority,
    sha256_json,
)


ROOT = Path(__file__).resolve().parents[1]


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class PromoteRagAgentValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.retrieval_path = self.root / "retrieval.json"
        self.validation_path = self.root / "validation.json"
        self.retrieval = self._retrieval_report()
        self._write_signed(self.retrieval_path, self.retrieval)
        self.validation = self._validation_report(
            retrieval_file_sha256=self._file_sha256(self.retrieval_path)
        )
        self._write_signed(self.validation_path, self.validation)

    def test_keep_signs_promotion_and_matching_unlocked_one_shot_gate(self) -> None:
        promotion, gate = produce_authority(
            self.validation_path,
            self.retrieval_path,
            decision="keep",
        )

        self.assertEqual("keep", promotion["decision"])
        self.assertEqual("promoted", promotion["state"])
        self.assertFalse(promotion["heldOutObserved"])
        self.assertEqual(
            sha256_json(
                {
                    key: value
                    for key, value in promotion.items()
                    if key != "promotionReceiptSha256"
                }
            ),
            promotion["promotionReceiptSha256"],
        )
        self.assertEqual(
            self._file_sha256(self.validation_path),
            promotion["validationAgentReport"]["fileSha256"],
        )
        self.assertEqual(
            self.validation["reportSha256"],
            promotion["validationAgentReport"]["reportSha256"],
        )
        self.assertEqual(
            self._file_sha256(self.retrieval_path),
            promotion["retrievalReport"]["fileSha256"],
        )
        self.assertEqual(
            self.retrieval["reportSha256"],
            promotion["winner"]["reportSha256"],
        )
        self.assertEqual(
            self.retrieval["validationSelection"]["winner"]["config"],
            promotion["winner"]["retrievalConfig"],
        )

        self.assertIsNotNone(gate)
        assert gate is not None
        self.assertEqual("unlocked", gate["state"])
        self.assertEqual(1, gate["maximumEvaluations"])
        self.assertEqual(0, gate["consumedEvaluations"])
        self.assertFalse(gate["heldOutObserved"])
        self.assertEqual(
            promotion["promotionReceiptSha256"], gate["promotionReceiptSha256"]
        )
        self.assertEqual(
            sha256_json(
                {
                    key: value
                    for key, value in gate.items()
                    if key != "gateReceiptSha256"
                }
            ),
            gate["gateReceiptSha256"],
        )
        for key, value in promotion["bindings"].items():
            self.assertEqual(value, gate[key])

    def test_keep_allows_losing_lane_outcome_failure_when_candidate_decision_passes(self) -> None:
        validation = self._validation_report(
            retrieval_file_sha256=self._file_sha256(self.retrieval_path)
        )
        validation["lanes"][0]["hardGates"]["citationResolution"] = False
        validation["candidateDecision"] = {
            "schemaVersion": "rag-ime.rag-agent-candidate-decision.v1",
            "candidateLane": "agentic",
            "accepted": True,
            "decision": "keep",
            "failedHardGates": [],
            "comparisonIntegrityGates": [
                gate for gate in REQUIRED_HARD_GATES
                if gate not in {"citationResolution", "abstention"}
            ],
            "candidateOutcomeGates": ["citationResolution", "abstention"],
            "losingLaneOutcomeFailures": ["baseline:citationResolution"],
            "latencyDecisionRole": "diagnostic_only",
        }
        self._write_signed(self.validation_path, validation)

        promotion, gate = produce_authority(
            self.validation_path,
            self.retrieval_path,
            decision="keep",
        )

        self.assertEqual("promoted", promotion["state"])
        self.assertIsNotNone(gate)

    def test_reject_signs_rejection_receipt_and_never_returns_a_gate(self) -> None:
        promotion, gate = produce_authority(
            self.validation_path,
            self.retrieval_path,
            decision="reject",
        )

        self.assertEqual("reject", promotion["decision"])
        self.assertEqual("rejected", promotion["state"])
        self.assertIsNone(gate)
        self.assertEqual(
            sha256_json(
                {
                    key: value
                    for key, value in promotion.items()
                    if key != "promotionReceiptSha256"
                }
            ),
            promotion["promotionReceiptSha256"],
        )

        output = self.root / "rejection.json"
        forbidden_gate = self.root / "must-not-exist.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "promote_rag_agent_validation.py"),
                "--validation-agent-report",
                str(self.validation_path),
                "--retrieval-report",
                str(self.retrieval_path),
                "--decision",
                "reject",
                "--output-promotion",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(output.is_file())
        self.assertFalse(forbidden_gate.exists())

    def test_reject_accepts_structurally_valid_failed_validation_and_summarizes_it(
        self,
    ) -> None:
        failed = self._validation_report(
            retrieval_file_sha256=self._file_sha256(self.retrieval_path)
        )
        failed["passed"] = False
        failed["acceptanceStatus"] = "rejected"
        failed["cleanupPassed"] = False
        failed["failure"] = "validation hard gates failed"
        for lane in failed["lanes"]:
            lane["hardGates"]["runtimePinned"] = False
            lane["hardGates"]["cleanup"] = False
        failed["lanes"][1]["hardGates"]["answerJudge"] = False
        pi_runtime = failed["piRuntime"]
        pi_runtime.pop("identitySha256")
        pi_runtime["sourceAccess"] = "read-only-pointer-stable-verified-snapshot-v1"
        pi_runtime["identitySha256"] = sha256_json(pi_runtime)
        self._write_signed(self.validation_path, failed)

        rejection, gate = produce_authority(
            self.validation_path,
            self.retrieval_path,
            decision="reject",
        )

        self.assertIsNone(gate)
        self.assertEqual("rejected", rejection["state"])
        self.assertEqual(
            {
                "status": "validation_failed",
                "validationPassed": False,
                "acceptanceStatus": "rejected",
                "cleanupPassed": False,
                "failedHardGateNames": ["answerJudge", "cleanup", "runtimePinned"],
                "failedHardGatesByLane": {
                    "baseline": ["cleanup", "runtimePinned"],
                    "skill": ["answerJudge", "cleanup", "runtimePinned"],
                    "tuned": ["cleanup", "runtimePinned"],
                    "agentic": ["cleanup", "runtimePinned"],
                },
                "reportFailure": "validation hard gates failed",
            },
            rejection["failureSummary"],
        )
        self.assertEqual(
            sha256_json(
                {
                    key: value
                    for key, value in rejection.items()
                    if key != "promotionReceiptSha256"
                }
            ),
            rejection["promotionReceiptSha256"],
        )

    def test_reject_still_rejects_failed_report_runtime_status_identity_drift(
        self,
    ) -> None:
        failed = self._validation_report(
            retrieval_file_sha256=self._file_sha256(self.retrieval_path)
        )
        failed["passed"] = False
        pi_runtime = failed["piRuntime"]
        pi_runtime.pop("identitySha256")
        pi_runtime["sourceAccess"] = "read-only-pointer-stable-verified-snapshot-v1"
        pi_runtime["identitySha256"] = sha256_json(pi_runtime)
        self._write_signed(self.validation_path, failed)

        with self.assertRaisesRegex(ValueError, "runtimePinned"):
            produce_authority(
                self.validation_path,
                self.retrieval_path,
                decision="reject",
            )

    def test_keep_rejects_failed_validation_and_any_false_required_hard_gate(self) -> None:
        failed = dict(self.validation)
        failed["passed"] = False
        self._write_signed(self.validation_path, failed)
        with self.assertRaisesRegex(ValueError, "did not pass"):
            produce_authority(
                self.validation_path, self.retrieval_path, decision="keep"
            )

        for gate_name in ("runtimePinned", "cleanup"):
            with self.subTest(gate=gate_name):
                report = self._validation_report(
                    retrieval_file_sha256=self._file_sha256(self.retrieval_path)
                )
                report["lanes"][2]["hardGates"][gate_name] = False
                self._write_signed(self.validation_path, report)
                with self.assertRaisesRegex(ValueError, "hard gate"):
                    produce_authority(
                        self.validation_path,
                        self.retrieval_path,
                        decision="keep",
                    )

    def test_rejects_cross_report_identity_drift(self) -> None:
        drifted = dict(self.retrieval)
        drifted["sourcePreparedSha256"] = _digest("different-prepared")
        self._write_signed(self.retrieval_path, drifted)
        validation = self._validation_report(
            retrieval_file_sha256=self._file_sha256(self.retrieval_path)
        )
        self._write_signed(self.validation_path, validation)

        for decision in ("keep", "reject"):
            with self.subTest(decision=decision):
                with self.assertRaisesRegex(ValueError, "sourcePreparedSha256"):
                    produce_authority(
                        self.validation_path,
                        self.retrieval_path,
                        decision=decision,
                    )

    def test_rejects_tampered_logical_self_hash_in_either_input(self) -> None:
        for target in ("validation", "retrieval"):
            with self.subTest(target=target):
                self._write_signed(self.retrieval_path, self.retrieval)
                validation = self._validation_report(
                    retrieval_file_sha256=self._file_sha256(self.retrieval_path)
                )
                self._write_signed(self.validation_path, validation)
                path = (
                    self.validation_path
                    if target == "validation"
                    else self.retrieval_path
                )
                value = json.loads(path.read_text(encoding="utf-8"))
                value["reportSha256"] = _digest("tampered")
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")

                for decision in ("keep", "reject"):
                    with self.subTest(decision=decision):
                        with self.assertRaisesRegex(ValueError, "self hash"):
                            produce_authority(
                                self.validation_path,
                                self.retrieval_path,
                                decision=decision,
                            )

    def _retrieval_report(self) -> dict[str, object]:
        tuned = {
            "mode": "hybrid",
            "topK": 10,
            "rerankEnabled": True,
            "rerankCandidateDepth": 40,
            "rerankFinalDepth": 10,
        }
        return {
            "schemaVersion": "rag-ime.rag-retrieval-run.v2",
            "status": "completed",
            "localOnly": True,
            "uploaded": False,
            "evaluationScope": "validation-only",
            "sourcePreparedSha256": _digest("prepared"),
            "validationSelection": {
                "heldOutLabelsObserved": False,
                "frozenConfigSha256": sha256_json(tuned),
                "winner": {
                    "config": tuned,
                    "configSha256": sha256_json(tuned),
                },
            },
            "heldOut": None,
            "comparison": None,
            "hardGates": {
                "heldOutLabelsHiddenDuringSelection": True,
                "heldOutMetricsSuppressedDuringChunkSelection": True,
                "corpusFrozenBeforeCandidateEvaluation": True,
                "qrelsNotPassedToRetriever": True,
                "knowledgeGraphReady": True,
                "lunaKnowledgeGraphExtractionPassed": True,
                "memoryMutationNotPerformed": True,
                "independentRerankerReady": True,
            },
        }

    def _validation_report(self, *, retrieval_file_sha256: str) -> dict[str, object]:
        default_config = {"mode": "lexical", "topK": 10}
        tuned_config = self.retrieval["validationSelection"]["winner"]["config"]
        case_ids = ["validation-1", "validation-2"]
        answer_manifest = _digest("answer-manifest")
        answer_case_set = _digest("answer-case-set")
        selected_case_set = _digest("selected-case-set")
        prompt_config = _digest("prompt-config")
        runtime_contract = _digest("runtime-contract")
        pi_runtime = {
            "schemaVersion": "rag-ime.rag-agent-pi-runtime-identity.v1",
            "runtimeVersion": "1.0.0",
            "piVersion": "0.50.0",
            "protocolVersion": "2",
            "sourceAccess": "explicit-verified-payload-v1",
        }
        pi_runtime["identitySha256"] = sha256_json(pi_runtime)
        model_routing = {
            "schemaVersion": "rag-ime.rag-evaluation-model-routing.v1",
            "model": "openai-codex/gpt-5.6-sol",
            "thinking": "max",
            "routeIds": ["primary", "toolAgent", "subagent"],
        }
        model_routing["identitySha256"] = sha256_json(model_routing)
        agent_config = {
            "schemaVersion": "rag-ime.rag-evaluation-agent-config.v1",
            "provider": "openai-codex",
            "model": "openai-codex/gpt-5.6-sol",
            "thinking": "max",
            "modelRouting": model_routing,
        }
        agent_config["identitySha256"] = sha256_json(agent_config)
        conditions = {
            "evaluationMode": "answer-only",
            "evaluationSplit": "validation",
            "caseIdsSha256": sha256_json(case_ids),
            "promptConfigSha256": prompt_config,
            "answerCaseManifestSha256": answer_manifest,
            "answerCaseSetSha256": answer_case_set,
            "selectedAnswerCaseSetSha256": selected_case_set,
            "runtimeContractSha256": runtime_contract,
            "piRuntime": pi_runtime,
            "agentConfig": agent_config,
        }
        lanes = []
        for lane in ("baseline", "skill", "tuned", "agentic"):
            lanes.append(
                {
                    "lane": lane,
                    "retrievalConfigSha256": (
                        sha256_json(default_config)
                        if lane in {"baseline", "skill"}
                        else sha256_json(tuned_config)
                    ),
                    "hardGates": {
                        gate: True for gate in REQUIRED_HARD_GATES
                    },
                }
            )
        return {
            "schemaVersion": "rag-ime.rag-agent-ablation-run.v1",
            "passed": True,
            "formalAcceptanceEligible": False,
            "formalAcceptancePassed": False,
            "acceptanceStatus": "validation-accepted-not-formal",
            "localOnly": True,
            "uploaded": False,
            "sourcePreparedSha256": _digest("prepared"),
            "sourceAnswerCasesSha256": _digest("answer-cases-file"),
            "sourceRetrievalReportSha256": retrieval_file_sha256,
            "answerCaseManifest": {
                "manifestSha256": answer_manifest,
                "answerCaseSetSha256": answer_case_set,
                "selectedCaseSetSha256": selected_case_set,
            },
            "heldOutAuthorization": {
                "authorized": False,
                "reason": "validation-only evaluation does not consume held-out",
            },
            "evaluation": {
                "mode": "answer-only",
                "split": "validation",
                "caseCount": len(case_ids),
                "caseIds": case_ids,
                "caseIdsSha256": sha256_json(case_ids),
                "caseSetSha256": selected_case_set,
                "answerCaseManifestSha256": answer_manifest,
                "answerCaseSetSha256": answer_case_set,
                "promptConfigSha256": prompt_config,
                "formalAcceptanceEligible": False,
                "heldOutLabelsInPrompt": False,
            },
            "defaultRetrievalConfig": default_config,
            "defaultRetrievalConfigSha256": sha256_json(default_config),
            "tunedRetrievalConfig": tuned_config,
            "tunedRetrievalConfigSha256": sha256_json(tuned_config),
            "conditions": conditions,
            "piRuntime": pi_runtime,
            "agentConfig": agent_config,
            "lanes": lanes,
            "cleanupPassed": True,
            "calibration": {"enabled": False},
            "development": {"enabled": False},
        }

    @staticmethod
    def _write_signed(path: Path, report: dict[str, object]) -> None:
        candidate = dict(report)
        candidate.pop("reportSha256", None)
        candidate["reportSha256"] = sha256_json(candidate)
        report.clear()
        report.update(candidate)
        path.write_text(
            json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
