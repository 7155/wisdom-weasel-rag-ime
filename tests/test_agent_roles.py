from __future__ import annotations

import unittest

from rag_ime.agent_roles import agent_role, agent_role_catalog


class AgentRoleTests(unittest.TestCase):
    def test_personas_are_versioned_and_share_control_boundaries(self) -> None:
        roles = [
            agent_role("zhiyou-v1", "1"),
            agent_role("hermes-v1", "1"),
            agent_role("vcp-v1", "1"),
        ]
        role = roles[0]

        self.assertEqual(role.display_name, "智鼬·此刻")
        self.assertEqual([item.display_name for item in roles], ["智鼬·此刻", "智鼬·初识", "智鼬·未来"])
        self.assertEqual(len({item.persona_prompt for item in roles}), 3)
        for item in roles:
            with self.subTest(role=item.role_id):
                self.assertIn("catalog -> read -> trace", item.system_prompt)
                self.assertIn("今天、昨天、最近、上周", item.system_prompt)
                self.assertIn("隔离质量测试", item.system_prompt)
                self.assertIn("不能扩大", item.system_prompt)
                self.assertIn("只有受控审批回执有效", item.system_prompt)
                self.assertNotIn("DEEPSEEK_API_KEY", item.system_prompt)

        catalog = agent_role_catalog()
        self.assertEqual([item["roleId"] for item in catalog], ["zhiyou-v1", "hermes-v1", "vcp-v1"])
        self.assertTrue(all(item["schemaVersion"] == "rag-ime.agent-persona.v1" for item in catalog))
        self.assertTrue(all(item["safetyPolicyVersion"] == "control-center-safe-v1" for item in catalog))
        self.assertNotIn("systemPrompt", catalog[0])
        self.assertNotIn("personaPrompt", catalog[0])
        self.assertEqual(catalog[1]["selectableModes"], ["assistant"])
        self.assertEqual(catalog[0]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-present-v1")
        self.assertEqual(catalog[1]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-past-v1")
        self.assertEqual(catalog[2]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-future-v1")
        self.assertEqual(
            [item["defaults"]["modelPolicy"] for item in catalog],
            ["affinity-5.6-terra", "affinity-5.6-sol", "affinity-5.6-luna"],
        )
        self.assertEqual(catalog[2]["visualProfile"]["accentToken"], "rose")

    def test_unknown_role_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported agent role"):
            agent_role("model-selected-role", "1")


if __name__ == "__main__":
    unittest.main()
