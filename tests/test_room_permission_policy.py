from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.rooms.participants import project_room_participant_policy
from rag_ime.rooms.store import AgentRoomStore
from rag_ime.agent_service import AgentService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tool_ids import (
    FULL_ACCESS_TOOL_PROFILE,
    READONLY_TOOL_PROFILE,
)
from rag_ime.pi.config import PiRuntimeConfig
from rag_ime.room_permission_policy import (
    ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
    default_room_permission_policy,
    normalize_room_permission_policy,
    resolve_room_permission_policy,
)


class RoomPermissionPolicyTests(unittest.TestCase):
    def test_canonical_schema_version_round_trips_and_defaults_are_kind_specific(self) -> None:
        collaboration = default_room_permission_policy("collaboration")
        self.assertEqual(
            collaboration,
            {
                "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                "room": {"executionMode": "full_trust"},
                "partner": {"executionMode": "inherit"},
                "toolAgent": {"executionMode": "inherit"},
            },
        )
        self.assertEqual(normalize_room_permission_policy(collaboration), collaboration)
        self.assertEqual(
            resolve_room_permission_policy(collaboration),
            {
                "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                "room": {"executionMode": "full_trust"},
                "partner": {"executionMode": "full_trust"},
                "toolAgent": {"executionMode": "full_trust"},
            },
        )
        roleplay = default_room_permission_policy("roleplay")
        self.assertEqual(roleplay["room"]["executionMode"], "per_action")
        self.assertEqual(
            normalize_room_permission_policy(
                {
                    "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                    "room": {"executionMode": "read_only"},
                    "partner": {"executionMode": "inherit"},
                    "toolAgent": {"executionMode": "inherit"},
                },
                room_kind="roleplay",
            )["room"]["executionMode"],
            "read_only",
        )

    def test_missing_or_wrong_schema_version_is_rejected(self) -> None:
        policy = default_room_permission_policy()
        missing = dict(policy)
        missing.pop("schemaVersion")
        with self.assertRaisesRegex(ValueError, "schemaVersion"):
            normalize_room_permission_policy(missing)
        wrong = {**policy, "schemaVersion": "rag-ime.room-permission-policy.v0"}
        with self.assertRaisesRegex(ValueError, "schemaVersion"):
            normalize_room_permission_policy(wrong)

    def test_child_layers_cannot_widen_parent_and_roleplay_cannot_elevate(self) -> None:
        with self.assertRaisesRegex(ValueError, "partner permission"):
            normalize_room_permission_policy(
                {
                    "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                    "room": {"executionMode": "read_only"},
                    "partner": {"executionMode": "per_action"},
                    "toolAgent": {"executionMode": "inherit"},
                }
            )
        with self.assertRaisesRegex(ValueError, "Tool-Agent permission"):
            normalize_room_permission_policy(
                {
                    "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                    "room": {"executionMode": "per_action"},
                    "partner": {"executionMode": "per_action"},
                    "toolAgent": {"executionMode": "workspace_managed"},
                }
            )
        for mode in ("workspace_managed", "full_trust"):
            with self.assertRaisesRegex(ValueError, "roleplay"):
                normalize_room_permission_policy(
                    {
                        "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
                        "room": {"executionMode": mode},
                        "partner": {"executionMode": "inherit"},
                        "toolAgent": {"executionMode": "inherit"},
                    },
                    room_kind="roleplay",
                )

    def test_migration_uniform_and_mixed_backfill_is_deterministic(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE agent_rooms(
                id TEXT PRIMARY KEY,
                room_kind TEXT NOT NULL,
                execution_mode TEXT NOT NULL DEFAULT 'workspace_managed'
            );
            CREATE TABLE agent_room_participants(
                room_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                participant_status TEXT NOT NULL
            );
            CREATE TABLE agent_sessions(
                id TEXT PRIMARY KEY,
                execution_mode TEXT NOT NULL
            );
            INSERT INTO agent_rooms(id, room_kind) VALUES
                ('uniform', 'collaboration'),
                ('mixed', 'collaboration'),
                ('missing', 'collaboration'),
                ('roleplay', 'roleplay');
            INSERT INTO agent_sessions(id, execution_mode) VALUES
                ('uniform-a', 'full_trust'),
                ('uniform-b', 'full_trust'),
                ('mixed-a', 'read_only'),
                ('mixed-b', 'full_trust');
            INSERT INTO agent_room_participants(room_id, session_id, participant_status) VALUES
                ('uniform', 'uniform-a', 'active'),
                ('uniform', 'uniform-b', 'active'),
                ('mixed', 'mixed-a', 'active'),
                ('mixed', 'mixed-b', 'active'),
                ('missing', 'not-present', 'active');
            """
        )
        migration = Path(__file__).parents[1] / "rag_ime/db/migrations/0186_room_permission_policy.sql"
        conn.executescript(migration.read_text(encoding="utf-8"))
        modes = dict(conn.execute("SELECT id, execution_mode FROM agent_rooms"))
        self.assertEqual(modes["uniform"], "full_trust")
        self.assertEqual(modes["mixed"], "per_action")
        self.assertEqual(modes["missing"], "per_action")
        self.assertEqual(modes["roleplay"], "per_action")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_rooms)")}
        self.assertIn("partner_execution_mode", columns)
        self.assertIn("tool_agent_execution_mode", columns)
        conn.close()

    def test_participant_policy_narrowing_preserves_full_access_system_root(self) -> None:
        full_access = {
            "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
            "room": {"executionMode": "full_trust"},
            "partner": {"executionMode": "per_action"},
            "toolAgent": {"executionMode": "inherit"},
        }
        policy = project_room_participant_policy(
            {"roomKind": "collaboration", "permissionPolicy": full_access},
            permission_policy=full_access,
            workspace_roots=[],
        )
        self.assertEqual(policy.execution_mode, "per_action")
        self.assertEqual(policy.tool_profile_version, FULL_ACCESS_TOOL_PROFILE)
        self.assertEqual(policy.workspace_roots, ("/",))
        read_only = {
            **full_access,
            "partner": {"executionMode": "read_only"},
            "toolAgent": {"executionMode": "inherit"},
        }
        narrowed = project_room_participant_policy(
            {"roomKind": "collaboration", "permissionPolicy": read_only},
            permission_policy=read_only,
            workspace_roots=[],
        )
        self.assertEqual(narrowed.execution_mode, "read_only")
        self.assertEqual(narrowed.tool_profile_version, READONLY_TOOL_PROFILE)
        self.assertFalse(narrowed.unrestricted)
        self.assertEqual(narrowed.workspace_roots, ())


class RoomStorePermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-policy-")
        root = Path(self.tmp.name)
        self.sessions = AgentSessionStore(root / "agent.sqlite")
        self.sessions.initialize()
        self.store = AgentRoomStore(root / "agent.sqlite", room_dir=root / "rooms")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _participant(self, role_id: str, name: str) -> dict[str, str]:
        session = self.sessions.create(title=name, role_id=role_id, role_version="1")
        return {
            "sessionId": str(session["id"]),
            "roleId": role_id,
            "roleVersion": "1",
            "displayName": name,
        }

    def test_permission_policy_round_trip_and_permission_only_update(self) -> None:
        room = self.store.create(
            title="Policy Room",
            routing_policy="manual_mentions",
            participants=[
                self._participant("companion-present-v1", "A"),
                self._participant("companion-future-v1", "B"),
            ],
        )
        self.assertEqual(room["executionMode"], "full_trust")
        self.assertEqual(room["permissionPolicy"]["schemaVersion"], ROOM_PERMISSION_POLICY_SCHEMA_VERSION)
        narrowed = {
            "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
            "room": {"executionMode": "full_trust"},
            "partner": {"executionMode": "per_action"},
            "toolAgent": {"executionMode": "inherit"},
        }
        updated = self.store.update_config(str(room["id"]), {"permissionPolicy": narrowed})
        self.assertEqual(updated["permissionPolicy"], narrowed)
        self.assertEqual(updated["executionMode"], "full_trust")

    def test_legacy_and_nested_execution_modes_must_match(self) -> None:
        room = self.store.create(
            title="Mismatch Room",
            routing_policy="manual_mentions",
            participants=[
                self._participant("companion-present-v1", "A"),
                self._participant("companion-future-v1", "B"),
            ],
        )
        policy = room["permissionPolicy"]
        with self.assertRaisesRegex(ValueError, "must match"):
            self.store.update_config(
                str(room["id"]),
                {"permissionPolicy": policy, "executionMode": "per_action"},
            )


class AgentServiceRoomPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-policy-service-")
        root = Path(self.tmp.name)
        self.service = AgentService(
            db_path=root / "agent.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=root / "agent-config",
                session_dir=root / "sessions",
                logs_dir=root / "logs",
            ),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def _create(self) -> dict[str, object]:
        return self.service.create_room(
            {
                "title": "Policy context Room",
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]

    def test_active_membership_context_exposes_policy_without_room_bound_turn(self) -> None:
        room = self._create()
        session_id = str(room["participants"][0]["sessionId"])
        context = self.service._room_delegation_context(session_id)
        self.assertFalse(context["roomBound"])
        self.assertEqual(context["roomId"], "")
        self.assertEqual(context["permissionPolicy"], room["permissionPolicy"])
        self.assertEqual(context["permissionPolicySource"], "room")

    def test_narrowing_clears_full_trust_room_overlay(self) -> None:
        room = self._create()
        room_id = str(room["id"])
        session_ids = [str(item["sessionId"]) for item in room["participants"]]
        self.assertTrue(
            all(
                self.service.sessions.get(session_id)["roomExecutionMode"]
                == "room_unrestricted"
                for session_id in session_ids
            )
        )
        narrowed = {
            "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
            "room": {"executionMode": "full_trust"},
            "partner": {"executionMode": "read_only"},
            "toolAgent": {"executionMode": "inherit"},
        }
        self.service.update_room(room_id, {"permissionPolicy": narrowed})
        self.assertTrue(
            all(
                self.service.sessions.get(session_id)["roomExecutionMode"] == ""
                for session_id in session_ids
            )
        )


if __name__ == "__main__":
    unittest.main()
