/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-artifact-ref.v1.json
 */

export interface AgentArtifactRefV1 {
  schemaVersion: 'rag-ime.agent-artifact-ref.v1';
  artifactId: string;
  ownerKind: 'subagent_run' | 'tool_run' | 'connector_run';
  ownerId: string;
  kind: string;
  mediaType: string;
  appendOnly: boolean;
  byteSize: number;
  sha256: string;
  recordCount: number;
  snapshotRevision: number;
  snapshotSha256: string;
  createdAtMs: number;
  updatedAtMs: number;
}
