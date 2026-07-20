/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/compiled-agent-runtime-profile.v1.json
 */

export interface CompiledAgentRuntimeProfileV1 {
  schemaVersion: 'rag-ime.compiled-agent-runtime-profile.v1';
  compilerVersion: 'agent-definition-compiler-v1';
  personaRef: DefinitionRef;
  collaborationRoleRef: DefinitionRef;
  templateRef: DefinitionRef;
  collaborationProfileRef: DefinitionRef | null;
  /**
   * @maxItems 8
   */
  effectiveCapabilities:
    | []
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
   * @maxItems 8
   */
  rejectedCapabilities:
    | []
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
  capabilityRevision: string;
  promptPlanRevision: string;
  skillPolicyRevision: string;
  contextPolicyRevision: string;
  contentHash: string;
}
export interface DefinitionRef {
  kind: 'persona' | 'collaboration-role' | 'agent-template' | 'collaboration-profile';
  id: string;
  version: string;
  contentHash: string;
}
