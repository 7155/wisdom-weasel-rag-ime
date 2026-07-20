from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.rime_lexicon_review import CONFIRM_TEXT
from rag_ime.rime_rank_export import record_rime_rank_feedback


PAGE_READ_PATHS = {
    "planning": "/api/planning/dashboard?date=2026-07-15",
    "overview": "/api/overview",
    "input": "/api/input-source",
    "agent": "/api/agent/sessions?limit=20",
    "rooms": "/api/agent/rooms?limit=20",
    "roles": "/api/agent/roles",
    "plugins": "/api/agent/tools",
    "voice": "/api/settings",
    "memory": "/api/memory/summary",
    "knowledge": "/api/knowledge/route-status",
    "history": "/api/history/page?limit=20",
    "diagnostics": "/api/runtime/status",
    "configuration": "/api/settings/schema",
}


class ControlCenterPageActionsHttpTests(unittest.TestCase):
    """Exercise the page action boundaries through the real local HTTP app.

    Component tests still cover rendering details, but this suite deliberately
    avoids the frontend mock transport: every assertion below crosses
    ``DebugRequestHandler`` and a temporary on-disk SQLite database.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-page-actions-")
        root = Path(self.tmp.name)
        self.db_path = root / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.history_event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=1_900_000_300_001,
                    source="manual",
                    committed_text="控制中心真实历史操作验收",
                    privacy_disposition="allowed",
                    recent_context="page action acceptance",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO memory_semantic_groups(
                    group_id, title, description, project,
                    source_event_ids_json, confidence, quality_score,
                    created_at_ms, updated_at_ms
                ) VALUES (
                    'group:page-action', '页面验收', '真实 HTTP 写入验收',
                    'wisdom-weasel-rag-ime', ?, 0.9, 0.9, 1, 1
                )
                """,
                (json.dumps([self.history_event_id]),),
            )

        checker = root / "check-input-source.sh"
        checker.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=true hitoolboxEnabled=true thirdPartyEnabled=true current=im.rime.inputmethod.Squirrel.Hans'\n",
            encoding="utf-8",
        )
        os.chmod(checker, 0o700)
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                seed_if_empty=False,
                input_source_check_script=checker,
                rime_user_dir=root / "Rime",
                rime_lexicon_backup_root=root / "LexiconBackups",
            )
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = root
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.service.pi_provider_auth.close()
        self.service.agent.close()
        self.service.management.close()
        self.tmp.cleanup()

    def test_every_sidebar_page_has_a_real_http_read_path(self) -> None:
        self.assertEqual(len(PAGE_READ_PATHS), 13)
        for page, path in PAGE_READ_PATHS.items():
            with self.subTest(page=page, path=path):
                status, payload = self._request("GET", path)
                self.assertEqual(status, 200, payload)
                self.assertIsInstance(payload, dict)
                self.assertNotEqual(payload.get("error"), "route_not_found")
                self.assertTrue(payload.get("schemaVersion"), payload)

    def test_control_transport_bootstrap_and_capabilities_match_the_web_route_catalog(self) -> None:
        bootstrap_status, bootstrap = self._request("GET", "/api/agent/control/bootstrap")
        capabilities_status, capabilities = self._request("GET", "/api/agent/control/capabilities")

        self.assertEqual(bootstrap_status, 200, bootstrap)
        self.assertEqual(capabilities_status, 200, capabilities)
        self.assertEqual(bootstrap["schemaVersion"], "rag-ime.agent-control-bootstrap.v1")
        self.assertEqual(capabilities["schemaVersion"], "rag-ime.control-capabilities.v1")
        route_ids = {str(item["pathId"]) for item in capabilities["routes"]}
        self.assertIn("knowledgeBases.list", route_ids)
        self.assertIn("knowledgeBases.document.import", route_ids)

    def test_diagnostics_repair_uses_preview_start_and_poll_without_returning_a_command(self) -> None:
        _, runtime = self._request("GET", "/api/runtime/status")
        preview = self._ok(
            "POST",
            "/api/runtime/action/preview",
            {
                "action": "open_accessibility_settings",
                "expectedRuntimeRevision": runtime["runtimeRevision"],
            },
        )
        started_status, started = self._request(
            "POST",
            "/api/runtime/action/start",
            {
                "action": "open_accessibility_settings",
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "commandSha256": preview["commandSha256"],
                "confirmText": "apply",
            },
        )
        self.assertEqual(started_status, 202, started)
        self.assertTrue(started["ok"])
        job_id = str(started["result"]["jobId"])
        job = self._ok("GET", f"/api/runtime/job/{quote(job_id, safe='')}")["job"]

        self.assertEqual(job["status"], "external-supervisor-required")
        self.assertEqual(job["result"]["externalAction"]["receiptId"], job_id)
        self.assertNotIn("externalCommand", job["result"])
        self.assertNotIn("path", job["result"]["externalAction"])

    def test_agent_rooms_and_roles_writes_persist_and_rejections_are_not_silent(self) -> None:
        status, created_role = self._request(
            "POST",
            "/api/agent/roles",
            {
                "displayName": "智鼬·页面验收",
                "tagline": "确认真实角色写入",
                "summary": "只用于隔离数据库中的控制中心验收。",
                "traits": ["清楚", "可靠"],
                "timelineModel": "luna",
                "selectableModes": ["assistant"],
            },
        )
        self.assertEqual(status, 201, created_role)
        self.assertTrue(created_role["ok"])
        role = created_role["role"]

        status, created_session = self._request(
            "POST",
            "/api/agent/sessions",
            {
                "title": "页面验收对话",
                "roleId": role["roleId"],
                "roleVersion": role["version"],
            },
        )
        self.assertEqual(status, 201, created_session)
        self.assertTrue(created_session["ok"])

        status, created_room = self._request(
            "POST",
            "/api/agent/rooms",
            {
                "title": "页面验收 Room",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [self.tmp.name],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            },
        )
        self.assertEqual(status, 201, created_room)
        self.assertTrue(created_room["ok"])

        listed_status, listed = self._request("GET", "/api/agent/sessions?limit=20")
        room_status, rooms = self._request("GET", "/api/agent/rooms?limit=20")
        role_status, roles = self._request("GET", "/api/agent/roles")
        self.assertEqual((listed_status, room_status, role_status), (200, 200, 200))
        self.assertTrue(any(item["id"] == created_session["session"]["id"] for item in listed["items"]))
        self.assertTrue(any(item["id"] == created_room["room"]["id"] for item in rooms["items"]))
        self.assertTrue(any(item["roleId"] == role["roleId"] for item in roles["items"]))

        denied_status, denied = self._request(
            "POST",
            "/api/agent/roles",
            {
                "displayName": "非法角色",
                "tagline": "不应写入",
                "summary": "验证服务端拒绝不是静默失败。",
                "traits": ["测试"],
                "timelineModel": "terra",
                "selectableModes": ["assistant"],
                "personaPrompt": "client-owned prompt",
            },
        )
        self.assertEqual(denied_status, 400, denied)
        self.assertFalse(denied["ok"])
        self.assertTrue(str(denied.get("error") or "").strip())

    def test_agent_wake_schedule_http_flow_persists_and_requires_confirmation(self) -> None:
        session_status, session_response = self._request(
            "POST",
            "/api/agent/sessions",
            {"title": "预约目标线程"},
        )
        self.assertEqual(session_status, 201, session_response)
        session = session_response["session"]
        wake_at_ms = int(time.time() * 1000) + 120_000
        denied_status, denied = self._request(
            "POST",
            "/api/agent/wake-schedules",
            {
                "title": "缺少确认",
                "instruction": "不应创建",
                "targetType": "session",
                "targetSessionId": session["id"],
                "wakeAtMs": wake_at_ms,
            },
        )
        self.assertEqual(denied_status, 400, denied)

        created_status, created_response = self._request(
            "POST",
            "/api/agent/wake-schedules",
            {
                "title": "稍后整理",
                "instruction": "整理今天的待办并汇报",
                "targetType": "session",
                "targetSessionId": session["id"],
                "wakeAtMs": wake_at_ms,
                "timezone": "Asia/Shanghai",
                "recurrenceKind": "once",
                "confirmText": "schedule",
            },
        )
        self.assertEqual(created_status, 201, created_response)
        created = created_response["schedule"]
        schedule_id = str(created["id"])

        listed = self._ok("GET", "/api/agent/wake-schedules?limit=20")
        self.assertTrue(any(item["id"] == schedule_id for item in listed["items"]))
        self.assertFalse(listed["schedulerActive"])

        runs = self._ok(
            "GET",
            f"/api/agent/wake-schedules/{quote(schedule_id, safe='')}/runs?limit=20",
        )
        self.assertEqual(runs["items"], [])

        paused = self._ok(
            "POST",
            f"/api/agent/wake-schedules/{quote(schedule_id, safe='')}/action",
            {"action": "pause", "confirmText": "apply"},
        )
        self.assertEqual(paused["schedule"]["status"], "paused")

    def test_configuration_file_routes_bind_preview_to_file_and_runtime_revision(self) -> None:
        root = Path(self.tmp.name)
        config_path = root / "rag-ime.config.yaml"
        config_path.write_text(
            "schemaVersion: rag-ime.user-config.v1\n"
            "settings:\n"
            "  context:\n"
            "    recentInputBaseline: 29\n",
            encoding="utf-8",
        )
        preview = self._ok(
            "POST",
            "/api/configuration/import-preview",
            {"path": str(config_path)},
        )
        self.assertTrue(preview["valid"])
        self.assertRegex(str(preview["configurationHash"]), r"^sha256:[a-f0-9]{64}$")
        self.assertEqual(preview["requiresConfirmation"], "IMPORT RAG-IME CONFIGURATION")

        applied = self._ok(
            "POST",
            "/api/configuration/import-apply",
            {
                "path": str(config_path),
                "expectedRuntimeRevision": preview["runtimeRevision"],
                "previewToken": preview["configurationHash"],
                "confirmText": preview["requiresConfirmation"],
            },
        )
        self.assertIn("context.recentInputBaseline", applied["changedKeys"])
        self.assertEqual(
            self._ok("GET", "/api/settings")["settings"]["context"]["recentInputBaseline"],
            29,
        )

        config_path.write_text(
            "schemaVersion: rag-ime.user-config.v1\n"
            "settings:\n"
            "  context:\n"
            "    recentInputBaseline: 30\n",
            encoding="utf-8",
        )
        stale_status, stale = self._request(
            "POST",
            "/api/configuration/import-apply",
            {
                "path": str(config_path),
                "expectedRuntimeRevision": applied["runtimeRevision"],
                "previewToken": preview["configurationHash"],
                "confirmText": preview["requiresConfirmation"],
            },
        )
        self.assertEqual(stale_status, 400, stale)
        self.assertIn("changed after preview", str(stale.get("error") or ""))

        backup_directory = root / "Backups"
        backup_directory.mkdir()
        exported = self._ok(
            "POST",
            "/api/configuration/backup-export",
            {"destination": str(backup_directory)},
        )
        self.assertEqual(
            Path(str(exported["path"])),
            backup_directory / "rag-ime-backup.ragime-backup",
        )
        restore_preview = self._ok(
            "POST",
            "/api/configuration/restore-preview",
            {"path": str(exported["path"])},
        )
        self.assertTrue(restore_preview["valid"])
        restore_status, restore_error = self._request(
            "POST",
            "/api/configuration/restore-apply",
            {
                "path": str(exported["path"]),
                "restoreToken": restore_preview["restoreToken"],
                "confirmText": restore_preview["requiresConfirmation"],
                "expectedRuntimeRevision": restore_preview["runtimeRevision"] + 1,
            },
        )
        self.assertEqual(restore_status, 400, restore_error)
        self.assertIn("changed after restore preview", str(restore_error.get("error") or ""))

    def test_management_write_pages_cross_http_and_change_the_temporary_database(self) -> None:
        goal = {
            "goalId": "goal:page-action",
            "title": "完成真实页面验收",
            "detail": "规划页必须写入本地数据库",
            "horizon": "medium_term",
            "status": "active",
            "priority": 3,
            "targetDate": "2026-07-31",
            "project": "wisdom-weasel-rag-ime",
        }
        dashboard = self._ok("GET", "/api/planning/dashboard?date=2026-07-15")
        preview = self._ok(
            "POST",
            "/api/planning/mutation/preview",
            {
                "kind": "goal.save",
                "payload": goal,
                "expectedRuntimeRevision": dashboard["runtimeRevision"],
            },
        )
        saved_goal = self._ok(
            "POST",
            "/api/planning/goal/save",
            {
                **goal,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            },
        )
        self.assertEqual(saved_goal["goal"]["id"], goal["goalId"])

        self._apply_settings(
            {
                "voice.hotwordsEnabled": True,
                "voice.hotwords": ["智鼬", "GPT-5.6"],
            }
        )
        settings = self._ok("GET", "/api/settings")
        self.assertTrue(settings["settings"]["voice"]["hotwordsEnabled"])
        self.assertEqual(settings["settings"]["voice"]["hotwords"], ["智鼬", "GPT-5.6"])

        before_width = int(settings["settings"]["display"]["maxWidth"])
        after_width = before_width + 20 if before_width <= 720 else before_width - 20
        self._apply_settings({"display.maxWidth": after_width})
        self.assertEqual(
            self._ok("GET", "/api/settings")["settings"]["display"]["maxWidth"],
            after_width,
        )

        edited = self._ok(
            "POST",
            "/api/memory/edit",
            {
                "kind": "group",
                "id": "group:page-action",
                "title": "页面验收已更新",
                "note": "真实 HTTP 写入已到达",
                "color": "teal",
            },
        )
        self.assertEqual(edited["changes"]["title"], "页面验收已更新")
        group_id = quote("group:page-action", safe="")
        entity = self._ok("GET", f"/api/memory/entities/group/{group_id}")
        self.assertEqual(entity["entity"]["label"], "页面验收已更新")

        history_revision = self._ok(
            "GET", "/api/planning/dashboard?date=2026-07-15"
        )["runtimeRevision"]
        history_preview = self._ok(
            "POST",
            "/api/history/tombstone/preview",
            {
                "eventId": self.history_event_id,
                "reason": "page_action_acceptance",
                "expectedRuntimeRevision": history_revision,
            },
        )
        history_apply = self._ok(
            "POST",
            "/api/history/tombstone/apply",
            {
                "eventId": self.history_event_id,
                "reason": "page_action_acceptance",
                "expectedRuntimeRevision": history_preview["expectedRevision"]["runtimeRevision"],
                "previewToken": history_preview["previewToken"],
                "payloadSha256": history_preview["payloadSha256"],
                "confirmText": "apply",
            },
        )
        self.assertTrue(history_apply["ok"])

        for index in range(2):
            record_rime_rank_feedback(
                self.db_path,
                preedit="zhi you",
                accepted_text="智鼬",
                action="accepted",
                candidate_rank=1,
                context_hash=f"page-action-{index}",
                project="wisdom-weasel-rag-ime",
            )
        lexicon_review = self._ok("GET", "/api/rime-lexicon/review")
        self.assertEqual(lexicon_review["entryCount"], 1)
        lexicon_apply = self._ok(
            "POST",
            "/api/rime-lexicon/apply",
            {
                "reviewToken": lexicon_review["reviewToken"],
                "selectedKeys": [lexicon_review["entries"][0]["reviewKey"]],
                "confirmText": CONFIRM_TEXT,
            },
        )
        self.assertTrue(lexicon_apply["applied"])

        knowledge_status, knowledge_error = self._request(
            "POST",
            "/api/knowledge/start",
            {"question": "请整理 password=page-action-secret", "mode": "knowledge_answer"},
        )
        self.assertEqual(knowledge_status, 200, knowledge_error)
        self.assertFalse(knowledge_error["ok"])
        self.assertEqual(knowledge_error["status"], "blocked")
        self.assertTrue(str(knowledge_error.get("error") or "").strip())

    def _apply_settings(self, changes: dict[str, object]) -> dict[str, object]:
        settings = self._ok("GET", "/api/settings")
        preview = self._ok(
            "POST",
            "/api/settings/preview",
            {
                "changes": changes,
                "expectedRuntimeRevision": settings["runtimeConfig"]["runtimeRevision"],
            },
        )
        return self._ok(
            "POST",
            "/api/settings/apply",
            {
                "changes": changes,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            },
        )

    def _ok(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        status, response = self._request(method, path, payload)
        self.assertEqual(status, 200, response)
        self.assertNotEqual(response.get("ok"), False, response)
        return response

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request = Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method=method,
        )
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            status = exc.code
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        if not isinstance(parsed, dict):
            raise AssertionError(f"{method} {path} returned a non-object response")
        return status, parsed


if __name__ == "__main__":
    unittest.main()
