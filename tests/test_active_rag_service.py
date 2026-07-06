from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

from rag_ime.active_rag_service import ActiveRagService, ActiveRagStartRequest
from rag_ime.deepseek_completion import CompletionCandidateDelta
from rag_ime.text_utils import stable_text_hash


class ActiveRagServiceTests(unittest.TestCase):
    def test_active_rag_uses_deepseek_when_enabled(self) -> None:
        provider = FakeActiveRagProvider(("这是原始选区长句", "DeepSeek主动候选"))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="这是原始选区长句，需要被避免复读")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls[0].scene, "active_rag")
        self.assertEqual(ready["status"], "ready")
        self.assertEqual([item["text"] for item in ready["candidates"]], ["DeepSeek主动候选"])
        accepted = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][0]["candidateId"]),
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
        self.assertEqual(second_ready["candidates"][0]["text"], "第二个主动候选")


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
) -> ActiveRagStartRequest:
    return ActiveRagStartRequest(
        selected_text=selected_text,
        selected_text_hash=stable_text_hash(selected_text),
        frontend_revision=frontend_revision,
        selection_epoch=selection_epoch,
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
