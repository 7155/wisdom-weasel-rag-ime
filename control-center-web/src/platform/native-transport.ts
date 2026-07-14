import { parseAgentEvent, parseContract, parseRoomEvent } from '@/contracts/validators';

import {
  controlRoute,
  isControlPathId,
  type ControlPathId,
  type ControlStreamKind,
} from './routes';
import type {
  NativeBridgeError,
  NativeBridgeMethod,
  NativeBridgeOutboundEnvelope,
  NativeBridgeRequestEnvelope,
  RagImeNativeBridgeReceiver,
  RagImeNativeMessageHandler,
} from './native-bridge';
import {
  assertControlRequest,
  assertControlSubscription,
  controlRequestWirePayload,
  controlSubscriptionWirePayload,
  type ControlEventObserver,
  type ControlRequest,
  type ControlSubscription,
  type ControlTransport,
  type ExternalActionReceipt,
  type ExternalActionRequest,
  type FilePickOptions,
  type FrontendCapabilities,
  type PickedFile,
} from './transport';

export interface NativeControlTransportOptions {
  bridgeWindow?: Window;
  requestTimeoutMs?: number;
  createId?: () => string;
}

interface PendingRequest {
  resolve(value: unknown): void;
  reject(error: Error): void;
  timer: ReturnType<typeof setTimeout>;
  removeAbortListener?: () => void;
}

interface NativeSubscription {
  request: ControlSubscription;
  observer: ControlEventObserver<unknown>;
  lastEventId: string;
  reconnectAttempt: number;
  reconnectTimer?: ReturnType<typeof setTimeout>;
}

export class NativeBridgeUnavailableError extends Error {
  constructor(message = 'ragImeNativeBridge is unavailable') {
    super(message);
    this.name = 'NativeBridgeUnavailableError';
  }
}

export class NativeBridgeCallError extends Error {
  readonly code?: string;
  readonly details?: unknown;

  constructor(error: NativeBridgeError) {
    const payload = typeof error === 'string' ? { message: error } : error;
    super(payload.message);
    this.name = 'NativeBridgeCallError';
    this.code = payload.code;
    this.details = payload.details;
  }
}

export class NativeControlTransport implements ControlTransport {
  readonly kind = 'native' as const;

  private readonly bridgeWindow: Window;
  private readonly handler: RagImeNativeMessageHandler;
  private readonly requestTimeoutMs: number;
  private readonly createId: () => string;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly subscriptions = new Map<string, NativeSubscription>();
  private readonly receiver: RagImeNativeBridgeReceiver;
  private readonly previousReceiver: RagImeNativeBridgeReceiver | undefined;
  private disposed = false;

  constructor(options: NativeControlTransportOptions = {}) {
    this.bridgeWindow = options.bridgeWindow ?? window;
    const handler = this.bridgeWindow.webkit?.messageHandlers?.ragImeNativeBridge;
    if (!handler || typeof handler.postMessage !== 'function') {
      throw new NativeBridgeUnavailableError();
    }
    this.handler = handler;
    this.requestTimeoutMs = clamp(options.requestTimeoutMs ?? 15_000, 100, 120_000);
    this.createId = options.createId ?? createBridgeId;
    this.previousReceiver = this.bridgeWindow.__RAG_IME_NATIVE_BRIDGE__;
    this.receiver = { receive: (envelope) => this.receive(envelope) };
    this.bridgeWindow.__RAG_IME_NATIVE_BRIDGE__ = this.receiver;
  }

  async capabilities(): Promise<FrontendCapabilities> {
    const raw = await this.call('capabilities', {});
    return normalizeNativeCapabilities(raw);
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    assertControlRequest(request);
    const result = await this.call('request', controlRequestWirePayload(request), request.signal);
    const contract = request.responseContract ?? controlRoute(request.pathId).responseContract;
    return (contract ? parseContract(contract, result) : result) as Response;
  }

  subscribe<Event = unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void {
    assertControlSubscription(request);
    this.assertActive();
    const subscriptionId = this.createId();
    this.subscriptions.set(subscriptionId, {
      request,
      observer: observer as ControlEventObserver<unknown>,
      lastEventId: request.lastEventId,
      reconnectAttempt: 0,
    });
    void this.call('subscribe', {
      subscriptionId,
      request: controlSubscriptionWirePayload(request),
    })
      .then(() => observer.open?.(request.lastEventId))
      .catch((error) => {
        this.subscriptions.delete(subscriptionId);
        observer.error?.(asError(error));
      });

    return () => this.cancelSubscription(subscriptionId);
  }

