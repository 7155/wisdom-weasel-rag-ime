from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.text_utils import stable_text_hash


class ActiveRagDebugServerTests(unittest.TestCase):
    def test_debug_service_exposes_active_rag_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DebugImeService(
                DebugServerConfig(
                    db_path=Path(temp_dir) / "active-rag-debug.sqlite",
                    seed_if_empty=False,
                )
            )

            started = service.active_rag_start(
                {
                    "selectedText": "选区 RAG 助手显式触发",
                    "frontendRevision": 1,
                    "selectionEpoch": 1,
                    "panelSessionId": "panel-1",
                    "frontAppBundleId": "app.test",
                }
            )
            ready = _wait_ready(service, str(started["sessionId"]))
            cancelled = service.active_rag_cancel({"sessionId": str(started["sessionId"])})

            self.assertEqual(started["status"], "pending")
            self.assertEqual(ready["status"], "ready")
            self.assertEqual(ready["uiMode"], "active_rag_assist")
            self.assertFalse(ready["keyPolicy"]["thinkingRowSelectable"])
            self.assertEqual(cancelled["status"], "ready")

    def test_active_rag_preview_is_read_only_and_redacts_selected_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DebugImeService(
                DebugServerConfig(
                    db_path=Path(temp_dir) / "active-rag-debug.sqlite",
                    seed_if_empty=False,
                )
            )
            selected_text = "这段真实选区只允许显式请求进入后端，不能出现在默认调试响应"

            preview = service.active_rag_preview(
                {
                    "selectedText": selected_text,
                    "frontendRevision": 3,
                    "selectionEpoch": 5,
                    "panelSessionId": "panel-preview",
                    "frontAppBundleId": "app.preview",
                    "evidencePack": [{"surfaceHints": ["主动候选短语"], "tags": ["demo"]}],
                    "maxCandidates": 3,
                }
            )
            with service.core._connect() as conn:
                feedback_count = conn.execute("SELECT COUNT(*) FROM memory_feedback_events").fetchone()[0]

        serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)
        self.assertTrue(preview["ok"])
        self.assertTrue(preview["dryRun"])
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["sessionId"], "active-rag:preview")
        self.assertEqual(feedback_count, 0)
        self.assertNotIn(selected_text, serialized)
        self.assertEqual(preview["selectedTextHash"], stable_text_hash(selected_text))
        self.assertEqual(preview["keyPolicy"]["numberKeys"], "select_candidate_when_ready_else_noop")
        self.assertEqual(preview["keyPolicy"]["tab"], "accept_top_when_ready")


def _wait_ready(service: DebugImeService, session_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 2
    last = service.active_rag_status({"sessionId": session_id})
    while time.monotonic() < deadline:
        last = service.active_rag_status({"sessionId": session_id})
        if last.get("status") in {"ready", "error", "stale_dropped", "cancelled"}:
            return last
        time.sleep(0.01)
    return last


if __name__ == "__main__":
    unittest.main()
