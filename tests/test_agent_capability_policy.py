from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_configuration import (
    AgentConfigurationStore,
    default_agent_configuration,
)
from rag_ime.agent_session_policy import AgentSessionPolicyService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tool_ids import CONTROL_TOOL_IDS
from rag_ime.agent_tools import ControlToolGateway, _TOOL_SPEC_BY_ID


class _Runtime:
    def __init__(self) -> None:
        self.open_session_ids: list[str] = []
        self.active_session_id: str | None = None
        self.status = "ready"
        self.closed: list[str] = []
        self.running_jobs = ["job:running"]

    def runtime_status(self) -> dict[str, object]:
        return {
            "status": self.status,
            "activeSessionId": self.active_session_id,
            "openSessionIds": list(self.open_session_ids),
        }

    def close_session(self, session_id: str) -> bool:
        self.closed.append(session_id)
        self.open_session_ids = [
            value for value in self.open_session_ids if value != session_id
        ]
        if self.active_session_id == session_id:
            self.active_session_id = None
        return True


class _Rooms:
    def __init__(self) -> None:
        self.active_session_id = ""

    def participant_for_session(
        self, session_id: str, *, active_only: bool
    ) -> dict[str, object] | None:
        del active_only
        if session_id != self.active_session_id:
            return None
        return {"roomId": "room:1", "status": "active"}

    def get(self, room_id: str) -> dict[str, object]:
        self.assert_room_id = room_id
        return {"id": room_id, "status": "active"}


class _Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, dict[str, object]]] = []

    def publish(
        self, session_id: str, event: str, payload: dict[str, object]
    ) -> None:
        self.items.append((session_id, event, payload))


class _Skills:
    def governance_catalog(self) -> list[dict[str, object]]:
        return [
            {
                "skillId": "quality-gate",
                "name": "quality-gate",
                "when": ["before delivery"],
                "notFor": [],
                "input": "evidence",
                "output": "gate result",
                "does": "Checks delivery evidence.",
                "risk": "medium",
                "stages": ["delivery"],
                "policyId": "room-skills",
                "policyVersion": 1,
                "contentRevision": "abc123",
            }
        ]


class _Extensions:
    def catalog(self) -> dict[str, object]:
        return {
            "catalogVersion": "1",
            "items": [
                {
                    "id": "session-review",
                    "displayName": "Session Review",
                    "description": "Reviews a Session.",
                    "source": {"label": "Product bundle"},
                    "permissions": ["session.read"],
                    "installedVersion": "1.0.0",
                    "installed": True,
                    "enabled": True,
                    "installState": "installed",
                }
            ],
        }


class AgentCapabilityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions = AgentSessionStore(self.root / "agent.sqlite3")
        self.sessions.initialize()
        self.configuration = AgentConfigurationStore(
            self.root / "agent.sqlite3"
        )
        self.configuration.initialize(default_agent_configuration())
        self.runtime = _Runtime()
        self.rooms = _Rooms()
        self.events = _Events()
        self.personas = SimpleNamespace(
            resolve=lambda _role_id, _role_version: SimpleNamespace(
                role_id="companion-future-v1",
                version="1",
                selectable_modes=("assistant", "coordinator"),
            )
        )
        self.policy = AgentSessionPolicyService(
            sessions=self.sessions,
            runtime_provider=lambda: self.runtime,
            personas=self.personas,
            rooms=self.rooms,
            events=self.events,
            runtime_status=self.runtime.runtime_status,
            probe_memory_maintenance=lambda *_args, **_kwargs: {},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _gateway(self) -> ControlToolGateway:
        return ControlToolGateway(
            sessions=self.sessions,
            management=object(),
            core=object(),
            project="test",
            configuration_store=self.configuration,
            governed_skills=_Skills(),
            extensions=_Extensions(),
        )

    def test_tool_inventory_ids_exactly_match_specs(self) -> None:
        self.assertEqual(frozenset(_TOOL_SPEC_BY_ID), frozenset(CONTROL_TOOL_IDS))
        self.assertEqual(len(_TOOL_SPEC_BY_ID), len(CONTROL_TOOL_IDS))
        self.assertIn("plugins", CONTROL_TOOL_IDS)

    def test_disclosure_never_grants_tool_authorization(self) -> None:
        session = self.sessions.create(title="restricted")
        session = self.sessions.set_runtime_policy(
            str(session["id"]),
            mode="assistant",
            tool_profile_version="subagent-readonly-v1",
            allowed_tools=["overview"],
        )
        updated = self.policy.update_session(
            str(session["id"]),
            {
                "capabilityDisclosurePreferences": {
                    "tool:memory": "enabled"
                }
            },
        )
        self.assertEqual(updated["policyRevision"], 2)
        current = self.sessions.get(str(session["id"]))
        self.assertEqual(current["allowedTools"], ["overview"])
        memory = next(
            item
            for item in self._gateway().manifests(
                session_id=str(session["id"])
            )["items"]
            if item["canonicalId"] == "tool:memory"
        )
        self.assertEqual(memory["disclosure"]["state"], "disclosed")
        self.assertEqual(memory["authorization"]["state"], "denied")

    def test_busy_mutation_is_rejected_without_retiring_runtime(self) -> None:
        session = self.sessions.create(title="busy")
        session_id = str(session["id"])
        self.sessions.set_status(session_id, "busy")
        self.runtime.active_session_id = session_id
        self.runtime.open_session_ids = [session_id]
        with self.assertRaisesRegex(ValueError, "Agent Loop"):
            self.policy.update_session(
                session_id,
                {
                    "capabilityDisclosurePreferences": {
                        "tool:memory": "disabled"
                    }
                },
            )
        self.assertEqual(self.runtime.closed, [])
        self.assertEqual(
            self.sessions.get(session_id)["capabilityDisclosurePreferences"],
            {},
        )

    def test_idle_mutation_retires_only_target_and_preserves_running_jobs(self) -> None:
        target = self.sessions.create(title="target")
        other = self.sessions.create(title="other")
        target_id = str(target["id"])
        other_id = str(other["id"])
        self.runtime.open_session_ids = [target_id, other_id]
        jobs_before = list(self.runtime.running_jobs)
        response = self.policy.update_session(
            target_id,
            {
                "capabilityDisclosurePreferences": {
                    "tool:memory": "disabled"
                }
            },
        )
        self.assertEqual(response["policyRevision"], 2)
        self.assertEqual(self.runtime.closed, [target_id])
        self.assertEqual(self.runtime.open_session_ids, [other_id])
        self.assertEqual(self.runtime.running_jobs, jobs_before)

    def test_active_room_rejects_disclosure_mutation(self) -> None:
        session = self.sessions.create(title="room participant")
        session_id = str(session["id"])
        self.rooms.active_session_id = session_id
        with self.assertRaisesRegex(ValueError, "managed by the Room"):
            self.policy.update_session(
                session_id,
                {
                    "capabilityDisclosurePreferences": {
                        "skill:quality-gate": "enabled"
                    }
                },
            )
        self.assertEqual(
            self.sessions.get(session_id)["capabilityDisclosurePreferences"],
            {},
        )

    def test_precedence_catalog_completeness_and_removed_item(self) -> None:
        snapshot = self.configuration.snapshot()
        self.configuration.update(
            {
                "sessionDefaults.capabilityDisclosurePreferences": {
                    "tool:memory": "disabled",
                    "extension:removed-plugin": "disabled",
                }
            },
            expected_revision=int(snapshot["revision"]),
            updated_by="test",
        )
        session = self.sessions.create(title="precedence")
        session_id = str(session["id"])
        self.policy.update_session(
            session_id,
            {
                "capabilityDisclosurePreferences": {
                    "tool:memory": "enabled",
                    "skill:quality-gate": "inherit",
                }
            },
        )
        catalog = self._gateway().manifests(session_id=session_id)
        by_id = {item["canonicalId"]: item for item in catalog["items"]}
        self.assertIn("tool:plugins", by_id)
        self.assertIn("skill:quality-gate", by_id)
        self.assertIn("extension:session-review", by_id)
        self.assertEqual(
            by_id["tool:memory"]["effectiveScope"], "session"
        )
        self.assertEqual(
            by_id["tool:memory"]["disclosure"]["effective"],
            "enabled",
        )
        removed = by_id["extension:removed-plugin"]
        self.assertEqual(removed["status"], "removed")
        self.assertEqual(removed["authorization"]["state"], "denied")
        self.assertFalse(catalog["projectScope"]["supported"])
        self.assertEqual(
            catalog["projectScope"]["reason"],
            "stable_project_identity_unavailable",
        )

    def test_project_default_precedes_global_and_session_precedes_project(self) -> None:
        session = self.sessions.create(
            title="project precedence",
            mode="coordinator",
            execution_mode="workspace_managed",
            workspace_roots=[str(self.root)],
        )
        session_id = str(session["id"])
        project_id = f"workspace-{session['workspaceScopeSha256']}"
        snapshot = self.configuration.snapshot()
        self.configuration.update(
            {
                "sessionDefaults.capabilityDisclosurePreferences": {
                    "tool:memory": "disabled",
                },
                "capabilityDisclosure.projectPreferences": {
                    project_id: {
                        "tool:memory": "enabled",
                        "extension:project-removed": "disabled",
                    }
                },
            },
            expected_revision=int(snapshot["revision"]),
            updated_by="test",
        )

        project_catalog = self._gateway().manifests(session_id=session_id)
        self.assertEqual(
            project_catalog["projectScope"],
            {
                "supported": True,
                "identityKind": "workspace_scope_sha256",
                "projectId": project_id,
                "reason": "session_workspace_scope",
            },
        )
        project_by_id = {
            item["canonicalId"]: item for item in project_catalog["items"]
        }
        self.assertEqual(
            project_by_id["tool:memory"]["effectiveScope"],
            "project_default",
        )
        self.assertEqual(
            project_by_id["tool:memory"]["disclosure"]["effective"],
            "enabled",
        )
        self.assertEqual(
            project_catalog["sessionPolicy"]["disclosurePreferences"][
                "projectDefault"
            ],
            {
                "extension:project-removed": "disabled",
                "tool:memory": "enabled",
            },
        )
        self.assertIn(
            "memory",
            {
                str(item["name"])
                for item in self._gateway().runtime_manifests(
                    self.sessions.get(session_id)
                )
            },
        )
        self.assertEqual(
            project_by_id["extension:project-removed"]["status"],
            "removed",
        )

        self.policy.update_session(
            session_id,
            {
                "capabilityDisclosurePreferences": {
                    "tool:memory": "disabled",
                }
            },
        )
        session_catalog = self._gateway().manifests(session_id=session_id)
        memory = next(
            item
            for item in session_catalog["items"]
            if item["canonicalId"] == "tool:memory"
        )
        self.assertEqual(memory["effectiveScope"], "session")
        self.assertEqual(memory["disclosure"]["effective"], "disabled")
        self.assertNotIn(
            "memory",
            {
                str(item["name"])
                for item in self._gateway().runtime_manifests(
                    self.sessions.get(session_id)
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
