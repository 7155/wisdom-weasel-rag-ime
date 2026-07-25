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
    modelProfile?: string;
    thinkingLevel?: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
  };
  runtimeCharacteristics: {
    intelligence: string;
    speed: string;
    context: string;
    /**
     * @minItems 1
     * @maxItems 6
     */
    suitableTasks:
      | [string]
      | [string, string]
      | [string, string, string]
      | [string, string, string, string]
      | [string, string, string, string, string]
      | [string, string, string, string, string, string];
    /**
     * @minItems 1
     * @maxItems 6
     */
    unsuitableTasks:
      | [string]
      | [string, string]
      | [string, string, string]
      | [string, string, string, string]
      | [string, string, string, string, string]
      | [string, string, string, string, string, string];
    isDefault: boolean;
  };
  safetyPolicyVersion: 'agent-core-v2';
  /**
   * @minItems 1
   * @maxItems 2
   */
  selectableModes:
    ['assistant' | 'coordinator'] | ['assistant' | 'coordinator', 'assistant' | 'coordinator'];
}
