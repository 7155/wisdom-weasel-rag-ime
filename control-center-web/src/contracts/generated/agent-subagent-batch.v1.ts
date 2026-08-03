/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-subagent-batch.v1.json
 */

export interface AgentSubagentBatchV1 {
  schemaVersion: 'rag-ime.agent-subagent-batch.v1';
  id: string;
  parentSessionId: string;
  parentRunId: string;
  contextMode: 'fresh' | 'fork';
  resultDeliveryMode: 'inline' | 'next_turn';
  state: 'queued' | 'running' | 'completed' | 'failed' | 'aborted' | 'timed_out';
  depth: number;
  maxDepth: number;
  abortRequested: boolean;
  causalMetadata: {
    todoId: string;
    todoRevision: number;
    goalId: string;
    goalRevision: number;
    roomBound: boolean;
    roomId: string;
    rootId: string;
    taskId: string;
    dispatchId: string;
    generation: number;
  };
  createdAtMs: number;
  updatedAtMs: number;
  completedAtMs: number | null;
  /**
   * @minItems 1
   * @maxItems 2
   */
  runs:
    | [
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ];
}
