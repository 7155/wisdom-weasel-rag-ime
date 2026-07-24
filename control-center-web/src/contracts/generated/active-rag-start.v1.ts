/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/active-rag-start.v1.json
 */

export interface ActiveRagStartV1 {
  selectedText?: string;
  selected_text?: string;
  selectedTextHash?: string;
  selected_text_hash?: string;
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
  isPasswordField?: boolean;
  credentialField?: boolean;
  app?: string;
  frontAppBundleId?: string;
  windowContext?: {
    schemaVersion: 'rag-ime.window-context.v1';
    captureMode: 'accessibility_semantics' | 'terminal_visible_range';
    snapshotId: string;
    revision: number;
    capturedAtMs?: number;
    privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
    application: {
      pid?: number;
      bundleId?: string;
      name?: string;
      windowTitle?: string;
    };
    focusedNodeRef?: string;
    /**
     * @maxItems 160
     */
    nodes: unknown[];
    nodeCount?: number;
    truncated?: boolean;
    semanticText?: string;
  };
  [k: string]: unknown;
}
