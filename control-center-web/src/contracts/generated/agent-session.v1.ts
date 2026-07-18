/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-session.v1.json
 */

export interface AgentSessionV1 {
  schemaVersion: 'rag-ime.agent-session.v1';
  id: string;
  piSessionId?: string;
  sessionFile?: string;
  runtimeBinding?: {
    schemaVersion: 'rag-ime.agent-runtime-binding.v1';
    driverId: string;
    runtimeKind: string;
    generation: number;
    state: 'prepared' | 'active' | 'stale';
    createdAtMs: number;
    updatedAtMs: number;
    [k: string]: unknown;
  };
  title: string;
  mode: 'assistant' | 'coordinator';
  status: 'idle' | 'active' | 'busy' | 'faulted' | 'archived';
  sessionKind?: 'conversation' | 'subagent_runtime';
  roleId: string;
  roleVersion: string;
  roleBookRevisionId: string;
  modelProfile: string;
  thinkingLevel?: '' | 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
  toolProfileVersion: string;
  toolAllowlistMode?: 'profile' | 'explicit';
  allowedTools?: string[];
  projectContextEnabled: boolean;
  piSkillsEnabled: boolean;
  codexSkillsEnabled: boolean;
  createdAtMs: number;
  updatedAtMs: number;
  lastOpenedAtMs?: number;
  archivedAtMs?: number | null;
  messageCount: number;
  lastMessagePreview?: string;
  workspaceRoots: string[];
  shellPolicyVersion?: string;
  [k: string]: unknown;
}
