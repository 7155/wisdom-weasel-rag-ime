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
  ownerKind: 'user' | 'shared' | 'agent' | 'session' | 'room';
  ownerId: string;
  knowledgeDomain: string;
  scopeKind: string;
  scopeId: string;
  visibility: string;
  authorizationRevision: string;
  bindingId: string;
  scopeMode: 'legacy' | 'authoritative' | 'quarantined';
  roleId: string;
  roleVersion: string;
  sourceKind:
    'user_final' | 'tool_receipt' | 'session_compaction' | 'session_digest' | 'explicit_memory';
  trustClass:
    'user_claim' | 'applied_receipt' | 'session_summary' | 'assistant_claim' | 'explicit_command';
  disposition:
    'pending' | 'remember' | 'not_for_memory' | 'needs_review' | 'consolidated' | 'expired';
  dispositionReason: string;
  dispositionUpdatedAtMs?: number | null;
  processedAtMs?: number | null;
  curationRunId: string;
  coverageStartEntryId: string;
  coverageEndEntryId: string;
  expiresAtMs?: number | null;
  metadata: {
    [k: string]: unknown;
  };
  createdAtMs: number;
  supersededAtMs?: number | null;
  [k: string]: unknown;
}
