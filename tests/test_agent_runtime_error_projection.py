from __future__ import annotations

import unittest

from rag_ime.agent_runtime_driver import AgentRuntimeError
from rag_ime.debug_server import _agent_session_runtime_error_payload
from rag_ime.pi_runtime_values import PiRuntimeCommandRejected


class AgentRuntimeErrorProjectionTests(unittest.TestCase):
    def test_internal_and_unknown_host_failures_do_not_blame_inputs_or_replay(self) -> None:
        for code in ("INTERNAL_ERROR", "RUNTIME_REJECTED", "FUTURE_HOST_ERROR"):
            with self.subTest(code=code):
                payload = _agent_session_runtime_error_payload(
                    PiRuntimeCommandRejected(
                        "npm IO failed in /private/user-context with token=secret",
                        host_error_code=code,
                    )
                )
                self.assertEqual(payload["errorCode"], "runtime_operation_failed")
                self.assertEqual(payload["causeCode"], code)
                self.assertFalse(payload["retryable"])
                self.assertEqual(payload["recovery"], {"action": "inspect_result"})
                self.assertIn("结果暂未确认", payload["error"])
                self.assertNotIn("参数", payload["error"])
                self.assertNotIn("temporarily unavailable", payload["error"])
                self.assertNotIn("/private/", str(payload))
                self.assertNotIn("secret", str(payload))

    def test_business_rejection_preserves_host_code_without_claiming_runtime_unavailability(self) -> None:
        for code in (
            "INVALID_PLUGIN_MANIFEST", "INVALID_PI_PACKAGE", "INVALID_PARAMS",
            "PLUGIN_NOT_FOUND", "PLUGIN_DIGEST_MISMATCH",
        ):
            with self.subTest(code=code):
                error = PiRuntimeCommandRejected(
                    "Invalid package in /private/user-context with token=secret",
                    host_error_code=code,
                )
                payload = _agent_session_runtime_error_payload(error)
                self.assertEqual(payload["errorCode"], "runtime_command_rejected")
                self.assertEqual(payload["causeCode"], code)
                self.assertFalse(payload["retryable"])
                self.assertEqual(payload["recovery"], {"action": "review_request"})
                self.assertNotIn("temporarily unavailable", payload["error"])
                self.assertRegex(payload["error"], r"[\u3400-\u9fff]")
                self.assertNotIn("/private/", str(payload))
                self.assertNotIn("secret", str(payload))

    def test_unavailable_runtime_keeps_the_connection_recovery(self) -> None:
        for cause_code in (
            "RUNTIME_NOT_RUNNING", "SESSION_NOT_FOUND", "SESSION_BUSY",
            "ROOM_SESSION_BUSY", "REQUEST_ALREADY_ACTIVE", "SETTLED_TIMEOUT",
            "SETTLEMENT_WAITER_LIMIT", "",
        ):
            with self.subTest(cause_code=cause_code):
                error = (
                    PiRuntimeCommandRejected(
                        "Pi Runtime lifecycle is not ready", host_error_code=cause_code,
                    )
                    if cause_code
                    else AgentRuntimeError("Pi Runtime Host connection failed")
                )
                payload = _agent_session_runtime_error_payload(error)
                self.assertEqual(payload["errorCode"], "session_runtime_unavailable")
                self.assertTrue(payload["retryable"])
                self.assertEqual(payload["recovery"], {"action": "retry"})
                if cause_code:
                    self.assertEqual(payload["causeCode"], cause_code)

    def test_missing_workspace_keeps_its_specific_recovery(self) -> None:
        payload = _agent_session_runtime_error_payload(
            AgentRuntimeError("workspace root does not exist: /private/workspace")
        )
        self.assertEqual(payload["errorCode"], "session_workspace_missing")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["recovery"], {"action": "select_workspace"})
        self.assertNotIn("/private/", str(payload))
