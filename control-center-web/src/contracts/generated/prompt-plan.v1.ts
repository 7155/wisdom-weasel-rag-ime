/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/prompt-plan.v1.json
 */

export interface PromptPlanV1 {
  schemaVersion: 'wisdom-weasel.prompt-plan.v1';
  bindingId: string;
  roomId: string;
  rootId: string;
  sessionId: string;
  journalId: string;
  generation: number;
  sessionEpoch: number;
  contextEpoch: number;
  capabilityRevision: string;
  capabilityEpoch: number;
  skillPolicyRevision: string;
  contextPolicyRevision: string;
  /**
   * @minItems 6
   * @maxItems 6
   */
  layers: [
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
    {
      [k: string]: unknown;
    },
    {
      [k: string]: unknown;
    },
  ];
  stablePrefixHash: string;
  projectionHash: string;
  throughSequence: number;
  sealedProjectionRefs: string[];
  dynamicTailRefs: string[];
  planHash: string;
}
