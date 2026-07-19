/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-conversation-context.v1.json
 */

export interface AgentConversationContextV1 {
  schemaVersion: 'rag-ime.agent-conversation-context.v1';
  available: boolean;
  date: string;
  /**
   * @maxItems 24
   */
  messages: {
    role: 'user' | 'assistant';
    sourceKind: 'user_message' | 'assistant_message' | 'room_event' | 'session_digest';
    text: string;
    occurredAtMs: number;
  }[];
  messageCount: number;
  deduplicatedMessageCount: number;
  redactedMessageCount: number;
  corroborationOnly: true;
  maySupportFacts: false;
}
