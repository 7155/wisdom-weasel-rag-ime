import type {
  Document as CommandDocument,
  Receipt as GeneratedWorkDocumentReceiptV1,
  WorkDocumentCommandV1 as GeneratedWorkDocumentCommandV1,
} from './generated/work-document-command.v1';
import type { WorkDocumentDetailV1 as GeneratedWorkDocumentDetailV1 } from './generated/work-document-detail.v1';
import type { WorkDocumentListV1 as GeneratedWorkDocumentListV1 } from './generated/work-document-list.v1';

export type WorkDocumentV1 = CommandDocument;
export type WorkDocumentAuthorityKind = WorkDocumentV1['authorityKind'];
export type WorkDocumentState = WorkDocumentV1['state'];
export type WorkDocumentListV1 = GeneratedWorkDocumentListV1;
export type WorkDocumentDetailV1 = GeneratedWorkDocumentDetailV1;
export type WorkDocumentReceiptV1 = GeneratedWorkDocumentReceiptV1;
export type WorkDocumentCommandV1 = GeneratedWorkDocumentCommandV1;

export type WorkDocumentErasePreviewV1 = WorkDocumentCommandV1 & {
  operation: 'erase-preview';
  document: WorkDocumentV1;
  approval: {
    approvalId: string;
    [key: string]: unknown;
  };
  payloadSha256: string;
};
