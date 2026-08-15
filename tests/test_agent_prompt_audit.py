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
from rag_ime.agent_templates import (
    agent_template,
    agent_template_catalog,
    progressive_capability_policy,
)
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
            self.assertIn("<responsibility-profile", template.prompt)
            self.assertIn("职责：", template.prompt)
            self.assertIn("AgentResult", template.prompt)
            self.assertNotIn("适用任务", template.prompt)
            self.assertNotIn("产物格式", template.prompt)
            self.assertNotIn("收工前", template.prompt)
            self.assertNotIn("已交付、已交接", template.prompt)
            policy = progressive_capability_policy()
            self.assertTrue(template.runtime_prompt.endswith(policy))
            self.assertEqual(template.room_runtime_prompt, policy)
            self.assertNotIn(template.prompt, template.room_runtime_prompt)
            self.assertNotIn("当前 Room 的责任", template.room_runtime_prompt)

        for item in collaboration_role_catalog():
            prompt = collaboration_role(item["roleId"], item["version"]).system_prompt
            self.assertIn("<work-lens", prompt)
            self.assertIn("<room-work>", prompt)
            self.assertIn("room_partner", prompt)
            self.assertIn("普通 Pi Session", prompt)
            self.assertIn("唯一最终回复", prompt)
            self.assertNotIn("room_commit", prompt)
            self.assertNotIn("room_define", prompt)
            self.assertNotIn("room_collaborate", prompt)
            self.assertNotIn("收工前", prompt)

        for item in collaboration_profile_catalog():
            prompt = collaboration_profile(item["profileId"], item["version"]).system_prompt
            if item["profileId"] == "standard-room":
                self.assertEqual(prompt, "")
                continue
            self.assertIn("<room-profile", prompt)
            self.assertNotIn("收工前", prompt)
            self.assertNotIn("skill_load", prompt)
            self.assertNotIn("原生控制中心", prompt)

    def test_progressive_capability_policy_is_bounded_and_runtime_authoritative(
        self,
    ) -> None:
        policy = progressive_capability_policy()

        self.assertLessEqual(len(policy), 1_100)
        self.assertLessEqual(len(policy.encode("utf-8")), 2_400)
        for token in (
            "routing card",
            "catalog revision",
            "元数据",
            "nextCandidates 仅建议",
            "精确正文一次",
            "<loaded_skill> 同 revision 不重载",
            "Skill 是可复用方法，不拥有 Runtime 状态",
            "TaskBrief、ContextRefs、SkillRefs",
            "结果统一返回状态、摘要",
            "Runtime 实际能力/审批/取消/工作区/生命周期/owner",
            "deliverable",
            "新鲜、权威 evidence receipt",
            "缺失即未完成",
        ):
            with self.subTest(contract=token):
                self.assertIn(token, policy)

    def test_skill_composition_prompt_allows_only_complementary_pairing(
        self,
    ) -> None:
        policy = progressive_capability_policy()

        self.assertIn("简单任务不加载流程 Skill", policy)
        self.assertIn("一个职责 Skill 加一个任务方法", policy)
        self.assertIn("最多两个互补 Skill", policy)
        self.assertIn("已知行为且有测试缝隙用 test-driven-implementation", policy)
        self.assertIn("未知故障用 systematic-debugging", policy)
        self.assertIn("只有委派确有收益时用 orchestrate-session", policy)

    def test_skill_composition_prompt_rejects_overlapping_authority(self) -> None:
        policy = progressive_capability_policy()

        self.assertIn("禁止固定流水线和重复职责", policy)
        self.assertIn("facilitate-room 仅供 Room Facilitator", policy)
        self.assertIn("Partner 继续使用普通 Session Skill", policy)
        self.assertIn("Review 由用户要求或风险决定，不是必经门槛", policy)
        for retired in (
            "implementation-execution",
            "quality-gate",
            "review-feedback-resolution",
            "structured-handoff",
            "work-document-archive",
        ):
            self.assertNotIn(retired, policy)

    def test_routing_prompt_does_not_gate_clear_reversible_work_on_confirmation(
        self,
    ) -> None:
        policy = progressive_capability_policy()

        self.assertIn("先查可验证事实", policy)
        self.assertIn("授权内可逆默认直接执行", policy)
        self.assertIn("外部事实不可得则阻塞", policy)
        self.assertIn("调查后仅剩实质取舍", policy)
        self.assertIn("明确要求 Grill/挑战/压力测试", policy)
        self.assertIn("普通模式合并 1-4 个独立项、分开依赖项", policy)
        self.assertIn("禁裸“确认”", policy)
        self.assertIn(
            "Goal/In scope/Readiness 内部模板原样作最终聊天",
            policy,
        )
        self.assertIn("计划不算完成", policy)

    def test_room_lifecycle_uses_plain_language_for_bounded_peer_work(
        self,
    ) -> None:
        prompt = collaboration_role("implementer", "1").system_prompt

        self.assertIn("普通 Pi Session 的轻量组合", prompt)
        self.assertIn("使用 room_partner 查看伙伴并委派有界任务", prompt)
        self.assertIn("使用 agents\n创建微型子 Agent", prompt)
        self.assertIn("共享工作区允许普通写入", prompt)
        self.assertIn("不要代替独立审查", prompt)
        self.assertIn("伙伴结果不是整个 Room 的最终回复", prompt)
        self.assertNotIn("room_state", prompt)
        self.assertNotIn("room_commit", prompt)

    def test_facilitator_owns_integration_review_routing_and_final_reply(
        self,
    ) -> None:
        role = collaboration_role("coordinator", "1")
        prompt = role.system_prompt

        self.assertEqual(role.display_name, "主持整合者")
        self.assertIn("当前协作的临时 Facilitator", prompt)
        self.assertIn("集成、端到端验证", prompt)
        self.assertIn("正式 Room 伙伴时使用 room_partner 委派", prompt)
        self.assertIn("私有微型助手时使用 agents", prompt)
        self.assertIn("是否需要独立 Reviewer 由风险决定", prompt)
        self.assertIn("唯一最终回复", prompt)

    def test_facilitator_avoids_forced_fanout_and_fake_workspace_isolation(
        self,
    ) -> None:
        prompt = collaboration_role("coordinator", "1").system_prompt

        self.assertIn("只有工作确实独立时并行", prompt)
        self.assertIn("共享工作区允许普通写入", prompt)
        self.assertIn("有冲突风险时改为顺序执行", prompt)
        self.assertNotIn("isolated_writable", prompt)
        self.assertNotIn("Kernel", prompt)

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
