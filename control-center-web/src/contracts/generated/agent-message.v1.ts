/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-message.v1.json
 */

export interface AgentMessageV1 {
  schemaVersion: 'rag-ime.agent-message.v1';
  id: string;
  sessionId: string;
  turnId: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  status: 'queued' | 'streaming' | 'completed' | 'failed' | 'aborted';
  blocks: Block[];
  attachments: string[];
  citations: string[];
  createdAtMs: number;
  completedAtMs?: number | null;
  provider?: string;
  model?: string;
  usage?: Usage;
  [k: string]: unknown;
}
export interface Block {
  id: string;
  type:
    | 'text'
    | 'code'
    | 'reasoning_summary'
    | 'progress'
    | 'tool_call'
    | 'tool_result'
    | 'citation'
    | 'image'
    | 'audio'
    | 'file'
    | 'sticker'
    | 'task_plan'
    | 'diff'
    | 'approval'
    | 'error'
    | 'unknown';
  status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted';
  presentationKind: string;
  data: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
export interface Usage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
}
