from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway, _TOOL_SPEC_BY_ID


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

    def test_runtime_schema_projection_does_not_share_mutable_global_branches(self) -> None:
        _, manifests = self._runtime_contracts(mode="coordinator")
        todo = next(item for item in manifests if item["name"] == "todo")
        append = next(
            branch
            for branch in todo["parameters"]["oneOf"]
            if branch["properties"]["op"]["const"] == "append"
        )
        append.pop("additionalProperties")

        _, fresh_manifests = self._runtime_contracts(mode="coordinator")
        fresh_todo = next(
            item for item in fresh_manifests if item["name"] == "todo"
        )
        fresh_append = next(
            branch
            for branch in fresh_todo["parameters"]["oneOf"]
            if branch["properties"]["op"]["const"] == "append"
        )

        self.assertFalse(fresh_append["additionalProperties"])

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

        planning = next(item for item in manifests if item["name"] == "planning")
        self.assertEqual(planning["description"], "规划与任务")
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
            and item.get("runtimeOwner") != "pi_host"
        }
        native_ask = next(item for item in catalog if item["id"] == "ask")
        self.assertEqual(native_ask["runtimeOwner"], "pi_host")
        self.assertTrue(native_ask["alwaysAvailable"])

        self.assertEqual(
            {str(manifest["name"]) for manifest in manifests},
            set(effective),
        )
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
                operation_branches = [
                    branch
                    for branch in branches
                    if isinstance(branch.get("properties", {}).get("op"), dict)
                    and "const" in branch["properties"]["op"]
                ]
                self.assertEqual(
                    {
                        branch["properties"]["op"]["const"]
                        for branch in operation_branches
                    },
                    effective[manifest["name"]],
                )
                for branch in operation_branches:
                    self.assertIs(
                        branch.get(
                            "additionalProperties",
                            schema.get("additionalProperties"),
                        ),
                        False,
                    )
                    self.assertIn("op", branch["required"])
                compatibility_branches = [
                    branch for branch in branches if branch not in operation_branches
                ]
                if manifest["name"] == "memory":
                    self.assertEqual(len(compatibility_branches), 1)
                    self.assertEqual(compatibility_branches[0]["required"], ["query"])
                    self.assertEqual(
                        compatibility_branches[0]["not"],
                        {"required": ["op"]},
                    )
                else:
                    self.assertEqual(compatibility_branches, [])

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
        # every deferred JSON Schema plus the hidden native-tool execution
        # targets. Only the compact cards enter the prompt, so keep their
        # tighter Provider-facing budget independent from this transport
        # envelope.
        # Goal lifecycle, fixed Todo policy, and explicit Knowledge rerank
        # controls add full internal schemas; their compact public cards remain
        # covered by the independent Provider-facing limit.
        self.assertLess(len(encoded), 52_000)
        self.assertLess(len(public_encoded), 12_000)
        self.assertTrue(all("profile" not in manifest for manifest in manifests))
        self.assertTrue(
            all(
                manifest["description"]
                == _TOOL_SPEC_BY_ID[str(manifest["name"])]["displayName"]
                for manifest in manifests
            )
        )
        self.assertIn("work_documents", {manifest["name"] for manifest in manifests})
        self.assertIn("agent_goal", {manifest["name"] for manifest in manifests})

    def test_runtime_contracts_require_tool_specific_identifiers_and_payloads(self) -> None:
        _catalog, manifests = self._runtime_contracts(mode="coordinator")
        tools = {manifest["name"]: manifest for manifest in manifests}

        self.assertEqual(
            self._branch(tools["workspace_patch"], "apply")["required"],
            ["op", "path", "oldText", "newText"],
        )
        self.assertEqual(
            self._branch(tools["workspace_edit"], "apply")["required"],
            ["op", "path", "resourceRevision", "edits"],
        )
        self.assertEqual(
            self._branch(tools["workspace_write"], "apply")["required"],
            ["op", "path", "resourceRevision", "content"],
        )
        self.assertEqual(
            self._branch(tools["workspace_lsp"], "rename")["required"],
            ["op", "path", "newName"],
        )
        self.assertEqual(
            self._branch(tools["workspace_lsp"], "code_action_apply")["required"],
            ["op", "path", "title"],
        )
        self.assertEqual(
            self._branch(tools["workspace_shell"], "run")["required"],
            ["op", "command"],
        )
        self.assertEqual(
            self._branch(tools["plugins"], "create_draft")["required"],
            ["op", "draftId", "manifest", "files"],
        )
        self.assertEqual(
            self._branch(tools["memory"], "read")["required"],
            ["op", "bookId"],
        )
        self.assertEqual(
            self._branch(tools["knowledge"], "search")["required"],
            ["op", "kbId", "query"],
        )
        self.assertEqual(
            self._branch(tools["agent_schedule"], "schedule")["required"],
            ["op", "instruction", "targetType", "wakeAtMs"],
        )
        self.assertEqual(
            self._branch(tools["browser"], "navigate")["required"],
            ["op", "url"],
        )
        self.assertEqual(
            self._branch(tools["browser"], "type")["required"],
            ["op", "refId", "text"],
        )
        self.assertEqual(
            self._branch(tools["desktop_semantic"], "act")["required"],
            ["op", "snapshotId", "revision", "nodeRef", "action"],
        )
        self.assertEqual(
            self._branch(tools["desktop_semantic"], "inspect")["properties"]["maxNodes"]["maximum"],
            500,
        )

        delegate = self._branch(tools["agents"], "delegate")
        self.assertEqual(
            delegate["anyOf"],
            [
                {"required": ["tasks"]},
                {
                    "required": [
                        "agent",
                        "task",
                        "expectedOutput",
                        "acceptanceCriteria",
                    ]
                },
            ],
        )
        self.assertEqual(delegate["properties"]["todoTask"]["maxLength"], 240)
        todo_branches = {
            branch["properties"]["op"]["const"]: branch
            for branch in tools["todo"]["parameters"]["oneOf"]
        }
        self.assertEqual(
            set(todo_branches),
            {
                "init",
                "start",
                "done",
                "drop",
                "block",
                "unblock",
                "append",
                "view",
                "rm",
            },
        )
        self.assertEqual(
            todo_branches["init"]["oneOf"],
            [{"required": ["list"]}, {"required": ["items"]}],
        )
        self.assertEqual(todo_branches["start"]["required"], ["op", "task"])
        self.assertEqual(
            todo_branches["append"]["required"],
            ["op", "phase", "items"],
        )
        self.assertEqual(todo_branches["view"]["required"], ["op"])
        for operation in ("done", "drop", "block", "unblock"):
            with self.subTest(todo_operation=operation):
                self.assertEqual(todo_branches[operation]["required"], ["op"])
                self.assertEqual(
                    todo_branches[operation]["oneOf"],
                    [{"required": ["task"]}, {"required": ["phase"]}],
                )
        self.assertEqual(todo_branches["rm"]["required"], ["op"])
        self.assertEqual(
            todo_branches["rm"]["not"],
            {"required": ["task", "phase"]},
        )
        abort = self._branch(tools["agents"], "abort")
        self.assertEqual(
            abort["anyOf"],
            [{"required": ["runId"]}, {"required": ["batchId"]}],
        )
        self.assertEqual(self._branch(tools["agents"], "status")["required"], ["op"])
        goal_setup = self._branch(tools["agent_goal"], "confirm_setup")
        self.assertEqual(
            goal_setup["required"],
            ["op", "confirmed", "objective"],
        )
        goal_complete = self._branch(tools["agent_goal"], "complete")
        self.assertEqual(
            goal_complete["properties"]["evidence"]["items"]["required"],
            ["kind", "summary", "reference"],
        )
        model_apply = self._branch(tools["models"], "profile_apply")
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
        lsp_properties = self._branch(tools["workspace_lsp"], "references")["properties"]
        self.assertIn("includeDeclaration", lsp_properties)
        self.assertEqual(lsp_properties["timeoutMs"]["maximum"], 20_000)
        self.assertEqual(lsp_properties["query"]["maxLength"], 240)
        audit_properties = self._branch(tools["configuration"], "audit")["properties"]
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
            effective["workspace_lsp"],
            {
                "status",
                "symbols",
                "hover",
                "definition",
                "references",
                "diagnostics",
            },
        )
        self.assertNotIn("rename", effective["workspace_lsp"])
        self.assertNotIn("code_action_apply", effective["workspace_lsp"])
        self.assertEqual(
            effective["agents"],
            {"catalog", "status", "artifact"},
        )
        self.assertNotIn("delegate", effective["agents"])
        self.assertNotIn("abort", effective["agents"])
        self.assertNotIn("workspace_patch", effective)
        self.assertNotIn("workspace_shell", effective)

        for manifest in manifests:
            with self.subTest(tool=manifest["name"]):
                operations = {
                    branch["properties"]["op"]["const"]
                    for branch in manifest["parameters"]["oneOf"]
                    if "op" in branch.get("properties", {})
                }
                self.assertEqual(operations, effective[manifest["name"]])
                self.assertTrue(operations)


if __name__ == "__main__":
    unittest.main()
