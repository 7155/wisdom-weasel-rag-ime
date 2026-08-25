from __future__ import annotations

import unittest

from rag_ime.agent_definitions import (
    canonical_collaboration_role_id,
    collaboration_role,
    collaboration_role_catalog,
)


class AgentDefinitionCompatibilityTests(unittest.TestCase):
    def test_room_roles_are_versioned_and_unique(self) -> None:
        roles = collaboration_role_catalog()
        self.assertEqual(
            [item["roleId"] for item in roles],
            ["coordinator", "researcher", "implementer", "reviewer", "specialist"],
        )
        self.assertEqual(len({item["roleId"] for item in roles}), len(roles))

    def test_room_contract_uses_native_session_and_delegation_capabilities(self) -> None:
        for role_id in ("coordinator", "researcher", "implementer", "reviewer"):
            prompt = collaboration_role(role_id).system_prompt
            self.assertIn("Pi Session", prompt)
            self.assertIn("agents", prompt)
            self.assertIn("room_partner", prompt)
            self.assertIn("Steer", prompt)
            self.assertIn("Stop", prompt)
            self.assertIn(
                "不要虚构不存在的工具",
                prompt,
            )
            self.assertNotIn("room_commit", prompt)

    def test_room_contract_describes_dynamic_partner_fanout_up_to_room_capacity(self) -> None:
        prompt = collaboration_role("coordinator").system_prompt

        self.assertIn("按任务规模动态选择", prompt)
        self.assertIn("最多 7 个 Partner", prompt)
        self.assertIn("Room 总参与者最多 8 个", prompt)
        self.assertNotIn("2–3 个无依赖", prompt)

    def test_retained_specialist_role_never_claims_domain_expertise(self) -> None:
        specialist = collaboration_role("specialist")
        catalog_entry = next(
            item for item in collaboration_role_catalog()
            if item["roleId"] == "specialist"
        )
        self.assertNotIn("专家", str(catalog_entry["displayName"]))
        self.assertNotIn("专家", str(catalog_entry["summary"]))
        self.assertIn("不要自称专家", specialist.system_prompt)

    def test_legacy_executor_reads_resolve_to_implementer_without_rewrites(self) -> None:
        self.assertEqual(canonical_collaboration_role_id("executor"), "implementer")
        self.assertEqual(canonical_collaboration_role_id(" executor "), "implementer")
        self.assertEqual(canonical_collaboration_role_id("reviewer"), "reviewer")
        self.assertEqual(canonical_collaboration_role_id(None), "implementer")
        self.assertEqual(canonical_collaboration_role_id("   "), "")


if __name__ == "__main__":
    unittest.main()
