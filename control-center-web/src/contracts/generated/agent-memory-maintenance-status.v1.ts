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
  dueReason:
    'pending_events' | 'idle' | 'daily' | 'owner_daily' | 'draft_pending_review' | 'not_due';
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
  ownerCuration?: {
    schemaVersion: 'rag-ime.owner-memory-curation-status.v1';
    ok: true;
    project: string;
    policy: {
      [k: string]: unknown;
    };
    due: boolean;
    pendingSourceCount: number;
    needsReviewSourceCount: number;
    scopes: {
      [k: string]: unknown;
    }[];
    [k: string]: unknown;
  };
  projection?: {
    schemaVersion: 'rag-ime.memory-projection-runtime.v1';
    ok: boolean;
    configured: boolean;
    owner: string;
    running: boolean;
    lastRunAtMs: number;
    lastError: string;
    freshness: {
      [k: string]: unknown;
    };
    disabledReason: string;
    [k: string]: unknown;
  };
  runs: {
    runId: string;
    createdAtMs: number;
    status: 'draft' | 'applied' | 'partial' | 'rolled_back' | 'superseded' | 'dismissed' | 'empty';
    summary: string;
    diffCount: number;
    bundleHash: string;
    sourceCursor: {
      [k: string]: unknown;
    };
    ownerKind: 'user' | 'shared' | 'agent' | 'session' | 'room';
    ownerId: string;
    runKind: 'legacy' | 'daily_curation' | 'manual_curation' | 'dream_insight';
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
