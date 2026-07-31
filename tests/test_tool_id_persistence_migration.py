from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.db.migration_runner import (
    apply_database_migrations,
    load_migrations,
)


LEGACY_TOOL_IDS = {
    "ime_overview": "overview",
    "ime_input": "input",
    "ime_voice": "voice",
    "ime_planning": "planning",
    "ime_memory": "memory",
    "ime_knowledge": "knowledge",
    "ime_models": "models",
    "ime_runtime": "runtime",
    "ime_configuration": "configuration",
    "ime_agents": "agents",
    "ime_browser": "browser",
    "ime_plugins": "plugins",
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _contains_legacy_tool_id(value: object) -> bool:
    if isinstance(value, str):
        return value in LEGACY_TOOL_IDS or value in {
            f"tool:{tool_id}" for tool_id in LEGACY_TOOL_IDS
        }
    if isinstance(value, list):
        return any(_contains_legacy_tool_id(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_legacy_tool_id(key) or _contains_legacy_tool_id(item)
            for key, item in value.items()
        )
    return False


class ProjectToolIdPersistenceMigrationTests(unittest.TestCase):
    def _pre_cutover_migrations(self, root: Path) -> Path:
        migrations = root / "migrations"
        migrations.mkdir()
        for migration in load_migrations():
            if migration.version < 118:
                shutil.copy2(migration.path, migrations / migration.path.name)
        return migrations

    def _insert_session(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        *,
        session_file: str = "",
    ) -> None:
        conn.execute(
            """
            INSERT INTO agent_sessions(
                id, session_file, title, session_mode, role_id, role_version,
                model_profile, tool_profile_version, created_at_ms, updated_at_ms,
                last_opened_at_ms, status
            ) VALUES (?, ?, ?, 'assistant', 'assistant', 'v1', 'pi/default',
                      'control-center-v1', 1, 1, 1, 'idle')
            """,
            (session_id, session_file, session_id),
        )

    def _insert_manifest_binding(
        self,
        conn: sqlite3.Connection,
        *,
        suffix: str,
        state: str,
        manifest_payload: object,
        room_binding: object,
        participant_binding: object,
        capability_epoch: int = 4,
    ) -> None:
        manifest_id = f"manifest-{suffix}"
        manifest_hash = suffix[0] * 64
        conn.execute(
            """
            INSERT INTO room_v2_capability_manifests(
                manifest_id, binding_id, room_id, root_id, task_id, dispatch_id,
                generation, capability_revision, capability_epoch, manifest_hash,
                payload_json, created_at_ms
            ) VALUES (?, ?, ?, ?, '', ?, 1, 'revision-1', ?, ?, ?, 10)
            """,
            (
                manifest_id,
                f"binding-{suffix}",
                f"room-{suffix}",
                f"root-{suffix}",
                f"dispatch-{suffix}",
                capability_epoch,
                manifest_hash,
                _json(manifest_payload),
            ),
        )
        conn.execute(
            """
            INSERT INTO room_v2_capability_runtime_bindings(
                session_id, manifest_id, manifest_hash, prompt_compile_receipt_id,
                prompt_plan_hash, compiled_profile_id, compiled_profile_revision,
                compiled_profile_hash, room_binding_json, participant_binding_json,
                capability_epoch, state, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, '1', ?, ?, ?, ?, ?, 10, 10)
            """,
            (
                f"room-session-{suffix}",
                manifest_id,
                manifest_hash,
                f"compile-{suffix}",
                f"plan-{suffix}",
                f"profile-{suffix}",
                f"profile-hash-{suffix}",
                _json(room_binding),
                _json(participant_binding),
                capability_epoch,
                state,
            ),
        )

    def test_0118_rewrites_only_active_configuration_and_invalidates_old_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-tool-id-cutover-") as temporary:
            root = Path(temporary)
            pre_cutover = self._pre_cutover_migrations(root)
            pi_history = root / "pi-session.jsonl"
            pi_history_bytes = (
                b'{"type":"toolCall","toolId":"ime_memory"}\n'
                b'{"type":"message","text":"immutable"}\n'
            )
            pi_history.write_bytes(pi_history_bytes)
            with closing(sqlite3.connect(":memory:")) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                apply_database_migrations(conn, migrations_dir=pre_cutover)
                with conn:
                    self._insert_session(
                        conn,
                        "session-main",
                        session_file=str(pi_history),
                    )
                    conn.execute(
                        """
                        INSERT INTO agent_session_tool_policies(
                            session_id, allowed_tools_json, disclosure_preferences_json,
                            policy_revision, updated_at_ms
                        ) VALUES (?, ?, ?, 7, 20)
                        """,
                        (
                            "session-main",
                            _json(
                                [
                                    *LEGACY_TOOL_IDS,
                                    "custom_ime_memory_extension",
                                    "rag_ime",
                                ]
                            ),
                            _json(
                                {
                                    "tool:ime_memory": "enabled",
                                    "tool:ime_plugins": "inherit",
                                    "tool:ime_memory_extra": "disabled",
                                    "ime_memory": "disabled",
                                }
                            ),
                        ),
                    )
                    configuration = {
                        "runtime": {
                            "enabled": True,
                            "startup": "lazy",
                            "idleTimeoutSeconds": 600,
                        },
                        "sessionDefaults": {
                            "resumeLastSession": True,
                            "roleId": "assistant",
                            "roleVersion": "v1",
                            "modelProfile": "pi/default",
                            "toolProfileVersion": "control-center-v1",
                            "capabilityDisclosurePreferences": {
                                "tool:ime_input": "inherit",
                                "tool:ime_browser_suffix": "disabled",
                                "ime_input": "enabled",
                            },
                        },
                        "coordination": {"enabled": True},
                        "capabilityDisclosure": {
                            "projectPreferences": {
                                "project-a": {
                                    "tool:ime_agents": "enabled",
                                    "tool:ime_agents_extra": "inherit",
                                },
                                "project-b": {"tool:ime_knowledge": "disabled"},
                            }
                        },
                    }
                    conn.execute(
                        """
                        INSERT INTO agent_configuration_state(
                            singleton_id, revision, configuration_json,
                            applied_revision, sync_state, sync_error,
                            updated_at_ms, updated_by
                        ) VALUES (1, 5, ?, 5, 'synchronized', '', 20, 'owner')
                        """,
                        (_json(configuration),),
                    )
                    approvals = (
                        ("pending-old", "ime_runtime", "pending"),
                        ("approved-old", "ime_voice", "approved"),
                        ("external-old", "ime_configuration", "external_pending"),
                        ("terminal-old", "ime_memory", "applied"),
                        ("pending-substring", "ime_memory_extension", "pending"),
                        ("pending-new", "memory", "pending"),
                    )
                    for approval_id, tool_name, state in approvals:
                        conn.execute(
                            """
                            INSERT INTO agent_approvals(
                                approval_id, session_id, tool_name, operation,
                                payload_sha256, preview_json, risk_level, state,
                                requested_at_ms, expires_at_ms, decided_at_ms,
                                decided_by, receipt_json
                            ) VALUES (?, 'session-main', ?, 'get', 'payload', ?, 'R1', ?,
                                      10, 9999, ?, ?, ?)
                            """,
                            (
                                approval_id,
                                tool_name,
                                _json({"toolId": tool_name}),
                                state,
                                30 if state == "applied" else None,
                                "owner" if state == "applied" else "",
                                _json({"toolId": tool_name, "evidence": "keep"})
                                if state == "applied"
                                else None,
                            ),
                        )
                    conn.execute(
                        """
                        INSERT INTO agent_runtime_events(
                            event_id, session_id, sequence, event_type,
                            created_at_ms, redacted_summary, metrics_json
                        ) VALUES ('event-old', 'session-main', 1, 'tool_result', 20,
                                  'ime_memory completed', ?)
                        """,
                        (_json({"toolId": "ime_memory"}),),
                    )
                    conn.execute(
                        """
                        INSERT INTO agent_control_events(
                            sequence, event_id, event_type, payload_json, created_at_ms
                        ) VALUES (1, 'control-old', 'configuration_changed', ?, 20)
                        """,
                        (_json({"tool:ime_memory": "enabled"}),),
                    )
                    self._insert_manifest_binding(
                        conn,
                        suffix="a",
                        state="active",
                        manifest_payload={"tools": [{"id": "ime_browser"}]},
                        room_binding={"roomId": "room-a"},
                        participant_binding={"participantId": "participant-a"},
                    )
                    self._insert_manifest_binding(
                        conn,
                        suffix="b",
                        state="prepared",
                        manifest_payload={"tools": [{"id": "memory"}]},
                        room_binding={"tool": "ime_planning"},
                        participant_binding={"participantId": "participant-b"},
                    )
                    self._insert_manifest_binding(
                        conn,
                        suffix="c",
                        state="active",
                        manifest_payload={"tools": [{"id": "custom_ime_browser"}]},
                        room_binding={"roomId": "room-c"},
                        participant_binding={"capability": "tool:ime_voice"},
                    )
                    self._insert_manifest_binding(
                        conn,
                        suffix="d",
                        state="active",
                        manifest_payload={"tools": [{"id": "ime_browser_extension"}]},
                        room_binding={"note": "uses ime_memory internally"},
                        participant_binding={"capability": "tool:ime_voice_extra"},
                    )
                    self._insert_manifest_binding(
                        conn,
                        suffix="e",
                        state="revoked",
                        manifest_payload={"tools": [{"id": "ime_models"}]},
                        room_binding={"tool": "ime_models"},
                        participant_binding={},
                        capability_epoch=9,
                    )
                    conn.execute(
                        """
                        INSERT INTO room_v2_tool_disclosure_receipts(
                            receipt_id, manifest_id, manifest_hash, receipt_kind,
                            query_text, tool_name, schema_hash, payload_hash,
                            payload_json, created_at_ms
                        ) VALUES ('disclosure-old', 'manifest-a', ?, 'load', '',
                                  'ime_browser', 'schema', ?, ?, 21)
                        """,
                        ("a" * 64, "f" * 64, _json({"toolId": "ime_browser"})),
                    )
                    conn.execute(
                        """
                        INSERT INTO room_v2_tool_invocation_receipts(
                            receipt_id, manifest_id, manifest_hash, load_receipt_id,
                            invocation_key, canonical_tool_name, original_tool_name,
                            command_hash, command_json, authorization_state, created_at_ms
                        ) VALUES ('invocation-old', 'manifest-a', ?, 'disclosure-old',
                                  'invoke-1', 'ime_browser', 'ime_browser', ?, ?,
                                  'authorized', 22)
                        """,
                        ("a" * 64, "e" * 64, _json({"toolId": "ime_browser"})),
                    )
                    conn.execute(
                        """
                        INSERT INTO room_v2_tool_execution_receipts(
                            execution_receipt_id, invocation_receipt_id,
                            session_id, tool_name, status, result_hash,
                            payload_json, created_at_ms
                        ) VALUES ('execution-old', 'invocation-old', 'room-session-a',
                                  'ime_browser', 'applied', 'result', ?, 23)
                        """,
                        (_json({"toolId": "ime_browser", "status": "applied"}),),
                    )

                immutable_before = {
                    "terminal_approval": conn.execute(
                        "SELECT * FROM agent_approvals WHERE approval_id = 'terminal-old'"
                    ).fetchone(),
                    "runtime_event": conn.execute(
                        "SELECT * FROM agent_runtime_events WHERE event_id = 'event-old'"
                    ).fetchone(),
                    "control_event": conn.execute(
                        "SELECT * FROM agent_control_events WHERE event_id = 'control-old'"
                    ).fetchone(),
                    "manifests": conn.execute(
                        "SELECT * FROM room_v2_capability_manifests ORDER BY manifest_id"
                    ).fetchall(),
                    "disclosure_receipt": conn.execute(
                        "SELECT * FROM room_v2_tool_disclosure_receipts"
                    ).fetchone(),
                    "invocation_receipt": conn.execute(
                        "SELECT * FROM room_v2_tool_invocation_receipts"
                    ).fetchone(),
                    "execution_receipt": conn.execute(
                        "SELECT * FROM room_v2_tool_execution_receipts"
                    ).fetchone(),
                }

                upgraded = apply_database_migrations(conn, applied_at_ms=1000)
                self.assertEqual(
                    upgraded.applied_versions,
                    (118, 119, 120, 121, 122, 123, 124, 125, 126),
                )

                policy = conn.execute(
                    """
                    SELECT allowed_tools_json, disclosure_preferences_json,
                           policy_revision, updated_at_ms
                    FROM agent_session_tool_policies
                    WHERE session_id = 'session-main'
                    """
                ).fetchone()
                self.assertEqual(
                    json.loads(policy[0]),
                    [
                        *LEGACY_TOOL_IDS.values(),
                        "custom_ime_memory_extension",
                        "rag_ime",
                    ],
                )
                self.assertEqual(
                    json.loads(policy[1]),
                    {
                        "tool:memory": "enabled",
                        "tool:plugins": "inherit",
                        "tool:ime_memory_extra": "disabled",
                        "ime_memory": "disabled",
                    },
                )
                self.assertEqual(policy[2:], (8, 1000))

                configuration_row = conn.execute(
                    """
                    SELECT revision, configuration_json, applied_revision,
                           sync_state, updated_at_ms, updated_by
                    FROM agent_configuration_state WHERE singleton_id = 1
                    """
                ).fetchone()
                migrated_configuration = json.loads(configuration_row[1])
                self.assertEqual(configuration_row[0], 6)
                self.assertEqual(configuration_row[2:], (6, "synchronized", 1000, "tool-id-cutover"))
                self.assertEqual(
                    migrated_configuration["sessionDefaults"]
                    ["capabilityDisclosurePreferences"],
                    {
                        "tool:input": "inherit",
                        "tool:ime_browser_suffix": "disabled",
                        "ime_input": "enabled",
                    },
                )
                self.assertEqual(
                    migrated_configuration["capabilityDisclosure"]["projectPreferences"],
                    {
                        "project-a": {
                            "tool:agents": "enabled",
                            "tool:ime_agents_extra": "inherit",
                        },
                        "project-b": {"tool:knowledge": "disabled"},
                    },
                )

                approval_states = {
                    row[0]: tuple(row[1:])
                    for row in conn.execute(
                        """
                        SELECT approval_id, tool_name, state, expires_at_ms,
                               decided_at_ms, decided_by
                        FROM agent_approvals ORDER BY approval_id
                        """
                    )
                }
                self.assertEqual(
                    approval_states["pending-old"],
                    ("ime_runtime", "expired", 1000, 1000, "tool-id-cutover"),
                )
                self.assertEqual(
                    approval_states["approved-old"],
                    ("ime_voice", "expired", 1000, 1000, "tool-id-cutover"),
                )
                self.assertEqual(
                    approval_states["external-old"],
                    ("ime_configuration", "expired", 1000, 1000, "tool-id-cutover"),
                )
                self.assertEqual(approval_states["terminal-old"][1], "applied")
                self.assertEqual(approval_states["pending-substring"][1], "pending")
                self.assertEqual(approval_states["pending-new"][1], "pending")

                bindings = {
                    row[0]: tuple(row[1:])
                    for row in conn.execute(
                        """
                        SELECT manifest_id, state, capability_epoch, manifest_hash,
                               room_binding_json, participant_binding_json
                        FROM room_v2_capability_runtime_bindings ORDER BY manifest_id
                        """
                    )
                }
                self.assertEqual(bindings["manifest-a"][:2], ("revoked", 5))
                self.assertEqual(bindings["manifest-b"][:2], ("revoked", 5))
                self.assertEqual(bindings["manifest-c"][:2], ("revoked", 5))
                self.assertEqual(bindings["manifest-d"][:2], ("active", 4))
                self.assertEqual(bindings["manifest-e"][:2], ("revoked", 9))
                self.assertEqual(bindings["manifest-a"][2], "a" * 64)
                self.assertEqual(json.loads(bindings["manifest-b"][3]), {"tool": "ime_planning"})
                self.assertEqual(
                    json.loads(bindings["manifest-c"][4]),
                    {"capability": "tool:ime_voice"},
                )

                self.assertEqual(
                    conn.execute(
                        "SELECT * FROM agent_approvals WHERE approval_id = 'terminal-old'"
                    ).fetchone(),
                    immutable_before["terminal_approval"],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT * FROM agent_runtime_events WHERE event_id = 'event-old'"
                    ).fetchone(),
                    immutable_before["runtime_event"],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT * FROM agent_control_events WHERE event_id = 'control-old'"
                    ).fetchone(),
                    immutable_before["control_event"],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT * FROM room_v2_capability_manifests ORDER BY manifest_id"
                    ).fetchall(),
                    immutable_before["manifests"],
                )
                self.assertEqual(
                    conn.execute("SELECT * FROM room_v2_tool_disclosure_receipts").fetchone(),
                    immutable_before["disclosure_receipt"],
                )
                self.assertEqual(
                    conn.execute("SELECT * FROM room_v2_tool_invocation_receipts").fetchone(),
                    immutable_before["invocation_receipt"],
                )
                self.assertEqual(
                    conn.execute("SELECT * FROM room_v2_tool_execution_receipts").fetchone(),
                    immutable_before["execution_receipt"],
                )
                self.assertEqual(pi_history.read_bytes(), pi_history_bytes)

                self.assertFalse(
                    any(tool_id in LEGACY_TOOL_IDS for tool_id in json.loads(policy[0]))
                )
                preference_maps = [
                    json.loads(policy[1]),
                    migrated_configuration["sessionDefaults"]
                    ["capabilityDisclosurePreferences"],
                    *migrated_configuration["capabilityDisclosure"]
                    ["projectPreferences"].values(),
                ]
                legacy_capability_keys = {
                    f"tool:{tool_id}" for tool_id in LEGACY_TOOL_IDS
                }
                self.assertFalse(
                    any(
                        key in legacy_capability_keys
                        for preferences in preference_maps
                        for key in preferences
                    )
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM agent_approvals
                        WHERE state IN ('pending', 'approved', 'external_pending')
                          AND tool_name IN (
                              'ime_overview', 'ime_input', 'ime_voice', 'ime_planning',
                              'ime_memory', 'ime_knowledge', 'ime_models', 'ime_runtime',
                              'ime_configuration', 'ime_agents', 'ime_browser', 'ime_plugins'
                          )
                        """
                    ).fetchone()[0],
                    0,
                )
                live_room_documents = conn.execute(
                    """
                    SELECT manifest.payload_json, binding.room_binding_json,
                           binding.participant_binding_json
                    FROM room_v2_capability_runtime_bindings AS binding
                    JOIN room_v2_capability_manifests AS manifest
                      ON manifest.manifest_id = binding.manifest_id
                    WHERE binding.state IN ('prepared', 'active')
                    """
                ).fetchall()
                self.assertFalse(
                    any(
                        _contains_legacy_tool_id(json.loads(document))
                        for row in live_room_documents
                        for document in row
                    )
                )

                state_before_second_run = conn.execute(
                    """
                    SELECT allowed_tools_json, disclosure_preferences_json,
                           policy_revision, updated_at_ms
                    FROM agent_session_tool_policies
                    """
                ).fetchall(), conn.execute(
                    "SELECT * FROM room_v2_capability_runtime_bindings ORDER BY manifest_id"
                ).fetchall()
                second = apply_database_migrations(conn, applied_at_ms=2000)
                self.assertEqual(second.applied_versions, ())
                self.assertEqual(
                    (
                        conn.execute(
                            """
                            SELECT allowed_tools_json, disclosure_preferences_json,
                                   policy_revision, updated_at_ms
                            FROM agent_session_tool_policies
                            """
                        ).fetchall(),
                        conn.execute(
                            "SELECT * FROM room_v2_capability_runtime_bindings ORDER BY manifest_id"
                        ).fetchall(),
                    ),
                    state_before_second_run,
                )

    def test_0118_destination_key_conflict_fails_closed_transactionally(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-tool-id-conflict-") as temporary:
            root = Path(temporary)
            pre_cutover = self._pre_cutover_migrations(root)
            with closing(sqlite3.connect(":memory:")) as conn:
                apply_database_migrations(conn, migrations_dir=pre_cutover)
                with conn:
                    self._insert_session(conn, "session-conflict")
                    original_allowed = _json(["ime_voice", "custom-tool"])
                    original_disclosure = _json({"tool:ime_memory": "inherit"})
                    conn.execute(
                        """
                        INSERT INTO agent_session_tool_policies(
                            session_id, allowed_tools_json, disclosure_preferences_json,
                            policy_revision, updated_at_ms
                        ) VALUES ('session-conflict', ?, ?, 2, 20)
                        """,
                        (original_allowed, original_disclosure),
                    )
                    configuration = {
                        "runtime": {
                            "enabled": True,
                            "startup": "lazy",
                            "idleTimeoutSeconds": 600,
                        },
                        "sessionDefaults": {
                            "resumeLastSession": True,
                            "roleId": "assistant",
                            "roleVersion": "v1",
                            "modelProfile": "pi/default",
                            "toolProfileVersion": "control-center-v1",
                            "capabilityDisclosurePreferences": {},
                        },
                        "coordination": {"enabled": True},
                        "capabilityDisclosure": {
                            "projectPreferences": {
                                "project-conflict": {
                                    "tool:ime_agents": "inherit",
                                    "tool:agents": "enabled",
                                }
                            }
                        },
                    }
                    conn.execute(
                        """
                        INSERT INTO agent_configuration_state(
                            singleton_id, revision, configuration_json,
                            applied_revision, sync_state, updated_at_ms, updated_by
                        ) VALUES (1, 3, ?, 3, 'synchronized', 20, 'owner')
                        """,
                        (_json(configuration),),
                    )

                with self.assertRaisesRegex(RuntimeError, "conflicting capability keys"):
                    apply_database_migrations(conn, applied_at_ms=1000)

                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = 118"
                    ).fetchone()
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT allowed_tools_json, disclosure_preferences_json,
                               policy_revision, updated_at_ms
                        FROM agent_session_tool_policies
                        """
                    ).fetchone(),
                    (original_allowed, original_disclosure, 2, 20),
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT revision, configuration_json FROM agent_configuration_state"
                    ).fetchone(),
                    (3, _json(configuration)),
                )

    def test_0118_policy_key_and_array_collisions_fail_closed(self) -> None:
        conflict_cases = (
            (
                ["ime_memory"],
                {"tool:ime_browser": "inherit", "tool:browser": "enabled"},
                "conflicting capability keys",
            ),
            (
                ["ime_memory", "memory"],
                {},
                "conflicting Tool IDs",
            ),
        )
        for index, (allowed, disclosure, message) in enumerate(conflict_cases):
            with self.subTest(message=message), tempfile.TemporaryDirectory(
                prefix=f"rag-ime-tool-policy-conflict-{index}-"
            ) as temporary:
                root = Path(temporary)
                pre_cutover = self._pre_cutover_migrations(root)
                with closing(sqlite3.connect(":memory:")) as conn:
                    apply_database_migrations(conn, migrations_dir=pre_cutover)
                    with conn:
                        self._insert_session(conn, "session-conflict")
                        conn.execute(
                            """
                            INSERT INTO agent_session_tool_policies(
                                session_id, allowed_tools_json,
                                disclosure_preferences_json,
                                policy_revision, updated_at_ms
                            ) VALUES ('session-conflict', ?, ?, 1, 20)
                            """,
                            (_json(allowed), _json(disclosure)),
                        )
                    with self.assertRaisesRegex(RuntimeError, message):
                        apply_database_migrations(conn, applied_at_ms=1000)
                    self.assertIsNone(
                        conn.execute(
                            "SELECT 1 FROM schema_migrations WHERE version = 118"
                        ).fetchone()
                    )


if __name__ == "__main__":
    unittest.main()
