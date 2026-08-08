/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/foreground-commit.v1.json
 */

export interface ForegroundCommitV1 {
  text: string;
  recentContext?: string;
  preedit?: string;
  project?: string;
  app?: string;
  frontAppBundleId?: string;
  frontmostApp?: string;
  bundleId?: string;
  candidateRank?: number | null;
  providerName?: string;
  tags?: string[];
  source?: string;
  contextGroupId?: string;
  contextGroupLevel?: string;
  captureMetadata?:
    | {
        captureSource?: string;
        fallbackReason?: string;
        fieldContextChars?: number;
        imeBufferChars?: number;
        selectedTextSha256?: string;
        selectionRule?: string;
      }
    | {
        schemaVersion: 'rag-ime.input-capture.v2';
        captureId: string;
        transactionId: string;
        sequence: number;
        channel: 'input_method' | 'voice';
        boundaryKind: 'host_return' | 'focus_change' | 'app_change' | 'deactivate' | 'voice_final';
        boundaryConfidence: 'strong' | 'weak';
        nativeCompositionBefore: boolean;
        rimeHandled: boolean;
        hostForwarded: boolean;
        modifiedReturn: boolean;
        finalCommitted: boolean;
        controllerEpoch: number;
        focusEpoch: number;
        appBundleId: string;
        fieldIdentitySha256: string;
        privacyRevision: string;
        occurredStartMs: number;
        occurredEndMs: number;
        contentSha256: string;
        captureSource:
          'text_input_client' | 'accessibility' | 'ime_active_buffer' | 'voice_insertion';
        fallbackReason: string;
        fieldContextChars: number;
        imeBufferChars: number;
        selectionRule: string;
      };
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
}
