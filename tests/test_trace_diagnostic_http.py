from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from unittest.mock import patch

from tests.runtime_capabilities import requires_loopback_bind

from rag_ime.agent_service import AgentService
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig


def _governed_presentation() -> dict[str, object]:
    return {
        "headline": "结构化诊断",
        "impact": "结果已按冻结证据完成治理呈现。",
        "primaryFindingId": "",
        "knownFacts": [],
        "evidenceGaps": [],
        "causalNodes": [],
        "expectedStageCount": 0,
        "recordedStageReceiptEvidenceIds": [],
        "failureAttribution": {
            "primaryLayer": "unknown",
            "summary": "当前冻结证据不足以确认唯一主要失败层。",
            "layers": [
                {
                    "layer": layer_name,
                    "verdict": "unknown",
                    "explanation": f"{layer_name} 层暂无足够冻结证据。",
                    "evidenceIds": [],
                }
                for layer_name in ("tool", "skill", "template", "workflow", "model")
            ],
        },
    }


class TraceDiagnosticHttpIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-trace-diagnostic-http-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "agent.sqlite"
        self.service = AgentService(
            db_path=self.db_path,
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def _server(self, *, server_name: str = "debug server") -> tuple[ThreadingHTTPServer, threading.Thread]:
        wrapper = SimpleNamespace(
            agent=self.service,
            config=SimpleNamespace(server_name=server_name),
            management_security_settings=lambda: {
                "postRequiresJson": True,
                "sameOriginOnly": True,
                "requireToken": False,
            },
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = wrapper
        Handler.static_dir = self.root
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    @staticmethod
    def _json_request(
        port: int,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                body = json.loads(error.read().decode("utf-8"))
            finally:
                error.close()
            return error.code, body

    def _sessions(self) -> tuple[str, str]:
        source = self.service.create_session(
            {
                "title": "source transcript",
                "mode": "coordinator",
                "workspaceRoots": [str(self.root)],
            }
        )["session"]
        diagnostic = self._full_auto_diagnostic_session()
        return str(source["id"]), str(diagnostic["id"])

    def _full_auto_trace_session(
        self,
        title: str,
        *,
        surface_key: str,
        workspace_roots: list[str] | None = None,
    ) -> dict[str, object]:
        return self.service.create_session(
            {
                "title": title,
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:trace-agent",
                "surfaceKey": surface_key,
                "mode": "coordinator",
                "toolProfileVersion": "control-center-auto-approve-v1",
                "executionMode": "full_trust",
                "dangerousModeConfirmation": "ENABLE_FULL_TRUST",
                "workspaceRoots": (
                    workspace_roots
                    if workspace_roots is not None
                    else [str(self.root)]
                ),
                "toolAllowlistMode": "profile",
                "projectContextEnabled": True,
                "piSkillsEnabled": True,
                "codexSkillsEnabled": True,
            }
        )["session"]

    def _full_auto_repair_session(self, title: str) -> dict[str, object]:
        return self._full_auto_trace_session(title, surface_key="repair")

    def _full_auto_diagnostic_session(
        self,
        title: str = "Trace diagnostic",
    ) -> dict[str, object]:
        return self._full_auto_trace_session(title, surface_key="diagnostic")


    @staticmethod
    def _structured_snapshot() -> dict[str, object]:
        result = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "结构化诊断已保存。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
            "presentation": _governed_presentation(),
        }
        return {
            "ok": True,
            "status": "idle",
            "items": [
                {
                    "role": "assistant",
                    "status": "completed",
                    "timelineSequence": 1,
                    "blocks": [
                        {
                            "status": "completed",
                            "data": {
                                "text": (
                                    "--- TRACE_DIAGNOSTIC_RESULT_V1 ---\n"
                                    + json.dumps(result, ensure_ascii=False)
                                    + "\n--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"
                                )
                            },
                        }
                    ],
                }
            ],
        }

    def _create_report(self) -> tuple[str, str, dict[str, object]]:
        source_id, diagnostic_id = self._sessions()
        report = self.service.create_trace_diagnostic_report(
            {
                "diagnosticSessionId": diagnostic_id,
                "title": "自动收束报告",
                "targets": [
                    {"kind": "session", "id": source_id, "title": "source"}
                ],
            }
        )
        return source_id, diagnostic_id, report

    def test_repair_authorization_requires_a_confirmed_full_automation_session(self) -> None:
        repair = self._full_auto_repair_session("Trace full-auto repair")
        payload = {
            "expectedRevision": 2,
            "findingId": "finding:repair",
            "sourceScope": "session:source",
            "sourceTraceId": "trace:source",
            "failureRef": "evidence:failure",
            "repairSessionId": repair["id"],
        }
        with patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            self.assertEqual(
                self.service.authorize_trace_diagnostic_repair("report:repair", payload),
                {"ok": True},
            )
        authorize.assert_called_once_with(
            "report:repair",
            expected_revision=2,
            finding_id="finding:repair",
            source_scope="session:source",
            source_trace_id="trace:source",
            failure_ref="evidence:failure",
            repair_session_id=repair["id"],
        )

        diagnostic = self._full_auto_diagnostic_session("Trace diagnostic is not repair")
        with self.assertRaisesRegex(ValueError, "unrestricted auto-approve profile"):
            self.service.authorize_trace_diagnostic_repair(
                "report:repair",
                {**payload, "repairSessionId": diagnostic["id"]},
            )

        per_action = self.service.create_session(
            {
                "title": "Trace manual repair",
                "mode": "coordinator",
                "toolProfileVersion": "control-center-full-access-v1",
                "executionMode": "per_action",
                "workspaceRoots": ["/"],
            }
        )["session"]
        with self.assertRaisesRegex(ValueError, "unrestricted auto-approve profile"):
            self.service.authorize_trace_diagnostic_repair(
                "report:repair",
                {**payload, "repairSessionId": per_action["id"]},
            )

    def test_repair_authorization_inherits_source_project_with_full_disk_authority(
        self,
    ) -> None:
        source = self.service.create_session(
            {
                "title": "source workspace",
                "mode": "coordinator",
                "executionMode": "per_action",
                "workspaceRoots": [str(self.root)],
            }
        )["session"]
        diagnostic = self._full_auto_trace_session(
            "source-bound diagnostic",
            surface_key="diagnostic",
            workspace_roots=[str(self.root)],
        )
        report = self.service.create_trace_diagnostic_report(
            {
                "diagnosticSessionId": diagnostic["id"],
                "title": "full disk repair authority",
                "targets": [
                    {
                        "kind": "session",
                        "id": source["id"],
                        "title": "source",
                        "traceIds": ["trace:source"],
                    }
                ],
            }
        )
        repair = self._full_auto_trace_session(
            "source-bound full disk repair",
            surface_key="repair",
            workspace_roots=[str(self.root)],
        )
        payload = {
            "expectedRevision": report["revision"],
            "findingId": "finding:repair",
            "sourceScope": f"session:{source['id']}",
            "sourceTraceId": "trace:source",
            "failureRef": "evidence:failure",
            "repairSessionId": repair["id"],
        }

        with patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            self.assertEqual(
                self.service.authorize_trace_diagnostic_repair(
                    str(report["reportId"]),
                    payload,
                ),
                {"ok": True},
            )
        authorize.assert_called_once()

    def test_repair_authorization_rejects_a_different_project_binding(self) -> None:
        source_root = self.root / "source"
        wrong_root = self.root / "wrong"
        source_root.mkdir()
        wrong_root.mkdir()
        source = self.service.create_session(
            {
                "title": "source workspace",
                "mode": "coordinator",
                "executionMode": "per_action",
                "workspaceRoots": [str(source_root)],
            }
        )["session"]
        diagnostic = self._full_auto_trace_session(
            "source-bound diagnostic",
            surface_key="diagnostic",
            workspace_roots=[str(source_root)],
        )
        report = self.service.create_trace_diagnostic_report(
            {
                "diagnosticSessionId": diagnostic["id"],
                "title": "frozen source binding",
                "targets": [
                    {
                        "kind": "session",
                        "id": source["id"],
                        "title": "source",
                        "traceIds": ["trace:source"],
                    }
                ],
            }
        )
        repair = self._full_auto_trace_session(
            "wrong project repair",
            surface_key="repair",
            workspace_roots=[str(wrong_root)],
        )

        with patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            with self.assertRaisesRegex(ValueError, "project workspace binding"):
                self.service.authorize_trace_diagnostic_repair(
                    str(report["reportId"]),
                    {
                        "expectedRevision": report["revision"],
                        "findingId": "finding:repair",
                        "sourceScope": f"session:{source['id']}",
                        "sourceTraceId": "trace:source",
                        "failureRef": "evidence:failure",
                        "repairSessionId": repair["id"],
                    },
                )
        authorize.assert_not_called()

    def test_session_repair_authorization_rejects_cross_target_trace_pairing(self) -> None:
        source_a = self.service.create_session(
            {"title": "source A", "mode": "coordinator", "workspaceRoots": [str(self.root)]}
        )["session"]
        source_b = self.service.create_session(
            {"title": "source B", "mode": "coordinator", "workspaceRoots": [str(self.root)]}
        )["session"]
        repair = self._full_auto_repair_session("session target repair")
        report = {
            "targets": [
                {
                    "targetKey": f"session:{source_a['id']}",
                    "kind": "session",
                    "id": source_a["id"],
                    "traceIds": ["trace:session:a"],
                },
                {
                    "targetKey": f"session:{source_b['id']}",
                    "kind": "session",
                    "id": source_b["id"],
                    "traceIds": ["trace:session:b"],
                },
            ]
        }
        payload = {
            "expectedRevision": 2,
            "findingId": "finding:repair",
            "sourceScope": f"session:{source_a['id']}",
            "sourceTraceId": "trace:session:b",
            "failureRef": "evidence:failure",
            "repairSessionId": repair["id"],
        }

        with patch.object(
            self.service.trace_diagnostic_reports,
            "get",
            return_value=report,
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            with self.assertRaisesRegex(ValueError, "frozen session target"):
                self.service.authorize_trace_diagnostic_repair(
                    "report:session-target",
                    payload,
                )
        authorize.assert_not_called()

        accepted_payload = {
            **payload,
            "sourceTraceId": "trace:session:a",
        }
        with patch.object(
            self.service.trace_diagnostic_reports,
            "get",
            return_value=report,
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            self.assertEqual(
                self.service.authorize_trace_diagnostic_repair(
                    "report:session-target",
                    accepted_payload,
                ),
                {"ok": True},
            )
        authorize.assert_called_once()

    def test_room_repair_authorization_checks_canonical_binding_when_available(self) -> None:
        room_a = "room:source-a"
        room_b = "room:source-b"
        repair = self._full_auto_repair_session("room target repair")
        repair_root = str(repair["workspaceRoots"][0])
        report = {
            "targets": [
                {
                    "targetKey": room_a,
                    "kind": "room",
                    "id": room_a,
                    "traceIds": ["trace:room:a"],
                },
                {
                    "targetKey": room_b,
                    "kind": "room",
                    "id": room_b,
                    "traceIds": ["trace:room:b"],
                },
            ]
        }
        base_payload = {
            "expectedRevision": 2,
            "findingId": "finding:repair",
            "sourceScope": room_a,
            "sourceTraceId": "trace:room:a",
            "failureRef": "evidence:failure",
            "repairSessionId": repair["id"],
        }

        with patch.object(
            self.service,
            "_trace_diagnostic_source_environment",
            side_effect=lambda kind, identifier: {
                "id": identifier,
                "kind": kind,
                "workspaceRoots": [repair_root],
            },
        ), patch.object(
            self.service.rooms,
            "get",
            side_effect=lambda room_id: {"id": room_id, "workspaceRoots": [repair_root]},
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "get",
            return_value=report,
        ), patch.object(
            self.service,
            "observation_trace",
            return_value={"trace": {"binding": {"roomId": room_b}}},
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            with self.assertRaisesRegex(ValueError, "room binding"):
                self.service.authorize_trace_diagnostic_repair(
                    "report:room-target",
                    base_payload,
                )
        authorize.assert_not_called()

        with patch.object(
            self.service,
            "_trace_diagnostic_source_environment",
            side_effect=lambda kind, identifier: {
                "id": identifier,
                "kind": kind,
                "workspaceRoots": [repair_root],
            },
        ), patch.object(
            self.service.rooms,
            "get",
            side_effect=lambda room_id: {"id": room_id, "workspaceRoots": [repair_root]},
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "get",
            return_value=report,
        ), patch.object(
            self.service,
            "observation_trace",
            side_effect=KeyError("trace:room:a"),
        ), patch.object(
            self.service.trace_diagnostic_reports,
            "authorize_repair",
            return_value={"ok": True},
        ) as authorize:
            self.assertEqual(
                self.service.authorize_trace_diagnostic_repair(
                    "report:room-target",
                    base_payload,
                ),
                {"ok": True},
            )
        authorize.assert_called_once()


    def test_run_repair_authorization_validates_trace_binding_without_workspace_fence(
        self,
    ) -> None:
        source = self.service.create_session(
            {
                "title": "run source workspace",
                "mode": "coordinator",
                "executionMode": "per_action",
                "workspaceRoots": [str(self.root)],
            }
        )["session"]
        diagnostic = self._full_auto_diagnostic_session()
        trace_projection = {
            "trace": {
                "traceId": "trace:run-source",
                "binding": {
                    "runId": "run:memory-maintenance",
                    "sessionId": source["id"],
                },
            }
        }
        run_projection = {"items": [{"sessionId": source["id"]}]}
        with patch.object(
            self.service,
            "observation_trace",
            return_value=trace_projection,
        ), patch.object(
            self.service,
            "observation_snapshot",
            return_value=run_projection,
        ):
            report = self.service.create_trace_diagnostic_report(
                {
                    "diagnosticSessionId": diagnostic["id"],
                    "title": "run trace binding",
                    "targets": [
                        {
                            "kind": "run",
                            "id": "run:memory-maintenance",
                            "title": "memory maintenance",
                            "traceIds": ["trace:run-source"],
                        }
                    ],
                }
            )

        repair = self._full_auto_repair_session("run full disk repair")
        payload = {
            "expectedRevision": report["revision"],
            "findingId": "finding:repair",
            "sourceScope": "run:run:memory-maintenance",
            "sourceTraceId": "trace:run-source",
            "failureRef": "evidence:failure",
            "repairSessionId": repair["id"],
        }

        with patch.object(self.service, "observation_trace", return_value=trace_projection), patch.object(
            self.service, "observation_snapshot", return_value=run_projection
        ):
            with patch.object(
                self.service.trace_diagnostic_reports,
                "authorize_repair",
                return_value={"ok": True},
            ) as authorize:
                with self.assertRaisesRegex(ValueError, "frozen run target"):
                    self.service.authorize_trace_diagnostic_repair(
                        str(report["reportId"]),
                        {**payload, "sourceTraceId": "trace:guessed"},
                    )
        authorize.assert_not_called()

        with patch.object(self.service, "observation_trace", return_value=trace_projection), patch.object(
            self.service, "observation_snapshot", return_value=run_projection
        ):
            with patch.object(
                self.service.trace_diagnostic_reports,
                "authorize_repair",
                return_value={"ok": True},
            ) as authorize:
                self.assertEqual(
                    self.service.authorize_trace_diagnostic_repair(
                        str(report["reportId"]),
                        payload,
                    ),
                    {"ok": True},
                )
        authorize.assert_called_once()

    def test_run_repair_authorization_rejects_a_missing_canonical_session_binding(self) -> None:
        diagnostic = self._full_auto_diagnostic_session()
        trace_projection = {
            "trace": {
                "traceId": "trace:unbound-run",
                "binding": {"runId": "run:unbound"},
            }
        }
        with patch.object(self.service, "observation_trace", return_value=trace_projection):
            with self.assertRaisesRegex(ValueError, "binding_required"):
                self.service.create_trace_diagnostic_report(
                    {
                        "diagnosticSessionId": diagnostic["id"],
                        "title": "unbound run",
                        "targets": [
                            {
                                "kind": "run",
                                "id": "run:unbound",
                                "title": "unbound run",
                                "traceIds": ["trace:unbound-run"],
                            }
                        ],
                    }
                )

    def test_terminal_diagnostic_session_finalizes_report_without_trace_page_mounted(self) -> None:
        _source_id, diagnostic_id, report = self._create_report()

        with patch.object(
            self.service,
            "messages",
            return_value=self._structured_snapshot(),
        ):
            self.service.events.publish(
                diagnostic_id,
                "turn_completed",
                {"terminalEvent": "agent_settled"},
                turn_id="turn:diagnostic",
            )
            self.assertTrue(self.service.events.flush())

        persisted = self.service.trace_diagnostic_reports.get(str(report["reportId"]))
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["result"]["summary"], "结构化诊断已保存。")

    def test_get_reconciles_an_older_generating_report_when_result_is_already_terminal(self) -> None:
        _source_id, _diagnostic_id, report = self._create_report()

        with patch.object(
            self.service,
            "messages",
            return_value=self._structured_snapshot(),
        ):
            reconciled = self.service.trace_diagnostic_report(str(report["reportId"]))

        self.assertEqual(reconciled["status"], "completed")
        self.assertEqual(reconciled["result"]["summary"], "结构化诊断已保存。")

    @requires_loopback_bind
    def test_http_create_finalize_list_get_persists_completed_report_in_sqlite(self) -> None:
        source_id, diagnostic_id = self._sessions()
        server, thread = self._server()
        try:
            status, created = self._json_request(
                server.server_port,
                "/api/observability/trace-diagnostic-reports",
                method="POST",
                payload={
                    "diagnosticSessionId": diagnostic_id,
                    "title": "HTTP 持久化报告",
                    "targets": [{"kind": "session", "id": source_id, "title": "source"}],
                },
            )
            self.assertEqual(status, 201)
            self.assertEqual(created["status"], "generating")
            report_id = str(created["reportId"])

            self.service.messages = lambda _session_id: self._structured_snapshot()  # type: ignore[method-assign]
            status, completed = self._json_request(
                server.server_port,
                f"/api/observability/trace-diagnostic-reports/{quote(report_id, safe='')}/finalize",
                method="POST",
                payload={"expectedRevision": 1},
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["revision"], 2)
            with sqlite3.connect(self.db_path) as connection:
                persisted = connection.execute(
                    "SELECT status, current_revision FROM trace_diagnostic_reports WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            self.assertEqual(persisted, ("completed", 2))

            status, listed = self._json_request(
                server.server_port,
                "/api/observability/trace-diagnostic-reports?limit=10",
            )
            self.assertEqual(status, 200)
            self.assertEqual(listed["items"][0]["reportId"], report_id)
            self.assertEqual(listed["items"][0]["status"], "completed")

            status, fetched = self._json_request(
                server.server_port,
                f"/api/observability/trace-diagnostic-reports/{quote(report_id, safe='')}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(fetched["reportId"], report_id)
            self.assertEqual(fetched["result"]["summary"], "结构化诊断已保存。")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @requires_loopback_bind
    def test_http_finalize_persists_failed_report_when_session_has_no_structured_result(self) -> None:
        source_id, diagnostic_id = self._sessions()
        server, thread = self._server()
        try:
            status, created = self._json_request(
                server.server_port,
                "/api/observability/trace-diagnostic-reports",
                method="POST",
                payload={
                    "diagnosticSessionId": diagnostic_id,
                    "title": "HTTP 失败报告",
                    "targets": [{"kind": "session", "id": source_id, "title": "source"}],
                },
            )
            self.assertEqual(status, 201)
            report_id = str(created["reportId"])

            status, failed = self._json_request(
                server.server_port,
                f"/api/observability/trace-diagnostic-reports/{quote(report_id, safe='')}/finalize",
                method="POST",
                payload={"expectedRevision": 1},
            )
            self.assertEqual(status, 200)
            self.assertEqual(failed["status"], "failed")
            self.assertTrue(failed["failureReason"])
            with sqlite3.connect(self.db_path) as connection:
                persisted = connection.execute(
                    "SELECT status, current_revision FROM trace_diagnostic_reports WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            self.assertEqual(persisted, ("failed", 2))

            status, fetched = self._json_request(
                server.server_port,
                f"/api/observability/trace-diagnostic-reports/{quote(report_id, safe='')}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(fetched["status"], "failed")
            self.assertEqual(fetched["failureReason"], failed["failureReason"])
            self.assertIsNone(fetched["result"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @requires_loopback_bind
    def test_remote_agent_gateway_cannot_read_local_diagnostic_report_routes(self) -> None:
        server, thread = self._server(server_name="agent gateway")
        headers = {
            "Host": "paw.example.ts.net",
            "Tailscale-User-Login": "alice@example.com",
        }
        try:
            with patch.dict(os.environ, {"RAG_IME_REMOTE_ALLOWED_LOGINS": "alice@example.com"}):
                status, body = self._json_request(
                    server.server_port,
                    "/api/observability/trace-diagnostic-reports?limit=10",
                    headers=headers,
                )
                self.assertEqual(status, 403)
                self.assertEqual(body["errorCode"], "route_not_allowed")

                status, body = self._json_request(
                    server.server_port,
                    "/control/v1/observability/trace-diagnostic-reports",
                    headers=headers,
                )
                self.assertEqual(status, 404)
                self.assertEqual(body["errorCode"], "route_not_found")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
