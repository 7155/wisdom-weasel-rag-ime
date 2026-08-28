/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/observability-sandbox-run-list.v1.json
 */

export interface ObservabilitySandboxRunListV1 {
  schemaVersion: 'rag-ime.observability-sandbox-run-list.v1';
  ok: true;
  /**
   * @maxItems 500
   */
  items: SandboxRun[];
  total: number;
}
export interface SandboxRun {
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
  traceIds: string[];
  evalRunIds: string[];
  createdAtMs: number;
  updatedAtMs: number;
}
