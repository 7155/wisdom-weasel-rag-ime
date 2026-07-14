/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/foreground-context.v2.json
 */

export interface ForegroundContextV2 {
  available: boolean;
  source: string;
  freshnessMs: number;
  capturedAtMs?: number;
  surroundingBefore?: string;
  surroundingAfter?: string;
  selectedText?: string;
  selectedTextHash?: string;
  canReplaceSelection: boolean;
  contextGroupId?: string;
  contextGroupLevel?: 'document' | 'project' | 'app' | 'global' | '';
  [k: string]: unknown;
}
