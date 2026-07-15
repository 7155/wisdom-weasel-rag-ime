import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type {
  ControlTransport,
  JsonValue,
  KnowledgeDocumentImportInput,
  KnowledgeDocumentImportReceipt,
} from '@/platform/transport';

export type KnowledgeParserMode = 'auto' | 'builtin' | 'mineru';
export type KnowledgeDocumentStatus = 'queued' | 'parsing' | 'indexing' | 'ready' | 'failed' | 'stale';

export interface DocumentKnowledgeBase {
  id: string;
  name: string;
  description: string;
  documentCount: number;
  chunkCount: number;
  status: string;
  agentEnabled: boolean;
  parser: KnowledgeParserMode;
  updatedAtMs: number;
  revision: JsonValue;
  chunkingConfig: KnowledgeChunkingConfig;
  retrievalConfig: KnowledgeRetrievalConfig;
}

export interface KnowledgeChunkingConfig {
  strategy: 'general' | 'markdown' | 'book' | 'qa' | 'laws' | 'separator' | 'fixed';
  size: number;
  overlap: number;
  separator: string;
  respectHeadings: boolean;
  respectPageBoundaries: boolean;
}

export interface KnowledgeRetrievalConfig {
  mode: 'hybrid' | 'dense' | 'lexical';
  topK: number;
  threshold: number;
  lexicalWeight: number;
  denseWeight: number;
  rrfK: number;
  candidateMultiplier: number;
}

export interface KnowledgeDocument {
  id: string;
  baseId: string;
  name: string;
  mimeType: string;
  byteSize: number;
  status: KnowledgeDocumentStatus;
  stage: string;
  progress: number;
  error: string;
  chunkCount: number;
  parser: string;
  updatedAtMs: number;
  revision: JsonValue;
  sha256: string;
  pageCount: number;
  tokenCount: number;
  parserVersion: string;
  sourceReadPath: string;
  indexedConfigRevision: number;
}

export interface KnowledgeChunk {
  id: string;
  ordinal: number;
  content: string;
  page: number | null;
  heading: string;
  lineStart: number | null;
  lineEnd: number | null;
  tokenCount: number;
}

export interface KnowledgePageSummary {
  page: number;
  chunkCount: number;
}

export interface KnowledgeAsset {
  id: string;
  name: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  readPath: string;
  page: number | null;
  caption: string;
}

export interface KnowledgeTableArtifact {
  id: string;
  title: string;
  page: number | null;
  columns: string[];
  rows: string[][];
  markdown: string;
}

export interface KnowledgeDocumentDetail {
  document: KnowledgeDocument;
  chunks: KnowledgeChunk[];
  chunkTotal: number;
  chunkHasMore: boolean;
  pages: KnowledgePageSummary[];
  assets: KnowledgeAsset[];
  tables: KnowledgeTableArtifact[];
  artifact: {
    available: boolean;
    format: string;
    mimeType: string;
    byteSize: number;
    lineCount: number;
    sha256: string;
  };
  contentWindow: { lineNumber: number; content: string }[];
  contentLineTotal: number;
  contentHasMore: boolean;
}

export interface KnowledgeIndexJob {
  id: string;
  baseId: string;
  documentId: string;
  documentName: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  error: string;
  createdAtMs: number;
  startedAtMs: number;
  finishedAtMs: number;
  updatedAtMs: number;
  revision: number;
  errorCode: string;
  parserMode: KnowledgeParserMode;
  cancellable: boolean;
}

export interface KnowledgeChunkPreview {
  documentId: string;
  total: number;
  truncated: boolean;
  chunks: KnowledgeChunk[];
}

export interface KnowledgeIndexRuntimeStatus {
  available: boolean;
  degraded: boolean;
  kind: string;
  fingerprint: string;
  provider: string;
  model: string;
  dimensions: number | null;
  vectorCount: number | null;
  reason: string;
}

export interface KnowledgeReindexPreview {
  previewToken: string;
  payloadSha256: string;
  expectedRevision: JsonValue;
  documentCount: number;
  staleDocumentCount: number;
  estimatedChunkCount: number;
}

