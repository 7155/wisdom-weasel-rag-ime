/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-binding.v2.json
 */

export interface RoomBindingV2 {
  schemaVersion: 'wisdom-weasel.room-binding.v2';
  bindingId: string;
  rootId: string;
  roomId: string;
  participantId: string;
  taskId: string | null;
  generation: number;
  protocolRevision: string;
  capabilityRevision: string;
  access: 'read' | 'write';
}
