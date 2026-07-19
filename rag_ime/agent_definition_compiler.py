from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .agent_definitions import CollaborationProfileManifest, CollaborationRoleManifest
from .agent_roles import PersonaManifest
from .agent_templates import AgentTemplate
from .contracts.json_schema import validate_contract


_COMPILER_VERSION = "agent-definition-compiler-v1"


@dataclass(frozen=True)
class DefinitionRef:
    kind: str
    definition_id: str
    version: str
    content_hash: str

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "id": self.definition_id,
            "version": self.version,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class CompiledAgentRuntimeProfile:
    compiler_version: str
    persona_ref: DefinitionRef
    collaboration_role_ref: DefinitionRef
    template_ref: DefinitionRef
    collaboration_profile_ref: DefinitionRef | None
    effective_capabilities: tuple[str, ...]
    rejected_capabilities: tuple[str, ...]
    capability_revision: str
    prompt_plan_revision: str
    skill_policy_revision: str
    context_policy_revision: str
    content_hash: str

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.compiled-agent-runtime-profile.v1",
            "compilerVersion": self.compiler_version,
            "personaRef": self.persona_ref.to_payload(),
            "collaborationRoleRef": self.collaboration_role_ref.to_payload(),
            "templateRef": self.template_ref.to_payload(),
            "collaborationProfileRef": (
                self.collaboration_profile_ref.to_payload()
                if self.collaboration_profile_ref is not None
                else None
            ),
            "effectiveCapabilities": list(self.effective_capabilities),
            "rejectedCapabilities": list(self.rejected_capabilities),
            "capabilityRevision": self.capability_revision,
            "promptPlanRevision": self.prompt_plan_revision,
            "skillPolicyRevision": self.skill_policy_revision,
            "contextPolicyRevision": self.context_policy_revision,
            "contentHash": self.content_hash,
        }
        validate_contract(payload, "compiled-agent-runtime-profile.v1.json")
        return payload


@dataclass(frozen=True)
class ParticipantBinding:
    binding_id: str
    session_id: str
    participant_id: str
    room_binding_ref: Mapping[str, str] | None
    persona_ref: DefinitionRef
    collaboration_role_ref: DefinitionRef
    template_ref: DefinitionRef
    collaboration_profile_ref: DefinitionRef | None
    compiled_runtime_profile_ref: Mapping[str, str]
    capability_revision: str
    capability_epoch: int

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-participant-binding.v2",
            "bindingId": self.binding_id,
            "sessionId": self.session_id,
            "participantId": self.participant_id,
            "roomBindingRef": dict(self.room_binding_ref) if self.room_binding_ref is not None else None,
            "personaRef": self.persona_ref.to_payload(),
            "collaborationRoleRef": self.collaboration_role_ref.to_payload(),
            "agentTemplateRef": self.template_ref.to_payload(),
            "collaborationProfileRef": (
                self.collaboration_profile_ref.to_payload()
                if self.collaboration_profile_ref is not None
                else None
            ),
            "compiledRuntimeProfileRef": dict(self.compiled_runtime_profile_ref),
            "capabilityRevision": self.capability_revision,
            "capabilityEpoch": self.capability_epoch,
        }
        _validate_participant_binding_projection(payload)
        return payload


@dataclass(frozen=True)
class AgentDefinitionCompilation:
    profile: CompiledAgentRuntimeProfile
    binding: ParticipantBinding