export interface KnowledgeSearchHit {
  id: string;
  documentId: string;
  documentName: string;
  title: string;
  excerpt: string;
  score: number | null;
  page: number | null;
  heading: string;
  lineStart: number | null;
  lineEnd: number | null;
}

export const knowledgeLibraryKeys = {
  root: ['knowledge-library'] as const,
  bases: () => [...knowledgeLibraryKeys.root, 'bases'] as const,
  base: (baseId: string) => [...knowledgeLibraryKeys.root, 'base', baseId] as const,
  documents: (baseId: string) => [...knowledgeLibraryKeys.root, 'documents', baseId] as const,
  jobs: (baseId: string) => [...knowledgeLibraryKeys.root, 'jobs', baseId] as const,
  documentDetail: (baseId: string, documentId: string) => [...knowledgeLibraryKeys.root, 'document-detail', baseId, documentId] as const,
  documentContent: (baseId: string, documentId: string) => [...knowledgeLibraryKeys.root, 'document-content', baseId, documentId] as const,
  worker: () => [...knowledgeLibraryKeys.root, 'worker'] as const,
  parsers: () => [...knowledgeLibraryKeys.root, 'parsers'] as const,
};

export function useKnowledgeLibraryQueries(baseId: string) {
  const transport = useControlTransport();
  const bases = useQuery({
    queryKey: knowledgeLibraryKeys.bases(),
    queryFn: async ({ signal }) => normalizeBases(await transport.request({
      pathId: 'knowledgeBases.list',
      signal,
    })),
    staleTime: 10_000,
  });
  const base = useQuery({
    queryKey: knowledgeLibraryKeys.base(baseId),
    enabled: Boolean(baseId),
    queryFn: async ({ signal }) => normalizeBaseEnvelope(await transport.request({
      pathId: 'knowledgeBases.get',
      params: { kbId: baseId },
      signal,
    })),
    staleTime: 10_000,
  });
  const documents = useQuery({
    queryKey: knowledgeLibraryKeys.documents(baseId),
    enabled: Boolean(baseId),
    queryFn: async ({ signal }) => normalizeDocuments(await transport.request({
      pathId: 'knowledgeBases.documents.list',
      params: { kbId: baseId },
      signal,
    }), baseId),
    refetchInterval: (query) => {
      const rows = (query.state.data ?? []) as KnowledgeDocument[];
      return rows.some((row) => ['queued', 'parsing', 'indexing'].includes(row.status)) ? 1_500 : false;
    },
  });
  const jobs = useQuery({
    queryKey: knowledgeLibraryKeys.jobs(baseId),
    enabled: Boolean(baseId),
    queryFn: async ({ signal }) => normalizeJobs(await transport.request({
      pathId: 'knowledgeBases.jobs.list',
      params: { kbId: baseId },
      signal,
    }), baseId),
    staleTime: 2_000,
    refetchInterval: (query) => {
      const rows = (query.state.data ?? []) as KnowledgeIndexJob[];
      return rows.some((row) => isActiveJobStatus(row.status)) ? 1_500 : 15_000;
    },
  });
  const worker = useQuery({
    queryKey: knowledgeLibraryKeys.worker(),
    queryFn: ({ signal }) => transport.request({ pathId: 'knowledgeWorker.health', signal }),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const parsers = useQuery({
    queryKey: knowledgeLibraryKeys.parsers(),
    queryFn: ({ signal }) => transport.request({ pathId: 'knowledgeParsers.list', signal }),
    staleTime: 30_000,
  });
  return { base, bases, documents, jobs, parsers, transport, worker };
}

export function useKnowledgeDocumentDetail(baseId: string, documentId: string, enabled = true) {
  const transport = useControlTransport();
  const chunksQuery = useInfiniteQuery({
    queryKey: knowledgeLibraryKeys.documentDetail(baseId, documentId),
    enabled: enabled && Boolean(baseId && documentId),
    initialPageParam: 0,
    queryFn: async ({ pageParam, signal }) => normalizeDocumentDetail(await transport.request({
      pathId: 'knowledgeBases.document.get',
      params: { kbId: baseId, fileId: documentId },
      query: { offset: pageParam, limit: 200, lineOffset: 0, lineLimit: 1 },
      signal,
    }), baseId, documentId),
    getNextPageParam: (lastPage, pages) => lastPage.chunkHasMore
      ? pages.reduce((count, page) => count + page.chunks.length, 0)
      : undefined,
    staleTime: 10_000,
  });
  const contentQuery = useInfiniteQuery({
    queryKey: knowledgeLibraryKeys.documentContent(baseId, documentId),
    enabled: enabled && Boolean(baseId && documentId),
    initialPageParam: 0,
    queryFn: async ({ pageParam, signal }) => normalizeDocumentDetail(await transport.request({
      pathId: 'knowledgeBases.document.get',
      params: { kbId: baseId, fileId: documentId },
      query: { offset: 0, limit: 1, lineOffset: pageParam, lineLimit: 200 },
      signal,
    }), baseId, documentId),
    getNextPageParam: (lastPage, pages) => lastPage.contentHasMore
      ? pages.reduce((count, page) => count + page.contentWindow.length, 0)
      : undefined,
    staleTime: 10_000,
  });
  const chunkDetail = chunksQuery.data ? mergeDocumentDetailPages(chunksQuery.data.pages) : undefined;
  return {
    ...chunksQuery,
    data: chunkDetail && contentQuery.data ? mergeDocumentContentPages(chunkDetail, contentQuery.data.pages) : chunkDetail,
    error: chunksQuery.error ?? contentQuery.error,
    isPending: chunksQuery.isPending || contentQuery.isPending,
    fetchNextContentPage: contentQuery.fetchNextPage,
    hasNextContentPage: contentQuery.hasNextPage,
    isFetchingNextContentPage: contentQuery.isFetchingNextPage,
  };
}

export async function createKnowledgeBase(
  transport: ControlTransport,
  input: { name: string; description: string },
): Promise<DocumentKnowledgeBase> {
  return normalizeBaseEnvelope(await transport.request({
    pathId: 'knowledgeBases.create',
    body: { ...input, agentEnabled: false, parserProvider: 'auto' },
  }));
}

export async function updateKnowledgeBase(
  transport: ControlTransport,
  base: DocumentKnowledgeBase,
  patch: {
    name?: string;
    description?: string;
    agentEnabled?: boolean;
    parser?: KnowledgeParserMode;
    chunkingConfig?: KnowledgeChunkingConfig;
    retrievalConfig?: KnowledgeRetrievalConfig;
  },
): Promise<DocumentKnowledgeBase> {
  return normalizeBaseEnvelope(await transport.request({
    pathId: 'knowledgeBases.update',
    params: { kbId: base.id },
    body: jsonRecord({
      ...patch,
      ...(patch.parser ? { parserProvider: parserProvider(patch.parser), parser: undefined } : {}),
      expectedRevision: base.revision,
    }),
  }));
}

export async function deleteKnowledgeBase(transport: ControlTransport, base: DocumentKnowledgeBase): Promise<void> {
  const preview = record(await transport.request({
    pathId: 'knowledgeBases.delete.preview',
    params: { kbId: base.id },
    body: { expectedRevision: base.revision },
  }));
  await transport.request({
    pathId: 'knowledgeBases.delete.apply',
    params: { kbId: base.id },
    body: jsonRecord({
      confirmText: 'delete',
      previewToken: text(preview.previewToken),
      payloadSha256: text(preview.payloadSha256),
      expectedRevision: preview.expectedRevision ?? base.revision,
    }),
  });
}

export async function importKnowledgeDocuments(
  transport: ControlTransport,
  options: KnowledgeDocumentImportInput,
): Promise<KnowledgeDocumentImportReceipt[]> {
  const importer = transport.importKnowledgeDocuments;
  if (!importer) throw new Error('当前控制通道不支持文档导入。');
  return importer.call(transport, options);
}

export async function retryKnowledgeDocument(
  transport: ControlTransport,
  base: DocumentKnowledgeBase,
  document: KnowledgeDocument,
  options: { parser?: KnowledgeParserMode; stage?: 'parse' | 'index' } = {},
): Promise<void> {
  await transport.request({
    pathId: 'knowledgeBases.document.retry',
    params: { kbId: base.id, fileId: document.id },
    body: {
      stage: options.stage ?? 'parse',
      ...(options.parser ? { parserProvider: parserProvider(options.parser) } : {}),
      expectedRevision: document.revision,
    },
  });
}

export async function previewKnowledgeReindex(
  transport: ControlTransport,
  base: DocumentKnowledgeBase,
): Promise<KnowledgeReindexPreview> {
  const payload = record(await transport.request({
    pathId: 'knowledgeBases.reindexPreview',
    params: { kbId: base.id },
  }));
  const summary = record(payload.summary);
  return {
    previewToken: text(payload.previewToken),
    payloadSha256: text(payload.payloadSha256),
    expectedRevision: jsonValue(payload.expectedRevision ?? base.revision),
    documentCount: number(summary.documentCount ?? payload.documentCount),
    staleDocumentCount: number(summary.staleDocumentCount ?? payload.staleDocumentCount),
    estimatedChunkCount: number(summary.estimatedChunkCount ?? payload.estimatedChunkCount),
  };
}

export async function rebuildKnowledgeBase(
  transport: ControlTransport,
  base: DocumentKnowledgeBase,
  preview: KnowledgeReindexPreview,
): Promise<void> {
  await transport.request({
    pathId: 'knowledgeBases.rebuild',
    params: { kbId: base.id },
    body: {
      previewToken: preview.previewToken,
      payloadSha256: preview.payloadSha256,
      expectedRevision: preview.expectedRevision,
      confirmText: 'REBUILD',
    },
  });
}

export async function cancelKnowledgeJob(
  transport: ControlTransport,
  baseId: string,
  jobId: string,
): Promise<void> {
  await transport.request({
    pathId: 'knowledgeBases.job.cancel',
    params: { kbId: baseId, jobId },
    body: {},
  });
}

export async function previewKnowledgeChunking(
  transport: ControlTransport,
  baseId: string,
  documentId: string,
  chunkingConfig: KnowledgeChunkingConfig,
): Promise<KnowledgeChunkPreview> {
  const payload = record(await transport.request({
    pathId: 'knowledgeBases.chunkPreview',
    params: { kbId: baseId, fileId: documentId },
    body: { chunkingConfig: jsonRecord({ ...chunkingConfig }), limit: 12 },
  }));
  const chunks = list(payload.items).map((item, index) => {
    const row = record(item);
    return {
      id: text(row.chunkId, text(row.id, `preview-${index + 1}`)),
      ordinal: number(row.ordinal ?? index),
      content: text(row.content),
      page: nullableNumber(row.page),
      heading: text(row.heading),
      lineStart: null,
      lineEnd: null,
      tokenCount: number(row.tokenCount),
    } satisfies KnowledgeChunk;
  });
  return {
    documentId,
    total: number(payload.total),
    truncated: bool(payload.truncated),
    chunks,
  };
}

export async function deleteKnowledgeDocument(
  transport: ControlTransport,
  baseId: string,
  documentId: string,
): Promise<void> {
  await transport.request({
    pathId: 'knowledgeBases.document.delete',
    params: { kbId: baseId, fileId: documentId },
  });
}

export async function searchKnowledgeBase(
  transport: ControlTransport,
  baseId: string,
  query: string,
  config: KnowledgeRetrievalConfig,
): Promise<KnowledgeSearchHit[]> {
  return normalizeSearchHits(await transport.request({
    pathId: 'knowledgeBases.search',
    params: { kbId: baseId },
    body: { query, topK: config.topK, mode: config.mode, threshold: config.threshold },
  }));
}

export async function openKnowledgeHit(
  transport: ControlTransport,
  baseId: string,
  hit: KnowledgeSearchHit,
): Promise<void> {
  await transport.request({
    pathId: 'knowledgeBases.open',
    params: { kbId: baseId, fileId: hit.documentId },
    query: {
      chunkId: hit.id,
      ...(hit.page !== null ? { page: hit.page } : {}),
      ...(hit.lineStart !== null ? { startLine: hit.lineStart } : {}),
      lines: 80,
    },
  });
}

export function chooseKnowledgeFiles(maxFiles = 20): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.htm,.png,.jpg,.jpeg,.webp';
    input.addEventListener('change', () => resolve([...(input.files ?? [])].slice(0, maxFiles)), { once: true });
    input.addEventListener('cancel', () => resolve([]), { once: true });
    input.click();
  });
}

