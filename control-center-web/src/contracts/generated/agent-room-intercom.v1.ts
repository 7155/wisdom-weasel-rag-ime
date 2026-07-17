/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room-intercom.v1.json
 */

export interface AgentRoomIntercomV1 {
  schemaVersion: 'rag-ime.agent-room-intercom.v1';
  id: string;
  roomId: string;
  kind: 'send' | 'ask' | 'reply';
  sourceParticipantId: string;
  targetParticipantId: string;
  sourceSessionId: string;
  targetSessionId: string;
  sourceGeneration: number;
  targetGeneration: number;
  clientMessageId: string;
  replyTo: string;
  workItemId: string;
  workAction: '' | 'assignment' | 'submission' | 'accepted' | 'revision' | 'blocked' | 'escalated';
  status: 'queued' | 'delivering' | 'delivered' | 'replied' | 'failed' | 'stale' | 'cancelled';
  content: string;
  acceptedTurnId: string;
  error: string;
  createdAtMs: number;
  updatedAtMs: number;
  deliveredAtMs: number | null;
  repliedAtMs: number | null;
}
