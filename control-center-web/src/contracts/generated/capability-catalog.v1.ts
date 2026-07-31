/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/capability-catalog.v1.json
 */

export interface CapabilityCatalogV1 {
  schemaVersion: 'rag-ime.capability-catalog.v1';
  ok: true;
  revision: string;
  effectiveAtMs: number;
  projectScope:
    | {
        supported: true;
        identityKind: 'workspace_scope_sha256';
        projectId: string;
        reason: 'session_workspace_scope';
      }
    | {
        supported: false;
        identityKind: 'none';
        reason: 'stable_project_identity_unavailable';
      };
  sessionPolicy?: {
    sessionId: string;
    mode: 'assistant' | 'coordinator';
    executionMode: 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
    workspaceScopeGranted: boolean;
    toolProfileVersion: string;
    toolAllowlistMode: 'profile' | 'explicit';
    allowedTools: string[];
    policyRevision: number;
    effectiveAtMs: number;
    disclosurePreferences: {
      globalDefault: Preferences;
      projectDefault: Preferences;
      session: Preferences;
      effective: {
        [k: string]: 'enabled' | 'disabled';
      };
    };
  };
  items: {
    id: string;
    canonicalId: string;
    kind: 'tool' | 'skill' | 'extension';
    source: {
      kind: string;
      label: string;
      [k: string]: unknown;
    };
    status: string;
    risk: string;
    requiredPermissions: string[];
    authorization: {
      state: 'authorized' | 'denied' | 'not_applicable';
      reason: string;
    };
    disclosure: {
      preference: 'inherit' | 'enabled' | 'disabled';
      effective: 'enabled' | 'disabled';
      state: 'disclosed' | 'hidden';
      reason: string;
      scope: 'session' | 'project_default' | 'global_default' | 'built_in_default';
    };
    effectiveScope: 'session' | 'project_default' | 'global_default' | 'built_in_default';
    reasons: string[];
    revision: string;
    effectiveAtMs: number;
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
export interface Preferences {
  [k: string]: 'inherit' | 'enabled' | 'disabled';
}