function normalizeBases(value: unknown): DocumentKnowledgeBase[] {
  const payload = record(value);
  const rows = Array.isArray(value) ? value : list(payload.items ?? payload.bases ?? payload.knowledgeBases);
  return rows.map(normalizeBase).filter((row) => Boolean(row.id));
}

function normalizeBaseEnvelope(value: unknown): DocumentKnowledgeBase {
  const payload = record(value);
  return normalizeBase(record(payload.base ?? payload.knowledgeBase ?? value));
}

function normalizeBase(value: unknown): DocumentKnowledgeBase {
  const row = record(value);
  const parser = text(row.parser, text(row.parserMode, text(record(row.settings).parser, 'auto')));
  return {
    id: text(row.id, text(row.baseId)),
    name: text(row.name, '未命名知识库'),
    description: text(row.description),
    documentCount: number(row.documentCount ?? row.documentsCount),
    chunkCount: number(row.chunkCount),
    status: text(row.status, 'ready'),
    agentEnabled: bool(row.agentEnabled ?? row.agent_enabled),
    parser: parserMode(parser),
    updatedAtMs: number(row.updatedAtMs ?? row.updated_at_ms),
    revision: jsonValue(row.revision ?? row.updatedAtMs ?? row.updated_at_ms ?? 0),
    chunkingConfig: normalizeChunkingConfig(row.chunkingConfig ?? row.chunking_config),
    retrievalConfig: normalizeRetrievalConfig(row.retrievalConfig ?? row.retrieval_config),
  };
}

