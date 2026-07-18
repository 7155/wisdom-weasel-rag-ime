/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-role-routing-profile.v1.json
 */

export interface AgentRoleRoutingProfileV1 {
  schemaVersion: 'rag-ime.agent-role-routing-profile.v1';
  roleId: string;
  roleVersion: string;
  revisionId: string;
  revisionNumber: number;
  advisoryOnly: boolean;
  personality: RoutingItem[];
  capabilities: RoutingItem[];
  recentWork: RoutingItem[];
  activeCommitments: RoutingItem[];
  lessonsAndLimits: RoutingItem[];
}
export interface RoutingItem {
  itemId: string;
  text: string;
  expiresAtMs?: number;
  provenance: {
    sourceType: string;
    sourceId: string;
    observedAtMs?: number | null;
    [k: string]: unknown;
  };
  evidenceIds: string[];
}
