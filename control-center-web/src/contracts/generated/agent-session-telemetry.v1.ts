/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-session-telemetry.v1.json
 */

export interface AgentSessionTelemetryV1 {
  schemaVersion: 'rag-ime.agent-session-telemetry.v1';
  model: {
    provider: string;
    id: string;
    name: string;
    [k: string]: unknown;
  };
  context: {
    tokens: number | null;
    contextWindow: number;
    percent: number | null;
    remainingTokens: number | null;
    compactAtTokens: number;
    tokensUntilCompact: number | null;
    reserveTokens: number;
    keepRecentTokens: number;
    autoCompactEnabled: boolean;
  };
  cumulativeUsage: Usage;
  latestUsage: Usage;
  latestCacheHitPercent: number | null;
  isCompacting: boolean;
  compactionCount: number;
  latestCompaction?: {
    reason: 'manual' | 'threshold' | 'overflow';
    status: 'running' | 'completed' | 'failed' | 'aborted';
    tokensBefore?: number;
    estimatedTokensAfter?: number;
    willRetry?: boolean;
    error?: string;
    updatedAtMs: number;
  };
  updatedAtMs: number;
}
export interface Usage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
}
