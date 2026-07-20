from __future__ import annotations

import unittest

from rag_ime.agent_definitions import (
    collaboration_profile,
    collaboration_profile_catalog,
    collaboration_role,
    collaboration_role_catalog,
)
from rag_ime.agent_roles import agent_role, agent_role_catalog
from rag_ime.agent_templates import agent_template, agent_template_catalog


class AgentPromptAuditTests(unittest.TestCase):
    def test_every_builtin_definition_has_one_non_placeholder_executable_prompt(self) -> None:
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
                self.assertRegex(prompt, r"适用|任务")
                self.assertRegex(prompt, r"证据|工具|来源")
                self.assertRegex(prompt, r"交")
                self.assertRegex(prompt, r"已交付|完成|收工前")

    def test_personas_use_positive_handoff_triggers_instead_of_only_suppression(self) -> None:
        for item in agent_role_catalog():
            prompt = agent_role(item["roleId"], item["version"]).persona_prompt
            positive = sum(prompt.count(token) for token in ("适用", "先", "主动", "交接", "交付", "完成"))
            suppressive = sum(prompt.count(token) for token in ("不得", "禁止", "不要", "不能"))
            self.assertGreaterEqual(positive, suppressive, item["roleId"])


if __name__ == "__main__":
    unittest.main()
