from __future__ import annotations

import json
import unittest

from rag_ime.agent_definition_compiler import AgentDefinitionCompiler
from rag_ime.agent_room_kernel_contracts import validate_kernel_contract
from rag_ime.agent_definitions import (
    canonical_collaboration_role_id,
    collaboration_profile,
    collaboration_profile_catalog,
    collaboration_role,
    collaboration_role_catalog,
)
from rag_ime.agent_roles import agent_role, agent_role_catalog
from rag_ime.agent_templates import agent_template, agent_template_catalog
from rag_ime.contracts.json_schema import ContractValidationError


class AgentDefinitionCompatibilityTests(unittest.TestCase):
    def test_catalogs_are_versioned_and_have_unique_definitions(self) -> None:
        personas = agent_role_catalog()
        templates = agent_template_catalog()
        self.assertEqual(len(personas), 4)
        self.assertEqual(len(templates), 5)
        self.assertEqual(len({item["roleId"] for item in personas}), len(personas))
        self.assertEqual(len({item["templateId"] for item in templates}), len(templates))

    def test_room_lifecycle_separates_facilitator_implementation_and_review(
        self,
    ) -> None:
        facilitator = collaboration_role("coordinator", "1").system_prompt
        researcher = collaboration_role("researcher", "1").system_prompt
        implementer = collaboration_role("implementer", "1").system_prompt
        reviewer = collaboration_role("reviewer", "1").system_prompt

        for prompt in (facilitator, researcher, implementer, reviewer):
            content = prompt.replace("\n", "")
            self.assertIn("当前工作卡片是你这一轮唯一负责的部分", content)
            self.assertIn("room_state", content)
            self.assertIn("room_commit.evidence", content)
            self.assertIn("不得改写、拼接、猜测", content)
            self.assertIn("完成主张不得强于实际观察", content)
            self.assertIn("exact managed Pi transcript prefix", content)
            self.assertIn("不承诺 provider cache hit", content)
            self.assertIn("有界 Agent subagent/delegation", content)
            self.assertIn("不得邀请第三位 Room partner 或调用 room_collaborate", content)
            self.assertIn("workspace_lsp", content)
            self.assertIn(
                "status/symbols/hover/definition/references/diagnostics",
                content,
            )
            self.assertNotIn("workspace_read", content)
            self.assertNotIn("workspace_patch", content)
            self.assertNotIn("workspace_shell", content)
            self.assertEqual(prompt.count("## 让用户看得懂"), 1)
            self.assertIn("保持当前 Persona 的语气", content)
            self.assertIn("当前任务责任必须改变发言内容", content)
            self.assertIn("不是固定句式", content)
            self.assertIn("不要输出协议字段、JSON、回执套话", content)
            self.assertIn("不得只重复 label", content)
            self.assertIn("同时包含稳定的 value、短 label", content)
            self.assertIn("不要用“我已读取当前工作卡片”", content)
            self.assertIn("2–4 个互不依赖的必要问题", content)
            self.assertIn("questionKind=unbounded", content)
            self.assertIn("1A 2C", content)
            self.assertIn("只有当前只剩一个真正互斥的决定", content)
            self.assertNotIn("需求对齐一次只问一个", content)
            self.assertIn("伙伴使用相同模型和完整工作能力", content)
            self.assertIn("collaborationRole 只描述当前任务责任", content)
            self.assertIn("不得把伙伴固定为只读、摘要或低能力角色", content)
            self.assertIn("每位伙伴最多发布一条 conversationalupdate", content)
            self.assertIn("稳定的 Tool 活动面", content)

        self.assertIn("临时 Facilitator", facilitator)
        self.assertIn("room_collaborate", facilitator)
        self.assertIn("room_integrate", facilitator)
        self.assertIn(
            "room_commit(decision=handoff, intent=review)",
            facilitator.replace("\n", ""),
        )
        self.assertIn("当前计划或集成决定及其理由", facilitator)
        self.assertIn("实际核对的材料和它改变的判断", researcher)
        self.assertIn("不要代替独立审查", implementer)
        self.assertIn("可观察改动、验证结果和交回 Facilitator", implementer)
        self.assertIn("本轮只审查已经集成的完整结果", reviewer)
        self.assertIn("不得修改被审对象", reviewer)
        self.assertIn("通过或退回", reviewer)
        self.assertIn("不冒充最终用户回复", reviewer)


class AgentDefinitionCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = AgentDefinitionCompiler()

    def test_four_layers_compile_to_versioned_binding_without_expanding_capability(self) -> None:
        compiled = self.compiler.compile(
            binding_id="binding-room-001",
            session_id="session-researcher-001",
            persona=agent_role("companion-present-v1", "1"),
            collaboration_role=collaboration_role("researcher", "1"),
            template=agent_template("researcher", "1"),
            profile=collaboration_profile("evidence-review", "1"),
            authorized_capabilities=("rag", "memory", "review"),
            capability_revision="capability-revision-17",
            capability_epoch=4,
            prompt_plan_revision="prompt-plan-v1",
            skill_policy_revision="skill-policy-v1",
            context_policy_revision="context-policy-v1",
            room_binding_ref={
                "schemaVersion": "wisdom-weasel.room-binding.v2",
                "bindingId": "room-binding-001",
            },
        )

        self.assertEqual(compiled.profile.effective_capabilities, ("memory", "rag"))
        self.assertEqual(compiled.profile.rejected_capabilities, ("delegation", "review"))
        self.assertEqual(compiled.binding.room_binding_ref["bindingId"], "room-binding-001")
        self.assertEqual(compiled.binding.capability_epoch, 4)
        self.assertEqual(compiled.profile.to_payload()["schemaVersion"], "rag-ime.compiled-agent-runtime-profile.v1")
        binding = compiled.binding.to_payload()
        self.assertEqual(binding["schemaVersion"], "wisdom-weasel.room-participant-binding.v2")
        self.assertRegex(
            binding["agentTemplateRef"],
            r"^rag-ime-definition://agent-template/researcher\?version=1&contentHash=sha256:[a-f0-9]{64}$",
        )
        validate_kernel_contract("participantBinding", binding)
        self.assertNotIn("participantId", binding)
        self.assertEqual(
            binding["compiledRuntimeProfileRef"]["contentHash"],
            compiled.profile.content_hash,
        )

    def test_profile_and_role_requests_can_only_shrink_template_and_authorization(self) -> None:
        compiled = self.compiler.compile(
            binding_id="binding-ordinary-001",
            session_id="session-ordinary-001",
            persona=agent_role("companion-present-v1", "1"),
            collaboration_role=collaboration_role("reviewer", "1"),
            template=agent_template("reviewer", "1"),
            profile=collaboration_profile("evidence-review", "1"),
            authorized_capabilities=("control", "review", "rag"),
            capability_revision="capability-revision-18",
            capability_epoch=1,
            prompt_plan_revision="prompt-plan-v1",
            skill_policy_revision="skill-policy-v1",
            context_policy_revision="context-policy-v1",
        )

        self.assertEqual(compiled.profile.effective_capabilities, ("rag", "review"))
        self.assertNotIn("control", compiled.profile.effective_capabilities)
        self.assertNotIn("memory", compiled.profile.effective_capabilities)
        self.assertIsNone(compiled.binding.room_binding_ref)
        self.assertEqual(
            compiled.binding.to_payload()["compiledRuntimeProfileRef"]["revision"],
            "agent-definition-compiler-v1",
        )

    def test_compilation_is_canonical_across_authorization_order(self) -> None:
        kwargs = dict(
            binding_id="binding-stable-001",
            session_id="session-stable-001",
            persona=agent_role("companion-firstlight-v1", "1"),
            collaboration_role=collaboration_role("researcher", "1"),
            template=agent_template("researcher", "1"),
            profile=None,
            capability_revision="capability-revision-19",
            capability_epoch=1,
            prompt_plan_revision="prompt-plan-v1",
            skill_policy_revision="skill-policy-v1",
            context_policy_revision="context-policy-v1",
        )

        left = self.compiler.compile(authorized_capabilities=("rag", "memory"), **kwargs)
        right = self.compiler.compile(authorized_capabilities=("memory", "rag"), **kwargs)

        self.assertEqual(left.profile.content_hash, right.profile.content_hash)
        self.assertEqual(
            left.binding.compiled_runtime_profile_ref["contentHash"],
            right.binding.compiled_runtime_profile_ref["contentHash"],
        )

    def test_participant_binding_rejects_old_object_refs_and_participant_id(self) -> None:
        compiled = self.compiler.compile(
            binding_id="binding-contract-001",
            session_id="session-contract-001",
            persona=agent_role("companion-present-v1", "1"),
            collaboration_role=collaboration_role("researcher", "1"),
            template=agent_template("researcher", "1"),
            profile=None,
            authorized_capabilities=("rag", "memory"),
            capability_revision="capability-revision-contract",
            capability_epoch=1,
            prompt_plan_revision="prompt-plan-v1",
            skill_policy_revision="skill-policy-v1",
            context_policy_revision="context-policy-v1",
        )
        payload = compiled.binding.to_payload()
        object_ref = dict(payload)
        object_ref["personaRef"] = compiled.profile.persona_ref.to_payload()
        with self.assertRaises(ContractValidationError):
            validate_kernel_contract("participantBinding", object_ref)

        participant_projection = dict(payload)
        participant_projection["participantId"] = "participant-contract"
        with self.assertRaises(ContractValidationError):
            validate_kernel_contract("participantBinding", participant_projection)

    def test_catalogs_are_read_only_contract_payloads_without_voice_or_tts_fields(self) -> None:
        roles = collaboration_role_catalog()
        profiles = collaboration_profile_catalog()

        self.assertEqual([item["roleId"] for item in roles], [
            "coordinator", "researcher", "implementer", "reviewer", "specialist",
        ])
        self.assertEqual(
            [item["profileId"] for item in profiles],
            ["standard-room", "evidence-review"],
        )
        serialized = json.dumps({"roles": roles, "profiles": profiles}, ensure_ascii=False).lower()
        self.assertNotIn("voiceprofile", serialized)
        self.assertNotIn("tts", serialized)
        self.assertNotIn("audio", serialized)

    def test_retained_specialist_role_never_claims_domain_expertise(self) -> None:
        specialist = collaboration_role("specialist")
        catalog_entry = next(
            item
            for item in collaboration_role_catalog()
            if item["roleId"] == "specialist"
        )

        # Clicking a job title cannot grant industry knowledge. The role is kept
        # only so historical participants stay valid, so neither the catalog the
        # control center renders nor the prompt the model receives may present
        # it as expertise.
        self.assertNotIn("专家", str(catalog_entry["displayName"]))
        self.assertNotIn("专家", str(catalog_entry["summary"]))
        self.assertNotIn("领域知识", json.dumps(catalog_entry, ensure_ascii=False))
        self.assertIn("不要自称专家", specialist.system_prompt)
        self.assertEqual(
            specialist.capability_restrictions,
            ("memory", "rag"),
        )

    def test_legacy_executor_reads_resolve_to_implementer_without_rewrites(self) -> None:
        # Historical rows keep the old id on disk; every read resolves it to
        # the canonical role, and unknown or blank input is passed through for
        # the caller's own validation rather than silently repaired.
        self.assertEqual(canonical_collaboration_role_id("executor"), "implementer")
        self.assertEqual(canonical_collaboration_role_id(" executor "), "implementer")
        self.assertEqual(canonical_collaboration_role_id("reviewer"), "reviewer")
        self.assertEqual(canonical_collaboration_role_id(None), "implementer")
        self.assertEqual(canonical_collaboration_role_id(""), "implementer")
        self.assertEqual(canonical_collaboration_role_id("   "), "")
        self.assertEqual(canonical_collaboration_role_id("observer"), "observer")

    def test_every_role_declares_only_lifecycle_exits_the_kernel_enforces(self) -> None:
        for role in collaboration_role_catalog():
            with self.subTest(role=role["roleId"]):
                self.assertTrue(role["allowedCommitDecisions"])
                self.assertLessEqual(
                    set(role["allowedCommitDecisions"]),
                    {"deliver", "handoff", "wait", "blocked"},
                )


if __name__ == "__main__":
    unittest.main()
