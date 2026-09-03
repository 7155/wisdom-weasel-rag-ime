/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-room-conversation-snapshot.v1.json
 */

export interface AgentRoomConversationSnapshotV1 {
  schemaVersion: 'rag-ime.agent-room-conversation-snapshot.v1';
  ok: true;
  room: {
    [k: string]: unknown;
  };
  /**
   * @maxItems 2000
   */
  events: {
    [k: string]: unknown;
  }[];
  firstEventSequence: number;
  cursorSequence: number;
  resumeToken: string;
  deferredEventCount: number;
  truncated: boolean;
}