class AgentDefinitionCompiler:
    """Compile four declarative layers; authorization remains the upper bound."""

    def compile(
        self,
        *,
        binding_id: str,
        session_id: str,
        participant_id: str,
        persona: PersonaManifest,
        collaboration_role: CollaborationRoleManifest,
        template: AgentTemplate,
        profile: CollaborationProfileManifest | None,
        authorized_capabilities: tuple[str, ...],
        capability_revision: str,
        capability_epoch: int,
        prompt_plan_revision: str,
        skill_policy_revision: str,
        context_policy_revision: str,
        room_binding_ref: Mapping[str, str] | None = None,
    ) -> AgentDefinitionCompilation:
        authorized = set(_normalized(authorized_capabilities))
        requested = set(template.capabilities)
        requested &= set(collaboration_role.capability_restrictions)
        if profile is not None:
            requested &= set(profile.capability_requests)
        effective = tuple(sorted(authorized & requested))
        all_requested = set(template.capabilities) | set(collaboration_role.capability_restrictions)
        if profile is not None:
            all_requested |= set(profile.capability_requests)
        rejected = tuple(sorted(all_requested - set(effective)))

        persona_ref = _definition_ref("persona", persona.role_id, persona.version, persona.to_payload())
        role_ref = _definition_ref(
            "collaboration-role",
            collaboration_role.role_id,
            collaboration_role.version,
            collaboration_role.to_payload(),
        )
        template_ref = _definition_ref(
            "agent-template", template.template_id, template.version, template.to_payload()
        )
        profile_ref = (
            _definition_ref("collaboration-profile", profile.profile_id, profile.version, profile.to_payload())
            if profile is not None
            else None
        )
        profile_material: dict[str, object] = {
            "compilerVersion": _COMPILER_VERSION,
            "personaRef": persona_ref.to_payload(),
            "collaborationRoleRef": role_ref.to_payload(),
            "templateRef": template_ref.to_payload(),
            "collaborationProfileRef": profile_ref.to_payload() if profile_ref else None,
            "effectiveCapabilities": list(effective),
            "rejectedCapabilities": list(rejected),
            "capabilityRevision": _required(capability_revision, "capability_revision"),
            "promptPlanRevision": _required(prompt_plan_revision, "prompt_plan_revision"),
            "skillPolicyRevision": _required(skill_policy_revision, "skill_policy_revision"),
            "contextPolicyRevision": _required(context_policy_revision, "context_policy_revision"),
        }
        compiled_profile = CompiledAgentRuntimeProfile(
            compiler_version=_COMPILER_VERSION,
            persona_ref=persona_ref,
            collaboration_role_ref=role_ref,
            template_ref=template_ref,
            collaboration_profile_ref=profile_ref,
            effective_capabilities=effective,
            rejected_capabilities=rejected,
            capability_revision=str(profile_material["capabilityRevision"]),
            prompt_plan_revision=str(profile_material["promptPlanRevision"]),
            skill_policy_revision=str(profile_material["skillPolicyRevision"]),
            context_policy_revision=str(profile_material["contextPolicyRevision"]),
            content_hash=_content_hash(profile_material),
        )
        compiled_profile.to_payload()
        binding = ParticipantBinding(
            binding_id=_required(binding_id, "binding_id"),
            session_id=_required(session_id, "session_id"),
            participant_id=_required(participant_id, "participant_id"),
            room_binding_ref=_room_binding_ref(room_binding_ref),
            persona_ref=persona_ref,
            collaboration_role_ref=role_ref,
            template_ref=template_ref,
            collaboration_profile_ref=profile_ref,
            compiled_runtime_profile_ref={
                "profileId": f"compiled:{binding_id}",
                "revision": _COMPILER_VERSION,
                "contentHash": compiled_profile.content_hash,
            },
            capability_revision=compiled_profile.capability_revision,
            capability_epoch=max(0, int(capability_epoch)),
        )
        binding.to_payload()
        return AgentDefinitionCompilation(profile=compiled_profile, binding=binding)


def _definition_ref(kind: str, definition_id: str, version: str, payload: object) -> DefinitionRef:
    return DefinitionRef(kind, definition_id, version, _content_hash(payload))


def _content_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _normalized(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _room_binding_ref(value: Mapping[str, str] | None) -> Mapping[str, str] | None:
    if value is None:
        return None
    schema_version = str(value.get("schemaVersion") or "").strip()
    binding_id = str(value.get("bindingId") or "").strip()
    if schema_version != "wisdom-weasel.room-binding.v2" or not binding_id:
        raise ValueError("room_binding_ref must reference wisdom-weasel.room-binding.v2")
    return {"schemaVersion": schema_version, "bindingId": binding_id}


def _validate_participant_binding_projection(payload: Mapping[str, object]) -> None:
    """Narrow guard until lane A lands the canonical v2 JSON Schema."""

    if payload.get("schemaVersion") != "wisdom-weasel.room-participant-binding.v2":
        raise ValueError("unsupported participant binding schema")
    for field in ("bindingId", "sessionId", "participantId", "capabilityRevision"):
        if not str(payload.get(field) or "").strip():
            raise ValueError(f"participant binding {field} is required")
    profile_ref = payload.get("compiledRuntimeProfileRef")
    if not isinstance(profile_ref, Mapping):
        raise ValueError("participant binding compiledRuntimeProfileRef is required")
    content_hash = str(profile_ref.get("contentHash") or "")
    if not content_hash.startswith("sha256:") or len(content_hash) != 71:
        raise ValueError("participant binding compiledRuntimeProfileRef hash is invalid")
