/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/requirement-anchor.v1.json
 */

export interface RequirementAnchorV1 {
  schemaVersion: 'wisdom-weasel.requirement-anchor.v1';
  anchorId: string;
  rootId: string;
  rootSequence: number;
  originalContentSha256: string;
  originalByteLength: number;
  createdBy: string;
  authenticity: 'original_user_bytes' | 'legacy_quarantined';
  provenance: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
