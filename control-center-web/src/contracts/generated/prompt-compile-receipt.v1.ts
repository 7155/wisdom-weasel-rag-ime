/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/prompt-compile-receipt.v1.json
 */

export interface PromptCompileReceiptV1 {
  schemaVersion: 'wisdom-weasel.prompt-compile-receipt.v1';
  receiptId: string;
  plan: {
    [k: string]: unknown;
  };
  omittedLayers: string[];
  producerAudit: {
    [k: string]: unknown;
  }[];
  createdAtMs: number;
}
