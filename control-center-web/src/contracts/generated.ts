/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Run scripts/generate_control_center_contracts.mjs instead.
 */

import type { ActiveRagStartV1 } from './generated/active-rag-start.v1';
import type { ActiveRagStatusV1 } from './generated/active-rag-status.v1';
import type { ActivityTimelineContextV1 } from './generated/activity-timeline-context.v1';
import type { AgentApprovalV1 } from './generated/agent-approval.v1';
import type { AgentArtifactInspectionV1 } from './generated/agent-artifact-inspection.v1';
import type { AgentArtifactRefV1 } from './generated/agent-artifact-ref.v1';
import type { AgentConfigurationV1 } from './generated/agent-configuration.v1';
import type { AgentContextItemV1 } from './generated/agent-context-item.v1';
import type { AgentContextTraceV1 } from './generated/agent-context-trace.v1';
import type { AgentControlBootstrapV1 } from './generated/agent-control-bootstrap.v1';
import type { AgentControlEventV1 } from './generated/agent-control-event.v1';
import type { AgentConversationContextV1 } from './generated/agent-conversation-context.v1';
import type { AgentEventV1 } from './generated/agent-event.v1';
import type { AgentMediaV1 } from './generated/agent-media.v1';
import type { AgentMemoryEvidenceV1 } from './generated/agent-memory-evidence.v1';
import type { AgentMemoryMaintenanceStatusV1 } from './generated/agent-memory-maintenance-status.v1';
import type { AgentMemorySourceV1 } from './generated/agent-memory-source.v1';
import type { AgentMessageV1 } from './generated/agent-message.v1';
import type { AgentModelCatalogV1 } from './generated/agent-model-catalog.v1';
import type { AgentModelSelectionV1 } from './generated/agent-model-selection.v1';
import type { AgentParticipantV1 } from './generated/agent-participant.v1';
import type { AgentPersonaV1 } from './generated/agent-persona.v1';
import type { AgentRoleBookToolResultV1 } from './generated/agent-role-book-tool-result.v1';
import type { AgentRoleBookV1 } from './generated/agent-role-book.v1';
import type { AgentRoleRoutingProfileV1 } from './generated/agent-role-routing-profile.v1';
import type { AgentRoomEventV1 } from './generated/agent-room-event.v1';
import type { AgentRoomIntercomV1 } from './generated/agent-room-intercom.v1';
import type { AgentRoomSnapshotV1 } from './generated/agent-room-snapshot.v1';
import type { AgentRoomWorkItemV1 } from './generated/agent-room-work-item.v1';
import type { AgentRoomV1 } from './generated/agent-room.v1';
import type { AgentRuntimeBindingV1 } from './generated/agent-runtime-binding.v1';
import type { AgentRuntimeV1 } from './generated/agent-runtime.v1';
import type { AgentSessionForkCandidatesV1 } from './generated/agent-session-fork-candidates.v1';
import type { AgentSessionForkCreateV1 } from './generated/agent-session-fork-create.v1';
import type { AgentSessionTelemetryV1 } from './generated/agent-session-telemetry.v1';
import type { AgentSessionV1 } from './generated/agent-session.v1';
import type { AgentSubagentBatchV1 } from './generated/agent-subagent-batch.v1';
import type { AgentSubagentRunV1 } from './generated/agent-subagent-run.v1';
import type { AgentTemplateV1 } from './generated/agent-template.v1';
import type { AgentThinkingSelectionV1 } from './generated/agent-thinking-selection.v1';
import type { AgentToolCallV1 } from './generated/agent-tool-call.v1';
import type { AgentToolResultV1 } from './generated/agent-tool-result.v1';
import type { AssistantCandidateActionV1 } from './generated/assistant-candidate-action.v1';
import type { AssistantOverlayV1 } from './generated/assistant-overlay.v1';
import type { ControlToolManifestV1 } from './generated/control-tool-manifest.v1';
import type { DailyActivityTimelineV1 } from './generated/daily-activity-timeline.v1';
import type { DailyConversationDigestV1 } from './generated/daily-conversation-digest.v1';
import type { ForegroundCommitV1 } from './generated/foreground-commit.v1';
import type { ForegroundContextV2 } from './generated/foreground-context.v2';
import type { FrontendCapabilitiesV1 } from './generated/frontend-capabilities.v1';
import type { FrontendSelectionResponseV1 } from './generated/frontend-selection-response.v1';
import type { FrontendSelectionV1 } from './generated/frontend-selection.v1';
import type { FrontendSuggestRequestV1 } from './generated/frontend-suggest-request.v1';
import type { FrontendSuggestResponseV1 } from './generated/frontend-suggest-response.v1';
import type { KnowledgeDocumentDetailV1 } from './generated/knowledge-document-detail.v1';
import type { KnowledgeDocumentImportV1 } from './generated/knowledge-document-import.v1';
import type { KnowledgeGraphV1 } from './generated/knowledge-graph.v1';
import type { KnowledgeLibraryV1 } from './generated/knowledge-library.v1';
import type { ManagementWorkErrorV1 } from './generated/management-work-error.v1';
import type { ManagementWorkPreviewV1 } from './generated/management-work-preview.v1';
import type { ManagementWorkReceiptV1 } from './generated/management-work-receipt.v1';
import type { MemoryBootstrapV1 } from './generated/memory-bootstrap.v1';
import type { MemoryCatalogV1 } from './generated/memory-catalog.v1';
import type { MemoryEntityV1 } from './generated/memory-entity.v1';
import type { MemoryGovernancePreviewV1 } from './generated/memory-governance-preview.v1';
import type { MemoryGraphV1 } from './generated/memory-graph.v1';
import type { MemoryReadErrorV1 } from './generated/memory-read-error.v1';
import type { ObservationEventV1 } from './generated/observation-event.v1';
import type { ObservationSnapshotV1 } from './generated/observation-snapshot.v1';
import type { OverlayConfigV1 } from './generated/overlay-config.v1';
import type { PiRuntimeManifestV1 } from './generated/pi-runtime-manifest.v1';
import type { RimeRankSelectionV1 } from './generated/rime-rank-selection.v1';
import type { RimeSelectV1 } from './generated/rime-select.v1';
import type { RimeSuggestRequestV1 } from './generated/rime-suggest-request.v1';
import type { RimeSuggestResponseV1 } from './generated/rime-suggest-response.v1';
import type { RoleBookCurationV1 } from './generated/role-book-curation.v1';
import type { RoleBookRevisionDraftV1 } from './generated/role-book-revision-draft.v1';
import type { UserMemoryDraftV1 } from './generated/user-memory-draft.v1';