function normalizeDocuments(value: unknown, baseId: string): KnowledgeDocument[] {
  const payload = record(value);
  return list(payload.items ?? payload.documents ?? value).map((item) => {
    const row = record(item);
    const rawStatus = text(row.status, 'queued');
    return {
      id: text(row.id, text(row.documentId)),
      baseId: text(row.baseId, baseId),
      name: text(row.name, text(row.fileName, '未命名文档')),
      mimeType: text(row.mimeType),
      byteSize: number(row.byteSize ?? row.size),
      status: documentStatus(rawStatus),
      stage: text(row.stage, rawStatus),
      progress: Math.max(0, Math.min(1, number(row.progress))),
      error: text(row.error, text(row.errorMessage)),
      chunkCount: number(row.chunkCount),
      parser: text(row.parser, text(row.parserProvider)),
      updatedAtMs: number(row.updatedAtMs ?? row.updated_at_ms),
      revision: jsonValue(row.revision ?? row.updatedAtMs ?? row.updated_at_ms ?? 0),
      sha256: text(row.sha256),
      pageCount: number(row.pageCount ?? row.pages),
      tokenCount: number(row.tokenCount ?? row.tokens),
      parserVersion: text(row.parserVersion ?? row.parser_version),
      sourceReadPath: safeSourcePath(text(row.sourceReadPath)),
      indexedConfigRevision: number(row.indexedConfigRevision ?? row.indexed_config_revision),
    };
  }).filter((row) => Boolean(row.id));
}

