/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/requirement-catalog-revision.v1.json
 */

export interface RequirementCatalogRevisionV1 {
  schemaVersion: 'wisdom-weasel.requirement-catalog-revision.v1';
  catalogRevisionId: string;
  rootId: string;
  revision: number;
  supersedesRevisionId: string | null;
  /**
   * @minItems 1
   */
  anchorRefs: [string, ...string[]];
  items: {
    [k: string]: unknown;
  }[];
  acceptanceCriteria: {
    [k: string]: unknown;
  }[];
  changeReason: string;
  provenance: {
    [k: string]: unknown;
  };
  payloadHash: string;
  createdBy: string;
  createdAtMs: number;
}
