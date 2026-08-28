/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/paw.plugin-usage.v1.json
 */

export type PawPluginUsageV1 = {
  [k: string]: unknown;
} & {
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
};
