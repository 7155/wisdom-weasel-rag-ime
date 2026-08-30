from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.eval_run_store import EvalRunStore
from rag_ime.trace_repair import (
    TraceRepairConflict,
    TraceRepairStore,
    TraceRepairValidationError,
    run_ai_judge_recheck,
)
from rag_ime.trace_runtime import build_trace_envelope
from rag_ime.trace_store import TraceStore


REPAIR_SESSION_ID = "agent:repair:1"
REPAIR_TRACE_ID = "trace:repair:1"


def _trace(
    trace_id: str = "trace:source:1",
    *,
    session_id: str = "",
) -> dict[str, object]:
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="agent",
        input_text="private input is never copied into the receipt",
        binding={"sessionId": session_id} if session_id else None,
        status="completed",
        now_ms=20,
    ).to_dict()


def _change_evidence(
    *,
    repair_session_id: str = REPAIR_SESSION_ID,
    repair_trace_id: str = REPAIR_TRACE_ID,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.trace-repair-canonical-evidence.v1",
        "evidenceKind": "change",
        "repairSessionId": repair_session_id,
        "repairTraceId": repair_trace_id,
        "eventCount": 1,
        "completedCount": 1,
        "toolCount": 1,
        "toolNames": ["workspace_patch"],
        "signalIds": ["event:change:1"],
        "changeCount": 1,
    }


def _test_evidence(
    *,
    repair_session_id: str = REPAIR_SESSION_ID,
    repair_trace_id: str = REPAIR_TRACE_ID,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.trace-repair-canonical-evidence.v1",
        "evidenceKind": "test",
        "repairSessionId": repair_session_id,
        "repairTraceId": repair_trace_id,
        "eventCount": 1,
        "completedCount": 1,
        "toolCount": 1,
        "toolNames": ["unittest"],
        "signalIds": ["event:test:1"],
        "testCount": 1,
        "passedCount": 1,
        "failedCount": 0,
        "status": "passed",
    }


def _record_evidence_pair(
    store: TraceRepairStore,
) -> tuple[dict[str, object], dict[str, object]]:
    change = store.record_change_evidence(
        source_scope="trace-repair",
        source_trace_id=REPAIR_TRACE_ID,
        evidence=_change_evidence(),
    )
    test = store.record_test_evidence(
        source_scope="trace-repair",
        source_trace_id=REPAIR_TRACE_ID,
        evidence=_test_evidence(),
        status="passed",
    )
    return change, test


