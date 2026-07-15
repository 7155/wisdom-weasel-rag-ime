/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-control-event.v1.json
 */

export interface AgentControlEventV1 {
  schemaVersion: 'rag-ime.agent-control-event.v1';
  eventId: string;
  sequence: number;
  eventType:
    | 'configuration_changed'
    | 'configuration_applied'
    | 'configuration_failed'
    | 'snapshot_required';
  createdAtMs: number;
  payload: {
    [k: string]: unknown;
  };
  resumeToken: string;
  [k: string]: unknown;
}
