/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/management-work-preview.v1.json
 */

export interface ManagementWorkPreviewV1 {
  schemaVersion: 'rag-ime.management-work-preview.v1';
  ok: true;
  previewToken: string;
  pathId: string;
  payloadSha256: string;
  expectedRevision: {
    [k: string]: unknown;
  };
  expiresAtMs: number;
  requiredConfirm: string;
  summary: {
    title: string;
    items: string[];
    risk: 'R1' | 'R2' | 'R3';
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
