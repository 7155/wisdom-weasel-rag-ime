/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-role.v1.json
 */

export interface CollaborationRoleV1 {
  schemaVersion: 'rag-ime.collaboration-role.v1';
  roleId: 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';
  version: '1';
  displayName: string;
  summary: string;
  /**
   * @minItems 1
   * @maxItems 8
   */
  responsibilities:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  /**
   * @minItems 1
   * @maxItems 8
   */
  entryConditions:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  /**
   * @minItems 1
   * @maxItems 8
   */
  exitConditions:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  /**
   * @minItems 1
   * @maxItems 4
   */
  allowedCommitDecisions:
    | ['deliver' | 'handoff' | 'wait' | 'blocked']
    | ['deliver' | 'handoff' | 'wait' | 'blocked', 'deliver' | 'handoff' | 'wait' | 'blocked']
    | [
        'deliver' | 'handoff' | 'wait' | 'blocked',
        'deliver' | 'handoff' | 'wait' | 'blocked',
        'deliver' | 'handoff' | 'wait' | 'blocked',
      ]
    | [
        'deliver' | 'handoff' | 'wait' | 'blocked',
        'deliver' | 'handoff' | 'wait' | 'blocked',
        'deliver' | 'handoff' | 'wait' | 'blocked',
        'deliver' | 'handoff' | 'wait' | 'blocked',
      ];
  /**
   * @minItems 1
   * @maxItems 8
   */
  capabilityRestrictions:
    | ['rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation']
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ]
    | [
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
        'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      ];
}