function normalizeDocumentDetail(value: unknown, baseId: string, documentId: string): KnowledgeDocumentDetail {
  const payload = record(value);
  const envelope = record(payload.detail ?? value);
  const documentPayload = record(envelope.document);
  const fallbackDocument = normalizeDocuments({ items: [{
    ...documentPayload,
    id: documentPayload.id ?? documentPayload.documentId ?? documentId,
    baseId: documentPayload.baseId ?? baseId,
    name: documentPayload.name ?? documentPayload.fileName ?? envelope.documentName,
    status: documentPayload.status ?? 'ready',
  }] }, baseId)[0] ?? emptyDocument(baseId, documentId);
  const chunksPayload = record(envelope.chunks);
  const chunkRows = Array.isArray(envelope.chunks) ? envelope.chunks : list(chunksPayload.items);
  const chunks = chunkRows.map((item, index) => {
    const row = record(item);
    return {
      id: text(row.chunkId, text(row.id, `chunk-${index + 1}`)),
      ordinal: number(row.ordinal ?? row.chunkOrder ?? row.chunk_order_index ?? index),
      content: text(row.content, text(row.text)),
      page: nullableNumber(row.page),
      heading: text(row.heading),
      lineStart: nullableNumber(row.lineStart ?? row.startLine),
      lineEnd: nullableNumber(row.lineEnd ?? row.endLine),
      tokenCount: number(row.tokenCount ?? row.tokens),
    } satisfies KnowledgeChunk;
  });
  return {
    document: fallbackDocument,
    chunks,
    chunkTotal: number(chunksPayload.total) || chunks.length,
    chunkHasMore: bool(chunksPayload.hasMore),
    pages: list(envelope.pages).map((item) => {
      const row = record(item);
      return { page: number(row.page), chunkCount: number(row.chunkCount) };
    }).filter((item) => item.page > 0),
    assets: list(envelope.assets).map((item, index) => {
      const row = record(item);
      return {
        id: text(row.assetId, text(row.id, `asset-${index + 1}`)),
        name: text(row.name, '解析产物'),
        mimeType: text(row.mimeType),
        byteSize: number(row.byteSize),
        sha256: text(row.sha256),
        readPath: safeAssetPath(text(row.readPath)),
        page: nullableNumber(row.page),
        caption: text(row.caption),
      } satisfies KnowledgeAsset;
    }),
    tables: list(envelope.tables).map((item, index) => {
      const row = record(item);
      return {
        id: text(row.tableId, text(row.id, `table-${index + 1}`)),
        title: text(row.title, `表格 ${index + 1}`),
        page: nullableNumber(row.page),
        columns: stringList(row.columns, 64),
        rows: list(row.rows).map((cells) => stringList(cells, 64)).slice(0, 500),
        markdown: text(row.markdown),
      } satisfies KnowledgeTableArtifact;
    }),
    artifact: normalizeArtifact(envelope.artifact),
    contentWindow: list(record(envelope.contentWindow).items ?? envelope.contentWindow).map((item, index) => {
      const row = record(item);
      return { lineNumber: number(row.lineNumber) || index + 1, content: text(row.content) };
    }),
    contentLineTotal: number(record(envelope.contentWindow).total) || number(record(envelope.artifact).lineCount),
    contentHasMore: bool(record(envelope.contentWindow).hasMore),
  };
}

