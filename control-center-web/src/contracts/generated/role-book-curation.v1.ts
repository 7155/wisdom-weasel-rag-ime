/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/role-book-curation.v1.json
 */

export interface RoleBookCurationV1 {
  schemaVersion: 'rag-ime.role-book-curation.v1';
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
  /**
   * @maxItems 16
   */
  warnings:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
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
