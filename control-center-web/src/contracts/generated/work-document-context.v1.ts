/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/work-document-context.v1.json
 */

export interface WorkDocumentContextV1 {
  schemaVersion: 'rag-ime.work-document-context.v1';
  /**
   * @maxItems 200
   */
  items: {
    documentId: string;
    title: string;
    path: string;
    contentSha256: string;
    authorityKey: string;
  }[];
}
