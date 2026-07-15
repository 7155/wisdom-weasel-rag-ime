/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-persona.v1.json
 */

export interface AgentPersonaV1 {
  schemaVersion: 'rag-ime.agent-persona.v1';
  roleId: string;
  version: string;
  displayName: string;
  tagline: string;
  summary: string;
  /**
   * @minItems 1
   * @maxItems 5
   */
  traits:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string];
  visualProfile: {
    avatarAssetId: string;
    symbolName: string;
    accentToken: 'teal' | 'blue' | 'rose' | 'neutral';
  };
  defaults: {
    modelPolicy: string;
    memoryPolicy: string;
    toolProfileVersion: string;
  };
  safetyPolicyVersion: 'control-center-safe-v1';
  /**
   * @minItems 1
   * @maxItems 2
   */
  selectableModes:
    ['assistant' | 'coordinator'] | ['assistant' | 'coordinator', 'assistant' | 'coordinator'];
}
