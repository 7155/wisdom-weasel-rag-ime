from __future__ import annotations

import unittest

from rag_ime.agent_room_capabilities import ROOM_PUBLIC_TOOLS
from rag_ime.agent_room_tool_catalog import compose_room_tool_catalog


def _tool(
    name: str,
    *,
    operation: str = "read",
    runtime_projections: tuple[dict[str, str], ...] = (),
) -> dict[str, object]:
    tool: dict[str, object] = {
        "name": name,
        "description": f"Use {name}",
        "parameters": {
            "type": "object",
            "required": ["op"],
            "properties": {"op": {"const": operation}},
            "additionalProperties": False,
        },
        "when": ["需要真实证据"],
        "notFor": ["当前上下文已经足够"],
        "input": "受控参数",
        "output": "带来源的结果",
        "does": "读取真实证据。",
        "risk": "R0",
    }
    if runtime_projections:
        tool["runtimeProjections"] = [
            dict(projection) for projection in runtime_projections
        ]
    return tool


class RoomToolCatalogTests(unittest.TestCase):
    def test_protocol_tools_survive_while_product_tools_keep_independent_gates(self) -> None:
        workspace_read = _tool("workspace_read")
        workspace_shell = _tool("workspace_shell", operation="run")

        plan = compose_room_tool_catalog(
            available=(workspace_read, workspace_shell),
            user_authorized=(workspace_read,),
            effective=(workspace_read,),
        )

        self.assertEqual(
            plan.user_authorized[: len(ROOM_PUBLIC_TOOLS)],
            ROOM_PUBLIC_TOOLS,
        )
        self.assertIn("workspace_read", plan.user_authorized)
        self.assertNotIn("workspace_shell", plan.user_authorized)
        self.assertIn("workspace_read", plan.template_allowed)
        self.assertIn("workspace_read", plan.role_allowed)
        self.assertIn("workspace_read", plan.profile_allowed)
        self.assertIn("workspace_shell", plan.runtime_registry)
        self.assertEqual(
            plan.runtime_registry["workspace_read"]["catalogKind"],
            "product-tool",
        )
        self.assertEqual(
            plan.runtime_registry["workspace_read"]["inputSchema"],
            workspace_read["parameters"],
        )

    def test_room_role_does_not_remove_tools_from_a_working_session(self) -> None:
        workspace_shell = _tool("workspace_shell", operation="run")

        plan = compose_room_tool_catalog(
            available=(workspace_shell,),
            user_authorized=(workspace_shell,),
            effective=(workspace_shell,),
        )

        self.assertIn("workspace_shell", plan.template_allowed)
        self.assertIn("workspace_shell", plan.role_allowed)
        self.assertIn("workspace_shell", plan.profile_allowed)

    def test_runtime_projection_metadata_survives_room_catalog_compilation(self) -> None:
        memory = _tool(
            "ime_memory",
            operation="capture",
            runtime_projections=(
                {"name": "memory_capture", "operation": "capture"},
            ),
        )

        plan = compose_room_tool_catalog(
            available=(memory,),
            user_authorized=(memory,),
            effective=(memory,),
        )

        self.assertEqual(
            plan.runtime_registry["ime_memory"]["runtimeProjections"],
            [{"name": "memory_capture", "operation": "capture"}],
        )


if __name__ == "__main__":
    unittest.main()