function normalizeJobs(value: unknown, baseId: string): KnowledgeIndexJob[] {
  const payload = record(value);
  return list(payload.items ?? payload.jobs ?? value).map((item, index) => {
    const row = record(item);
    const nestedError = record(row.error);
    return {
      id: text(row.id, text(row.jobId, `job-${index + 1}`)),
      baseId: text(row.baseId, baseId),
      documentId: text(row.documentId, text(row.fileId)),
      documentName: text(row.documentName, text(row.fileName)),
      kind: text(row.kind, text(row.type, 'index')),
      status: text(row.status, 'queued'),
      stage: text(row.stage, text(row.status, 'queued')),
      progress: Math.max(0, Math.min(1, number(row.progress))),
      error: text(row.errorMessage, text(nestedError.message)),
      createdAtMs: number(row.createdAtMs ?? row.created_at_ms),
      startedAtMs: number(row.startedAtMs ?? row.started_at_ms),
      finishedAtMs: number(row.finishedAtMs ?? row.finished_at_ms),
      updatedAtMs: number(row.updatedAtMs ?? row.updated_at_ms),
      revision: number(row.revision),
      errorCode: text(row.errorCode, text(nestedError.code)),
      parserMode: parserMode(text(row.parserMode, 'auto')),
      cancellable: bool(row.cancellable) || isActiveJobStatus(text(row.status)),
    };
  });
}

