from __future__ import annotations

import json
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rag_ime.minimind_quality_gate import (
    DEFAULT_DATASET_ROOT,
    HUMAN_JUDGMENT_SCHEMA_VERSION,
    HumanJudgmentFixtureScorer,
    RawCompletionBatch,
    audit_completion_dataset,
    compare_quality_reports,
    export_minimind_ranking_pairs,
    export_minimind_training_pairs,
    load_completion_dataset,
    run_minimind_quality_gate,
    run_minimind_raw_output_gate,
    write_quality_report,
)
from rag_ime.models import ModelPrediction
from rag_ime.predictor import NullPredictionProvider
from scripts.minimind_retraining import main as retraining_main


class _DatasetProvider:
    def __init__(self, *, broken: bool = False, overrides: dict[str, list[str]] | None = None) -> None:
        dataset = load_completion_dataset(DEFAULT_DATASET_ROOT)
        self.by_prefix = {
            case.prefix: (list(case.hard_negatives) if broken and case.case_id == "test-tech-model-chain-1" else list(case.completions))
            for cases in dataset.values()
            for case in cases
        }
        self.by_prefix.update(overrides or {})
        self.calls: list[dict[str, object]] = []

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = "",
        rime_candidates=(),
    ):
        self.calls.append(
            {
                "currentInput": current_input,
                "recentContext": recent_context,
                "maxCandidates": max_candidates,
                "requestType": request_type,
                "rimeCandidates": tuple(rime_candidates),
            }
        )
        return [
            ModelPrediction(
                text=text,
                rank=index,
                provider_name="fake-minimind",
                latency_ms=12 + index,
                confidence=0.9,
            )
            for index, text in enumerate(self.by_prefix.get(recent_context, []), start=1)
        ][:max_candidates]


class _RawDatasetProvider:
    def __init__(self) -> None:
        dataset = load_completion_dataset(DEFAULT_DATASET_ROOT)
        self.by_prefix = {case.prefix: case.completions for cases in dataset.values() for case in cases}

    def complete_raw(self, *, prefix: str, max_candidates: int = 3) -> RawCompletionBatch:
        candidates = self.by_prefix.get(prefix, ())[:max_candidates]
        return RawCompletionBatch(
            candidates=tuple(candidates),
            raw_response="RAW:" + "|".join(candidates),
            latency_ms=9,
            provider_name="fake-raw-checkpoint",
        )


def _human_scorer(*, extra: list[dict[str, object]] | None = None) -> HumanJudgmentFixtureScorer:
    payload = _human_fixture_payload(extra=extra)
    with tempfile.TemporaryDirectory(prefix="minimind-judgments-") as tmp:
        path = Path(tmp) / "judgments.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return HumanJudgmentFixtureScorer.from_path(path)


def _human_fixture_payload(*, extra: list[dict[str, object]] | None = None) -> dict[str, object]:
    dataset = load_completion_dataset(DEFAULT_DATASET_ROOT)
    audit = audit_completion_dataset(DEFAULT_DATASET_ROOT)
    judgments = [
        {"caseId": case.case_id, "candidate": candidate, "accepted": accepted}
        for cases in dataset.values()
        for case in cases
        for accepted, values in ((True, case.completions), (False, case.hard_negatives))
        for candidate in values
    ]
    judgments.extend(extra or [])
    return {
        "schemaVersion": HUMAN_JUDGMENT_SCHEMA_VERSION,
        "datasetFingerprint": audit["datasetFingerprint"],
        "scorerId": "reviewed-fixture-v1",
        "judgments": judgments,
    }