class TraceRepairStoreTests(unittest.TestCase):
    def test_change_and_test_evidence_are_durable_and_receipt_is_bound_to_both(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            traces = TraceStore(db)
            traces.persist(_trace())
            traces.persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            store = TraceRepairStore(db)
            change, test = _record_evidence_pair(store)

            receipt = store.persist_receipt(
                source_scope="trace-runtime",
                source_trace_id="trace:source:1",
                failure_ref="failure:trace:timeout",
                change_receipt_id=str(change["evidenceId"]),
                test_evidence_id=str(test["evidenceId"]),
                repair_trace_id=REPAIR_TRACE_ID,
                repair_session_id=REPAIR_SESSION_ID,
            )

            self.assertEqual(
                set(receipt),
                {
                    "schemaVersion", "repairReceiptId", "sourceScope", "sourceTraceId",
                    "failureRef", "changeReceiptId", "testEvidenceId", "testStatus",
                    "repairTraceId", "repairSessionId", "createdAtMs",
                },
            )
            self.assertEqual(store.get_receipt(str(receipt["repairReceiptId"])), receipt)
            self.assertEqual(
                store.get_evidence(str(change["evidenceId"]))["evidenceId"],
                change["evidenceId"],
            )

    def test_receipt_rejects_arbitrary_or_cross_trace_evidence_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            TraceStore(db).persist(_trace())
            TraceStore(db).persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            store = TraceRepairStore(db)
            with self.assertRaises(TraceRepairValidationError):
                store.persist_receipt(
                    source_scope="trace-runtime",
                    source_trace_id="trace:source:1",
                    failure_ref="failure:1",
                    change_receipt_id="change:does-not-exist",
                    test_evidence_id="test:does-not-exist",
                    repair_trace_id=REPAIR_TRACE_ID,
                    repair_session_id=REPAIR_SESSION_ID,
                )
            other = store.record_change_evidence(
                source_scope="trace-repair",
                source_trace_id="trace:other-repair",
                evidence=_change_evidence(repair_trace_id="trace:other-repair"),
            )
            test = store.record_test_evidence(
                source_scope="trace-repair",
                source_trace_id=REPAIR_TRACE_ID,
                evidence=_test_evidence(),
                status="passed",
            )
            with self.assertRaises(TraceRepairValidationError):
                store.persist_receipt(
                    source_scope="trace-runtime",
                    source_trace_id="trace:source:1",
                    failure_ref="failure:1",
                    change_receipt_id=str(other["evidenceId"]),
                    test_evidence_id=str(test["evidenceId"]),
                    repair_trace_id=REPAIR_TRACE_ID,
                    repair_session_id=REPAIR_SESSION_ID,
                )

    def test_receipt_identity_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            TraceStore(db).persist(_trace())
            TraceStore(db).persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            store = TraceRepairStore(db)
            change, test = _record_evidence_pair(store)
            first = store.persist_receipt(
                source_scope="trace-runtime", source_trace_id="trace:source:1", failure_ref="failure:1",
                change_receipt_id=str(change["evidenceId"]), test_evidence_id=str(test["evidenceId"]),
                repair_trace_id=REPAIR_TRACE_ID, repair_session_id=REPAIR_SESSION_ID,
            )
            self.assertEqual(store.persist_receipt(**{
                "source_scope": "trace-runtime", "source_trace_id": "trace:source:1", "failure_ref": "failure:1",
                "change_receipt_id": str(change["evidenceId"]), "test_evidence_id": str(test["evidenceId"]),
                "repair_trace_id": REPAIR_TRACE_ID, "repair_session_id": REPAIR_SESSION_ID,
            }), first)
            with self.assertRaises(TraceRepairConflict):
                store.persist_receipt(
                    source_scope="trace-runtime", source_trace_id="trace:source:1", failure_ref="failure:changed",
                    change_receipt_id=str(change["evidenceId"]), test_evidence_id=str(test["evidenceId"]),
                    repair_trace_id=REPAIR_TRACE_ID, repair_session_id=REPAIR_SESSION_ID,
                )


class TraceRepairRecheckTests(unittest.TestCase):
    def test_ai_judge_recheck_is_bound_to_repair_and_writes_eval_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-recheck-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            TraceStore(db).persist(_trace())
            TraceStore(db).persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            repair_store = TraceRepairStore(db)
            change, test = _record_evidence_pair(repair_store)
            receipt = repair_store.persist_receipt(
                source_scope="trace-runtime", source_trace_id="trace:source:1", failure_ref="failure:1",
                change_receipt_id=str(change["evidenceId"]), test_evidence_id=str(test["evidenceId"]),
                repair_trace_id=REPAIR_TRACE_ID, repair_session_id=REPAIR_SESSION_ID,
            )
            result = run_ai_judge_recheck(
                trace_store=TraceStore(db), repair_store=repair_store, eval_store=EvalRunStore(db),
                source_trace_id="trace:source:1", repair_trace_id=REPAIR_TRACE_ID,
                source_scope="trace-runtime", failure_ref="failure:1",
                judge=lambda _trace: {"relevance": .9, "coverage": .8, "groundedness": .7, "contradiction": .1, "confidence": .9},
                now_ms=30,
            )
            self.assertEqual(result["traceIds"], [REPAIR_TRACE_ID])
            self.assertEqual(result["sourceTraceId"], "trace:source:1")
            self.assertEqual(result["repairTraceId"], REPAIR_TRACE_ID)
            self.assertEqual(result["repairReceiptId"], receipt["repairReceiptId"])
            self.assertEqual(result["changeReceiptId"], change["evidenceId"])
            self.assertEqual(result["testEvidenceId"], test["evidenceId"])

    def test_ai_judge_recheck_rejects_latest_unrelated_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-recheck-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            trace_store = TraceStore(db)
            trace_store.persist(_trace())
            trace_store.persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            repair_store = TraceRepairStore(db)
            change, test = _record_evidence_pair(repair_store)
            repair_store.persist_receipt(
                source_scope="trace-runtime",
                source_trace_id="trace:source:1",
                failure_ref="failure:1",
                change_receipt_id=str(change["evidenceId"]),
                test_evidence_id=str(test["evidenceId"]),
                repair_trace_id=REPAIR_TRACE_ID,
                repair_session_id=REPAIR_SESSION_ID,
            )
            trace_store.persist(_trace("trace:unrelated:latest"))
            with self.assertRaisesRegex(TraceRepairValidationError, "repair trace"):
                run_ai_judge_recheck(
                    trace_store=trace_store, repair_store=repair_store, eval_store=EvalRunStore(db),
                    source_trace_id="trace:source:1", repair_trace_id="trace:unrelated:latest",
                    source_scope="trace-runtime", failure_ref="failure:1",
                    judge=lambda _trace: {"relevance": .9, "coverage": .8, "groundedness": .7, "contradiction": .1, "confidence": .9},
                    now_ms=30,
                )

    def test_ai_judge_recheck_rejects_permuted_receipt_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-repair-recheck-") as tmp:
            db = Path(tmp) / "trace.sqlite"
            trace_store = TraceStore(db)
            trace_store.persist(_trace())
            trace_store.persist(_trace(REPAIR_TRACE_ID, session_id=REPAIR_SESSION_ID))
            repair_store = TraceRepairStore(db)
            change, test = _record_evidence_pair(repair_store)
            receipt = repair_store.persist_receipt(
                source_scope="trace-runtime",
                source_trace_id="trace:source:1",
                failure_ref="failure:1",
                change_receipt_id=str(change["evidenceId"]),
                test_evidence_id=str(test["evidenceId"]),
                repair_trace_id=REPAIR_TRACE_ID,
                repair_session_id=REPAIR_SESSION_ID,
            )
            permuted = dict(receipt)
            permuted["sourceScope"] = "failure:1"
            permuted["failureRef"] = "trace-runtime"

            with patch("rag_ime.trace_repair._receipts_for_store", return_value=[permuted]):
                with self.assertRaisesRegex(TraceRepairValidationError, "binding"):
                    run_ai_judge_recheck(
                        trace_store=trace_store,
                        repair_store=repair_store,
                        eval_store=EvalRunStore(db),
                        source_trace_id="trace:source:1",
                        repair_trace_id=REPAIR_TRACE_ID,
                        source_scope="trace-runtime",
                        failure_ref="failure:1",
                        judge=lambda _trace: {
                            "relevance": .9,
                            "coverage": .8,
                            "groundedness": .7,
                            "contradiction": .1,
                            "confidence": .9,
                        },
                        now_ms=30,
                    )


if __name__ == "__main__":
    unittest.main()
