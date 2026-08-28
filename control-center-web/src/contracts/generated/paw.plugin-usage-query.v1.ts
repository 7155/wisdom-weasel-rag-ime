/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/paw.plugin-usage-query.v1.json
 */

export interface PawPluginUsageQueryV1 {
  schemaVersion: 'paw.plugin-usage-query.v1';
  events: Event[];
  aggregates: {
    packageId: string;
    packageVersion: string;
    resourceKind: 'extension' | 'tool' | 'command' | 'skill' | 'prompt' | 'theme';
    resourceId: string;
    loadedCount: number;
    invocationCount: number;
    terminalCount: number;
    succeededCount: number;
    failedCount: number;
    cancelledCount: number;
    averageDurationMs: number | null;
    lastLoadedAtMs: number | null;
    lastInvokedAtMs: number | null;
  }[];
}
export interface Event {
  schemaVersion: 'paw.plugin-usage.v1';
  eventId: string;
  occurredAtMs: number;
  sessionId: string;
  packageId: string;
  packageVersion: string;
  resourceKind: 'extension' | 'tool' | 'command' | 'skill' | 'prompt' | 'theme';
  resourceId: string;
  activity: 'loaded' | 'invoked' | 'finished';
  invocationId?: string;
  outcome?: 'succeeded' | 'failed' | 'cancelled';
  durationMs?: number;
}
