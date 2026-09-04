/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lab-cost-receipt.v1.json
 */

export type AgentLabCostReceiptV1 = {
  [k: string]: unknown;
} & {
  schemaVersion: 'rag-ime.agent-lab-cost-receipt.v1';
  authority: 'pricing_estimate' | 'pricing_lower_bound' | 'runtime_cost_reconciled';
  pricingIdentity: PricingIdentity;
  usage: Usage;
  runtimeCostReceipt?: RuntimeCostReceipt;
  pricingLowerBound?: PricingLowerBound;
  estimate: Estimate;
  billing: Billing;
  /**
   * @minItems 2
   * @maxItems 8
   */
  boundaries:
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string];
  receiptSha256: Sha256;
};
export type Identity = string;
export type RateDecimalUsd = string;
export type Sha256 = string;
export type EvidenceRef = string;
export type AmountDecimalUsd = string;
export type Billing = BillingNotProvided | BillingProvided;

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
  uncachedInputUsd: RateDecimalUsd;
  cachedInputUsd: RateDecimalUsd;
  outputUsd: RateDecimalUsd;
}
export interface Usage {
  available: true;
  uncachedInputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  sourceRef: EvidenceRef;
  sourceSha256: Sha256;
}
export interface RuntimeCostReceipt {
  requestCount: number;
  runtimeDbSha256: Sha256;
  /**
   * @minItems 1
   * @maxItems 10000
   */
  transcriptSha256s: [Sha256, ...Sha256[]];
  databaseUsage: {
    uncachedInputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
  };
  trialAggregate?: TrialAggregate;
  reportedCostUsd: {
    input: AmountDecimalUsd;
    cacheRead: AmountDecimalUsd;
    output: AmountDecimalUsd;
    total: AmountDecimalUsd;
  };
  sourceSha256: Sha256;
}
export interface TrialAggregate {
  sourceRef: Identity;
  sourceSha256: Sha256;
  uncachedInputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
}
export interface PricingLowerBound {
  sourceSha256: Sha256;
  /**
   * @minItems 1
   * @maxItems 100
   */
  tiers: [
    {
      inputTokensAbove: number;
      rates: Rates;
    },
    ...{
      inputTokensAbove: number;
      rates: Rates;
    }[],
  ];
}
export interface Estimate {
  uncachedInputCostUsd: AmountDecimalUsd;
  cachedInputCostUsd: AmountDecimalUsd;
  outputCostUsd: AmountDecimalUsd;
  totalCostUsd: AmountDecimalUsd;
}
export interface BillingNotProvided {
  status: 'not_provided';
}
export interface BillingProvided {
  status: 'provided';
  currency: 'USD';
  totalUsd: AmountDecimalUsd;
  receiptRef: EvidenceRef;
  receiptSha256: Sha256;
}
