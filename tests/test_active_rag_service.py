from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.active_rag_service import ActiveRagService, ActiveRagStartRequest
from rag_ime.deepseek_completion import CompletionCandidateDelta
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.text_utils import stable_text_hash


class ActiveRagServiceTests(unittest.TestCase):
    def test_active_rag_local_evidence_pack_runs_without_deepseek_flag(self) -> None:
        provider = FakeActiveRagProvider(("DeepSeek不应调用",))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": ""}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls, [])
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["uiMode"], "active_rag_assist")
        self.assertFalse(ready["keyPolicy"]["thinkingRowSelectable"])
        self.assertEqual([item["text"] for item in ready["candidates"]], ["主动候选"])

    def test_active_rag_uses_deepseek_when_enabled(self) -> None:
        provider = FakeActiveRagProvider(("这是原始选区长句", "DeepSeek主动候选"))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="这是原始选区长句，需要被避免复读")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls[0].scene, "active_rag")
        self.assertEqual(ready["status"], "ready")
        self.assertEqual([item["text"] for item in ready["candidates"]], ["主动候选", "DeepSeek主动候选"])
        accepted = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][1]["candidateId"]),
            selected_text_hash=request.selected_text_hash,
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
        )
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["insertText"], "DeepSeek主动候选")

    def test_active_rag_accept_validates_selection_anchor(self) -> None:
        provider = FakeActiveRagProvider(("DeepSeek主动候选",))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        rejected = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][0]["candidateId"]),
            selected_text_hash=stable_text_hash("别的选区"),
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
        )

        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["reason"], "selected_text_hash_mismatch")

    def test_active_rag_accept_validates_panel_and_front_app_when_supplied(self) -> None:
        service = ActiveRagService()
        request = _request(selected_text="选区", panel_session_id="panel-a", front_app_bundle_id="app.a")
        started = service.start(request)
        ready = _wait_ready(service, str(started["sessionId"]))

        rejected_panel = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][0]["candidateId"]),
            selected_text_hash=request.selected_text_hash,
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
            panel_session_id="panel-b",
            front_app_bundle_id="app.a",
        )
        rejected_app = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][0]["candidateId"]),
            selected_text_hash=request.selected_text_hash,
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
            panel_session_id="panel-a",
            front_app_bundle_id="app.b",
        )

        self.assertEqual(rejected_panel["reason"], "panel_session_id_mismatch")
        self.assertEqual(rejected_app["reason"], "front_app_bundle_id_mismatch")

    def test_active_rag_accept_records_feedback_event(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-feedback-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag.sqlite")
            service = ActiveRagService(core=core)
            request = _request(selected_text="选区", panel_session_id="panel-a", front_app_bundle_id="app.a")
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

            accepted = service.accept(
                session_id=str(ready["sessionId"]),
                candidate_id=str(ready["candidates"][0]["candidateId"]),
                selected_text_hash=request.selected_text_hash,
                frontend_revision=request.frontend_revision,
                selection_epoch=request.selection_epoch,
                panel_session_id=request.panel_session_id,
                front_app_bundle_id=request.front_app_bundle_id,
            )
            with core._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT candidate_id, candidate_text, action, context_hash, metadata_json
                    FROM memory_feedback_events
                    ORDER BY id ASC
                    """
                ).fetchall()

        self.assertTrue(accepted["ok"])
        self.assertGreaterEqual(len(rows), 2)
        actions = [row["action"] for row in rows]
        self.assertIn("active_rag_shown", actions)
        self.assertIn("active_rag_accept", actions)
        accept_row = next(row for row in rows if row["action"] == "active_rag_accept")
        self.assertEqual(accept_row["candidate_text"], "主动候选")
        self.assertEqual(accept_row["context_hash"], request.selected_text_hash)
        self.assertIn("panel-a", accept_row["metadata_json"])

    def test_active_rag_cancel_records_feedback_event(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-cancel-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag.sqlite")
            gate = threading.Event()
            provider = BlockingActiveRagProvider(gate)
            service = ActiveRagService(core=core, completion_provider=provider)
            request = ActiveRagStartRequest(
                selected_text="准备取消的选区",
                selected_text_hash=stable_text_hash("准备取消的选区"),
                frontend_revision=9,
                selection_epoch=4,
                panel_session_id="panel-cancel",
                front_app_bundle_id="app.cancel",
            )
            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                cancelled = service.cancel(str(started["sessionId"]))
                gate.set()
            with core._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT action, context_hash, metadata_json
                    FROM memory_feedback_events
                    ORDER BY id ASC
                    """
                ).fetchall()

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual([row["action"] for row in rows], ["active_rag_cancel"])
        self.assertEqual(rows[0]["context_hash"], request.selected_text_hash)
        self.assertIn("panel-cancel", rows[0]["metadata_json"])

    def test_active_rag_deepseek_stale_session_dropped(self) -> None:
        gate = threading.Event()
        provider = BlockingActiveRagProvider(gate)
        service = ActiveRagService(completion_provider=provider)
        first = _request(selected_text="第一段选区", frontend_revision=1, selection_epoch=1)
        second = _request(selected_text="第二段选区", frontend_revision=2, selection_epoch=2)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            first_started = service.start(first)
            second_started = service.start(second)
            first_status = service.status(str(first_started["sessionId"]))
            gate.set()
            second_ready = _wait_ready(service, str(second_started["sessionId"]))

        self.assertEqual(first_status["status"], "stale_dropped")
        self.assertEqual(second_ready["status"], "ready")
        self.assertIn("第二个主动候选", [item["text"] for item in second_ready["candidates"]])


class FakeActiveRagProvider:
    def __init__(self, texts: tuple[str, ...]):
        self.texts = texts
        self.calls: list[object] = []

    def stream_candidates(self, request):
        self.calls.append(request)
        for text in self.texts:
            yield CompletionCandidateDelta(text=text, insert_text=text)


class BlockingActiveRagProvider:
    def __init__(self, gate: threading.Event):
        self.gate = gate
        self.calls: list[object] = []

    def stream_candidates(self, request):
        self.calls.append(request)
        self.gate.wait(timeout=2)
        yield CompletionCandidateDelta(text="第二个主动候选", insert_text="第二个主动候选")


def _request(
    *,
    selected_text: str,
    frontend_revision: int = 7,
    selection_epoch: int = 3,
    panel_session_id: str = "",
    front_app_bundle_id: str = "",
) -> ActiveRagStartRequest:
    return ActiveRagStartRequest(
        selected_text=selected_text,
        selected_text_hash=stable_text_hash(selected_text),
        frontend_revision=frontend_revision,
        selection_epoch=selection_epoch,
        panel_session_id=panel_session_id,
        front_app_bundle_id=front_app_bundle_id,
        context="RAG 输入法主动改写",
        evidence_pack=({"surfaceHints": ["主动候选"], "tags": ["RAG"]},),
    )


def _wait_ready(service: ActiveRagService, session_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 2
    last = service.status(session_id)
    while time.monotonic() < deadline:
        last = service.status(session_id)
        if last["status"] in {"ready", "error", "stale_dropped", "cancelled"}:
            return last
        time.sleep(0.01)
    return last


if __name__ == "__main__":
    unittest.main()
