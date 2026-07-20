from __future__ import annotations

import unittest

from rag_ime.agent_roles import agent_role, agent_role_catalog, persona_model_profile


class AgentRoleTests(unittest.TestCase):
    def test_personas_are_versioned_and_share_control_boundaries(self) -> None:
        roles = [
            agent_role("companion-future-v1", "1"),
            agent_role("companion-present-v1", "1"),
            agent_role("companion-firstlight-v1", "1"),
            agent_role("companion-flash-v1", "1"),
        ]
        role = roles[1]

        self.assertEqual(role.display_name, "智鼬·此刻")
        self.assertEqual([item.display_name for item in roles], ["智鼬·未来", "智鼬·此刻", "智鼬·初识", "智鼬·闪念"])
        self.assertEqual(len({item.persona_prompt for item in roles}), 4)
        for item in roles:
            with self.subTest(role=item.role_id):
                self.assertIn("catalog -> read -> trace", item.system_prompt)
                self.assertIn("今天、昨天、最近、上周", item.system_prompt)
                self.assertIn("隔离质量测试", item.system_prompt)
                self.assertIn("不能扩大", item.system_prompt)
                self.assertIn("只有受控审批回执有效", item.system_prompt)
                self.assertNotIn("DEEPSEEK_API_KEY", item.system_prompt)

        catalog = agent_role_catalog()
        self.assertEqual([item["roleId"] for item in catalog], ["companion-future-v1", "companion-present-v1", "companion-firstlight-v1", "companion-flash-v1"])
        self.assertTrue(all(item["schemaVersion"] == "rag-ime.agent-persona.v1" for item in catalog))
        self.assertTrue(all(item["safetyPolicyVersion"] == "control-center-safe-v1" for item in catalog))
        self.assertNotIn("systemPrompt", catalog[0])
        self.assertNotIn("personaPrompt", catalog[0])
        self.assertTrue(all(item["selectableModes"] == ["assistant", "coordinator"] for item in catalog))
        self.assertEqual(catalog[0]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-future-v1")
        self.assertEqual(catalog[1]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-present-v1")
        self.assertEqual(catalog[2]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-past-v1")
        self.assertEqual(catalog[3]["visualProfile"]["avatarAssetId"], "rag-ime-timeline-flash-v1")
        self.assertEqual(
            [item["defaults"]["modelPolicy"] for item in catalog],
            ["fixed", "fixed", "fixed", "fixed"],
        )
        self.assertEqual(
            [persona_model_profile(item) for item in roles],
            ["gpt/gpt-5.6-sol", "gpt/gpt-5.6-terra", "gpt/gpt-5.6-luna", "deepseek/deepseek-v4-flash"],
        )
        self.assertEqual(catalog[0]["visualProfile"]["accentToken"], "rose")
        self.assertTrue(catalog[0]["runtimeCharacteristics"]["isDefault"])

    def test_unknown_role_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported agent role"):
            agent_role("model-selected-role", "1")

    def test_legacy_role_ids_are_read_only_aliases_and_never_enter_the_catalog(self) -> None:
        aliases = {
            "vcp-v1": "companion-future-v1",
            "zhiyou-v1": "companion-present-v1",
            "hermes-v1": "companion-firstlight-v1",
            "flash-v1": "companion-flash-v1",
        }
        for legacy_id, canonical_id in aliases.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertEqual(agent_role(legacy_id, "1").role_id, canonical_id)
        serialized = repr(agent_role_catalog())
        for legacy_id in aliases:
            self.assertNotIn(f"'roleId': '{legacy_id}'", serialized)


if __name__ == "__main__":
    unittest.main()
