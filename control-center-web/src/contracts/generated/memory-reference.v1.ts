/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-reference.v1.json
 */

export type ReferenceKind =
  'event' | 'evidence' | 'atom' | 'book' | 'timeline' | 'role_book_revision';

export interface MemoryReferenceV1 {
  schemaVersion: 'rag-ime.memory-reference.v1';
  settingsRevision: string;
  runtimeRevision: number;
  ok: true;
  kind: ReferenceKind;
  referenceId: string;
  item: {
    id: string;
    title: string;
    status: string;
    text?: string;
    textPreview?: string;
    summary?: string;
    detail?: string;
    sensitive?: boolean;
    ownerKind?: string;
    ownerId?: string;
    createdAtMs?: number;
    updatedAtMs?: number;
    occurredAtMs?: number;
    sourceContextAvailable?: boolean;
    sourceContext?: {
      recentContext: string;
      preedit: string;
      redacted: boolean;
      scopeProject: string;
      usedFor: ('source_fingerprint' | 'semantic_grouping')[];
    };
    [k: string]: unknown;
  };
  source: Source;
  ref: Reference;
  /**
   * @maxItems 80
   */
  evidenceRefs: Reference[];
}
export interface Source {
  kind: string;
  sourceKind?: string;
  id: string;
}
export interface Reference {
  kind: ReferenceKind;
  id: string;
  referenceKind: ReferenceKind;
  referenceId: string;
  label?: string;
}
