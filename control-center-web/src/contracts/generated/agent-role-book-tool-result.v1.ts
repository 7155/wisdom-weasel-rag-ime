/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-role-book-tool-result.v1.json
 */

export interface AgentRoleBookToolResultV1 {
  schemaVersion: 'rag-ime.agent-role-book-tool-result.v1';
  operation: 'get' | 'history' | 'propose_revision' | 'review';
  roleId: string;
  roleVersion: string;
  summary: string;
  activeRevisionChanged: false;
  result: {
    [k: string]: unknown;
  };
}
