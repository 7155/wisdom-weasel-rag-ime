/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/sandbox-run.v1.json
 */

export interface SandboxRunV1 {
  schemaVersion: 'rag-ime.sandbox-run.v1';
  sandboxRunId: string;
  appId: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  policy: {
    workspaceBindingId: string;
    workspaceFingerprint: string;
    mutationMode: 'read_only' | 'staged';
    network: 'blocked' | 'allowlisted';
    productionWriteBlocked: true;
  };
  replayCohort?: {
    suiteId: string;
    suiteRevision: string;
    caseId: string;
    inputFingerprint: string;
    environmentFingerprint: string;
    configFingerprint: string;
    modelProfileFingerprint: string;
    toolProfileFingerprint: string;
    skillProfileFingerprint: string;
  };
  traceIds: string[];
  evalRunIds: string[];
  createdAtMs: number;
  updatedAtMs: number;
}
