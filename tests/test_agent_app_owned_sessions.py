from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_service import AgentService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.control_api import (
    ControlAccessContext,
    ControlApiError,
    ControlPathId,
    ControlRequest,
    ControlScope,
    default_route_policy,
)
from rag_ime.db.migration_runner import (
    apply_database_migrations,
    load_migrations,
)
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi.config import PiRuntimeConfig


class AgentAppOwnedSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-app-owned-sessions-"
        )
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "agent.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_app_owned_conversation_is_persisted_but_not_listed_as_agent(self) -> None:
        agent = self.sessions.create(title="普通 Agent", created_at_ms=100)
        app = self.sessions.create(
            title="掌柜问数 · 问数",
            surface_kind="extension_app",
            owner_app_id="extension:zhanggui-wenshu",
            surface_key="ask",
            created_at_ms=200,
        )

        self.assertEqual(app["sessionKind"], "conversation")
        self.assertEqual(app["surfaceKind"], "extension_app")
        self.assertEqual(app["ownerAppId"], "extension:zhanggui-wenshu")
        self.assertEqual(app["surfaceKey"], "ask")
        validate_contract("agent-session.v1", app)

        self.assertEqual(
            {session["id"] for session in self.sessions.list()},
            {agent["id"], app["id"]},
        )
        self.assertEqual(
            [
                session["id"]
                for session in self.sessions.list(surface_kind="agent")
            ],
            [agent["id"]],
        )
        self.assertEqual(
            [
                session["id"]
                for session in self.sessions.list(
                    surface_kind="extension_app",
                    owner_app_id="extension:zhanggui-wenshu",
                )
            ],
            [app["id"]],
        )
        self.assertEqual(
            [
                session["id"]
                for session in self.sessions.list(
                    surface_kind="extension_app",
                    owner_app_id="extension:zhanggui-wenshu",
                    surface_key="ask",
                )
            ],
            [app["id"]],
        )
        self.assertEqual(
            self.sessions.list(
                surface_kind="extension_app",
                owner_app_id="extension:other-app",
            ),
            [],
        )
        self.assertEqual(self.sessions.search_history(query="掌柜问数"), [])

    def test_store_rejects_incomplete_or_invalid_surface_ownership(self) -> None:
        invalid = (
            {"surface_kind": "extension_app"},
            {
                "surface_kind": "extension_app",
                "owner_app_id": "zhanggui-wenshu",
                "surface_key": "ask",
            },
            {
                "surface_kind": "extension_app",
                "owner_app_id": "extension:zhanggui-wenshu",
                "surface_key": "问数",
            },
            {"owner_app_id": "extension:zhanggui-wenshu"},
        )
        for index, fields in enumerate(invalid):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.sessions.create(title=f"invalid-{index}", **fields)

        with self.assertRaises(ValueError):
            self.sessions.list(surface_kind="extension_app")
        with self.assertRaises(ValueError):
            self.sessions.list(
                surface_kind="agent",
                owner_app_id="extension:zhanggui-wenshu",
            )

    def test_app_owned_keyset_pagination_keeps_filter_bindings_in_order(self) -> None:
        created = [
            self.sessions.create(
                title=f"掌柜问数 · 问数 {index}",
                surface_kind="extension_app",
                owner_app_id="extension:zhanggui-wenshu",
                surface_key="ask",
                created_at_ms=100,
            )
            for index in range(3)
        ]
        expected = [
            str(item["id"])
            for item in sorted(created, key=lambda item: str(item["id"]), reverse=True)
        ]

        first = self.sessions.list_page(
            surface_kind="extension_app",
            owner_app_id="extension:zhanggui-wenshu",
            surface_key="ask",
            limit=2,
        )
        second = self.sessions.list_page(
            surface_kind="extension_app",
            owner_app_id="extension:zhanggui-wenshu",
            surface_key="ask",
            before_updated_at_ms=first["nextBeforeUpdatedAtMs"],
            before_id=first["nextBeforeId"],
            limit=2,
        )

        self.assertEqual(
            [item["id"] for item in first["items"] + second["items"]],
            expected,
        )

    def test_builtin_memory_surface_round_trips_and_rejects_unstable_identity(self) -> None:
        timeline = self.sessions.create(
            title="Memory 时间线",
            surface_kind="builtin_app",
            owner_app_id="memory",
            surface_key="timeline",
        )
        journal = self.sessions.create(
            title="Memory 日记 2026-08-31",
            surface_kind="builtin_app",
            owner_app_id="memory",
            surface_key="journal-2026-08-31",
        )

        self.assertEqual(timeline["sessionKind"], "conversation")
        self.assertEqual(timeline["surfaceKind"], "builtin_app")
        self.assertEqual(timeline["ownerAppId"], "memory")
        self.assertEqual(timeline["surfaceKey"], "timeline")
        validate_contract("agent-session.v1", timeline)
        self.assertEqual(
            [
                item["id"]
                for item in self.sessions.list(
                    surface_kind="builtin_app",
                    owner_app_id="memory",
                    surface_key="journal-2026-08-31",
                )
            ],
            [journal["id"]],
        )
        self.assertEqual(
            {item["id"] for item in self.sessions.list(
                surface_kind="builtin_app",
                owner_app_id="memory",
            )},
            {timeline["id"], journal["id"]},
        )
        self.assertEqual(self.sessions.search_history(query="Memory"), [])

        for fields in (
            {
                "surface_kind": "builtin_app",
                "owner_app_id": "settings",
                "surface_key": "timeline",
            },
            {
                "surface_kind": "builtin_app",
                "owner_app_id": "memory",
                "surface_key": "journal-2026-02-30",
            },
            {
                "surface_kind": "builtin_app",
                "owner_app_id": "memory",
                "surface_key": "preferences",
            },
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.sessions.create(title="invalid builtin surface", **fields)


class AgentAppOwnedSessionApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-app-owned-session-application-"
        )
        self.root = Path(self.temporary.name)
        self.service = AgentService(
            db_path=self.root / "agent.sqlite",
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
        self.temporary.cleanup()

    def test_local_create_and_list_keep_extension_app_conversations_separate(self) -> None:
        agent = self.service.create_session({"title": "普通对话"})["session"]
        app = self.service.create_session(
            {
                "title": "掌柜问数 · 对账",
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:zhanggui-wenshu",
                "surfaceKey": "reconcile",
            }
        )["session"]
        writable_app = self.service.create_session(
            {
                "title": "掌柜问数 · 解释",
                "mode": "coordinator",
                "workspaceRoots": [str(self.root)],
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:zhanggui-wenshu",
                "surfaceKey": "explain",
            }
        )["session"]

        self.assertEqual(
            [session["id"] for session in self.service.list_sessions()["items"]],
            [agent["id"]],
        )
        listed = self.service.list_sessions(
            {
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:zhanggui-wenshu",
                "surfaceKey": "reconcile",
            }
        )
        self.assertEqual([session["id"] for session in listed["items"]], [app["id"]])
        self.assertEqual(writable_app["mode"], "coordinator")
        self.assertEqual(writable_app["workspaceRoots"], [str(self.root.resolve())])

        with self.assertRaises(ValueError):
            self.service.create_session(
                {
                    "title": "invalid",
                    "surfaceKind": "extension_app",
                    "ownerAppId": "extension:zhanggui-wenshu",
                }
            )
        with self.assertRaises(ValueError):
            self.service.list_sessions({"surfaceKind": "extension_app"})

    def test_builtin_memory_surface_ensure_is_atomic_and_reuses_latest_conversation(self) -> None:
        payload = {
            "title": "Memory · 2026-08-31",
            "mode": "assistant",
            "toolProfileVersion": "control-center-v1",
            "executionMode": "per_action",
            "workspaceRoots": [],
            "surfaceKind": "builtin_app",
            "ownerAppId": "memory",
            "surfaceKey": "journal-2026-08-31",
        }

        first = self.service.ensure_surface_session(payload)
        second = self.service.ensure_surface_session({
            **payload,
            "title": "这个标题不参与身份判断",
        })

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["session"]["id"], second["session"]["id"])
        self.assertEqual(
            self.service.list_sessions()["items"],
            [],
        )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self.service.ensure_surface_session({
                    **payload,
                    "title": "Memory · Timeline",
                    "surfaceKey": "timeline",
                }),
                range(8),
            ))
        self.assertEqual(len({item["session"]["id"] for item in results}), 1)
        self.assertEqual(sum(item["created"] is True for item in results), 1)

        self.service.sessions.archive(str(first["session"]["id"]), updated_at_ms=200)
        replacement = self.service.ensure_surface_session(payload)
        self.assertTrue(replacement["created"])
        self.assertNotEqual(replacement["session"]["id"], first["session"]["id"])


class AgentAppOwnedSessionRoutePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_route_policy()

    def test_native_routes_accept_app_ownership_but_remote_routes_reject_it(self) -> None:
        native_create = ControlRequest(
            request_id="native-create",
            path_id=ControlPathId.AGENT_SESSIONS_CREATE.value,
            body={
                "title": "掌柜问数 · 问数",
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:zhanggui-wenshu",
                "surfaceKey": "ask",
            },
        )
        native_list = ControlRequest(
            request_id="native-list",
            path_id=ControlPathId.AGENT_SESSIONS_LIST.value,
            query={
                "surfaceKind": "extension_app",
                "ownerAppId": "extension:zhanggui-wenshu",
                "surfaceKey": "ask",
            },
        )

        self.policy.authorize(native_create, ControlAccessContext.native())
        self.policy.authorize(native_list, ControlAccessContext.native())

        remote_context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_READ.value, ControlScope.AGENT_WRITE.value},
        )
        with self.assertRaises(ControlApiError):
            self.policy.authorize(native_create, remote_context)
        with self.assertRaises(ControlApiError):
            self.policy.authorize(native_list, remote_context)

    def test_local_http_list_forwards_app_surface_filters(self) -> None:
        received: list[dict[str, object]] = []

        class AgentRecorder:
            def list_sessions(self, payload):
                received.append(dict(payload))
                return {
                    "schemaVersion": "rag-ime.agent-session-list.v1",
                    "ok": True,
                    "items": [],
                }

        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = SimpleNamespace(agent=AgentRecorder())
        handler.path = (
            "/api/agent/sessions?surfaceKind=extension_app"
            "&ownerAppId=extension%3Azhanggui-wenshu&surfaceKey=ask"
        )
        handler._authorize_gateway_request = lambda _method, _parsed: True
        handler._serve_gateway_static = lambda _path: False
        written: list[tuple[HTTPStatus, dict[str, object]]] = []
        handler._write_json = lambda status, body: written.append((status, body))

        handler.do_GET()

        self.assertEqual(written[0][0], HTTPStatus.OK)
        self.assertEqual(received[0]["surfaceKind"], "extension_app")
        self.assertEqual(received[0]["ownerAppId"], "extension:zhanggui-wenshu")
        self.assertEqual(received[0]["surfaceKey"], "ask")

    def test_builtin_surface_ensure_is_loopback_only(self) -> None:
        request = ControlRequest(
            request_id="memory-surface-ensure",
            path_id="agent.sessions.surface.ensure",
            body={
                "title": "Memory · Timeline",
                "mode": "assistant",
                "toolProfileVersion": "control-center-v1",
                "executionMode": "per_action",
                "workspaceRoots": [],
                "surfaceKind": "builtin_app",
                "ownerAppId": "memory",
                "surfaceKey": "timeline",
            },
        )

        self.policy.authorize(request, ControlAccessContext.native())
        with self.assertRaises(ControlApiError):
            self.policy.authorize(
                request,
                ControlAccessContext.remote(
                    device_id="phone-1",
                    scopes={ControlScope.AGENT_WRITE.value},
                ),
            )

    def test_local_http_surface_ensure_forwards_to_atomic_application(self) -> None:
        payload = {
            "title": "Memory · Timeline",
            "mode": "assistant",
            "toolProfileVersion": "control-center-v1",
            "executionMode": "per_action",
            "workspaceRoots": [],
            "surfaceKind": "builtin_app",
            "ownerAppId": "memory",
            "surfaceKey": "timeline",
        }
        received: list[dict[str, object]] = []

        class AgentRecorder:
            def ensure_surface_session(self, value):
                received.append(dict(value))
                return {"ok": True, "created": False, "session": {"id": "agent:memory"}}

        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = SimpleNamespace(agent=AgentRecorder())
        handler.path = "/api/agent/sessions/surface/ensure"
        handler._authorize_gateway_request = lambda _method, _parsed: True
        handler._management_post_security_error = lambda _path, require_json=True: None
        handler._read_json = lambda: payload
        written: list[tuple[HTTPStatus, dict[str, object]]] = []
        handler._write_json = lambda status, body: written.append((status, body))

        handler.do_POST()

        self.assertEqual(received, [payload])
        self.assertEqual(written[0][0], HTTPStatus.OK)
        self.assertFalse(written[0][1]["created"])