function normalizeChunkingConfig(value: unknown): KnowledgeChunkingConfig {
  const row = record(value);
  const rawStrategy = text(row.strategy, 'markdown');
  const strategy = rawStrategy === 'paragraph' ? 'general' : rawStrategy;
  return {
    strategy: ['general', 'markdown', 'book', 'qa', 'laws', 'separator', 'fixed'].includes(strategy)
      ? strategy as KnowledgeChunkingConfig['strategy']
      : 'markdown',
    size: boundedNumber(row.size, 200, 8_000, 1_200),
    overlap: boundedNumber(row.overlap, 0, 2_000, 160),
    separator: text(row.separator, '\n\n'),
    respectHeadings: row.respectHeadings !== false,
    respectPageBoundaries: row.respectPageBoundaries !== false,
  };
}

function normalizeRetrievalConfig(value: unknown): KnowledgeRetrievalConfig {
  const row = record(value);
  const mode = text(row.mode, 'hybrid');
  return {
    mode: mode === 'dense' || mode === 'lexical' ? mode : 'hybrid',
    topK: boundedNumber(row.topK ?? row.top_k, 1, 100, 10),
    threshold: boundedNumber(row.threshold, 0, 1, 0),
    lexicalWeight: boundedNumber(row.lexicalWeight ?? row.lexical_weight, 0, 10, 1),
    denseWeight: boundedNumber(row.denseWeight ?? row.dense_weight, 0, 10, 1),
    rrfK: boundedNumber(row.rrfK ?? row.rrf_k, 1, 1_000, 60),
    candidateMultiplier: boundedNumber(row.candidateMultiplier ?? row.candidate_multiplier, 1, 20, 4),
  };
}

function emptyDocument(baseId: string, documentId: string): KnowledgeDocument {
  return {
    id: documentId, baseId, name: '未命名文档', mimeType: '', byteSize: 0, status: 'ready', stage: 'ready',
    progress: 1, error: '', chunkCount: 0, parser: '', updatedAtMs: 0, revision: 0, sha256: '', pageCount: 0,
    tokenCount: 0, parserVersion: '', sourceReadPath: '', indexedConfigRevision: 0,
  };
}

function mergeDocumentDetailPages(pages: KnowledgeDocumentDetail[]): KnowledgeDocumentDetail {
  const first = pages[0];
  if (!first) throw new Error('文档详情为空。');
  const chunks = pages.flatMap((page) => page.chunks);
  const last = pages.at(-1) ?? first;
  return { ...first, chunks, chunkHasMore: last.chunkHasMore };
}

function mergeDocumentContentPages(detail: KnowledgeDocumentDetail, pages: KnowledgeDocumentDetail[]): KnowledgeDocumentDetail {
  const contentWindow = pages.flatMap((page) => page.contentWindow);
  const last = pages.at(-1);
  return {
    ...detail,
    contentWindow,
    contentLineTotal: pages[0]?.contentLineTotal || detail.contentLineTotal,
    contentHasMore: last?.contentHasMore ?? false,
  };
}

function isActiveJobStatus(value: string): boolean {
  return ['queued', 'running', 'parsing', 'embedding', 'indexing'].includes(value.toLowerCase());
}

export function knowledgeIndexRuntimeStatus(value: unknown): KnowledgeIndexRuntimeStatus {
  const root = record(value);
  const components = record(root.components);
  const providerRoot = record(root.provider);
  const denseContainer = firstRecord(root.dense, components.dense, providerRoot.dense, root.embedding, components.embedding);
  const dense = { ...denseContainer, ...record(denseContainer.provider) };
  const fingerprint = text(dense.fingerprint);
  const parts = fingerprint.split(':');
  const dimensions = number(dense.dimensions ?? dense.dimension) || parts.map((part) => Number(part)).find((part) => Number.isInteger(part) && part > 0) || null;
  return {
    available: dense.available === true,
    degraded: dense.degraded === true,
    kind: text(dense.kind, '未报告'),
    fingerprint,
    provider: text(dense.providerName, text(dense.kind, parts[0] || '未报告')),
    model: text(dense.model, parts.length > 2 ? parts.slice(1).filter((part) => !/^\d+$/u.test(part)).join(':') || '内置' : parts[1] || '未报告'),
    dimensions,
    vectorCount: typeof dense.vectorCount === 'number' && Number.isFinite(dense.vectorCount) ? dense.vectorCount : null,
    reason: text(dense.reason),
  };
}

