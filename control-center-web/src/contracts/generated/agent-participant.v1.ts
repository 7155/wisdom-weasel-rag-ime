/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-participant.v1.json
 */

export interface AgentParticipantV1 {
  schemaVersion: 'rag-ime.agent-participant.v1';
  id: string;
  roomId: string;
  sessionId: string;
  roleId: string;
  roleVersion: string;
  displayName: string;
  collaborationRole: 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';
  status: 'active' | 'muted' | 'removed';
  ordinal: number;
  createdAtMs: number;
  lastSpokeAtMs: number | null;
}
