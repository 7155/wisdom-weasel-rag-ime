/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lab-cost-request.v1.json
 */

export type Identity = string;
export type DecimalUsd = string;
export type Sha256 = string;
export type Usage = Usage1 & {
  available: true;
  uncachedInputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  sourceRef: EvidenceRef;
  sourceSha256: Sha256;
};
export type Usage1 =
  | {
      uncachedInputTokens?: {
        [k: string]: unknown;
      };
      [k: string]: unknown;
    }
  | {
      cachedInputTokens?: {
        [k: string]: unknown;
      };
      [k: string]: unknown;
    }
  | {
      outputTokens?: {
        [k: string]: unknown;
      };
      [k: string]: unknown;
    };
export type EvidenceRef = string;

export interface AgentLabCostRequestV1 {
  schemaVersion: 'rag-ime.agent-lab-cost-request.v1';
  pricingIdentity: PricingIdentity;
  usage: Usage;
  billedReceipt?: BilledReceipt;
}
export interface PricingIdentity {
  pricingId: Identity;
  provider: Identity;
  model: Identity;
  currency: 'USD';
  unit: 'per_million_tokens';
  rates: Rates;
  publishedDate: string;
  sourceUrl: string;
  sourceSha256: Sha256;
}
export interface Rates {
  uncachedInputUsd: DecimalUsd;
  cachedInputUsd: DecimalUsd;
  outputUsd: DecimalUsd;
}
export interface BilledReceipt {
  currency: 'USD';
  totalUsd: DecimalUsd;
  receiptRef: EvidenceRef;
  receiptSha256: Sha256;
}
