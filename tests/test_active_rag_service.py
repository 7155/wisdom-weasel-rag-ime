from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.active_rag_service import ACTIVE_RAG_DEFAULT_MAX_CHARS, ActiveRagService, ActiveRagStartRequest
from rag_ime.deepseek_completion import CompletionCandidateDelta, DeepSeekCompletionError, build_deepseek_completion_messages
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms, stable_text_hash


class ActiveRagServiceTests(unittest.TestCase):
    def test_sensitive_field_is_blocked_before_hash_validation_retrieval_and_remote(self) -> None:
        provider = FakeActiveRagProvider(("绝不应该调用",))
        service = ActiveRagService(completion_provider=provider)
        secret = "账号 user@example.test 密码 swordfish"
        request = ActiveRagStartRequest(
            selected_text=secret,
            selected_text_hash="frontend-supplied-secret-hash-must-not-return",
            frontend_revision=9,
            selection_epoch=2,
            context=secret,
            secure_input=True,
            evidence_pack=({"surfaceHints": ["绝不应该召回"]},),
            remote_model_allowed=True,
        )

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            blocked = service.start(request)
            status = service.status(str(blocked["sessionId"]))
            diagnostics = service.diagnostics(str(blocked["sessionId"]))

        blob = json.dumps(blocked, ensure_ascii=False)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["error"], "sensitive_field_blocked")
        self.assertEqual(blocked["selectedTextHash"], "")
        self.assertEqual(blocked["candidateCount"], 0)
        self.assertEqual(blocked["candidates"], [])
        self.assertFalse(blocked["diagnostics"]["retrieval"]["called"])
        self.assertFalse(blocked["diagnostics"]["remoteModel"]["requested"])
        self.assertEqual(blocked["diagnostics"]["remoteModel"]["skipReason"], "sensitive_field_blocked")
        self.assertEqual(provider.calls, [])
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(diagnostics["status"], "blocked")
        self.assertNotIn(secret, blob)
        self.assertNotIn("frontend-supplied-secret-hash", blob)
        self.assertNotIn("sha256:", blob)

    def test_sensitive_text_guard_blocks_credential_words_even_without_secure_flag(self) -> None:
        service = ActiveRagService()
        secret = "请保存 API key sk-example-secret"
        request = ActiveRagStartRequest(
            selected_text=secret,
            selected_text_hash=stable_text_hash(secret),
            frontend_revision=1,
            selection_epoch=1,
            context=secret,
            sensitive_text_guard_enabled=False,
        )

        blocked = service.preview(request, local_only=True)

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["evidenceCount"], 0)
        self.assertEqual(blocked["candidateCount"], 0)
        self.assertNotIn(secret, json.dumps(blocked, ensure_ascii=False))

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

    def test_active_rag_publishes_unselectable_partial_stream_before_ready(self) -> None:
        provider = StreamingActiveRagProvider()
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区", max_chars=120)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            self.assertTrue(provider.emitted.wait(timeout=1))
            pending = service.status(str(started["sessionId"]))
            provider.release.set()
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(pending["status"], "pending")
        self.assertFalse(pending["keyPolicy"]["ready"])
        self.assertEqual(pending["candidates"][0]["text"], "第一段正在流式返回")
        self.assertTrue(pending["candidates"][0]["metadata"]["streamingPartial"])
        self.assertTrue(pending["diagnostics"]["modelRequest"]["partialVisible"])
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["candidates"][0]["text"], "第一段已经完整返回")
        self.assertEqual(
            pending["candidates"][0]["candidateStableId"],
            ready["candidates"][0]["candidateStableId"],
        )

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

    def test_active_rag_default_deepseek_budget_is_paragraph_length(self) -> None:
        paragraph = "我会把 DeepSeek 主动生成和 LLM 预测显示拆成两条稳定链路，让显式触发时输出一段完整正文。"
        provider = FakeActiveRagProvider((paragraph,))
        service = ActiveRagService(completion_provider=provider)
        request = ActiveRagStartRequest(
            selected_text="DeepSeek 输出我希望是一段话",
            selected_text_hash=stable_text_hash("DeepSeek 输出我希望是一段话"),
            frontend_revision=7,
            selection_epoch=3,
            context="Ctrl+Enter不行，DeepSeek没输出，LLM不显示",
        )

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(provider.calls[0].max_chars, ACTIVE_RAG_DEFAULT_MAX_CHARS)
        self.assertEqual(ready["status"], "ready")
        self.assertGreaterEqual(len(ready["candidates"][0]["text"]), 40)
        self.assertLessEqual(len(ready["candidates"][0]["text"]), ACTIVE_RAG_DEFAULT_MAX_CHARS)

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

    def test_active_rag_deepseek_empty_result_returns_retriable_error_without_fake_candidate(self) -> None:
        provider = FakeActiveRagProvider(())
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="选区", max_candidates=2)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "error")
        self.assertEqual(ready["candidateCount"], 0)
        self.assertEqual(ready["candidates"][0]["sourceType"], "status")
        self.assertEqual(ready["candidates"][0]["text"], "生成失败，请重试")
        self.assertEqual(ready["candidates"][0]["insertText"], "")
        self.assertNotIn("request_fallback", json.dumps(ready, ensure_ascii=False))
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(ready["diagnostics"]["modelRequest"]["contentRetryAttempted"])
        self.assertFalse(ready["diagnostics"]["modelRequest"]["contentRetryCompleted"])

    def test_active_rag_retries_once_without_rag_when_first_result_is_empty(self) -> None:
        provider = SequencedActiveRagProvider(((), ("重新依据当前请求生成可用正文",)))
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="检查当前请求和RAG拼接", max_chars=120)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["candidates"][0]["text"], "重新依据当前请求生成可用正文")
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(provider.calls[0].evidence_pack)
        self.assertEqual(provider.calls[1].evidence_pack, ())
        self.assertTrue(provider.calls[1].recovery_mode)
        self.assertEqual(provider.calls[1].selected_text, request.selected_text)
        self.assertTrue(ready["diagnostics"]["modelRequest"]["contentRetryCompleted"])

    def test_active_rag_failed_recovery_keeps_retry_diagnostics(self) -> None:
        provider = FailingActiveRagProvider()
        service = ActiveRagService(completion_provider=provider)
        request = _request(selected_text="改正", max_chars=120)

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        model_request = ready["diagnostics"]["modelRequest"]
        self.assertEqual(ready["status"], "error")
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(provider.calls[1].recovery_mode)
        self.assertEqual(provider.calls[1].selected_text, "")
        self.assertTrue(model_request["contentRetryAttempted"])
        self.assertFalse(model_request["contentRetryCompleted"])
        self.assertIn(
            "deepseek_context_only_retry_started",
            [item["name"] for item in ready["traceEvents"]],
        )

    def test_active_rag_uses_fresh_context_when_semantic_anchor_is_stale(self) -> None:
        provider = FakeActiveRagProvider(("使用当前输入重新构建查询并过滤旧锚点",))
        service = ActiveRagService(completion_provider=provider)
        stale = "上一轮已经失效的请求"
        current = "现在需要检查上下文构建逻辑，避免空结果被直接输出。"
        request = ActiveRagStartRequest(
            selected_text=stale,
            selected_text_hash=stable_text_hash(stale),
            frontend_revision=12,
            selection_epoch=8,
            placement="insert_after_selection",
            intent="answer",
            context=current,
            max_chars=120,
        )

        with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
            started = service.start(request)
            ready = _wait_ready(service, str(started["sessionId"]))

        payload = json.loads(build_deepseek_completion_messages(provider.calls[0])[1]["content"])
        self.assertEqual(ready["status"], "ready")
        self.assertIn("避免空结果", payload["currentRequest"])
        self.assertNotEqual(payload["currentRequest"], stale)
        self.assertEqual(
            ready["diagnostics"]["contextInjection"]["resolvedRequestChars"],
            len(payload["currentRequest"]),
        )

    def test_active_rag_pending_timeout_returns_pinned_retriable_error(self) -> None:
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

        self.assertEqual(ready["status"], "error")
        self.assertEqual(ready["pollAfterMs"], 0)
        self.assertEqual(ready["candidateCount"], 0)
        self.assertEqual(ready["candidates"][0]["sourceType"], "status")
        self.assertEqual(ready["candidates"][0]["text"], "生成失败，请重试")
        self.assertIn("visible_timeout", ready["error"])

    def test_active_rag_deepseek_prompt_gets_timeline_context_pack(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-timeline-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-timeline.sqlite")
            event_id = _record_timeline_event(core, "主动 DeepSeek 生成按钮进入候选框")
            _insert_timeline_book(core, event_id=event_id)
            provider = FakeActiveRagProvider(("DeepSeek主动候选",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = _request(selected_text="主动候选")

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        evidence_pack = provider.calls[0].evidence_pack
        context_packet = provider.calls[0].context_packet
        source_types = [item.get("sourceType") for item in evidence_pack]
        self.assertEqual(ready["status"], "ready")
        self.assertNotIn("recent_input_context", source_types)
        self.assertTrue(any(source_type in {"daily_book", "memory"} for source_type in source_types))
        self.assertTrue(
            any(
                "DeepSeek" in " ".join(
                    [str(item.get("evidencePreview") or ""), *(str(value) for value in item.get("surfaceHints", []))]
                )
                for item in evidence_pack
            )
        )
        self.assertEqual(context_packet["schemaVersion"], "rag-ime.smart-context-packet.v1")
        self.assertEqual(context_packet["currentInput"]["mode"], "active_rag")
        self.assertTrue(context_packet["notebook"]["items"])
        diagnostics = ready["diagnostics"]
        self.assertTrue(diagnostics["contextInjection"]["applied"])
        self.assertGreater(diagnostics["contextInjection"]["contextChars"], 0)
        self.assertTrue(str(diagnostics["contextInjection"]["contextHash"]).startswith("sha256:"))
        self.assertGreaterEqual(diagnostics["retrieval"]["evidenceCount"], 1)
        self.assertGreaterEqual(diagnostics["retrieval"]["contextEvidenceCount"], 1)
        self.assertTrue(diagnostics["retrieval"]["lanes"])
        self.assertTrue(diagnostics["remoteModel"]["allowed"])
        self.assertEqual(diagnostics["remoteModel"]["provider"], "deepseek")
        self.assertGreaterEqual(diagnostics["remoteModel"]["elapsedMs"], 0)
        trace_names = [item["name"] for item in ready["traceEvents"]]
        self.assertIn("deepseek_request_context_built", trace_names)
        self.assertIn("deepseek_request_completed", trace_names)

    def test_active_rag_keeps_short_foreground_context_primary_over_recent_voice_tail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-voice-context-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-voice-context.sqlite")
            foreground = "前台上下文只有十五个字"
            voice_text = (
                "这是一次很长的语音输入，前面讨论了模型训练、候选窗口、流式识别和记忆整理，"
                "用户最后真正关心的是当前输入能否完整进入生成请求。" + foreground
            )
            _record_timeline_event(core, voice_text)
            provider = FakeActiveRagProvider(("近期语音输入已进入当前生成上下文",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = ActiveRagStartRequest(
                selected_text=foreground,
                selected_text_hash=stable_text_hash(foreground),
                frontend_revision=11,
                selection_epoch=5,
                context=foreground,
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=120,
            )

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        sent_context = provider.calls[0].current_context
        injection = ready["diagnostics"]["contextInjection"]
        self.assertEqual(sent_context, foreground)
        self.assertEqual(injection["foregroundContextChars"], len(foreground))
        self.assertEqual(injection["effectiveContextChars"], injection["foregroundContextChars"])
        self.assertFalse(injection["augmentedWithTimelineRecentInput"])
        self.assertFalse(injection["timelineRecentInputUsedForGeneration"])
        self.assertEqual(injection["contextPolicy"], "foreground_first")
        self.assertNotIn("timeline_recent_input", injection["source"])
        self.assertNotIn("recent_input_context", [item.get("sourceType") for item in provider.calls[0].evidence_pack])

    def test_active_rag_short_unmatched_foreground_does_not_promote_recent_request(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-short-context-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-short-context.sqlite")
            recent = "请完成上下文构建、空结果恢复和前台诊断的全部修复。"
            _record_timeline_event(core, recent)
            provider = FakeActiveRagProvider(("已完成短上下文恢复链路修复",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = ActiveRagStartRequest(
                selected_text="改正",
                selected_text_hash=stable_text_hash("改正"),
                frontend_revision=15,
                selection_epoch=9,
                placement="insert_after_selection",
                intent="complete",
                context="改正",
                surrounding_before="改正",
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=120,
            )

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        payload = json.loads(build_deepseek_completion_messages(provider.calls[0])[1]["content"])
        injection = ready["diagnostics"]["contextInjection"]
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(provider.calls[0].current_context, "改正")
        self.assertEqual(payload["currentRequest"], "改正")
        self.assertTrue(injection["shortForegroundCapture"])
        self.assertFalse(injection["fullForegroundDocumentCaptured"])
        self.assertEqual(injection["resolvedRequestChars"], len("改正"))
        self.assertGreater(injection["timelineRecentInputChars"], len("改正"))
        self.assertFalse(injection["timelineRecentInputUsedForGeneration"])

    def test_generic_foreground_terms_do_not_turn_timeline_book_into_rag_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-generic-timeline-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-generic-timeline.sqlite")
            event_id = _record_timeline_event(core, "前台上下文测试需要稳定显示当前输入内容")
            _insert_timeline_book(core, event_id=event_id)
            with core._connect() as conn:
                conn.execute(
                    """
                    UPDATE memory_books
                    SET title = ?, summary = ?, normalized_text = ?,
                        tags_json = ?, surface_hints_json = ?
                    WHERE book_id = 'book:daily:active-rag'
                    """,
                    (
                        "前台上下文运行记录",
                        "当前前台上下文测试需要稳定显示输入内容。",
                        "当前 前台 上下文 测试 输入 内容",
                        json.dumps(["前台", "上下文"], ensure_ascii=False),
                        json.dumps(["前台上下文", "当前测试"], ensure_ascii=False),
                    ),
                )
            provider = FakeActiveRagProvider(("只依据鹤白螺钉九三当前输入",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = ActiveRagStartRequest(
                selected_text="鹤白螺钉九三用于当前前台上下文测试",
                selected_text_hash=stable_text_hash("鹤白螺钉九三用于当前前台上下文测试"),
                frontend_revision=17,
                selection_epoch=11,
                context="鹤白螺钉九三用于当前前台上下文测试",
                surrounding_before="鹤白螺钉九三用于当前前台上下文测试",
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=120,
            )

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["diagnostics"]["retrieval"]["evidenceCount"], 0)
        self.assertEqual(provider.calls[0].evidence_pack, ())
        self.assertFalse(ready["diagnostics"]["contextInjection"]["timelineRecentInputUsedForGeneration"])

    def test_active_rag_short_commit_observes_but_does_not_inject_recent_field_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-short-commit-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-short-commit.sqlite")
            recent = "请检查当前前台上下文是否完整注入，并在证据为空时明确降级。"
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="squirrel",
                    committed_text="改正",
                    privacy_disposition="allowed",
                    recent_context=recent,
                    project="wisdom-weasel-rag-ime",
                    tags=("user-input",),
                )
            )
            provider = FakeActiveRagProvider(("已修复短提交上下文恢复",))
            service = ActiveRagService(core=core, completion_provider=provider)
            request = ActiveRagStartRequest(
                selected_text="改正",
                selected_text_hash=stable_text_hash("改正"),
                frontend_revision=16,
                selection_epoch=10,
                placement="insert_after_selection",
                intent="complete",
                context="改正",
                surrounding_before="改正",
                project="wisdom-weasel-rag-ime",
                max_candidates=1,
                max_chars=120,
            )

            with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                started = service.start(request)
                ready = _wait_ready(service, str(started["sessionId"]))

        payload = json.loads(build_deepseek_completion_messages(provider.calls[0])[1]["content"])
        injection = ready["diagnostics"]["contextInjection"]
        self.assertEqual(provider.calls[0].current_context, "改正")
        self.assertEqual(payload["currentRequest"], "改正")
        self.assertGreater(injection["timelineRecentInputChars"], len("改正"))
        self.assertEqual(injection["resolvedRequestChars"], len("改正"))
        self.assertFalse(injection["timelineRecentInputUsedForGeneration"])

    def test_active_rag_local_timeline_candidate_does_not_show_generic_recent_title(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-local-timeline-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-local-timeline.sqlite")
            event_id = _record_timeline_event(core, "LLM 候选需要明确显示模型预测来源")
            _insert_timeline_book(core, event_id=event_id)
            service = ActiveRagService(core=core)
            request = ActiveRagStartRequest(
                selected_text="主动候选",
                selected_text_hash=stable_text_hash("主动候选"),
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

    def test_active_rag_local_issue_request_never_impersonates_remote_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-local-fallback-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag-local-fallback.sqlite")
            event_id = _record_timeline_event(core, "LLM消失LLM")
            _insert_timeline_book(core, event_id=event_id)
            service = ActiveRagService(core=core)
            request = ActiveRagStartRequest(
                selected_text="主动候选",
                selected_text_hash=stable_text_hash("主动候选"),
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
        self.assertEqual(ready["candidates"][0]["sourceType"], "memory")
        self.assertTrue(ready["candidates"][0]["text"])
        self.assertNotEqual(ready["candidates"][0]["text"], "修复LLM显示")
        self.assertNotIn("request_fallback", json.dumps(ready, ensure_ascii=False))

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


class SequencedActiveRagProvider:
    def __init__(self, responses: tuple[tuple[str, ...], ...]):
        self.responses = responses
        self.calls: list[object] = []

    def stream_candidates(self, request):
        call_index = len(self.calls)
        self.calls.append(request)
        texts = self.responses[min(call_index, len(self.responses) - 1)]
        for text in texts:
            yield CompletionCandidateDelta(text=text, insert_text=text)


class FailingActiveRagProvider:
    def __init__(self):
        self.calls: list[object] = []

    def stream_candidates(self, request):
        self.calls.append(request)
        raise DeepSeekCompletionError("active_rag_no_insertable_content:governor_rejected_content")
        yield


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


class StreamingActiveRagProvider:
    supports_text_delta_callback = True

    def __init__(self):
        self.emitted = threading.Event()
        self.release = threading.Event()

    def stream_candidates(self, request, *, on_text_delta=None):
        _ = request
        if on_text_delta is not None:
            on_text_delta("第一段正在流式返回")
        self.emitted.set()
        self.release.wait(timeout=2)
        yield CompletionCandidateDelta(text="第一段已经完整返回", insert_text="第一段已经完整返回")


def _record_timeline_event(core: LocalSqliteCoreClient, text: str) -> int:
    memory_id = core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source="manual",
            committed_text=text,
            privacy_disposition="allowed",
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
