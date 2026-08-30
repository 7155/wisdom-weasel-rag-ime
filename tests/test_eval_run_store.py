from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.eval_run_store import EvalRunConflict, EvalRunStore
from rag_ime.trace_runtime import TraceContractError, build_eval_run


def _ground_truth(eval_run_id: str = "eval:1", *, now_ms: int = 20):
    return build_eval_run(
        eval_run_id=eval_run_id,
        trace_ids=["trace:b", "trace:a"],
        mode="ground_truth",
        truth_kind="frozen",
        dataset_id="dataset:v1",
        label_revision="labels:v3",
        metrics={"accuracy": 0.75, "f1": 1.0},
        now_ms=now_ms,
    )


def _ai_judge(eval_run_id: str = "eval:judge", *, now_ms: int = 10):
    return build_eval_run(
        eval_run_id=eval_run_id,
        trace_ids=["trace:a"],
        mode="ai_judge",
        truth_kind="none",
        evaluator={
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "thinking": "max",
            "displayName": "Luna Max",
        },
        metrics={"confidence": 0.8},
        now_ms=now_ms,
    )


class EvalRunStoreTests(unittest.TestCase):
    def test_persists_validated_payload_and_preserves_authority_without_transcript(self):
        with tempfile.TemporaryDirectory(prefix="eval-run-store-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            run = _ground_truth()

            persisted = store.persist(run)

            self.assertEqual(persisted, run.to_dict())
            self.assertEqual(store.get("eval:1"), run.to_dict())
            self.assertEqual(persisted["metricAuthority"], "ground_truth")
            self.assertEqual(persisted["truth"], {
                "status": "frozen",
                "datasetId": "dataset:v1",
                "labelRevision": "labels:v3",
            })
            self.assertNotIn("input", persisted)
            self.assertNotIn("prompt", persisted)
            self.assertNotIn("transcript", persisted)
            with closing(sqlite3.connect(Path(tmp) / "eval.sqlite")) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(eval_runs)")}
            self.assertFalse({"input", "prompt", "transcript"}.intersection(columns))

    def test_same_id_same_payload_is_idempotent_and_different_payload_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="eval-run-store-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            first = _ground_truth()

            self.assertEqual(store.persist(first), store.persist(first.to_dict()))
            changed = _ground_truth(now_ms=21)
            with self.assertRaises(EvalRunConflict):
                store.persist(changed)

    def test_list_is_stable_and_trace_lookup_is_indexed_by_real_trace_ids(self):
        with tempfile.TemporaryDirectory(prefix="eval-run-store-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            store.persist(_ground_truth(now_ms=20))
            store.persist(_ai_judge(now_ms=10))
            store.persist(_ground_truth("eval:0", now_ms=10))

            self.assertEqual(
                [item["evalRunId"] for item in store.list()],
                ["eval:0", "eval:judge", "eval:1"],
            )
            self.assertEqual(
                [item["evalRunId"] for item in store.for_trace("trace:a")],
                ["eval:0", "eval:judge", "eval:1"],
            )
            self.assertEqual(store.for_trace("trace:missing"), [])

            recent, total = store.recent_for_trace("trace:a", limit=2)
            self.assertEqual(total, 3)
            self.assertEqual(
                [item["evalRunId"] for item in recent],
                ["eval:1", "eval:judge"],
            )
            with self.assertRaises(ValueError):
                store.recent_for_trace("trace:a", limit=0)

    def test_rejects_unvalidated_and_mixed_authority_payloads_before_write(self):
        with tempfile.TemporaryDirectory(prefix="eval-run-store-") as tmp:
            store = EvalRunStore(Path(tmp) / "eval.sqlite")
            invalid = _ai_judge("eval:invalid").to_dict()
            invalid["prompt"] = "must never persist"
            with self.assertRaises(TraceContractError):
                store.persist(invalid)

            judge = store.persist(_ai_judge())
            self.assertEqual(judge["metricAuthority"], "ai_judge_estimate")
            self.assertEqual(judge["truth"]["status"], "none")

    def test_suite_binding_is_optional_for_manual_runs_but_typed_when_present(self):
        manual = _ground_truth()
        self.assertNotIn("suiteBinding", manual.to_dict())
        bound = build_eval_run(
            eval_run_id="eval:bound",
            trace_ids=["trace:a"],
            mode="ground_truth",
            truth_kind="frozen",
            dataset_id="dataset:v1",
            label_revision="labels:v3",
            metrics={"f1": 1.0},
            suite_binding={"suiteId": "sgg", "suiteRevision": "fixture-v2"},
            now_ms=20,
        ).to_dict()
        self.assertEqual(
            bound["suiteBinding"],
            {"suiteId": "sgg", "suiteRevision": "fixture-v2"},
        )
        for invalid in (
            {"suiteId": "sgg"},
            {"suiteId": "sgg", "suiteRevision": "fixture-v2", "extra": "x"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(TraceContractError):
                build_eval_run(
                    eval_run_id="eval:invalid-binding",
                    trace_ids=["trace:a"],
                    mode="ground_truth",
                    truth_kind="frozen",
                    dataset_id="dataset:v1",
                    label_revision="labels:v3",
                    metrics={"f1": 1.0},
                    suite_binding=invalid,
                    now_ms=20,
                )


if __name__ == "__main__":
    unittest.main()
