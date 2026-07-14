/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room.v1.json
 */

export interface AgentRoomV1 {
  schemaVersion: 'rag-ime.agent-room.v1';
  id: string;
  title: string;
  status: 'active' | 'archived';
  routingPolicy: 'manual_mentions' | 'moderator';
  moderatorParticipantId: string;
  createdAtMs: number;
  updatedAtMs: number;
  lastEventSequence: number;
  /**
   * @minItems 2
   * @maxItems 4
   */
  participants:
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ];
}
