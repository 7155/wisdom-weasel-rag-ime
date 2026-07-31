/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-plan-mutation.v1.json
 */

export type AgentPlanMutationV1 = {
  [k: string]: unknown;
} & {
  action:
    'save' | 'submit_review' | 'approve' | 'return_to_draft' | 'complete' | 'cancel' | 'reset';
  expectedRevision?: number;
  title?: string;
  note?: string;
  /**
   * @maxItems 100
   */
  items?: {
    id?: string;
    title: string;
    status: 'pending' | 'in_progress' | 'completed';
  }[];
};
