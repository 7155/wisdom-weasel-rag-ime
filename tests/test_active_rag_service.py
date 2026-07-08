from __future__ import annotations

import json
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
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms, stable_text_hash


class ActiveRagServiceTests(unittest.TestCase):
    def test_active_rag_local_evidence_pack_runs_without_deepseek_flag(self) -> None:
        provider = FakeActiveRagProvider(("DeepSeek不应调用",))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": ""}):
            started = service.start(request)
            self.assertGreaterEqual(started["elapsedMs"], 0)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls, [])
        self.assertEqual(ready["status"], "ready")
        self.assertGreaterEqual(ready["elapsedMs"], 0)
        self.assertEqual(ready["pollAfterMs"], 0)
        self.assertEqual(ready["uiMode"], "active_rag_assist")
        self.assertFalse(ready["keyPolicy"]["thinkingRowSelectable"])
        self.assertEqual([item["text"] for item in ready["candidates"]], ["主动候选"])

    def test_active_rag_pending_status_reports_poll_backoff(self) -> None:
        gate = threading.Event()
        provider = BlockingActiveRagProvider(gate)
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            pending = service.status(str(started["sessionId"]))
            gate.set()
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(pending["status"], "pending")
        self.assertGreaterEqual(pending["elapsedMs"], 0)
        self.assertGreater(pending["pollAfterMs"], 0)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["pollAfterMs"], 0)

    def test_active_rag_uses_deepseek_when_enabled(self) -> None:
        provider = FakeActiveRagProvider(("这是原始选区长句", "DeepSeek主动候选"))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="这是原始选区长句，需要被避免复读", max_candidates=2)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls[0].scene, "active_rag")
        self.assertEqual(provider.calls[0].max_chars, 24)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual([item["text"] for item in ready["candidates"]], ["DeepSeek主动候选"])
        self.assertEqual(ready["candidates"][0]["selectionAction"], "commit_side_candidate")
        self.assertEqual(ready["candidates"][0]["candidateOrdinal"], 1)
        self.assertEqual(ready["candidates"][0]["metadata"]["frontendRevision"], request.frontend_revision)
        accepted = service.accept(
            session_id=str(ready["sessionId"]),
            candidate_id=str(ready["candidates"][0]["candidateId"]),
            selected_text_hash=request.selected_text_hash,
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
        )
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["insertText"], "DeepSeek主动候选")

    def test_active_rag_governs_remote_candidate_length(self) -> None:
        provider = FakeActiveRagProvider(("这是一个过长候选，需要缩短，保留关键动作",))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="候选长度治理", max_chars=6)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertLessEqual(len(ready["candidates"][0]["text"]), 6)
        self.assertTrue(ready["candidates"][0]["metadata"]["lengthGoverned"])
        self.assertEqual(ready["candidates"][0]["metadata"]["maxChars"], 6)

    def test_active_rag_governs_local_evidence_length_with_surface_hints(self) -> None:
        service = ActiveRagService()
        request = _request(
            selected_text="本地证据长度治理",
            max_chars=8,
            evidence_pack=(
                {
                    "surfaceHints": ["时间线笔记本", "这是一整段很长的原始 RAG 证据，不应该直接显示给输入法候选框"],
                    "tags": ["RAG"],
                },
            ),
        )

        started = service.start(request)
        ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["candidates"][0]["text"], "时间线笔记本")
        self.assertLessEqual(len(ready["candidates"][0]["text"]), 8)
        self.assertFalse(ready["candidates"][0]["metadata"]["lengthGoverned"])

    def test_active_rag_allows_short_keyword_reuse_but_rejects_exact_selection_echo(self) -> None:
        provider = FakeActiveRagProvider(("DeepSeek 生成按钮和 RAG 记忆上下文", "生成按钮优化"))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="DeepSeek 生成按钮和 RAG 记忆上下文", max_candidates=2)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertEqual([item["text"] for item in ready["candidates"]], ["生成按钮优化"])

    def test_active_rag_deepseek_empty_result_returns_visible_fallback_candidate(self) -> None:
        provider = FakeActiveRagProvider(())
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区", max_candidates=2)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertGreaterEqual(ready["candidateCount"], 1)
        self.assertEqual(ready["candidates"][0]["sourceType"], "model")
        self.assertEqual(ready["candidates"][0]["metadata"]["parseMode"], "request_fallback")
        self.assertNotIn("主动候选", [item["text"] for item in ready["candidates"]])

    def test_active_rag_pending_timeout_returns_visible_fallback_candidate(self) -> None:
        gate = threading.Event()
        provider = BlockingActiveRagProvider(gate)
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="LLM没有输出，现在只要一个框")

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            session_id = str(started["sessionId"])
            with service._lock:
                service._sessions[session_id].created_at_ms -= 16_000
            ready = service.status(session_id)
            gate.set()

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["pollAfterMs"], 0)
        self.assertEqual(ready["candidates"][0]["sourceType"], "model")
        self.assertEqual(ready["candidates"][0]["text"], "修复LLM输出")
        self.assertEqual(ready["candidates"][0]["metadata"]["fallbackReason"], "visible_timeout")

    def test_active_rag_deepseek_prompt_gets_timeline_context_pack(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-timeline-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-timeline.sqlite")
            event_id = _record_timeline_event(core, "主动 DeepSeek 生成按钮进入候选框")
            _insert_timeline_book(core, event_id=event_id)
            provider = FakeActiveRagProvider(("DeepSeek主动候选",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = _request(selected_text="候选框")

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        evidence_pack = provider.calls[0].evidence_pack
        context_packet = provider.calls[0].context_packet
        source_types = [item.get("sourceType") for item in evidence_pack]
        self.assertEqual(ready["status"], "ready")
        self.assertIn("recent_input_context", source_types)
        self.assertIn("daily_book", source_types)
        self.assertTrue(any("DeepSeek 生成" in item.get("surfaceHints", []) for item in evidence_pack))
        self.assertEqual(context_packet["schemaVersion"], "rag-ime.smart-context-packet.v1")
        self.assertEqual(context_packet["currentInput"]["mode"], "active_rag")
        self.assertTrue(context_packet["notebook"]["items"])

    def test_active_rag_local_timeline_candidate_does_not_show_generic_recent_title(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-local-timeline-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-local-timeline.sqlite")
            event_id = _record_timeline_event(core, "LLM 候选需要明确显示模型预测来源")
            _insert_timeline_book(core, event_id=event_id)
            service = ActiveRagService(core=core)
            request = ActiveRagStartRequest(
                selected_text="LLM不显示",
                selected_text_hash=stable_text_hash("LLM不显示"),
                frontend_revision=7,
                selection_epoch=3,
                context="LLM不显示，RAG能命中，并且DeepSeek需要根据笔记本预测",
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=18,
            )
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertGreaterEqual(ready["evidenceCount"], 1)
        self.assertNotEqual(ready["candidates"][0]["text"], "最近输入上下文")

    def test_active_rag_local_issue_request_prefers_model_fallback_over_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-local-fallback-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-local-fallback.sqlite")
            event_id = _record_timeline_event(core, "LLM消失LLM")
            _insert_timeline_book(core, event_id=event_id)
            service = ActiveRagService(core=core)
            request = ActiveRagStartRequest(
                selected_text="LLM不显示",
                selected_text_hash=stable_text_hash("LLM不显示"),
                frontend_revision=7,
                selection_epoch=3,
                context="LLM不显示，RAG能命中，并且DeepSeek需要根据笔记本预测",
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=18,
            )
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["candidates"][0]["sourceType"], "model")
        self.assertEqual(ready["candidates"][0]["text"], "修复LLM显示")
        self.assertNotEqual(ready["candidates"][0]["text"], "LLM消失LLM")

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
                provider.released.wait(timeout=0.2)
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
        self.released = threading.Event()
        self.calls: list[object] = []

    def stream_candidates(self, request):
        self.calls.append(request)
        self.gate.wait(timeout=2)
        self.released.set()
        yield CompletionCandidateDelta(text="第二个主动候选", insert_text="第二个主动候选")


def _record_timeline_event(core: LocalSqliteCoreClient, text: str) -> int:
    memory_id = core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source="manual",
            committed_text=text,
            recent_context="Active RAG 前台验收",
            project="wisdom-weasel-rag-ime",
            tags=("RAG", "DeepSeek"),
        )
    )
    return int(str(memory_id).split(":", 1)[1])


def _insert_timeline_book(core: LocalSqliteCoreClient, *, event_id: int) -> None:
    core.initialize()
    timestamp = now_ms()
    with core._connect() as conn:
        conn.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json, query_expansions_json,
                source_event_ids_json, memory_atom_ids_json, status, confidence,
                quality_score, created_at_ms, updated_at_ms, metadata_json
            )
            VALUES (?, 'daily', '2026-07-07', ?, ?, ?, ?, '', ?, ?, ?, ?, '[]', 'active', 0.8, 0.8, ?, ?, '{}')
            """,
            (
                "book:daily:active-rag",
                "Active RAG 时间线",
                "用户希望 RAG 先做 evidence，再由 DeepSeek 生成一条可确认候选。",
                "active rag timeline deepseek",
                "wisdom-weasel-rag-ime",
                json.dumps(["RAG", "DeepSeek"], ensure_ascii=False),
                json.dumps(["DeepSeek 生成", "主动候选"], ensure_ascii=False),
                json.dumps(["Active RAG", "候选框"], ensure_ascii=False),
                json.dumps([event_id], ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )


def _request(
    *,
    selected_text: str,
    frontend_revision: int = 7,
    selection_epoch: int = 3,
    panel_session_id: str = "",
    front_app_bundle_id: str = "",
    max_candidates: int = 1,
    max_chars: int = 24,
    evidence_pack: tuple[dict[str, object], ...] | None = None,
) -> ActiveRagStartRequest:
    return ActiveRagStartRequest(
        selected_text=selected_text,
        selected_text_hash=stable_text_hash(selected_text),
        frontend_revision=frontend_revision,
        selection_epoch=selection_epoch,
        panel_session_id=panel_session_id,
        front_app_bundle_id=front_app_bundle_id,
        context="RAG 输入法主动改写",
        evidence_pack=evidence_pack or ({"surfaceHints": ["主动候选"], "tags": ["RAG"]},),
        max_candidates=max_candidates,
        max_chars=max_chars,
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
