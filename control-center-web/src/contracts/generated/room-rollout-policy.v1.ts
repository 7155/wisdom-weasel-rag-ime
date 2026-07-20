/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-rollout-policy.v1.json
 */

export interface RoomRolloutPolicyV1 {
  schemaVersion: 'wisdom-weasel.room-rollout-policy.v1';
  policyId: string;
  previousPolicyId?: string | null;
  stage: 'off' | 'shadow' | 'named_canary' | 'production_cohort' | 'kernel_only';
  cohortId: string;
  readinessHash: string;
  rollbackTarget: 'off' | 'shadow' | 'named_canary' | 'production_cohort' | 'kernel_only';
  adminRef: string;
  approvalSignature: string;
  createdAtMs: number;
}
