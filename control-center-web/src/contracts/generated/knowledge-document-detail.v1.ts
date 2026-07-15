/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/knowledge-document-detail.v1.json
 */

export interface KnowledgeDocumentDetailV1 {
  schemaVersion: 'rag-ime.knowledge-library.v1';
  document: {
    documentId: string;
    kbId: string;
    fileName: string;
    mimeType: string;
    byteSize: number;
    sha256: string;
    status: 'queued' | 'parsing' | 'indexing' | 'ready' | 'stale' | 'failed' | 'deleting';
    sourceReadPath: string;
    [k: string]: unknown;
  };
  chunks: {
    items: unknown[];
    offset: number;
    limit: number;
    total: number;
    hasMore: boolean;
  };
  pages: unknown[];
  assets: {
    assetId: string;
    name: string;
    mimeType: 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp' | 'image/bmp';
    byteSize: number;
    sha256: string;
    readPath: string;
  }[];
  tables: unknown[];
  artifact: {
    [k: string]: unknown;
  };
  contentWindow: {
    [k: string]: unknown;
  };
}
