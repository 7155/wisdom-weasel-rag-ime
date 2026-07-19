/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-profile-compile-receipt.v1.json
 */

/**
 * @maxItems 8
 */
export type Capabilities =
  | []
  | ['rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation']
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ]
  | [
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
      'rag' | 'memory' | 'planning' | 'review' | 'control' | 'delegation',
    ];

export interface CollaborationProfileCompileReceiptV1 {
  schemaVersion: 'rag-ime.collaboration-profile-compile-receipt.v1';
  receiptId: string;
  contentHash: string;
  compilerVersion: 'collaboration-profile-compiler-v1';
  bindingRevision: string;
  baselineCapabilities: Capabilities;
  requestedCapabilities: Capabilities;
  effectiveCapabilities: Capabilities;
  rejectedCapabilities: Capabilities;
  createdAtMs: number;
}
