from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway


class AgentToolRuntimeContractTest(unittest.TestCase):
    @staticmethod
    def _branch(manifest, operation: str):
        schema = manifest["parameters"]
        branch = next(
            branch
            for branch in schema["oneOf"]
            if branch["properties"]["op"]["const"] == operation
        )
        return {
            **branch,
            "additionalProperties": branch.get(
                "additionalProperties",
                schema.get("additionalProperties"),
            ),
            "properties": {
                **schema.get("properties", {}),
                **branch.get("properties", {}),
            },
        }

    def _runtime_contracts(self, *, mode: str = "assistant", profile: str = "control-center-v1"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = AgentSessionStore(root / "agent.sqlite")
        store.initialize()
        session = store.create(
            title="tool contract",
            mode=mode,
            workspace_roots=[str(root)] if mode == "coordinator" else [],
            tool_profile_version=profile,
            created_at_ms=1,
        )
        gateway = ControlToolGateway(
            sessions=store,
            management=object(),
            core=object(),
            project="contract-test",
        )
        catalog = gateway.manifests(session_id=str(session["id"]))["items"]
        return catalog, gateway.runtime_manifests(session)

    def test_planning_manifest_requires_dashboard_identifiers_for_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AgentSessionStore(Path(temporary) / "agent.sqlite")
            store.initialize()
            session = store.create(title="tool contract", created_at_ms=1)
            gateway = ControlToolGateway(
                sessions=store,
                management=object(),
                core=object(),
                project="contract-test",
            )

            manifests = gateway.runtime_manifests(session)

        planning = next(item for item in manifests if item["name"] == "ime_planning")
        self.assertIn("先用 dashboard", planning["description"])
        schema = planning["parameters"]
        self.assertEqual(schema["type"], "object")
        task_action = next(
            branch
            for branch in schema["oneOf"]
            if branch["properties"]["op"]["const"] == "task_action"
        )
        self.assertEqual(task_action["required"], ["op", "taskId", "date", "action"])
        self.assertIn("dashboard", task_action["properties"]["taskId"]["description"])

    def test_every_enabled_runtime_tool_exposes_exact_operation_branches(self) -> None:
        catalog, manifests = self._runtime_contracts(mode="coordinator")
        effective = {
            item["id"]: set(item["effectiveOperations"])
            for item in catalog
            if item["enabled"] is True
        }

        self.assertEqual(len(manifests), 21)
        for manifest in manifests:
            with self.subTest(tool=manifest["name"]):
                self.assertEqual(
                    set(manifest) & {"name", "when", "notFor", "input", "output", "does"},
                    {"name", "when", "notFor", "input", "output", "does"},
                )
                self.assertTrue(manifest["when"])
                self.assertTrue(manifest["notFor"])
                self.assertTrue(manifest["input"])
                self.assertTrue(manifest["output"])
                self.assertTrue(manifest["does"])
                schema = manifest["parameters"]
                self.assertEqual(schema["type"], "object")
                branches = schema["oneOf"]
                self.assertEqual(
                    {
                        branch["properties"]["op"]["const"]
                        for branch in branches
                    },
                    effective[manifest["name"]],
                )
                for branch in branches:
                    self.assertIs(
                        branch.get(
                            "additionalProperties",
                            schema.get("additionalProperties"),
                        ),
                        False,
                    )
                    self.assertIn("op", branch["required"])

    def test_runtime_manifest_keeps_internal_catalog_and_public_cards_bounded(self) -> None:
        _catalog, manifests = self._runtime_contracts(mode="coordinator")
        encoded = json.dumps(
            manifests,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        cards = [
            {
                key: manifest[key]
                for key in ("name", "when", "notFor", "input", "output", "does")
            }
            for manifest in manifests
        ]
        public_encoded = json.dumps(
            cards,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        # The full registry is an internal Product -> Pi handshake and includes
        # every deferred JSON Schema. Only the compact cards enter the prompt.
        self.assertLess(len(encoded), 40_000)
        self.assertLess(len(public_encoded), 12_000)

    def test_runtime_contracts_require_tool_specific_identifiers_and_payloads(self) -> None:
        _catalog, manifests = self._runtime_contracts(mode="coordinator")
        tools = {manifest["name"]: manifest for manifest in manifests}

        self.assertEqual(
            self._branch(tools["workspace_patch"], "apply")["required"],
            ["op", "path", "oldText", "newText"],
        )
        self.assertEqual(
            self._branch(tools["workspace_shell"], "run")["required"],
            ["op", "command"],
        )
        self.assertEqual(
            self._branch(tools["ime_plugins"], "create_draft")["required"],
            ["op", "draftId", "manifest", "files"],
        )
        self.assertEqual(
            self._branch(tools["ime_memory"], "read")["required"],
            ["op", "bookId"],
        )
        self.assertEqual(
            self._branch(tools["ime_knowledge"], "search")["required"],
            ["op", "kbId", "query"],
        )
        self.assertEqual(
            self._branch(tools["agent_schedule"], "schedule")["required"],
            ["op", "instruction", "targetType", "wakeAtMs"],
        )
        self.assertEqual(
            self._branch(tools["ime_browser"], "navigate")["required"],
            ["op", "url"],
        )
        self.assertEqual(
            self._branch(tools["ime_browser"], "type")["required"],
            ["op", "refId", "text"],
        )
        self.assertEqual(
            self._branch(tools["desktop_semantic"], "act")["required"],
            ["op", "snapshotId", "revision", "nodeRef", "action"],
        )

        delegate = self._branch(tools["ime_agents"], "delegate")
        self.assertEqual(
            delegate["anyOf"],
            [{"required": ["tasks"]}, {"required": ["agent", "task"]}],
        )
        abort = self._branch(tools["ime_agents"], "abort")
        self.assertEqual(
            abort["anyOf"],
            [{"required": ["runId"]}, {"required": ["batchId"]}],
        )
        self.assertEqual(self._branch(tools["ime_agents"], "status")["required"], ["op"])

        plan_update = self._branch(tools["agent_plan"], "update")
        self.assertEqual(
            plan_update["anyOf"],
            [{"required": ["title"]}, {"required": ["itemId"]}],
        )
        model_apply = self._branch(tools["ime_models"], "profile_apply")
        self.assertEqual(model_apply["required"], ["op", "slot"])
        self.assertEqual(
            model_apply["anyOf"],
            [
                {"required": ["provider"]},
                {"required": ["endpoint"]},
                {"required": ["model"]},
            ],
        )

    def test_workspace_and_audit_optional_arguments_are_not_hidden_from_pi(self) -> None:
        _catalog, manifests = self._runtime_contracts(mode="coordinator")
        tools = {manifest["name"]: manifest for manifest in manifests}

        list_properties = self._branch(tools["workspace_list"], "list")["properties"]
        self.assertEqual(list_properties["limit"]["maximum"], 300)
        read_properties = self._branch(tools["workspace_read"], "read")["properties"]
        self.assertEqual(read_properties["limit"]["maximum"], 65_536)
        search_properties = self._branch(tools["workspace_search"], "search")["properties"]
        self.assertIn("caseSensitive", search_properties)
        self.assertEqual(search_properties["query"]["maxLength"], 200)
        audit_properties = self._branch(tools["ime_configuration"], "audit")["properties"]
        self.assertIn("action", audit_properties)

    def test_readonly_profile_filters_parameter_branches_with_operations(self) -> None:
        catalog, manifests = self._runtime_contracts(
            mode="coordinator",
            profile="subagent-readonly-v1",
        )
        effective = {
            item["id"]: set(item["effectiveOperations"])
            for item in catalog
            if item["enabled"] is True
        }
        self.assertEqual(effective["workspace_list"], {"list"})
        self.assertEqual(effective["workspace_read"], {"read"})
        self.assertEqual(effective["workspace_search"], {"search"})
        self.assertEqual(
            effective["ime_agents"],
            {"catalog", "status", "artifact"},
        )
        self.assertNotIn("delegate", effective["ime_agents"])
        self.assertNotIn("abort", effective["ime_agents"])
        self.assertNotIn("workspace_patch", effective)
        self.assertNotIn("workspace_shell", effective)

        for manifest in manifests:
            with self.subTest(tool=manifest["name"]):
                operations = {
                    branch["properties"]["op"]["const"]
                    for branch in manifest["parameters"]["oneOf"]
                }
                self.assertEqual(operations, effective[manifest["name"]])
                self.assertTrue(operations)


if __name__ == "__main__":
    unittest.main()
