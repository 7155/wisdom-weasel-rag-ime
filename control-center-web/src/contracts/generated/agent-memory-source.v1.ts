/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-memory-source.v1.json
 */

export interface AgentMemorySourceV1 {
  schemaVersion: 'rag-ime.agent-memory-source.v1';
  sourceId: string;
  sessionId: string;
  piEntryId: string;
  inputEventId: number;
  sourceRole: 'user' | 'tool_receipt';
  sourceRevision: number;
  canonicalTextSha256: string;
  status: 'active' | 'superseded' | 'archived' | 'tombstoned';
  createdAtMs: number;
  supersededAtMs?: number | null;
  [k: string]: unknown;
}
