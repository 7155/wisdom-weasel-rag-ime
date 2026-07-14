import type { GeneratedContractName } from '@/contracts/generated';
import type { UiControlEvent } from '@/contracts/ui-events';

import {
  CONTROL_ROUTES,
  assertAllowedBody,
  assertAllowedQuery,
  controlRoute,
  resolveControlPath,
  type ControlPathId,
  type SubscriptionPathId,
} from './routes';

export type ControlTransportKind = 'http' | 'native' | 'mock';
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type ControlQueryValue = string | number | boolean;

export interface ControlRequest<Body extends JsonValue = JsonValue> {
  pathId: ControlPathId;
  params?: Readonly<Record<string, string>>;
  query?: Readonly<Record<string, ControlQueryValue>>;
  body?: Body;
  responseContract?: GeneratedContractName;
  signal?: AbortSignal;
}

export interface ControlSubscription {
  pathId: SubscriptionPathId;
  params?: Readonly<Record<string, string>>;
  query?: Readonly<Record<string, ControlQueryValue>>;
  lastEventId: string;
}

export interface ControlReconnectNotice {
  attempt: number;
  delayMs: number;
  lastEventId: string;
}

export interface ControlEventObserver<Event = UiControlEvent | unknown> {
  next(event: Event): void;
  open?(lastEventId: string): void;
  error?(error: Error): void;
  reconnect?(notice: ControlReconnectNotice): void;
  snapshotRequired?(event: Event): void;
}

export interface FrontendCapabilities {
  schemaVersion: string;
  transport: ControlTransportKind;
  routeIds: readonly ControlPathId[];
  features: Readonly<Record<string, boolean>>;
  native: {
    pickFiles: boolean;
    revealPath: boolean;
    approvedExternalActions: boolean;
    keychain: boolean;
    tcc: boolean;
  };
  raw?: unknown;
}

export interface FilePickOptions {
  accepts?: readonly string[];
  multiple?: boolean;
  purpose: 'attachment' | 'configuration-import' | 'restore' | 'export-destination';
}

export interface PickedFile {
  id: string;
  name: string;
  mimeType: string;
  byteSize: number;
  path?: string;
}

export type ApprovedExternalActionId =
  | 'open_accessibility_settings'
  | 'restart_sidecar'
  | 'restart_predictor'
  | 'redeploy_rime';

export interface ExternalActionRequest {
  action: ApprovedExternalActionId;
  receiptId: string;
  payloadSha256: string;
  commandSha256: string;
}

export interface ExternalActionReceipt {
  receiptId: string;
  action: ApprovedExternalActionId;
  accepted: boolean;
  completed: boolean;
  exitCode?: number;
  error?: string;
}

export interface ControlTransport {
  readonly kind: ControlTransportKind;
  capabilities(): Promise<FrontendCapabilities>;
  request<Response = unknown>(request: ControlRequest): Promise<Response>;
  subscribe<Event = UiControlEvent | unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void;
  pickFiles?(options: FilePickOptions): Promise<PickedFile[]>;
  revealPath?(path: string): Promise<void>;
  runApprovedExternalAction?(request: ExternalActionRequest): Promise<ExternalActionReceipt>;
  dispose?(): void;
}

const allowedRequestKeys = new Set([
  'pathId',
  'params',
  'query',
  'body',
  'responseContract',
  'signal',
]);

export function assertControlRequest(request: ControlRequest): void {
  for (const key of Object.keys(request)) {
    if (!allowedRequestKeys.has(key)) {
      throw new TypeError(`ControlRequest field is not allowed: ${key}`);
    }
  }
  controlRoute(request.pathId);
  resolveControlPath(request.pathId, request.params);
  assertAllowedQuery(request.pathId, request.query);
  assertAllowedBody(request.pathId, request.body);
}

export function assertControlSubscription(request: ControlSubscription): void {
  const route = controlRoute(request.pathId);
  if (!route.subscription) {
    throw new TypeError(`Control path is not subscribable: ${request.pathId}`);
  }
  if (typeof request.lastEventId !== 'string') {
    throw new TypeError('ControlSubscription.lastEventId is required');
  }
  resolveControlPath(request.pathId, request.params);
  assertAllowedQuery(request.pathId, {
    ...(request.query ?? {}),
    lastEventId: request.lastEventId,
  });
}

export function controlRequestWirePayload(request: ControlRequest): object {
  assertControlRequest(request);
  return {
    pathId: request.pathId,
    ...(request.params ? { params: request.params } : {}),
    ...(request.query ? { query: request.query } : {}),
    ...(request.body !== undefined ? { body: request.body } : {}),
  };
}

export function controlSubscriptionWirePayload(request: ControlSubscription): object {
  assertControlSubscription(request);
  return {
    pathId: request.pathId,
    ...(request.params ? { params: request.params } : {}),
    ...(request.query ? { query: request.query } : {}),
    lastEventId: request.lastEventId,
  };
}

export function browserCapabilities(raw?: unknown): FrontendCapabilities {
  const payload = isRecord(raw) ? raw : {};
  const featureSource = isRecord(payload.features) ? payload.features : {};
  const features = Object.fromEntries(
    Object.entries(featureSource).filter((entry): entry is [string, boolean] => {
      return typeof entry[1] === 'boolean';
    }),
  );
  return {
    schemaVersion:
      typeof payload.schemaVersion === 'string'
        ? payload.schemaVersion
        : 'rag-ime.control-capabilities.v1',
    transport: 'http',
    routeIds: capabilityRouteIds(payload),
    features,
    native: {
      pickFiles: false,
      revealPath: false,
      approvedExternalActions: false,
      keychain: false,
      tcc: false,
    },
    raw,
  };
}

function capabilityRouteIds(payload: Record<string, unknown>): ControlPathId[] {
  if (Array.isArray(payload.routes)) {
    return payload.routes
      .map((route) => (isRecord(route) ? route.pathId : undefined))
      .filter(
        (pathId): pathId is ControlPathId =>
          typeof pathId === 'string' && Object.hasOwn(CONTROL_ROUTES, pathId),
      );
  }
  return Object.keys(CONTROL_ROUTES) as ControlPathId[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
