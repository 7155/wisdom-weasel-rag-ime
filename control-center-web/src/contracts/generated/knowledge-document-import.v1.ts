/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/knowledge-document-import.v1.json
 */

export interface KnowledgeDocumentImportV1 {
  schemaVersion: 'rag-ime.knowledge-document-import.v1';
  ok: true;
  receipt: {
    kbId: string;
    documentId: string;
    fileName: string;
    mimeType: string;
    byteSize: number;
    sha256: string;
    status: 'queued' | 'parsing' | 'indexing' | 'ready' | 'stale' | 'failed' | 'deleting';
  };
}
