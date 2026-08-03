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
  todoTask: string;
  todoPhase: string;
  templateId: 'researcher' | 'planner' | 'worker' | 'reviewer' | 'delegate';
  templateVersion: '1';
  ordinal: number;
  task: string;
  expectedOutput: string;
  /**
   * @maxItems 8
   */
  acceptanceCriteria:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  outputSchema?: {
    [k: string]: unknown;
  };
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
  artifact?: {
    schemaVersion: 'rag-ime.agent-artifact-ref.v1';
    artifactId: string;
    ownerKind: 'subagent_run';
    ownerId: string;
    kind: 'lifecycle';
    sha256: string;
    [k: string]: unknown;
  };
  supervision?: {
    phase: 'none' | 'soft' | 'hard' | 'forced';
    reason: string;
    requestedAtMs: number | null;
    graceMs: number;
  };
  resultContextScheduledAtMs: number | null;
  createdAtMs: number;
  startedAtMs: number | null;
  updatedAtMs: number;
  completedAtMs: number | null;
}
