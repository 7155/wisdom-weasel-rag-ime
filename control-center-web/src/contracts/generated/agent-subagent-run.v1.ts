/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-subagent-run.v1.json
 */

export interface AgentSubagentRunV1 {
  schemaVersion: 'rag-ime.agent-subagent-run.v1';
  id: string;
  batchId: string;
  childSessionId: string;
  templateId: 'researcher' | 'planner' | 'worker' | 'reviewer' | 'delegate';
  templateVersion: '1';
  ordinal: number;
  task: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'aborted' | 'timed_out';
  budget: {
    maxTurns: number;
    maxToolCalls: number;
    maxTotalTokens: number;
    maxDurationMs: number;
    maxOutputChars: number;
  };
  usage: {
    turnCount: number;
    toolCount: number;
    totalTokens: number;
  };
  result: {
    [k: string]: unknown;
  };
  error: string;
  createdAtMs: number;
  startedAtMs: number | null;
  updatedAtMs: number;
  completedAtMs: number | null;
}
