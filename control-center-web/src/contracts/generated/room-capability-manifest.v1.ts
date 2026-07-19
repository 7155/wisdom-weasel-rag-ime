/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-capability-manifest.v1.json
 */

export interface RoomCapabilityManifestV1 {
  schemaVersion: 'wisdom-weasel.room-capability-manifest.v1';
  manifestId: string;
  bindingId: string;
  roomId: string;
  rootId: string;
  taskId: string;
  dispatchId: string;
  generation: number;
  capabilityRevision: string;
  capabilityEpoch: number;
  tools: {
    [k: string]: unknown;
  }[];
  manifestHash: string;
  createdAtMs: number;
}
