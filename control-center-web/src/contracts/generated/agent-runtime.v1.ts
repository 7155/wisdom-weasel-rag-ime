/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-runtime.v1.json
 */

export interface AgentRuntimeV1 {
  schemaVersion: 'rag-ime.agent-runtime.v1';
  enabled: boolean;
  managed: boolean;
  status:
    | 'disabled'
    | 'not_installed'
    | 'needs_configuration'
    | 'stopped'
    | 'starting'
    | 'ready'
    | 'busy'
    | 'faulted';
  driverId?: string;
  runtimeKind?: string;
  runtimeVersion?: string;
  piVersion: string;
  idleTimeoutSeconds: number;
  activeSessionId?: string | null;
  lastError?: string;
  capabilities: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