export type {
  ActiveRagStartV1,
  ActiveRagStatusV1,
  ActivityTimelineContextV1,
  AgentApprovalV1,
  AgentArtifactInspectionV1,
  AgentArtifactRefV1,
  AgentConfigurationV1,
  AgentContextItemV1,
  AgentContextTraceV1,
  AgentControlBootstrapV1,
  AgentControlEventV1,
  AgentConversationContextV1,
  AgentEventV1,
  AgentMediaV1,
  AgentMemoryEvidenceV1,
  AgentMemoryMaintenanceStatusV1,
  AgentMemorySourceV1,
  AgentMessageV1,
  AgentModelCatalogV1,
  AgentModelSelectionV1,
  AgentParticipantV1,
  AgentPersonaV1,
  AgentRoleBookToolResultV1,
  AgentRoleBookV1,
  AgentRoleRoutingProfileV1,
  AgentRoomEventV1,
  AgentRoomIntercomV1,
  AgentRoomSnapshotV1,
  AgentRoomWorkItemV1,
  AgentRoomV1,
  AgentRuntimeBindingV1,
  AgentRuntimeV1,
  AgentSessionForkCandidatesV1,
  AgentSessionForkCreateV1,
  AgentSessionTelemetryV1,
  AgentSessionV1,
  AgentSubagentBatchV1,
  AgentSubagentRunV1,
  AgentTemplateV1,
  AgentThinkingSelectionV1,
  AgentToolCallV1,
  AgentToolResultV1,
  AssistantCandidateActionV1,
  AssistantOverlayV1,
  ControlToolManifestV1,
  DailyActivityTimelineV1,
  DailyConversationDigestV1,
  ForegroundCommitV1,
  ForegroundContextV2,
  FrontendCapabilitiesV1,
  FrontendSelectionResponseV1,
  FrontendSelectionV1,
  FrontendSuggestRequestV1,
  FrontendSuggestResponseV1,
  KnowledgeDocumentDetailV1,
  KnowledgeDocumentImportV1,
  KnowledgeGraphV1,
  KnowledgeLibraryV1,
  ManagementWorkErrorV1,
  ManagementWorkPreviewV1,
  ManagementWorkReceiptV1,
  MemoryBootstrapV1,
  MemoryCatalogV1,
  MemoryEntityV1,
  MemoryGovernancePreviewV1,
  MemoryGraphV1,
  MemoryReadErrorV1,
  ObservationEventV1,
  ObservationSnapshotV1,
  OverlayConfigV1,
  PiRuntimeManifestV1,
  RimeRankSelectionV1,
  RimeSelectV1,
  RimeSuggestRequestV1,
  RimeSuggestResponseV1,
  RoleBookCurationV1,
  RoleBookRevisionDraftV1,
  UserMemoryDraftV1,
};

