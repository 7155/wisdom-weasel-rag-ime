import { parseAgentEvent, parseContract, parseRoomEvent } from '@/contracts/validators';

import {
  controlRoute,
  resolveControlPath,
  type ControlPathId,
  type ControlStreamKind,
} from './routes';
import { SseParser, type ParsedSseEvent } from './sse';
import {
  assertControlRequest,
  assertControlSubscription,
  browserCapabilities,
  type ControlEventObserver,
  type ControlQueryValue,
  type ControlRequest,
  type ControlSubscription,
  type ControlTransport,
  type FrontendCapabilities,
} from './transport';

export interface HttpControlTransportOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  reconnectBaseDelayMs?: number;
  reconnectMaxDelayMs?: number;
  random?: () => number;
}

export class ControlTransportHttpError extends Error {
  readonly status: number;
  readonly pathId: ControlPathId;
  readonly payload: unknown;

  constructor(pathId: ControlPathId, status: number, message: string, payload?: unknown) {
    super(message);
    this.name = 'ControlTransportHttpError';
    this.pathId = pathId;
    this.status = status;
    this.payload = payload;
  }
}

export class HttpControlTransport implements ControlTransport {
  readonly kind = 'http' as const;

  private readonly baseUrl: URL;
  private readonly fetchImpl: typeof fetch;
  private readonly reconnectBaseDelayMs: number;
  private readonly reconnectMaxDelayMs: number;
  private readonly random: () => number;
  private readonly subscriptions = new Set<AbortController>();

  constructor(options: HttpControlTransportOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.reconnectBaseDelayMs = clamp(options.reconnectBaseDelayMs ?? 250, 0, 30_000);
    this.reconnectMaxDelayMs = clamp(options.reconnectMaxDelayMs ?? 5_000, 0, 60_000);
    this.random = options.random ?? Math.random;
  }

  async capabilities(): Promise<FrontendCapabilities> {
    try {
      const raw = await this.request({
        pathId: 'control.capabilities',
      });
      return browserCapabilities(raw);
    } catch (error) {
      if (!(error instanceof ControlTransportHttpError) || error.status !== 404) throw error;
      return browserCapabilities({
        schemaVersion: 'rag-ime.control-capabilities.v1',
        features: { legacyEndpointAdapter: true },
      });
    }
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    assertControlRequest(request);
    const route = controlRoute(request.pathId);
    if (route.subscription) {
      throw new TypeError(`Use subscribe() for ${request.pathId}`);
    }
    if ((route.method === 'GET' || route.method === 'DELETE') && request.body !== undefined) {
      throw new TypeError(`${route.method} ${request.pathId} cannot carry a body`);
    }

    const url = this.url(request.pathId, request.params, request.query);
    const headers = new Headers({ Accept: 'application/json' });
    if (request.body !== undefined) headers.set('Content-Type', 'application/json');
    const response = await this.fetchImpl(url, {
      method: route.method,
      headers,
      ...(request.body === undefined ? {} : { body: JSON.stringify(request.body) }),
      ...(request.signal ? { signal: request.signal } : {}),
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      const message =
        isRecord(payload) && typeof payload.error === 'string'
          ? payload.error
          : `${request.pathId} returned HTTP ${response.status}`;
      throw new ControlTransportHttpError(request.pathId, response.status, message, payload);
    }
    const contract = request.responseContract ?? route.responseContract;
    return (contract ? parseContract(contract, payload) : payload) as Response;
  }

  subscribe<Event = unknown>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
  ): () => void {
    assertControlSubscription(request);
    const controller = new AbortController();
    this.subscriptions.add(controller);
    void this.runSubscription(request, observer, controller).finally(() => {
      this.subscriptions.delete(controller);
    });
    return () => controller.abort();
  }

  dispose(): void {
    for (const controller of this.subscriptions) controller.abort();
    this.subscriptions.clear();
  }

