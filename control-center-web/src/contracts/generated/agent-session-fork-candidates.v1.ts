/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-session-fork-candidates.v1.json
 */

export interface AgentSessionForkCandidatesV1 {
  schemaVersion: 'rag-ime.agent-session-fork-candidates.v1';
  ok: true;
  sessionId: string;
  /**
   * @maxItems 500
   */
  items: {
    entryId: string;
    text: string;
    role: 'user' | 'assistant';
    createdAtMs: number;
  }[];
}
