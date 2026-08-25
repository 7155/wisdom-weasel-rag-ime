import { CONTROL_ROUTES, type ControlPathId } from '@/platform/routes';
import {
  managedAgentMediaContentPath,
  type ControlEventObserver,
  type ControlRequest,
  type ControlSubscription,
  type ControlTransport,
  type ControlTransportKind,
  type FrontendCapabilities,
} from '@/platform/transport';

type StubHandler = unknown | ((request: ControlRequest) => unknown | Promise<unknown>);

export class StubControlTransport implements ControlTransport {
  readonly requests: ControlRequest[] = [];
  private readonly subscriptions = new Map<
    number,
    { request: ControlSubscription; observer: ControlEventObserver<unknown> }
  >();
  private nextSubscriptionId = 1;

  constructor(
    readonly kind: ControlTransportKind,
    private readonly routes: Partial<Record<ControlPathId, StubHandler>>,
  ) {}

  async capabilities(): Promise<FrontendCapabilities> {
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: this.kind,
      routeIds: Object.keys(CONTROL_ROUTES) as ControlPathId[],
      features: {},
      native: {
        pickFiles: false,
        managedAgentImageImport: false,
        revealPath: false,
        approvedExternalActions: false,
        keychain: false,
        tcc: false,
      },
    };
  }

  agentMediaContentUrl(receiptPath: string): string {
    const managedPath = managedAgentMediaContentPath(receiptPath);
    if (!managedPath) throw new TypeError('Agent media content requires a managed receipt path');
    return this.kind === 'native'
      ? new URL(managedPath, 'http://127.0.0.1:8766').toString()
      : managedPath;
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    this.requests.push(request);
    if (!Object.hasOwn(this.routes, request.pathId)) {
      throw new Error(`No stub response registered for ${request.pathId}`);
    }
    const handler = this.routes[request.pathId];
    const value = typeof handler === 'function' ? await handler(request) : handler;
    return value as Response;
  }

  subscribe<Event = unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void {
    const id = this.nextSubscriptionId;
    this.nextSubscriptionId += 1;
    this.subscriptions.set(id, {
      request,
      observer: observer as ControlEventObserver<unknown>,
    });
    observer.open?.(request.lastEventId);
    return () => this.subscriptions.delete(id);
  }

  emit(pathId: ControlSubscription['pathId'], event: unknown): number {
    let delivered = 0;
    for (const subscription of this.subscriptions.values()) {
      if (subscription.request.pathId !== pathId) continue;
      subscription.observer.next(event);
      delivered += 1;
    }
    return delivered;
  }

  subscriptionCount(pathId: ControlSubscription['pathId']): number {
    let count = 0;
    for (const subscription of this.subscriptions.values()) {
      if (subscription.request.pathId === pathId) count += 1;
    }
    return count;
  }
}
