from __future__ import annotations

import unittest

from rag_ime.agent_room_capabilities import ROOM_PUBLIC_TOOLS
from rag_ime.agent_room_tool_catalog import compose_room_tool_catalog


def _tool(name: str, *, operation: str = "read") -> dict[str, object]:
    return {
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


class RoomToolCatalogTests(unittest.TestCase):
    def test_protocol_tools_survive_while_product_tools_keep_independent_gates(self) -> None:
        workspace_read = _tool("workspace_read")
        workspace_shell = _tool("workspace_shell", operation="run")

        plan = compose_room_tool_catalog(
            available=(workspace_read, workspace_shell),
            user_authorized=(workspace_read,),
            effective=(workspace_read,),
        )

        self.assertEqual(plan.user_authorized[:3], ROOM_PUBLIC_TOOLS)
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


if __name__ == "__main__":
    unittest.main()
