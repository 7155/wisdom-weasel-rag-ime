/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/workspace-lsp-status.v1.json
 */

export interface WorkspaceLspStatusV1 {
  schemaVersion: 'rag-ime.workspace-lsp-status.v1';
  runtimeInstanceId: string;
  runtimeEpoch: number;
  observedAtMs: number;
  heartbeatExpiresAtMs: number;
  current: boolean;
  summary: string;
  state: 'ready' | 'available' | 'degraded' | 'unavailable';
  /**
   * @maxItems 64
   */
  roots: {
    root: string;
    state: 'ready' | 'available' | 'degraded' | 'unavailable';
    errorCode?: string;
    error?: string;
    /**
     * @maxItems 32
     */
    servers: {
      name: string;
      state: 'ready' | 'available' | 'degraded' | 'unavailable';
      /**
       * @maxItems 32
       */
      languageIds: string[];
      /**
       * @maxItems 64
       */
      fileExtensions: string[];
      errorCode?: string;
      error?: string;
    }[];
  }[];
}
