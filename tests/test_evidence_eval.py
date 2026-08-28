from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.eval_run_store import EvalRunStore
from rag_ime.evidence_eval import evaluate_evidence_ground_truth
from rag_ime.trace_runtime import EvidenceRef, TraceContractError, build_trace_envelope, make_span


def _trace(trace_id: str, included: tuple[str, ...], *, status: str = "completed"):
    evidence = tuple(
        EvidenceRef(
            evidence_id=evidence_id,
            source_kind="knowledge",
            source_ref=f"knowledge://{evidence_id}",
            disposition="included",
        )
        for evidence_id in included
    )
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="vertical_agent",
        input_text="private user input must not enter EvalRun",
        spans=(make_span(span_id=f"span:{trace_id}", name="retrieve", started_at_ms=10, ended_at_ms=12),),
        evidence=evidence,
        status=status,
        now_ms=20,
    )


def _multi_stage_trace(trace_id: str, *, run_id: str):
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="vertical_agent",
        input_text="private input",
        binding={"runId": run_id},
        spans=(
            make_span(
                span_id=f"span:{trace_id}",
                name="retrieve",
                started_at_ms=10,
                ended_at_ms=12,
            ),
        ),
        evidence=(
            EvidenceRef(
                evidence_id="e1",
                source_kind="knowledge",
                source_ref="knowledge://e1",
                evidence_stage="retrieval_candidate",
                disposition="included",
            ),
            EvidenceRef(
                evidence_id="e1",
                source_kind="knowledge",
                source_ref="knowledge://e1",
                evidence_stage="retrieval_output",
                disposition="included",
            ),
        ),
        status="completed",
        now_ms=20,
    )


class EvidenceGroundTruthEvalTests(unittest.TestCase):
    def test_perfect_and_partial_sets_produce_reproducible_micro_metrics(self):
        traces = (_trace("trace:perfect", ("e1", "e2")), _trace("trace:partial", ("e2", "e3")))
        labels = {
            "trace:perfect": {"requiredEvidenceIds": ["e1", "e2"]},
            "trace:partial": {"requiredEvidenceIds": ["e2", "e4"]},
        }

        run = evaluate_evidence_ground_truth(traces, labels, dataset_id="dataset:v1", label_revision="labels:1")

        self.assertEqual(run["mode"], "ground_truth")
        self.assertEqual(run["metricAuthority"], "ground_truth")
        self.assertEqual(run["metrics"], {"precision": 0.75, "recall": 0.75, "f1": 0.75})
        self.assertNotIn("accuracy", run["metrics"])
        self.assertEqual(run["createdAtMs"], 20)

        repeat = evaluate_evidence_ground_truth(traces, labels, dataset_id="dataset:v1", label_revision="labels:1")
        self.assertEqual(repeat, run)

    def test_zero_denominator_is_explicitly_zero(self):
        run = evaluate_evidence_ground_truth(
            (_trace("trace:empty", ()),),
            {"trace:empty": {"requiredEvidenceIds": []}},
            dataset_id="dataset:v1",
            label_revision="labels:1",
        )

        self.assertEqual(run["metrics"], {"precision": 0.0, "recall": 0.0, "f1": 0.0})

    def test_store_persistence_is_idempotent_and_contains_no_transcript(self):
        with tempfile.TemporaryDirectory(prefix="evidence-eval-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            traces = (_trace("trace:1", ("e1",)),)
            labels = {"trace:1": ["e1"]}

            first = evaluate_evidence_ground_truth(
                traces, labels, dataset_id="dataset:v1", label_revision="labels:1", store=store
            )
            second = evaluate_evidence_ground_truth(
                traces, labels, dataset_id="dataset:v1", label_revision="labels:1", store=store
            )

            self.assertEqual(second, first)
            self.assertEqual(store.get(str(first["evalRunId"])), first)
            self.assertNotIn("private user input", str(first))
            self.assertNotIn("transcript", first)

    def test_different_explicit_times_get_distinct_ids_and_persist_without_conflict(self):
        with tempfile.TemporaryDirectory(prefix="evidence-eval-time-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            traces = (_trace("trace:1", ("e1",)),)
            labels = {"trace:1": ["e1"]}

            first = evaluate_evidence_ground_truth(
                traces, labels, dataset_id="dataset:v1", label_revision="labels:1", now_ms=30, store=store
            )
            second = evaluate_evidence_ground_truth(
                traces, labels, dataset_id="dataset:v1", label_revision="labels:1", now_ms=31, store=store
            )

            self.assertNotEqual(first["evalRunId"], second["evalRunId"])
            self.assertEqual(first["createdAtMs"], 30)
            self.assertEqual(second["createdAtMs"], 31)
            self.assertEqual(len(store.list()), 2)

    def test_same_evidence_across_stages_counts_once_and_random_run_binding_does_not_change_identity(self):
        labels = {"trace:staged": ["e1"]}
        first = evaluate_evidence_ground_truth(
            (_multi_stage_trace("trace:staged", run_id="sandbox:random-a"),),
            labels,
            dataset_id="dataset:v1",
            label_revision="labels:1",
        )
        second = evaluate_evidence_ground_truth(
            (_multi_stage_trace("trace:staged", run_id="sandbox:random-b"),),
            labels,
            dataset_id="dataset:v1",
            label_revision="labels:1",
        )

        self.assertEqual(
            first["metrics"],
            {"precision": 1.0, "recall": 1.0, "f1": 1.0},
        )
        self.assertEqual(first["evalRunId"], second["evalRunId"])

    def test_rejects_empty_or_mismatched_inputs_and_non_completed_traces(self):
        cases = (
            ((), {}, "non-empty trace"),
            ((_trace("trace:1", ("e1",)),), {}, "non-empty label"),
            ((_trace("trace:1", ("e1",)),), {"trace:other": ["e1"]}, "trace/label IDs"),
            ((_trace("trace:1", ("e1",), status="building"),), {"trace:1": ["e1"]}, "completed"),
        )
        for traces, labels, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TraceContractError, message):
                    evaluate_evidence_ground_truth(traces, labels, dataset_id="dataset:v1", label_revision="labels:1")

    def test_rejects_duplicate_trace_and_ai_judge_fields(self):
        trace = _trace("trace:1", ("e1",))
        with self.assertRaisesRegex(TraceContractError, "duplicate trace"):
            evaluate_evidence_ground_truth(
                (trace, trace), {"trace:1": ["e1"]}, dataset_id="dataset:v1", label_revision="labels:1"
            )
        with self.assertRaisesRegex(TraceContractError, "AI Judge"):
            evaluate_evidence_ground_truth(
                (trace,),
                {"trace:1": {"requiredEvidenceIds": ["e1"], "confidence": 0.9}},
                dataset_id="dataset:v1",
                label_revision="labels:1",
            )
        with self.assertRaisesRegex(TraceContractError, "AI Judge"):
            evaluate_evidence_ground_truth(
                (trace,),
                {"trace:1": ["e1"]},
                dataset_id="dataset:v1",
                label_revision="labels:1",
                evaluator={"provider": "openai"},
            )


if __name__ == "__main__":
    unittest.main()
