/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-background-job.v1.json
 */

export interface AgentBackgroundJobV1 {
  schemaVersion: 'rag-ime.agent-background-job.v1';
  jobId: string;
  sessionId: string;
  label: string;
  status: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'orphaned';
  command: string;
  commandSha256: string;
  cwd: string;
  networkAllowed: boolean;
  maxRunSeconds: number;
  pid: number | null;
  createdAtMs: number;
  startedAtMs: number;
  updatedAtMs: number;
  endedAtMs: number;
  exitCode: number | null;
  outputBytes: number;
  logStartCursor: number;
  logTruncated: boolean;
  cancelRequestedAtMs: number;
  error: string;
  approvalId: string;
  causalMetadata: {
    todoId: string;
    todoRevision: number;
    goalId: string;
    goalRevision: number;
    turnId: string;
    roomBound: boolean;
  };
  roomLineage?: {
    roomId: string;
    rootId: string;
    generation: number;
    taskId: string;
    dispatchId: string;
  };
}
