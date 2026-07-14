import { CONTROL_ROUTES, type ControlPathId } from '@/platform/routes';
import type {
  ControlEventObserver,
  ControlRequest,
  ControlSubscription,
  ControlTransport,
  ControlTransportKind,
  FrontendCapabilities,
} from '@/platform/transport';

type StubHandler = unknown | ((request: ControlRequest) => unknown | Promise<unknown>);

export class StubControlTransport implements ControlTransport {
  readonly requests: ControlRequest[] = [];

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
    _request: ControlSubscription,
    _observer: ControlEventObserver<Event>,
  ): () => void {
    return () => {};
  }
}
