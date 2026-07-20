/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-profile-command.v1.json
 */

export interface CollaborationProfileCommandV1 {
  schemaVersion: 'rag-ime.collaboration-profile-command.v1';
  commandId: string;
  action:
    'inspect' | 'validate' | 'compile' | 'dry_run' | 'stage' | 'activate' | 'rollback' | 'revoke';
  idempotencyKey: string;
  actorRef: string;
  profileId?: string;
  candidateId?: string;
  contentHash?: string;
  expectedPointerRevision?: number;
  activationScope?: 'immediate' | 'new_roots_only';
  adminConfirmation?: string;
  payload: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
