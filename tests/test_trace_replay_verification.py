from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.eval_run_store import EvalRunStore
from rag_ime.sandbox_run_store import SandboxRunStore
from rag_ime.trace_repair import TraceRepairStore
from rag_ime.trace_replay_verification import (
    TraceReplayVerificationStore,
    TraceVerificationValidationError,
)
from rag_ime.trace_runtime import (
    build_eval_run,
    build_sandbox_run,
    build_trace_envelope,
    fingerprint_text,
)
from rag_ime.trace_store import TraceStore


SOURCE_TRACE_ID = "trace:replay:source"
REPAIR_TRACE_ID = "trace:replay:repair"
REGRESSION_TRACE_ID = "trace:replay:regression"
REPAIR_SESSION_ID = "agent:replay:repair"


def _cohort(*, input_text: str = "same failing case") -> dict[str, str]:
    return {
        "suiteId": "suite:trace-replay",
        "suiteRevision": "suite-rev-1",
        "caseId": "case:one",
        "inputFingerprint": fingerprint_text(input_text),
        "environmentFingerprint": fingerprint_text("macos-arm64:runtime-1"),
        "configFingerprint": fingerprint_text("config-1"),
        "modelProfileFingerprint": fingerprint_text("model-profile-1"),
        "toolProfileFingerprint": fingerprint_text("tool-profile-1"),
        "skillProfileFingerprint": fingerprint_text("skill-profile-1"),
    }


def _trace(
    trace_id: str,
    *,
    input_text: str = "same failing case",
    session_id: str = "agent:replay:source",
) -> dict[str, object]:
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="agent",
        input_text=input_text,
        binding={"sessionId": session_id, "caseId": "case:one"},
        status="completed",
        now_ms=1,
    ).to_dict()


def _ground_truth_eval(
    eval_run_id: str,
    trace_id: str,
    accuracy: float,
    *,
    cohort: dict[str, str],
    suite_id: str | None = None,
) -> dict[str, object]:
    return build_eval_run(
        eval_run_id=eval_run_id,
        trace_ids=[trace_id],
        mode="ground_truth",
        truth_kind="frozen",
        metrics={"accuracy": accuracy},
        dataset_id="trace-replay-fixture",
        label_revision="labels-v1",
        suite_binding={
            "suiteId": suite_id or cohort["suiteId"],
            "suiteRevision": cohort["suiteRevision"],
        },
        input_trace_fingerprint=cohort["inputFingerprint"],
        status="completed",
        started_at_ms=1,
        completed_at_ms=2,
        elapsed_ms=1,
        latency_ms=1,
        usage={"input": 10, "output": 2, "totalTokens": 12},
        now_ms=1,
        updated_at_ms=2,
    ).to_dict()


def _sandbox(
    sandbox_run_id: str,
    trace_ids: list[str],
    eval_run_ids: list[str],
    *,
    cohort: dict[str, str],
) -> dict[str, object]:
    return build_sandbox_run(
        sandbox_run_id=sandbox_run_id,
        app_id="trace-agent",
        workspace_root="/workspace/replay-fixture",
        workspace_binding_id="workspace-binding:trace-replay",
        trace_ids=trace_ids,
        eval_run_ids=eval_run_ids,
        status="completed",
        replay_cohort=cohort,
        now_ms=3,
    ).to_dict()