  async pickFiles(options: FilePickOptions): Promise<PickedFile[]> {
    const result = await this.call('pickFiles', options);
    if (!Array.isArray(result)) throw new NativeBridgeCallError('pickFiles returned a non-array');
    return result.map(parsePickedFile);
  }

  async revealPath(path: string): Promise<void> {
    if (!path || path.length > 4096 || path.includes('\u0000')) {
      throw new TypeError('revealPath requires a bounded local path');
    }
    await this.call('revealPath', { path });
  }

  async runApprovedExternalAction(
    request: ExternalActionRequest,
  ): Promise<ExternalActionReceipt> {
    const result = await this.call('runApprovedExternalAction', request);
    if (!isRecord(result) || typeof result.receiptId !== 'string') {
      throw new NativeBridgeCallError('external action returned an invalid receipt');
    }
    return result as unknown as ExternalActionReceipt;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const subscriptionId of [...this.subscriptions.keys()]) {
      this.cancelSubscription(subscriptionId);
    }
    for (const [id, item] of this.pending) {
      globalThis.clearTimeout(item.timer);
      item.removeAbortListener?.();
      item.reject(new NativeBridgeUnavailableError('native transport was disposed'));
      this.pending.delete(id);
    }
    if (this.bridgeWindow.__RAG_IME_NATIVE_BRIDGE__ === this.receiver) {
      this.bridgeWindow.__RAG_IME_NATIVE_BRIDGE__ = this.previousReceiver;
    }
  }

  private call(method: NativeBridgeMethod, payload: unknown, signal?: AbortSignal): Promise<unknown> {
    this.assertActive();
    if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
    const id = this.createId();

    return new Promise((resolve, reject) => {
      const timer = globalThis.setTimeout(() => {
        const item = this.pending.get(id);
        if (!item) return;
        item.removeAbortListener?.();
        this.pending.delete(id);
        reject(new NativeBridgeCallError({ code: 'timeout', message: `${method} timed out` }));
      }, this.requestTimeoutMs);

      const pending: PendingRequest = { resolve, reject, timer };
      if (signal) {
        const abort = (): void => {
          globalThis.clearTimeout(timer);
          this.pending.delete(id);
          reject(new DOMException('Aborted', 'AbortError'));
        };
        signal.addEventListener('abort', abort, { once: true });
        pending.removeAbortListener = () => signal.removeEventListener('abort', abort);
      }
      this.pending.set(id, pending);

      const envelope: NativeBridgeRequestEnvelope = { id, method, payload };
      try {
        this.handler.postMessage(envelope);
      } catch (error) {
        globalThis.clearTimeout(timer);
        pending.removeAbortListener?.();
        this.pending.delete(id);
        reject(asError(error));
      }
    });
  }

  private receive(envelope: NativeBridgeOutboundEnvelope): void {
    if (this.disposed) return;
    if ('id' in envelope) {
      const pending = this.pending.get(envelope.id);
      if (!pending) return;
      globalThis.clearTimeout(pending.timer);
      pending.removeAbortListener?.();
      this.pending.delete(envelope.id);
      if (envelope.ok) pending.resolve(envelope.result);
      else pending.reject(new NativeBridgeCallError(envelope.error));
      return;
    }
    const subscription = this.subscriptions.get(envelope.subscriptionId);
    if (!subscription) return;
    if (envelope.kind === 'error') {
      subscription.observer.error?.(new NativeBridgeCallError(envelope.error));
      if (isRetryableBridgeError(envelope.error)) {
        this.scheduleSubscriptionReconnect(envelope.subscriptionId, subscription);
      } else {
        this.subscriptions.delete(envelope.subscriptionId);
      }
      return;
    }
    if (envelope.kind === 'complete') {
      subscription.lastEventId = envelope.lastEventId || subscription.lastEventId;
      this.scheduleSubscriptionReconnect(envelope.subscriptionId, subscription);
      return;
    }
    try {
      const streamKind = controlRoute(subscription.request.pathId).subscription;
      const event = parseNativeEvent(streamKind, envelope.event);
      subscription.lastEventId = envelope.lastEventId || eventResumeToken(event);
      subscription.reconnectAttempt = 0;
      subscription.observer.next(event);
      if (isSnapshotRequired(event)) subscription.observer.snapshotRequired?.(event);
    } catch (error) {
      subscription.observer.error?.(asError(error));
    }
  }

  private cancelSubscription(subscriptionId: string): void {
    const subscription = this.subscriptions.get(subscriptionId);
    if (!subscription) return;
    this.subscriptions.delete(subscriptionId);
    if (subscription.reconnectTimer) globalThis.clearTimeout(subscription.reconnectTimer);
    if (this.disposed) return;
    void this.call('cancelSubscription', {
      subscriptionId,
      lastEventId: subscription.lastEventId,
    }).catch(() => {
      // Cancellation is idempotent and best-effort during host teardown.
    });
  }

  private assertActive(): void {
    if (this.disposed) throw new NativeBridgeUnavailableError('native transport was disposed');
  }

  private scheduleSubscriptionReconnect(
    subscriptionId: string,
    subscription: NativeSubscription,
  ): void {
    if (this.disposed || subscription.reconnectTimer) return;
    subscription.reconnectAttempt += 1;
    const delayMs = Math.min(5_000, 250 * 2 ** Math.min(5, subscription.reconnectAttempt - 1));
    subscription.observer.reconnect?.({
      attempt: subscription.reconnectAttempt,
      delayMs,
      lastEventId: subscription.lastEventId,
    });
    subscription.reconnectTimer = globalThis.setTimeout(() => {
      subscription.reconnectTimer = undefined;
      if (this.disposed || this.subscriptions.get(subscriptionId) !== subscription) return;
      const request = { ...subscription.request, lastEventId: subscription.lastEventId };
      void this.call('subscribe', {
        subscriptionId,
        request: controlSubscriptionWirePayload(request),
      })
        .then(() => subscription.observer.open?.(subscription.lastEventId))
        .catch((error) => {
          subscription.observer.error?.(asError(error));
          this.scheduleSubscriptionReconnect(subscriptionId, subscription);
        });
    }, delayMs);
  }
}

