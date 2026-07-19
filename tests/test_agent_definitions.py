from __future__ import annotations

import json
import unittest
from pathlib import Path

from rag_ime.agent_definition_compiler import AgentDefinitionCompiler
from rag_ime.agent_definitions import (
    collaboration_profile,
    collaboration_profile_catalog,
    collaboration_role,
    collaboration_role_catalog,
)
from rag_ime.agent_roles import agent_role, agent_role_catalog
from rag_ime.agent_templates import agent_template, agent_template_catalog


FIXTURE = Path(__file__).with_name("fixtures") / "agent_definition_legacy_baseline.json"


class AgentDefinitionCompatibilityTests(unittest.TestCase):
    def test_legacy_persona_and_template_catalogs_are_byte_stable_fixtures(self) -> None:
        baseline = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(agent_role_catalog(), baseline["personas"])
        self.assertEqual(agent_template_catalog(), baseline["templates"])


class AgentDefinitionCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = AgentDefinitionCompiler()

    def test_four_layers_compile_to_versioned_binding_without_expanding_capability(self) -> None:
        compiled = self.compiler.compile(
            binding_id="binding-room-001",
            session_id="session-researcher-001",
            participant_id="participant-researcher",
            persona=agent_role("zhiyou-v1", "1"),
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
        self.assertEqual(binding["agentTemplateRef"]["id"], "researcher")
        self.assertEqual(
            binding["compiledRuntimeProfileRef"]["contentHash"],
            compiled.profile.content_hash,
        )

    def test_profile_and_role_requests_can_only_shrink_template_and_authorization(self) -> None:
        compiled = self.compiler.compile(
            binding_id="binding-ordinary-001",
            session_id="session-ordinary-001",
            participant_id="participant-ordinary",
            persona=agent_role("zhiyou-v1", "1"),
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
            participant_id="participant-stable",
            persona=agent_role("hermes-v1", "1"),
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

    def test_catalogs_are_read_only_contract_payloads_without_voice_or_tts_fields(self) -> None:
        roles = collaboration_role_catalog()
        profiles = collaboration_profile_catalog()

        self.assertEqual([item["roleId"] for item in roles], [
            "coordinator", "researcher", "implementer", "reviewer", "specialist",
        ])
        self.assertEqual(profiles[0]["profileId"], "evidence-review")
        serialized = json.dumps({"roles": roles, "profiles": profiles}, ensure_ascii=False).lower()
        self.assertNotIn("voiceprofile", serialized)
        self.assertNotIn("tts", serialized)
        self.assertNotIn("audio", serialized)


if __name__ == "__main__":
    unittest.main()