class AgentAppOwnedSessionMigrationTests(unittest.TestCase):
    def test_0177_migrates_only_exact_zhanggui_mode_titles(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rag-ime-app-session-migration-"
        ) as temporary:
            migrations_0176 = Path(temporary) / "migrations-0176"
            migrations_0176.mkdir()
            for migration in load_migrations():
                if migration.version <= 176:
                    shutil.copy2(migration.path, migrations_0176 / migration.path.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                apply_database_migrations(conn, migrations_dir=migrations_0176)
                conn.executemany(
                    """
                    INSERT INTO agent_sessions(
                        id, title, session_mode, role_id, role_version,
                        model_profile, tool_profile_version, created_at_ms,
                        updated_at_ms, last_opened_at_ms, status
                    ) VALUES (?, ?, 'assistant', 'companion-future-v1', '1',
                              'test/model', 'control-center-v1', 1, 1, 1, 'idle')
                    """,
                    (
                        ("agent:ask", "掌柜问数 · 问数"),
                        ("agent:reconcile", "掌柜问数 · 对账"),
                        ("agent:explain", "掌柜问数 · 解释"),
                        ("agent:ordinary", "掌柜问数历史说明"),
                    ),
                )

                upgraded = apply_database_migrations(conn)

                self.assertEqual(upgraded.applied_versions[:3], (177, 178, 179))
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT id, surface_kind, owner_app_id, surface_key
                        FROM agent_sessions ORDER BY id
                        """
                    ).fetchall(),
                    [
                        (
                            "agent:ask",
                            "extension_app",
                            "extension:zhanggui-wenshu",
                            "ask",
                        ),
                        (
                            "agent:explain",
                            "extension_app",
                            "extension:zhanggui-wenshu",
                            "explain",
                        ),
                        ("agent:ordinary", "agent", "", ""),
                        (
                            "agent:reconcile",
                            "extension_app",
                            "extension:zhanggui-wenshu",
                            "reconcile",
                        ),
                    ],
                )

    def test_0178_expands_surface_kind_without_losing_rows_indexes_or_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rag-ime-builtin-session-migration-"
        ) as temporary:
            migrations_0177 = Path(temporary) / "migrations-0177"
            migrations_0177.mkdir()
            for migration in load_migrations():
                if migration.version <= 177:
                    shutil.copy2(migration.path, migrations_0177 / migration.path.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                apply_database_migrations(conn, migrations_dir=migrations_0177)
                conn.execute(
                    """
                    INSERT INTO agent_sessions(
                        id, title, session_mode, role_id, role_version,
                        model_profile, tool_profile_version, created_at_ms,
                        updated_at_ms, last_opened_at_ms, status,
                        surface_kind, owner_app_id, surface_key
                    ) VALUES (
                        'agent:existing', 'Existing App', 'assistant',
                        'companion-future-v1', '1', 'test/model',
                        'control-center-v1', 1, 1, 1, 'idle',
                        'extension_app', 'extension:existing', 'main'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO agent_approvals(
                        approval_id, session_id, tool_name, operation,
                        payload_sha256, risk_level, state,
                        requested_at_ms, expires_at_ms
                    ) VALUES (
                        'approval:existing', 'agent:existing', 'memory', 'read',
                        ?, 'R1', 'pending', 1, 2
                    )
                    """,
                    ("a" * 64,),
                )

                upgraded = apply_database_migrations(conn)

                self.assertEqual(upgraded.applied_versions[:2], (178, 179))
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT surface_kind, owner_app_id, surface_key
                        FROM agent_sessions WHERE id = 'agent:existing'
                        """
                    ).fetchone(),
                    ("extension_app", "extension:existing", "main"),
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT session_id FROM agent_approvals WHERE approval_id = 'approval:existing'"
                    ).fetchone(),
                    ("agent:existing",),
                )
                self.assertIn(
                    "idx_agent_sessions_surface_recent",
                    {row[1] for row in conn.execute("PRAGMA index_list(agent_sessions)")},
                )
                self.assertNotIn(
                    "surface_kind_v177",
                    {row[1] for row in conn.execute("PRAGMA table_info(agent_sessions)")},
                )
                conn.execute(
                    """
                    INSERT INTO agent_sessions(
                        id, title, session_mode, role_id, role_version,
                        model_profile, tool_profile_version, created_at_ms,
                        updated_at_ms, last_opened_at_ms, status,
                        surface_kind, owner_app_id, surface_key
                    ) VALUES (
                        'agent:memory', 'Memory Timeline', 'assistant',
                        'companion-future-v1', '1', 'test/model',
                        'control-center-v1', 2, 2, 2, 'idle',
                        'builtin_app', 'memory', 'timeline'
                    )
                    """
                )


if __name__ == "__main__":
    unittest.main()
