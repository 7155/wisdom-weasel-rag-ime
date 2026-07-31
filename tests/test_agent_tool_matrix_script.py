from __future__ import annotations

import unittest

from rag_ime.agent_tool_ids import CONTROL_TOOL_IDS
from scripts.check_agent_tool_matrix import EXPECTED_TOOL_IDS, TOOL_CALLS


class AgentToolMatrixScriptTests(unittest.TestCase):
    def test_matrix_has_one_real_invocation_for_every_enabled_product_tool(self) -> None:
        self.assertEqual(EXPECTED_TOOL_IDS, frozenset(CONTROL_TOOL_IDS))
        self.assertEqual(tuple(TOOL_CALLS), CONTROL_TOOL_IDS)
        self.assertEqual(set(TOOL_CALLS), EXPECTED_TOOL_IDS)
        for tool, args in TOOL_CALLS.items():
            with self.subTest(tool=tool):
                self.assertTrue(str(args.get("op") or ""))

    def test_workspace_mutations_form_one_verifiable_isolated_chain(self) -> None:
        self.assertEqual(TOOL_CALLS["workspace_patch"]["oldText"], "hello")
        self.assertEqual(TOOL_CALLS["workspace_patch"]["newText"], "patched")
        self.assertEqual(
            TOOL_CALLS["workspace_edit"]["edits"],
            [{"oldText": "patched", "newText": "edited"}],
        )
        self.assertEqual(TOOL_CALLS["workspace_write"]["path"], "created.txt")
        self.assertIn("agent-tool-matrix-shell-ok", TOOL_CALLS["workspace_shell"]["command"])


if __name__ == "__main__":
    unittest.main()
