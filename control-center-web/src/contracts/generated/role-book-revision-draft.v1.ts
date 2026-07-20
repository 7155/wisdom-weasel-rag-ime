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
    /**
     * @maxItems 6
     */
    traitProposals:
      | []
      | [Proposal]
      | [Proposal, Proposal]
      | [Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal];
    /**
     * @maxItems 12
     */
    capabilityProposals:
      | []
      | [Proposal]
      | [Proposal, Proposal]
      | [Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
        ]
      | [
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
        ]
      | [
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
          Proposal,
        ];
    /**
     * @maxItems 8
     */
    lessonProposals:
      | []
      | [Proposal]
      | [Proposal, Proposal]
      | [Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal];
    /**
     * @maxItems 8
     */
    commitmentProposals:
      | []
      | [Proposal]
      | [Proposal, Proposal]
      | [Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal]
      | [Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal, Proposal];
  };
  policy: {
    defaultApply: false;
    safeAutoApplyFields: 'recentWork'[];
    reviewRequiredFields: ('traits' | 'capabilities' | 'lessonsAndLimits' | 'activeCommitments')[];
  };
  proposalDiagnostics: {
    status:
      | 'not_configured'
      | 'no_conversation_evidence'
      | 'no_eligible_evidence'
      | 'unsupported'
      | 'completed'
      | 'failed';
    provider: string;
    inputChars: number;
    acceptedProposalCount: number;
    rejectedProposalCount: number;
    error?: string;
  };
  createdAtMs: number;
}
export interface Proposal {
  text: string;
  confidence: number;
  /**
   * @minItems 1
   * @maxItems 8
   */
  sourceEvidenceIds:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  reviewRequired: true;
}
