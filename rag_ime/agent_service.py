from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from threading import RLock

from .agent_configuration import (
    AgentConfigurationStore,
    AgentControlEventHub,
    default_agent_configuration,
    runtime_policy_from_configuration,
)
from .agent_approval_application import AgentApprovalApplicationService
from .agent_context_runtime import AgentContextRuntime
from .agent_command_receipts import AgentCommandReceiptStore
from .agent_events import AgentEventHub
from .agent_event_projection import AgentEventProjectionService
from .agent_block_store import AgentBlockStore
from .agent_delegation import AgentDelegationCoordinator
from .agent_media import AgentMediaStore
from .agent_memory_context import AgentMemoryContextService
from .agent_memory_context_support import (
    compaction_summary as _compaction_summary,
)
from .agent_memory_evidence import AgentMemoryEvidenceService
from .agent_message_snapshot import AgentMessageSnapshotService
from .agent_memory_sources import AgentMemorySourceStore
from .agent_personas import AgentPersonaStore
from .agent_prompt_application import AgentPromptApplicationService
from .agent_prompt_delivery import AgentPromptDeliveryService
from .agent_prompt_support import (
    optional_client_message_id as _optional_client_message_id,
)
from .agent_protocol import AgentEventEnvelope
from .agent_role_book import AgentRoleBookStore
from .agent_role_application import AgentRoleApplicationService
from .agent_session_application import AgentSessionApplicationService
from .agent_session_branching import AgentSessionBranchingService
from .agent_session_policy import AgentSessionPolicyService
from .agent_room_intercom import (
    AgentRoomIntercomRouter,
    AgentRoomIntercomStore,
)
from .agent_room_intercom_application import (
    RoomIntercomApplicationService,
)
from .agent_room_legacy_dispatch import RoomLegacyDispatchService
from .agent_room_legacy_cancellation import RoomLegacyCancellationService
from .agent_room_management import RoomManagementService
from .agent_room_prompt_context import (
    agent_message_text as _agent_message_text,
    room_intercom_prompt as _room_intercom_prompt,
    room_participant_prompt as _room_participant_prompt,
)
from .agent_room_capabilities import (
    RoomCapabilityManifestStore,
    room_runtime_registry,
)
from .agent_room_application import RoomApplicationService
from .agent_definition_compiler import AgentDefinitionCompiler
from .collaboration_profile_control import CollaborationProfileControl
from .agent_definitions import CollaborationProfileManifest
from .agent_task_context import AgentTaskContextResolver
from .agent_prompt_plans import RoomPromptPlanStore
from .agent_room_context import ProviderProjectionJournalStore, RoomContextLedgerStore
from .agent_room_skills import RoomSkillPolicy, RoomSkillPolicyStore
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_peer_review import RoomPeerReviewStore
from .agent_room_route_owners import room_route_owner
from .agent_room_work import AgentRoomWorkStore
from .agent_room_work_application import RoomWorkApplicationService
from .agent_room_kernel import KernelMode, RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel_application import RoomKernelApplicationService
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus, RoomKernelWorker, RoomKernelWorkerLoop
from .agent_room_runtime_coordinator import RoomKernelRuntimeCoordinator
from .agent_room_turn_registry import RoomTurnRegistry
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_governance_projection import GovernanceProjectionStore
from .agent_room_learning_runtime import ReflectionProvider, RoomLearningRuntime
from .agent_knowledge_promotion import KNOWLEDGE_ROUTE_HASH, KnowledgePromotionStore
from .knowledge_scope import bound_session_knowledge_caller
from .agent_runtime_driver import (
    AgentRuntimePolicy,
    AgentRuntimeDriver,
    RuntimeDriverContext,
    RuntimeDriverFactory,
    ToolManifestProvider,
)
from .agent_rooms import AgentRoomEventHub, AgentRoomStore
from .agent_roles import PersonaManifest
from .agent_sessions import AgentSessionStore
from .agent_wake_scheduler import AgentWakeScheduleStore, AgentWakeScheduler
from .agent_wake_application import AgentWakeApplicationService
from .contracts.json_schema import validate_contract
from .embeddings import EmbeddingProvider
from .observability import ObservationHub
from .pi_runtime import PiRuntimeConfig, PiRuntimeDriverFactory
from .personal_context import (
    AgentMemoryEvidenceStore,
    PersonalContextConsolidator,
)
from .session_memory_recall import SessionMemoryRecallBuilder
from .text_utils import compact_whitespace

ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT = 12
ROOM_CONTEXT_HISTORY_CHAR_BUDGET = 3_600
ROOM_CONTEXT_PROMPT_CHAR_BUDGET = 24_000
ROOM_MESSAGE_CHAR_LIMIT = 8_000


