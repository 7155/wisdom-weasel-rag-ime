import type {
  ExternalActionRequest,
  FilePickOptions,
} from './transport';

export type NativeBridgeMethod =
  | 'capabilities'
  | 'request'
  | 'subscribe'
  | 'cancelSubscription'
  | 'pickFiles'
  | 'revealPath'
  | 'runApprovedExternalAction';

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

export type NativeBridgeOutboundEnvelope =
  | NativeBridgeResponseEnvelope
  | NativeBridgeSubscriptionEventEnvelope;

export interface RagImeNativeBridgeReceiver {
  receive(envelope: NativeBridgeOutboundEnvelope): void;
}

export interface RagImeNativeMessageHandler {
  postMessage(envelope: NativeBridgeRequestEnvelope): void;
}

export interface NativePickFilesPayload extends FilePickOptions {}
export interface NativeRevealPathPayload {
  path: string;
}
export interface NativeExternalActionPayload extends ExternalActionRequest {}

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
