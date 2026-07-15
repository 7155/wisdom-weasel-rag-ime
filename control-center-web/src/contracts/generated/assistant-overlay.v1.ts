/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/assistant-overlay.v1.json
 */

export interface AssistantOverlayV1 {
  schemaVersion: 'rag-ime.assistant-overlay.v1';
  visible: boolean;
  uiMode: string;
  phase: string;
  inputMode: string;
  statusText?: string;
  snapshotId?: string;
  sessionFingerprint?: string;
  expiresAfterMs?: number;
  candidates: Candidate[];
  sourceCards?: unknown[];
  keyPolicy: {
    [k: string]: unknown;
  };
  overlayConfig?: {
    [k: string]: unknown;
  };
  progressive?: {
    [k: string]: unknown;
  };
  frontendTransaction: {
    [k: string]: unknown;
  };
  dismissReason?: string;
  [k: string]: unknown;
}
export interface Candidate {
  text?: string;
  insertText: string;
  sourceType: 'model' | 'rag' | 'memory' | 'action';
  candidateStableId?: string;
  snapshotId?: string;
  selectionAction?: string;
  sourceBadge?: string;
  memoryId?: string;
  suggestionId?: string;
  sourceEventId?: number | null;
  metadata?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
