/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-control-bootstrap.v1.json
 */

export interface AgentControlBootstrapV1 {
  schemaVersion: 'rag-ime.agent-control-bootstrap.v1';
  apiVersion: 'control-api.v1';
  configuration: {
    [k: string]: unknown;
  };
  runtime: {
    [k: string]: unknown;
  };
  capabilities: {
    schemaVersion: 'rag-ime.control-capability-list.v1';
    items: unknown[];
    [k: string]: unknown;
  };
  platform: {
    [k: string]: unknown;
  };
  routes: {
    pathId: string;
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
    remoteSafe: boolean;
    subscription: boolean;
    params: string[];
    query: string[];
    remoteScopes?: string[];
    remoteQuery?: string[];
    target: {
      '8766': string;
      '8768': string | null;
      [k: string]: unknown;
    };
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
