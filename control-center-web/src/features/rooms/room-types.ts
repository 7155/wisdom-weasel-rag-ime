export type RoomCollaborationRole = 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';

export interface RoomParticipant {
  id: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
  collaborationRole?: RoomCollaborationRole;
  status: string;
  ordinal: number;
}

export type RoomKind = 'collaboration' | 'roleplay';
export type RoomExecutionMode = 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
export type RoomRoutingPolicy = 'moderator' | 'manual_mentions' | 'sequential' | 'natural' | 'parallel' | 'invite_only';

export interface RoomTopic {
  id: string;
  roomId: string;
  title: string;
  summary: string;
  status: 'active' | 'archived';
  ordinal: number;
  createdAtMs: number;
  updatedAtMs: number;
}

export interface RoomArtifact {
  id: string;
  roomId: string;
  topicId: string;
  displayName: string;
  path: string;
  mediaType: string;
  status: 'active' | 'archived';
  createdAtMs: number;
  updatedAtMs: number;
}

export type RoomWorkState = 'queued' | 'active' | 'review' | 'blocked' | 'done' | 'failed' | 'cancelled';

/** Dual-axis independent review verdict recorded on a WorkItem: operability
 * (does it run) and requirement (does it satisfy the ask) stay separate. */
export interface RoomWorkItemReview {
  operabilityVerdict: string;
  requirementVerdict: string;
  evidenceRefs: string[];
  reason: string;
  reviewerParticipantId: string;
  reviewedAtMs: number | null;
}

export interface RoomWorkItem {
  id: string;
  roomId: string;
  topicId: string;
  rootTurnId: string;
  rootWorkId: string;
  parentWorkId: string;
  objective: string;
  expectedOutput: string;
  acceptanceCriteria: string[];
  accountableParticipantId: string;
  currentOwnerParticipantId: string;
  offeredToParticipantId: string;
  createdByParticipantId: string;
  clientMessageId: string;
  state: RoomWorkState;
  depth: number;
  revision: number;
  resultSummary: string;
  artifactRefs: string[];
  evidenceRefs: string[];
  review?: RoomWorkItemReview;
  blocker: Record<string, unknown>;
  acceptedTurnId: string;
  createdAtMs: number;
  updatedAtMs: number;
  completedAtMs: number | null;
}

export interface RoomSummary {
  id: string;
  title: string;
  status: string;
  roomKind?: RoomKind;
  avatar?: string;
  description?: string;
  scenarioPrompt?: string;
  routingPolicy: RoomRoutingPolicy;
  routingConfig?: {
    maxResponders?: number;
    naturalJitter?: number;
    fallbackParticipantId?: string;
  };
  moderatorParticipantId: string;
  activeTopicId?: string;
  configRevision?: number;
  workspaceRoots?: string[];
  executionMode?: RoomExecutionMode;
  topics?: RoomTopic[];
  artifacts?: RoomArtifact[];
  workItems?: RoomWorkItem[];
  updatedAtMs: number;
  participants: RoomParticipant[];
}