def _repair_receipt(db: Path) -> dict[str, object]:
    store = TraceRepairStore(db)
    change = store.record_change_evidence(
        source_scope="trace-repair",
        source_trace_id=REPAIR_TRACE_ID,
        evidence={
            "schemaVersion": "rag-ime.trace-repair-canonical-evidence.v1",
            "evidenceKind": "change",
            "repairSessionId": REPAIR_SESSION_ID,
            "repairTraceId": REPAIR_TRACE_ID,
            "changeCount": 1,
            "toolNames": ["workspace_patch"],
        },
        created_at_ms=5,
    )
    test = store.record_test_evidence(
        source_scope="trace-repair",
        source_trace_id=REPAIR_TRACE_ID,
        evidence={
            "schemaVersion": "rag-ime.trace-repair-canonical-evidence.v1",
            "evidenceKind": "test",
            "repairSessionId": REPAIR_SESSION_ID,
            "repairTraceId": REPAIR_TRACE_ID,
            "status": "passed",
            "testCount": 1,
            "passedCount": 1,
            "failedCount": 0,
            "sandboxedCount": 1,
            "sandboxRequired": True,
            "toolNames": ["workspace_shell"],
        },
        status="passed",
        created_at_ms=6,
    )
    return store.persist_receipt(
        source_scope="trace-runtime",
        source_trace_id=SOURCE_TRACE_ID,
        failure_ref="failure:one",
        change_receipt_id=str(change["evidenceId"]),
        test_evidence_id=str(test["evidenceId"]),
        repair_trace_id=REPAIR_TRACE_ID,
        repair_session_id=REPAIR_SESSION_ID,
        created_at_ms=7,
    )


