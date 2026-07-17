/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-memory-evidence.v1.json
 */

export interface AgentMemoryEvidenceV1 {
  schemaVersion: 'rag-ime.agent-memory-evidence.v1';
  evidenceId: string;
  project: string;
  roleId: string;
  sessionId: string;
  sourceKind:
    | 'user_message'
    | 'assistant_message'
    | 'tool_receipt'
    | 'session_digest'
    | 'room_event'
    | 'work_receipt';
  sourceId: string;
  idempotencyKey: string;
  text: string;
  textSha256: string;
  classification: 'raw_evidence';
  maySupportLongTermFact: false;
  provenance: {
    [k: string]: unknown;
  };
  metadata: {
    [k: string]: unknown;
  };
  privacyClass: 'local' | 'private';
  status: 'active' | 'tombstoned';
  occurredAtMs: number;
  recordedAtMs: number;
}
