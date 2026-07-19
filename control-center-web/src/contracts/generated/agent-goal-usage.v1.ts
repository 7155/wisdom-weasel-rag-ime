/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-goal-usage.v1.json
 */

export type AgentGoalUsageV1 = {
  [k: string]: unknown;
} & {
  sessionId: string;
  turnId?: string;
  eventId?: string;
  idempotencyKey: string;
  tokenDelta?: number;
  elapsedDeltaMs?: number;
};
