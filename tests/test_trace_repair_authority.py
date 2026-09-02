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


def _service(
    tmp: str,
    snapshot: dict[str, object],
    repair_trace: dict[str, object] | None,
    *,
    terminal_turn_id: str = "",
    persist_source_trace: bool = True,
):
    db = Path(tmp) / "trace-repair.sqlite"
    traces = TraceStore(db)
    if persist_source_trace:
        traces.persist(
            build_trace_envelope(
                trace_id=SOURCE_TRACE_ID,
                source_kind="agent",
                input_text="source",
                now_ms=1,
            ).to_dict()
        )
    if repair_trace is not None:
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

    def runtime_turn_terminal_event(
        session_id: str,
        turn_id: str,
    ) -> dict[str, object] | None:
        if session_id != SESSION_ID or turn_id != terminal_turn_id:
            return None
        return {
            "eventId": f"event:{turn_id}:terminal",
            "sessionId": session_id,
            "turnId": turn_id,
            "sequence": 42,
            "eventType": "turn_completed",
            "createdAtMs": 25,
            "status": "completed",
        }

    service.sessions = SimpleNamespace(
        runtime_turn_terminal_event=runtime_turn_terminal_event
    )
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


def _snapshot(
    *,
    exit_code: int = 0,
    nested_fake: bool = False,
    sandboxed: bool = True,
    receipt_nested: bool = False,
    turn_id: str = "",
) -> dict[str, object]:
    result: dict[str, object] = {
        "schemaVersion": "rag-ime.workspace-command-receipt.v1",
        "commandSha256": "a" * 64,
        "networkAllowed": not sandboxed,
        "timedOut": False,
        "outputLimited": False,
        "sourceReadOnly": False,
        "temporaryWritesDiscarded": False,
        "exitCode": exit_code,
        "ok": exit_code == 0,
    }
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
        "items": (
            [{
                "id": f"{turn_id}:assistant",
                "turnId": turn_id,
                "role": "assistant",
                "status": "completed",
                "createdAtMs": 10,
                "completedAtMs": 20,
            }]
            if turn_id
            else []
        ),
        "liveEvents": [
            {
                "eventType": "tool_finished",
                "eventId": "event:test",
                "payload": {
                    "toolCallId": "call:test",
                    "toolName": "bash",
                    "args": {"command": "npm test"},
                    "result": {"receipt": result} if receipt_nested else result,
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

    def test_successful_full_trust_test_uses_server_terminal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _runtime = _service(
                tmp,
                _snapshot(sandboxed=False, receipt_nested=True),
                _repair_trace(),
            )

            evidence = service.record_trace_repair_test_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": REPAIR_TRACE_ID,
                }
            )["evidence"]

            self.assertEqual(evidence["testStatus"], "passed")
            self.assertEqual(evidence["evidence"]["sandboxedCount"], 0)
            self.assertFalse(evidence["evidence"]["sandboxRequired"])
            self.assertEqual(evidence["evidence"]["sessionTerminalCount"], 1)

    def test_only_completed_test_executions_after_the_last_change_are_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(sandboxed=False, receipt_nested=True)
            failed_before = json.loads(json.dumps(snapshot["liveEvents"][0]))
            failed_before["sequence"] = 10
            failed_before["payload"]["toolCallId"] = "call:failed-before"
            failed_before["payload"]["result"]["receipt"]["exitCode"] = 1
            failed_before["payload"]["isError"] = True
            edit = json.loads(json.dumps(snapshot["liveEvents"][1]))
            edit["sequence"] = 20
            edit["payload"]["toolCallId"] = "call:edit"
            passed_start = {
                "eventType": "tool_started",
                "eventId": "event:test-start",
                "sequence": 29,
                "payload": {
                    "toolCallId": "call:passed",
                    "toolName": "bash",
                    "args": {"command": "npm test"},
                },
            }
            passed = json.loads(json.dumps(snapshot["liveEvents"][0]))
            passed["sequence"] = 30
            passed["payload"]["toolCallId"] = "call:passed"
            passed["payload"]["args"] = {}
            transport_start = {
                **passed_start,
                "eventId": "event:transport-start",
                "sequence": 39,
                "payload": {
                    **passed_start["payload"],
                    "toolCallId": "call:transport-failure",
                },
            }
            transport_failure = {
                "eventType": "tool_finished",
                "eventId": "event:transport-failure",
                "sequence": 40,
                "payload": {
                    "toolCallId": "call:transport-failure",
                    "toolName": "bash",
                    "args": {},
                    "result": {},
                    "isError": True,
                },
            }
            snapshot["liveEvents"] = [
                failed_before,
                edit,
                passed_start,
                passed,
                transport_start,
                transport_failure,
            ]
            service, _runtime = _service(tmp, snapshot, _repair_trace())

            evidence = service.record_trace_repair_test_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": REPAIR_TRACE_ID,
                }
            )["evidence"]

            self.assertEqual(evidence["testStatus"], "passed")
            self.assertEqual(evidence["evidence"]["failedCount"], 0)
            self.assertEqual(evidence["evidence"]["passedCount"], 1)
            self.assertEqual(evidence["evidence"]["signalIds"], ["call:passed"])

    def test_timed_out_test_receipt_is_an_executed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(sandboxed=False, receipt_nested=True)
            edit = json.loads(json.dumps(snapshot["liveEvents"][1]))
            edit["sequence"] = 20
            test_start = {
                "eventType": "tool_started",
                "eventId": "event:timeout-start",
                "sequence": 29,
                "payload": {
                    "toolCallId": "call:timeout",
                    "toolName": "bash",
                    "args": {"command": "npm test"},
                },
            }
            timed_out = json.loads(json.dumps(snapshot["liveEvents"][0]))
            timed_out["sequence"] = 30
            timed_out["payload"]["toolCallId"] = "call:timeout"
            timed_out["payload"]["args"] = {}
            receipt = timed_out["payload"]["result"]["receipt"]
            receipt["exitCode"] = 0
            receipt["timedOut"] = True
            receipt["ok"] = False
            timed_out["payload"]["isError"] = False
            snapshot["liveEvents"] = [edit, test_start, timed_out]
            service, _runtime = _service(tmp, snapshot, _repair_trace())

            evidence = service.record_trace_repair_test_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": REPAIR_TRACE_ID,
                }
            )["evidence"]

            self.assertEqual(evidence["testStatus"], "failed")
            self.assertEqual(evidence["evidence"]["failedCount"], 1)
            self.assertEqual(evidence["evidence"]["passedCount"], 0)
            self.assertEqual(evidence["evidence"]["signalIds"], ["call:timeout"])

    def test_terminal_repair_turn_materializes_a_privacy_safe_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            turn_id = "turn-repair-1"
            trace_id = f"trace:turn:{turn_id}"
            snapshot = _snapshot(sandboxed=False)
            snapshot["items"] = [
                {
                    "id": "history:assistant",
                    "turnId": "history:user",
                    "role": "assistant",
                    "status": "completed",
                    "createdAtMs": 20,
                    "completedAtMs": 20,
                }
            ]
            service, _runtime = _service(
                tmp,
                snapshot,
                None,
                terminal_turn_id=turn_id,
            )

            evidence = service.record_trace_repair_test_evidence(
                {
                    "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                    "repairSessionId": SESSION_ID,
                    "repairTraceId": trace_id,
                }
            )["evidence"]

            self.assertEqual(evidence["testStatus"], "passed")
            persisted = service.trace_store.get(trace_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["sourceKind"], "agent_repair")
            self.assertEqual(
                persisted["binding"],
                {"sessionId": SESSION_ID, "turnId": turn_id},
            )
            self.assertEqual(persisted["status"], "completed")
            self.assertEqual(persisted["createdAtMs"], 25)
            self.assertEqual(persisted["updatedAtMs"], 25)

    def test_repair_turn_trace_requires_a_durable_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _runtime = _service(
                tmp,
                _snapshot(sandboxed=False, turn_id="requested-turn"),
                None,
            )
            with self.assertRaises(TraceRepairValidationError):
                service.record_trace_repair_test_evidence(
                    {
                        "schemaVersion": "rag-ime.trace-repair-test-evidence.v1",
                        "repairSessionId": SESSION_ID,
                        "repairTraceId": "trace:turn:requested-turn",
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

    def test_receipt_freezes_an_observation_backed_source_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, _runtime = _service(
                tmp,
                _snapshot(),
                _repair_trace(),
                persist_source_trace=False,
            )
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
            projected_source = build_trace_envelope(
                trace_id=SOURCE_TRACE_ID,
                source_kind="memory",
                input_text="source",
                binding={"sessionId": "session:source"},
                status="completed",
                now_ms=1,
            ).to_dict()
            service.observation_trace = lambda _payload: {
                "trace": projected_source
            }
            with self.assertRaisesRegex(
                TraceRepairValidationError,
                "source trace binding does not match sourceScope",
            ):
                service.create_trace_repair_receipt(
                    {
                        "schemaVersion": "rag-ime.trace-repair-receipt-create.v1",
                        "sourceScope": "session:session:other",
                        "sourceTraceId": SOURCE_TRACE_ID,
                        "failureRef": "failure:observation",
                        "changeReceiptId": change["evidenceId"],
                        "testEvidenceId": test["evidenceId"],
                        "repairTraceId": REPAIR_TRACE_ID,
                        "repairSessionId": SESSION_ID,
                    }
                )

            receipt = service.create_trace_repair_receipt(
                {
                    "schemaVersion": "rag-ime.trace-repair-receipt-create.v1",
                    "sourceScope": "session:session:source",
                    "sourceTraceId": SOURCE_TRACE_ID,
                    "failureRef": "failure:observation",
                    "changeReceiptId": change["evidenceId"],
                    "testEvidenceId": test["evidenceId"],
                    "repairTraceId": REPAIR_TRACE_ID,
                    "repairSessionId": SESSION_ID,
                }
            )["receipt"]

            self.assertEqual(receipt["sourceTraceId"], SOURCE_TRACE_ID)
            persisted = service.trace_store.get(SOURCE_TRACE_ID)
            self.assertIsNotNone(persisted)
            self.assertEqual(
                persisted["binding"],
                {"sessionId": "session:source"},
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
