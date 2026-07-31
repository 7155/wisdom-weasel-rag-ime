/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/workspace-lsp-result.v1.json
 */

export interface WorkspaceLspResultV1 {
  schemaVersion: 'rag-ime.workspace-lsp-result.v1';
  summary: string;
  operation: 'symbols' | 'hover' | 'definition' | 'references' | 'diagnostics';
  root: string;
  server: string;
  /**
   * @maxItems 200
   */
  items?: {
    [k: string]: unknown;
  }[];
  content?: string;
  range?: {
    line: number;
    column: number;
    endLine: number;
    endColumn: number;
  } | null;
  truncated?: boolean;
}
