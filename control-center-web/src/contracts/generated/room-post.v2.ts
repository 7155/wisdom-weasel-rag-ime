/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-post.v2.json
 */

export interface RoomPostV2 {
  schemaVersion: 'wisdom-weasel.room-post.v2';
  postId: string;
  roomId: string;
  rootId: string;
  generation: number;
  taskId?: string;
  dispatchId?: string;
  authorActorRef: string;
  kind: string;
  visibility: 'room' | 'root';
  content: string;
  blocks?: {
    schemaVersion: 'rag-ime.agent-block.v1';
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
      | 'card'
      | 'checklist'
      | 'table'
      | 'artifact'
      | 'reference'
      | 'status'
      | 'unknown';
    status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted';
    presentationKind: string;
    data: {
      [k: string]: unknown;
    };
    summary: string;
    source: {
      [k: string]: unknown;
    };
    visibility: 'room_post' | 'root_post';
    digest: string;
    ref: string;
    generation: number;
    [k: string]: unknown;
  }[];
  idempotencyKey: string;
  publicationSource: {
    kind: 'user' | 'room_commit';
    ref: string;
  };
  createdAtMs: number;
}
