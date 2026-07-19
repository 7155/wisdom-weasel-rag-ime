/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-post.v2.json
 */

export interface RoomPostV2 {
  schemaVersion: 'wisdom-weasel.room-post.v2';
  postId: string;
  roomId: string;
  rootId: string;
  generation: number;
  taskId?: string;
  dispatchId?: string;
  authorActorRef: string;
  kind: string;
  visibility: 'room' | 'root';
  content: string;
  idempotencyKey: string;
  publicationSource: {
    kind: 'user' | 'room_commit';
    ref: string;
  };
  createdAtMs: number;
}
