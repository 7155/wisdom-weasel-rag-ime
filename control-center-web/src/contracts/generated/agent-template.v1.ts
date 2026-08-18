/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-template.v1.json
 */

export interface AgentTemplateV1 {
  schemaVersion: 'rag-ime.agent-template.v1';
  templateId: 'researcher' | 'planner' | 'worker' | 'reviewer' | 'delegate';
  version: '1';
  displayName: string;
  summary: string;
  /**
   * @minItems 1
   * @maxItems 2
   */
  contextModes: ['fresh' | 'fork'] | ['fresh' | 'fork', 'fresh' | 'fork'];
  toolProfileVersion: 'subagent-readonly-v1' | 'subagent-worker-v1';
  defaultAccess: 'read_only' | 'write';
  /**
   * @minItems 1
   * @maxItems 2
   */
  allowedAccess: ['read_only' | 'write'] | ['read_only' | 'write', 'read_only' | 'write'];
  budget: {
    maxDepth: number;
    maxTurns: number;
    maxToolCalls: number;
    maxTotalTokens: number;
    maxDurationMs: number;
    maxOutputChars: number;
  };
  /**
   * @minItems 1
   * @maxItems 8
   */
  capabilities:
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
