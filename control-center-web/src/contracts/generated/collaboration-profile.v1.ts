/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-profile.v1.json
 */

export interface CollaborationProfileV1 {
  schemaVersion: 'rag-ime.collaboration-profile.v1';
  profileId: string;
  version: string;
  displayName: string;
  summary: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  collaborationRoleRefs:
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
      ];
  /**
   * @minItems 1
   * @maxItems 8
   */
  capabilityRequests:
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
  /**
   * @minItems 1
   * @maxItems 16
   */
  requiredGateIds:
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
      ];
  /**
   * @minItems 1
   * @maxItems 12
   */
  promptGuidance:
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
      ];
  trustTier: 'builtin' | 'signed' | 'local-untrusted';
}
