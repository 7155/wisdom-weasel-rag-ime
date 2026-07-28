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

    def test_room_lifecycle_distinguishes_parallel_help_from_sequential_handoff(
        self,
    ) -> None:
        prompt = collaboration_role("implementer", "1").system_prompt

        self.assertIn("最终验收或收口", prompt)
        self.assertIn("顺序责任转移", prompt)
        self.assertIn("不要提前把该成员作为并行子任务", prompt)
        self.assertIn("也不要用 wait 等待对方回填", prompt)
        self.assertIn("intent 必须是 close", prompt)
        self.assertIn("每个 AC 只提交直接支撑它的最小引用集合", prompt)
        self.assertIn("不得重写、拼接、猜测", prompt)
        self.assertIn("不运行\nsleep 或轮询命令等待参与者", prompt)
        self.assertIn("read、grep、find、ls", prompt)
        self.assertIn("精确文本修改使用 edit", prompt)
        self.assertIn("bash 只用于必须由命令完成的构建", prompt)
        self.assertIn("不做额外发现\n或加载", prompt)
        for hidden_name in (
            "workspace_read",
            "workspace_patch",
            "workspace_shell",
        ):
            self.assertNotIn(hidden_name, prompt)
        self.assertIn(
            "同一交付摘要不要先用 room_post 重复发布",
            prompt,
        )


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