function firstRecord(...values: unknown[]): Record<string, unknown> {
  return values.map(record).find((value) => Object.keys(value).length > 0) ?? {};
}

function normalizeSearchHits(value: unknown): KnowledgeSearchHit[] {
  const payload = record(value);
  return list(payload.items ?? payload.hits ?? payload.results ?? value).map((item, index) => {
    const row = record(item);
    const citation = record(row.citation ?? row.provenance);
    const score = row.score;
    return {
      id: text(row.id, text(row.chunkId, `hit-${index + 1}`)),
      documentId: text(row.documentId, text(citation.documentId)),
      documentName: text(row.documentName, text(citation.documentName, '未命名文档')),
      title: text(row.title, text(row.heading, '文档片段')),
      excerpt: text(row.excerpt, text(row.text, text(row.content))),
      score: typeof score === 'number' && Number.isFinite(score) ? score : null,
      page: nullableNumber(row.page ?? citation.page),
      heading: text(row.heading, text(citation.heading)),
      lineStart: nullableNumber(row.lineStart ?? citation.lineStart),
      lineEnd: nullableNumber(row.lineEnd ?? citation.lineEnd),
    };
  });
}

function documentStatus(value: string): KnowledgeDocumentStatus {
  return ['queued', 'parsing', 'indexing', 'ready', 'failed', 'stale'].includes(value)
    ? value as KnowledgeDocumentStatus
    : value === 'error' ? 'failed' : 'queued';
}

function parserMode(value: string): KnowledgeParserMode {
  return value === 'builtin' ? value : value === 'mineru' || value === 'mineru_local_http' ? 'mineru' : 'auto';
}

function parserProvider(value: KnowledgeParserMode): 'auto' | 'builtin' | 'mineru_local_http' {
  return value === 'mineru' ? 'mineru_local_http' : value;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function boundedNumber(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? Math.max(min, Math.min(max, parsed)) : fallback;
}

function stringList(value: unknown, limit: number): string[] {
  return Array.isArray(value)
    ? value.flatMap((item) => typeof item === 'string' ? [item.slice(0, 2_000)] : []).slice(0, limit)
    : [];
}

function safeAssetPath(value: string): string {
  if (/^\/api\/knowledge-bases\/[A-Za-z0-9._:-]+\/documents\/[A-Za-z0-9._:-]+\/assets\/[a-f0-9]{64}$/u.test(value)) return value;
  if (/^\/v1\/knowledge\/assets\/[A-Za-z0-9._-]+$/u.test(value)) return value;
  if (/^(?:blob:|data:image\/(?:png|jpeg|webp|gif);base64,)/iu.test(value)) return value;
  return '';
}

function safeSourcePath(value: string): string {
  return /^\/api\/knowledge-bases\/[A-Za-z0-9._:-]+\/documents\/[A-Za-z0-9._:-]+\/source$/u.test(value) ? value : '';
}

function normalizeArtifact(value: unknown): KnowledgeDocumentDetail['artifact'] {
  const row = record(value);
  return {
    available: bool(row.available),
    format: text(row.format),
    mimeType: text(row.mimeType),
    byteSize: number(row.byteSize),
    lineCount: number(row.lineCount),
    sha256: text(row.sha256),
  };
}

function bool(value: unknown): boolean {
  return value === true || value === 1;
}

function jsonRecord(value: Record<string, unknown>): Record<string, JsonValue> {
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, JsonValue] => isJson(entry[1])));
}

function isJson(value: unknown): value is JsonValue {
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return true;
  if (Array.isArray(value)) return value.every(isJson);
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).every(isJson);
  return false;
}

function jsonValue(value: unknown): JsonValue {
  return isJson(value) ? value : 0;
}
