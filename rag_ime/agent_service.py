from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import RLock

from .db import sqlite_connection
from .agent_configuration import (
    AgentConfigurationStore,
    AgentControlEventHub,
    default_agent_configuration,
    runtime_policy_from_configuration,
)
from .agent_approval_application import AgentApprovalApplicationService
from .agent_approval_model import ApprovalModelArbiter
from .agent_background_jobs import AgentBackgroundJobService
from .agent_context_runtime import AgentContextRuntime
from .agent_execution_policy import (
    execution_policy_prompt,
)
from .work_documents import WorkDocumentService
from .agent_command_receipts import (
    AgentCommandReceiptStore,
    AgentTurnConflictError,
)
from .agent_events import AgentEventHub
from .agent_event_projection import AgentEventProjectionService
from .agent_block_store import AgentBlockStore
from .agent_delegation import AgentDelegationCoordinator
from .agent_file_preview import AgentFilePreviewReader
from .agent_media import AgentMediaStore, IMAGE_MIME_TYPES
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
from .agent_session_mode_gate import AgentSessionModeGate
from .agent_room_intercom import (
    AgentRoomIntercomRouter,
    AgentRoomIntercomStore,
)
from .agent_room_intercom_application import (
    RoomIntercomApplicationService,
)
from .agent_room_session_dispatch import RoomSessionDispatchService
from .agent_room_session_cancellation import RoomSessionCancellationService
from .agent_room_management import RoomManagementService
from .agent_room_partner_application import (
    RoomPartnerApplicationService,
)
from .agent_room_prompt_context import (
    agent_message_text as _agent_message_text,
    room_intercom_prompt as _room_intercom_prompt,
    room_participant_prompt as _room_participant_prompt,
)
from .collaboration_profile_control import CollaborationProfileControl
from .agent_task_context import AgentTaskContextResolver
from .agent_room_work import AgentRoomWorkStore
from .agent_room_work_application import RoomWorkApplicationService
from .agent_room_turn_registry import RoomTurnRegistry
from .agent_governance_projection import GovernanceProjectionStore
from .agent_knowledge_promotion import KNOWLEDGE_ROUTE_HASH, KnowledgePromotionStore
from .knowledge_scope import bound_session_knowledge_caller
from .agent_runtime_driver import (
    AgentRuntimePolicy,
    AgentRuntimeDriver,
    RuntimeDriverContext,
    RuntimeDriverFactory,
    ToolManifestProvider,
)
from .agent_rooms import AgentRoomEventHub, AgentRoomNotFound, AgentRoomStore
from .agent_roles import PersonaManifest
from .agent_sessions import AgentSessionStore
from .agent_tool_ids import (
    CONTROL_CENTER_TOOL_PROFILE,
)
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
# Ordinary Goal recovery allows four native follow-up opportunities, followed
# by one final settle decision that must stop the cancel scope.
GOAL_SETTLE_ATTEMPT_LIMIT = 5
GOAL_CONTINUATION_LIMIT = 4


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
        background_job_execution_owner: bool = True,
        collaboration_profile_signers: Mapping[str, bytes] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = str(project or "")
        self.personas = AgentPersonaStore(db_path)
        self.personas.initialize()
        self.role_books = AgentRoleBookStore(db_path)
        self.role_books.initialize()
        self.tool_token = str(tool_gateway_token or secrets.token_urlsafe(32))
        self.plugin_approval_token = secrets.token_urlsafe(32)
        self.tool_gateway_url = str(tool_gateway_url).strip()
        if not self.tool_gateway_url:
            raise ValueError("tool gateway URL must not be empty")
        self._tool_manifest_provider: ToolManifestProvider | None = None
        configured = replace(
            runtime_config or PiRuntimeConfig.from_environment(),
            tool_gateway_token=self.tool_token,
            plugin_approval_token=self.plugin_approval_token,
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
        self.session_mode_gate = AgentSessionModeGate()
        self.room_turns = RoomTurnRegistry()
        self.runtime_factory.apply_policy(
            runtime_policy_from_configuration(
                self.configuration_store.snapshot()["configuration"]
            )
        )
        self.media = AgentMediaStore(db_path)
        self.media.initialize()
        self.file_previews = AgentFilePreviewReader(self.media)
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
        self.governance_projection = GovernanceProjectionStore(db_path)
        self.governance_projection.initialize()
        self.knowledge_promotion = KnowledgePromotionStore(db_path)
        self.knowledge_promotion.initialize()
        self._collaboration_profile_signers = {
            str(signer_id): bytes(key)
            for signer_id, key in (collaboration_profile_signers or {}).items()
        }
        self.observations = ObservationHub(db_path)
        self.room_events = AgentRoomEventHub(self.rooms)
        self._remove_observation_room_observer = self.room_events.add_observer(
            self.observations.enqueue_room_event
        )
        self.events = AgentEventHub(
            sequence_loader=self.sessions.max_event_sequence,
            event_recorder=self._record_event,
            event_observer=self._mirror_event_to_room,
            background_projection=True,
        )
        self.background_jobs = AgentBackgroundJobService(
            db_path,
            events=self.events.publish,
            execution_owner=background_job_execution_owner,
        )
        self.background_jobs.initialize()
        self.work_documents = WorkDocumentService(
            db_path,
            sessions=self.sessions,
            context_runtime=self.context_runtime,
        )
        self.work_documents.initialize()
        self.room_work.set_terminal_observer(
            self.work_documents.observe_authority
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
        self.approval_model = ApprovalModelArbiter(
            db_path,
            runtime_provider=lambda: self.runtime,
            context_provider=self._approval_model_context,
        )
        self.role_application = AgentRoleApplicationService(
            personas=self.personas,
            runtime_provider=lambda: self.runtime,
            runtime_factory=self.runtime_factory,
        )
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
            context_runtime=self.context_runtime,
            events=self.events,
            media_resolver=self.media.resolve_pi_image,
            runtime_driver_factory=self.runtime_factory,
            runtime_provider=lambda: self.runtime,
            tool_gateway_token=self.tool_token,
            tool_gateway_url=self.tool_gateway_url,
            tool_manifest_provider=self._runtime_tool_manifest,
            compaction_observer=self._checkpoint_runtime_compaction,
            room_context_provider=self._room_delegation_context,
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
        )
        self.memory_context_application = (
            AgentMemoryContextService(
                sessions=self.sessions,
                personas=self.personas,
                role_books=self.role_books,
                memory_bootstrap=self.memory_bootstrap,
                context_runtime=self.context_runtime,
                task_context=self.task_context,
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
                room_public_recovery_context=(
                    self._room_public_recovery_context_for_session
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
                rooms=self.rooms,
                agent_blocks=self.agent_blocks,
                observations=self.observations,
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
                room_turns=self.room_turns,
                runtime_provider=lambda: self.runtime,
                # Read-only membership checks; the registry stays the only
                # mutation owner.
                user_priority_sessions=(
                    self.room_turns.user_priority_sessions
                ),
                turn_lock=self.room_turns.lock,
                guard_room_session_route=(
                    lambda route_id, session_id: (
                        self._guard_room_session_route(
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
                guard_room_session_route=lambda route_id, session_id: (
                self._guard_room_session_route(route_id, session_id)
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
        self.room_dispatch = RoomSessionDispatchService(
            self,
            build_participant_prompt=_room_participant_prompt,
            resolve_attachments=self._resolve_room_attachments,
        )
        self.room_cancellation = RoomSessionCancellationService(self)
        self.room_partner_application = RoomPartnerApplicationService(
            rooms=self.rooms,
            room_turns=self.room_turns,
            runtime_status=self.runtime.runtime_status,
            sessions=self.sessions,
            room_events=self.room_events,
            room_target_idle=self._room_target_idle,
            begin_room_turn=self._begin_room_turn,
            room_dispatch=self.room_dispatch,
            cancel_room_turn=self._cancel_room_turn,
            abort_session=self.abort,
            room_topic_for_turn=self._room_topic_for_turn,
        )
        self.room_work_application = RoomWorkApplicationService(self)
        self.approval_application = AgentApprovalApplicationService(self)
        self.message_snapshot = AgentMessageSnapshotService(
            sessions=self.sessions,
            runtime_provider=lambda: self.runtime,
            workflow_projector=self.workflow_state,
            agent_blocks=self.agent_blocks,
            observations=self.observations,
            events=self.events,
            background_jobs=self.background_jobs,
            room_public_messages=(
                self._room_public_messages_for_session
            ),
            room_recent_public_messages=(
                self._recent_room_public_messages_for_session
            ),
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
            # Read-only busy checks under the shared lock; mutation stays
            # inside the registry.
            turn_lock=self.room_turns.lock,
            pending_turns=self.room_turns.pending_turn_by_session,
            user_priority_sessions=(
                self.room_turns.user_priority_sessions
            ),
        )

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
            }
        return dict(provider(session_id, str(turn_id or "")))

    def _runtime_tool_manifest(
        self,
        session: Mapping[str, object],
    ) -> list[Mapping[str, object]]:
        session_id = str(session.get("id") or "").strip()
        if session_id:
            # Prompt/runtime callbacks may retain an earlier Session mapping.
            # The durable lease policy is authoritative for this disclosure.
            session = self.sessions.get(session_id)
        provider = self._tool_manifest_provider
        if provider is None:
            return []
        return [dict(item) for item in provider(session)]



    def _approval_model_context(
        self,
        approval: Mapping[str, object],
        session: Mapping[str, object],
    ) -> dict[str, object]:
        """Project user/task evidence without any primary-Agent output."""

        session_id = str(
            approval.get("sessionId") or session.get("id") or ""
        )
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        room_id = (
            str(participant.get("roomId") or "")
            if isinstance(participant, Mapping)
            else ""
        )
        if room_id:
            requests: list[dict[str, object]] = []
            for event in self.rooms.list_events(room_id, limit=500):
                if str(event.get("eventType") or "") != "user_message":
                    continue
                payload = (
                    event.get("payload")
                    if isinstance(event.get("payload"), Mapping)
                    else {}
                )
                text = str(payload.get("text") or "").strip()
                if not text:
                    continue
                requests.append(
                    {
                        "role": "user",
                        "text": text,
                        "turnId": str(event.get("turnId") or ""),
                        "createdAtMs": int(event.get("createdAtMs") or 0),
                    }
                )
            task = self.task_context.resolve(session_id)
            root_id, dispatch_id = self.room_turns.active_turn(session_id)
            task_context = {
                "kind": str(task.get("kind") or "room_task"),
                "roomId": room_id,
                "rootId": root_id,
                "dispatchId": dispatch_id,
                "taskId": str(task.get("workItemId") or ""),
                "state": str(task.get("state") or ""),
                "objective": str(task.get("objective") or ""),
                "expectedOutput": str(task.get("expectedOutput") or ""),
            }
            return {
                "contextKind": "room",
                "contextAvailable": bool(requests),
                "contextId": room_id,
                "userRequests": requests[-8:],
                "currentTask": task_context,
                "actor": {
                    "sessionId": session_id,
                    "roomId": room_id,
                    "participantId": (
                        str(participant.get("id") or "")
                        if isinstance(participant, Mapping)
                        else ""
                    ),
                    "dispatchId": (
                        dispatch_id
                    ),
                },
            }

        message_snapshot = self.message_snapshot.messages(session_id)
        snapshot_messages = message_snapshot.get("items")
        if not isinstance(snapshot_messages, list):
            # Older in-process projections used ``messages``; the canonical
            # snapshot contract is ``items``. Keep context assembly tolerant
            # while reading the authoritative snapshot, not Provider output.
            snapshot_messages = message_snapshot.get("messages")
        requests: list[dict[str, object]] = []
        for message in list(snapshot_messages or []):
            if not isinstance(message, Mapping):
                continue
            if str(message.get("role") or "") != "user":
                continue
            text = _approval_user_request_text(message)
            if not text:
                continue
            requests.append(
                {
                    "role": "user",
                    "text": text,
                    "turnId": str(
                        message.get("turnId") or message.get("id") or ""
                    ),
                    "createdAtMs": int(message.get("createdAtMs") or 0),
                }
            )
        workflow = self.sessions.workflow_state(session_id)
        goal = (
            workflow.get("goal")
            if isinstance(workflow.get("goal"), Mapping)
            else {}
        )
        todo = (
            workflow.get("todo")
            if isinstance(workflow.get("todo"), Mapping)
            else {}
        )
        current_task = {
            "kind": "agent_workflow",
            "activeUserRequest": (
                str(requests[-1]["text"]) if requests else ""
            ),
            "goal": (
                {
                    "goalId": str(goal.get("goalId") or ""),
                    "status": str(goal.get("status") or ""),
                    "objective": str(goal.get("objective") or ""),
                    "successCriteria": str(
                        goal.get("successCriteria") or ""
                    ),
                    "evidenceExpectations": list(
                        goal.get("evidenceExpectations") or []
                    ),
                }
                if goal.get("configured") is True
                else {}
            ),
            "todo": {
                "phases": [
                    {
                        "name": str(phase.get("name") or ""),
                        "tasks": [
                            {
                                "content": str(item.get("content") or ""),
                                "status": str(item.get("status") or ""),
                            }
                            for item in list(phase.get("tasks") or [])
                            if isinstance(item, Mapping)
                        ],
                    }
                    for phase in list(todo.get("phases") or [])
                    if isinstance(phase, Mapping)
                ],
            },
        }
        return {
            "contextKind": "session",
            "contextAvailable": bool(requests),
            "contextId": session_id,
            "userRequests": requests[-8:],
            "currentTask": current_task,
            "actor": {"sessionId": session_id},
        }



    def _room_public_recovery_context_for_session(
        self,
        session_id: str,
    ) -> str:
        # Room partners are ordinary Pi Sessions. Pi's own compaction summary
        # is the recovery source; there is no second Kernel recovery packet.
        return ""


    def _runtime_session_context(self, session: Mapping[str, object]) -> Mapping[str, object]:
        delegation = getattr(self, "delegation", None)
        if delegation is not None:
            delegated = delegation.runtime_session_context(session)
            if delegated:
                return delegated
        session_id = str(session.get("id") or "")
        session_context = "\n\n".join(
            value
            for value in (
                execution_policy_prompt(session),
                self.memory_context_application.provider_context(session_id),
            )
            if value
        )
        return {"sessionContext": session_context} if session_context else {}

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
            self.personas.resolve_active(
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
        session_id = _required_text(payload, "sessionId")
        with self._direct_agent_entry(session_id):
            return self.session_application.ensure_runtime(payload)

    def list_sessions(self, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        return self.session_application.list_sessions(payload)

    def workflow_state(self, session_id: str) -> dict[str, object]:
        state = self.sessions.workflow_state(
            session_id,
            room_dispatch_authorized=(
                self._active_room_dispatch_authorizes_work(session_id)
            ),
        )
        validate_contract(state, "agent-workflow-state.v1.json")
        return state

    def _active_room_dispatch_context(
        self,
        session_id: str,
    ) -> dict[str, object] | None:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        root_id, dispatch_id = self.room_turns.active_turn(session_id)
        if participant is None or not root_id:
            return None
        task = self.task_context.resolve(session_id)
        return {
            "roomId": str(participant.get("roomId") or ""),
            "rootId": root_id,
            "taskId": str(task.get("workItemId") or ""),
            "dispatchId": dispatch_id,
            "generation": 0,
        }

    def _active_room_dispatch_authorizes_work(
        self,
        session_id: str,
    ) -> bool:
        return self._active_room_dispatch_context(session_id) is not None

    def _room_delegation_context(
        self,
        session_id: str,
    ) -> dict[str, object]:
        live = self._active_room_dispatch_context(session_id)
        if live is None:
            return {
                "roomBound": False,
                "roomId": "",
                "rootId": "",
                "taskId": "",
                "dispatchId": "",
                "generation": 0,
            }
        lineage = {
            "roomId": str(live.get("roomId") or ""),
            "rootId": str(live.get("rootId") or ""),
            "taskId": str(live.get("taskId") or ""),
            "dispatchId": str(live.get("dispatchId") or ""),
        }
        return {
            "roomBound": True,
            **lineage,
            "generation": int(live["generation"]),
        }


    def mutate_goal(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request = dict(payload)
        validate_contract(request, "agent-goal-mutation.v1.json")
        if request["action"] in {"pause", "cancel"}:
            self._transition_goal_cancellation(session_id, request)
        else:
            self.sessions.mutate_agent_goal(session_id, request)
        state = self.publish_workflow_state(session_id, reason=f"goal:{request['action']}")
        goal = state.get("goal")
        if isinstance(goal, Mapping) and goal.get("goalId"):
            try:
                self.work_documents.observe_authority(
                    "session_goal", str(goal["goalId"])
                )
            except Exception:
                # The reconciler owns filesystem recovery; Goal state remains canonical.
                pass
        return state

    def _transition_goal_cancellation(
        self,
        session_id: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        action = str(request["action"])
        scope_kind = "goal"
        source = self.sessions.agent_goal(session_id)
        scope_id = str(source["goalId"])
        expected_terminal = "paused" if action == "pause" else "cancelled"
        source_revision = int(source["revision"])
        expected_revision = request.get("expectedRevision")
        existing = None
        if str(source["status"]) == expected_terminal:
            candidate = self.sessions.lifecycle_cancellation_for_transition(
                session_id,
                scope_kind=scope_kind,
                scope_id=scope_id,
                transition_revision=source_revision,
                action=action,
            )
            if (
                candidate is not None
                and (
                    expected_revision is None
                    or int(candidate["sourceRevision"]) == int(expected_revision)
                )
            ):
                existing = candidate
        if existing is None:
            lifecycle_request = {
                "requestId": _lifecycle_cancellation_request_id(
                    session_id=session_id,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    source_revision=source_revision,
                    action=action,
                ),
                "scopeKind": scope_kind,
                "scopeId": scope_id,
                "sourceRevision": source_revision,
                "sourceTurnId": self.sessions.latest_runtime_turn_id(session_id),
                "action": action,
                "reason": str(request.get("reason") or request.get("note") or ""),
            }
            mutation = self.sessions.mutate_agent_goal(
                session_id,
                request,
                lifecycle_request=lifecycle_request,
            )
            existing = dict(mutation["lifecycleAudit"])
        audit = self._cancel_lifecycle_owners(existing)
        self.events.publish(
            session_id,
            "lifecycle_cancellation_changed",
            {"audit": audit},
            turn_id=str(audit.get("sourceTurnId") or ""),
        )
        return audit

    def _cancel_lifecycle_owners(
        self,
        audit: Mapping[str, object],
    ) -> dict[str, object]:
        request_id = str(audit["requestId"])
        session_id = str(audit["sessionId"])
        scope_kind = str(audit["scopeKind"])
        scope_id = str(audit["scopeId"])
        source_revision = int(audit["sourceRevision"])
        reason = str(audit.get("reason") or f"{scope_kind}_{audit['action']}")
        current = dict(audit)

        runtime_owner = _lifecycle_owner(current, "runtime")
        if runtime_owner["status"] not in {"succeeded", "excluded"}:
            try:
                raw_runtime_receipt = self.runtime.abort(session_id)
                runtime_receipt = _lifecycle_public_receipt(
                    raw_runtime_receipt
                )
                runtime_status = _runtime_lifecycle_status(
                    runtime_receipt
                )
            except Exception as exc:
                runtime_status = "unknown"
                runtime_receipt = {
                    "reason": "runtime_owner_request_failed",
                    "errorType": type(exc).__name__,
                }
            current = self.sessions.record_lifecycle_owner_receipt(
                request_id,
                owner="runtime",
                status=runtime_status,
                receipt=runtime_receipt,
            )

        approval_owner = _lifecycle_owner(current, "approval")
        if approval_owner["status"] not in {"succeeded", "excluded"}:
            try:
                approval_receipt = self.sessions.cancel_causal_approvals(
                    session_id,
                    request_id=request_id,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    source_revision=source_revision,
                    reason=reason,
                )
                approval_status = "succeeded"
            except Exception as exc:
                approval_status = "unknown"
                approval_receipt = {
                    "reason": "approval_owner_request_failed",
                    "errorType": type(exc).__name__,
                }
            current = self.sessions.record_lifecycle_owner_receipt(
                request_id,
                owner="approval",
                status=approval_status,
                receipt=_lifecycle_public_receipt(approval_receipt),
            )

        job_owner = _lifecycle_owner(current, "job")
        if job_owner["status"] not in {"succeeded", "excluded"}:
            try:
                job_receipt = self.background_jobs.cancel_causal(
                    session_id,
                    request_id=request_id,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    source_revision=source_revision,
                    reason=reason,
                )
                job_status = _job_lifecycle_status(job_receipt)
            except Exception as exc:
                job_status = "unknown"
                job_receipt = {
                    "reason": "background_job_owner_request_failed",
                    "errorType": type(exc).__name__,
                }
            current = self.sessions.record_lifecycle_owner_receipt(
                request_id,
                owner="job",
                status=job_status,
                receipt=_lifecycle_public_receipt(job_receipt),
            )
        delegation_owner = _lifecycle_owner(current, "delegation")
        if delegation_owner["status"] not in {"succeeded", "excluded"}:
            try:
                delegation_receipt = self.delegation.cancel_causal(
                    session_id,
                    request_id=request_id,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    source_revision=source_revision,
                    reason=reason,
                )
                delegation_status = _delegation_lifecycle_status(
                    delegation_receipt
                )
            except Exception as exc:
                delegation_status = "unknown"
                delegation_receipt = {
                    "reason": "delegation_owner_request_failed",
                    "errorType": type(exc).__name__,
                }
            current = self.sessions.record_lifecycle_owner_receipt(
                request_id,
                owner="delegation",
                status=delegation_status,
                receipt=_lifecycle_public_receipt(
                    delegation_receipt
                ),
            )
        return current

    def internal_workflow_state(self, payload: Mapping[str, object]) -> dict[str, object]:
        state = self.workflow_state(_required_text(payload, "sessionId"))
        return {
            "ok": True,
            "result": {
                "todo": state["todo"],
                "goal": state["goal"],
                "actGate": state["actGate"],
            },
        }

    def settle_goal_runtime(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Decide whether one ordinary Goal turn needs one native continuation.

        Pi owns turn scheduling; this method owns the product decision.  A
        continuation claim is persisted atomically against the Goal lifecycle
        epoch, so replay is idempotent and a new Pi cancel scope or process
        cannot replenish the global allowance. Paused, completed, exhausted,
        or stalled Goals and closed Act Gates terminate without asking another
        model to judge its own completion.
        """

        request = dict(payload)
        validate_contract(request, "agent-goal-settle-request.v1.json")
        session_id = str(request["sessionId"])
        settle_scope_id = str(request["settleScopeId"])
        settle_attempt = int(request["settleAttempt"])
        fresh_tool_evidence_count = int(
            request["freshToolEvidenceCount"]
        )
        fresh_tool_evidence_sha256 = str(
            request["freshToolEvidenceSha256"]
        )
        state = self.workflow_state(session_id)
        goal = (
            state["goal"]
            if isinstance(state.get("goal"), Mapping)
            else {}
        )
        gate = (
            state["actGate"]
            if isinstance(state.get("actGate"), Mapping)
            else {}
        )
        goal_id = str(goal.get("goalId") or "")
        goal_status = str(goal.get("status") or "cleared")
        gate_reason = str(gate.get("reason") or "governance_blocked")
        continuation = self.sessions.agent_goal_continuation_budget(
            session_id,
            goal_id=goal_id,
            limit=GOAL_CONTINUATION_LIMIT,
        )

        decision = "inactive"
        reason = "goal_not_active"
        if goal.get("configured") is True:
            if goal_status == "paused":
                decision = "paused"
                reason = "goal_paused"
            elif goal_status == "completed":
                decision = "completed"
                reason = "goal_completed"
            elif goal_status == "cancelled":
                decision = "cancelled"
                reason = "goal_cancelled"
            elif goal_status != "active":
                decision = "inactive"
                reason = f"goal_{goal_status or 'not_active'}"
            elif goal.get("budgetExceeded") is True:
                decision = "budget_exhausted"
                reason = "goal_budget_exhausted"
            elif gate.get("allowed") is not True:
                decision = "blocked"
                reason = gate_reason
            elif settle_attempt >= GOAL_SETTLE_ATTEMPT_LIMIT:
                decision = "stalled"
                reason = "settle_attempt_limit"
            elif (
                settle_attempt > 1
                and fresh_tool_evidence_count == 0
            ):
                decision = "stalled"
                reason = "no_progress"
            else:
                decision = "continue"
                reason = "goal_active"

        material = "\x1f".join(
            (
                session_id,
                goal_id,
                str(int(goal.get("revision") or 0)),
                settle_scope_id,
                str(settle_attempt),
                str(fresh_tool_evidence_count),
                fresh_tool_evidence_sha256,
            )
        )
        request_key = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if decision == "continue":
            claim = self.sessions.claim_agent_goal_continuation(
                session_id,
                goal_id=goal_id,
                request_key=request_key,
                limit=GOAL_CONTINUATION_LIMIT,
            )
            continuation = {
                key: int(claim[key])
                for key in ("epoch", "issuedCount", "limit", "remaining")
            }
            current_goal = (
                claim["goal"]
                if isinstance(claim.get("goal"), Mapping)
                else goal
            )
            current_gate = (
                claim["actGate"]
                if isinstance(claim.get("actGate"), Mapping)
                else gate
            )
            goal = current_goal
            goal_id = str(goal.get("goalId") or "")
            if claim.get("claimed") is not True:
                claim_reason = str(claim.get("reason") or "goal_not_active")
                if claim_reason == "goal_continuation_limit":
                    decision = "stalled"
                elif str(goal.get("status") or "") == "paused":
                    decision = "paused"
                    claim_reason = "goal_paused"
                elif str(goal.get("status") or "") == "completed":
                    decision = "completed"
                    claim_reason = "goal_completed"
                elif str(goal.get("status") or "") == "cancelled":
                    decision = "cancelled"
                    claim_reason = "goal_cancelled"
                elif goal.get("budgetExceeded") is True:
                    decision = "budget_exhausted"
                    claim_reason = "goal_budget_exhausted"
                else:
                    decision = "blocked"
                reason = claim_reason

        result: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-goal-settle-result.v1",
            "sessionId": session_id,
            "goalId": goal_id,
            "goalRevision": int(goal.get("revision") or 0),
            "settleScopeId": settle_scope_id,
            "settleAttempt": settle_attempt,
            "freshToolEvidenceCount": fresh_tool_evidence_count,
            "freshToolEvidenceSha256": fresh_tool_evidence_sha256,
            "continuationEpoch": int(continuation["epoch"]),
            "continuationCount": int(continuation["issuedCount"]),
            "continuationLimit": int(continuation["limit"]),
            "continuationRemaining": int(continuation["remaining"]),
            "state": decision,
            "reason": reason,
            "followUpKey": "",
            "message": "",
        }
        if decision == "continue":
            result["followUpKey"] = (
                "goal-settle:"
                + request_key[:32]
            )
            result["message"] = (
                '<managed-goal-follow-up origin="goal-supervisor">'
                "当前 Goal 仍处于 active，Todo 中有正在执行的任务，且预算允许继续。"
                "一次回答结束不代表 Goal 完成；立即完成 Todo 中当前正在执行、"
                "能够产生新验收证据的下一步。不要只汇报进度或复述 Todo。"
                "先同步更新 Todo 状态；若已经没有可继续的下一步，再把 Goal 更新为"
                "完成、暂停或取消，而不是继续空转。"
                "</managed-goal-follow-up>"
            )
        validate_contract(result, "agent-goal-settle-result.v1.json")
        return {"ok": True, "result": result}

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
                "todo": state["todo"],
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

    def update_role(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.role_application.update_role(payload)

    def archive_role(self, payload: Mapping[str, object]) -> dict[str, object]:
        role_id = str(payload.get("roleId") or "").strip()
        role_version = str(payload.get("roleVersion") or "").strip()
        defaults = self.configuration_store.snapshot()["configuration"]["sessionDefaults"]
        if role_id == defaults["roleId"] and role_version == defaults["roleVersion"]:
            raise ValueError("default companion cannot be removed; choose another default first")
        return self.role_application.archive_role(payload)

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

    def _restore_room_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> None:
        self.room_management.restore_participant_sessions(room)

    def room(self, room_id: str) -> dict[str, object]:
        return self.room_management.get_room(room_id)

    def room_snapshot(self, room_id: str) -> dict[str, object]:
        return self.room_management.snapshot(room_id)

    def room_history(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.room_management.history(room_id, payload)


    def collaboration_profile_projection(self, profile_id: str) -> dict[str, object]:
        with sqlite_connection(self.db_path) as conn:
            return self._collaboration_profile_control(conn).projection(profile_id)

    def apply_collaboration_profile_command(
        self,
        payload: Mapping[str, object],
        *,
        caller_authorized: bool = False,
    ) -> dict[str, object]:
        if not caller_authorized:
            raise PermissionError("CollaborationProfile control requires an authorized control caller")
        with sqlite_connection(self.db_path) as conn:
            result = self._collaboration_profile_control(conn).execute(payload)
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
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row) as conn:
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
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row) as conn:
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
        )

















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

    def update_room_participant_role(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management.update_participant_role(
            room_id,
            payload,
        )

    def delete_room(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.room_management.delete_room(room_id, payload)

    def create_room(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.room_management.create_room(payload)

    def post_room_message(self, room_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        message = str(payload.get("message") or "")
        if not message.strip():
            raise ValueError("room message must not be empty")
        if len(message) > ROOM_MESSAGE_CHAR_LIMIT:
            raise ValueError(
                f"Room message must not exceed {ROOM_MESSAGE_CHAR_LIMIT} characters"
            )
        client_message_id = _optional_client_message_id(payload.get("clientMessageId"))
        work_item_id = _optional_work_item_id(payload.get("workItemId"))
        answer_to_post_id = str(payload.get("answerToPostId") or "").strip()
        answer_to_root_id = str(payload.get("answerToRootId") or "").strip()
        if bool(answer_to_post_id) != bool(answer_to_root_id):
            raise ValueError(
                "Room clarification answers require answerToPostId and answerToRootId"
            )
        if len(answer_to_post_id) > 320 or len(answer_to_root_id) > 320:
            raise ValueError("Room clarification answer identity is too long")
        attachment_ids = _room_attachment_ids(payload.get("attachmentIds"))
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
                attachment_ids=attachment_ids,
                answer_to_post_id=answer_to_post_id,
                answer_to_root_id=answer_to_root_id,
            )
        claim = self.command_receipts.begin(
            command_scope="room_message",
            scope_id=room_id,
            client_message_id=client_message_id,
            payload={
                "message": message,
                "participantIds": requested_participant_ids,
                "workItemId": work_item_id,
                "attachmentIds": attachment_ids,
                "answerToPostId": answer_to_post_id,
                "answerToRootId": answer_to_root_id,
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
                attachment_ids=attachment_ids,
                answer_to_post_id=answer_to_post_id,
                answer_to_root_id=answer_to_root_id,
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

    def execute_room_partner_tool(
        self,
        session_id: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
    ) -> dict[str, object]:
        return self.room_partner_application.execute(
            session_id,
            args,
            tool_call_id=tool_call_id,
        )

    def steer_room_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Durably apply one typed supplement to a running Room participant."""

        root_id = str(payload.get("rootId") or "").strip()
        client_action_id = str(payload.get("clientActionId") or "").strip()
        if not root_id or not client_action_id:
            raise ValueError(
                "participant steer requires rootId and clientActionId"
            )
        receipt_payload = {
            "action": payload.get("action"),
            "rootId": root_id,
            "expectedGeneration": payload.get("expectedGeneration"),
            "participantId": payload.get("participantId"),
            "message": payload.get("message"),
        }
        scope_id = f"{room_id}:{root_id}"
        claim = self.command_receipts.begin(
            command_scope="room_participant_steer",
            scope_id=scope_id,
            client_message_id=client_action_id,
            payload=receipt_payload,
        )
        if claim.replay_response is not None:
            return {**claim.replay_response, "idempotentReplay": True}
        try:
            response = self._steer_room_participant_once(room_id, payload)
        except Exception as exc:
            self.command_receipts.fail(
                claim,
                command_scope="room_participant_steer",
                scope_id=scope_id,
                client_message_id=client_action_id,
                error=exc,
            )
            raise
        response["controlReceipt"] = {
            "state": "accepted",
            "scope": "room_participant_steer",
            "clientActionId": client_action_id,
        }
        return self.command_receipts.complete(
            claim,
            command_scope="room_participant_steer",
            scope_id=scope_id,
            client_message_id=client_action_id,
            response=response,
        )

    def _steer_room_participant_once(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        if str(payload.get("action") or "").strip() != "steer_participant":
            raise ValueError(
                "Room participant control action must be steer_participant"
            )
        root_id = str(payload.get("rootId") or "").strip()
        message = str(payload.get("message") or "").strip()
        client_action_id = str(payload.get("clientActionId") or "").strip()
        if not message:
            raise ValueError("participant steer message must not be empty")
        if len(message) > ROOM_MESSAGE_CHAR_LIMIT:
            raise ValueError(
                f"Room message must not exceed {ROOM_MESSAGE_CHAR_LIMIT} characters"
            )
        room = self.rooms.get(room_id)
        events = [
            event
            for event in self.rooms.list_events(room_id, after_sequence=0, limit=2000)
            if str(event.get("turnId") or "") == root_id
        ]
        if not any(str(event.get("eventType") or "") == "user_message" for event in events):
            raise ValueError("Room turn does not belong to this Room")
        routed_participant_ids = {
            str(
                event.get("participantId")
                or (
                    event.get("payload", {}).get("targetParticipantId")
                    if isinstance(event.get("payload"), Mapping)
                    else ""
                )
                or ""
            )
            for event in events
            if str(event.get("eventType") or "") == "route_decision"
        }
        routed_participant_ids.discard("")
        requested_participant_id = str(payload.get("participantId") or "").strip()
        participant_id = requested_participant_id or next(iter(routed_participant_ids), "")
        if not participant_id or participant_id not in routed_participant_ids:
            raise ValueError("participant steer target is not part of this Room turn")
        participant = self.rooms.participant(participant_id)
        if (
            str(participant.get("roomId") or "") != room_id
            or str(participant.get("status") or "") != "active"
        ):
            raise ValueError("participant steer target is no longer active")
        session_id = str(participant.get("sessionId") or "")
        topic_id = str(room.get("activeTopicId") or "")
        room_event = self.room_events.publish(
            room_id=room_id,
            event_type="user_message",
            payload={
                "text": message,
                "delivery": "steer",
                "rootId": root_id,
                "targetParticipantIds": [participant_id],
                "clientActionId": client_action_id,
            },
            turn_id=root_id,
            participant_id=participant_id,
            source_session_id=session_id,
            topic_id=topic_id,
        )
        accepted = self.prompt(
            session_id,
            {
                "message": message,
                "clientMessageId": client_action_id,
                "delivery": "steer",
                "_contextSourceToken": self._context_source_token,
                "_contextSource": "room",
                "_checkpointText": message,
            },
        )
        return {
            "schemaVersion": "rag-ime.agent-room-steer.v1",
            "ok": True,
            "accepted": True,
            "roomId": room_id,
            "rootId": root_id,
            "participantId": participant_id,
            "sessionId": session_id,
            "delivery": "steer",
            "turnId": str(accepted.get("turnId") or ""),
            "event": room_event,
            "sessionReceipt": accepted,
        }

    def _resolve_room_attachments(
        self,
        room_id: str,
        target_session_ids: Sequence[str],
        attachment_ids: Sequence[str],
    ) -> list[dict[str, object]]:
        if not attachment_ids:
            return []
        room = self.rooms.get(room_id)
        if room.get("status") != "active":
            raise ValueError("Room attachments require an active Room")
        active_by_session = {
            str(participant.get("sessionId") or ""): participant
            for participant in room.get("participants", [])
            if (
                isinstance(participant, Mapping)
                and participant.get("status") == "active"
            )
        }
        for session_id in target_session_ids:
            participant = active_by_session.get(str(session_id))
            if participant is None:
                raise ValueError("Room attachment target is no longer an active participant")
            selected = self.runtime.model_catalog(str(session_id)).get("selected")
            if (
                not isinstance(selected, Mapping)
                or selected.get("supportsImages") is not True
            ):
                name = str(participant.get("displayName") or "所选伙伴")
                raise ValueError(
                    f"{name} 的当前模型不支持图片，请切换模型或移除图片后重试"
                )
        receipts = [
            self.media.receipt(media_id, room_id=room_id)
            for media_id in dict.fromkeys(attachment_ids)
        ]
        for receipt in receipts:
            if receipt.get("mimeType") not in IMAGE_MIME_TYPES:
                raise ValueError("Room attachments currently support PNG, JPEG, GIF, and WebP only")
        return receipts


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
        return self.room_cancellation.abort_turn(
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
        attachment_ids: Sequence[str],
        answer_to_post_id: str,
        answer_to_root_id: str,
    ) -> dict[str, object]:
        if answer_to_post_id or answer_to_root_id:
            raise ValueError("Room messages no longer accept clarification reply ids")
        return self.room_dispatch.post_message(
            room_id,
            message=message,
            client_message_id=client_message_id,
            requested_participant_ids=requested_participant_ids,
            work_item_id=work_item_id,
            attachment_ids=attachment_ids,
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
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        return self.room_dispatch.dispatch_target(
            room=room,
            target=target,
            decision=decision,
            message=message,
            room_turn_id=room_turn_id,
            topic_id=topic_id,
            unread=unread,
            work_item=work_item,
            attachment_ids=attachment_ids,
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
        self.background_jobs.cancel_session(
            session_id,
            reason="agent_session_deleted",
        )
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

    def _room_public_messages_for_session(
        self,
        session_id: str,
    ) -> dict[str, object] | None:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if participant is None:
            return None
        room_id = str(participant.get("roomId") or "")
        participant_id = str(participant.get("id") or "")
        if not room_id or not participant_id:
            return None
        events = self.rooms.list_events(
            room_id,
            limit=2_000,
        )
        return {
            "participantId": participant_id,
            "events": [
                event
                for event in events
                if event.get("eventType") == "user_message"
                or (
                    event.get("eventType") == "room_post"
                    and str(event.get("participantId") or "")
                    == participant_id
                )
            ],
        }

    def _recent_room_public_messages_for_session(
        self,
        session_id: str,
    ) -> dict[str, object] | None:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if participant is None:
            return None
        room_id = str(participant.get("roomId") or "")
        participant_id = str(participant.get("id") or "")
        if not room_id or not participant_id:
            return None
        events = self.rooms.recent_public_messages(
            room_id,
            limit=100,
        )
        return {
            "participantId": participant_id,
            "events": [
                event
                for event in events
                if event.get("eventType") == "user_message"
                or (
                    event.get("eventType") == "room_post"
                    and str(event.get("participantId") or "")
                    == participant_id
                )
            ],
        }


    def messages(self, session_id: str) -> dict[str, object]:
        return self.message_snapshot.messages(session_id)

    def import_media(
        self,
        *,
        session_id: str = "",
        room_id: str = "",
        data: bytes,
        mime_type: str,
        file_name: str = "",
    ) -> dict[str, object]:
        owner_type, owner_id = _media_owner_input(
            session_id=session_id,
            room_id=room_id,
        )
        if owner_type == "session":
            self.sessions.get(owner_id)
        else:
            room = self.rooms.get(owner_id)
            if room.get("status") != "active":
                raise ValueError("Room attachments require an active Room")
        return {
            "schemaVersion": "rag-ime.agent-media-import.v1",
            "ok": True,
            "media": self.media.import_bytes(
                session_id=owner_id if owner_type == "session" else "",
                room_id=owner_id if owner_type == "room" else "",
                data=data,
                mime_type=mime_type,
                file_name=file_name,
            ),
        }

    def list_media(self, payload: Mapping[str, object]) -> dict[str, object]:
        owner_type, owner_id = _media_owner_input(
            session_id=payload.get("sessionId"),
            room_id=payload.get("roomId"),
        )
        if owner_type == "session":
            self.sessions.get(owner_id)
        else:
            self.rooms.get(owner_id)
        return {
            "schemaVersion": "rag-ime.agent-media-list.v1",
            "ok": True,
            "ownerType": owner_type,
            "ownerId": owner_id,
            "items": self.media.list_for_owner(
                session_id=owner_id if owner_type == "session" else "",
                room_id=owner_id if owner_type == "room" else "",
                limit=_integer(payload.get("limit"), default=100, minimum=1, maximum=500),
            ),
        }

    def media_receipt(
        self,
        media_id: str,
        *,
        session_id: str = "",
        room_id: str = "",
    ) -> dict[str, object]:
        owner_type, owner_id = _media_owner_input(
            session_id=session_id,
            room_id=room_id,
        )
        if owner_type == "session":
            self.sessions.get(owner_id)
        else:
            self.rooms.get(owner_id)
        return {
            "schemaVersion": "rag-ime.agent-media-get.v1",
            "ok": True,
            "media": self.media.receipt(
                media_id,
                session_id=owner_id if owner_type == "session" else "",
                room_id=owner_id if owner_type == "room" else "",
            ),
        }

    def media_content(
        self,
        media_id: str,
        *,
        session_id: str = "",
        room_id: str = "",
    ) -> tuple[dict[str, object], bytes]:
        owner_type, owner_id = _media_owner_input(
            session_id=session_id,
            room_id=room_id,
        )
        if owner_type == "session":
            self.sessions.get(owner_id)
        else:
            self.rooms.get(owner_id)
        return self.media.read(
            media_id,
            session_id=owner_id if owner_type == "session" else "",
            room_id=owner_id if owner_type == "room" else "",
        )

    def file_preview(
        self,
        media_id: str,
        *,
        session_id: str,
        expected_sha256: str = "",
    ) -> dict[str, object]:
        self.sessions.get(session_id)
        return self.file_previews.read(
            media_id,
            session_id=session_id,
            expected_sha256=expected_sha256,
        )

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
        retry_of_client_message_id: str = "",
        context_source: str = "user",
        delivery: str = "prompt",
        transient_context: str = "",
        media_owner_room_id: str = "",
        on_accepted: (
            Callable[[Mapping[str, object]], None] | None
        ) = None,
    ) -> dict[str, object]:
        if media_owner_room_id:
            if context_source != "room":
                raise ValueError(
                    "Room-owned media requires a Room prompt context"
                )
            self._resolve_room_attachments(
                media_owner_room_id,
                [session_id],
                attachment_ids,
            )
        elif context_source == "room" and attachment_ids:
            raise ValueError(
                "Room prompt attachments require a Room media owner"
            )
        if context_source == "room":
            return self.prompt_application.prompt_with_checkpoint(
                session_id=session_id,
                message=message,
                checkpoint_text=checkpoint_text,
                attachment_ids=attachment_ids,
                client_message_id=client_message_id,
                retry_of_client_message_id=(
                    retry_of_client_message_id
                ),
                context_source=context_source,
                delivery=delivery,
                transient_context=transient_context,
                media_owner_room_id=media_owner_room_id,
                on_accepted=on_accepted,
            )
        with self._direct_agent_entry(session_id):
            return self.prompt_application.prompt_with_checkpoint(
                session_id=session_id,
                message=message,
                checkpoint_text=checkpoint_text,
                attachment_ids=attachment_ids,
                client_message_id=client_message_id,
                retry_of_client_message_id=(
                    retry_of_client_message_id
                ),
                context_source=context_source,
                delivery=delivery,
                transient_context=transient_context,
                media_owner_room_id=media_owner_room_id,
                on_accepted=on_accepted,
            )

    @contextmanager
    def _direct_agent_entry(
        self,
        session_id: str,
    ) -> Iterator[None]:
        with self.session_mode_gate.claim_agent(session_id):
            self._assert_direct_agent_prompt_available(session_id)
            self.room_turns.hold_priority((session_id,))
            try:
                yield
            finally:
                self.room_turns.release_priority_session(
                    session_id
                )

    def _assert_direct_agent_prompt_available(
        self,
        session_id: str,
    ) -> None:
        room_busy = self.room_turns.session_turn_active(
            session_id
        )
        if not room_busy:
            return
        raise AgentTurnConflictError(
            "Session 正在执行 Room 任务，不能同时从 Agent 发送；"
            "请等待 Room 结束或先停止该 Room 任务"
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
        runtime_receipt: Mapping[str, object] = {}
        try:
            raw_runtime_receipt = self.runtime.abort(session_id)
            if isinstance(raw_runtime_receipt, Mapping):
                runtime_receipt = raw_runtime_receipt
        finally:
            approval_cancellation = (
                self.approval_application.cancel_pending_for_session(
                    session_id,
                    reason="user_abort",
                    turn_id=str(runtime_receipt.get("turnId") or ""),
                )
            )
        return {
            "schemaVersion": "rag-ime.agent-abort.v1",
            "ok": True,
            "sessionId": session_id,
            "runtimeReceipt": dict(runtime_receipt),
            "approvalCancellation": approval_cancellation,
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
                        "compactionEntryId": result.get("compactionEntryId"),
                        "expectedContextEpoch": result.get("contextEpochBefore"),
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
        legacy_pending = _integer(
            compile_state.get("pendingEventCount"),
            default=0,
            minimum=0,
            maximum=2_147_483_647,
        )
        owner_curation = (
            status.get("ownerCuration")
            if isinstance(status.get("ownerCuration"), Mapping)
            else {}
        )
        pending = _integer(
            owner_curation.get("pendingSourceCount"),
            default=legacy_pending,
            minimum=0,
            maximum=2_147_483_647,
        )
        needs_review = _integer(
            owner_curation.get("needsReviewSourceCount"),
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
            f"记忆整理已达到触发条件，当前有 {pending} 条受治理证据、{needs_review} 条待人工判定"
            if due
            else f"已检查记忆整理状态：{pending} 条受治理证据、{needs_review} 条待人工判定、{drafts} 份待审草案"
        )
        self.events.publish(
            session_id,
            "memory_maintenance_updated",
            {
                "trigger": trigger,
                "due": due,
                "dueReason": str(status.get("dueReason") or ""),
                "pendingEventCount": pending,
                "pendingSourceCount": pending,
                "needsReviewSourceCount": needs_review,
                "legacyPendingEventCount": legacy_pending,
                "pendingDraftCount": drafts,
                "summary": summary,
            },
        )
        return {**status, "trigger": trigger}

    def list_approvals(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.list_approvals(payload)

    def resolve_review(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        return self.approval_application.resolve_review(session_id, payload)

    def resolve_ui_request(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        request_id = str(payload.get("requestId") or "").strip()
        if not request_id:
            raise ValueError("UI requestId must not be empty")
        response = {
            key: payload[key]
            for key in (
                "value",
                "confirmed",
                "cancelled",
                "resolutionSource",
            )
            if key in payload
        }
        if response.get("cancelled") is not True and not (
            "value" in response or isinstance(response.get("confirmed"), bool)
        ):
            raise ValueError("UI response must include a value, confirmation, or cancellation")
        return self.runtime.resolve_ui_request(
            session_id,
            request_id,
            response=response,
        )

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










    def _consume_room_knowledge_cache_tombstones(self) -> int:
        """Clear process-local recall state after durable knowledge invalidation.

        Retiring the durable tombstones belongs to the store that writes them;
        this service only owns the in-process recall state that has to follow.
        """
        retired = self.knowledge_promotion.consume_cache_tombstones(
            consumed_at_ms=int(time.time() * 1000)
        )
        self.memory_context_application.clear_recall_state(retired.session_ids)
        return retired.consumed






    def close(self) -> None:
        self.delegation.close()
        self.runtime.stop()
        self.background_jobs.close()
        self.events.close()
        self._remove_observation_room_observer()
        self.observations.close()
        self._remove_wake_observer()
        self.wake_scheduler.close()
        self.room_intercom.close()

    def reconfigure_runtime(self, config: PiRuntimeConfig) -> dict[str, object]:
        self.runtime.stop()
        config = replace(
            config,
            tool_gateway_token=self.tool_token,
            plugin_approval_token=self.plugin_approval_token,
            role_resolver=self.personas.resolve,
            role_book_resolver=self.role_books.prompt_block,
        )
        self.runtime_factory.reconfigure(config)
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
        self.delegation.reconfigure(config)
        self.room_intercom.notify()
        return self.runtime_status()

    def _apply_runtime_policy(self, policy: AgentRuntimePolicy) -> dict[str, object]:
        self.runtime.stop()
        self.runtime_factory.apply_policy(policy)
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
        self.delegation.refresh_runtime_factory()
        self.room_intercom.notify()
        return self.runtime.runtime_status()

    def _record_event(self, event: AgentEventEnvelope) -> None:
        self.event_projection_application.record(event)


    def _mirror_event_to_room(self, event: AgentEventEnvelope) -> None:
        if not self.room_turns.allows_room_event(event):
            return
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
        child: bool = False,
    ) -> None:
        self.room_turns.begin(
            session_id,
            room_turn_id,
            topic_id,
            dispatch_id=dispatch_id,
            child=child,
        )

    def _accept_room_turn(
        self,
        session_id: str,
        session_turn_id: str,
        room_turn_id: str,
    ) -> None:
        with self.room_turns.lock:
            buffered = self.room_turns.accept(
                session_id,
                session_turn_id,
                room_turn_id,
            )
            for event in buffered:
                self._mirror_event_to_room(event)
                if event.event_type in {
                    "turn_completed",
                    "turn_failed",
                }:
                    break

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

    def _guard_room_session_route(self, route_id: str, session_id: str) -> None:
        # Pi Session is the sole execution owner for direct and Room prompts.
        self.sessions.get(str(session_id or ""))

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
    )


def pi_runtime_config_from_settings(settings: Mapping[str, object]) -> PiRuntimeConfig:
    agent = settings.get("agent") if isinstance(settings.get("agent"), Mapping) else {}
    pi = agent.get("pi") if isinstance(agent.get("pi"), Mapping) else {}
    privacy = (
        settings.get("privacy")
        if isinstance(settings.get("privacy"), Mapping)
        else {}
    )
    runtime_config = PiRuntimeConfig.from_environment(
        enabled_default=_bool(pi.get("enabled")),
        idle_timeout_default=_integer(
            pi.get("idleTimeoutSeconds"),
            default=900,
            minimum=0,
            maximum=86400,
        ),
        system_proxy_default=_bool(pi.get("systemProxy", True)),
    )
    if (
        runtime_config.debug_context_dir is None
        and _bool(privacy.get("debugIncludeText"))
    ):
        configured_directory = str(
            privacy.get("debugContextDirectory") or ""
        ).strip()
        storage_gib = _integer(
            privacy.get("debugContextMaxGiB"),
            default=5,
            minimum=1,
            maximum=64,
        )
        max_calls_per_turn = _integer(
            privacy.get("debugContextMaxCallsPerTurn"),
            default=128,
            minimum=1,
            maximum=256,
        )
        runtime_config = replace(
            runtime_config,
            debug_context_dir=(
                Path(configured_directory).expanduser()
                if configured_directory
                else runtime_config.agent_dir.parent / "debug-context"
            ),
            debug_context_max_bytes=storage_gib * 1024 * 1024 * 1024,
            debug_context_max_calls=max_calls_per_turn,
        )
    return runtime_config


def agent_service_from_settings(
    db_path: str | Path,
    settings: Mapping[str, object],
    *,
    project: str = "",
    memory_embedding_provider: EmbeddingProvider | None = None,
    wake_scheduler_enabled: bool = True,
    runtime_execution_owner: bool = True,
) -> AgentService:
    runtime_config = pi_runtime_config_from_settings(settings)
    agent = settings.get("agent") if isinstance(settings.get("agent"), Mapping) else {}
    pi = agent.get("pi") if isinstance(agent.get("pi"), Mapping) else {}
    default_model_profile = (
        f"{runtime_config.provider}/{runtime_config.model}"
        if runtime_config.provider and runtime_config.model
        else "pi/default"
    )
    return AgentService(
        db_path=db_path,
        runtime_config=runtime_config,
        runtime_factory=PiRuntimeDriverFactory(
            runtime_config,
            execution_owner=runtime_execution_owner,
        ),
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
        background_job_execution_owner=runtime_execution_owner,
    )














def _approval_user_request_text(
    message: Mapping[str, object],
) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    text = message.get("text")
    if isinstance(text, str):
        return text.strip()
    blocks = message.get("blocks")
    if not isinstance(blocks, Sequence) or isinstance(
        blocks,
        (str, bytes, bytearray),
    ):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        block_type = str(block.get("type") or "")
        if block_type not in {"text", "input_text"}:
            continue
        value = block.get("text") or block.get("content")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)






def _lifecycle_cancellation_request_id(
    *,
    session_id: str,
    scope_kind: str,
    scope_id: str,
    source_revision: int,
    action: str,
) -> str:
    canonical = json.dumps(
        {
            "sessionId": session_id,
            "scopeKind": scope_kind,
            "scopeId": scope_id,
            "sourceRevision": int(source_revision),
            "action": action,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "lifecycle:"
        + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )


def _lifecycle_owner(
    audit: Mapping[str, object],
    owner: str,
) -> Mapping[str, object]:
    owners = audit.get("owners")
    if not isinstance(owners, Mapping):
        return {"status": "pending", "receipt": {}}
    value = owners.get(owner)
    return value if isinstance(value, Mapping) else {
        "status": "pending",
        "receipt": {},
    }


def _lifecycle_public_receipt(value: object) -> dict[str, object]:
    forbidden = {
        "pid",
        "processid",
        "processhandle",
        "processgroupid",
    }

    def project(item: object) -> object:
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized = "".join(
                    character
                    for character in key.casefold()
                    if character.isalnum()
                )
                if normalized in forbidden:
                    continue
                result[key] = project(child)
            return result
        if isinstance(item, (list, tuple)):
            return [project(child) for child in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        return str(item)

    projected = project(value)
    return projected if isinstance(projected, dict) else {}


def _runtime_lifecycle_status(receipt: Mapping[str, object]) -> str:
    if not receipt:
        return "unknown"
    lifecycle = receipt.get("lifecycle")
    if isinstance(lifecycle, Mapping):
        if (
            lifecycle.get("drained") is False
            or bool(lifecycle.get("failedOperationIds"))
            or bool(lifecycle.get("pendingOperations"))
        ):
            return "partial"
    return "succeeded"


def _job_lifecycle_status(receipt: Mapping[str, object]) -> str:
    jobs = receipt.get("jobs")
    if not isinstance(jobs, list):
        return "unknown"
    statuses = {
        str(item.get("status") or "")
        for item in jobs
        if isinstance(item, Mapping)
    }
    if statuses & {"queued", "running", "cancelling", "failed", "orphaned"}:
        return "partial"
    return "succeeded"


def _delegation_lifecycle_status(
    receipt: Mapping[str, object],
) -> str:
    if not receipt:
        return "unknown"
    if (
        str(receipt.get("state") or "") == "requested"
        or bool(receipt.get("pendingRunIds"))
    ):
        return "partial"
    return "succeeded"


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _media_owner_input(
    *,
    session_id: object = "",
    room_id: object = "",
) -> tuple[str, str]:
    session = str(session_id or "").strip()
    room = str(room_id or "").strip()
    if bool(session) == bool(room):
        raise ValueError("exactly one sessionId or roomId is required")
    owner_id = session or room
    if (
        len(owner_id) > 160
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]*", owner_id)
    ):
        raise ValueError("media owner id is invalid")
    return ("session", session) if session else ("room", room)


def _room_attachment_ids(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("attachmentIds must be an array")
    if len(value) > 8:
        raise ValueError("a Room message supports at most 8 images")
    result: list[str] = []
    for item in value:
        media_id = str(item or "").strip()
        if not re.fullmatch(r"media_[A-Za-z0-9_-]{12,80}", media_id):
            raise ValueError("attachmentIds must contain managed mediaId values")
        if media_id not in result:
            result.append(media_id)
    return result














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
