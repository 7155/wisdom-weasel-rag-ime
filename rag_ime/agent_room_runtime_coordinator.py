from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .agent_core_policy import core_agent_policy_prompt
from .agent_definition_compiler import AgentDefinitionCompiler
from .agent_personas import AgentPersonaStore
from .agent_prompt_plans import (
    PromptLayer,
    RoomPromptPlanStore,
    compose_persona_layer,
)
from .agent_room_capabilities import (
    RoomCapabilityManifestStore,
)
from .agent_room_tool_catalog import compose_room_tool_catalog
from .agent_room_context import (
    ProviderProjectionJournalStore,
    RoomContextLedgerStore,
)
from .agent_room_context_epochs import RoomSessionContextEpochStore
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_room_learning_runtime import RoomLearningRuntime
from .agent_room_profile_pins import RoomCollaborationProfilePins
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_runtime_capabilities import RoomRuntimeCapabilityService
from .agent_room_skills import RoomSkillPolicy, RoomSkillPolicyStore
from .agent_room_task_context import RoomTaskContextProjector
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
        context_epochs: RoomSessionContextEpochStore,
        skill_policy: RoomSkillPolicy,
        skill_receipts: RoomSkillPolicyStore,
        requirements: RequirementGovernanceStore,
        learning: RoomLearningGovernanceStore,
        learning_runtime: RoomLearningRuntime,
        definition_compiler: AgentDefinitionCompiler,
        role_book_prompt_resolver: Callable[[str], str],
        session_resolver: Callable[[str], Mapping[str, object]],
        product_tool_manifest_provider: Callable[
            [str], Mapping[str, Sequence[Mapping[str, object]]]
        ],
        work_document_provider: Callable[
            [str], Mapping[str, object] | None
        ],
    ) -> None:
        self.db_path = Path(db_path)
        self.rooms = rooms
        self.personas = personas
        self.kernel = kernel
        self.capabilities = capabilities
        self.prompt_plans = prompt_plans
        self.projection_journals = projection_journals
        self.context_ledger = context_ledger
        self.context_epochs = context_epochs
        self.skill_policy = skill_policy
        self.skill_receipts = skill_receipts
        self.requirements = requirements
        self.task_context = RoomTaskContextProjector(
            requirements,
            accepted_evidence_provider=(
                kernel.accepted_evidence_by_criterion
            ),
            work_document_provider=work_document_provider,
        )
        self.learning = learning
        self.learning_runtime = learning_runtime
        self.definition_compiler = definition_compiler
        self.role_book_prompt_resolver = role_book_prompt_resolver
        self.session_resolver = session_resolver
        self.product_tool_manifest_provider = product_tool_manifest_provider
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
        runtime_registry: Mapping[str, Mapping[str, object]],
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
            runtime_registry=runtime_registry,
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
        task = self.kernel.task(str(dispatch["taskId"]))
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
        session = self.session_resolver(session_id)
        intent_kind = str(dispatch.get("intentKind") or "")
        is_alignment = self.kernel.dispatch_is_preparable_alignment(dispatch_id)
        is_report = intent_kind == "close"
        role_id = _effective_dispatch_role_id(
            dispatch=dispatch,
            task=task,
            root=root,
        )
        role = collaboration_role(role_id)
        template_id = (
            {
                "coordinator": "planner",
                "researcher": "researcher",
                "reviewer": "reviewer",
            }.get(role_id, "worker")
        )
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
        context_epoch_transition = self.context_epochs.prepare_dispatch(
            session_id=session_id,
            root_id=str(dispatch["rootId"]),
            generation=generation,
            dispatch_id=dispatch_id,
            now_ms=prepared_at_ms,
        )
        context_epoch = int(context_epoch_transition["toEpoch"])
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
            # Report execution is read-only with respect to the workspace, but
            # it must still be able to append its one governed Room Post and
            # Commit. `room-binding.access=read` would collapse the manifest to
            # room_state only; filesystem mutability is fenced by the Task's
            # read_only workspace policy and the report-only tool catalog.
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
            context_epoch=context_epoch,
            generation=generation,
            created_at_ms=prepared_at_ms,
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
        context_dedupe_key = f"dispatch:{dispatch_id}:provider-context"
        context_entry = self.context_ledger.entry_by_dedupe_key(
            root_id=str(dispatch["rootId"]),
            dedupe_key=context_dedupe_key,
        )
        if context_entry is None:
            context_entry, _ = self.context_ledger.append_entry(
                root_id=str(dispatch["rootId"]),
                room_id=room_id,
                generation=generation,
                entry_kind="dispatch_state",
                source_ref=dispatch_id,
                dedupe_key=context_dedupe_key,
                content=self.task_context.render(
                    task,
                    dispatch,
                    room_id=room_id,
                ),
                created_at_ms=prepared_at_ms,
            )
        replay = [
            entry
            for entry in self.context_ledger.replay_root(str(dispatch["rootId"]))
            if int(entry["generation"]) == generation
        ]
        selected, omission = _bounded_provider_context_entries(
            replay,
            current_entry_id=str(context_entry["entryId"]),
        )
        if omission:
            omission_dedupe_key = f"dispatch:{dispatch_id}:context-omission"
            frozen_omission = self.context_ledger.entry_by_dedupe_key(
                root_id=str(dispatch["rootId"]),
                dedupe_key=omission_dedupe_key,
            )
            if frozen_omission is None:
                self.context_ledger.append_entry(
                    root_id=str(dispatch["rootId"]),
                    room_id=room_id,
                    generation=generation,
                    entry_kind="recovery_packet",
                    source_ref=dispatch_id,
                    dedupe_key=omission_dedupe_key,
                    content=json.dumps(
                        {
                            "schemaVersion": "wisdom-weasel.room-context-omission.v1",
                            "policy": "anchors-current-deduped-recent-public-v2",
                            **omission,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    created_at_ms=prepared_at_ms,
                )
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
            session=session,
            role_book_prompt=role_book_prompt,
            role=role,
            template=template,
            profile_pin=profile_pin,
            profile_overlay=profile_overlay,
            journal_id=journal_id,
            guard_pin=guard_pin,
        )
        prompt_receipt_id = f"prompt-compile:{dispatch_id}"
        frozen_prompt_receipt = self.prompt_plans.receipt(prompt_receipt_id)
        if frozen_prompt_receipt is None:
            prompt = self.prompt_plans.compile(
                receipt_id=prompt_receipt_id,
                room_binding=room_binding,
                participant_binding=participant_binding,
                journal_id=journal_id,
                session_epoch=max(1, generation + 1),
                context_epoch=context_epoch,
                skill_policy_revision=skill_policy_revision,
                context_policy_revision="room-context-policy-v1",
                layers=layers,
                created_at_ms=prepared_at_ms,
            )
        else:
            prompt = {"receipt": frozen_prompt_receipt}
        if prompt is None:
            raise RoomKernelFenceError(
                "managed Dispatch PromptCompile produced no receipt"
            )
        product_tools = self.product_tool_manifest_provider(session_id)
        tool_plan = compose_room_tool_catalog(
            available=_manifest_group(product_tools, "available"),
            user_authorized=_manifest_group(product_tools, "userAuthorized"),
            effective=_manifest_group(product_tools, "effective"),
        )
        user_authorized = tool_plan.user_authorized
        template_allowed = tool_plan.template_allowed
        role_allowed = tool_plan.role_allowed
        profile_allowed = tool_plan.profile_allowed
        state_allowed = tool_plan.state_allowed
        runtime_registry = tool_plan.runtime_registry
        if is_alignment:
            # Alignment owns the progressive definition step; execution and
            # collaboration remain unavailable until the definition fence has
            # been durably recorded and the next handoff is committed.
            alignment_tools = (
                "room_state",
                "room_post",
                "room_commit",
                "room_define",
            )
            user_authorized = alignment_tools
            template_allowed = alignment_tools
            role_allowed = alignment_tools
            profile_allowed = alignment_tools
            state_allowed = alignment_tools
            runtime_registry = {
                name: tool_plan.runtime_registry[name]
                for name in alignment_tools
            }
        elif is_report:
            # A ReportDispatch may project accepted Room evidence and publish
            # the single final report, but it cannot mutate work, delegate, or
            # reopen the execution graph.
            report_tools = (
                "room_state",
                "room_post",
                "room_commit",
            )
            user_authorized = report_tools
            template_allowed = report_tools
            role_allowed = report_tools
            profile_allowed = report_tools
            state_allowed = report_tools
            runtime_registry = {
                name: tool_plan.runtime_registry[name]
                for name in report_tools
            }
        bound = self.bind_capability_runtime(
            room_binding=room_binding,
            participant_binding=participant_binding,
            prompt_compile_receipt=prompt["receipt"],
            manifest_id=f"capability-manifest:{dispatch_id}",
            dispatch_id=dispatch_id,
            user_authorized=user_authorized,
            template_allowed=template_allowed,
            role_allowed=role_allowed,
            profile_allowed=profile_allowed,
            state_allowed=state_allowed,
            runtime_registry=runtime_registry,
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
        return {
            "sessionId": session_id,
            "manifestId": bound["manifest"]["manifestId"],
            "manifestHash": bound["manifest"]["manifestHash"],
            "promptCompileReceiptId": prompt["receipt"]["receiptId"],
            "promptPlanHash": prompt["receipt"]["plan"]["planHash"],
            "contextEpochTransition": context_epoch_transition,
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
        stage = _room_skill_stage(
            dispatch,
            alignment_chain=self.kernel.dispatch_is_active_alignment(dispatch_id),
        )
        selection = self.skill_policy.select_stage(stage)
        loaded = runtime_receipt.get("roomSkillLoad")
        if selection["selection"] == "required" and not isinstance(
            loaded,
            Mapping,
        ):
            raise RoomKernelFenceError(
                "Pi omitted the Skill required for this Room Dispatch stage"
            )
        if isinstance(loaded, Mapping):
            if (
                selection["selection"] != "required"
                or loaded.get("name") != selection["skillId"]
            ):
                raise RoomKernelFenceError(
                    "Pi loaded a Skill outside the required Room policy"
                )
            skill_id = str(loaded["name"])
            skill_hash = _required_text(loaded, "contentRevision")
            catalog_revision = _required_text(
                loaded,
                "catalogRevision",
            )
            capability_epoch = int(dispatch["capabilityEpoch"])
            dispatch_attempt = int(dispatch.get("attempt") or 0)
            skill_binding = {
                "dispatchId": dispatch_id,
                "capabilityEpoch": capability_epoch,
                "dispatchAttempt": dispatch_attempt,
                "stage": stage,
                "skillId": skill_id,
                "skillHash": skill_hash,
                "catalogRevision": catalog_revision,
                "policyId": self.skill_policy.policy_id,
                "policyVersion": self.skill_policy.version,
                "hashRule": self.skill_policy.hash_rule,
            }
            binding_hash = hashlib.sha256(
                json.dumps(
                    skill_binding,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            receipt_id = (
                f"room-skill-load:{dispatch_id}:{capability_epoch}:"
                f"{dispatch_attempt}:{binding_hash}"
            )
            prior = self.skill_receipts.latest_for_session(
                str(dispatch["targetSessionId"])
            )
            created_at_ms = (
                int(prior["createdAtMs"])
                if isinstance(prior, Mapping)
                and str(prior.get("receiptId") or "") == receipt_id
                else now_ms
            )
            self.skill_receipts.pin_skill(
                receipt_id=receipt_id,
                root_id=str(dispatch["rootId"]),
                task_id=str(dispatch["taskId"]),
                dispatch_id=dispatch_id,
                session_id=str(dispatch["targetSessionId"]),
                skill_id=skill_id,
                skill_hash=skill_hash,
                catalog_revision=catalog_revision,
                load_reason="stage_required",
                capability_epoch=capability_epoch,
                idempotency_key=(
                    f"{dispatch_id}/{capability_epoch}/{dispatch_attempt}/"
                    f"{stage}/{binding_hash}"
                ),
                created_at_ms=created_at_ms,
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


def _effective_dispatch_role_id(
    *,
    dispatch: Mapping[str, object],
    task: Mapping[str, object],
    root: Mapping[str, object],
) -> str:
    """Derive the current job from Kernel ownership, never a roster default."""

    intent_kind = str(dispatch.get("intentKind") or "")
    target_id = str(dispatch.get("targetParticipantId") or "")
    facilitator_id = str(root.get("facilitatorParticipantId") or "")
    if intent_kind == "align":
        if not facilitator_id or target_id != facilitator_id:
            raise RoomKernelFenceError(
                "alignment Dispatch must target the Root Facilitator"
            )
        return "coordinator"
    if intent_kind == "review" or str(task.get("taskKind") or "") == "review":
        return "reviewer"
    if intent_kind == "close":
        return "coordinator"
    if str(task.get("workspacePolicy") or "") == "isolated_writable":
        return "implementer"
    if str(task.get("workspacePolicy") or "") == "read_only":
        return "researcher"
    if facilitator_id and target_id == facilitator_id:
        return "coordinator"
    return "implementer"


def _prompt_layers(
    *,
    persona: PersonaManifest,
    session: Mapping[str, object],
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
            "pi-core-safety:v2",
            core_agent_policy_prompt(
                persona.safety_policy_prompt,
                session,
                # Room settlement is owned by the collaboration role's
                # `<room-work>` contract and the Room Kernel. Injecting the
                # ordinary Goal/Task state machine here would create a second
                # lifecycle owner with different terminal-state vocabulary.
                managed_work=False,
            ),
            ("safety", "authorization", "durable-memory"),
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
            template.room_runtime_prompt,
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
    parts = [profile.system_prompt.strip()] if profile.system_prompt.strip() else []
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


def _room_skill_stage(
    dispatch: Mapping[str, object],
    *,
    alignment_chain: bool = False,
) -> str:
    if alignment_chain:
        return "requirements"
    return {
        "align": "requirements",
        "execute": "implementation",
        "review": "vision-review",
        "revise": "feedback",
        "retry": "debugging",
        "resume": "implementation",
        "wake": "implementation",
        "callback": "handoff",
        "close": "closure",
    }.get(str(dispatch.get("intentKind") or ""), "implementation")


def _manifest_group(
    plan: Mapping[str, Sequence[Mapping[str, object]]],
    key: str,
) -> Sequence[Mapping[str, object]]:
    values = plan.get(key)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise RoomKernelFenceError(f"Room product Tool plan has no {key} group")
    return values


def _bounded_provider_context_entries(
    entries: list[dict[str, object]],
    *,
    current_entry_id: str,
) -> tuple[list[dict[str, object]], dict[str, int] | None]:
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
    original_requirement_texts = _original_requirement_texts(current)
    deduplicated_public_entries = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and entry.get("entryKind") == "room_post"
        and str(entry.get("content") or "").strip()
        in original_requirement_texts
    ]
    deduplicated_ids = {
        str(entry.get("entryId") or "")
        for entry in deduplicated_public_entries
    }
    anchors = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and entry.get("entryKind") == "root_state"
    ]
    recent = [
        entry
        for entry in entries
        if entry.get("entryId") != current_entry_id
        and str(entry.get("entryId") or "") not in deduplicated_ids
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
    omission = None
    if omitted_entries:
        omission = {
            "omittedEntryCount": len(omitted_entries),
            "omittedContentBytes": sum(
                len(str(entry.get("content") or "").encode("utf-8"))
                for entry in omitted_entries
            ),
            "deduplicatedEntryCount": len(deduplicated_public_entries),
            "deduplicatedContentBytes": sum(
                len(str(entry.get("content") or "").encode("utf-8"))
                for entry in deduplicated_public_entries
            ),
        }
    return [*chosen, current], omission


def _original_requirement_texts(
    current: Mapping[str, object],
) -> frozenset[str]:
    try:
        payload = json.loads(str(current.get("content") or ""))
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(payload, Mapping):
        return frozenset()
    requirements = payload.get("requirements")
    if not isinstance(requirements, Mapping):
        return frozenset()
    originals = requirements.get("original")
    if not isinstance(originals, list):
        return frozenset()
    return frozenset(
        text
        for original in originals
        if isinstance(original, Mapping)
        for text in [str(original.get("text") or "").strip()]
        if text
    )








def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value
