from __future__ import annotations

import tempfile
import threading
import unittest
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.models import InputEvent, MemoryAction, ModelPrediction


class _ManagementPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text=f"{current_input}候选",
                rank=1,
                provider_name="test-local-model",
                latency_ms=3,
                confidence=0.82,
                metadata={"prompt": recent_context, "reason": "test"},
            )
        ][:max_candidates]


class DebugManagementApiTests(unittest.TestCase):
    def setUp(self) -> None:
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
        self.tmp.cleanup()

    def test_candidate_explain_returns_ranking_reasons(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_001,
                source="manual",
                committed_text="候选解释需要展示排序原因",
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

    def test_history_endpoint_redacts_raw_text_by_default_and_tombstone_audits(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_010,
                source="manual",
                committed_text="这是一整段旧输入历史不应该默认完整展示",
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

    def test_cleanup_diff_apply_and_rollback_are_audited(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_020,
                source="manual",
                committed_text="离线整理稳定记忆",
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

    def test_management_http_routes_are_available(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_040,
                source="manual",
                committed_text="HTTP 管理接口默认脱敏展示",
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

    def test_management_console_sends_cleanup_confirmation(self) -> None:
        app_js = Path(__file__).resolve().parents[1].joinpath("debug", "app.js").read_text(encoding="utf-8")

        self.assertIn("confirmCleanupDiffAction", app_js)
        self.assertIn("confirm: action", app_js)

    def _upsert_item(self, *, memory_id: str, kind: str, text: str) -> None:
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
                app="",
                confidence=0.7,
                quality_score=0.5,
                status="pending",
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


if __name__ == "__main__":
    unittest.main()
