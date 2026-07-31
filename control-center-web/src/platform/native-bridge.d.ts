import type {
  ExternalActionRequest,
  FilePickOptions,
  VoiceCredentialSaveRequest,
  VoiceNativeActionId,
  VoiceProviderId,
} from './transport';

export type NativeBridgeMethod =
  | 'capabilities'
  | 'request'
  | 'subscribe'
  | 'cancelSubscription'
  | 'cancelRequest'
  | 'pickFiles'
  | 'pasteImages'
  | 'readKnowledgeAsset'
  | 'readKnowledgeDocumentSource'
  | 'revealPath'
  | 'runApprovedExternalAction'
  | 'voiceCredentialStatus'
  | 'voiceCredentialSave'
  | 'voiceAction';

export interface NativeBridgeRequestEnvelope {
  id: string;
  method: NativeBridgeMethod;
  payload: unknown;
}

export type NativeBridgeError =
  | string
  | {
      code?: string;
      message: string;
      details?: unknown;
      retryable?: boolean;
    };

export type NativeBridgeResponseEnvelope =
  | { id: string; ok: true; result: unknown }
  | { id: string; ok: false; error: NativeBridgeError };

export interface NativeBridgeSubscriptionEventEnvelope {
  subscriptionId: string;
  kind: 'event';
  event: unknown;
  lastEventId: string;
}

export interface NativeBridgeSubscriptionErrorEnvelope {
  subscriptionId: string;
  kind: 'error';
  error: NativeBridgeError;
}

export interface NativeBridgeSubscriptionCompleteEnvelope {
  subscriptionId: string;
  kind: 'complete';
  lastEventId: string;
}

export type NativeBridgeOutboundEnvelope =
  | NativeBridgeResponseEnvelope
  | NativeBridgeSubscriptionEventEnvelope
  | NativeBridgeSubscriptionErrorEnvelope
  | NativeBridgeSubscriptionCompleteEnvelope;

export interface RagImeNativeBridgeReceiver {
  receive(envelope: NativeBridgeOutboundEnvelope): void;
}

export interface RagImeNativeMessageHandler {
  postMessage(envelope: NativeBridgeRequestEnvelope): void;
}

export interface NativePickFilesPayload extends FilePickOptions {}
export type NativePasteImagesPayload = {
  maxFiles: number;
} & (
  | { sessionId: string; roomId?: never }
  | { roomId: string; sessionId?: never }
);
export interface NativeKnowledgeAssetPayload {
  kbId: string;
  fileId: string;
  assetId: string;
}
export interface NativeKnowledgeDocumentSourcePayload {
  kbId: string;
  fileId: string;
}
export interface NativeRevealPathPayload {
  path: string;
}
export interface NativeExternalActionPayload extends ExternalActionRequest {}
export interface NativeVoiceCredentialStatusPayload {
  provider: VoiceProviderId;
}
export interface NativeVoiceCredentialSavePayload extends VoiceCredentialSaveRequest {}
export interface NativeVoiceActionPayload {
  action: VoiceNativeActionId;
}

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        ragImeNativeBridge?: RagImeNativeMessageHandler;
      };
    };
    __RAG_IME_NATIVE_BRIDGE__?: RagImeNativeBridgeReceiver;
  }
}

export {};
