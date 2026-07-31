/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-goal-mutation.v1.json
 */

export type AgentGoalMutationV1 = {
  [k: string]: unknown;
} & {
  action: 'confirm_setup' | 'update' | 'pause' | 'resume' | 'complete' | 'cancel' | 'clear';
  expectedRevision: number;
  confirmed?: true;
  objective?: string;
  successCriteria?: string;
  /**
   * @maxItems 20
   */
  evidenceExpectations?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  tokenBudget?: number | null;
  timeBudgetMs?: number | null;
  summary?: string;
  reason?: string;
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
};
