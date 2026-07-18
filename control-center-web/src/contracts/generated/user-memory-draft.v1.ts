/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/user-memory-draft.v1.json
 */

export interface UserMemoryDraftV1 {
  schemaVersion: 'rag-ime.user-memory-draft.v1';
  draftId: string;
  status: 'review_required';
  project: string;
  roleId: string;
  sourceDigestId: string;
  sourceEvidenceIds: string[];
  candidates: {
    [k: string]: unknown;
  }[];
  policy: {
    rawDialoguePromotion: 'forbidden';
    defaultApply: false;
    [k: string]: unknown;
  };
  createdAtMs: number;
}
