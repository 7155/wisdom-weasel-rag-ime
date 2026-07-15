/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-catalog.v1.json
 */

export interface MemoryCatalogV1 {
  schemaVersion: 'rag-ime.memory-catalog.v1';
  project: string;
  catalogVersion: string;
  items: Item[];
  [k: string]: unknown;
}
export interface Item {
  bookId: string;
  bookKey: string;
  bookType: 'daily' | 'topic' | 'project' | 'session';
  title: string;
  summary: string;
  updatedAtMs: number;
  sourceCount: number;
  status: 'active' | 'archived';
  [k: string]: unknown;
}
