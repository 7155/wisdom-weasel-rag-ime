/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/session-recall-effect-receipt.v1.json
 */

export interface SessionRecallEffectReceiptV1 {
  schemaVersion: 'rag-ime.session-recall-effect-receipt.v1';
  fixtureSha256: string;
  /**
   * @minItems 5
   */
  candidateWeights: [
    {
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    },
    {
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    },
    {
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    },
    {
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    },
    {
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    },
    ...{
      queryWeight: number;
      summaryWeight: number;
      score: number;
      metrics: {
        factHit: number;
        preferenceHit: number;
        projectHit: number;
        taskHit: number;
        irrelevantInjection: number;
        crossScopeLeak: number;
        duplicateBytes: number;
        tokenBytes: number;
        compactionForgettingRecovery: number;
        wrongOldTopic: number;
      };
      selections: {
        caseId: string;
        selected: string[];
        fusion: {
          applied: boolean;
          queryWeight: number;
          contextWeight: number;
        };
      }[];
    }[],
  ];
  selected: {
    queryWeight: number;
    summaryWeight: number;
    reason: string;
  };
}
