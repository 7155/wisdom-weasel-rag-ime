/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-thinking-selection.v1.json
 */

export interface AgentThinkingSelectionV1 {
  schemaVersion: 'rag-ime.agent-thinking-selection.v1';
  ok: true;
  sessionId: string;
  thinkingLevel: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
  selected: {
    [k: string]: unknown;
  } | null;
}
