/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/overlay-config.v1.json
 */

export interface OverlayConfigV1 {
  schemaVersion: 'rag-ime.overlay-config.v1';
  candidateFontSize: number;
  maxWidth: number;
  fadeAnimation: boolean;
  panelStyle: 'compact' | 'expanded';
  expiresAfterMs: number;
  maxCandidates: number;
  showSourceBadge: boolean;
  badges: {
    [k: string]: string;
  };
  colors: {
    [k: string]: string;
  };
  keyPolicy: {
    [k: string]: unknown;
  };
  activeRag: {
    enabled: boolean;
    shortcut: string;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
