/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/work-document-detail.v1.json
 */

export interface WorkDocumentDetailV1 {
  schemaVersion: 'rag-ime.work-document-detail.v1';
  document: Document;
  reopen: {
    eligible: boolean;
    authorityRevision: number;
    transitionReceiptId: string;
    reasonCode:
      | 'ready'
      | 'document_not_archived'
      | 'authority_terminal'
      | 'authority_not_advanced'
      | 'authority_unavailable';
  };
}
export interface Document {
  documentId: string;
  authorityKind: 'session_todo' | 'session_goal' | 'room_work_item';
  authorityId: string;
  authorityRevision: number;
  authorityKey: string;
  documentRevision: number;
  contentSha256: string;
  workspaceRoot: string;
  path: string;
  activePath: string;
  archivePath: string;
  state: 'active' | 'archive_pending' | 'archived' | 'reopen_pending' | 'error';
  title: string;
  terminalReceiptId: string;
  error: string;
  createdAtMs: number;
  updatedAtMs: number;
}
