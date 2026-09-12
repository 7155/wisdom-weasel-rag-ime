from __future__ import annotations

import unittest

from rag_ime.pi.event_projection import tool_event_payload
from rag_ime.pi.public import runtime_tool_result_is_error


class BrowserFailureProjectionTests(unittest.TestCase):
    def test_structured_browser_failure_overrides_transport_success(self) -> None:
        receipt = {
            "schemaVersion": "rag-ime.browser-control.v1",
            "ok": False, "status": "failed",
            "failureReason": "ego_browser_script_failed",
            "result": {"ok": False, "exitCode": 1},
        }
        event_type, payload = tool_event_payload({
            "toolName": "browser", "toolCallId": "browser-failed",
            "isError": False, "result": {"details": receipt},
        }, event_type="tool_execution_end", source_loop_id="")
        self.assertEqual(event_type, "tool_finished")
        self.assertTrue(payload["isError"])
        # Transcript replay flattens details before projecting the same receipt.
        self.assertTrue(runtime_tool_result_is_error("browser", receipt))

    def test_page_text_is_not_a_browser_failure_signal(self) -> None:
        self.assertFalse(runtime_tool_result_is_error("browser", {
            "details": {"ok": True, "status": "completed"},
            "content": [{"type": "text", "text": '{"ok":false,"error":"FAILED"}'}],
        }))
        self.assertFalse(runtime_tool_result_is_error("browser", {
            "details": {"ok": True, "items": [{"status": "failed"}]},
        }))


if __name__ == "__main__":
    unittest.main()