export interface ContractTypeMap {
  'active-rag-start.v1': ActiveRagStartV1;
  'active-rag-status.v1': ActiveRagStatusV1;
  'activity-timeline-context.v1': ActivityTimelineContextV1;
  'agent-approval.v1': AgentApprovalV1;
  'agent-artifact-inspection.v1': AgentArtifactInspectionV1;
  'agent-artifact-ref.v1': AgentArtifactRefV1;
  'agent-configuration.v1': AgentConfigurationV1;
  'agent-context-item.v1': AgentContextItemV1;
  'agent-context-trace.v1': AgentContextTraceV1;
  'agent-control-bootstrap.v1': AgentControlBootstrapV1;
  'agent-control-event.v1': AgentControlEventV1;
  'agent-conversation-context.v1': AgentConversationContextV1;
  'agent-event.v1': AgentEventV1;
  'agent-media.v1': AgentMediaV1;
  'agent-memory-evidence.v1': AgentMemoryEvidenceV1;
  'agent-memory-maintenance-status.v1': AgentMemoryMaintenanceStatusV1;
  'agent-memory-source.v1': AgentMemorySourceV1;
  'agent-message.v1': AgentMessageV1;
  'agent-model-catalog.v1': AgentModelCatalogV1;
  'agent-model-selection.v1': AgentModelSelectionV1;
  'agent-participant.v1': AgentParticipantV1;
  'agent-persona.v1': AgentPersonaV1;
  'agent-role-book-tool-result.v1': AgentRoleBookToolResultV1;
  'agent-role-book.v1': AgentRoleBookV1;
  'agent-role-routing-profile.v1': AgentRoleRoutingProfileV1;
  'agent-room-event.v1': AgentRoomEventV1;
  'agent-room-intercom.v1': AgentRoomIntercomV1;
  'agent-room-snapshot.v1': AgentRoomSnapshotV1;
  'agent-room-work-item.v1': AgentRoomWorkItemV1;
  'agent-room.v1': AgentRoomV1;
  'agent-runtime-binding.v1': AgentRuntimeBindingV1;
  'agent-runtime.v1': AgentRuntimeV1;
  'agent-session-fork-candidates.v1': AgentSessionForkCandidatesV1;
  'agent-session-fork-create.v1': AgentSessionForkCreateV1;
  'agent-session-telemetry.v1': AgentSessionTelemetryV1;
  'agent-session.v1': AgentSessionV1;
  'agent-subagent-batch.v1': AgentSubagentBatchV1;
  'agent-subagent-run.v1': AgentSubagentRunV1;
  'agent-template.v1': AgentTemplateV1;
  'agent-thinking-selection.v1': AgentThinkingSelectionV1;
  'agent-tool-call.v1': AgentToolCallV1;
  'agent-tool-result.v1': AgentToolResultV1;
  'assistant-candidate-action.v1': AssistantCandidateActionV1;
  'assistant-overlay.v1': AssistantOverlayV1;
  'control-tool-manifest.v1': ControlToolManifestV1;
  'daily-activity-timeline.v1': DailyActivityTimelineV1;
  'daily-conversation-digest.v1': DailyConversationDigestV1;
  'foreground-commit.v1': ForegroundCommitV1;
  'foreground-context.v2': ForegroundContextV2;
  'frontend-capabilities.v1': FrontendCapabilitiesV1;
  'frontend-selection-response.v1': FrontendSelectionResponseV1;
  'frontend-selection.v1': FrontendSelectionV1;
  'frontend-suggest-request.v1': FrontendSuggestRequestV1;
  'frontend-suggest-response.v1': FrontendSuggestResponseV1;
  'knowledge-document-detail.v1': KnowledgeDocumentDetailV1;
  'knowledge-document-import.v1': KnowledgeDocumentImportV1;
  'knowledge-graph.v1': KnowledgeGraphV1;
  'knowledge-library.v1': KnowledgeLibraryV1;
  'management-work-error.v1': ManagementWorkErrorV1;
  'management-work-preview.v1': ManagementWorkPreviewV1;
  'management-work-receipt.v1': ManagementWorkReceiptV1;
  'memory-bootstrap.v1': MemoryBootstrapV1;
  'memory-catalog.v1': MemoryCatalogV1;
  'memory-entity.v1': MemoryEntityV1;
  'memory-governance-preview.v1': MemoryGovernancePreviewV1;
  'memory-graph.v1': MemoryGraphV1;
  'memory-read-error.v1': MemoryReadErrorV1;
  'observation-event.v1': ObservationEventV1;
  'observation-snapshot.v1': ObservationSnapshotV1;
  'overlay-config.v1': OverlayConfigV1;
  'pi-runtime-manifest.v1': PiRuntimeManifestV1;
  'rime-rank-selection.v1': RimeRankSelectionV1;
  'rime-select.v1': RimeSelectV1;
  'rime-suggest-request.v1': RimeSuggestRequestV1;
  'rime-suggest-response.v1': RimeSuggestResponseV1;
  'role-book-curation.v1': RoleBookCurationV1;
  'role-book-revision-draft.v1': RoleBookRevisionDraftV1;
  'user-memory-draft.v1': UserMemoryDraftV1;
}

export type GeneratedContractName = keyof ContractTypeMap;
