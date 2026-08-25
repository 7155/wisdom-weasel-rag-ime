import {
  MAX_COMPOSER_ATTACHMENT_BYTES,
  normalizeComposerAttachmentMimeType,
} from '@/contracts/attachment-policy';
import {
  parseAgentEvent,
  parseContract,
  parseObservationEvent,
  parseRoomEvent,
} from '@/contracts/validators';

import {
  controlRoute,
  resolveControlPath,
  type ControlPathId,
  type ControlStreamKind,
} from './routes';
import { SseParser, type ParsedSseEvent } from './sse';
import {
  assertBrowserSnapshotId,
  assertControlRequest,
  assertControlSubscription,
  managedAgentMediaContentPath,
  browserCapabilities,
  type AgentImagePasteOptions,
  type ControlEventObserver,
  type ControlQueryValue,
  type ControlRequest,
  type ControlSubscription,
  type ControlTransport,
  type FrontendCapabilities,
  type KnowledgeDocumentImportInput,
  type KnowledgeDocumentImportReceipt,
  type KnowledgeAssetPayload,
  type KnowledgeAssetReadInput,
  type KnowledgeDocumentSourcePayload,
  type KnowledgeDocumentSourceReadInput,
  type PickedFile,
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
    if (route.method !== 'GET') headers.set('Content-Type', 'application/json');
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

  browserSnapshotImageUrl(snapshotId: string): string {
    assertBrowserSnapshotId(snapshotId);
    return this.url('browser.snapshot.image', { snapshotId }, undefined).toString();
  }

  agentMediaContentUrl(receiptPath: string): string {
    const managedPath = managedAgentMediaContentPath(receiptPath);
    if (!managedPath) throw new TypeError('Agent media content requires a managed receipt path');
    return new URL(managedPath, this.baseUrl).toString();
  }

  async pasteImages(options: AgentImagePasteOptions): Promise<PickedFile[]> {
    const { files, maxFiles, ownerKey, ownerId } = assertHttpFilePasteOptions(options);
    const receipts: PickedFile[] = [];
    for (const file of files.slice(0, maxFiles)) {
      // Pasted code/text/archive files often carry no browser MIME type;
      // they import as octet-stream instead of being refused.
      const mimeType = normalizeComposerAttachmentMimeType(file.type);
      const url = new URL('/api/agent/media/import', this.baseUrl);
      url.searchParams.set(ownerKey, ownerId);
      url.searchParams.set('fileName', file.name);
      const response = await this.fetchImpl(url, {
        method: 'POST',
        headers: new Headers({
          Accept: 'application/json',
          'Content-Type': mimeType,
          'Cache-Control': 'no-store',
        }),
        body: file,
      });
      const payload = await responsePayload(response);
      if (!response.ok) {
        const message = isRecord(payload) && typeof payload.error === 'string'
          ? payload.error
          : `Agent media import returned HTTP ${response.status}`;
        throw new Error(message);
      }
      receipts.push(parseAgentMediaImportResponse(payload, {
        ownerKey,
        ownerId,
        file,
        mimeType,
      }));
    }
    return receipts;
  }

  async importKnowledgeDocuments(
    input: KnowledgeDocumentImportInput,
  ): Promise<KnowledgeDocumentImportReceipt[]> {
    const { files, maxFiles } = assertKnowledgeDocumentImportInput(input, true);
    const parserProvider = knowledgeParserProvider(input);
    const receipts: KnowledgeDocumentImportReceipt[] = [];
    for (const file of files.slice(0, maxFiles)) {
      if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const mimeType = file.type || 'application/octet-stream';
      const url = this.url(
        'knowledgeBases.document.import',
        { kbId: input.kbId },
        {
          fileName: file.name,
          mimeType,
          ...(parserProvider ? { parserProvider } : {}),
        },
      );
      const response = await this.fetchImpl(url, {
        method: 'POST',
        headers: new Headers({
          Accept: 'application/json',
          'Content-Type': mimeType,
          'Cache-Control': 'no-store',
          'X-Rag-Ime-File-Size': String(file.size),
        }),
        body: file,
        ...(input.signal ? { signal: input.signal } : {}),
      });
      const payload = await responsePayload(response);
      if (!response.ok) {
        const message =
          isRecord(payload) && typeof payload.error === 'string'
            ? payload.error
            : `knowledgeBases.document.import returned HTTP ${response.status}`;
        throw new ControlTransportHttpError(
          'knowledgeBases.document.import',
          response.status,
          message,
          payload,
        );
      }
      receipts.push(parseKnowledgeDocumentImportResponse(payload, input.kbId, file));
    }
    return receipts;
  }

  async readKnowledgeAsset(input: KnowledgeAssetReadInput): Promise<KnowledgeAssetPayload> {
    assertKnowledgeAssetReadInput(input);
    const url = this.url(
      'knowledgeBases.asset.get',
      { kbId: input.kbId, fileId: input.fileId, assetId: input.assetId },
      undefined,
    );
    const response = await this.fetchImpl(url, {
      method: 'GET',
      headers: new Headers({
        Accept: [...KNOWLEDGE_ASSET_MIME_TYPES].join(', '),
        'Cache-Control': 'no-store',
      }),
      ...(input.signal ? { signal: input.signal } : {}),
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      const message =
        isRecord(payload) && typeof payload.error === 'string'
          ? payload.error
          : `knowledgeBases.asset.get returned HTTP ${response.status}`;
      throw new ControlTransportHttpError('knowledgeBases.asset.get', response.status, message, payload);
    }
    if (response.url && response.url !== url.toString()) {
      throw new TypeError('Knowledge asset response was redirected outside its fixed route');
    }
    const mimeType = response.headers.get('Content-Type')?.split(';', 1)[0]?.trim().toLowerCase() ?? '';
    const declaredSize = Number(response.headers.get('Content-Length'));
    const sha256 = normalizedEntityTag(response.headers.get('ETag'));
    if (
      !KNOWLEDGE_ASSET_MIME_TYPES.has(mimeType) ||
      !Number.isSafeInteger(declaredSize) ||
      declaredSize <= 0 ||
      declaredSize > MAX_KNOWLEDGE_ASSET_BYTES ||
      sha256 !== input.assetId ||
      response.headers.get('X-Content-Type-Options')?.toLowerCase() !== 'nosniff' ||
      !response.headers.get('Content-Disposition')?.toLowerCase().startsWith('inline')
    ) {
      throw new TypeError('Knowledge asset returned invalid security headers');
    }
    const blob = await response.blob();
    if (
      blob.size !== declaredSize ||
      blob.size > MAX_KNOWLEDGE_ASSET_BYTES ||
      (await sha256Hex(blob)) !== sha256
    ) {
      throw new TypeError('Knowledge asset size did not match its bounded receipt');
    }
    return {
      kbId: input.kbId,
      fileId: input.fileId,
      assetId: input.assetId,
      mimeType,
      byteSize: blob.size,
      sha256,
      blob,
    };
  }

  async readKnowledgeDocumentSource(
    input: KnowledgeDocumentSourceReadInput,
  ): Promise<KnowledgeDocumentSourcePayload> {
    assertKnowledgeDocumentSourceReadInput(input);
    const url = this.url(
      'knowledgeBases.document.source',
      { kbId: input.kbId, fileId: input.fileId },
      undefined,
    );
    const response = await this.fetchImpl(url, {
      method: 'GET',
      headers: new Headers({
        Accept: [...KNOWLEDGE_SOURCE_MIME_TYPES].join(', '),
        'Cache-Control': 'no-store',
      }),
      ...(input.signal ? { signal: input.signal } : {}),
    });
    if (!response.ok) {
      const payload = await responsePayload(response);
      const message =
        isRecord(payload) && typeof payload.error === 'string'
          ? payload.error
          : `knowledgeBases.document.source returned HTTP ${response.status}`;
      throw new ControlTransportHttpError(
        'knowledgeBases.document.source',
        response.status,
        message,
        payload,
      );
    }
    if (response.url && response.url !== url.toString()) {
      throw new TypeError('Knowledge source response was redirected outside its fixed route');
    }
    const mimeType = response.headers.get('Content-Type')?.split(';', 1)[0]?.trim().toLowerCase() ?? '';
    const declaredSize = Number(response.headers.get('Content-Length'));
    const sha256 = normalizedEntityTag(response.headers.get('ETag'));
    if (
      !KNOWLEDGE_SOURCE_MIME_TYPES.has(mimeType) ||
      !Number.isSafeInteger(declaredSize) ||
      declaredSize <= 0 ||
      declaredSize > MAX_KNOWLEDGE_SOURCE_BYTES ||
      !/^[a-f0-9]{64}$/.test(sha256) ||
      response.headers.get('X-Content-Type-Options')?.toLowerCase() !== 'nosniff' ||
      !response.headers.get('Content-Disposition')?.toLowerCase().startsWith('inline')
    ) {
      throw new TypeError('Knowledge document source returned invalid security headers');
    }
    const blob = await response.blob();
    if (
      blob.size !== declaredSize ||
      blob.size > MAX_KNOWLEDGE_SOURCE_BYTES ||
      (await sha256Hex(blob)) !== sha256
    ) {
      throw new TypeError('Knowledge document source did not match its bounded receipt');
    }
    return {
      kbId: input.kbId,
      fileId: input.fileId,
      mimeType,
      byteSize: blob.size,
      sha256,
      blob,
    };
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
    case 'kernel':
      return payload;
    case 'control':
      return payload;
    case 'observation':
      return parseObservationEvent(payload);
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
  return isRecord(event) && (
    event.eventType === 'snapshot_required'
    || event.reason === 'event_replay_gap'
  );
}

function assertHttpFilePasteOptions(options: AgentImagePasteOptions): {
  files: File[];
  maxFiles: number;
  ownerKey: 'sessionId' | 'roomId';
  ownerId: string;
} {
  const ownerKey = options.roomId ? 'roomId' : 'sessionId';
  const ownerId = options.roomId ?? options.sessionId;
  if (
    !ownerId
    || !/^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$/.test(ownerId)
    || (options.roomId !== undefined && options.sessionId !== undefined)
  ) {
    throw new TypeError('HTTP file paste requires exactly one bounded sessionId or roomId');
  }
  const files = Array.from(options.files ?? []);
  if (!files.length) {
    throw new TypeError('Browser file paste requires clipboard File objects; use the native app when WebKit hides clipboard files');
  }
  const maxFiles = options.maxFiles ?? files.length;
  if (!Number.isSafeInteger(maxFiles) || maxFiles < 1 || maxFiles > 8 || files.length > maxFiles) {
    throw new TypeError('HTTP file paste requires between 1 and 8 files within maxFiles');
  }
  for (const file of files) {
    if (
      !(file instanceof File)
      || !file.name
      || file.name.length > 512
      || file.name.includes('\u0000')
      || file.size <= 0
      || file.size > MAX_COMPOSER_ATTACHMENT_BYTES
    ) {
      throw new TypeError('HTTP file paste accepts only named, non-empty files up to 20 MiB');
    }
  }
  return { files, maxFiles, ownerKey, ownerId };
}

function parseAgentMediaImportResponse(
  payload: unknown,
  expected: {
    ownerKey: 'sessionId' | 'roomId';
    ownerId: string;
    file: File;
    mimeType: string;
  },
): PickedFile {
  if (
    !isRecord(payload)
    || payload.schemaVersion !== 'rag-ime.agent-media-import.v1'
    || payload.ok !== true
    || !isRecord(payload.media)
  ) {
    throw new TypeError('Agent media import returned an invalid envelope');
  }
  const media = payload.media;
  const oppositeOwnerKey = expected.ownerKey === 'sessionId' ? 'roomId' : 'sessionId';
  if (
    media.schemaVersion !== 'rag-ime.agent-media.v1'
    || typeof media.mediaId !== 'string'
    || !/^media_[A-Za-z0-9_-]{12,80}$/.test(media.mediaId)
    || media[expected.ownerKey] !== expected.ownerId
    || media[oppositeOwnerKey] !== undefined
    || media.ownerType !== (expected.ownerKey === 'roomId' ? 'room' : 'session')
    || media.ownerId !== expected.ownerId
    || media.mimeType !== expected.mimeType
    || media.byteSize !== expected.file.size
    || media.origin !== 'user_attachment'
    || typeof media.sha256 !== 'string'
    || !/^[a-f0-9]{64}$/.test(media.sha256)
    || typeof media.fileName !== 'string'
    || !media.fileName
    || media.fileName.length > 160
    || 'path' in media
  ) {
    throw new TypeError('Agent media import returned an invalid managed receipt');
  }
  return {
    id: media.mediaId,
    name: media.fileName,
    mimeType: expected.mimeType,
    byteSize: expected.file.size,
    [expected.ownerKey]: expected.ownerId,
    sha256: media.sha256,
  };
}

function assertKnowledgeDocumentImportInput(
  input: KnowledgeDocumentImportInput,
  requireFiles: true,
): { files: File[]; maxFiles: number } {
  if (!/^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$/.test(input.kbId)) {
    throw new TypeError('Knowledge import requires a valid kbId');
  }
  const maxFiles = input.maxFiles ?? 8;
  if (!Number.isInteger(maxFiles) || maxFiles < 1 || maxFiles > 20) {
    throw new TypeError('Knowledge import maxFiles must be between 1 and 20');
  }
  const files = Array.from(input.files ?? []);
  if (requireFiles && files.length === 0) {
    throw new TypeError('HTTP knowledge import requires browser-selected File objects');
  }
  if (files.length > maxFiles) throw new TypeError('Knowledge import selected too many files');
  for (const file of files) {
    if (!(file instanceof File) || file.size <= 0 || file.size > 200 * 1024 * 1024) {
      throw new TypeError('Knowledge documents must be non-empty files no larger than 200 MiB');
    }
    if (!file.name || file.name.length > 512 || file.name.includes('\u0000')) {
      throw new TypeError('Knowledge document file name is invalid');
    }
  }
  return { files, maxFiles };
}

function knowledgeParserProvider(
  input: KnowledgeDocumentImportInput,
): 'auto' | 'builtin' | 'mineru_local_http' | undefined {
  if (input.parserProvider && input.parser) {
    throw new TypeError('Knowledge import accepts only one parser selector');
  }
  if (input.parserProvider) return input.parserProvider;
  if (input.parser === 'mineru') return 'mineru_local_http';
  return input.parser;
}

const KNOWLEDGE_ASSET_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/bmp',
]);
const MAX_KNOWLEDGE_ASSET_BYTES = 25 * 1024 * 1024;
const KNOWLEDGE_SOURCE_MIME_TYPES = new Set([
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/bmp',
  'image/tiff',
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/json',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]);
const MAX_KNOWLEDGE_SOURCE_BYTES = 50 * 1024 * 1024;

function assertKnowledgeAssetReadInput(input: KnowledgeAssetReadInput): void {
  if (!isRecord(input) || Object.keys(input).some((key) => !['kbId', 'fileId', 'assetId', 'signal'].includes(key))) {
    throw new TypeError('Knowledge asset read input contained an unsupported field');
  }
  if (!isSafeKnowledgeId(input.kbId) || !isSafeKnowledgeId(input.fileId)) {
    throw new TypeError('Knowledge asset read requires bounded kbId and fileId values');
  }
  if (!/^[a-f0-9]{64}$/.test(input.assetId)) {
    throw new TypeError('Knowledge asset read requires a sha256 assetId');
  }
}

function assertKnowledgeDocumentSourceReadInput(input: KnowledgeDocumentSourceReadInput): void {
  if (!isRecord(input) || Object.keys(input).some((key) => !['kbId', 'fileId', 'signal'].includes(key))) {
    throw new TypeError('Knowledge document source input contained an unsupported field');
  }
  if (!isSafeKnowledgeId(input.kbId) || !isSafeKnowledgeId(input.fileId)) {
    throw new TypeError('Knowledge document source requires bounded kbId and fileId values');
  }
}

function isSafeKnowledgeId(value: string): boolean {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$/.test(value);
}

function normalizedEntityTag(value: string | null): string {
  return (value ?? '').trim().replace(/^W\//, '').replace(/^"|"$/g, '').toLowerCase();
}

async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
}

function parseKnowledgeDocumentImportResponse(
  payload: unknown,
  kbId: string,
  file: File,
): KnowledgeDocumentImportReceipt {
  if (
    !isRecord(payload) ||
    payload.schemaVersion !== 'rag-ime.knowledge-document-import.v1' ||
    payload.ok !== true ||
    !isRecord(payload.receipt)
  ) {
    throw new TypeError('Knowledge document import returned an invalid envelope');
  }
  const receipt = payload.receipt;
  if (
    receipt.kbId !== kbId ||
    typeof receipt.documentId !== 'string' ||
    !/^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$/.test(receipt.documentId) ||
    receipt.fileName !== file.name ||
    typeof receipt.mimeType !== 'string' ||
    receipt.byteSize !== file.size ||
    typeof receipt.sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/.test(receipt.sha256) ||
    typeof receipt.status !== 'string' ||
    receipt.status.length === 0
  ) {
    throw new TypeError('Knowledge document import returned an invalid receipt');
  }
  return receipt as unknown as KnowledgeDocumentImportReceipt;
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
