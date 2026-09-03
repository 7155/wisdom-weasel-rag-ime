/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-permission-policy.v1.json
 */

export interface RoomPermissionPolicyV1 {
  schemaVersion: 'rag-ime.room-permission-policy.v1';
  room: RoomPermissionLayer;
  partner: RoomPermissionLowerLayer;
  toolAgent: RoomPermissionLowerLayer;
}
export interface RoomPermissionLayer {
  executionMode: 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
}
export interface RoomPermissionLowerLayer {
  executionMode: 'inherit' | 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
}
