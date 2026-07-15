/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/management-work-error.v1.json
 */

export interface ManagementWorkErrorV1 {
  schemaVersion: 'rag-ime.management-work-error.v1';
  ok: false;
  errorCode:
    | 'confirmation_mismatch'
    | 'domain_not_applicable'
    | 'domain_not_found'
    | 'domain_rejected'
    | 'domain_scope_mismatch'
    | 'invalid_payload'
    | 'invalid_request'
    | 'payload_hash_mismatch'
    | 'payload_too_large'
    | 'preview_already_used'
    | 'preview_expired'
    | 'preview_not_found'
    | 'preview_path_mismatch'
    | 'receipt_already_rolled_back'
    | 'receipt_not_found'
    | 'receipt_path_mismatch'
    | 'revision_mismatch'
    | 'rollback_authority_mismatch'
    | 'rollback_path_mismatch'
    | 'rollback_state_changed'
    | 'rollback_token_mismatch'
    | 'rollback_unavailable'
    | 'stored_contract_invalid'
    | 'unsupported_backend'
    | 'unsupported_mutation';
  error: string;
  currentRevision: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
