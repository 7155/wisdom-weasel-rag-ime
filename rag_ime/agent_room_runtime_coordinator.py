from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .agent_definition_compiler import AgentDefinitionCompiler
from .agent_personas import AgentPersonaStore
from .agent_prompt_plans import (
    PromptLayer,
    RoomPromptPlanStore,
    compose_persona_layer,
)
from .agent_room_capabilities import (
    RoomCapabilityManifestStore,
    room_runtime_registry,
)
from .agent_room_context import (
    ProviderProjectionJournalStore,
    RoomContextLedgerStore,
)
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_room_learning_runtime import RoomLearningRuntime
from .agent_room_profile_pins import RoomCollaborationProfilePins
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_runtime_capabilities import RoomRuntimeCapabilityService
from .agent_room_skills import RoomSkillPolicy, RoomSkillPolicyStore
from .agent_rooms import AgentRoomStore
from .agent_roles import PersonaManifest
from .agent_templates import agent_template
from .agent_definitions import (
    CollaborationProfileManifest,
    collaboration_role,
)


class RoomKernelRuntimeCoordinator:
    """Compile and fence the runtime state for one canonical Room Dispatch.

    The Kernel owns routing and state transitions. This coordinator owns the
    preparation boundary between a durable Dispatch and Pi Runtime: definitions,
    prompt layers, provider projection, Skills, and capability revocation.
    """

    def __init__(
        self,
        *,
        db_path: str | Path,
        rooms: AgentRoomStore,
        personas: AgentPersonaStore,
        kernel: RoomKernelStore,
        capabilities: RoomCapabilityManifestStore,
        prompt_plans: RoomPromptPlanStore,
        projection_journals: ProviderProjectionJournalStore,
        context_ledger: RoomContextLedgerStore,
        skill_policy: RoomSkillPolicy,
        skill_receipts: RoomSkillPolicyStore,
        requirements: RequirementGovernanceStore,
        learning: RoomLearningGovernanceStore,
        learning_runtime: RoomLearningRuntime,
        definition_compiler: AgentDefinitionCompiler,
        role_book_prompt_resolver: Callable[[str], str],
    ) -> None:
        self.db_path = Path(db_path)
        self.rooms = rooms
        self.personas = personas
        self.kernel = kernel
        self.capabilities = capabilities
        self.prompt_plans = prompt_plans
        self.projection_journals = projection_journals
        self.context_ledger = context_ledger
        self.skill_policy = skill_policy
        self.skill_receipts = skill_receipts
        self.requirements = requirements
        self.learning = learning
        self.learning_runtime = learning_runtime
        self.definition_compiler = definition_compiler
        self.role_book_prompt_resolver = role_book_prompt_resolver
        self.profile_pins = RoomCollaborationProfilePins(self.db_path)
        self.runtime_capabilities = RoomRuntimeCapabilityService(
            kernel=kernel,
            capabilities=capabilities,
            skill_receipts=skill_receipts,
        )

    def bind_capability_runtime(
        self,
        *,
        room_binding: Mapping[str, object],
        participant_binding: Mapping[str, object],
        prompt_compile_receipt: Mapping[str, object],
        manifest_id: str,
        dispatch_id: str,
        user_authorized: Sequence[str],
        template_allowed: Sequence[str],
        role_allowed: Sequence[str],
        profile_allowed: Sequence[str],
        state_allowed: Sequence[str],
        created_at_ms: int,
        runtime_state: str = "active",
    ) -> dict[str, object]:
        return self.runtime_capabilities.bind(
            room_binding=room_binding,
            participant_binding=participant_binding,
            prompt_compile_receipt=prompt_compile_receipt,
            manifest_id=manifest_id,
            dispatch_id=dispatch_id,
            user_authorized=user_authorized,
            template_allowed=template_allowed,
            role_allowed=role_allowed,
            profile_allowed=profile_allowed,
            state_allowed=state_allowed,
            created_at_ms=created_at_ms,
            runtime_state=runtime_state,
        )

    def prepare_dispatch(
        self,
        dispatch: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        """Durably prepare Prompt/Profile/Capability before Kernel leasing."""

        del now_ms
        dispatch_id = _required_text(dispatch, "dispatchId")
        prepared_at_ms = self.kernel.dispatch_enqueued_at(dispatch_id)
        session_id = _required_text(dispatch, "targetSessionId")
        root = self.kernel.root(_required_text(dispatch, "rootId"))
        room_id = str(root["roomId"])
        participant = self.rooms.participant_for_session(session_id)
        if participant is None or participant.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "managed Dispatch Session has no canonical Room participant"
            )
        persona = self.personas.resolve(
            participant.get("roleId"),
            participant.get("roleVersion") or "1",
        )
        role_book_prompt = self.role_book_prompt_resolver(session_id)
        role_id = str(participant.get("collaborationRole") or "implementer")
        if role_id == "executor":
            role_id = "implementer"
        role = collaboration_role(role_id)
        template_id = {
            "coordinator": "planner",
            "researcher": "researcher",
            "reviewer": "reviewer",
        }.get(str(participant.get("collaborationRole") or ""), "worker")
        template = agent_template(template_id)
        active_profile, profile_pin = self.profile_pins.resolve(
            root,
            pinned_at_ms=prepared_at_ms,
        )
        capability_revision = _required_text(
            dispatch,
            "runtimeProfileRevision",
        )
        generation = int(dispatch["generation"])
        capability_epoch = int(dispatch["capabilityEpoch"])
        room_binding = {
            "schemaVersion": "wisdom-weasel.room-binding.v2",
            "bindingId": f"room-binding:{dispatch_id}",
            "rootId": dispatch["rootId"],
            "roomId": room_id,
            "participantId": participant["id"],
            "taskId": dispatch["taskId"],
            "generation": generation,
            "protocolRevision": "room-v2",
            "capabilityRevision": capability_revision,
            "access": "write",
        }
        participant_binding_id = f"participant-binding:{dispatch_id}"
        guard_pin = self.learning.guard_for_root(
            binding_id=participant_binding_id,
            root_id=str(dispatch["rootId"]),
            scope_key=f"room:{room_id}",
        )
        guard_surfaces = (
            self.learning.materialized_guard(
                scope_key=str(guard_pin["scopeKey"]),
                guard_epoch=int(guard_pin["guardEpoch"]),
                config_hash=str(guard_pin["configHash"]),
            )
            if guard_pin is not None
            else None
        )
        skill_policy_revision = (
            f"room-skill-policy-v1@{guard_pin['configHash']}"
            if guard_pin is not None
            else "room-skill-policy-v1"
        )
        compiled = self.definition_compiler.compile(
            binding_id=participant_binding_id,
            session_id=session_id,
            persona=persona,
            collaboration_role=role,
            template=template,
            profile=active_profile,
            authorized_capabilities=(
                "control",
                "delegation",
                "memory",
                "planning",
                "rag",
                "review",
            ),
            capability_revision=capability_revision,
            capability_epoch=capability_epoch,
            prompt_plan_revision="room-prompt-plan-v1",
            skill_policy_revision=skill_policy_revision,
            context_policy_revision="room-context-policy-v1",
            room_binding_ref={
                "bindingId": room_binding["bindingId"],
                "schemaVersion": room_binding["schemaVersion"],
            },
        )
        participant_binding = compiled.binding.to_payload()
        journal_id = f"room-journal:{dispatch_id}"
        self.projection_journals.open_journal(
            journal_id=journal_id,
            root_id=str(dispatch["rootId"]),
            room_id=room_id,
            binding_id=str(participant_binding["bindingId"]),
            session_id=session_id,
            session_epoch=max(1, generation + 1),
            context_epoch=max(1, capability_epoch + 1),
            generation=generation,
            created_at_ms=prepared_at_ms,
        )
        task = self.kernel.task(str(dispatch["taskId"]))
        context_entry, _ = self.context_ledger.append_entry(
            root_id=str(dispatch["rootId"]),
            room_id=room_id,
            generation=generation,
            entry_kind="dispatch_state",
            source_ref=dispatch_id,
            dedupe_key=f"dispatch:{dispatch_id}:provider-context",
            content=_bounded_dispatch_context(task, dispatch),
            created_at_ms=prepared_at_ms,
        )
        replay = [
            entry
            for entry in self.context_ledger.replay_root(str(dispatch["rootId"]))
            if int(entry["generation"]) == generation
        ]
        selected, omitted = _bounded_provider_context_entries(
            replay,
            current_entry_id=str(context_entry["entryId"]),
        )
        if omitted:
            omission_entry, _ = self.context_ledger.append_entry(
                root_id=str(dispatch["rootId"]),
                room_id=room_id,
                generation=generation,
                entry_kind="recovery_packet",
                source_ref=dispatch_id,
                dedupe_key=f"dispatch:{dispatch_id}:context-omission",
                content=json.dumps(
                    {
                        "schemaVersion": "wisdom-weasel.room-context-omission.v1",
                        "policy": "anchors-current-and-recent-public-v1",
                        "omittedEntryCount": omitted[0],
                        "omittedContentBytes": omitted[1],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at_ms=prepared_at_ms,
            )
            selected.insert(-1, omission_entry)
        for entry in selected:
            self.projection_journals.append_entry(
                journal_id,
                str(entry["entryId"]),
                dedupe_key=f"context-entry:{entry['entryId']}",
                expected_generation=generation,
                appended_at_ms=prepared_at_ms,
            )
        profile_overlay = _profile_overlay_prompt(
            active_profile,
            guard_surfaces["prompt"] if guard_surfaces is not None else None,
        )
        layers = _prompt_layers(
            persona=persona,
            role_book_prompt=role_book_prompt,
            role=role,
            template=template,
            profile_pin=profile_pin,
            profile_overlay=profile_overlay,
            journal_id=journal_id,
            guard_pin=guard_pin,
        )
        prompt = self.prompt_plans.compile(
            receipt_id=f"prompt-compile:{dispatch_id}",
            room_binding=room_binding,
            participant_binding=participant_binding,
            journal_id=journal_id,
            session_epoch=max(1, generation + 1),
            context_epoch=max(1, capability_epoch + 1),
            skill_policy_revision=skill_policy_revision,
            context_policy_revision="room-context-policy-v1",
            layers=layers,
            created_at_ms=prepared_at_ms,
        )
        if prompt is None:
            raise RoomKernelFenceError(
                "managed Dispatch PromptCompile produced no receipt"
            )
        tools = tuple(room_runtime_registry())
        bound = self.bind_capability_runtime(
            room_binding=room_binding,
            participant_binding=participant_binding,
            prompt_compile_receipt=prompt["receipt"],
            manifest_id=f"capability-manifest:{dispatch_id}",
            dispatch_id=dispatch_id,
            user_authorized=tools,
            template_allowed=tools,
            role_allowed=tools,
            profile_allowed=tools,
            state_allowed=tools,
            created_at_ms=prepared_at_ms,
            runtime_state="prepared",
        )
        if guard_pin is not None:
            self.learning.bind_execution(
                dispatch_id=dispatch_id,
                root_id=str(dispatch["rootId"]),
                scope_key=str(guard_pin["scopeKey"]),
                guard_epoch=int(guard_pin["guardEpoch"]),
                config_hash=str(guard_pin["configHash"]),
                now_ms=prepared_at_ms,
            )
        requirement_binding, _ = self.requirements.prepare_dispatch_binding(
            dispatch_id=dispatch_id,
            root_id=str(dispatch["rootId"]),
            task_id=str(dispatch["taskId"]),
            session_id=session_id,
            generation=generation,
            requirement_anchor_ref=str(
                root.get("requirementAnchorRef") or ""
            ),
            created_at_ms=prepared_at_ms,
        )
        return {
            "sessionId": session_id,
            "manifestId": bound["manifest"]["manifestId"],
            "manifestHash": bound["manifest"]["manifestHash"],
            "promptCompileReceiptId": prompt["receipt"]["receiptId"],
            "promptPlanHash": prompt["receipt"]["plan"]["planHash"],
            "requirementObservation": requirement_binding,
            "guardPin": guard_pin,
        }

    def accept_runtime_context(
        self,
        runtime_receipt: Mapping[str, object],
    ) -> None:
        dispatch_id = _required_text(runtime_receipt, "dispatchId")
        dispatch = self.kernel.dispatch(dispatch_id)
        now_ms = int(time.time() * 1000)
        provider = runtime_receipt.get("providerContextReceipt")
        if (
            isinstance(provider, Mapping)
            and int(provider.get("throughSequence") or 0) > 0
        ):
            projection = self.projection_journals.projection(
                str(provider.get("journalId") or ""),
                expected_generation=int(dispatch["generation"]),
            )
            if int(provider["throughSequence"]) > int(
                projection["sealedThroughSequence"]
            ):
                self.projection_journals.record_provider_receipt(
                    str(provider["journalId"]),
                    receipt_id=f"provider-projection:{dispatch_id}",
                    provider_request_id=_required_text(
                        provider,
                        "providerRequestId",
                    ),
                    through_sequence=int(provider["throughSequence"]),
                    projection_hash=_required_text(
                        provider,
                        "projectionHash",
                    ),
                    expected_generation=int(dispatch["generation"]),
                    created_at_ms=now_ms,
                )
        loaded = runtime_receipt.get("roomSkillLoad")
        if isinstance(loaded, Mapping):
            stage = _room_skill_stage(dispatch)
            selection = self.skill_policy.select_stage(stage)
            if (
                selection["selection"] != "required"
                or loaded.get("name") != selection["skillId"]
            ):
                raise RoomKernelFenceError(
                    "Pi loaded a Skill outside the required Room policy"
                )
            self.skill_receipts.pin_skill(
                receipt_id=f"room-skill-load:{dispatch_id}",
                root_id=str(dispatch["rootId"]),
                task_id=str(dispatch["taskId"]),
                dispatch_id=dispatch_id,
                session_id=str(dispatch["targetSessionId"]),
                skill_id=str(loaded["name"]),
                skill_hash=_required_text(loaded, "contentRevision"),
                catalog_revision=_required_text(
                    loaded,
                    "catalogRevision",
                ),
                load_reason="stage_required",
                capability_epoch=int(dispatch["capabilityEpoch"]),
                idempotency_key=f"{dispatch_id}/{stage}",
                created_at_ms=now_ms,
            )

    def resolve_collaboration_profile(
        self,
        root: Mapping[str, object],
        *,
        pinned_at_ms: int,
    ) -> tuple[CollaborationProfileManifest, dict[str, object]]:
        return self.profile_pins.resolve(root, pinned_at_ms=pinned_at_ms)

    def record_learning_signal(
        self,
        signal: Mapping[str, object],
    ) -> None:
        now_ms = int(
            signal.get("createdAtMs") or int(time.time() * 1000)
        )
        self.persist_learning_event(
            root_id=str(signal["rootId"]),
            dispatch_id=str(signal["dispatchId"]),
            taxonomy="tool_failure",
            failure_signature=(
                f"runtime_failed:{signal.get('reason') or 'unknown'}"
            ),
            reason=f"runtime_failed:{signal.get('reason') or 'unknown'}",
            now_ms=now_ms,
        )

    def persist_learning_event(
        self,
        *,
        root_id: str,
        dispatch_id: str,
        taxonomy: str,
        failure_signature: str,
        reason: str,
        now_ms: int,
    ) -> dict[str, object] | None:
        receipt = self.kernel.record_learning_signal(
            root_id=root_id,
            dispatch_id=dispatch_id,
            receipt_kind=(
                "dead_letter" if taxonomy == "tool_failure" else "rejected"
            ),
            status=(
                "unknown" if taxonomy == "tool_failure" else "rejected"
            ),
            reason=reason,
            now_ms=now_ms,
        )
        return self.learning_runtime.record_signal(
            root_id=root_id,
            dispatch_id=dispatch_id,
            kernel_receipt_id=str(receipt["receiptId"]),
            taxonomy=taxonomy,
            failure_signature=failure_signature,
            evidence_refs=[str(receipt["receiptId"])],
            observed_at_ms=now_ms,
        )

    def revoke_session(self, session_id: str, now_ms: int) -> None:
        self.runtime_capabilities.revoke(session_id, now_ms)


def _prompt_layers(
    *,
    persona: PersonaManifest,
    role_book_prompt: str,
    role: object,
    template: object,
    profile_pin: Mapping[str, object],
    profile_overlay: str,
    journal_id: str,
    guard_pin: Mapping[str, object] | None,
) -> tuple[PromptLayer, ...]:
    return (
        PromptLayer(
            "core_rails",
            "pi-core-safety",
            "pi-core-safety:v1",
            persona.safety_policy_prompt,
            ("safety", "authorization"),
        ),
        PromptLayer(
            "persona",
            "persona-compiler",
            f"persona:{persona.role_id}@{persona.version}",
            compose_persona_layer(
                persona.persona_prompt,
                role_book_prompt,
            ),
            ("identity", "role-memory"),
        ),
        PromptLayer(
            "collaboration_role",
            "collaboration-role-compiler",
            f"collaboration-role:{role.role_id}@{role.version}",
            role.system_prompt,
            ("collaboration-duty",),
        ),
        PromptLayer(
            "agent_template_policy",
            "template-capability-compiler",
            f"agent-template:{template.template_id}@{template.version}",
            template.runtime_prompt,
            ("tool-policy", "skill-policy"),
        ),
        PromptLayer(
            "room_profile_overlay",
            (
                "guard-materialization"
                if guard_pin is not None
                else "profile-room-kernel-compiler"
            ),
            (
                str(guard_pin["configHash"])
                if guard_pin is not None
                else str(profile_pin["bundleContentHash"])
            ),
            profile_overlay,
            ("room-overlay",),
            "guard-active" if guard_pin is not None else "profile-pinned",
        ),
        PromptLayer(
            "provider_dynamic_facts",
            "room-context-compiler",
            journal_id,
            "",
            ("dynamic-facts",),
        ),
    )


def _profile_overlay_prompt(
    profile: CollaborationProfileManifest,
    guard: object,
) -> str:
    parts = [profile.system_prompt.strip()]
    if isinstance(guard, Mapping):
        condition = guard.get("condition")
        action = guard.get("action")
        if isinstance(condition, Mapping) and isinstance(action, Mapping):
            parts.extend(
                (
                    "已审核的 Room Guard 只在以下条件命中时进一步收紧行为：",
                    json.dumps(
                        {"condition": dict(condition), "action": dict(action)},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
    return "\n".join(parts)


def _room_skill_stage(dispatch: Mapping[str, object]) -> str:
    return {
        "execute": "implementation",
        "review": "review",
        "revise": "feedback",
        "retry": "debugging",
        "resume": "implementation",
        "wake": "implementation",
        "callback": "handoff",
    }.get(str(dispatch.get("intentKind") or ""), "implementation")


def _bounded_dispatch_context(
    task: Mapping[str, object],
    dispatch: Mapping[str, object],
) -> str:
    task_projection = {
        key: task.get(key)
        for key in (
            "taskId",
            "rootId",
            "parentTaskId",
            "ownerParticipantId",
            "assigneeParticipantId",
            "revision",
            "state",
        )
    }
    task_projection.update(
        objective=_bounded_text(task.get("objective"), maximum=4_000),
        expectedOutput=_bounded_text(
            task.get("expectedOutput"),
            maximum=2_000,
        ),
        requirementItemIds=[
            _bounded_text(value, maximum=240)
            for value in list(task.get("requirementItemIds") or ())[:128]
        ],
        acceptanceCriterionIds=[
            _bounded_text(value, maximum=240)
            for value in list(
                task.get("acceptanceCriterionIds") or ()
            )[:128]
        ],
    )
    return json.dumps(
        {
            "task": task_projection,
            "dispatch": {
                key: dispatch[key]
                for key in (
                    "dispatchId",
                    "taskId",
                    "intentKind",
                    "generation",
                    "hopCount",
                    "depth",
                    "targetParticipantId",
                )
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _bounded_provider_context_entries(
    entries: list[dict[str, object]],
    *,
    current_entry_id: str,
) -> tuple[list[dict[str, object]], tuple[int, int] | None]:
    maximum_entries = 24
    maximum_bytes = 64 * 1024
    checkpoint_reserve = 512
    current = next(
        (
            entry
            for entry in entries
            if entry.get("entryId") == current_entry_id
        ),
        None,
    )
    if current is None:
        raise RoomKernelFenceError(
            "current Dispatch context entry is missing"
        )
    current_bytes = len(
        str(current.get("content") or "").encode("utf-8")
    )
    if current_bytes + checkpoint_reserve > maximum_bytes:
        raise RoomKernelFenceError(
            "current Dispatch context exceeds provider projection budget"
        )
    anchors = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and entry.get("entryKind") in {"requirement_anchor", "root_state"}
    ]
    recent = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and entry.get("entryKind")
        in {
            "room_post",
            "room_commit",
            "evidence_receipt",
            "knowledge_receipt",
            "skill_receipt",
        }
    ]
    chosen: list[dict[str, object]] = []
    used_bytes = current_bytes
    for entry in [*anchors[:8], *reversed(recent)]:
        if entry in chosen or len(chosen) >= maximum_entries - 2:
            continue
        size = len(str(entry.get("content") or "").encode("utf-8"))
        if used_bytes + size + checkpoint_reserve > maximum_bytes:
            continue
        chosen.append(entry)
        used_bytes += size
    chosen.sort(key=lambda entry: int(entry.get("sequence") or 0))
    chosen_ids = {
        str(entry.get("entryId") or "") for entry in chosen
    }
    omitted_entries = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and str(entry.get("entryId") or "") not in chosen_ids
    ]
    omitted = None
    if omitted_entries:
        omitted = (
            len(omitted_entries),
            sum(
                len(str(entry.get("content") or "").encode("utf-8"))
                for entry in omitted_entries
            ),
        )
    return [*chosen, current], omitted








def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[: max(0, maximum)]


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value