  private async runSubscription<Event>(
    request: ControlSubscription,
    observer: ControlEventObserver<Event>,
    controller: AbortController,
  ): Promise<void> {
    const route = controlRoute(request.pathId);
    const streamKind = route.subscription;
    if (!streamKind) return;
    let lastEventId = request.lastEventId;
    let attempt = 0;

    while (!controller.signal.aborted) {
      try {
        const headers = new Headers({
          Accept: 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Last-Event-ID': lastEventId,
        });
        const response = await this.fetchImpl(
          this.url(request.pathId, request.params, {
            ...(request.query ?? {}),
            lastEventId,
          }),
          {
            method: 'GET',
            headers,
            signal: controller.signal,
          },
        );
        if (!response.ok) {
          throw new ControlTransportHttpError(
            request.pathId,
            response.status,
            `${request.pathId} stream returned HTTP ${response.status}`,
          );
        }
        if (!response.body) throw new Error(`${request.pathId} stream has no response body`);

        attempt = 0;
        observer.open?.(lastEventId);
        const decoder = new TextDecoder();
        const parser = new SseParser((item) => {
          try {
            const event = parseStreamEvent(streamKind, item) as Event;
            lastEventId = streamResumeToken(event, item.id, lastEventId);
            observer.next(event);
            if (isSnapshotRequired(event)) observer.snapshotRequired?.(event);
          } catch (error) {
            observer.error?.(asError(error));
          }
        });
        const reader = response.body.getReader();
        try {
          while (!controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            parser.push(decoder.decode(value, { stream: true }));
          }
          parser.push(decoder.decode());
          parser.finish();
        } finally {
          reader.releaseLock();
        }
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) return;
        observer.error?.(asError(error));
      }

      if (controller.signal.aborted) return;
      attempt += 1;
      const delayMs = reconnectDelay(
        attempt,
        this.reconnectBaseDelayMs,
        this.reconnectMaxDelayMs,
        this.random,
      );
      observer.reconnect?.({ attempt, delayMs, lastEventId });
      try {
        await abortableDelay(delayMs, controller.signal);
      } catch {
        return;
      }
    }
  }

  private url(
    pathId: ControlPathId,
    params: Readonly<Record<string, string>> | undefined,
    query: Readonly<Record<string, ControlQueryValue>> | undefined,
  ): URL {
    const url = new URL(resolveControlPath(pathId, params), this.baseUrl);
    for (const [key, rawValue] of Object.entries(query ?? {})) {
      if (rawValue === undefined) continue;
      url.searchParams.append(key, String(rawValue));
    }
    return url;
  }
}

function parseStreamEvent(streamKind: ControlStreamKind, item: ParsedSseEvent): unknown {
  const payload = JSON.parse(item.data) as unknown;
  switch (streamKind) {
    case 'agent':
      return parseAgentEvent(payload);
    case 'room':
      return parseRoomEvent(payload);
    case 'control':
      return payload;
  }
}

function streamResumeToken(event: unknown, sseId: string, fallback: string): string {
  if (isRecord(event)) {
    if (typeof event.resumeToken === 'string' && event.resumeToken.length > 0) {
      return event.resumeToken;
    }
    if (typeof event.eventId === 'string' && event.eventId.length > 0) return event.eventId;
  }
  return sseId || fallback;
}

function isSnapshotRequired(event: unknown): boolean {
  return isRecord(event) && event.eventType === 'snapshot_required';
}

async function responsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (text.length === 0) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function normalizeBaseUrl(value: string): URL {
  const url = new URL(value, globalThis.location?.href ?? 'http://127.0.0.1/');
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new TypeError('HttpControlTransport baseUrl must use HTTP or HTTPS');
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new TypeError('HttpControlTransport baseUrl must not contain credentials, query, or hash');
  }
  return url;
}

function reconnectDelay(
  attempt: number,
  baseMs: number,
  maximumMs: number,
  random: () => number,
): number {
  const exponential = Math.min(maximumMs, baseMs * 2 ** Math.max(0, attempt - 1));
  const jitter = 0.8 + clamp(random(), 0, 1) * 0.4;
  return Math.round(exponential * jitter);
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const timer = globalThis.setTimeout(finish, milliseconds);
    signal.addEventListener('abort', abort, { once: true });

    function finish(): void {
      signal.removeEventListener('abort', abort);
      resolve();
    }
    function abort(): void {
      globalThis.clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    }
  });
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
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
