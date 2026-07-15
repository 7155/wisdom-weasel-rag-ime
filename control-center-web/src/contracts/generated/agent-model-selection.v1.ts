/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-model-selection.v1.json
 */

export interface AgentModelSelectionV1 {
  schemaVersion: 'rag-ime.agent-model-selection.v1';
  ok: true;
  sessionId: string;
  selected: {
    provider: string;
    id: string;
    name: string;
    api: string;
    reasoning: boolean;
    /**
     * @minItems 1
     */
    thinkingLevels: [
      'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max',
      ...('off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max')[],
    ];
    supportsImages: boolean;
    contextWindow: number;
    maxTokens: number;
  };
  session: {
    schemaVersion: 'rag-ime.agent-session.v1';
    id: string;
    modelProfile: string;
    [k: string]: unknown;
  };
}
