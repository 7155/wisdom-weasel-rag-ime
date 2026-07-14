import { parseAgentEvent, parseContract, parseRoomEvent } from '@/contracts/validators';
import { CONTROL_ROUTES, controlRoute, type ControlPathId } from '@/platform/routes';
import {
  assertControlRequest,
  assertControlSubscription,
  type ControlEventObserver,
  type ControlRequest,
  type ControlSubscription,
  type ControlTransport,
  type ExternalActionReceipt,
  type ExternalActionRequest,
  type FilePickOptions,
  type FrontendCapabilities,
  type PickedFile,
} from '@/platform/transport';

export interface MockRequestCall {
  request: ControlRequest;
  at: number;
}

export interface MockSubscriptionCall {
  id: string;
  request: ControlSubscription;
  at: number;
}

export type MockRouteHandler =
  | unknown
  | ((request: ControlRequest) => unknown | Promise<unknown>);

export interface MockControlTransportOptions {
  capabilities?: Partial<FrontendCapabilities>;
  routes?: Partial<Record<ControlPathId, MockRouteHandler>>;
  pickedFiles?: PickedFile[];
  externalAction?: (
    request: ExternalActionRequest,
  ) => ExternalActionReceipt | Promise<ExternalActionReceipt>;
  now?: () => number;
}

interface ActiveSubscription {
  request: ControlSubscription;
  observer: ControlEventObserver<unknown>;
  lastEventId: string;
}

export class MockControlTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: MockRequestCall[] = [];
  readonly subscriptionCalls: MockSubscriptionCall[] = [];

  private readonly routeHandlers = new Map<ControlPathId, MockRouteHandler>();
  private readonly subscriptions = new Map<string, ActiveSubscription>();
  private readonly capabilityValue: FrontendCapabilities;
  private readonly pickedFiles: PickedFile[];
  private readonly externalAction?: MockControlTransportOptions['externalAction'];
  private readonly now: () => number;
  private nextSubscriptionId = 1;

  constructor(options: MockControlTransportOptions = {}) {
    for (const [pathId, handler] of Object.entries(options.routes ?? {}) as [
      ControlPathId,
      MockRouteHandler,
    ][]) {
      this.routeHandlers.set(pathId, handler);
    }
    this.capabilityValue = {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      routeIds: Object.keys(CONTROL_ROUTES) as ControlPathId[],
      features: {},
      native: {
        pickFiles: Boolean(options.pickedFiles),
        revealPath: false,
        approvedExternalActions: Boolean(options.externalAction),
        keychain: false,
        tcc: false,
      },
      ...options.capabilities,
      transport: 'mock',
    };
    this.pickedFiles = [...(options.pickedFiles ?? [])];
    this.externalAction = options.externalAction;
    this.now = options.now ?? Date.now;
  }

  async capabilities(): Promise<FrontendCapabilities> {
    return this.capabilityValue;
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    assertControlRequest(request);
    throwIfAborted(request.signal);
    if (controlRoute(request.pathId).subscription) {
      throw new TypeError(`Use subscribe() for ${request.pathId}`);
    }
    this.requests.push({ request, at: this.now() });
    if (!this.routeHandlers.has(request.pathId)) {
      throw new Error(`No mock response registered for ${request.pathId}`);
    }
    const handler = this.routeHandlers.get(request.pathId);
    const value = typeof handler === 'function' ? await handler(request) : handler;
    throwIfAborted(request.signal);
    const contract = request.responseContract ?? controlRoute(request.pathId).responseContract;
    return (contract ? parseContract(contract, value) : value) as Response;
  }

  subscribe<Event = unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void {
    assertControlSubscription(request);
    const id = `mock-subscription-${this.nextSubscriptionId++}`;
    this.subscriptions.set(id, {
      request,
      observer: observer as ControlEventObserver<unknown>,
      lastEventId: request.lastEventId,
    });
    this.subscriptionCalls.push({ id, request, at: this.now() });
    observer.open?.(request.lastEventId);
    return () => this.subscriptions.delete(id);
  }

  emit(pathId: ControlSubscription['pathId'], event: unknown): number {
    let delivered = 0;
    for (const subscription of this.subscriptions.values()) {
      if (subscription.request.pathId !== pathId) continue;
      try {
        const streamKind = controlRoute(pathId).subscription;
        const parsed =
          streamKind === 'agent'
            ? parseAgentEvent(event)
            : streamKind === 'room'
              ? parseRoomEvent(event)
              : event;
        subscription.lastEventId = resumeToken(parsed) || subscription.lastEventId;
        subscription.observer.next(parsed);
        if (isSnapshotRequired(parsed)) subscription.observer.snapshotRequired?.(parsed);
        delivered += 1;
      } catch (error) {
        subscription.observer.error?.(asError(error));
      }
    }
    return delivered;
  }

  simulateReconnect(pathId: ControlSubscription['pathId'], delayMs = 20): void {
    for (const subscription of this.subscriptions.values()) {
      if (subscription.request.pathId !== pathId) continue;
      subscription.observer.reconnect?.({
        attempt: 1,
        delayMs,
        lastEventId: subscription.lastEventId,
      });
    }
  }

  activeSubscriptionCount(): number {
    return this.subscriptions.size;
  }

  async pickFiles(_options: FilePickOptions): Promise<PickedFile[]> {
    return [...this.pickedFiles];
  }

  async revealPath(_path: string): Promise<void> {}

  async runApprovedExternalAction(
    request: ExternalActionRequest,
  ): Promise<ExternalActionReceipt> {
    if (!this.externalAction) throw new Error('No external action mock is registered');
    return this.externalAction(request);
  }

  dispose(): void {
    this.subscriptions.clear();
  }
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
}

function resumeToken(value: unknown): string {
  if (!isRecord(value)) return '';
  if (typeof value.resumeToken === 'string') return value.resumeToken;
  if (typeof value.eventId === 'string') return value.eventId;
  return '';
}

function isSnapshotRequired(value: unknown): boolean {
  return isRecord(value) && value.eventType === 'snapshot_required';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
