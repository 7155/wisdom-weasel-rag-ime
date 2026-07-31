/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-media.v1.json
 */

export interface AgentMediaV1 {
  schemaVersion: 'rag-ime.agent-media.v1';
  mediaId: string;
  ownerType: 'session' | 'room';
  ownerId: string;
  sessionId?: string;
  roomId?: string;
  fileName?: string;
  mimeType:
    | 'image/png'
    | 'image/jpeg'
    | 'image/gif'
    | 'image/webp'
    | 'audio/mpeg'
    | 'audio/mp4'
    | 'audio/wav'
    | 'application/pdf'
    | 'text/plain'
    | 'text/markdown'
    | 'text/html'
    | 'text/x-diff'
    | 'text/x-patch';
  byteSize: number;
  sha256: string;
  width?: number | null;
  height?: number | null;
  durationMs?: number | null;
  thumbnailMediaId?: string | null;
  origin: 'user_attachment' | 'tool_result' | 'managed_asset';
  originTool?: string;
  originReceiptId?: string;
  createdAtMs: number;
  [k: string]: unknown;
}
