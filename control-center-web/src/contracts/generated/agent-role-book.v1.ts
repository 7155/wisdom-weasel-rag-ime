/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-role-book.v1.json
 */

export interface AgentRoleBookV1 {
  schemaVersion: 'rag-ime.agent-role-book.v1';
  revisionId: string;
  roleId: string;
  roleVersion: string;
  revisionNumber: number;
  status: 'draft' | 'active' | 'superseded' | 'rolled_back';
  displayName: string;
  mission: string;
  basePersonaVersion: string;
  sections: Sections;
  sourceRevisionId: string;
  changeSummary: string;
  proposedBy: string;
  createdAtMs: number;
  activatedAtMs: number | null;
  supersededAtMs: number | null;
  rolledBackAtMs: number | null;
}
export interface Sections {
  /**
   * @maxItems 6
   */
  personality:
    | []
    | [Item]
    | [Item, Item]
    | [Item, Item, Item]
    | [Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item];
  /**
   * @maxItems 12
   */
  capabilities:
    | []
    | [Item]
    | [Item, Item]
    | [Item, Item, Item]
    | [Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item, Item, Item, Item, Item];
  /**
   * @maxItems 8
   */
  recentWork:
    | []
    | [Item]
    | [Item, Item]
    | [Item, Item, Item]
    | [Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item];
  /**
   * @maxItems 8
   */
  lessonsAndLimits:
    | []
    | [Item]
    | [Item, Item]
    | [Item, Item, Item]
    | [Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item];
  /**
   * @maxItems 8
   */
  activeCommitments:
    | []
    | [Item]
    | [Item, Item]
    | [Item, Item, Item]
    | [Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item]
    | [Item, Item, Item, Item, Item, Item, Item, Item];
}
export interface Item {
  itemId: string;
  text: string;
  provenance: Provenance;
  expiresAtMs?: number;
  /**
   * @minItems 1
   * @maxItems 16
   */
  evidenceIds:
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
export interface Provenance {
  sourceType: string;
  sourceId: string;
  observedAtMs?: number | null;
}
