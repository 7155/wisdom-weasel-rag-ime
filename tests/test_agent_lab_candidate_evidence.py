from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from rag_ime.agent_lab.candidate_evidence import (
    _bound_json,
    _case_comparisons,
    _configuration_patch,
    _trace_binding,
    build_candidate_evidence,
    project_candidate_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "enterprise-rag.luna-prompt-v4-standard-r6.v1"


def _case(case_id: str, *, passed: bool) -> dict[str, object]:
    return {
        "evaluationCaseId": case_id,
        "queryId": "private-query",
        "answer": "private-answer",
        "agentSuccess": passed,
        "citationFactCoverage": 1.0 if passed else 0.6,
        "answerJudgeCorrect": passed,
        "toolSuccess": True,
        "abstentionExpected": False,
        "abstentionCorrect": True,
        "citationSupport": {"secret": "private-evidence"},
    }


class AgentLabCandidateEvidenceTests(unittest.TestCase):
    def test_case_comparison_matches_identity_and_only_projects_public_metrics(self) -> None:
        before = [_case("case-01", passed=False), _case("case-02", passed=True)]
        after = [_case("case-02", passed=True), _case("case-01", passed=True)]
        original = copy.deepcopy((before, after))
        rows = _case_comparisons(before, after)
        self.assertEqual([row["caseId"] for row in rows], ["case-01", "case-02"])
        self.assertEqual(rows[0]["before"]["status"], "failed")
        self.assertEqual(rows[0]["after"]["status"], "passed")
        self.assertEqual(rows[0]["before"]["metrics"]["citationFactCoverage"], 0.6)
        self.assertNotIn("private-", json.dumps(rows))
        self.assertEqual((before, after), original)

    def test_case_identity_or_denominator_drift_is_not_a_comparison(self) -> None:
        with self.assertRaises(ValueError):
            _case_comparisons([_case("case-01", passed=False)], [_case("case-02", passed=True)])
        with self.assertRaises(ValueError):
            _case_comparisons([_case("case-01", passed=False)] * 2, [_case("case-01", passed=True)] * 2)
        with self.assertRaises(ValueError):
            _case_comparisons([_case("case-01", passed=False)], [{**_case("case-01", passed=True), "abstentionExpected": True}])

    def test_patch_is_frozen_configuration_diff_not_a_reconstructed_source_commit(self) -> None:
        patch = _configuration_patch(
            {"conditions": {"model": "sol", "promptProfile": "incumbent", "privateBody": "secret"}},
            {"conditions": {"model": "luna", "promptProfile": "coverage-balanced-evidence-gate-v4"}},
            before_ref="baseline/report.json", after_ref="candidate/report.json",
        )
        self.assertEqual(patch["kind"], "frozen_configuration")
        self.assertIn('-  "model": "sol"', patch["unifiedDiff"])
        self.assertIn('+  "model": "luna"', patch["unifiedDiff"])
        self.assertNotIn("secret", patch["unifiedDiff"])
        self.assertEqual(patch["beforeRef"], "baseline/report.json#conditions")

    def test_hash_bound_loader_rejects_path_escape_symlink_and_changed_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owned = root / "eval/interview-metrics/runs"
            owned.mkdir(parents=True)
            source = owned / "receipt.json"
            source.write_text('{"safe":true}', encoding="utf-8")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            ref = "eval/interview-metrics/runs/receipt.json"
            self.assertEqual(_bound_json(root, ref, prefix="eval/interview-metrics/runs/", expected_sha256=expected), {"safe": True})
            for unsafe in ["../receipt.json", str(source), "eval/interview-metrics/runs/../receipt.json"]:
                with self.assertRaises(ValueError):
                    _bound_json(root, unsafe, prefix="eval/interview-metrics/runs/")
            outside = root / "outside.json"
            outside.write_text('{}', encoding="utf-8")
            (owned / "linked.json").symlink_to(outside)
            with self.assertRaises(ValueError):
                _bound_json(root, "eval/interview-metrics/runs/linked.json", prefix="eval/interview-metrics/runs/")
            source.write_text('{"safe":false}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _bound_json(root, ref, prefix="eval/interview-metrics/runs/", expected_sha256=expected)

    def test_trace_requires_explicit_canonical_identity_and_never_uses_session_hashes(self) -> None:
        self.assertEqual(_trace_binding("baseline", {"sessionSha256": "a" * 64})["status"], "unavailable")
        bound = _trace_binding("baseline", {"traceIds": ["trace:run:baseline", "not-a-trace", "trace:run:baseline"]})
        self.assertEqual(bound["traceIds"], ["trace:run:baseline"])

    def test_missing_artifact_keeps_experiment_readable_without_fabricating_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = project_candidate_evidence({"experimentId": EXPERIMENT_ID, "baseline": {"runId": "baseline", "evidenceRefs": []}}, root=Path(tmp))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["caseComparisons"], [])
        self.assertEqual(result["baselineTrace"]["traceIds"], [])

    @unittest.skipUnless((ROOT / ".rag-ime-data/eval/host/validation-answer-evidence-qrels-candidate-aware-attention-r6.json").is_file(), "Host-only frozen RAG artifacts unavailable")
    def test_current_r6_replays_existing_scorer_and_exposes_four_actual_case_deltas(self) -> None:
        from scripts.import_agent_lab_experiments import read_public_experiments
        _, _, experiments = read_public_experiments(ledger_path=ROOT / "eval/interview-metrics/agent-experiments.v1.json")
        experiment = next(row for row in experiments if row["experimentId"] == EXPERIMENT_ID)
        result = build_candidate_evidence(experiment, root=ROOT)
        self.assertEqual(result["status"], "partial")  # No canonical Trace IDs in frozen report.
        self.assertEqual(len(result["caseComparisons"]), 4)
        self.assertEqual(result["caseComparisons"][0]["before"]["metrics"]["citationFactCoverage"], 0.6)
        self.assertEqual(result["caseComparisons"][0]["after"]["metrics"]["citationFactCoverage"], 1.0)
        self.assertEqual(sum(row["before"]["status"] == "passed" for row in result["caseComparisons"]), 3)
        self.assertEqual(sum(row["after"]["status"] == "passed" for row in result["caseComparisons"]), 4)
        self.assertFalse(result["validationBoundary"]["unbiasedPromotionClaimAllowed"])
        self.assertFalse(result["validationBoundary"]["heldOutOpened"])
        self.assertIn('"promptProfile": "coverage-balanced-evidence-gate-v4"', result["patch"]["unifiedDiff"])

    def test_installed_projection_reads_public_receipt_without_private_files_or_scorer(self) -> None:
        from scripts.import_agent_lab_experiments import read_public_experiments
        from scripts.list_agent_lab_install_receipts import required_receipts
        _, _, experiments = read_public_experiments(ledger_path=ROOT / "eval/interview-metrics/agent-experiments.v1.json")
        experiment = next(row for row in experiments if row["experimentId"] == EXPERIMENT_ID)
        source = ROOT / "eval/interview-metrics/runs/agent-lab-candidate-evidence-enterprise-rag-r6.v1.json"
        self.assertIn(source, required_receipts(ROOT / "eval/interview-metrics/agent-experiments.v1.json"))
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp)
            ledger = ROOT / "eval/interview-metrics/agent-experiments.v1.json"
            for copied in (ledger, *required_receipts(ledger)):
                target = installed / copied.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(copied.read_bytes())
            with patch("rag_ime.agent_lab.candidate_evidence.build_candidate_evidence", side_effect=AssertionError("live GET must not rescore")):
                result = project_candidate_evidence(experiment, root=installed)
                from rag_ime.eval_lab import EvalLabProjection
                response = EvalLabProjection(installed / "paw.sqlite", source_ledger_path=installed / ledger.relative_to(ROOT)).list_runs()
                projected = next(row for row in response["experiments"] if row["experimentId"] == EXPERIMENT_ID)
                self.assertEqual(projected["optimizationEvidence"], result)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["caseComparisons"]), 4)
            self.assertEqual(result["patch"]["status"], "available")
            self.assertEqual(result["baselineTrace"]["status"], "unavailable")
            self.assertFalse((installed / ".rag-ime-data").exists())
            self.assertFalse((installed / "scripts").exists())
            self.assertEqual(project_candidate_evidence({**experiment, "revisionSha256": "0" * 64}, root=installed)["status"], "unavailable")

    def test_public_export_is_append_only_and_contains_no_case_bodies(self) -> None:
        from scripts.export_agent_lab_candidate_evidence import write_or_verify
        source = ROOT / "eval/interview-metrics/runs/agent-lab-candidate-evidence-enterprise-rag-r6.v1.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        forbidden = {"question", "queryId", "answer", "citations", "citationTokens", "qrels", "quote", "privateTranscript"}
        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(child) for child in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(child) for child in value))
            return set()
        self.assertFalse(forbidden & keys(payload))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "receipt.json"
            self.assertEqual(write_or_verify(target, payload), "written")
            original = target.read_bytes()
            self.assertEqual(write_or_verify(target, payload), "verified")
            with self.assertRaises(ValueError):
                write_or_verify(target, {**payload, "manifestSha256": "f" * 64})
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
