from __future__ import annotations

import unittest

from scripts.check_agent_tool_matrix import EXPECTED_TOOL_IDS, TOOL_CALLS


class AgentToolMatrixScriptTests(unittest.TestCase):
    def test_matrix_has_one_real_invocation_for_every_enabled_product_tool(self) -> None:
        self.assertEqual(set(TOOL_CALLS), EXPECTED_TOOL_IDS)
        provider_workspace_tools = {"ls", "read", "grep", "find", "edit", "write", "bash"}
        self.assertTrue(provider_workspace_tools.issubset(TOOL_CALLS))
        self.assertTrue(
            {
                "workspace_list",
                "workspace_read",
                "workspace_search",
                "workspace_edit",
                "workspace_write",
                "workspace_shell",
            }.isdisjoint(TOOL_CALLS)
        )
        for tool, args in TOOL_CALLS.items():
            with self.subTest(tool=tool):
                if tool not in provider_workspace_tools:
                    self.assertTrue(str(args.get("op") or ""))

    def test_workspace_mutations_form_one_verifiable_isolated_chain(self) -> None:
        self.assertEqual(TOOL_CALLS["workspace_patch"]["oldText"], "hello")
        self.assertEqual(TOOL_CALLS["workspace_patch"]["newText"], "patched")
        self.assertEqual(
            TOOL_CALLS["edit"]["edits"],
            [{"oldText": "patched", "newText": "edited"}],
        )
        self.assertEqual(TOOL_CALLS["write"]["path"], "created.txt")
        self.assertIn("agent-tool-matrix-shell-ok", TOOL_CALLS["bash"]["command"])


if __name__ == "__main__":
    unittest.main()
