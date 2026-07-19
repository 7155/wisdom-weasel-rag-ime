/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-goal-mutation.v1.json
 */

export interface AgentGoalMutationV1 {
  action: 'set' | 'update' | 'pause' | 'resume' | 'complete' | 'clear';
  expectedRevision?: number;
  objective?: string;
  tokenBudget?: number | null;
  timeBudgetMs?: number | null;
  summary?: string;
  /**
   * @minItems 1
   * @maxItems 20
   */
  evidence?:
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ]
    | [
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
        {
          kind: 'test' | 'artifact' | 'commit' | 'receipt' | 'note';
          summary: string;
          reference: string;
        },
      ];
}