class TraceReplayVerificationTests(unittest.TestCase):
    def _stores(self, db: Path, *, after_accuracy: float = 1.0):
        cohort = _cohort()
        traces = TraceStore(db)
        traces.persist(_trace(SOURCE_TRACE_ID))
        traces.persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
        traces.persist(_trace(REGRESSION_TRACE_ID, input_text="regression case"))
        evals = EvalRunStore(db)
        evals.persist(_ground_truth_eval("eval:before", SOURCE_TRACE_ID, 0.0, cohort=cohort))
        evals.persist(_ground_truth_eval("eval:after", REPAIR_TRACE_ID, after_accuracy, cohort=cohort))
        regression_cohort = {**cohort, "inputFingerprint": fingerprint_text("regression case")}
        evals.persist(
            _ground_truth_eval(
                "eval:regression",
                REGRESSION_TRACE_ID,
                1.0,
                cohort=regression_cohort,
                suite_id="suite:trace-regression",
            )
        )
        sandboxes = SandboxRunStore(db)
        sandboxes.persist(
            _sandbox("sandbox:before", [SOURCE_TRACE_ID], ["eval:before"], cohort=cohort)
        )
        sandboxes.persist(
            _sandbox(
                "sandbox:after",
                [REPAIR_TRACE_ID, REGRESSION_TRACE_ID],
                ["eval:after", "eval:regression"],
                cohort=cohort,
            )
        )
        return cohort

    def test_same_case_ground_truth_replay_persists_a_kept_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-replay-") as temporary:
            db = Path(temporary) / "trace.sqlite"
            cohort = self._stores(db)
            repair = _repair_receipt(db)
            store = TraceReplayVerificationStore(db)

            replay_case = store.freeze_case(
                source_scope="trace-runtime",
                failure_ref="failure:one",
                source_trace_id=SOURCE_TRACE_ID,
                baseline_eval_run_id="eval:before",
                baseline_sandbox_run_id="sandbox:before",
                success_metric="accuracy",
                success_threshold=1.0,
                rollback_target="git:before-repair",
                created_at_ms=10,
            )
            receipt = store.verify_repair(
                replay_case_id=str(replay_case["replayCaseId"]),
                repair_receipt_id=str(repair["repairReceiptId"]),
                repair_eval_run_id="eval:after",
                repair_sandbox_run_id="sandbox:after",
                regression_eval_run_ids=["eval:regression"],
                verified_at_ms=20,
            )

            self.assertEqual(receipt["decision"], "kept")
            self.assertEqual(receipt["comparison"]["status"], "available")
            self.assertEqual(receipt["comparison"]["before"], 0.0)
            self.assertEqual(receipt["comparison"]["after"], 1.0)
            self.assertEqual(receipt["comparison"]["absoluteDelta"], 1.0)
            self.assertEqual(receipt["replayCohort"], cohort)
            self.assertTrue(receipt["regression"]["passed"])
            self.assertEqual(store.get_verification(str(receipt["verificationReceiptId"])), receipt)

    def test_changed_input_is_incomparable_and_writes_no_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-replay-") as temporary:
            db = Path(temporary) / "trace.sqlite"
            self._stores(db)
            repair = _repair_receipt(db)
            store = TraceReplayVerificationStore(db)
            replay_case = store.freeze_case(
                source_scope="trace-runtime",
                failure_ref="failure:one",
                source_trace_id=SOURCE_TRACE_ID,
                baseline_eval_run_id="eval:before",
                baseline_sandbox_run_id="sandbox:before",
                success_metric="accuracy",
                success_threshold=1.0,
                rollback_target="git:before-repair",
                created_at_ms=10,
            )
            after = EvalRunStore(db).get("eval:after")
            assert after is not None
            after["inputTraceFingerprint"] = fingerprint_text("different case")
            after["evalRunId"] = "eval:after:different"
            EvalRunStore(db).persist(after)

            with self.assertRaisesRegex(TraceVerificationValidationError, "input fingerprint"):
                store.verify_repair(
                    replay_case_id=str(replay_case["replayCaseId"]),
                    repair_receipt_id=str(repair["repairReceiptId"]),
                    repair_eval_run_id="eval:after:different",
                    repair_sandbox_run_id="sandbox:after",
                    regression_eval_run_ids=["eval:regression"],
                    verified_at_ms=20,
                )
            self.assertEqual(store.list_verifications(), [])

    def test_after_failure_is_persisted_as_rejected_not_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-replay-") as temporary:
            db = Path(temporary) / "trace.sqlite"
            self._stores(db, after_accuracy=0.0)
            repair = _repair_receipt(db)
            store = TraceReplayVerificationStore(db)
            replay_case = store.freeze_case(
                source_scope="trace-runtime",
                failure_ref="failure:one",
                source_trace_id=SOURCE_TRACE_ID,
                baseline_eval_run_id="eval:before",
                baseline_sandbox_run_id="sandbox:before",
                success_metric="accuracy",
                success_threshold=1.0,
                rollback_target="git:before-repair",
                created_at_ms=10,
            )
            receipt = store.verify_repair(
                replay_case_id=str(replay_case["replayCaseId"]),
                repair_receipt_id=str(repair["repairReceiptId"]),
                repair_eval_run_id="eval:after",
                repair_sandbox_run_id="sandbox:after",
                regression_eval_run_ids=["eval:regression"],
                verified_at_ms=20,
            )

            self.assertEqual(receipt["decision"], "rejected")
            self.assertFalse(receipt["repairPassed"])
            self.assertEqual(receipt["comparison"]["absoluteDelta"], 0.0)

    def test_regression_evidence_is_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-replay-") as temporary:
            db = Path(temporary) / "trace.sqlite"
            self._stores(db)
            repair = _repair_receipt(db)
            store = TraceReplayVerificationStore(db)
            replay_case = store.freeze_case(
                source_scope="trace-runtime",
                failure_ref="failure:one",
                source_trace_id=SOURCE_TRACE_ID,
                baseline_eval_run_id="eval:before",
                baseline_sandbox_run_id="sandbox:before",
                success_metric="accuracy",
                success_threshold=1.0,
                rollback_target="git:before-repair",
                created_at_ms=10,
            )

            with self.assertRaisesRegex(TraceVerificationValidationError, "regression"):
                store.verify_repair(
                    replay_case_id=str(replay_case["replayCaseId"]),
                    repair_receipt_id=str(repair["repairReceiptId"]),
                    repair_eval_run_id="eval:after",
                    repair_sandbox_run_id="sandbox:after",
                    regression_eval_run_ids=[],
                    verified_at_ms=20,
                )


if __name__ == "__main__":
    unittest.main()