class MiniMindQualityGateTests(unittest.TestCase):
    def test_public_dataset_is_split_safe_prompt_free_and_chain_valid(self) -> None:
        audit = audit_completion_dataset(DEFAULT_DATASET_ROOT)

        self.assertTrue(audit["ok"], audit)
        self.assertEqual(audit["splitCounts"], {"train": 8, "val": 5, "test": 6})
        self.assertEqual(audit["datasetRoot"], "dataset/minimind_completion_v3_public")
        self.assertEqual(audit["positivePairCount"], 57)
        self.assertEqual(audit["hardNegativeCount"], 57)
        self.assertGreaterEqual(audit["multiTurnChainCount"], 2)
        self.assertEqual(set(audit["domainCounts"]), {"technical", "daily"})
        self.assertTrue(all(item["goldTransitionsValid"] for item in audit["chains"]))
        self.assertEqual(len(audit["reviewedBaselines"]), 2)

    def test_export_contains_only_prefix_and_completion_and_never_hard_negatives(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-export-") as tmp:
            report = export_minimind_training_pairs(DEFAULT_DATASET_ROOT, tmp)
            rows = [
                json.loads(line)
                for line in (Path(tmp) / "test.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            source = load_completion_dataset(DEFAULT_DATASET_ROOT)["test"]
            hard_negative_pairs = {(case.prefix, value) for case in source for value in case.hard_negatives}

            self.assertTrue(report["ok"])
            self.assertEqual(report["pairCounts"], {"train": 24, "val": 15, "test": 18})
            self.assertTrue(all(set(row) == {"prefix", "completion"} for row in rows))
            self.assertFalse({(row["prefix"], row["completion"]) for row in rows} & hard_negative_pairs)
            self.assertTrue(report["prefixLossMasked"])
            self.assertFalse(report["hardNegativesExportedAsTargets"])

    def test_good_provider_passes_semantic_boundary_echo_and_continuous_tab_gate(self) -> None:
        provider = _DatasetProvider()
        report = run_minimind_quality_gate(
            provider,
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            checkpoint="fake-good",
            semantic_scorer=_human_scorer(),
        )

        self.assertTrue(report["gatePassed"], report)
        summary = report["summary"]
        for key in (
            "semanticTop1Rate",
            "semanticTop3Rate",
            "semanticJudgmentCoverageRate",
            "lexicalReferenceTop1Rate",
            "lexicalReferenceTop3Rate",
            "bareCompletionRate",
            "boundaryValidRate",
            "antiEchoRate",
            "threeCandidateRate",
            "hardNegativeAvoidanceRate",
            "diversityRate",
            "tabChainPassRate",
        ):
            self.assertEqual(summary[key], 1.0, key)
        self.assertEqual(len(report["tabChains"]), 2)
        self.assertTrue(all(item["passed"] for item in report["tabChains"]))
        self.assertTrue(all(call["currentInput"] == "" for call in provider.calls))
        self.assertTrue(all(call["requestType"] == "ime_post_commit" for call in provider.calls))
        self.assertEqual(report["evaluationStage"], "production_candidate")
        self.assertIn("parsing/filtering", report["candidateSourceContract"])
        self.assertTrue(report["promotionEligible"])

    def test_ranking_export_pairs_chosen_and_rejected_suffixes_without_chat_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-ranking-") as tmp:
            report = export_minimind_ranking_pairs(DEFAULT_DATASET_ROOT, tmp)
            rows = [
                json.loads(line)
                for line in (Path(tmp) / "test.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(report["pairCounts"], {"train": 24, "val": 15, "test": 18})
        self.assertTrue(report["promptFree"])
        self.assertFalse(report["useAsCausalPositiveTargets"])
        self.assertTrue(all(set(row) == {"prefix", "chosen", "rejected"} for row in rows))
        self.assertTrue(all(row["chosen"] != row["rejected"] for row in rows))

    def test_hard_negative_and_broken_word_boundary_fail_without_output_rewrite(self) -> None:
        provider = _DatasetProvider(broken=True)
        report = run_minimind_quality_gate(
            provider,
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            semantic_scorer=_human_scorer(),
        )
        broken = next(item for item in report["cases"] if item["caseId"] == "test-tech-model-chain-1")

        self.assertFalse(report["gatePassed"])
        self.assertFalse(broken["semanticTop1"])
        self.assertFalse(broken["boundaryValid"])
        self.assertEqual(broken["candidates"][0]["text"], "面再做检查。")
        self.assertFalse(broken["candidates"][0]["hardNegativeAvoided"])
        self.assertFalse(next(item for item in report["tabChains"] if item["chainId"] == "test-tech-model-chain")["passed"])

    def test_audit_detects_cross_split_prefix_leakage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-leak-") as tmp:
            copied = Path(tmp) / "dataset"
            shutil.copytree(DEFAULT_DATASET_ROOT, copied)
            train_first = json.loads((copied / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
            val_lines = (copied / "val.jsonl").read_text(encoding="utf-8").splitlines()
            val_first = json.loads(val_lines[0])
            val_first["prefix"] = train_first["prefix"]
            val_lines[0] = json.dumps(val_first, ensure_ascii=False, separators=(",", ":"))
            (copied / "val.jsonl").write_text("\n".join(val_lines) + "\n", encoding="utf-8")

            audit = audit_completion_dataset(copied)

        self.assertFalse(audit["ok"])
        self.assertIn("prefix_cross_split_leakage", {item["code"] for item in audit["errors"]})

    def test_audit_requires_one_hard_negative_for_each_positive_branch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-hard-negative-") as tmp:
            copied = Path(tmp) / "dataset"
            shutil.copytree(DEFAULT_DATASET_ROOT, copied)
            lines = (copied / "train.jsonl").read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0])
            first["hardNegatives"] = first["hardNegatives"][:2]
            lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
            (copied / "train.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

            audit = audit_completion_dataset(copied)

        self.assertFalse(audit["ok"])
        self.assertIn("hard_negative_count_must_match_completions", {item["code"] for item in audit["errors"]})

    def test_audit_rejects_missing_reviewed_baseline_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-baseline-") as tmp:
            copied = Path(tmp) / "dataset"
            shutil.copytree(DEFAULT_DATASET_ROOT, copied)
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["reviewedBaselines"][0]["humanJudgments"] = "baselines/missing.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            audit = audit_completion_dataset(copied)

        self.assertFalse(audit["ok"])
        self.assertIn("reviewed_baseline_file_missing", {item["code"] for item in audit["errors"]})

    def test_report_writer_and_baseline_comparison_are_machine_readable(self) -> None:
        report = run_minimind_quality_gate(
            _DatasetProvider(),
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            checkpoint="current",
            semantic_scorer=_human_scorer(),
        )
        baseline = json.loads(json.dumps(report))
        baseline["checkpoint"] = "baseline"
        baseline["summary"]["semanticTop1Rate"] = 0.5
        comparison = compare_quality_reports(report, baseline)

        with tempfile.TemporaryDirectory(prefix="minimind-report-") as tmp:
            path = Path(tmp) / "quality.json"
            report["comparison"] = comparison
            write_quality_report(report, path)
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(comparison["sameDatasetFingerprint"])
        self.assertEqual(comparison["deltas"]["semanticTop1Rate"], 0.5)
        self.assertEqual(loaded["schemaVersion"], "rag-ime.minimind-quality-gate.v1")

    def test_report_without_explicit_semantic_scorer_is_not_promotion_eligible(self) -> None:
        report = run_minimind_quality_gate(_DatasetProvider(), dataset_root=DEFAULT_DATASET_ROOT, split="test")

        self.assertFalse(report["gatePassed"])
        self.assertFalse(report["promotionEligible"])
        self.assertFalse(report["semanticScorer"]["configured"])
        self.assertEqual(report["summary"]["lexicalReferenceTop1Rate"], 1.0)
        self.assertEqual(report["summary"]["semanticJudgmentCoverageRate"], 0.0)

    def test_human_fixture_rejects_lexically_similar_antonym_and_accepts_paraphrase(self) -> None:
        dataset = load_completion_dataset(DEFAULT_DATASET_ROOT)["test"]
        antonym_case = next(case for case in dataset if case.case_id == "test-tech-model-chain-3")
        paraphrase_case = next(case for case in dataset if case.case_id == "test-tech-latency-semantic")
        antonym = "这轮已经偏离当前主题。"
        paraphrase = "仍需验证内容是否合适。"
        provider = _DatasetProvider(
            overrides={
                antonym_case.prefix: [antonym, *antonym_case.completions[1:]],
                paraphrase_case.prefix: [paraphrase, *paraphrase_case.completions[1:]],
            }
        )
        scorer = _human_scorer(
            extra=[
                {"caseId": antonym_case.case_id, "candidate": antonym, "accepted": False},
                {"caseId": paraphrase_case.case_id, "candidate": paraphrase, "accepted": True},
            ]
        )

        report = run_minimind_quality_gate(
            provider,
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            semantic_scorer=scorer,
        )
        antonym_report = next(item for item in report["cases"] if item["caseId"] == antonym_case.case_id)["candidates"][0]
        paraphrase_report = next(item for item in report["cases"] if item["caseId"] == paraphrase_case.case_id)["candidates"][0]

        self.assertTrue(antonym_report["lexicalReferenceAccepted"])
        self.assertFalse(antonym_report["semanticAccepted"])
        self.assertFalse(paraphrase_report["lexicalReferenceAccepted"])
        self.assertTrue(paraphrase_report["semanticAccepted"])

    def test_raw_output_gate_is_explicit_and_preserves_exact_branch_text(self) -> None:
        report = run_minimind_raw_output_gate(
            _RawDatasetProvider(),
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            checkpoint="raw-checkpoint",
            semantic_scorer=_human_scorer(),
        )

        self.assertTrue(report["gatePassed"], report)
        self.assertEqual(report["evaluationStage"], "raw_model_output")
        self.assertFalse(report["scoringContract"]["productionProviderMayParseOrFilter"])
        self.assertTrue(report["cases"][0]["rawResponse"].startswith("RAW:"))
        self.assertEqual(report["cases"][0]["candidates"][0]["text"], "补充剩余细节。")

    def test_comparison_rejects_fingerprint_mismatch_without_deltas(self) -> None:
        report = run_minimind_quality_gate(
            _DatasetProvider(),
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            semantic_scorer=_human_scorer(),
        )
        baseline = json.loads(json.dumps(report))
        baseline["datasetFingerprint"] = "sha256:different"

        comparison = compare_quality_reports(report, baseline)

        self.assertFalse(comparison["comparable"])
        self.assertEqual(comparison["rejectionReason"], "dataset_fingerprint_mismatch")
        self.assertNotIn("deltas", comparison)

    def test_evaluate_cli_rejects_an_unconfigured_predictor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="minimind-cli-") as tmp:
            report_path = Path(tmp) / "quality.json"
            stdout = io.StringIO()
            with patch(
                "scripts.minimind_retraining.prediction_provider_from_env",
                return_value=NullPredictionProvider(),
            ), redirect_stdout(stdout):
                code = retraining_main(
                    [
                        "evaluate",
                        "--provider",
                        "env",
                        "--report",
                        str(report_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertIn("predictor is not configured", payload["error"])
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), payload)

    def test_evaluate_cli_can_replay_explicit_raw_checkpoint_outputs(self) -> None:
        dataset = load_completion_dataset(DEFAULT_DATASET_ROOT)
        raw_rows = [
            {
                "prefix": case.prefix,
                "candidates": list(case.completions),
                "rawResponse": "RAW:" + "|".join(case.completions),
                "latencyMs": 11,
            }
            for cases in dataset.values()
            for case in cases
        ]
        with tempfile.TemporaryDirectory(prefix="minimind-raw-cli-") as tmp:
            raw_path = Path(tmp) / "raw.jsonl"
            judgment_path = Path(tmp) / "judgments.json"
            report_path = Path(tmp) / "report.json"
            raw_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in raw_rows),
                encoding="utf-8",
            )
            judgment_path.write_text(
                json.dumps(_human_fixture_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = retraining_main(
                    [
                        "evaluate",
                        "--stage",
                        "raw_model_output",
                        "--provider",
                        "raw-jsonl",
                        "--raw-output-jsonl",
                        str(raw_path),
                        "--semantic-judgments",
                        str(judgment_path),
                        "--report",
                        str(report_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["gatePassed"])
            self.assertEqual(payload["evaluationStage"], "raw_model_output")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
