from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.management_service import ManagementService
from rag_ime.management_work_contract import (
    ManagementWorkContract,
    ManagementWorkError,
    WorkExecution,
)
from rag_ime.memory_book_compiler import (
    memory_book_plan_from_compile_output,
    store_memory_book_plan,
)
from rag_ime.models import InputEvent
from rag_ime.runtime_config import RuntimeConfigResolver
from rag_ime.settings_store import ManagementSettingsStore


ROOT = Path(__file__).resolve().parents[1]


class ManagementWorkContractUnitTests(unittest.TestCase):
    def test_preview_apply_and_rollback_are_hash_revision_and_token_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-work-contract-") as tmp:
            db_path = Path(tmp) / "work.sqlite"
            ManagementSettingsStore(db_path).initialize()
            contract = ManagementWorkContract(db_path=db_path)
            domain = {"taskId": "task:one", "action": "complete"}
            revision = {"runtimeRevision": 3, "subjectRevision": "sha256:before"}
            preview = contract.create_preview(
                path_id="planning.task.action",
                payload=domain,
                expected_revision=revision,
                required_confirm="apply",
                summary={"title": "更新任务", "items": ["完成 task:one"], "risk": "R1"},
            )
            validate_contract(preview, "management-work-preview.v1.json")

            with self.assertRaisesRegex(ManagementWorkError, "canonical SHA-256"):
                contract.execute_apply(
                    path_id="planning.task.action",
                    payload=domain,
                    preview_token=str(preview["previewToken"]),
                    payload_sha256="sha256:" + "0" * 64,
                    confirm_text="apply",
                    current_revision=lambda _conn: revision,
                    executor=lambda _conn: self.fail("hash mismatch must not execute"),
                )

            applied = contract.execute_apply(
                path_id="planning.task.action",
                payload=domain,
                preview_token=str(preview["previewToken"]),
                payload_sha256=str(preview["payloadSha256"]),
                confirm_text="apply",
                current_revision=lambda _conn: revision,
                executor=lambda _conn: WorkExecution(
                    result={"ok": True, "eventId": "event:one"},
                    audit_action="planning_task_complete",
                    target_type="task",
                    target_id="task:one",
                    rollback_available=True,
                    rollback_path_id="planning.taskEvent.undo",
                    rollback_confirm="undo",
                    rollback_authority={"eventId": "event:one"},
                    rollback_data={"afterRevision": "sha256:after"},
                ),
            )

            self.assertTrue(applied["ok"])
            validate_contract(applied, "management-work-receipt.v1.json")
            self.assertTrue(applied["rollbackAvailable"])
            self.assertEqual(applied["pathId"], "planning.task.action")
            with sqlite3.connect(db_path) as conn:
                preview_row = conn.execute(
                    "SELECT preview_token_sha256, status FROM management_work_previews"
                ).fetchone()
                receipt_row = conn.execute(
                    "SELECT rollback_token_sha256 FROM management_work_receipts WHERE receipt_id = ?",
                    (applied["receiptId"],),
                ).fetchone()
            self.assertNotEqual(preview_row[0], preview["previewToken"])
            self.assertNotEqual(receipt_row[0], applied["rollbackToken"])
            self.assertEqual(preview_row[1], "applied")

            rolled_back = contract.execute_rollback(
                path_id="planning.taskEvent.undo",
                receipt_id=str(applied["receiptId"]),
                rollback_token=str(applied["rollbackToken"]),
                payload_sha256=str(applied["payloadSha256"]),
                confirm_text="undo",
                expected_apply_path_id="planning.task.action",
                executor=lambda _conn, receipt: WorkExecution(
                    result={"ok": True, "eventId": receipt.rollback_authority["eventId"]},
                    audit_action="planning_task_event_undo",
                    target_type="task",
                    target_id="task:one",
                ),
            )

            self.assertFalse(rolled_back["rollbackAvailable"])
            validate_contract(rolled_back, "management-work-receipt.v1.json")
            self.assertEqual(rolled_back["rollbackOfReceiptId"], applied["receiptId"])
            with self.assertRaisesRegex(ManagementWorkError, "already rolled back"):
                contract.execute_rollback(
                    path_id="planning.taskEvent.undo",
                    receipt_id=str(applied["receiptId"]),
                    rollback_token=str(applied["rollbackToken"]),
                    payload_sha256=str(applied["payloadSha256"]),
                    confirm_text="undo",
                    expected_apply_path_id="planning.task.action",
                    executor=lambda _conn, _receipt: self.fail("receipt reuse must not execute"),
                )

    def test_preview_fails_closed_after_expiry_or_revision_change(self) -> None:
        clock = [1_000]
        with tempfile.TemporaryDirectory(prefix="rag-ime-work-expiry-") as tmp:
            db_path = Path(tmp) / "work.sqlite"
            ManagementSettingsStore(db_path).initialize()
            contract = ManagementWorkContract(
                db_path=db_path,
                preview_ttl_ms=1_000,
                clock_ms=lambda: clock[0],
            )
            preview = contract.create_preview(
                path_id="planning.task.action",
                payload={"taskId": "task:one", "action": "complete"},
                expected_revision={"runtimeRevision": 1, "subjectRevision": "one"},
                required_confirm="apply",
                summary={"title": "更新任务", "items": [], "risk": "R1"},
            )
            clock[0] = 2_001
            with self.assertRaisesRegex(ManagementWorkError, "expired"):
                contract.execute_apply(
                    path_id="planning.task.action",
                    payload={"taskId": "task:one", "action": "complete"},
                    preview_token=str(preview["previewToken"]),
                    payload_sha256=str(preview["payloadSha256"]),
                    confirm_text="apply",
                    current_revision=lambda _conn: {"runtimeRevision": 1, "subjectRevision": "two"},
                    executor=lambda _conn: self.fail("expired preview must not execute"),
                )


class PlanningWorkContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-planning-work-")
        self.db_path = Path(self.tmp.name) / "planning.sqlite"
        self.settings = ManagementSettingsStore(self.db_path)
        self.settings.initialize()
        resolver = RuntimeConfigResolver(self.settings, environ={})
        self.management = ManagementService(
            db_path=self.db_path,
            project="wisdom-weasel-rag-ime",
            repo_root=ROOT,
            settings_store=self.settings,
            health_provider=lambda: {"ok": True},
            input_source_provider=lambda: {},
            predictor_provider=lambda: {},
            runtime_config_provider=resolver.resolve,
        )

    def tearDown(self) -> None:
        self.management.close()
        self.tmp.cleanup()

    def _preview(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        return self.management.planning_mutation_preview(
            {
                "kind": kind,
                "payload": payload,
                "expectedRuntimeRevision": self.management.revision().runtime_revision,
            }
        )

    def test_task_save_action_and_undo_return_real_receipts(self) -> None:
        task_payload = {
            "taskId": "task:contract",
            "date": "2026-07-14",
            "title": "补齐 WorkContract",
            "priority": 2,
        }
        preview = self._preview("task.save", task_payload)
        saved = self.management.planning_apply_task_save(
            {
                **task_payload,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["pathId"], "planning.task.save")
        self.assertEqual(saved["task"]["id"], "task:contract")
        self.assertTrue(saved["rollbackAvailable"])

        action_preview = self._preview(
            "task.action",
            {"taskId": "task:contract", "action": "complete"},
        )
        applied = self.management.planning_apply_task_action(
            {
                "taskId": "task:contract",
                "action": "complete",
                "expectedRuntimeRevision": action_preview["expectedRevision"]["runtimeRevision"],
                "previewToken": action_preview["previewToken"],
                "payloadSha256": action_preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        denied = self.management.planning_undo_task_event_contract(
            {
                "eventId": applied["eventId"],
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
                "confirmText": "rollback",
            }
        )
        undone = self.management.planning_undo_task_event_contract(
            {
                "eventId": applied["eventId"],
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
                "confirmText": "undo",
            }
        )

        self.assertEqual(denied["errorCode"], "confirmation_mismatch")
        self.assertTrue(undone["ok"])
        self.assertEqual(undone["task"]["status"], "todo")
        self.assertEqual(undone["rollbackOfReceiptId"], applied["receiptId"])

    def test_new_task_save_can_rollback_only_while_snapshot_is_current(self) -> None:
        task_payload = {
            "taskId": "task:rollback",
            "date": "2026-07-14",
            "title": "可回滚保存",
        }
        preview = self._preview("task.save", task_payload)
        saved = self.management.planning_apply_task_save(
            {
                **task_payload,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )
        rollback = self.management.planning_mutation_rollback(
            {
                "receiptId": saved["receiptId"],
                "rollbackToken": saved["rollbackToken"],
                "payloadSha256": saved["payloadSha256"],
                "confirmText": "rollback",
            }
        )

        self.assertTrue(rollback["ok"], rollback)
        self.assertTrue(rollback["deleted"])
        dashboard = self.management.planning_dashboard(plan_date="2026-07-14")
        self.assertEqual(dashboard["tasks"], [])

    def test_apply_without_preview_or_with_unknown_field_fails_closed(self) -> None:
        result = self.management.planning_apply_task_save(
            {
                "date": "2026-07-14",
                "title": "不得直接保存",
                "expectedRuntimeRevision": self.management.revision().runtime_revision,
                "previewToken": "missing",
                "payloadSha256": "sha256:" + "0" * 64,
                "confirmText": "apply",
                "shell": "rm -rf /",
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["errorCode"], "invalid_request")
        validate_contract(result, "management-work-error.v1.json")
        self.assertEqual(self.management.planning_dashboard(plan_date="2026-07-14")["tasks"], [])

    def test_task_action_preview_becomes_stale_when_task_changes(self) -> None:
        self.management.planning_save_task(
            {
                "taskId": "task:stale",
                "date": "2026-07-14",
                "title": "检测陈旧预览",
            }
        )
        preview = self._preview(
            "task.action",
            {"taskId": "task:stale", "action": "complete"},
        )
        self.management.planning_task_action(
            {"taskId": "task:stale", "action": "start"}
        )
        denied = self.management.planning_apply_task_action(
            {
                "taskId": "task:stale",
                "action": "complete",
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        self.assertEqual(denied["errorCode"], "revision_mismatch")
        dashboard = self.management.planning_dashboard(plan_date="2026-07-14")
        self.assertEqual(dashboard["tasks"][0]["status"], "in_progress")


class KnowledgeDatabaseWorkContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-work-")
        self.db_path = Path(self.tmp.name) / "knowledge.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.service = DebugImeService(DebugServerConfig(db_path=self.db_path, seed_if_empty=False))

    def tearDown(self) -> None:
        self.service.agent.close()
        self.service.management.close()
        self.tmp.cleanup()

    def _draft(self) -> dict[str, object]:
        event_ref = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_045,
                source="manual",
                committed_text="WorkContract 知识库草案",
                privacy_disposition="allowed",
                recent_context="Memory Book",
                project="wisdom-weasel-rag-ime",
            )
        )
        event_id = int(event_ref.split(":", 1)[1])
        plan = memory_book_plan_from_compile_output(
            {
                "dailyBooks": [
                    {
                        "bookKey": "2026-07-14",
                        "title": "WorkContract",
                        "summary": "显式预览后应用。",
                        "sourceEventIds": [event_id],
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-test",
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            store_memory_book_plan(conn, plan)
        return plan

    def test_database_apply_and_rollback_are_bound_to_run_receipt_and_hash(self) -> None:
        plan = self._draft()
        preview = self.service.knowledge_workbench_database_apply_preview(
            {"runId": plan["runId"]}
        )
        applied = self.service.knowledge_workbench_database_apply_contract(
            {
                "runId": plan["runId"],
                "confirm": "apply",
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
            }
        )
        wrong_run = self.service.knowledge_workbench_database_rollback_contract(
            {
                "runId": "memory_book_wrong",
                "confirm": "rollback",
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
            }
        )
        rolled_back = self.service.knowledge_workbench_database_rollback_contract(
            {
                "runId": plan["runId"],
                "confirm": "rollback",
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
            }
        )

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["pathId"], "knowledge.database.apply")
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["run"]["status"], "applied")
        self.assertEqual(applied["rollbackAuthority"], {"runId": plan["runId"]})
        self.assertEqual(wrong_run["errorCode"], "rollback_authority_mismatch")
        self.assertTrue(rolled_back["ok"])
        self.assertEqual(rolled_back["run"]["status"], "rolled_back")

    def test_database_apply_rejects_wrong_hash_without_mutating_run(self) -> None:
        plan = self._draft()
        preview = self.service.knowledge_workbench_database_apply_preview(
            {"runId": plan["runId"]}
        )
        denied = self.service.knowledge_workbench_database_apply_contract(
            {
                "runId": plan["runId"],
                "confirm": "apply",
                "previewToken": preview["previewToken"],
                "payloadSha256": "sha256:" + "0" * 64,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
            }
        )
        review = self.service.agent_memory_maintenance_run(
            {"runId": plan["runId"], "project": "wisdom-weasel-rag-ime"}
        )

        self.assertEqual(denied["errorCode"], "payload_hash_mismatch")
        self.assertTrue(review["canApply"])
        self.assertEqual(review["run"]["status"], "draft")

    def test_database_apply_preview_becomes_stale_after_draft_edit(self) -> None:
        plan = self._draft()
        preview = self.service.knowledge_workbench_database_apply_preview(
            {"runId": plan["runId"]}
        )
        review = self.service.agent_memory_maintenance_run(
            {"runId": plan["runId"], "project": "wisdom-weasel-rag-ime"}
        )
        diff_id = review["run"]["changes"][0]["diffId"]
        self.service.knowledge_workbench_database_draft_edit(
            {"runId": plan["runId"], "diffId": diff_id, "selected": False}
        )
        denied = self.service.knowledge_workbench_database_apply_contract(
            {
                "runId": plan["runId"],
                "confirm": "apply",
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
            }
        )

        self.assertEqual(denied["errorCode"], "revision_mismatch")
        current = self.service.agent_memory_maintenance_run(
            {"runId": plan["runId"], "project": "wisdom-weasel-rag-ime"}
        )
        self.assertEqual(current["run"]["status"], "draft")

    def test_http_routes_enforce_preview_before_knowledge_apply(self) -> None:
        plan = self._draft()

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = ROOT / "debug"
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            denied = _post_json(
                server.server_port,
                "/api/knowledge/database/apply",
                {"runId": plan["runId"], "confirm": "apply"},
            )
            preview = _post_json(
                server.server_port,
                "/api/knowledge/database/apply-preview",
                {"runId": plan["runId"]},
            )
            applied = _post_json(
                server.server_port,
                "/api/knowledge/database/apply",
                {
                    "runId": plan["runId"],
                    "confirm": "apply",
                    "previewToken": preview["previewToken"],
                    "payloadSha256": preview["payloadSha256"],
                    "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                },
            )
            rolled_back = _post_json(
                server.server_port,
                "/api/knowledge/database/rollback",
                {
                    "runId": plan["runId"],
                    "confirm": "rollback",
                    "receiptId": applied["receiptId"],
                    "rollbackToken": applied["rollbackToken"],
                    "payloadSha256": applied["payloadSha256"],
                },
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(denied["errorCode"], "invalid_request")
        self.assertTrue(applied["ok"])
        self.assertTrue(rolled_back["ok"])


def _post_json(port: int, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError("management route returned a non-object response")
    return parsed


if __name__ == "__main__":
    unittest.main()
