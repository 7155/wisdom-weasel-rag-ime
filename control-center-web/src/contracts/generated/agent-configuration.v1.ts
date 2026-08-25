/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-configuration.v1.json
 */

export interface AgentConfigurationV1 {
  schemaVersion: 'rag-ime.agent-configuration.v1';
  revision: number;
  revisionToken: string;
  configuration: {
    runtime: {
      enabled: boolean;
      startup: 'lazy';
      idleTimeoutSeconds: number;
      [k: string]: unknown;
    };
    sessionDefaults: {
      resumeLastSession: boolean;
      roleId: string;
      roleVersion: string;
      toolProfileVersion: string;
      capabilityDisclosurePreferences: {
        [k: string]: 'inherit' | 'enabled' | 'disabled';
      };
      [k: string]: unknown;
    };
    modelRouting: {
      sessionModelProfile: string;
      sessionThinkingLevel: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
      roomPartnerModelProfile: string;
      roomPartnerThinkingLevel: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
      toolAgentModelProfile: string;
      toolAgentThinkingLevel: 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
      [k: string]: unknown;
    };
    coordination: {
      enabled: boolean;
      [k: string]: unknown;
    };
    capabilityDisclosure: {
      projectPreferences: {
        [k: string]: unknown;
      };
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
  sync: {
    state: 'synchronized' | 'pending' | 'failed';
    appliedRevision: number;
    error: string;
    [k: string]: unknown;
  };
  updatedAtMs: number;
  updatedBy: string;
  lastEventId: string;
  [k: string]: unknown;
}
