/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/workspace-lsp-mutation-receipt.v1.json
 */

export interface WorkspaceLspMutationReceiptV1 {
  schemaVersion: 'rag-ime.workspace-lsp-mutation-receipt.v1';
  mutationApplied: true;
  summary: string;
  operation: 'rename' | 'code_action_apply';
  root: string;
  server: string;
  referencesEvidence?: {
    root: string;
    path: string;
    relativePath: string;
    line: number;
    column: number;
    server: string;
    resourceRevision: string;
    preimageSha256: string;
    count: number;
    truncated: boolean;
    /**
     * @maxItems 64
     */
    items: {
      path: string;
      relativePath: string;
      line: number;
      column: number;
      endLine: number;
      endColumn: number;
    }[];
  };
  /**
   * @minItems 1
   * @maxItems 16
   */
  changedFiles:
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ]
    | [
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
        {
          path: string;
          preimageSha256: string;
          postimageSha256: string;
        },
      ];
  undoAvailable: false;
}
