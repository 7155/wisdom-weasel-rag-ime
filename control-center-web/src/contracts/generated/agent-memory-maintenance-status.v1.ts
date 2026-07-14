/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-memory-maintenance-status.v1.json
 */

export interface AgentMemoryMaintenanceStatusV1 {
  schemaVersion: 'rag-ime.agent-memory-maintenance-status.v1';
  ok: true;
  policy: 'review';
  autoApply: false;
  scheduledDraftOnly: true;
  due: boolean;
  dueReason: 'pending_events' | 'idle' | 'daily' | 'not_due';
  idleMs: number;
  compileState: {
    project: string;
    lastCompiledEventId: number;
    lastRunMs: number;
    pendingEventCount: number;
    lastBundleHash: string;
    [k: string]: unknown;
  };
  pendingDraftCount: number;
  runs: {
    runId: string;
    createdAtMs: number;
    status: 'draft' | 'applied' | 'partial' | 'rolled_back' | 'superseded' | 'empty';
    summary: string;
    diffCount: number;
    bundleHash: string;
    sourceCursor: {
      [k: string]: unknown;
    };
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
