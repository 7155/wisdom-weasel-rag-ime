/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/work-document-command.v1.json
 */

export type WorkDocumentCommandV1 = {
  [k: string]: unknown;
} & {
  schemaVersion: 'rag-ime.work-document-command.v1';
  ok: true;
  operation: 'register' | 'archive' | 'repair' | 'reopen' | 'erase-preview' | 'erase';
  document: Document | null;
  receipt?: Receipt;
  approval?: {
    [k: string]: unknown;
  };
  payloadSha256?: string;
};

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
export interface Receipt {
  receiptId: string;
  operation: 'register' | 'archive' | 'repair' | 'reopen' | 'erase';
  status: 'accepted' | 'applied' | 'failed';
  idempotent: boolean;
  createdAtMs: number;
}
