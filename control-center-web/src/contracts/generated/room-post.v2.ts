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
  question?: {
    prompt: string;
    options: {
      [k: string]: unknown;
    } & QuestionOption[];
  };
  /**
   * @maxItems 16
   */
  mentions?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
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
  /**
   * @maxItems 8
   */
  attachments?:
    | []
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ]
    | [
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
        {
          schemaVersion: 'rag-ime.agent-media.v1';
          mediaId: string;
          ownerType: 'room';
          ownerId: string;
          roomId: string;
          fileName: string;
          mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp';
          byteSize: number;
          sha256: string;
          width?: number | null;
          height?: number | null;
          durationMs?: number | null;
          thumbnailMediaId?: string | null;
          origin: 'user_attachment';
          originTool?: string;
          originReceiptId?: string;
          createdAtMs: number;
        },
      ];
  workResult?: {
    proposedOperabilityVerdict: 'passed' | 'failed' | 'unverified';
    proposedRequirementVerdict: 'satisfied' | 'not_satisfied' | 'unverified';
  };
  idempotencyKey: string;
  publicationSource: {
    kind: 'user' | 'room_commit' | 'room_post' | 'runtime_projection';
    ref: string;
  };
  chronology?: Chronology;
  createdAtMs: number;
}
export interface QuestionOption {
  value: string;
  label: string;
  description?: string;
  recommended?: boolean;
}
export interface Chronology {
  schemaVersion: 'wisdom-weasel.room-post-chronology.v1';
  roomEventId: string;
  roomEventSequence: number;
  createdAtMs: number;
  afterPostId: string | null;
  orderKey: string;
}
