/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-file-descriptor.v1.json
 */

export interface AgentFileDescriptorV1 {
  schemaVersion: 'rag-ime.agent-file-descriptor.v1';
  mediaId: string;
  sessionId: string;
  fileName: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  previewKind: 'markdown' | 'code' | 'diff' | 'image' | 'html' | 'unsupported';
  language: string;
  contentUrl: string;
}
