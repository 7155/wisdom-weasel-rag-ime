from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway


class AgentToolRuntimeContractTest(unittest.TestCase):
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

    def test_every_enabled_runtime_tool_exposes_an_object_parameter_schema(self) -> None:
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

        self.assertGreaterEqual(len(manifests), 13)
        for manifest in manifests:
            with self.subTest(tool=manifest["name"]):
                self.assertEqual(manifest["parameters"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
