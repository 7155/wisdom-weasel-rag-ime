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
from rag_ime.deepseek_memory_organizer import (
    DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION,
    _memory_book_recovery_prompt,
    _memory_book_system_prompt,
    _memory_curation_recovery_prompt,
    _memory_curation_system_prompt,
    _owner_memory_recovery_prompt,
    _owner_memory_system_prompt,
    _role_book_curation_system_prompt,
)
from rag_ime.memory_generator import (
    _core_optimization_system_prompt,
    _memory_generation_system_prompt,
)
from rag_ime.historical_memory_curation import (
    DEFAULT_HISTORICAL_CURATION_INSTRUCTION,
)


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
        self.assertEqual(prompts["profile:standard-room"], "")
        non_empty = {name: prompt for name, prompt in prompts.items() if prompt.strip()}
        self.assertEqual(
            len(set(non_empty.values())),
            len(non_empty),
            "each injected definition needs a unique prompt producer",
        )
        for name, prompt in prompts.items():
            with self.subTest(definition=name):
                if name == "profile:standard-room":
                    continue
                self.assertGreater(len(prompt.strip()), 80)
                self.assertNotRegex(prompt, r"(?i)\b(?:TODO|TBD)\b|未定|待补")

    def test_definition_layers_do_not_repeat_each_others_hard_rules(self) -> None:
        for item in agent_role_catalog():
            prompt = agent_role(item["roleId"], item["version"]).persona_prompt
            self.assertIn("<persona", prompt)
            self.assertNotIn("收工前", prompt)
            self.assertNotIn("已交付、已交接", prompt)
            self.assertNotIn("skill_load", prompt)
            self.assertNotIn("原生控制中心", prompt)
            self.assertNotIn("适用任务", prompt)
            self.assertNotIn("输入法", prompt)

        for item in agent_template_catalog():
            template = agent_template(item["templateId"], item["version"])
            self.assertIn("适用任务", template.prompt)
            self.assertIn("产物格式", template.prompt)
            self.assertNotIn("收工前", template.prompt)
            self.assertNotIn("已交付、已交接", template.prompt)
            self.assertIn("<capability-policy>", template.runtime_prompt)
            self.assertIn("能力家族索引在同一 Context Epoch 内保持稳定", template.runtime_prompt)
            self.assertIn("真正的已激活状态只看本轮 tools", template.runtime_prompt)
            self.assertIn("Skill 用 skill_search", template.runtime_prompt)
            self.assertIn("Tool 用 tool_search", template.runtime_prompt)
            self.assertIn("notFor 命中时不要加载", template.runtime_prompt)
            self.assertIn("skill_load", template.runtime_prompt)
            self.assertIn("tool_load", template.runtime_prompt)
            self.assertIn("每个 skill_load 调用一个精确 Skill", template.runtime_prompt)
            self.assertIn("不表示整个任务只能使用一个 Skill", template.runtime_prompt)
            self.assertIn("同一模型轮次并列调用，最多两份", template.runtime_prompt)
            self.assertIn("不要同时加载互相竞争的完整流程", template.runtime_prompt)
            self.assertIn("tool_load 一次加载 1 至 4 个精确", template.runtime_prompt)
            self.assertIn("不要为盘点、预热或猜测后续用途加载", template.runtime_prompt)
            self.assertNotIn(template.prompt, template.room_runtime_prompt)
            self.assertNotIn("当前 Room 的责任", template.room_runtime_prompt)
            self.assertIn("skill_load", template.room_runtime_prompt)
            self.assertIn("tool_load", template.room_runtime_prompt)

        for item in collaboration_role_catalog():
            prompt = collaboration_role(item["roleId"], item["version"]).system_prompt
            self.assertIn("<work-lens", prompt)
            self.assertIn("<room-work>", prompt)
            self.assertIn("room_commit", prompt)
            self.assertNotIn("收工前", prompt)
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
            if item["profileId"] == "standard-room":
                self.assertEqual(prompt, "")
                continue
            self.assertIn("<room-profile", prompt)
            self.assertNotIn("收工前", prompt)
            self.assertNotIn("skill_load", prompt)
            self.assertNotIn("原生控制中心", prompt)

    def test_room_lifecycle_keeps_root_requirements_as_boundary_not_child_work(self) -> None:
        prompt = collaboration_role("implementer", "1").system_prompt

        self.assertIn("根任务原始需求是不可变的上位边界", prompt)
        self.assertIn("开始与收工都要核对", prompt)
        self.assertIn("不会自动扩大", prompt)
        self.assertIn("只执行当前 Task/Dispatch", prompt)
        self.assertIn("只提交当前任务给出的验收别名", prompt)
        self.assertIn("不执行父任务或其他成员的步骤", prompt)
        self.assertIn("岗位只是工作视角，不形成主从层级", prompt)
        self.assertIn("当前 Dispatch 的持有者对产物和证据负责", prompt)
        self.assertIn("不清楚时调用 room_state", prompt)
        self.assertIn("成功工具结果返回的 evidenceRef", prompt)
        self.assertIn("postRef 只是公开消息引用，不是验收 evidenceRef", prompt)
        self.assertIn("不提交数据库 criterionId、pass、verdict", prompt)
        self.assertIn("暂存后立即结束本轮", prompt)

    def test_coordinator_owns_its_dispatch_instead_of_delegating_everything(self) -> None:
        prompt = collaboration_role("coordinator", "1").system_prompt

        self.assertIn("当前 Dispatch 要求直接产物时也完成自己的责任", prompt)
        self.assertIn("只有专业能力或并行收益明确时", prompt)
        self.assertIn("核对返回证据", prompt)

    def test_unpinned_role_book_is_zero_bytes_not_a_status_message(self) -> None:
        persona = agent_role("companion-present-v1", "1").persona_prompt
        without_role_book = compose_persona_layer(persona, "")
        with_role_book = compose_persona_layer(
            persona,
            "这位伙伴已经形成的稳定工作画像：\n- 协作偏好：先给结论",
        )

        self.assertEqual(without_role_book, persona.strip())
        self.assertNotIn("<agent-profile>", without_role_book)
        self.assertNotIn("revision_not_pinned", without_role_book)
        self.assertEqual(with_role_book.count("<agent-profile>"), 1)
        self.assertEqual(with_role_book.count("稳定工作画像"), 1)

    def test_memory_governance_prompts_are_agent_first(self) -> None:
        prompts = {
            "default_instruction": DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION,
            "atom_curation": _memory_curation_system_prompt(),
            "atom_recovery": _memory_curation_recovery_prompt(),
            "book_compile": _memory_book_system_prompt(),
            "book_recovery": _memory_book_recovery_prompt(),
            "owner_curation": _owner_memory_system_prompt(),
            "owner_recovery": _owner_memory_recovery_prompt(),
            "role_book": _role_book_curation_system_prompt(),
            "historical_curation": DEFAULT_HISTORICAL_CURATION_INSTRUCTION,
            "legacy_distillation": _memory_generation_system_prompt(max_count=3),
            "legacy_core_optimization": _core_optimization_system_prompt(
                max_memories=3,
                max_lexicon_phrases=4,
                max_hide_suggestions=5,
            ),
        }

        for name, prompt in prompts.items():
            with self.subTest(prompt=name):
                self.assertNotIn("你是 RAG 输入法", prompt)
                self.assertNotIn("你是一个输入法", prompt)
                self.assertNotIn("个人输入历史的语义整理器", prompt)
                self.assertNotIn("输入法 core/RAG/词库优化器", prompt)
        for name in (
            "default_instruction",
            "atom_curation",
            "book_compile",
            "book_recovery",
            "owner_curation",
            "historical_curation",
            "legacy_distillation",
            "legacy_core_optimization",
        ):
            self.assertRegex(prompts[name], r"Agent|个人 AI")

    def test_memory_and_lexicon_governance_stay_separate(self) -> None:
        book_prompt = _memory_book_system_prompt()
        legacy_prompt = _core_optimization_system_prompt(
            max_memories=3,
            max_lexicon_phrases=4,
            max_hide_suggestions=5,
        )

        self.assertIn("模型输出不能自行成为用户事实", book_prompt)
        self.assertIn("输入法或语音最终输入", book_prompt)
        self.assertIn("Rime", book_prompt)
        self.assertIn("三条路径不能互相冒充", legacy_prompt)
        self.assertIn("普通 Agent 回答", legacy_prompt)
        self.assertIn("不直接修改正式 Atom", legacy_prompt)


if __name__ == "__main__":
    unittest.main()
