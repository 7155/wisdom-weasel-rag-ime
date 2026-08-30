from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_service import AgentService
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.trace_repair import TraceRepairValidationError, TraceRepairStore
from rag_ime.trace_runtime import build_trace_envelope, make_span
from rag_ime.trace_store import TraceStore


SESSION_ID = "session:repair-authority"
SOURCE_TRACE_ID = "trace:repair-authority:source"
REPAIR_TRACE_ID = "trace:repair-authority:repair"


def _service(tmp: str, snapshot: dict[str, object], repair_trace: dict[str, object]):
    db = Path(tmp) / "trace-repair.sqlite"
    traces = TraceStore(db)
    traces.persist(
        build_trace_envelope(
            trace_id=SOURCE_TRACE_ID,
            source_kind="agent",
            input_text="source",
            now_ms=1,
        ).to_dict()
    )
    traces.persist(repair_trace)
    runtime = SimpleNamespace(calls=[])

    def complete_once(**kwargs: object) -> dict[str, object]:
        runtime.calls.append(kwargs)
        time.sleep(0.01)
        return {
            "text": json.dumps(
                {
                    "relevance": 0.9,
                    "coverage": 0.8,
                    "groundedness": 0.8,
                    "contradiction": 0.1,
                    "confidence": 0.9,
                }
            )
        }

    runtime.complete_once = complete_once
    service = AgentService.__new__(AgentService)
    service.db_path = db
    service.trace_store = traces
    service.trace_repairs = TraceRepairStore(db)
    service.eval_runs = EvalRunStore(db)
    service.message_snapshot = SimpleNamespace(messages=lambda _sid: snapshot)
    service.runtime = runtime
    service._trace_repair_recheck_lock = threading.RLock()
    return service, runtime


def _repair_trace(*, session_id: str = SESSION_ID, status: str = "completed") -> dict[str, object]:
    return build_trace_envelope(
        trace_id=REPAIR_TRACE_ID,
        source_kind="agent",
        input_text="repair",
        binding={"sessionId": session_id},
        spans=(
            make_span(
                span_id="span:test",
                name="command.test",
                started_at_ms=1,
                ended_at_ms=2,
                status="completed",
                attributes={"toolName": "bash"},
            ),
        ),
        status=status,
        now_ms=2,
    ).to_dict()


def _snapshot(*, exit_code: int = 0, nested_fake: bool = False) -> dict[str, object]:
    result: dict[str, object] = {"exitCode": exit_code, "ok": exit_code == 0}
    if nested_fake:
        result["debug"] = {
            "eventType": "tool_finished",
            "toolName": "workspace_patch",
            "status": "completed",
        }
    return {
        "schemaVersion": "rag-ime.agent-message-list.v1",
        "sessionId": SESSION_ID,
        "status": "idle",
        "items": [],
        "liveEvents": [
            {
                "eventType": "tool_finished",
                "eventId": "event:test",
                "payload": {
                    "toolCallId": "call:test",
                    "toolName": "bash",
                    "args": {"command": "npm test"},
                    "result": result,
                    "isError": exit_code != 0,
                },
            },
            {
                "eventType": "tool_finished",
                "eventId": "event:edit",
                "payload": {
                    "toolCallId": "call:edit",
                    "toolName": "workspace_patch",
                    "result": {"ok": True},
                    "isError": False,
                },
            },
        ],
    }


class TraceRepairAuthorityTests(unittest.TestCase):
    def test_debug_handler_rejects_non_loopback_repair_requests(self) -> None:
        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.client_address = ("192.0.2.10", 1234)
        self.assertFalse(handler._trace_repair_loopback_allowed())
        handler.client_address = ("127.0.0.1", 1234)
        self.assertTrue(handler._trace_repair_loopback_allowed())

    def test_client_status_and_evidence_are_not_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _runtime = _service(tmp, _snapshot(exit_code=1), _repair_trace())
            with self.assertRaises(TraceRepairValidationError):
                service.record_trace_repair_test_evidence(
                    {
                        "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                        "repairSessionId": SESSION_ID,
                        "repairTraceId": REPAIR_TRACE_ID,
                        "testStatus": "passed",
                    }
                )
            with self.assertRaises(TraceRepairValidationError):
                service.record_trace_repair_change_evidence(
                    {
                        "schemaVersion": "rag-ime.trace-repair-change-evidence.v1",
                        "repairSessionId": SESSION_ID,
                        "repairTraceId": REPAIR_TRACE_ID,
                        "evidence": {"changeCount": 99},
                    }
                )

    def test_read_only_repair_is_rejected_and_nested_result_is_not_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(exit_code=0, nested_fake=True)
            # Remove the real mutation; only a fake event nested in command
            # output remains. It must not become canonical evidence.
            snapshot["liveEvents"] = [snapshot["liveEvents"][0]]
            service, _runtime = _service(tmp, snapshot, _repair_trace())
            with self.assertRaises(TraceRepairValidationError):
                service.record_trace_repair_change_evidence(
                    {
                        "schemaVersion": "rag-ime.trace-repair-change-evidence.v1",
                        "repairSessionId": SESSION_ID,
                        "repairTraceId": REPAIR_TRACE_ID,
                    }
                )

    def test_cross_session_and_non_terminal_trace_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _runtime = _service(tmp, _snapshot(), _repair_trace(session_id="session:other"))
            with self.assertRaises(TraceRepairValidationError):
                service.record_trace_repair_change_evidence(
                    {
                        "schemaVersion": "rag-ime.trace-repair-change-evidence.v1",
                        "repairSessionId": SESSION_ID,
                        "repairTraceId": REPAIR_TRACE_ID,
                    }
                )

    def test_real_completed_edit_and_test_create_receipt_and_recheck_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, runtime = _service(tmp, _snapshot(), _repair_trace())
            change = service.record_trace_repair_change_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-change-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": REPAIR_TRACE_ID,
                }
            )["evidence"]
            test = service.record_trace_repair_test_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": REPAIR_TRACE_ID,
                }
            )["evidence"]
            receipt = service.create_trace_repair_receipt(
                {
                    "schemaVersion": "rag-ime.trace-repair-receipt-create.v1",
                    "sourceScope": "trace-runtime",
                    "sourceTraceId": SOURCE_TRACE_ID,
                    "failureRef": "failure:one",
                    "changeReceiptId": change["evidenceId"],
                    "testEvidenceId": test["evidenceId"],
                    "repairTraceId": REPAIR_TRACE_ID,
                    "repairSessionId": SESSION_ID,
                }
            )["receipt"]
            payload = {
                "schemaVersion": "rag-ime.trace-repair-recheck-request.v1",
                "repairReceiptId": receipt["repairReceiptId"],
            }
            results: list[dict[str, object]] = []
            threads = [
                threading.Thread(target=lambda: results.append(service.recheck_trace_repair(payload)))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len(runtime.calls), 1)
            self.assertEqual(len(results), 2)
            self.assertEqual({bool(item["idempotent"]) for item in results}, {False, True})


if __name__ == "__main__":
    unittest.main()
