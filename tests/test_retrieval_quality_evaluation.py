from __future__ import annotations

import unittest

from rag_ime.retrieval_quality_evaluation import (
    REFERENCE_LANE_WEIGHTS,
    REFERENCE_METADATA_FUSION,
    REFERENCE_PROFILE,
    RetrievalEvaluationCase,
    RetrievalParameterSet,
    _balanced_limit,
    _dataset_payload,
    _holdout_gate,
    _metadata_cases,
    _parameter_grid,
    _runtime_defaults_match,
    _split_for_key,
)


def _reference_parameters() -> RetrievalParameterSet:
    return RetrievalParameterSet(
        name=REFERENCE_PROFILE,
        lane_weights=tuple(REFERENCE_LANE_WEIGHTS.items()),
        metadata_fusion=REFERENCE_METADATA_FUSION,
    )


def _score(*, quality: float, evidence_mrr: float) -> dict[str, object]:
    return {
        "qualityScore": quality,
        "maxMetadataFamilyAmplification": 1.2,
        "bySuite": {
            "evidence_input": {
                "count": 10,
                "successAt5": 0.8,
                "mrrAt10": evidence_mrr,
            },
            "metadata_term": {
                "count": 10,
                "successAt5": 0.9,
                "mrrAt10": 0.8,
            },
            "superseded_value": {
                "count": 2,
                "successAt5": 1.0,
                "mrrAt10": 1.0,
            },
        },
    }


class RetrievalQualityEvaluationTests(unittest.TestCase):
    def test_parameter_grid_is_deduplicated_and_contains_runtime_profile(self) -> None:
        candidates = _parameter_grid(_reference_parameters())
        signatures = {
            (
                candidate.lane_weights,
                candidate.metadata_fusion,
                candidate.rrf_k,
                candidate.query_coverage_weight,
            )
            for candidate in candidates
        }

        self.assertEqual(len(candidates), 387)
        self.assertEqual(len(signatures), len(candidates))
        self.assertEqual(
            [candidate.name for candidate in candidates if _runtime_defaults_match(candidate)],
            ["grid-r1.10-v1.05-m1.00-k40-q0.30"],
        )

    def test_holdout_gate_rejects_evidence_mrr_regression(self) -> None:
        baseline = _reference_parameters()
        selected = next(
            candidate
            for candidate in _parameter_grid(baseline)
            if candidate.name == "grid-r1.10-v1.05-m1.00-k40-q0.30"
        )

        accepted, reasons = _holdout_gate(
            baseline=_score(quality=0.70, evidence_mrr=0.60),
            selected=_score(quality=0.71, evidence_mrr=0.58),
            baseline_tuning=_score(quality=0.60, evidence_mrr=0.50),
            selected_tuning=_score(quality=0.62, evidence_mrr=0.52),
            baseline_parameters=baseline,
            selected_parameters=selected,
        )

        self.assertFalse(accepted)
        self.assertIn(
            "evidence_input MRR@10 regressed by more than 0.010",
            reasons,
        )

    def test_balanced_limit_is_stable_and_keeps_holdout_cases(self) -> None:
        cases = [
            RetrievalEvaluationCase(
                key=f"case-{index}",
                suite="evidence_input",
                query_text=f"query-{index}",
                expected_doc_ids=frozenset({f"doc-{index}"}),
                split=_split_for_key(f"doc-{index}"),
            )
            for index in range(100)
        ]

        first = _balanced_limit(cases, 20)
        second = _balanced_limit(cases, 20)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        self.assertTrue(any(case.split == "holdout" for case in first))
        self.assertTrue(any(case.split == "tuning" for case in first))

    def test_metadata_cases_are_unambiguous_and_grouped_by_target_doc(self) -> None:
        cases = _metadata_cases(
            {
                "atom-a": {
                    "doc_id": "doc-a",
                    "metadata_terms": ("alpha", "alpha-alias", "shared"),
                },
                "atom-b": {
                    "doc_id": "doc-b",
                    "metadata_terms": ("beta", "shared"),
                },
            },
            limit=20,
        )
        by_doc: dict[str, set[str]] = {}
        for case in cases:
            self.assertEqual(len(case.expected_doc_ids), 1)
            target = next(iter(case.expected_doc_ids))
            by_doc.setdefault(target, set()).add(case.split)

        self.assertEqual(set(by_doc), {"doc-a", "doc-b"})
        self.assertTrue(all(len(splits) == 1 for splits in by_doc.values()))
        self.assertEqual(len(cases), 3)

        dataset = _dataset_payload(cases)
        self.assertEqual(dataset["targetDocOverlapAcrossSplits"], 0)
        self.assertEqual(dataset["ambiguousMultiTargetCases"], 0)


if __name__ == "__main__":
    unittest.main()
