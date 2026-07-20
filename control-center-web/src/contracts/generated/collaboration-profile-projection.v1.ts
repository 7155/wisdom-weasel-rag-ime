/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-profile-projection.v1.json
 */

export interface CollaborationProfileProjectionV1 {
  schemaVersion: 'rag-ime.collaboration-profile-projection.v1';
  profileId: string;
  routeHash: string;
  /**
   * @minItems 1
   * @maxItems 1
   */
  requiredReadScopes: ['agent.read'];
  /**
   * @minItems 2
   * @maxItems 2
   */
  requiredWriteScopes: ['agent.write' | 'agent.approve', 'agent.write' | 'agent.approve'];
  guardEpoch: number;
  normalAgentFallback: true;
  inspection: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 50
   */
  recentReceipts: {
    [k: string]: unknown;
  }[];
}
