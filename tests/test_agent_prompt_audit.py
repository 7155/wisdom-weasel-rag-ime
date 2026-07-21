from __future__ import annotations

import unittest

from rag_ime.agent_definitions import (
    collaboration_profile,
    collaboration_profile_catalog,
    collaboration_role,
    collaboration_role_catalog,
)
from rag_ime.agent_roles import agent_role, agent_role_catalog
from rag_ime.agent_prompt_plans import compose_persona_layer
from rag_ime.agent_templates import agent_template, agent_template_catalog


class AgentPromptAuditTests(unittest.TestCase):
    def test_every_builtin_definition_has_one_non_placeholder_prompt(self) -> None:
        prompts: dict[str, str] = {}
        for item in agent_role_catalog():
            manifest = agent_role(item["roleId"], item["version"])
            prompts[f"persona:{manifest.role_id}"] = manifest.persona_prompt
        for item in agent_template_catalog():
            manifest = agent_template(item["templateId"], item["version"])
            prompts[f"template:{manifest.template_id}"] = manifest.prompt
        for item in collaboration_role_catalog():
            manifest = collaboration_role(item["roleId"], item["version"])
            prompts[f"role:{manifest.role_id}"] = manifest.system_prompt
        for item in collaboration_profile_catalog():
            manifest = collaboration_profile(item["profileId"], item["version"])
            prompts[f"profile:{manifest.profile_id}"] = manifest.system_prompt

        self.assertEqual(len(prompts), 16)
        self.assertEqual(len(set(prompts.values())), len(prompts), "each definition needs a unique prompt producer")
        for name, prompt in prompts.items():
            with self.subTest(definition=name):
                self.assertGreater(len(prompt.strip()), 80)
                self.assertNotRegex(prompt, r"(?i)\b(?:TODO|TBD)\b|未定|待补")

    def test_definition_layers_do_not_repeat_each_others_hard_rules(self) -> None:
        for item in agent_role_catalog():
            prompt = agent_role(item["roleId"], item["version"]).persona_prompt
            self.assertIn("适用任务", prompt)
            self.assertIn("表达气质", prompt)
            self.assertNotIn("收工前", prompt)
            self.assertNotIn("已交付、已交接", prompt)
            self.assertNotIn("skill_load", prompt)
            self.assertNotIn("原生控制中心", prompt)

        for item in agent_template_catalog():
            template = agent_template(item["templateId"], item["version"])
            self.assertIn("适用任务", template.prompt)
            self.assertIn("产物格式", template.prompt)
            self.assertNotIn("收工前", template.prompt)
            self.assertNotIn("已交付、已交接", template.prompt)
            self.assertIn("name、when、notFor、input、output、does", template.runtime_prompt)
            self.assertIn("skill_load", template.runtime_prompt)
            self.assertIn("tool_load", template.runtime_prompt)

        for item in collaboration_role_catalog():
            prompt = collaboration_role(item["roleId"], item["version"]).system_prompt
            self.assertIn("收工前", prompt)
            self.assertRegex(prompt, r"交接|交给|交回")
            positive = sum(
                prompt.count(token)
                for token in ("适用", "先", "主动", "交接", "提交", "完成")
            )
            suppressive = sum(
                prompt.count(token)
                for token in ("不得", "禁止", "不要", "不能")
            )
            self.assertGreaterEqual(positive, suppressive, item["roleId"])

        for item in collaboration_profile_catalog():
            prompt = collaboration_profile(item["profileId"], item["version"]).system_prompt
            self.assertIn("Room 路由覆盖层", prompt)
            self.assertNotIn("收工前", prompt)
            self.assertNotIn("skill_load", prompt)
            self.assertNotIn("原生控制中心", prompt)

    def test_unpinned_role_book_is_zero_bytes_not_a_status_message(self) -> None:
        persona = agent_role("companion-present-v1", "1").persona_prompt
        without_role_book = compose_persona_layer(persona, "")
        with_role_book = compose_persona_layer(
            persona,
            "RAG_IME_ROLE_BOOK_V1\n- 已验证偏好：先给结论",
        )

        self.assertEqual(without_role_book, persona.strip())
        self.assertNotIn("<agent-role-book>", without_role_book)
        self.assertNotIn("revision_not_pinned", without_role_book)
        self.assertEqual(with_role_book.count("<agent-role-book>"), 1)
        self.assertEqual(with_role_book.count("RAG_IME_ROLE_BOOK_V1"), 1)


if __name__ == "__main__":
    unittest.main()
