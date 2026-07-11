from __future__ import annotations

import tempfile
import threading
import unittest
import json
import os
import subprocess
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.predictor_latency import PredictorLatencyTrace, append_latency_trace
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.knowledge_workbench import KnowledgeGenerationResult, KnowledgeWorkbenchRequest
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.memory_book_compiler import memory_book_plan_from_compile_output, store_memory_book_plan
from rag_ime.models import InputEvent, MemoryAction, ModelPrediction
from rag_ime.predictor import OpenAICompatiblePredictionConfig
from rag_ime.retrieval_docs import rebuild_retrieval_docs


class _ManagementPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        text = f"{current_input}候选" if current_input else "继续完善候选栏展示"
        return [
            ModelPrediction(
                text=text,
                rank=1,
                provider_name="test-local-model",
                latency_ms=3,
                confidence=0.82,
                metadata={"prompt": recent_context, "reason": "test"},
            )
        ][:max_candidates]


class _CapabilityProbePredictionProvider(_ManagementPredictionProvider):
    config = OpenAICompatiblePredictionConfig(
        base_url="http://127.0.0.1:8767",
        model="probe-model",
        provider_name="local-mlx",
        profile="qwen3_06b_ime_hot",
    )

    def __init__(self) -> None:
        self.probe_calls = 0

    def capability_probe(self) -> dict[str, object]:
        self.probe_calls += 1
        return {
            "ok": True,
            "providerName": "local-mlx",
            "model": "/models/minimind-ime-v3",
            "modelFingerprint": "sha256:" + "b" * 64,
            "capabilities": {"streaming": True, "serverTiming": True},
            "promptCache": {"enabled": False},
        }


class _WarmupEmbeddingProvider:
    fingerprint = "mlx-bert:test-q8:cfg-test"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed(self, text: str) -> list[float]:
        return self.embed_query(text)

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.25, 0.75]


class _KnowledgeGenerator:
    ready = True

    def generate(self, request, *, evidence, notion_answer="", notion_sources=None):
        _ = request, evidence, notion_sources
        return KnowledgeGenerationResult(
            answer="本地知识答案" if not notion_answer else f"已合并：{notion_answer}",
            elapsed_ms=5,
            model="deepseek-test",
            prompt_diagnostics={"success": True, "notionIncluded": bool(notion_answer)},
        )


class DebugManagementApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._pinyin_env_keys = (
            "RAG_IME_PINYIN_FUZZY_ENABLED",
            "RAG_IME_PINYIN_FUZZY_PROFILE",
            "RAG_IME_PINYIN_FUZZY_Z_ZH",
            "RAG_IME_PINYIN_FUZZY_C_CH",
            "RAG_IME_PINYIN_FUZZY_S_SH",
            "RAG_IME_PINYIN_FUZZY_EN_ENG",
            "RAG_IME_PINYIN_FUZZY_IN_ING",
            "RAG_IME_PINYIN_FUZZY_ONG_ON",
            "RAG_IME_PINYIN_FUZZY_N_L",
            "RAG_IME_PINYIN_FUZZY_F_H",
        )
        self._pinyin_env = {key: os.environ.get(key) for key in self._pinyin_env_keys}
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-debug-management-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                seed_if_empty=False,
                predictor=_ManagementPredictionProvider(),
            )
        )

    def tearDown(self) -> None:
        for key, value in self._pinyin_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_candidate_explain_returns_ranking_reasons(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_001,
                source="manual",
                committed_text="候选解释需要展示排序原因",
                privacy_disposition="allowed",
                recent_context="RAG 输入法管理界面",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )

        report = self.service.candidate_explain({"query": "候选解释", "recentContext": "管理界面", "topK": 3})

        self.assertTrue(report["ok"])
        self.assertEqual(report["schemaVersion"], "rag-ime.management-candidate-explain.v1")
        self.assertTrue(report["queryHash"].startswith("sha256:"))
        self.assertGreaterEqual(len(report["candidates"]), 1)
        first = report["candidates"][0]
        self.assertIn("sourceType", first)
        self.assertIn("score", first)
        self.assertIn("reason", first)

    def test_local_mlx_embedding_is_warmed_before_health_becomes_ready(self) -> None:
        provider = _WarmupEmbeddingProvider()
        with tempfile.TemporaryDirectory(prefix="rag-ime-embedding-warmup-") as tmp:
            with patch("rag_ime.debug_server.embedding_provider_from_env", return_value=provider):
                service = DebugImeService(
                    DebugServerConfig(
                        db_path=Path(tmp) / "warmup.sqlite",
                        seed_if_empty=False,
                        predictor=_ManagementPredictionProvider(),
                    )
                )
                report = service.health()["embeddingWarmup"]

        self.assertTrue(report["enabled"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["dimensions"], 2)
        self.assertEqual(provider.queries, ["输入法语义检索预热"])

    def test_predictor_status_reports_cache_capabilities(self) -> None:
        provider = _CapabilityProbePredictionProvider()
        self.service.predictor = provider

        status = self.service.predictor_status()
        cached = self.service.predictor_status()
        forced = self.service.model_probe({})

        self.assertTrue(status["ok"])
        self.assertIn("predictor", status)
        self.assertIn("capabilities", status["predictor"])
        self.assertEqual(provider.probe_calls, 2)
        self.assertFalse(status["predictor"]["statusCache"]["hit"])
        self.assertTrue(cached["predictor"]["statusCache"]["hit"])
        self.assertFalse(forced["predictor"]["statusCache"]["hit"])

        runtime = self.service.management.runtime_status()
        detail = runtime["components"]["predictor"]["detail"]
        self.assertIn("minimind-ime-v3", detail)
        self.assertIn("bbbbbbbbbbbb", detail)

    def test_pinyin_settings_apply_to_runtime_env_immediately(self) -> None:
        result = self.service.settings_update(
            {
                "pinyin.fuzzyProfile": "none",
                "pinyin.rerankUsesFuzzy": False,
                "pinyin.pairs.sSh": False,
                "pinyin.pairs.nL": True,
            }
        )
        health = self.service.health()

        self.assertTrue(result["ok"])
        self.assertEqual(os.environ["RAG_IME_PINYIN_FUZZY_ENABLED"], "0")
        self.assertEqual(os.environ["RAG_IME_PINYIN_FUZZY_PROFILE"], "none")
        self.assertEqual(os.environ["RAG_IME_PINYIN_FUZZY_S_SH"], "0")
        self.assertEqual(os.environ["RAG_IME_PINYIN_FUZZY_N_L"], "1")
        self.assertFalse(health["pinyinRuntime"]["fuzzyEnabled"])

    def test_predictor_latency_api_redacts_prompt_text(self) -> None:
        trace_path = Path(self.tmp.name) / "predictor-latency.jsonl"
        append_latency_trace(
            {
                "requestId": "req-1",
                "requestType": "ime_hot",
                "firstCandidateMs": 12,
                "totalMs": 18,
                "prompt": "secret prompt",
                "rawText": "secret raw",
            },
            path=trace_path,
        )

        report = self.service.predictor_latency({"log": str(trace_path), "last": 5})

        self.assertTrue(report["ok"])
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["summary"]["firstCandidateMs"]["p50Ms"], 12)

    def test_predictor_benchmark_runs_as_job(self) -> None:
        report = self.service.predictor_benchmark(
            {
                "cases": "docs/eval/predictor_latency_cases.jsonl",
                "profile": "qwen3_06b_ime_hot",
                "repeat": 1,
            }
        )

        self.assertEqual(report["schemaVersion"], "rag-ime.predictor-benchmark.v1")
        self.assertGreaterEqual(report["sampleCount"], 1)

    def test_clear_cache_requires_confirm_text(self) -> None:
        denied = self.service.predictor_cache_clear({"confirmText": "wrong"})
        allowed = self.service.predictor_cache_clear({"confirmText": "CLEAR PREDICTOR CACHE"})

        self.assertFalse(denied["ok"])
        self.assertTrue(allowed["ok"])
        self.assertFalse(allowed["cleared"])

    def test_history_endpoint_redacts_raw_text_by_default_and_tombstone_audits(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_010,
                source="manual",
                committed_text="这是一整段旧输入历史不应该默认完整展示",
                privacy_disposition="allowed",
                recent_context="包含用户真实输入上下文",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )

        history = self.service.management_history({"limit": 5, "project": "wisdom-weasel-rag-ime"})

        self.assertTrue(history["ok"])
        item = history["items"][0]
        self.assertNotIn("text", item)
        self.assertNotIn("recentContext", item)
        self.assertTrue(item["textHash"].startswith("sha256:"))
        self.assertIn("textPreview", item)

        tombstone = self.service.management_history_tombstone({"eventId": 1, "reason": "test tombstone"})

        self.assertTrue(tombstone["ok"])
        self.assertGreater(int(tombstone["auditId"]), 0)
        self.assertEqual(self._audit_count("history_tombstone"), 1)
        governance = self.core.inspect_memory_governance(limit=10)
        self.assertTrue(any(item["targetValue"] == "event:1" for item in governance["tombstones"]))

    def test_history_can_show_raw_text_only_when_debug_flag_enabled(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_011,
                source="manual",
                committed_text="只有显式调试开关才展示完整原文",
                privacy_disposition="allowed",
                recent_context="debug raw text",
                project="wisdom-weasel-rag-ime",
            )
        )
        service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                seed_if_empty=False,
                predictor=_ManagementPredictionProvider(),
                include_raw_text=True,
            )
        )

        history = service.management_history({"limit": 1, "project": "wisdom-weasel-rag-ime"})

        self.assertTrue(history["rawTextVisible"])
        self.assertEqual(history["items"][0]["text"], "只有显式调试开关才展示完整原文")

    def test_memory_and_lexicon_review_actions_update_status_and_audit(self) -> None:
        self._upsert_item(memory_id="stable:pending", kind="stable_memory", text="稳定记忆待审核")
        self._upsert_item(memory_id="phrase:pending", kind="phrase", text="连续预测")

        memories = self.service.management_memories({"status": "pending"})
        lexicon = self.service.management_lexicon({"status": "pending"})

        self.assertTrue(any(item["memoryId"] == "stable:pending" for item in memories["items"]))
        self.assertTrue(any(item["memoryId"] == "phrase:pending" for item in lexicon["items"]))
        self.assertNotIn("text", memories["items"][0])

        approved = self.service.management_memory_action({"memoryId": "stable:pending", "action": "approve"})
        rejected = self.service.management_lexicon_action({"memoryId": "phrase:pending", "action": "reject"})

        self.assertTrue(approved["ok"])
        self.assertTrue(rejected["ok"])
        self.assertEqual(self.core.inspect_memory_v2(status="approved")["items"][0]["memoryId"], "stable:pending")
        self.assertEqual(self.core.inspect_memory_v2(status="rejected")["items"][0]["memoryId"], "phrase:pending")
        self.assertEqual(self._audit_count("memory_approve"), 1)
        self.assertEqual(self._audit_count("lexicon_reject"), 1)

    def test_lexicon_rime_export_is_approved_phrase_dry_run_preview(self) -> None:
        self._upsert_item(memory_id="phrase:approved", kind="phrase", text="连续预测", status="approved")
        self._upsert_item(memory_id="phrase:pending", kind="phrase", text="待审核短语", status="pending")
        self._upsert_item(memory_id="memory:approved", kind="stable_memory", text="稳定记忆", status="approved")

        preview = self.service.management_lexicon_export_rime(
            {"project": "wisdom-weasel-rag-ime", "status": "approved", "dryRun": True}
        )
        pending_attempt = self.service.management_lexicon_export_rime({"status": "pending", "dryRun": True})
        apply_attempt = self.service.management_lexicon_export_rime({"dryRun": False})

        self.assertTrue(preview["ok"])
        self.assertTrue(preview["dryRun"])
        self.assertFalse(preview["applySupported"])
        self.assertEqual(preview["entryCount"], 1)
        self.assertEqual(preview["entries"][0]["phrase"], "连续预测")
        self.assertIn("连续预测", preview["text"])
        self.assertNotIn("待审核短语", preview["text"])
        self.assertNotIn("稳定记忆", preview["text"])
        self.assertFalse(pending_attempt["ok"])
        self.assertEqual(pending_attempt["requiredStatus"], "approved")
        self.assertFalse(apply_attempt["ok"])
        self.assertIn("dryRun", apply_attempt["error"])

    def test_cleanup_diff_apply_and_rollback_are_audited(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_020,
                source="manual",
                committed_text="离线整理稳定记忆",
                privacy_disposition="allowed",
                recent_context="用户接受过这个短语",
                project="wisdom-weasel-rag-ime",
                tags=("memory",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=1_900_000_100_021,
                memory_id="event:1",
                action_type="accepted",
                query="离线整理",
            )
        )
        plan = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")
        run = self.core.list_memory_cleanup_runs(run_id=str(plan["runId"]), limit=1)
        diff_id = int(run["items"][0]["diffs"][0]["diffId"])

        inspected = self.service.management_cleanup_diff({"id": diff_id})
        missing_apply_confirm = self.service.management_cleanup_diff_apply({"diffId": diff_id})
        applied = self.service.management_cleanup_diff_apply({"diffId": diff_id, "confirm": "apply"})
        missing_rollback_confirm = self.service.management_cleanup_diff_rollback({"diffId": diff_id})
        rolled_back = self.service.management_cleanup_diff_rollback({"diffId": diff_id, "confirm": "rollback"})

        self.assertTrue(inspected["ok"])
        self.assertFalse(missing_apply_confirm["ok"])
        self.assertEqual(missing_apply_confirm["requiredConfirm"], "apply")
        self.assertTrue(applied["ok"])
        self.assertFalse(missing_rollback_confirm["ok"])
        self.assertEqual(missing_rollback_confirm["requiredConfirm"], "rollback")
        self.assertTrue(rolled_back["ok"])
        self.assertGreater(int(applied["auditId"]), 0)
        self.assertEqual(self._audit_count("cleanup_diff_apply"), 1)
        self.assertEqual(self._audit_count("cleanup_diff_rollback"), 1)

    def test_debug_management_health_is_localhost_only_by_default(self) -> None:
        health = self.service.health()

        self.assertTrue(health["management"]["localhostOnly"])
        self.assertFalse(health["management"]["rawTextVisible"])
        self.assertIn("settings", health["management"])

    def test_settings_update_schema_and_reset_are_audited(self) -> None:
        schema = self.service.settings_schema()
        update = self.service.settings_update({"display.badges.model": "AI", "interaction.postCommit.numberKeys": "select_prediction"})
        settings = self.service.settings()
        reset = self.service.settings_reset_section({"section": "display"})

        self.assertTrue(schema["ok"])
        self.assertIn("interaction", {item["id"] for item in schema["sections"]})
        self.assertTrue(update["ok"])
        self.assertGreater(int(update["auditId"]), 0)
        self.assertEqual(settings["settings"]["display"]["badges"]["model"], "AI")
        self.assertEqual(settings["settings"]["interaction"]["postCommit"]["numberKeys"], "select_prediction")
        self.assertEqual(reset["settings"]["display"]["badges"]["model"], "模")
        self.assertEqual(self._audit_count("settings_update"), 1)
        self.assertEqual(self._audit_count("settings_reset_section"), 1)

    def test_active_rag_shortcut_update_returns_runtime_sync_commands(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(["defaults"], 0, "", "")
        )
        self.service._runtime_command_runner = runner
        result = self.service.active_rag_settings_update(
            {
                "shortcut": "ctrl+r",
                "capture": {
                    "accessibility": True,
                    "clipboardFallback": False,
                },
            }
        )
        runtime_sync = result["runtimeSync"]
        commands = runtime_sync["commands"]

        self.assertTrue(result["ok"])
        self.assertEqual(result["settings"]["activeRag"]["shortcut"], "ctrl+r")
        self.assertEqual(runtime_sync["shortcut"], "ctrl+r")
        self.assertTrue(runtime_sync["attempted"])
        self.assertTrue(runtime_sync["applied"])
        self.assertEqual(runner.call_count, 4)
        self.assertIn("activeRag.shortcut", result["changedKeys"])
        self.assertNotIn("confirmText", result["settings"])
        self.assertIn(
            ["defaults", "write", "im.rime.inputmethod.Squirrel", "RagImeActiveRagShortcut", "-string", "ctrl+r"],
            commands,
        )
        self.assertIn(
            ["defaults", "write", "im.rime.inputmethod.Squirrel", "RagImeActiveRagCaptureClipboardFallback", "-bool", "false"],
            commands,
        )

    def test_display_badge_customization_applies_to_rime_suggest_preview(self) -> None:
        self.service.settings_update({"display.badges.model": "AI", "display.maxPostCommitCandidates": 2})
        payload = {
            "sessionId": "custom-display",
            "requestSeq": 1,
            "privacyDisposition": "allowed",
            "rawInput": "",
            "preedit": "",
            "committedContext": "我想设计一个候选栏",
            "commitTextPreview": "候选栏",
            "predictionFirstMerge": True,
            "maxSideCandidates": 8,
            "latencyBudgetMs": 1000,
            "rimeContext": {"candidates": []},
            "foregroundText": {
                "surroundingBefore": "我想设计一个候选栏",
                "surroundingAfter": "",
                "source": "accessibility",
                "captureAgeMs": 0,
            },
        }
        with patch.dict("os.environ", {"RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL": "1"}, clear=False):
            response = self.service.rime_suggest(payload)
            model_items = [item for item in response["displayCandidates"] if item["sourceType"] == "model"]
            for request_seq in range(2, 6):
                if model_items:
                    break
                time.sleep(0.2)
                response = self.service.rime_suggest({**payload, "requestSeq": request_seq})
                model_items = [item for item in response["displayCandidates"] if item["sourceType"] == "model"]

        self.assertLessEqual(len([item for item in response["displayCandidates"] if item["selectionAction"] != "none"]), 2)
        self.assertTrue(model_items)
        self.assertEqual(model_items[0]["badge"], "AI")

    def test_disable_composition_prediction_keeps_rime_like_candidates_only(self) -> None:
        self.service.settings_update({"interaction.composition.showPrediction": False})
        response = self.service.rime_suggest(
            {
                "sessionId": "custom-composition",
                "requestSeq": 1,
                "privacyDisposition": "allowed",
                "rawInput": "houxuan",
                "preedit": "houxuan",
                "committedContext": "输入法",
                "predictionFirstMerge": True,
                "maxSideCandidates": 8,
                "rimeContext": {"candidates": [{"label": "1", "text": "候选"}]},
            }
        )

        self.assertTrue(all(item["sourceType"] in {"rime", "raw_english", "status"} for item in response["displayCandidates"]))

    def test_rag_preview_reports_disabled_lanes_from_settings(self) -> None:
        self.service.settings_update({"rag.lanes.bm25Tags": False})

        preview = self.service.rag_core_v3_query_preview({"query": "多路召回"})

        self.assertTrue(preview["ok"])
        self.assertTrue(preview["lanes"]["bm25Tags"]["disabledBySettings"])
        self.assertIn({"lane": "bm25Tags", "reason": "disabled_by_management_settings"}, preview["blocked"])

    def test_vocabulary_and_active_rag_management_api(self) -> None:
        added = self.service.vocabulary_item_save(
            {
                "surface": "StableCandidateSnapshot",
                "aliases": ["候选快照"],
                "pinyin": "hou xuan kuai zhao",
                "tags": ["输入法"],
                "priority": 100,
            },
            action="add",
        )
        items = self.service.vocabulary_items({"query": "Stable"})
        export_preview = self.service.vocabulary_rime_export_preview({})
        active = self.service.active_rag_preview(
            {
                "selectedText": "候选栏闪烁，需要解释原因",
                "privacyDisposition": "allowed",
            }
        )

        self.assertTrue(added["ok"])
        self.assertEqual(items["items"][0]["surface"], "StableCandidateSnapshot")
        self.assertIn("StableCandidateSnapshot", export_preview["text"])
        self.assertTrue(active["ok"])
        self.assertTrue(active["dryRun"])
        self.assertIn("selectedTextHash", active)

    def test_management_security_token_gate_when_enabled(self) -> None:
        self.service.settings_update({"managementSecurity.requireToken": True, "managementSecurity.token": "secret-token"})

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/settings/update",
                data=json.dumps({"display.badges.model": "AI"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urlopen(request, timeout=5)
                denied_payload = {"ok": True}
            except HTTPError as exc:
                try:
                    denied_payload = json.loads(exc.read().decode("utf-8"))
                finally:
                    exc.close()

            allowed_request = Request(
                f"http://127.0.0.1:{server.server_port}/api/settings/update",
                data=json.dumps({"display.badges.model": "AI"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-RAG-IME-Admin-Token": "secret-token"},
                method="POST",
            )
            with urlopen(allowed_request, timeout=5) as response:
                allowed_payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertFalse(denied_payload["ok"])
        self.assertIn("token", denied_payload["error"])
        self.assertTrue(allowed_payload["ok"])

    def test_rag_core_v3_preview_is_read_only(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_030,
                source="manual",
                committed_text="多路召回",
                privacy_disposition="allowed",
                recent_context="RAG 输入法",
                project="wisdom-weasel-rag-ime",
                tags=("RAG",),
            )
        )
        before = self._retrieval_doc_count()

        preview = self.service.rag_core_v3_query_preview({"query": "多路召回", "project": "wisdom-weasel-rag-ime"})
        after = self._retrieval_doc_count()

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["schemaVersion"], "rag-ime.rag-core-v3-preview.v1")
        self.assertEqual(before, after)

    def test_rag_core_v3_preview_redacts_raw_text_by_default(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_031,
                source="manual",
                committed_text="隐私短语",
                privacy_disposition="allowed",
                recent_context="超级秘密上下文",
                project="wisdom-weasel-rag-ime",
                tags=("RAG",),
            )
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")

        preview = self.service.rag_core_v3_query_preview({"query": "隐私短语", "project": "wisdom-weasel-rag-ime"})
        blob = json.dumps(preview, ensure_ascii=False)

        self.assertTrue(preview["ok"])
        self.assertFalse(preview["rawTextVisible"])
        self.assertNotIn("隐私短语 超级秘密上下文", blob)
        self.assertNotIn("超级秘密上下文", blob)
        self.assertIn("evidencePreviewHash", blob)

    def test_rag_core_v3_preview_reports_lane_breakdown(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_032,
                source="manual",
                committed_text="多路召回",
                privacy_disposition="allowed",
                recent_context="RAG 输入法",
                project="wisdom-weasel-rag-ime",
                tags=("RAG",),
            )
        )

        rebuild = self.service.rag_core_v3_rebuild_retrieval_docs({"project": "wisdom-weasel-rag-ime"})
        preview = self.service.rag_core_v3_query_preview({"query": "多路召回", "project": "wisdom-weasel-rag-ime"})

        self.assertTrue(rebuild["ok"])
        self.assertIn("bm25Raw", preview["lanes"])
        self.assertGreaterEqual(preview["lanes"]["bm25Raw"]["count"], 1)

    def test_deepseek_preview_requires_explicit_flag_or_token(self) -> None:
        with patch.dict("os.environ", {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "0"}, clear=False):
            preview = self.service.deepseek_completion_preview({"currentContext": "RAG 输入法"})

        self.assertFalse(preview["ok"])
        self.assertIn("RAG_IME_DEEPSEEK_ACTIVE_RAG=1", preview["requires"])

    def test_deepseek_preview_blocks_secure_input_before_retrieval_or_prompt_build(self) -> None:
        secret = "账号 admin 密码 cannot-leave-this-machine"

        preview = self.service.deepseek_completion_preview(
            {
                "currentContext": secret,
                "selectedText": secret,
                "secureInput": True,
                "dryRun": False,
            }
        )

        blob = json.dumps(preview, ensure_ascii=False)
        self.assertFalse(preview["ok"])
        self.assertEqual(preview["error"], "sensitive_field_blocked")
        self.assertFalse(preview["retrieval"]["called"])
        self.assertFalse(preview["remoteModel"]["requested"])
        self.assertEqual(preview["messages"], [])
        self.assertEqual(preview["evidencePack"], [])
        self.assertEqual(preview["candidates"], [])
        self.assertNotIn(secret, blob)
        self.assertNotIn("sha256:", blob)

    def test_deepseek_preview_dry_run_builds_single_candidate_rag_evidence(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_034,
                source="manual",
                committed_text="BM25 加向量召回用于输入法候选",
                privacy_disposition="allowed",
                recent_context="RAG 输入法核心改造",
                project="wisdom-weasel-rag-ime",
                tags=("RAG",),
            )
        )

        self.service.settings_update(
            {
                "activeRag.allowRemoteModel": True,
                "privacy.allowRemoteModelForActiveRag": True,
                "confirmText": "ALLOW REMOTE MODEL",
            }
        )
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_DEEPSEEK_ACTIVE_RAG": "1",
                "RAG_IME_DEEPSEEK_API_KEY": "test-key-not-sent-by-dry-run",
            },
            clear=False,
        ):
            preview = self.service.deepseek_completion_preview(
                {"currentContext": "RAG 输入法核心改造", "dryRun": True}
            )

        self.assertTrue(preview["ok"])
        self.assertTrue(preview["dryRun"])
        self.assertGreaterEqual(len(preview["evidencePack"]), 1)
        self.assertTrue(preview["requestDiagnostics"]["injection"]["success"])
        self.assertTrue(preview["requestDiagnostics"]["injection"]["evidenceIncluded"])
        self.assertNotIn("text", preview["messages"][1]["content"])
        self.assertIn("hash", preview["messages"][1]["content"])
        self.assertNotIn("RAG 输入法核心改造", json.dumps(preview, ensure_ascii=False))

    def test_active_rag_route_status_reports_every_remote_gate(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_DEEPSEEK_ACTIVE_RAG": "1",
                "RAG_IME_DEEPSEEK_API_KEY": "route-test-key",
            },
            clear=False,
        ):
            blocked = self.service.active_rag_route_status(local_only=False)
            self.service.settings_update(
                {
                    "activeRag.allowRemoteModel": True,
                    "privacy.allowRemoteModelForActiveRag": True,
                    "confirmText": "ALLOW REMOTE MODEL",
                }
            )
            ready = self.service.active_rag_route_status(local_only=False)

        self.assertFalse(blocked["remoteReady"])
        self.assertEqual(blocked["skipReason"], "active_rag_remote_not_allowed")
        self.assertTrue(ready["remoteReady"])
        self.assertTrue(all(ready["gates"].values()))
        self.assertFalse(ready["passivePostCommitRemoteAllowed"])

    def test_knowledge_workbench_runs_explicit_deepseek_session(self) -> None:
        self.service.knowledge_workbench.generator = _KnowledgeGenerator()
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_044,
                source="manual",
                committed_text="个人知识工作台使用本地 RAG 证据",
                privacy_disposition="allowed",
                recent_context="DeepSeek 显式知识问答",
                project="wisdom-weasel-rag-ime",
                tags=("knowledge-workbench",),
            )
        )
        self._upsert_item(
            memory_id="stable:knowledge-workbench",
            kind="stable_memory",
            text="个人知识工作台使用本地 RAG 证据",
            status="approved",
        )
        self.service.rag_core_v3_rebuild_retrieval_docs({"project": "wisdom-weasel-rag-ime"})
        self.service.settings_update(
            {
                "activeRag.allowRemoteModel": True,
                "privacy.allowRemoteModelForActiveRag": True,
                "confirmText": "ALLOW REMOTE MODEL",
            }
        )
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_DEEPSEEK_ACTIVE_RAG": "1",
                "RAG_IME_DEEPSEEK_API_KEY": "knowledge-route-test-key",
            },
            clear=False,
        ):
            started = self.service.knowledge_workbench_start(
                {
                    "mode": "knowledge_answer",
                    "question": "个人知识工作台使用本地 RAG 证据",
                    "context": "本地 RAG",
                    "generation": 3,
                    "includeNotion": False,
                }
            )
            deadline = time.monotonic() + 2
            response = started
            while response.get("status") not in {"ready", "error", "cancelled"} and time.monotonic() < deadline:
                time.sleep(0.005)
                response = self.service.knowledge_workbench_status({"sessionId": started["sessionId"]})

        self.assertTrue(started["ok"])
        self.assertEqual(response["status"], "ready")
        self.assertEqual(response["answer"], "本地知识答案")
        self.assertEqual(response["generation"], 3)
        self.assertGreaterEqual(len(response["evidence"]), 1)
        self.assertIn("contextInjection", response["diagnostics"])

    def test_knowledge_workbench_retrieves_memories_from_other_apps(self) -> None:
        self._upsert_item(
            memory_id="stable:cross-app-bge",
            kind="stable_memory",
            text="BGE 向量索引需要在 provider 指纹变化后重新构建",
            status="approved",
            app="com.openai.codex",
        )
        self.service.rag_core_v3_rebuild_retrieval_docs({"project": "wisdom-weasel-rag-ime"})

        evidence = self.service._knowledge_workbench_evidence(
            KnowledgeWorkbenchRequest(
                question="BGE provider 指纹变化后怎么处理向量索引",
                mode="knowledge_answer",
                app="com.rag-ime.control",
            )
        )

        self.assertIn("stable:cross-app-bge", [item["sourceId"] for item in evidence])
        matched = next(item for item in evidence if item["sourceId"] == "stable:cross-app-bge")
        self.assertIn("BGE 向量索引", matched["text"])
        self.assertGreater(matched["score"], 0.0)

    def test_knowledge_workbench_reserves_structured_book_and_atom_evidence(self) -> None:
        phrase_hits = [
            {
                "doc_id": "phrase:noisy",
                "doc_type": "phrase",
                "source_id": "phrase:noisy",
                "text": "重复的短语证据",
                "source_lane": lane,
                "rank": 1,
                "tags": ["输入法"],
                "metadata": {},
            }
            for lane in ("bm25_raw", "bm25_tags", "tagmemo")
        ]
        structured_hits = [
            {
                "doc_id": "book:demo",
                "doc_type": "book",
                "source_id": "book:demo",
                "text": "输入法优先演示路线",
                "source_lane": "bm25_raw",
                "rank": 2,
                "tags": ["输入法", "RAG"],
                "metadata": {"bookTitle": "输入法优先演示路线"},
            },
            {
                "doc_id": "atom:demo",
                "doc_type": "atom",
                "source_id": "atom:demo",
                "text": "DeepSeek 只处理显式知识工作台查询",
                "source_lane": "bm25_tags",
                "rank": 3,
                "tags": ["DeepSeek"],
                "metadata": {},
            },
        ]
        with patch(
            "rag_ime.debug_server.retrieve_hybrid_rag_candidates",
            return_value={"candidates": [], "hits": [*phrase_hits, *structured_hits]},
        ) as retrieve:
            evidence = self.service._knowledge_workbench_evidence(
                KnowledgeWorkbenchRequest(
                    question="输入法演示如何联动知识工作台",
                    mode="knowledge_answer",
                    app="com.rag-ime.control.demo",
                )
            )

        self.assertEqual([item["sourceId"] for item in evidence[:2]], ["book:demo", "atom:demo"])
        self.assertEqual(retrieve.call_args.args[1].app, "")

    def test_knowledge_workbench_blocks_sensitive_text_before_retrieval(self) -> None:
        response = self.service.knowledge_workbench_start(
            {
                "mode": "recall",
                "question": "帮我回忆账号密码",
                "context": "password=must-not-leave",
                "secureInput": True,
            }
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "sensitive_field_blocked")
        self.assertFalse(response["retrieval"]["called"])
        self.assertFalse(response["remoteModel"]["requested"])

    def test_knowledge_route_reports_worker_and_polling_as_separate_gates(self) -> None:
        route = self.service.knowledge_workbench_route_status()

        self.assertIn("notion", route)
        self.assertIn("submitConfigured", route["notion"])
        self.assertIn("pollConfigured", route["notion"])
        self.assertFalse(route["notion"]["ready"])

    def test_knowledge_database_draft_requires_confirmation_and_supports_rollback(self) -> None:
        event_ref = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_045,
                source="manual",
                committed_text="数据库整理草案验证",
                privacy_disposition="allowed",
                recent_context="Memory Book",
                project="wisdom-weasel-rag-ime",
            )
        )
        event_id = int(event_ref.split(":", 1)[1])
        plan = memory_book_plan_from_compile_output(
            {
                "schemaVersion": "rag-ime.memory-book-compile.v1",
                "dailyBooks": [
                    {
                        "bookKey": "2026-07-10",
                        "title": "数据库整理草案",
                        "summary": "显式审阅后才应用。",
                        "sourceEventIds": [event_id],
                    }
                ],
                "memoryAtoms": [],
                "tagEdges": [],
                "phraseCandidates": [],
                "warnings": [],
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-test",
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            store_memory_book_plan(conn, plan)

        blocked = self.service.knowledge_workbench_database_apply({"runId": plan["runId"]})
        applied = self.service.knowledge_workbench_database_apply(
            {"runId": plan["runId"], "confirm": "apply"}
        )
        rolled_back = self.service.knowledge_workbench_database_rollback(
            {"runId": plan["runId"], "confirm": "rollback"}
        )

        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["requiredConfirm"], "apply")
        self.assertEqual(applied["run"]["status"], "applied")
        self.assertEqual(rolled_back["run"]["status"], "rolled_back")
        self.assertIn("retrieval", applied)

    def test_legacy_browser_control_surface_is_removed(self) -> None:
        root = Path(__file__).resolve().parents[1]

        self.assertFalse((root / "debug" / "index.html").exists())
        self.assertFalse((root / "debug" / "app.js").exists())
        self.assertFalse((root / "debug" / "styles.css").exists())
        self.assertTrue((root / "macos" / "RagImeControl" / "RagImeControlApp.swift").is_file())

    def test_memory_book_preview_is_dry_run_and_redacted(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_033,
                source="manual",
                committed_text="真实历史整理入口",
                privacy_disposition="allowed",
                recent_context="不应该默认展示的上下文",
                project="wisdom-weasel-rag-ime",
                tags=("RAG",),
            )
        )

        preview = self.service.rag_core_v3_memory_book_preview({"project": "wisdom-weasel-rag-ime", "limit": 10})
        blob = json.dumps(preview, ensure_ascii=False)

        self.assertTrue(preview["ok"])
        self.assertTrue(preview["dryRun"])
        self.assertFalse(preview["rawTextVisible"])
        self.assertNotIn("真实历史整理入口", blob)
        self.assertNotIn("不应该默认展示的上下文", blob)
        self.assertIn("textHash", blob)

    def test_management_http_routes_are_available(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_040,
                source="manual",
                committed_text="HTTP 管理接口默认脱敏展示",
                privacy_disposition="allowed",
                recent_context="debug management route",
                project="wisdom-weasel-rag-ime",
            )
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/history?limit=3", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schemaVersion"], "rag-ime.management-history.v1")
        self.assertFalse(payload["rawTextVisible"])
        self.assertNotIn("text", payload["items"][0])

    def test_management_cleanup_diff_http_requires_confirmation(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_050,
                source="manual",
                committed_text="离线整理稳定记忆",
                privacy_disposition="allowed",
                recent_context="用户接受过这个短语",
                project="wisdom-weasel-rag-ime",
                tags=("memory",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=1_900_000_100_051,
                memory_id="event:1",
                action_type="accepted",
                query="离线整理",
            )
        )
        plan = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")
        run = self.core.list_memory_cleanup_runs(run_id=str(plan["runId"]), limit=1)
        diff_id = int(run["items"][0]["diffs"][0]["diffId"])

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            missing_request = Request(
                f"http://127.0.0.1:{server.server_port}/api/cleanup-diff/apply",
                data=json.dumps({"diffId": diff_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(missing_request, timeout=5) as missing_response:
                missing_payload = json.loads(missing_response.read().decode("utf-8"))

            apply_request = Request(
                f"http://127.0.0.1:{server.server_port}/api/cleanup-diff/apply",
                data=json.dumps({"diffId": diff_id, "confirm": "apply"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(apply_request, timeout=5) as apply_response:
                apply_payload = json.loads(apply_response.read().decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertFalse(missing_payload["ok"])
        self.assertEqual(missing_payload["requiredConfirm"], "apply")
        self.assertTrue(apply_payload["ok"])
        self.assertEqual(apply_payload["result"]["diff"]["status"], "applied")
        self.assertEqual(self._audit_count("cleanup_diff_apply"), 1)

    def test_api_root_names_the_single_native_control_center(self) -> None:
        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path(".")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                content_type = response.headers.get_content_type()
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(content_type, "application/json")
        self.assertEqual(payload["schemaVersion"], "rag-ime.local-api-root.v1")
        self.assertEqual(payload["controlCenter"], "RagImeControl.app")
        self.assertFalse(payload["browserUI"])

    def _upsert_item(
        self,
        *,
        memory_id: str,
        kind: str,
        text: str,
        status: str = "pending",
        app: str = "",
    ) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            upsert_memory_item(
                conn,
                memory_id=memory_id,
                kind=kind,
                text=text,
                normalized_text=normalize_text(text),
                summary="management test",
                source_event_id=None,
                project="wisdom-weasel-rag-ime",
                app=app,
                confidence=0.7,
                quality_score=0.5,
                status=status,
                privacy_class="local",
                created_at_ms=1_900_000_100_030,
                updated_at_ms=1_900_000_100_030,
                metadata={"direct_candidate_allowed": True},
                tags=("management-test",),
                embedding_provider=None,
            )

    def _audit_count(self, action: str) -> int:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM management_audit_log WHERE action = ?",
                (action,),
            ).fetchone()
            return int(row["count"])

    def _retrieval_doc_count(self) -> int:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT COUNT(*) AS count FROM memory_retrieval_docs").fetchone()
            return int(row["count"])


if __name__ == "__main__":
    unittest.main()