function parseNativeEvent(streamKind: ControlStreamKind | undefined, value: unknown): unknown {
  switch (streamKind) {
    case 'agent':
      return parseAgentEvent(value);
    case 'room':
      return parseRoomEvent(value);
    case 'control':
      return value;
    default:
      throw new NativeBridgeCallError('event arrived for a non-subscription route');
  }
}

function normalizeNativeCapabilities(value: unknown): FrontendCapabilities {
  const payload = isRecord(value) ? value : {};
  const rawRouteIds = Array.isArray(payload.routeIds)
    ? payload.routeIds
    : Array.isArray(payload.routes)
      ? payload.routes.map((route) => (isRecord(route) ? route.pathId : undefined))
      : [];
  const routeIds = rawRouteIds.filter(isControlPathId);
  const rawFeatures = isRecord(payload.features) ? payload.features : {};
  const rawNative = isRecord(payload.native) ? payload.native : {};
  return {
    schemaVersion:
      typeof payload.schemaVersion === 'string'
        ? payload.schemaVersion
        : 'rag-ime.control-frontend-capabilities.v1',
    transport: 'native',
    routeIds,
    features: booleanRecord(rawFeatures),
    native: {
      pickFiles: rawNative.pickFiles === true || rawNative.filePicker === true,
      revealPath: rawNative.revealPath === true,
      approvedExternalActions: rawNative.approvedExternalActions === true,
      keychain: rawNative.keychain === true || rawNative.keychainStatus === true,
      tcc: rawNative.tcc === true || rawNative.tccStatus === true,
    },
    raw: value,
  };
}

function parsePickedFile(value: unknown): PickedFile {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.name !== 'string' ||
    typeof value.mimeType !== 'string' ||
    typeof value.byteSize !== 'number'
  ) {
    throw new NativeBridgeCallError('pickFiles returned an invalid file receipt');
  }
  return value as unknown as PickedFile;
}

function booleanRecord(value: Record<string, unknown>): Record<string, boolean> {
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, boolean] => {
      return typeof entry[1] === 'boolean';
    }),
  );
}

function eventResumeToken(event: unknown): string {
  if (!isRecord(event)) return '';
  if (typeof event.resumeToken === 'string') return event.resumeToken;
  if (typeof event.eventId === 'string') return event.eventId;
  return '';
}

function isSnapshotRequired(event: unknown): boolean {
  return isRecord(event) && event.eventType === 'snapshot_required';
}

function isRetryableBridgeError(error: NativeBridgeError): boolean {
  return typeof error === 'object' && error !== null && error.retryable === true;
}

function createBridgeId(): string {
  return globalThis.crypto.randomUUID();
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