class AgentService:
    def __init__(
        self,
        *,
        db_path: str | Path,
        runtime_config: PiRuntimeConfig | None = None,
        runtime_factory: RuntimeDriverFactory | None = None,
        configuration_defaults: Mapping[str, object] | None = None,
        project: str = "",
        process_id_provider: Callable[[], int] = os.getpid,
        tool_gateway_url: str = "http://127.0.0.1:8766/api/agent/tool/execute",
        tool_gateway_token: str = "",
        memory_embedding_provider: EmbeddingProvider | None = None,
        wake_scheduler_enabled: bool = False,
        wake_scheduler_poll_seconds: float = 1.0,
        room_kernel_mode: KernelMode = "off",
        room_runner_secrets: Mapping[str, bytes | str] | None = None,
        room_delivery_gate_enforcement: bool = False,
        room_artifact_hash_provider: Callable[[str], str] | None = None,
        room_kernel_poll_seconds: float = 0.25,
        collaboration_profile_signers: Mapping[str, bytes] | None = None,
        room_learning_authority_secrets: Mapping[str, bytes | str] | None = None,
        room_guard_config_secret: bytes | str | None = None,
        room_reflection_provider: ReflectionProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = str(project or "")
        self.personas = AgentPersonaStore(db_path)
        self.personas.initialize()
        self.role_books = AgentRoleBookStore(db_path)
        self.role_books.initialize()
        self.tool_token = str(tool_gateway_token or secrets.token_urlsafe(32))
        self.tool_gateway_url = str(tool_gateway_url).strip()
        if not self.tool_gateway_url:
            raise ValueError("tool gateway URL must not be empty")
        self._tool_manifest_provider: ToolManifestProvider | None = None
        configured = replace(
            runtime_config or PiRuntimeConfig.from_environment(),
            tool_gateway_token=self.tool_token,
            tool_gateway_url=self.tool_gateway_url,
            role_resolver=self.personas.resolve,
            role_book_resolver=self.role_books.prompt_block,
        )
        self.runtime_factory = runtime_factory or PiRuntimeDriverFactory(configured)
        self.sessions = AgentSessionStore(db_path)
        self.sessions.initialize()
        self.context_runtime = AgentContextRuntime(db_path)
        self.context_runtime.initialize()
        self.command_receipts = AgentCommandReceiptStore(db_path)
        self.command_receipts.initialize()
        seed_configuration = dict(
            configuration_defaults
            or default_agent_configuration(
                enabled=configured.enabled,
                idle_timeout_seconds=configured.idle_timeout_seconds,
                model_profile=self.runtime_factory.default_model_profile,
            )
        )
        self.configuration_store = AgentConfigurationStore(db_path)
        self.configuration_store.initialize(seed_configuration)
        self.control_events = AgentControlEventHub(self.configuration_store)
        self._configuration_lock = RLock()
        self._context_source_token = object()
        self.room_turns = RoomTurnRegistry()
        # Compatibility aliases for the legacy dispatcher/canceller. The
        # registry owns these collections; no second source of truth exists.
        self._room_turn_lock = self.room_turns.lock
        self._pending_room_turn_by_session = (
            self.room_turns.pending_turn_by_session
        )
        self._pending_room_dispatch_by_session = (
            self.room_turns.pending_dispatch_by_session
        )
        self._room_turn_by_session_turn = (
            self.room_turns.turn_by_session_turn
        )
        self._room_dispatch_by_session_turn = (
            self.room_turns.dispatch_by_session_turn
        )
        self._room_topic_by_room_turn = (
            self.room_turns.topic_by_room_turn
        )
        self._room_user_priority_sessions = (
            self.room_turns.user_priority_sessions
        )
        self._cancelled_room_turns = (
            self.room_turns.cancelled_turns
        )
        self._cancelled_room_root_by_session = (
            self.room_turns.cancelled_root_by_session
        )
        self._cancelled_room_turn_by_session_turn = (
            self.room_turns.cancelled_turn_by_session_turn
        )
        self.runtime_factory.apply_policy(
            runtime_policy_from_configuration(
                self.configuration_store.snapshot()["configuration"]
            )
        )
        self.media = AgentMediaStore(db_path)
        self.media.initialize()
        self.agent_blocks = AgentBlockStore(db_path)
        self.agent_blocks.initialize()
        self.memory_sources = AgentMemorySourceStore(db_path, project=project)
        self.memory_sources.initialize()
        self.memory_evidence = AgentMemoryEvidenceStore(db_path, project=self.project)
        self.memory_evidence.initialize()
        self.memory_bootstrap = SessionMemoryRecallBuilder(
            db_path,
            project=self.project,
            embedding_provider=memory_embedding_provider,
        )
        self.memory_bootstrap.initialize()
        self.personal_context = PersonalContextConsolidator(
            db_path,
            project=self.project,
            role_book_applier=self.role_books,
        )
        self.personal_context.initialize()
        self.rooms = AgentRoomStore(
            db_path,
            room_dir=(
                self.runtime_factory.session_root.expanduser().resolve(strict=False).parent
                / "rooms"
            ),
        )
        self.rooms.initialize()
        self.room_work = AgentRoomWorkStore(db_path)
        self.room_work.initialize()
        self.room_kernel = RoomKernelStore(
            db_path,
            mode=room_kernel_mode,
            enforce_test_delivery_gate=room_delivery_gate_enforcement,
        )
        self.room_kernel.initialize()
        self.room_kernel_projection = RoomKernelProjection(db_path)
        self.room_kernel_projection.initialize()
        self.room_capabilities = RoomCapabilityManifestStore(db_path)
        self.room_capabilities.initialize()
        self.room_prompt_plans = RoomPromptPlanStore(db_path)
        self.room_prompt_plans.initialize()
        self.room_projection_journals = ProviderProjectionJournalStore(db_path)
        self.room_projection_journals.initialize()
        self.room_context_ledger = RoomContextLedgerStore(db_path)
        self.room_context_ledger.initialize()
        room_skill_root = Path(__file__).resolve().parents[1] / "integrations" / "pi"
        self.room_skill_policy = RoomSkillPolicy(
            room_skill_root / "room-skill-policy.json",
            room_skill_root / "skills",
        )
        self.room_skill_receipts = RoomSkillPolicyStore(db_path, self.room_skill_policy)
        self.room_skill_receipts.initialize()
        self.room_requirements = RequirementGovernanceStore(db_path)
        self.room_requirements.initialize()
        self.room_peer_review = RoomPeerReviewStore(db_path, runner_secrets=room_runner_secrets)
        self.room_peer_review.initialize()
        self.room_learning = RoomLearningGovernanceStore(
            db_path,
            authority_secrets=room_learning_authority_secrets,
            config_secret=room_guard_config_secret,
        )
        self.room_learning.initialize()
        self.governance_projection = GovernanceProjectionStore(db_path)
        self.governance_projection.initialize()
        self.room_learning_runtime = RoomLearningRuntime(
            self.room_learning,
            reflection_provider=room_reflection_provider,
        )
        self.knowledge_promotion = KnowledgePromotionStore(db_path)
        self.knowledge_promotion.initialize()
        self._room_artifact_hash_provider = room_artifact_hash_provider
        self.agent_definition_compiler = AgentDefinitionCompiler()
        self._collaboration_profile_signers = {
            str(signer_id): bytes(key)
            for signer_id, key in (collaboration_profile_signers or {}).items()
        }
        self._room_kernel_poll_seconds = room_kernel_poll_seconds
        self.observations = ObservationHub(db_path)
        self.room_events = AgentRoomEventHub(self.rooms)
        self._remove_observation_room_observer = self.room_events.add_observer(
            self.observations.enqueue_room_event
        )
        self.events = AgentEventHub(
            sequence_loader=self.sessions.max_event_sequence,
            event_recorder=self._record_event,
            event_observer=self._mirror_event_to_room,
        )
        self.runtime: AgentRuntimeDriver = self.runtime_factory.create(
            RuntimeDriverContext(
                sessions=self.sessions,
                events=self.events,
                media_resolver=self.media.resolve_pi_image,
                tool_gateway_token=self.tool_token,
                tool_gateway_url=self.tool_gateway_url,
                tool_manifest_provider=self._runtime_tool_manifest,
                compaction_observer=self._checkpoint_runtime_compaction,
            ),
            purpose="interactive",
            session_context_provider=self._runtime_session_context,
        )
        self.role_application = AgentRoleApplicationService(
            personas=self.personas,
            runtime=self.runtime,
            runtime_factory=self.runtime_factory,
        )
        # Build the Room runtime graph now, but do not start its worker until
        # every callback owner used by on_change has been constructed.
        self._bind_room_kernel_runtime(start_worker=False)
        initial_configuration = self.configuration_store.snapshot()
        if (
            initial_configuration["sync"]["state"] != "synchronized"
            or initial_configuration["sync"]["appliedRevision"]
            != initial_configuration["revision"]
        ):
            _, reconciled_event = self.configuration_store.mark_applied(
                int(initial_configuration["revision"]),
                runtime_status=self.runtime.runtime_status(),
            )
            self.control_events.fan_out(reconciled_event)
        self.delegation = AgentDelegationCoordinator(
            db_path=db_path,
            runtime_config=configured,
            sessions=self.sessions,
            events=self.events,
            media_resolver=self.media.resolve_pi_image,
            runtime_driver_factory=self.runtime_factory,
            tool_gateway_token=self.tool_token,
            compaction_observer=self._checkpoint_runtime_compaction,
        )
        self.session_application = AgentSessionApplicationService(
            sessions=self.sessions,
            runtime_provider=lambda: self.runtime,
            runtime_factory=self.runtime_factory,
            personas=self.personas,
            role_books=self.role_books,
            configuration_store=self.configuration_store,
            rooms=self.rooms,
            delegation=self.delegation,
            media=self.media,
            events=self.events,
            runtime_status=lambda: self.runtime_status(),
            initial_role_runtime_defaults=self._initial_role_runtime_defaults,
            pending_memory_bootstrap=self._pending_memory_bootstrap,
            ensure_session_role_book=lambda session_id: (
                self._ensure_session_role_book(session_id)
            ),
            probe_memory_maintenance=lambda session_id, **kwargs: (
                self._probe_memory_maintenance(session_id, **kwargs)
            ),
        )
        self.session_policy = AgentSessionPolicyService(
            sessions=self.sessions,
            runtime_provider=lambda: self.runtime,
            personas=self.personas,
            rooms=self.rooms,
            events=self.events,
            runtime_status=lambda: self.runtime_status(),
            probe_memory_maintenance=lambda session_id, **kwargs: (
                self._probe_memory_maintenance(session_id, **kwargs)
            ),
        )
        self.session_branching = AgentSessionBranchingService(
            sessions=self.sessions,
            runtime_provider=lambda: self.runtime,
            runtime_factory=self.runtime_factory,
            rooms=self.rooms,
            delegation=self.delegation,
            media=self.media,
            events=self.events,
            command_receipts=self.command_receipts,
            ensure_session_role_book=lambda session_id: (
                self._ensure_session_role_book(session_id)
            ),
            prompt_with_checkpoint=lambda **kwargs: (
                self._prompt_with_checkpoint(**kwargs)
            ),
        )
        self.task_context = AgentTaskContextResolver(
            delegation=self.delegation,
            rooms=self.rooms,
            room_capabilities=self.room_capabilities,
            room_kernel=self.room_kernel,
            room_requirements=self.room_requirements,
        )
        self.memory_context_application = (
            AgentMemoryContextService(
                sessions=self.sessions,
                personas=self.personas,
                role_books=self.role_books,
                memory_bootstrap=self.memory_bootstrap,
                context_runtime=self.context_runtime,
                task_context=self.task_context,
                room_capabilities=self.room_capabilities,
                room_prompt_plans=self.room_prompt_plans,
                room_skill_receipts=self.room_skill_receipts,
                room_skill_policy=self.room_skill_policy,
                runtime_provider=lambda: self.runtime,
            )
        )
        self.memory_evidence_application = (
            AgentMemoryEvidenceService(
                sessions=self.sessions,
                memory_evidence=self.memory_evidence,
                message_text=_agent_message_text,
            )
        )
        self.prompt_delivery_application = (
            AgentPromptDeliveryService(
                sessions=self.sessions,
                context_runtime=self.context_runtime,
                runtime_provider=lambda: self.runtime,
                runtime_tool_manifest=lambda session: (
                    self._runtime_tool_manifest(session)
                ),
            )
        )
        self.prompt_application = AgentPromptApplicationService(
            sessions=self.sessions,
            command_receipts=self.command_receipts,
            configuration_store=self.configuration_store,
            media=self.media,
            events=self.events,
            memory_sources=self.memory_sources,
            memory_context=self.memory_context_application,
            memory_evidence=self.memory_evidence_application,
            prompt_delivery_service=(
                self.prompt_delivery_application
            ),
            runtime_provider=lambda: self.runtime,
            runtime_status=lambda: self.runtime_status(),
            create_session=lambda payload: (
                self.create_session(payload)
            ),
            dispatch_checkpoint=lambda **kwargs: (
                self._prompt_with_checkpoint(**kwargs)
            ),
            context_source_token=self._context_source_token,
            transient_context_char_budget=(
                ROOM_CONTEXT_PROMPT_CHAR_BUDGET
            ),
        )
        self.event_projection_application = (
            AgentEventProjectionService(
                sessions=self.sessions,
                room_kernel=self.room_kernel,
                rooms=self.rooms,
                agent_blocks=self.agent_blocks,
                observations=self.observations,
                room_kernel_projection=(
                    self.room_kernel_projection
                ),
                room_events=self.room_events,
                room_turns=self.room_turns,
                append_recent_message=(
                    lambda session_id, message: (
                        self._append_recent_recall_message(
                            session_id,
                            message,
                        )
                    )
                ),
                record_assistant_evidence=(
                    lambda event: (
                        self._record_assistant_evidence_safely(
                            event
                        )
                    )
                ),
                notify_intercom=lambda: (
                    getattr(self, "room_intercom", None)
                    and self.room_intercom.notify()
                ),
            )
        )
        self.room_intercom_application = (
            RoomIntercomApplicationService(
                sessions=self.sessions,
                rooms=self.rooms,
                room_work=self.room_work,
                context_runtime=self.context_runtime,
                room_events=self.room_events,
                runtime_provider=lambda: self.runtime,
                user_priority_sessions=(
                    self._room_user_priority_sessions
                ),
                turn_lock=self._room_turn_lock,
                guard_legacy_room_route=(
                    lambda route_id, session_id: (
                        self._guard_legacy_room_route(
                            route_id,
                            session_id,
                        )
                    )
                ),
                runtime_prompt_with_context=(
                    lambda session_id, message, **kwargs: (
                        self._runtime_prompt_with_context(
                            session_id,
                            message,
                            **kwargs,
                        )
                    )
                ),
                room_intercom_prompt=_room_intercom_prompt,
                room_participant_prompt=(
                    _room_participant_prompt
                ),
                publish_room_work_activity=(
                    lambda work, **kwargs: (
                        self._publish_room_work_activity(
                            work,
                            **kwargs,
                        )
                    )
                ),
            )
        )
        self.room_intercom = AgentRoomIntercomRouter(
            AgentRoomIntercomStore(db_path),
            generation_provider=self._room_runtime_generation,
            idle_probe=self._room_target_idle,
            delivery_handler=self._deliver_room_intercom,
            audit_publisher=self._publish_room_intercom_audit,
        )
        self.room_work.reconcile_intercom_outcomes()
        self._approval_executor: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None
        self._memory_maintenance_probe: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None
        self._process_id_provider = process_id_provider
        self.wake_schedules = AgentWakeScheduleStore(db_path)
        self.wake_schedules.initialize()
        self.wake_application = AgentWakeApplicationService(
            schedules=self.wake_schedules,
            sessions=self.sessions,
            personas=self.personas,
            rooms=self.rooms,
            context_runtime=self.context_runtime,
            events=self.events,
            create_session=lambda payload: self.create_session(payload),
            prompt=lambda session_id, payload: self.prompt(
                session_id,
                payload,
            ),
            guard_legacy_room_route=lambda route_id, session_id: (
                self._guard_legacy_room_route(route_id, session_id)
            ),
            context_source_token=self._context_source_token,
        )
        self.wake_scheduler = AgentWakeScheduler(
            store=self.wake_schedules,
            dispatch=self.wake_application.dispatch,
            enabled=wake_scheduler_enabled,
            poll_seconds=wake_scheduler_poll_seconds,
            max_parallel=2,
        )
        self.wake_application.bind_scheduler(self.wake_scheduler)
        self._remove_wake_observer = self.events.add_observer(
            self.wake_scheduler.observe_event
        )
        self.room_legacy_dispatch = RoomLegacyDispatchService(
            self,
            build_participant_prompt=_room_participant_prompt,
        )
        self.room_legacy_cancellation = RoomLegacyCancellationService(self)
        self.room_work_application = RoomWorkApplicationService(self)
        self.approval_application = AgentApprovalApplicationService(self)
        self.message_snapshot = AgentMessageSnapshotService(
            sessions=self.sessions,
            runtime=self.runtime,
            agent_blocks=self.agent_blocks,
            observations=self.observations,
            events=self.events,
        )
        self.room_management = RoomManagementService(
            rooms=self.rooms,
            sessions=self.sessions,
            personas=self.personas,
            events=self.room_events,
            create_session=lambda payload: (
                self.create_session(payload)
            ),
            delete_session=lambda session_id: (
                self.delete_session(session_id)
            ),
            runtime_status=lambda: self.runtime_status(),
            turn_lock=self._room_turn_lock,
            pending_turns=self._pending_room_turn_by_session,
            user_priority_sessions=self._room_user_priority_sessions,
        )
        self.room_kernel_worker_loop.start()

    def bind_approval_executor(
        self,
        executor: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        self._approval_executor = executor

    def bind_memory_maintenance_probe(
        self,
        probe: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        self._memory_maintenance_probe = probe

    def bind_tool_manifest_provider(self, provider: ToolManifestProvider) -> None:
        """Bind the backend-owned tool catalog without exposing gateway credentials."""

        self._tool_manifest_provider = provider

    def list_context_items(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.sessions.get(session_id)
        value = dict(payload or {})
        items = self.context_runtime.list_items(
            session_id,
            status=str(value.get("status") or ""),
            limit=_integer(value.get("limit"), default=100, minimum=1, maximum=500),
        )
        return {
            "schemaVersion": "rag-ime.agent-context-inbox.v1",
            "ok": True,
            "sessionId": session_id,
            "items": items,
        }

    def acknowledge_context_item(
        self,
        session_id: str,
        item_id: str,
    ) -> dict[str, object]:
        self.sessions.get(session_id)
        return {
            "schemaVersion": "rag-ime.agent-context-item-ack.v1",
            "ok": True,
            "sessionId": session_id,
            "item": self.context_runtime.acknowledge(session_id, item_id),
        }

    def list_context_traces(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.sessions.get(session_id)
        value = dict(payload or {})
        return {
            "schemaVersion": "rag-ime.agent-context-trace-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": self.context_runtime.list_traces(
                session_id,
                limit=_integer(value.get("limit"), default=30, minimum=1, maximum=100),
            ),
        }

    def context_trace(self, session_id: str, trace_id: str) -> dict[str, object]:
        self.sessions.get(session_id)
        trace = self.context_runtime.trace(trace_id)
        if trace["sessionId"] != session_id:
            raise KeyError(trace_id)
        return trace

    def debug_context(self, session_id: str, turn_id: str = "") -> dict[str, object]:
        self.sessions.get(session_id)
        provider = getattr(self.runtime, "debug_context", None)
        if not callable(provider):
            return {
                "schemaVersion": "rag-ime.pi-debug-context-response.v1",
                "sessionId": session_id,
                "turnId": str(turn_id or ""),
                "available": False,
                "transient": True,
                "context": None,
                "telemetry": None,
                "reason": "runtime does not expose transient debug context",
            }
        return dict(provider(session_id, str(turn_id or "")))

    def _runtime_tool_manifest(
        self,
        session: Mapping[str, object],
    ) -> list[Mapping[str, object]]:
        runtime_capability = self.room_capabilities.manifest_for_runtime(str(session.get("id") or ""))
        if runtime_capability is not None:
            manifest, _binding = runtime_capability
            registry = room_runtime_registry()
            return [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": registry[str(tool["name"])]["inputSchema"],
                    "when": list(tool["when"]),
                    "notFor": list(tool["notFor"]),
                    "input": tool["input"],
                    "output": tool["output"],
                    "does": tool["does"],
                    "profile": "room-kernel-v2",
                    "risk": tool["risk"],
                }
                for tool in manifest["tools"]
                if isinstance(tool, Mapping) and tool.get("authorized") is True
            ]
        if self.room_capabilities.runtime_binding(str(session.get("id") or ""), active_only=False) is not None:
            return []
        provider = self._tool_manifest_provider
        if provider is None:
            return []
        return [dict(item) for item in provider(session)]

    def _runtime_session_context(self, session: Mapping[str, object]) -> Mapping[str, object]:
        bound = self.room_capabilities.manifest_for_runtime(str(session.get("id") or ""))
        if bound is None:
            tombstone = self.room_capabilities.runtime_binding(
                str(session.get("id") or ""), active_only=False
            )
            if tombstone is not None:
                return {
                    "roomCapability": {
                        "manifestId": tombstone["manifestId"],
                        "manifestHash": tombstone["manifestHash"],
                        "capabilityEpoch": tombstone["capabilityEpoch"],
                        "status": tombstone["state"],
                    }
                }
            return {}
        manifest, binding = bound
        prompt = self.room_prompt_plans.provider_payload(
            str(binding["promptCompileReceiptId"])
        )
        dispatch = self.room_kernel.dispatch(str(manifest["dispatchId"]))
        root_limits = self.room_kernel.resource_limits(str(dispatch["rootId"]))
        skill_selection = self.room_skill_policy.select_stage(
            _room_skill_stage(dispatch)
        )
        result: dict[str, object] = {
            "roomCapability": {
                "manifestId": manifest["manifestId"],
                "manifestHash": manifest["manifestHash"],
                "promptCompileReceiptId": binding["promptCompileReceiptId"],
                "promptPlanHash": binding["promptPlanHash"],
                "compiledRuntimeProfileRef": binding["compiledRuntimeProfileRef"],
                "capabilityEpoch": binding["capabilityEpoch"],
            },
            "managedSystemPrompt": prompt["stableSystemPrompt"],
            "providerContext": prompt["providerContext"],
            "roomProviderContext": {
                "journalId": prompt["journalId"],
                "throughSequence": prompt["throughSequence"],
                "projectionHash": prompt["projectionHash"],
                "generation": prompt["generation"],
            },
            "roomResourceLimits": {
                "deadlineAtMs": root_limits["deadline_at_ms"],
                "maxInputTokens": 64_000,
                "maxOutputTokens": 16_000,
                "maxToolCalls": 64,
                "maxToolCost": 10_000,
                "retryRemaining": max(0, int(root_limits["retry_limit"]) - int(root_limits["retry_used"])),
                "repairRemaining": max(0, int(root_limits["repair_limit"]) - int(root_limits["repair_used"])),
            },
        }
        if skill_selection["selection"] == "required":
            skill_id = str(skill_selection["skillId"])
            result["roomSkillPolicy"] = {
                **skill_selection,
                "skillHash": self.room_skill_policy.skill_hash(skill_id),
                "policyId": self.room_skill_policy.policy_id,
                "policyVersion": self.room_skill_policy.version,
                "nextCandidates": self.room_skill_receipts.next_candidates(skill_id),
            }
        else:
            result["roomSkillPolicy"] = skill_selection
        return result

    def runtime_status(self) -> dict[str, object]:
        payload = self.runtime.runtime_status()
        payload.setdefault("driverId", self.runtime_factory.driver_id)
        payload.setdefault("runtimeKind", self.runtime_factory.runtime_kind)
        payload.setdefault("runtimeVersion", str(payload.get("piVersion") or ""))
        capabilities = (
            dict(payload.get("capabilities"))
            if isinstance(payload.get("capabilities"), Mapping)
            else {}
        )
        capabilities["delegation"] = True
        payload["capabilities"] = capabilities
        configuration = self.configuration_store.snapshot()
        payload["configurationRevision"] = configuration["revision"]
        payload["configurationSyncState"] = configuration["sync"]["state"]
        validate_contract(payload, "agent-runtime.v1.json")
        return payload

    def configuration(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-configuration-get.v1",
            "ok": True,
            "configuration": self.configuration_store.snapshot(),
        }

    def update_configuration(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._configuration_lock:
            return self._update_configuration_locked(payload)

    def _update_configuration_locked(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        expected_revision = payload.get("expectedRevision")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ValueError("agent configuration update requires expectedRevision")
        changes = payload.get("changes")
        if not isinstance(changes, Mapping):
            raise ValueError("agent configuration update requires a changes object")
        role_id = changes.get("sessionDefaults.roleId")
        role_version = changes.get("sessionDefaults.roleVersion")
        if role_id is not None or role_version is not None:
            current = self.configuration_store.snapshot()["configuration"]
            defaults = current["sessionDefaults"]
            self.personas.resolve(
                role_id or defaults["roleId"],
                role_version or defaults["roleVersion"],
            )
        runtime_keys = {
            "runtime.enabled",
            "runtime.startup",
            "runtime.idleTimeoutSeconds",
        }
        if runtime_keys.intersection(str(key) for key in changes):
            status = self.runtime.runtime_status()
            if status.get("status") in {"starting", "busy"}:
                raise ValueError("agent runtime settings cannot change during an active turn")

        update = self.configuration_store.update(
            changes,
            expected_revision=expected_revision,
            updated_by=str(payload.get("updatedBy") or "api-client"),
        )
        self.control_events.fan_out(update.event)
        snapshot = update.snapshot
        sync_event = None
        if update.runtime_sync_required:
            revision = int(snapshot["revision"])
            try:
                status = self._apply_runtime_policy(
                    runtime_policy_from_configuration(snapshot["configuration"])
                )
            except Exception as exc:
                fallback_status = self.runtime.runtime_status()
                snapshot, sync_event = self.configuration_store.mark_failed(
                    revision,
                    error=str(exc),
                    runtime_status=fallback_status,
                )
            else:
                snapshot, sync_event = self.configuration_store.mark_applied(
                    revision,
                    runtime_status=status,
                )
            self.control_events.fan_out(sync_event)
        return {
            "schemaVersion": "rag-ime.agent-configuration-update.v1",
            "ok": snapshot["sync"]["state"] != "failed",
            "changedKeys": list(update.changed_keys),
            "configuration": snapshot,
            "event": sync_event or update.event,
        }

    def ensure_runtime(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_application.ensure_runtime(payload)

    def list_sessions(self, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        return self.session_application.list_sessions(payload)

    def workflow_state(self, session_id: str) -> dict[str, object]:
        state = self.sessions.workflow_state(session_id)
        validate_contract(state, "agent-workflow-state.v1.json")
        return state

    def mutate_plan(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = dict(payload)
        validate_contract(request, "agent-plan-mutation.v1.json")
        self.sessions.mutate_agent_plan(session_id, request)
        return self.publish_workflow_state(session_id, reason=f"plan:{request['action']}")

    def mutate_goal(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = dict(payload)
        validate_contract(request, "agent-goal-mutation.v1.json")
        self.sessions.mutate_agent_goal(session_id, request)
        return self.publish_workflow_state(session_id, reason=f"goal:{request['action']}")

    def internal_workflow_state(self, payload: Mapping[str, object]) -> dict[str, object]:
        state = self.workflow_state(_required_text(payload, "sessionId"))
        return {
            "ok": True,
            "result": {
                "plan": state["plan"],
                "goal": state["goal"],
                "actGate": state["actGate"],
            },
        }

    def record_goal_usage(self, payload: Mapping[str, object]) -> dict[str, object]:
        request = dict(payload)
        validate_contract(request, "agent-goal-usage.v1.json")
        state = self.sessions.record_agent_goal_usage(
            str(request["sessionId"]),
            idempotency_key=str(request["idempotencyKey"]),
            turn_id=str(request.get("turnId") or ""),
            event_id=str(request.get("eventId") or ""),
            token_delta=int(request.get("tokenDelta") or 0),
            elapsed_delta_ms=int(request.get("elapsedDeltaMs") or 0),
        )
        validate_contract(state, "agent-workflow-state.v1.json")
        self.events.publish(
            str(request["sessionId"]),
            "workflow_changed",
            {"reason": "goal:usage", **state},
        )
        return {
            "ok": True,
            "result": {
                "plan": state["plan"],
                "goal": state["goal"],
                "actGate": state["actGate"],
            },
        }

    def publish_workflow_state(
        self,
        session_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        state = self.workflow_state(session_id)
        self.events.publish(
            session_id,
            "workflow_changed",
            {"reason": reason, **state},
        )
        return state

    def create_session(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_application.create_session(payload)

    def list_roles(self) -> dict[str, object]:
        return self.role_application.list_roles()

    def create_role(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.role_application.create_role(payload)

    def role_model_catalog(self) -> dict[str, object]:
        return self.role_application.model_catalog()

    def update_role_runtime_defaults(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.role_application.update_runtime_defaults(payload)

    def _role_payload(
        self,
        value: Mapping[str, object],
        *,
        available_models: set[tuple[str, str]] | None = None,
    ) -> dict[str, object]:
        return self.role_application.role_payload(
            value,
            available_models=available_models,
        )

    def _initial_role_runtime_defaults(
        self,
        role: PersonaManifest,
        *,
        default_model_profile: str | None = None,
        available_models: set[tuple[str, str]] | None = None,
    ) -> dict[str, str]:
        return self.role_application.initial_runtime_defaults(
            role,
            default_model_profile=default_model_profile,
            available_models=available_models,
        )

    def _available_role_models(self) -> set[tuple[str, str]] | None:
        return self.role_application.available_models()

    def preview_wake_schedule(
        self,
        payload: Mapping[str, object],
        *,
        requested_by_session_id: str = "",
    ) -> dict[str, object]:
        return self.wake_application.preview(
            payload,
            requested_by_session_id=requested_by_session_id,
        )

    def list_wake_schedules(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.wake_application.list(payload)

    def get_wake_schedule(self, schedule_id: str) -> dict[str, object]:
        return self.wake_application.get(schedule_id)

    def create_wake_schedule(
        self,
        payload: Mapping[str, object],
        *,
        created_by_session_id: str = "",
        require_confirmation: bool = True,
    ) -> dict[str, object]:
        return self.wake_application.create(
            payload,
            created_by_session_id=created_by_session_id,
            require_confirmation=require_confirmation,
        )

    def wake_schedule_runs(
        self,
        schedule_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.wake_application.runs(schedule_id, payload)

    def wake_schedule_action(
        self,
        schedule_id: str,
        payload: Mapping[str, object],
        *,
        require_confirmation: bool = True,
    ) -> dict[str, object]:
        return self.wake_application.action(
            schedule_id,
            payload,
            require_confirmation=require_confirmation,
        )

    def _validated_wake_schedule(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.wake_application.validate(payload)

    def _dispatch_scheduled_wake(self, claim: Mapping[str, object]) -> None:
        self.wake_application.dispatch(claim)

    def list_agent_templates(self) -> dict[str, object]:
        return self.delegation.catalog()

    def delegate_tasks(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.delegation.delegate(session_id, payload)

    def delegation_status(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.delegation.status(session_id, payload)

    def delegation_console(
        self,
        session_id: str,
        run_id: str,
    ) -> dict[str, object]:
        return self.delegation.console(session_id, run_id)

    def control_delegation(
        self,
        session_id: str,
        run_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.delegation.control(session_id, run_id, payload)

    def abort_delegation(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.delegation.abort(session_id, payload)

    def delegation_artifact(
        self,
        session_id: str,
        artifact_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        return self.delegation.inspect_artifact(
            session_id,
            artifact_id,
            limit=_integer(value.get("limit"), default=100, minimum=1, maximum=500),
        )

    def list_rooms(self, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        return self.room_management.list_rooms(payload)

    def _room_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return self.room_management.participant_sessions(room)

    def _repair_room_participant_session(
        self,
        room: Mapping[str, object],
        participant: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management._repair_participant_session(
            room,
            participant,
        )

    def _restore_legacy_room_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> None:
        self.room_management.restore_participant_sessions(room)

    def room(self, room_id: str) -> dict[str, object]:
        return self.room_management.get_room(room_id)

    def room_snapshot(self, room_id: str) -> dict[str, object]:
        return self.room_management.snapshot(room_id)

    def room_kernel_snapshot(self, room_id: str) -> dict[str, object]:
        return self.room_kernel_application.snapshot(room_id)

    def collaboration_profile_projection(self, profile_id: str) -> dict[str, object]:
        with sqlite3.connect(self.db_path) as conn:
            return self._collaboration_profile_control(conn).projection(profile_id)

    def apply_collaboration_profile_command(
        self,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError("CollaborationProfile control requires an authorized control caller")
        with sqlite3.connect(self.db_path) as conn:
            result = self._collaboration_profile_control(conn).execute(payload)
        self._run_room_learning_maintenance()
        return result

    def observe_room_user_correction(
        self,
        *,
        room_id: str,
        root_id: str,
        dispatch_id: str,
        correction_ref: str,
        caller_authorized: bool = False,
        now_ms: int | None = None,
    ) -> dict[str, object] | None:
        if not caller_authorized:
            raise PermissionError("Room correction observation requires an authorized caller")
        if self.room_kernel.root(root_id).get("roomId") != room_id:
            raise RoomKernelFenceError("correction Root belongs to another Room")
        return self._persist_room_learning_event(
            root_id=root_id,
            dispatch_id=dispatch_id,
            taxonomy="user_correction",
            failure_signature=f"user_correction:{correction_ref}",
            reason="user_correction",
            now_ms=int(now_ms if now_ms is not None else time.time() * 1000),
        )

    def rollback_room_guard(
        self,
        *,
        scope_key: str,
        rollback_receipt_id: str,
        authority_ref: str,
        authority_secret: bytes | str,
        reason: str,
        caller_authorized: bool = False,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError("Room Guard rollback requires an authorized caller")
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        result = self.room_learning.rollback(
            rollback_receipt_id=rollback_receipt_id,
            scope_key=scope_key,
            authority_ref=authority_ref,
            authority_secret=authority_secret,
            reason=reason,
            now_ms=timestamp,
        )
        for dispatch_id in result["cancelledDispatchIds"]:
            dispatch = self.room_kernel.dispatch(str(dispatch_id))
            self._persist_room_learning_event(
                root_id=str(dispatch["rootId"]),
                dispatch_id=str(dispatch_id),
                taxonomy="rollback",
                failure_signature=f"rollback:{reason}",
                reason="rollback",
                now_ms=timestamp,
            )
        self._run_room_learning_maintenance()
        return result

    def room_knowledge_search(
        self,
        payload: Mapping[str, object],
        *,
        authenticated_session_id: str,
    ) -> dict[str, object]:
        self._consume_room_knowledge_cache_tombstones()
        forbidden = {"owner", "ownerId", "ownerKind", "scope", "scopeId", "scopeKind", "allowedScopes", "allowedDomains", "sessionId"}
        if forbidden.intersection(payload):
            raise PermissionError("knowledge owner/scope/session are server-derived")
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("knowledge search query is required")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            caller = bound_session_knowledge_caller(conn, authenticated_session_id)
        receipt_id = str(payload.get("retrievalReceiptId") or f"knowledge-retrieval:{uuid.uuid4().hex}")
        result = self.knowledge_promotion.search(
            retrieval_receipt_id=receipt_id,
            query=query,
            caller=caller,
            limit=int(payload.get("limit") or 10),
            created_at_ms=int(payload.get("createdAtMs") or int(time.time() * 1000)),
        )
        return {
            "schemaVersion": "wisdom-weasel.room-knowledge-search-result.v1",
            "routeHash": KNOWLEDGE_ROUTE_HASH,
            "requiredScopes": ["agent.read"],
            **result,
        }

    def room_knowledge_read(
        self,
        payload: Mapping[str, object],
        *,
        authenticated_session_id: str,
    ) -> dict[str, object]:
        self._consume_room_knowledge_cache_tombstones()
        forbidden = {"owner", "ownerId", "ownerKind", "scope", "scopeId", "scopeKind", "allowedScopes", "allowedDomains", "sessionId", "query"}
        if forbidden.intersection(payload):
            raise PermissionError("knowledge read uses only its prior retrieval receipt")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            caller = bound_session_knowledge_caller(conn, authenticated_session_id)
        if caller is None:
            raise PermissionError("knowledge read requires an active Room ParticipantBinding")
        result = self.knowledge_promotion.read(
            claim_ref=_required_text(payload, "claimRef"),
            retrieval_receipt_id=_required_text(payload, "retrievalReceiptId"),
            expected_hash=_required_text(payload, "expectedHash"),
            caller=caller,
        )
        return {
            "schemaVersion": "wisdom-weasel.room-knowledge-read-result.v1",
            "routeHash": KNOWLEDGE_ROUTE_HASH,
            "requiredScopes": ["agent.read"],
            **result,
        }

    def _collaboration_profile_control(
        self,
        conn: sqlite3.Connection,
    ) -> CollaborationProfileControl:
        return CollaborationProfileControl(
            conn,
            trusted_signers=self._collaboration_profile_signers,
            baseline_capabilities=(
                "rag", "memory", "planning", "review", "control", "delegation"
            ),
            binding_revision="room-v2-agent-definition-compiler-v1",
            cancel_root=lambda root_id, _now_ms: self.room_kernel_commands.cancel_root(root_id),
        )

    def bind_room_capability_runtime(
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
        return self.room_kernel_runtime.bind_capability_runtime(
            manifest_id=manifest_id,
            room_binding=room_binding,
            participant_binding=participant_binding,
            prompt_compile_receipt=prompt_compile_receipt,
            dispatch_id=dispatch_id,
            user_authorized=user_authorized,
            template_allowed=template_allowed,
            role_allowed=role_allowed,
            profile_allowed=profile_allowed,
            state_allowed=state_allowed,
            created_at_ms=created_at_ms,
            runtime_state=runtime_state,
        )

    def _prepare_managed_room_dispatch(
        self,
        dispatch: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        return self.room_kernel_runtime.prepare_dispatch(dispatch, now_ms)

    def _accept_managed_room_runtime_context(
        self,
        runtime_receipt: Mapping[str, object],
    ) -> None:
        self.room_kernel_runtime.accept_runtime_context(runtime_receipt)

    def _resolve_room_collaboration_profile(
        self,
        root: Mapping[str, object],
        *,
        pinned_at_ms: int,
    ) -> tuple[CollaborationProfileManifest, dict[str, object]]:
        return self.room_kernel_runtime.resolve_collaboration_profile(
            root,
            pinned_at_ms=pinned_at_ms,
        )

    def room_capability_tool_search(self, payload: Mapping[str, object]) -> dict[str, object]:
        receipt, _ = self.room_capabilities.runtime_tool_search(
            session_id=_required_text(payload, "sessionId"),
            receipt_id=_required_text(payload, "receiptId"),
            query=str(payload.get("query") or ""),
            created_at_ms=int(payload.get("createdAtMs") or int(time.time() * 1000)),
        )
        return {"ok": True, "result": receipt}

    def room_capability_tool_load(self, payload: Mapping[str, object]) -> dict[str, object]:
        receipt, _ = self.room_capabilities.runtime_tool_load(
            session_id=_required_text(payload, "sessionId"),
            receipt_id=_required_text(payload, "receiptId"),
            tool_name=_required_text(payload, "toolName"),
            created_at_ms=int(payload.get("createdAtMs") or int(time.time() * 1000)),
        )
        return {"ok": True, "result": receipt}

    def execute_room_capability_tool(
        self,
        session_id: str,
        tool_name: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        load_receipt_id: str,
    ) -> dict[str, object] | None:
        return self.room_kernel_application.execute_capability_tool(
            session_id,
            tool_name,
            args,
            tool_call_id=tool_call_id,
            load_receipt_id=load_receipt_id,
        )

    def apply_room_kernel_command(
        self,
        room_id: str,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError("Room Kernel control requires an authorized control caller")
        self.rooms.get(room_id)
        if str(payload.get("roomId") or "") != room_id:
            raise RoomKernelFenceError("control command path Room does not match payload")
        result = self.room_kernel_commands.control(payload)
        self.room_kernel_projection.sync_room(room_id)
        return dict(result["kernelReceipt"])

    def create_room_kernel_root(
        self,
        room_id: str,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError(
                "Room Kernel create requires an authorized caller"
            )
        return self.room_kernel_application.create_root(room_id, payload)

    def dispatch_room_kernel(
        self,
        room_id: str,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError(
                "Room Kernel dispatch requires an authorized caller"
            )
        return self.room_kernel_application.dispatch(room_id, payload)

    def finalize_room_kernel_route(self, room_id: str, payload: Mapping[str, object], *, caller_authorized: bool = False) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError("Room Kernel finalize requires an authorized caller")
        root_id = str(payload.get("rootId") or "")
        if self.room_kernel.root(root_id).get("roomId") != room_id:
            raise RoomKernelFenceError("Finalize Root belongs to another Room")
        return self.finalize_room_kernel_root(root_id, catalog_revision_id=str(payload.get("catalogRevisionId") or ""), target_commit=str(payload.get("targetCommit") or ""), blind_review_status=str(payload.get("blindReviewStatus") or "unavailable"), delivery_gate_preview_receipt_id=str(payload.get("deliveryGatePreviewReceiptId") or ""))

    def settle_room_kernel_dispatch(
        self,
        room_id: str,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError(
                "Room Kernel settle requires an authorized runtime caller"
            )
        return self.room_kernel_application.settle(room_id, payload)

    def governance_read_model(self, *, scope_key: str | None = None) -> dict[str, object]:
        return {
            "schemaVersion": "wisdom-weasel.governance-read-model.v1",
            "governance": self.governance_projection.snapshot(scope_key=scope_key),
        }

    def knowledge_governance_read_model(self) -> dict[str, object]:
        return {
            "schemaVersion": "wisdom-weasel.knowledge-governance-read-model.v1",
            "knowledge": self.knowledge_promotion.governance_snapshot(),
        }

    def finalize_room_kernel_root(
        self,
        root_id: str,
        *,
        catalog_revision_id: str = "",
        target_commit: str = "",
        blind_review_status: str = "unavailable",
        delivery_gate_preview_receipt_id: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        return self.room_kernel_application.finalize(
            root_id,
            catalog_revision_id=catalog_revision_id,
            target_commit=target_commit,
            blind_review_status=blind_review_status,
            delivery_gate_preview_receipt_id=(
                delivery_gate_preview_receipt_id
            ),
            now_ms=now_ms,
        )

    def room_work_items(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_work_application.room_work_items(
            room_id,
            payload,
        )

    def room_work_item(
        self,
        room_id: str,
        work_item_id: str,
    ) -> dict[str, object]:
        return self.room_work_application.room_work_item(
            room_id,
            work_item_id,
        )

    def create_room_work_item(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.create_room_work_item(
            room_id,
            payload,
        )

    def reassign_room_work_item(
        self,
        room_id: str,
        work_item_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.reassign_room_work_item(
            room_id,
            work_item_id,
            payload,
        )

    def room_topics(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_management.topics(room_id, payload)

    def create_room_topic(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.create_topic(room_id, payload)

    def update_room_topic(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.update_topic(room_id, payload)

    def room_artifacts(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_management.artifacts(room_id, payload)

    def add_room_artifact(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.add_artifact(room_id, payload)

    def update_room_artifact(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.update_artifact(room_id, payload)

    def update_room(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.update_room(room_id, payload)

    def add_room_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management.add_participant(room_id, payload)

    def remove_room_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management.remove_participant(room_id, payload)

    def delete_room(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management.delete_room(room_id, payload)

    def create_room(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.create_room(payload)

    def post_room_message(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("room message must not be empty")
        if len(message) > ROOM_MESSAGE_CHAR_LIMIT:
            raise ValueError(
                f"Room message must not exceed {ROOM_MESSAGE_CHAR_LIMIT} characters"
            )
        client_message_id = _optional_client_message_id(payload.get("clientMessageId"))
        work_item_id = _optional_work_item_id(payload.get("workItemId"))
        requested_ids = payload.get("participantIds")
        if requested_ids is None:
            requested_participant_ids: list[str] = []
        elif isinstance(requested_ids, list):
            requested_participant_ids = [
                str(value or "").strip()
                for value in requested_ids
                if str(value or "").strip()
            ]
        else:
            raise ValueError("participantIds must be an array")
        if not client_message_id:
            return self._post_room_message_once(
                room_id,
                message=message,
                client_message_id="",
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
            )
        claim = self.command_receipts.begin(
            command_scope="room_message",
            scope_id=room_id,
            client_message_id=client_message_id,
            payload={
                "message": message,
                "participantIds": requested_participant_ids,
                "workItemId": work_item_id,
            },
        )
        if claim.replay_response is not None:
            return {**claim.replay_response, "idempotentReplay": True}
        try:
            response = self._post_room_message_once(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
            )
        except Exception as exc:
            self.command_receipts.fail(
                claim,
                command_scope="room_message",
                scope_id=room_id,
                client_message_id=client_message_id,
                error=exc,
            )
            raise
        return self.command_receipts.complete(
            claim,
            command_scope="room_message",
            scope_id=room_id,
            client_message_id=client_message_id,
            response=response,
        )

    def abort_room_turn(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room_turn_id = _required_text(payload, "roomTurnId")
        if len(room_turn_id) > 320:
            raise ValueError("roomTurnId must not exceed 320 characters")
        client_request_id = _optional_client_message_id(payload.get("clientRequestId"))
        if not client_request_id:
            raise ValueError("clientRequestId must not be empty")
        claim = self.command_receipts.begin(
            command_scope="room_turn_abort",
            scope_id=room_id,
            client_message_id=client_request_id,
            payload={"roomTurnId": room_turn_id},
        )
        if claim.replay_response is not None:
            return {**claim.replay_response, "idempotentReplay": True}
        try:
            response = self._abort_room_turn_once(
                room_id,
                room_turn_id=room_turn_id,
            )
        except Exception as exc:
            self.command_receipts.fail(
                claim,
                command_scope="room_turn_abort",
                scope_id=room_id,
                client_message_id=client_request_id,
                error=exc,
            )
            raise
        return self.command_receipts.complete(
            claim,
            command_scope="room_turn_abort",
            scope_id=room_id,
            client_message_id=client_request_id,
            response=response,
        )

    def _abort_room_turn_once(
        self,
        room_id: str,
        *,
        room_turn_id: str,
    ) -> dict[str, object]:
        if self.room_kernel.mode in {"cohort", "kernel_only"}:
            return self.room_kernel_application.cancel_root(
                room_id,
                room_turn_id,
            )
        return self.room_legacy_cancellation.abort_turn(
            room_id,
            room_turn_id=room_turn_id,
        )

    def _post_room_message_once(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
    ) -> dict[str, object]:
        if self.room_kernel.mode in {"cohort", "kernel_only"}:
            return self.room_application.post_message(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
            )
        return self.room_legacy_dispatch.post_message(
            room_id,
            message=message,
            client_message_id=client_message_id,
            requested_participant_ids=requested_participant_ids,
            work_item_id=work_item_id,
        )

    def _dispatch_room_target(
        self,
        *,
        room: Mapping[str, object],
        target: Mapping[str, object],
        decision: Mapping[str, object],
        message: str,
        room_turn_id: str,
        topic_id: str,
        unread: Mapping[str, object],
        work_item: Mapping[str, object] | None,
    ) -> dict[str, object]:
        return self.room_legacy_dispatch.dispatch_target(
            room=room,
            target=target,
            decision=decision,
            message=message,
            room_turn_id=room_turn_id,
            topic_id=topic_id,
            unread=unread,
            work_item=work_item,
        )

    def send_room_intercom(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.send_room_intercom(
            source_session_id,
            payload,
        )

    def list_room_intercom(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_work_application.list_room_intercom(
            session_id,
            payload,
        )

    def assign_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.assign_room_work(
            session_id,
            payload,
        )

    def submit_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.submit_room_work(
            session_id,
            payload,
        )

    def accept_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.accept_room_work(
            session_id,
            payload,
        )

    def return_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.return_room_work(
            session_id,
            payload,
        )

    def block_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.block_room_work(
            session_id,
            payload,
        )

    def escalate_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application.escalate_room_work(
            session_id,
            payload,
        )

    def list_room_work(
        self,
        session_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_work_application.list_room_work(
            session_id,
            payload,
        )

    def subscribe_room_events(
        self,
        room_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        self.rooms.get(room_id)
        return self.room_events.subscribe(
            room_id,
            after_event_id=after_event_id,
            heartbeat_seconds=heartbeat_seconds,
        )

    def subscribe_room_kernel_events(
        self,
        room_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        self.rooms.get(room_id)
        self.room_kernel_projection.sync_room(room_id)
        return self.room_kernel_projection.subscribe(
            room_id,
            after_event_id=after_event_id,
            heartbeat_seconds=heartbeat_seconds,
        )

    def model_catalog(self, session_id: str) -> dict[str, object]:
        return self.session_policy.model_catalog(session_id)

    def command_catalog(self, session_id: str) -> dict[str, object]:
        return self.session_policy.command_catalog(session_id)

    def select_model(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_policy.select_model(session_id, payload)

    def select_thinking_level(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_policy.select_thinking_level(
            session_id,
            payload,
        )

    def update_session(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_policy.update_session(session_id, payload)

    def delete_session(self, session_id: str) -> dict[str, object]:
        return self.session_application.delete_session(session_id)

    def fork_candidates(self, session_id: str) -> dict[str, object]:
        return self.session_branching.fork_candidates(session_id)

    def fork_session(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_branching.fork_session(
            session_id,
            payload,
        )

    def rewrite_session(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.session_branching.rewrite_session(
            session_id,
            payload,
        )

    def _rewrite_session_once(
        self,
        *,
        session_id: str,
        entry_id: str,
        message: str,
        attachment_ids: list[str],
        client_message_id: str,
    ) -> dict[str, object]:
        return self.session_branching.rewrite_session_once(
            session_id=session_id,
            entry_id=entry_id,
            message=message,
            attachment_ids=attachment_ids,
            client_message_id=client_message_id,
        )

    def _rewritable_session(self, session_id: str) -> dict[str, object]:
        return self.session_branching.rewritable_session(session_id)

    def _forkable_session(self, session_id: str) -> dict[str, object]:
        return self.session_branching.forkable_session(session_id)

    def messages(self, session_id: str) -> dict[str, object]:
        return self.message_snapshot.messages(session_id)

    def import_media(
        self,
        *,
        session_id: str,
        data: bytes,
        mime_type: str,
        file_name: str = "",
    ) -> dict[str, object]:
        self.sessions.get(session_id)
        return {
            "schemaVersion": "rag-ime.agent-media-import.v1",
            "ok": True,
            "media": self.media.import_bytes(
                session_id=session_id,
                data=data,
                mime_type=mime_type,
                file_name=file_name,
            ),
        }

    def list_media(self, payload: Mapping[str, object]) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        self.sessions.get(session_id)
        return {
            "schemaVersion": "rag-ime.agent-media-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": self.media.list_for_session(
                session_id,
                limit=_integer(payload.get("limit"), default=100, minimum=1, maximum=500),
            ),
        }

    def media_receipt(self, media_id: str, *, session_id: str) -> dict[str, object]:
        self.sessions.get(session_id)
        return {
            "schemaVersion": "rag-ime.agent-media-get.v1",
            "ok": True,
            "media": self.media.receipt(media_id, session_id=session_id),
        }

    def media_content(self, media_id: str, *, session_id: str) -> tuple[dict[str, object], bytes]:
        self.sessions.get(session_id)
        return self.media.read(media_id, session_id=session_id)

    def prompt(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.prompt_application.prompt(
            session_id,
            payload,
        )

    def deep_search(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.prompt_application.deep_search(payload)

    def _deep_search_session(
        self,
        runtime: Mapping[str, object],
    ) -> tuple[dict[str, object], bool]:
        return self.prompt_application.deep_search_session(
            runtime
        )

    def _prompt_with_checkpoint(
        self,
        *,
        session_id: str,
        message: str,
        checkpoint_text: str,
        attachment_ids: list[str],
        client_message_id: str = "",
        context_source: str = "user",
        delivery: str = "prompt",
        transient_context: str = "",
    ) -> dict[str, object]:
        return self.prompt_application.prompt_with_checkpoint(
            session_id=session_id,
            message=message,
            checkpoint_text=checkpoint_text,
            attachment_ids=attachment_ids,
            client_message_id=client_message_id,
            context_source=context_source,
            delivery=delivery,
            transient_context=transient_context,
        )

    def _runtime_prompt_with_context(
        self,
        session_id: str,
        message: str,
        *,
        images: list[Mapping[str, str]] | None = None,
        client_message_id: str = "",
        source_kind: str,
        delivery: str = "prompt",
        transient_context: str = "",
    ) -> tuple[dict[str, object], str, int]:
        return self.prompt_delivery_application.deliver(
            session_id,
            message,
            images=images,
            client_message_id=client_message_id,
            source_kind=source_kind,
            delivery=delivery,
            transient_context=transient_context,
        )

    def _ensure_session_role_book(self, session_id: str) -> dict[str, object]:
        return self.memory_context_application.ensure_role_book(
            session_id
        )

    def _pending_memory_bootstrap(
        self,
        session: Mapping[str, object],
    ) -> dict[str, object]:
        return self.memory_context_application.pending_bootstrap(
            session
        )

    def _ensure_memory_bootstrap(
        self,
        session: Mapping[str, object],
        *,
        query_text: str,
    ) -> dict[str, object]:
        return self.memory_context_application.ensure_bootstrap(
            session,
            query_text=query_text,
        )

    def refresh_session_context(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.memory_context_application.refresh(payload)

    def _memory_trigger_for_session(self, session_id: str) -> str:
        return self.task_context.trigger(session_id)

    def _memory_room_ids(self, session_id: str) -> tuple[str, ...]:
        return self.task_context.room_ids(session_id)

    def _memory_task_context(self, session_id: str) -> dict[str, object]:
        return self.task_context.resolve(session_id)

    def _remember_recall_query(self, session_id: str, query_text: str) -> None:
        self.memory_context_application.remember_query(
            session_id,
            query_text,
        )

    def _memory_recall_query(self, session_id: str, *, fallback: str = "") -> str:
        return self.memory_context_application.recall_query(
            session_id,
            fallback=fallback,
        )

    def _replace_recent_recall_messages(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, object]],
    ) -> None:
        self.memory_context_application.replace_recent_messages(
            session_id,
            messages,
        )

    def _append_recent_recall_message(
        self,
        session_id: str,
        message: Mapping[str, object],
    ) -> None:
        self.memory_context_application.append_recent_message(
            session_id,
            message,
        )

    def _recent_recall_messages(self, session_id: str) -> list[dict[str, object]]:
        return self.memory_context_application.recent_messages(
            session_id
        )

    def _record_user_evidence_safely(
        self,
        *,
        session_id: str,
        pi_entry_id: str,
        turn_id: str,
        text: str,
    ) -> dict[str, object]:
        return self.memory_evidence_application.record_user(
            session_id=session_id,
            pi_entry_id=pi_entry_id,
            turn_id=turn_id,
            text=text,
        )

    def _record_assistant_evidence_safely(
        self,
        event: AgentEventEnvelope,
    ) -> dict[str, object]:
        return self.memory_evidence_application.record_assistant(
            event
        )

    def _record_tool_receipt_evidence_safely(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        return self.memory_evidence_application.record_tool_receipt(
            approval
        )

    def _record_room_evidence_safely(
        self,
        *,
        room_id: str,
        room_event: Mapping[str, object],
        text: str,
        role_id: str,
        session_id: str,
        event_type: str,
        accepted: bool,
    ) -> dict[str, object]:
        return self.memory_evidence_application.record_room(
            room_id=room_id,
            room_event=room_event,
            text=text,
            role_id=role_id,
            session_id=session_id,
            event_type=event_type,
            accepted=accepted,
        )

    def abort(self, session_id: str) -> dict[str, object]:
        runtime_receipt = self.runtime.abort(session_id)
        return {
            "schemaVersion": "rag-ime.agent-abort.v1",
            "ok": True,
            "sessionId": session_id,
            "runtimeReceipt": (
                dict(runtime_receipt)
                if isinstance(runtime_receipt, Mapping)
                else {}
            ),
        }

    def compact(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        self._recent_recall_messages(session_id)
        result = dict(
            self.runtime.compact(session_id, str(payload.get("instructions") or ""))
        )
        if not isinstance(result.get("memoryCheckpoint"), Mapping):
            result["memoryCheckpoint"] = dict(
                self._checkpoint_runtime_compaction(session_id, result, "manual")
            )
        maintenance = self._probe_memory_maintenance(session_id, trigger="compaction")
        if result.get("contextRefreshApplied") is True:
            context_refresh = {
                "schemaVersion": "rag-ime.agent-session-context-refresh.v1",
                "ok": True,
                "result": {
                    "sessionId": session_id,
                    "trigger": "compaction",
                    "status": "runtime_applied",
                }
            }
        else:
            try:
                context_refresh = self.refresh_session_context(
                    {
                        "sessionId": session_id,
                        "trigger": "compaction",
                        "summary": _compaction_summary(result),
                        "recentMessages": self._recent_recall_messages(session_id),
                    }
                )
            except Exception as exc:
                context_refresh = {
                    "schemaVersion": "rag-ime.agent-session-context-refresh.v1",
                    "ok": False,
                    "error": _public_error(exc),
                }
        return {
            "schemaVersion": "rag-ime.agent-compact.v1",
            "ok": True,
            "sessionId": session_id,
            "result": result,
            "memoryMaintenance": maintenance,
            "contextRefresh": context_refresh,
        }

    def _checkpoint_runtime_compaction(
        self,
        session_id: str,
        result: Mapping[str, object],
        trigger: str,
    ) -> Mapping[str, object]:
        summary = _compaction_summary(result)
        material = json.dumps(
            {
                "sessionId": session_id,
                "summary": summary,
                "firstKeptEntryId": str(result.get("firstKeptEntryId") or ""),
                "trigger": compact_whitespace(trigger) or "automatic",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        # Pi's Session JSONL is the authoritative compaction checkpoint. A
        # lossy summary may guide the immediate post-compaction recall, but it
        # is not evidence and must never silently enter long-term memory.
        return {
            "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
            "ok": True,
            "stored": False,
            "status": "session_context_only",
            "summarySha256": hashlib.sha256(summary.encode("utf-8")).hexdigest()
            if summary
            else "",
            "checkpointKey": hashlib.sha256(material.encode("utf-8")).hexdigest()[:32],
            "longTermMemoryEligible": False,
        }

    def _probe_memory_maintenance(self, session_id: str, *, trigger: str) -> dict[str, object]:
        if self._memory_maintenance_probe is None:
            return {
                "schemaVersion": "rag-ime.agent-memory-maintenance-probe.v1",
                "ok": False,
                "available": False,
                "trigger": trigger,
            }
        try:
            status = dict(
                self._memory_maintenance_probe(
                    {"project": self.project, "limit": 5, "trigger": trigger}
                )
            )
        except Exception as exc:
            return {
                "schemaVersion": "rag-ime.agent-memory-maintenance-probe.v1",
                "ok": False,
                "available": True,
                "trigger": trigger,
                "error": _public_error(exc),
            }
        compile_state = status.get("compileState") if isinstance(status.get("compileState"), Mapping) else {}
        pending = _integer(
            compile_state.get("pendingEventCount"),
            default=0,
            minimum=0,
            maximum=2_147_483_647,
        )
        drafts = _integer(
            status.get("pendingDraftCount"),
            default=0,
            minimum=0,
            maximum=2_147_483_647,
        )
        due = status.get("due") is True
        summary = (
            f"记忆整理已达到触发条件，当前有 {pending} 条新记录"
            if due
            else f"已检查记忆整理状态：{pending} 条新记录、{drafts} 份待审草案"
        )
        self.events.publish(
            session_id,
            "memory_maintenance_updated",
            {
                "trigger": trigger,
                "due": due,
                "dueReason": str(status.get("dueReason") or ""),
                "pendingEventCount": pending,
                "pendingDraftCount": drafts,
                "summary": summary,
            },
        )
        return {**status, "trigger": trigger}

    def list_approvals(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.list_approvals(payload)

    def resolve_review(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.resolve_review(session_id, payload)

    def decide_approval(self, approval_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.decide_approval(approval_id, payload)

    def _finish_approval_decision(
        self,
        approval: Mapping[str, object],
        *,
        pending_in_pi: bool,
    ) -> dict[str, object]:
        return self.approval_application.finish_decision(
            approval,
            pending_in_pi=pending_in_pi,
        )

    def auto_approve_pending(self, approval: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.auto_approve_pending(approval)

    def _execute_approved_operation(
        self,
        decided: Mapping[str, object],
    ) -> dict[str, object]:
        return self.approval_application.execute_approved(decided)

    def _checkpoint_applied_approval(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        return self.approval_application.checkpoint_applied(approval)

    def _finish_terminal_approval(
        self,
        approval: Mapping[str, object],
        *,
        pending_in_pi: bool,
    ) -> dict[str, object]:
        return self.approval_application.finish_terminal(
            approval,
            pending_in_pi=pending_in_pi,
        )

    def finalize_external_approval(
        self,
        approval_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.approval_application.finalize_external(
            approval_id,
            payload,
        )

    def approval_result(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.approval_result(payload)

    def list_memory_sources(self, payload: Mapping[str, object]) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        self.sessions.get(session_id)
        return {
            "schemaVersion": "rag-ime.agent-memory-source-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": self.memory_sources.list_for_session(
                session_id,
                limit=_integer(payload.get("limit"), default=100, minimum=1, maximum=500),
            ),
        }

    def subscribe_events(
        self,
        session_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        self.sessions.get(session_id)
        return self.events.subscribe(
            session_id,
            after_event_id=after_event_id,
            heartbeat_seconds=heartbeat_seconds,
        )

    def subscribe_control_events(
        self,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        return self.control_events.subscribe(
            after_event_id=after_event_id,
            heartbeat_seconds=heartbeat_seconds,
        )

    def observation_snapshot(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.observations.snapshot(payload)

    def subscribe_observations(
        self,
        *,
        after_event_id: str = "",
        filters: Mapping[str, object] | None = None,
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        return self.observations.subscribe(
            after_event_id=after_event_id,
            filters=filters,
            heartbeat_seconds=heartbeat_seconds,
        )

    def _bind_room_kernel_runtime(self, *, start_worker: bool = True) -> None:
        prior = getattr(self, "room_kernel_worker_loop", None)
        if prior is not None:
            prior.close()
        if self.room_kernel.mode in {"cohort", "kernel_only"} and (
            not callable(getattr(self.runtime, "dispatch_room", None))
            or not callable(getattr(self.runtime, "cancel_room", None))
        ):
            raise RuntimeError("managed Room Kernel requires typed Pi Room RPC")
        self.room_kernel_runtime = RoomKernelRuntimeCoordinator(
            db_path=self.db_path,
            rooms=self.rooms,
            personas=self.personas,
            kernel=self.room_kernel,
            capabilities=self.room_capabilities,
            prompt_plans=self.room_prompt_plans,
            projection_journals=self.room_projection_journals,
            context_ledger=self.room_context_ledger,
            skill_policy=self.room_skill_policy,
            skill_receipts=self.room_skill_receipts,
            requirements=self.room_requirements,
            learning=self.room_learning,
            learning_runtime=self.room_learning_runtime,
            definition_compiler=self.agent_definition_compiler,
            role_book_prompt_resolver=lambda session_id: (
                self.role_books.prompt_block(
                    self.sessions.get(session_id)
                )
            ),
        )
        self.room_kernel_worker = RoomKernelWorker(
            self.room_kernel,
            self.runtime,  # type: ignore[arg-type]
            prepare_dispatch=self.room_kernel_runtime.prepare_dispatch,
            accept_runtime_context=self.room_kernel_runtime.accept_runtime_context,
            revoke_session=self.room_kernel_runtime.revoke_session,
            learning_observer=self.room_kernel_runtime.record_learning_signal,
        )
        self.room_kernel_commands = KernelCommandBus(self.room_kernel, self.room_kernel_worker)
        self.room_kernel_worker_loop = RoomKernelWorkerLoop(
            self.room_kernel_worker,
            on_change=self._sync_all_room_kernel_projections,
            poll_seconds=self._room_kernel_poll_seconds,
        )
        self.room_application = RoomApplicationService(
            rooms=self.rooms,
            sessions=self.sessions,
            personas=self.personas,
            role_books=self.role_books,
            work_items=self.room_work,
            kernel=self.room_kernel,
            commands=self.room_kernel_commands,
            projection=self.room_kernel_projection,
            context=self.room_context_ledger,
            requirements=self.room_requirements,
            capabilities=self.room_capabilities,
            wake_worker=self.room_kernel_worker_loop.wake,
            restore_participant_sessions=self._restore_legacy_room_participant_sessions,
        )
        self.room_kernel_application = RoomKernelApplicationService(
            rooms=self.rooms,
            kernel=self.room_kernel,
            commands=self.room_kernel_commands,
            projection=self.room_kernel_projection,
            capabilities=self.room_capabilities,
            context=self.room_context_ledger,
            requirements=self.room_requirements,
            peer_review=self.room_peer_review,
            learning=self.room_learning,
            wake_worker=self.room_kernel_worker_loop.wake,
            revoke_session=self.room_kernel_runtime.revoke_session,
            artifact_hash_provider=self._room_artifact_hash_provider,
        )
        if start_worker:
            self.room_kernel_worker_loop.start()

    def _sync_all_room_kernel_projections(self) -> None:
        for room_id in self.room_kernel.room_ids():
            self.room_kernel_projection.sync_room(room_id)
        self._run_room_learning_maintenance()
        self._consume_room_knowledge_cache_tombstones()

    def _consume_room_knowledge_cache_tombstones(self) -> int:
        """Clear process-local recall state after durable knowledge invalidation."""
        consumed_at_ms = int(time.time() * 1000)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT tombstone_id,session_id FROM room_v2_knowledge_cache_tombstones
                   WHERE consumed_at_ms=0 ORDER BY created_at_ms,tombstone_id"""
            ).fetchall()
            session_ids = {str(row["session_id"]) for row in rows if row["session_id"]}
            if rows:
                conn.executemany(
                    "UPDATE room_v2_knowledge_cache_tombstones SET consumed_at_ms=? WHERE tombstone_id=?",
                    [(consumed_at_ms, str(row["tombstone_id"])) for row in rows],
                )
            conn.commit()
        self.memory_context_application.clear_recall_state(
            tuple(session_ids)
        )
        return len(rows)

    def _record_room_learning_signal(
        self,
        signal: Mapping[str, object],
    ) -> None:
        self.room_kernel_runtime.record_learning_signal(signal)

    def _persist_room_learning_event(
        self,
        *,
        root_id: str,
        dispatch_id: str,
        taxonomy: str,
        failure_signature: str,
        reason: str,
        now_ms: int,
    ) -> dict[str, object] | None:
        return self.room_kernel_runtime.persist_learning_event(
            root_id=root_id,
            dispatch_id=dispatch_id,
            taxonomy=taxonomy,
            failure_signature=failure_signature,
            reason=reason,
            now_ms=now_ms,
        )

    def _apply_managed_cancel(self, item: Mapping[str, object]) -> Mapping[str, object]:
        root = self.room_kernel.root(str(item["root_id"]))
        command = {
            "schemaVersion": "wisdom-weasel.room-kernel-command.v1",
            "commandId": f"managed-cancel:{item['cancel_id']}",
            "rootId": root["rootId"],
            "roomId": root["roomId"],
            "commandKind": "cancel_root",
            "targetKind": "root",
            "targetId": root["rootId"],
            "sourceKind": str(item["source_kind"]),
            "sourceId": str(item["source_receipt_id"]),
            "idempotencyKey": str(item["cancel_id"]),
            "generation": int(root["generation"]),
            "payload": {"dispatchId": item.get("dispatch_id")},
            "createdAtMs": int(item["created_at_ms"]),
        }
        return self.room_kernel_commands.control(command)

    def _run_room_learning_maintenance(self) -> None:
        now_ms = int(time.time() * 1000)
        try:
            self.room_learning_runtime.ingest_kernel_receipts(now_ms=now_ms)
        except Exception:
            pass
        for _ in range(8):
            try:
                if self.room_learning_runtime.materialize_once(now_ms=now_ms) is None:
                    break
            except Exception:
                break
        for _ in range(8):
            result = self.room_learning_runtime.drain_cancel_once(
                self._apply_managed_cancel,
                now_ms=now_ms,
            )
            if result is None or result.get("state") != "applied":
                break
        try:
            self.room_learning_runtime.run_reflection_once(now_ms=now_ms)
        except Exception:
            pass

    def _revoke_room_runtime_capability(
        self,
        session_id: str,
        now_ms: int,
    ) -> None:
        self.room_kernel_runtime.revoke_session(session_id, now_ms)

    def close(self) -> None:
        self.room_kernel_worker_loop.close()
        self._remove_observation_room_observer()
        self.observations.close()
        self._remove_wake_observer()
        self.wake_scheduler.close()
        self.room_intercom.close()
        self.delegation.close()
        self.runtime.stop()

    def reconfigure_runtime(self, config: PiRuntimeConfig) -> dict[str, object]:
        self.room_kernel_worker_loop.close()
        self.runtime.stop()
        config = replace(
            config,
            tool_gateway_token=self.tool_token,
            role_resolver=self.personas.resolve,
            role_book_resolver=self.role_books.prompt_block,
        )
        self.runtime_factory.reconfigure(config)
        self.delegation.reconfigure(config)
        self.runtime = self.runtime_factory.create(
            RuntimeDriverContext(
                sessions=self.sessions,
                events=self.events,
                media_resolver=self.media.resolve_pi_image,
                tool_gateway_token=self.tool_token,
                tool_gateway_url=self.tool_gateway_url,
                tool_manifest_provider=self._runtime_tool_manifest,
                compaction_observer=self._checkpoint_runtime_compaction,
            ),
            purpose="interactive",
            session_context_provider=self._runtime_session_context,
        )
        self._bind_room_kernel_runtime()
        self.room_intercom.notify()
        return self.runtime_status()

    def _apply_runtime_policy(self, policy: AgentRuntimePolicy) -> dict[str, object]:
        self.room_kernel_worker_loop.close()
        self.runtime.stop()
        self.runtime_factory.apply_policy(policy)
        self.delegation.refresh_runtime_factory()
        self.runtime = self.runtime_factory.create(
            RuntimeDriverContext(
                sessions=self.sessions,
                events=self.events,
                media_resolver=self.media.resolve_pi_image,
                tool_gateway_token=self.tool_token,
                tool_gateway_url=self.tool_gateway_url,
                tool_manifest_provider=self._runtime_tool_manifest,
                compaction_observer=self._checkpoint_runtime_compaction,
            ),
            purpose="interactive",
            session_context_provider=self._runtime_session_context,
        )
        self._bind_room_kernel_runtime()
        self.room_intercom.notify()
        return self.runtime.runtime_status()

    def _record_event(self, event: AgentEventEnvelope) -> None:
        self.event_projection_application.record(event)

    def _mirror_event_to_room(self, event: AgentEventEnvelope) -> None:
        self.event_projection_application.mirror_to_room(
            event
        )

    def _begin_room_turn(
        self,
        session_id: str,
        room_turn_id: str,
        topic_id: str = "",
        *,
        dispatch_id: str = "",
    ) -> None:
        self.room_turns.begin(
            session_id,
            room_turn_id,
            topic_id,
            dispatch_id=dispatch_id,
        )

    def _accept_room_turn(
        self,
        session_id: str,
        session_turn_id: str,
        room_turn_id: str,
    ) -> None:
        self.room_turns.accept(
            session_id,
            session_turn_id,
            room_turn_id,
        )

    def _cancel_room_turn(self, session_id: str, room_turn_id: str) -> None:
        self.room_turns.cancel(session_id, room_turn_id)

    def _room_turn_for_event(self, event: AgentEventEnvelope) -> str:
        return self.room_turns.turn_for_event(event)

    def _room_dispatch_for_event(self, event: AgentEventEnvelope) -> str:
        return self.room_turns.dispatch_for_event(event)

    def _finish_room_turn(
        self,
        session_id: str,
        session_turn_id: str,
        room_turn_id: str,
    ) -> None:
        self.room_turns.finish(
            session_id,
            session_turn_id,
            room_turn_id,
        )

    def _drop_room_topic_if_idle_locked(self, room_turn_id: str) -> None:
        self.room_turns.drop_topic_if_idle(room_turn_id)

    def _room_topic_for_turn(self, room_turn_id: str) -> str:
        return self.room_turns.topic_for_turn(room_turn_id)

    def _room_runtime_generation(self, session_id: str) -> int:
        return self.room_intercom_application.runtime_generation(
            session_id
        )

    def _room_target_idle(
        self,
        session_id: str,
        *,
        allow_user_priority: bool = False,
    ) -> bool:
        return self.room_intercom_application.target_idle(
            session_id,
            allow_user_priority=allow_user_priority,
        )

    def _deliver_room_intercom(
        self,
        item: Mapping[str, object],
    ) -> Mapping[str, object]:
        return self.room_intercom_application.deliver(item)

    def _publish_room_intercom_audit(
        self,
        item: Mapping[str, object],
        phase: str,
    ) -> None:
        self.room_intercom_application.publish_audit(
            item,
            phase,
        )

    def _require_room_participant(
        self,
        session_id: str,
        *,
        active_only: bool = True,
    ) -> dict[str, object]:
        return self.room_work_application._require_room_participant(
            session_id,
            active_only=active_only,
        )

    def _notify_room_work(
        self,
        session_id: str,
        work: Mapping[str, object],
        *,
        target_participant_id: str,
        action: str,
        content: str,
    ) -> Mapping[str, object] | None:
        return self.room_work_application._notify_room_work(
            session_id,
            work,
            target_participant_id=target_participant_id,
            action=action,
            content=content,
        )

    def _enqueue_room_intercom(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_work_application._enqueue_room_intercom(
            source_session_id,
            payload,
        )

    def _guard_legacy_room_route(self, route_id: str, session_id: str) -> None:
        binding = self.room_kernel.session_binding(str(session_id or ""))
        owner = room_route_owner(route_id, has_room_binding=binding is not None)
        if binding is not None and owner == "kernel":
            raise RoomKernelFenceError(
                f"RoomBinding route {route_id} is owned by Kernel, not the legacy executor"
            )

    @staticmethod
    def _room_work_operation(
        operation: str,
        work: Mapping[str, object],
        *,
        delivery: Mapping[str, object] | None,
    ) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-room-work-operation.v1",
            "ok": True,
            "operation": operation,
            "work": dict(work),
            "delivery": dict(delivery) if isinstance(delivery, Mapping) else None,
        }

    def _publish_room_work_activity(
        self,
        work: Mapping[str, object],
        *,
        phase: str,
        actor: Mapping[str, object],
    ) -> None:
        return self.room_work_application._publish_room_work_activity(
            work,
            phase=phase,
            actor=actor,
        )


def agent_service_from_environment(
    db_path: str | Path,
    *,
    project: str = "",
    memory_embedding_provider: EmbeddingProvider | None = None,
    wake_scheduler_enabled: bool = True,
) -> AgentService:
    room_kernel_mode = _room_kernel_mode_from_environment()
    return AgentService(
        db_path=db_path,
        runtime_config=PiRuntimeConfig.from_environment(),
        project=project,
        tool_gateway_url=os.environ.get(
            "RAG_IME_AGENT_TOOL_URL",
            "http://127.0.0.1:8766/api/agent/tool/execute",
        ),
        memory_embedding_provider=memory_embedding_provider,
        wake_scheduler_enabled=wake_scheduler_enabled,
        room_kernel_mode=room_kernel_mode,
        room_runner_secrets=_room_runner_secrets_from_provider(),
        room_delivery_gate_enforcement=_room_delivery_gate_enforcement(room_kernel_mode),
        room_artifact_hash_provider=_room_artifact_hash_provider_from_environment(),
    )


def pi_runtime_config_from_settings(settings: Mapping[str, object]) -> PiRuntimeConfig:
    agent = settings.get("agent") if isinstance(settings.get("agent"), Mapping) else {}
    pi = agent.get("pi") if isinstance(agent.get("pi"), Mapping) else {}
    return PiRuntimeConfig.from_environment(
        enabled_default=_bool(pi.get("enabled")),
        idle_timeout_default=_integer(
            pi.get("idleTimeoutSeconds"),
            default=900,
            minimum=0,
            maximum=86400,
        ),
    )


def agent_service_from_settings(
    db_path: str | Path,
    settings: Mapping[str, object],
    *,
    project: str = "",
    memory_embedding_provider: EmbeddingProvider | None = None,
    wake_scheduler_enabled: bool = True,
) -> AgentService:
    runtime_config = pi_runtime_config_from_settings(settings)
    agent = settings.get("agent") if isinstance(settings.get("agent"), Mapping) else {}
    pi = agent.get("pi") if isinstance(agent.get("pi"), Mapping) else {}
    default_model_profile = (
        f"{runtime_config.provider}/{runtime_config.model}"
        if runtime_config.provider and runtime_config.model
        else "pi/default"
    )
    room_kernel_mode = _room_kernel_mode_from_environment()
    return AgentService(
        db_path=db_path,
        runtime_config=runtime_config,
        configuration_defaults=default_agent_configuration(
            enabled=runtime_config.enabled,
            idle_timeout_seconds=runtime_config.idle_timeout_seconds,
            role_id=str(pi.get("defaultRoleId") or "companion-future-v1"),
            role_version="1",
            model_profile=default_model_profile,
            tool_profile_version=str(pi.get("toolProfile") or "control-center-v1"),
            resume_last_session=_bool(pi.get("resumeLastSession")),
            coordinator_enabled=_bool(pi.get("coordinatorEnabled")),
        ),
        project=project,
        tool_gateway_url=os.environ.get(
            "RAG_IME_AGENT_TOOL_URL",
            "http://127.0.0.1:8766/api/agent/tool/execute",
        ),
        memory_embedding_provider=memory_embedding_provider,
        wake_scheduler_enabled=wake_scheduler_enabled,
        room_kernel_mode=room_kernel_mode,
        room_runner_secrets=_room_runner_secrets_from_provider(),
        room_delivery_gate_enforcement=_room_delivery_gate_enforcement(room_kernel_mode),
        room_artifact_hash_provider=_room_artifact_hash_provider_from_environment(),
    )


def _room_kernel_mode_from_environment() -> KernelMode:
    value = os.environ.get("RAG_IME_ROOM_KERNEL_MODE", "off").strip().lower()
    if value not in {"off", "shadow", "cohort", "test"}:
        return "off"
    if value == "cohort" and os.environ.get("RAG_IME_ROOM_KERNEL_COHORT_ID", "").strip() != "room-v2-test":
        return "shadow"
    return value  # type: ignore[return-value]


def _room_delivery_gate_enforcement(mode: KernelMode) -> bool:
    return (
        mode == "cohort"
        and os.environ.get("RAG_IME_ROOM_KERNEL_COHORT_ID", "").strip() == "room-v2-test"
    )


def _room_runner_secrets_from_provider() -> dict[str, str]:
    """Load runner trust only from the service's file-based secret provider."""
    provider_path = os.environ.get("RAG_IME_ROOM_RUNNER_SECRET_PROVIDER_FILE", "").strip()
    if not provider_path:
        return {}
    value = json.loads(Path(provider_path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(secret, str) and key and secret
        for key, secret in value.items()
    ):
        raise ValueError("Room runner secret provider must contain a non-empty string map")
    return dict(value)


def _room_artifact_hash_provider_from_environment() -> Callable[[str], str] | None:
    provider_path = os.environ.get("RAG_IME_ROOM_ARTIFACT_HASH_PROVIDER_FILE", "").strip()
    if not provider_path:
        return None
    path = Path(provider_path).expanduser()

    def current_hash(root_id: str) -> str:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            return ""
        result = value.get(root_id)
        return str(result) if isinstance(result, str) else ""

    return current_hash


def _room_skill_stage(dispatch: Mapping[str, object]) -> str:
    """Map a Kernel-owned intent to policy selection without letting Skills route."""

    return {
        "execute": "implementation",
        "review": "review",
        "revise": "feedback",
        "retry": "debugging",
        "resume": "implementation",
        "wake": "implementation",
        "callback": "handoff",
    }.get(str(dispatch.get("intentKind") or ""), "implementation")


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value














def _optional_work_item_id(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("workItemId must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 320 or any(
        ord(char) < 32 for char in normalized
    ):
        raise ValueError("workItemId must contain between 1 and 320 safe characters")
    return normalized


def _public_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:240] or error.__class__.__name__


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _integer(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()








def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
