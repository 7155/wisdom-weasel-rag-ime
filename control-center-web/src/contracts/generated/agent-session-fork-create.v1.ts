/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-session-fork-create.v1.json
 */

export interface AgentSessionForkCreateV1 {
  schemaVersion: 'rag-ime.agent-session-fork-create.v1';
  ok: true;
  sourceSessionId: string;
  entryId: string;
  selectedText: string;
  session: Session;
}
export interface Session {
  schemaVersion: 'rag-ime.agent-session.v1';
  id: string;
  title: string;
  mode: 'assistant' | 'coordinator';
  status: 'idle' | 'active' | 'busy' | 'faulted' | 'archived';
  roleId: string;
  roleVersion: string;
  roleBookRevisionId: string;
  modelProfile: string;
  toolProfileVersion: string;
  projectContextEnabled: boolean;
  piSkillsEnabled: boolean;
  codexSkillsEnabled: boolean;
  createdAtMs: number;
  updatedAtMs: number;
  messageCount: number;
  workspaceRoots: string[];
  [k: string]: unknown;
}
