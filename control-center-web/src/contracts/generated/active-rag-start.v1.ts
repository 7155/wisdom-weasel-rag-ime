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
  visualContext?: {
    schemaVersion: 'rag-ime.visual-context.v1';
    mimeType: 'image/jpeg' | 'image/png';
    dataBase64: string;
    pixelWidth: number;
    pixelHeight: number;
    source: string;
  };
  [k: string]: unknown;
}
