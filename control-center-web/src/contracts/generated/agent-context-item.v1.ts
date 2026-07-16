/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-context-item.v1.json
 */

export interface AgentContextItemV1 {
  schemaVersion: 'rag-ime.agent-context-item.v1';
  itemId: string;
  sessionId: string;
  sourceKind: string;
  sourceId: string;
  lane: 'result' | 'status' | 'notification' | 'room' | 'schedule' | 'fact';
  lifecycle: 'once' | 'turn' | 'until_ack' | 'persistent';
  status: 'pending' | 'delivered' | 'consumed' | 'acknowledged' | 'expired';
  title: string;
  summary: string;
  availableAtMs: number;
  expiresAtMs: number | null;
  deliveredTurnId: string;
  createdAtMs: number;
  updatedAtMs: number;
}
