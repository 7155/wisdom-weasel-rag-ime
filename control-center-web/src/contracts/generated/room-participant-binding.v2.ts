/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-participant-binding.v2.json
 */

export interface RoomParticipantBindingV2 {
  schemaVersion: 'wisdom-weasel.room-participant-binding.v2';
  bindingId: string;
  sessionId: string;
  /**
   * Canonical immutable definition reference: rag-ime-definition://{kind}/{percent-encoded-id}?version={version}&contentHash=sha256:{64 lowercase hex}
   */
  personaRef: string;
  /**
   * Canonical immutable definition reference: rag-ime-definition://{kind}/{percent-encoded-id}?version={version}&contentHash=sha256:{64 lowercase hex}
   */
  collaborationRoleRef: string;
  /**
   * Canonical immutable definition reference: rag-ime-definition://{kind}/{percent-encoded-id}?version={version}&contentHash=sha256:{64 lowercase hex}
   */
  agentTemplateRef: string;
  /**
   * Null, or canonical immutable definition reference: rag-ime-definition://{kind}/{percent-encoded-id}?version={version}&contentHash=sha256:{64 lowercase hex}
   */
  collaborationProfileRef: string | null;
  compiledRuntimeProfileRef: {
    profileId: string;
    revision: string;
    contentHash: string;
  };
  capabilityRevision: string;
  capabilityEpoch: number;
  roomBindingRef: {
    bindingId: string;
    schemaVersion: 'wisdom-weasel.room-binding.v2';
  } | null;
}
