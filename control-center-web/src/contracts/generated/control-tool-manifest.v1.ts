/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/control-tool-manifest.v1.json
 */

export interface ControlToolManifestV1 {
  schemaVersion: 'rag-ime.control-tool-manifest.v1';
  id: string;
  domain: string;
  displayName: string;
  description: string;
  category:
    | 'overview'
    | 'input'
    | 'voice'
    | 'planning'
    | 'memory'
    | 'knowledge'
    | 'models'
    | 'runtime'
    | 'configuration'
    | 'agents'
    | 'browser'
    | 'desktop'
    | 'workspace';
  riskLevel: 'R0' | 'R1' | 'R2' | 'R3';
  operationRisks?: {
    [k: string]: 'R0' | 'R1' | 'R2' | 'R3';
  };
  sessionModes: ('assistant' | 'coordinator')[];
  operations: string[];
  resultPresentation:
    'status' | 'table' | 'citation' | 'tool_result' | 'diff' | 'approval' | 'terminal' | 'media';
  availability: 'online' | 'offline' | 'disabled' | 'unconfigured';
  version: string;
  alwaysAvailable?: boolean;
  [k: string]: unknown;
}
