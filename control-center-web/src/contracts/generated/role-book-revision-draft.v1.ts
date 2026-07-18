/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/role-book-revision-draft.v1.json
 */

export interface RoleBookRevisionDraftV1 {
  schemaVersion: 'rag-ime.role-book-revision-draft.v1';
  draftId: string;
  status: 'draft';
  project: string;
  roleId: string;
  baseRoleVersion: string;
  sourceDigestId: string;
  sourceEvidenceIds: string[];
  patch: {
    recentWork: {
      [k: string]: unknown;
    }[];
    traitProposals: {
      [k: string]: unknown;
    }[];
    capabilityProposals: {
      [k: string]: unknown;
    }[];
    [k: string]: unknown;
  };
  policy: {
    defaultApply: false;
    safeAutoApplyFields: 'recentWork'[];
    reviewRequiredFields: ('traits' | 'capabilities')[];
    [k: string]: unknown;
  };
  createdAtMs: number;
}
